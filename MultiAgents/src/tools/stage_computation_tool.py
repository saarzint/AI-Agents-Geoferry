"""
Tool for computing the current stage of a user's admissions journey.
Determines which stage the user is in based on their profile completeness
and progress through the admissions process.
"""

import os
from typing import Optional, Dict, Any
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field
import sys
import json

# Add the app directory to the Python path to import supabase_client
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'app'))

import logging
logger = logging.getLogger(__name__)

try:
    from supabase_client import get_supabase
except ImportError:
    print("Warning: Could not import supabase_client. Make sure the app module is in the Python path.")
    logger.warning("Could not import supabase_client. Make sure the app module is in the Python path.")
    get_supabase = None

from datetime import datetime, timedelta


class StageComputationInput(BaseModel):
    """Input schema for Stage Computation Tool"""
    
    user_id: int = Field(..., description="User ID to compute stage for")


class StageComputationTool(BaseTool):
    name: str = "Stage Computation Tool"
    description: str = (
        "Determines the current stage of a user's admissions journey based on their profile completeness "
        "and progress. Returns the stage name and description. Use this tool to understand where the user "
        "is in their admissions process."
    )
    args_schema: type[BaseModel] = StageComputationInput
    
    def _run(self, **kwargs) -> str:
        """Compute the current stage for a user"""
        user_id = kwargs.get("user_id")
        
        if not user_id:
            return json.dumps({"error": "user_id is required"})
        
        if get_supabase is None:
            return json.dumps({"error": "Supabase client not available"})
        
        try:
            supabase = get_supabase()
            
            # Get profile data
            profile_resp = supabase.table("user_profile").select(
                "full_name,gpa,intended_major,budget,citizenship_country,destination_country,test_scores,academic_background,preferences,university_interests"
            ).eq("id", user_id).execute()
            
            # Get counts of various data
            universities_resp = supabase.table("university_results").select("id").eq("user_profile_id", user_id).execute()
            scholarships_resp = supabase.table("scholarship_results").select("id").eq("user_profile_id", user_id).gte("deadline", datetime.now().date().isoformat()).execute()
            app_reqs_resp = supabase.table("application_requirements").select("id").eq("user_profile_id", user_id).execute()
            visa_resp = supabase.table("visa_requirements").select("id").eq("user_profile_id", user_id).execute()
            
            # Check profile completeness and capture missing fields
            profile_complete = False
            missing_fields: list[str] = []
            if profile_resp.data:
                prof = profile_resp.data[0]
                critical_field_keys = [
                    "full_name",
                    "gpa",
                    "intended_major",
                    "budget",
                    "citizenship_country",
                    "destination_country",
                    "preferences",
                    "university_interests",
                    "test_scores",
                    "academic_background",
                ]
                friendly_names = {
                    "full_name": "Full name",
                    "gpa": "GPA",
                    "intended_major": "Intended major",
                    "budget": "Budget",
                    "citizenship_country": "Citizenship country",
                    "destination_country": "Destination country",
                    "preferences": "Preferences",
                    "university_interests": "University interests",
                    "test_scores": "Test scores",
                    "academic_background": "Academic background",
                }
                def _is_missing(value: Any) -> bool:
                    return value is None or (isinstance(value, str) and str(value).strip() == "")
                missing_fields = [
                    friendly_names.get(key, key)
                    for key in critical_field_keys
                    if _is_missing(prof.get(key))
                ]
                profile_complete = len(missing_fields) == 0
            
            universities_count = len(universities_resp.data) if universities_resp.data else 0
            scholarships_count = len(scholarships_resp.data) if scholarships_resp.data else 0
            app_reqs_count = len(app_reqs_resp.data) if app_reqs_resp.data else 0
            visa_count = len(visa_resp.data) if visa_resp.data else 0
            
            # Check for approaching deadlines (within 45 days)
            approaching_deadlines = 0
            today = datetime.now().date()
            
            # Check scholarship deadlines
            for schol in (scholarships_resp.data or []):
                deadline = schol.get('deadline')
                if deadline:
                    try:
                        deadline_date = datetime.fromisoformat(str(deadline)).date()
                        days_left = (deadline_date - today).days
                        if 0 <= days_left <= 45:
                            approaching_deadlines += 1
                    except:
                        pass
            
            # Check application deadlines
            for req in (app_reqs_resp.data or []):
                deadlines = req.get('deadlines', {})
                if isinstance(deadlines, dict):
                    for deadline_value in deadlines.values():
                        if deadline_value and deadline_value not in [None, "None", "", False]:
                            try:
                                deadline_date = datetime.fromisoformat(str(deadline_value)).date()
                                days_left = (deadline_date - today).days
                                if 0 <= days_left <= 45:
                                    approaching_deadlines += 1
                                    break  # Count once per application requirement
                            except:
                                pass
            
            # Determine stage based on logic
            stage = self._compute_stage(
                profile_complete=profile_complete,
                universities_count=universities_count,
                app_reqs_count=app_reqs_count,
                approaching_deadlines=approaching_deadlines,
                scholarships_count=scholarships_count,
                visa_count=visa_count,
                missing_fields=missing_fields
            )
            
            return json.dumps({
                "current_stage": stage["name"],
                "stage_number": stage["number"],
                "stage_description": stage["description"],
                "reasoning": stage["reasoning"]
            }, indent=2)
            
        except Exception as e:
            return json.dumps({"error": f"Error computing stage: {str(e)}"})
    
    def _compute_stage(
        self,
        profile_complete: bool,
        universities_count: int,
        app_reqs_count: int,
        approaching_deadlines: int,
        scholarships_count: int,
        visa_count: int,
        missing_fields: list[str]
    ) -> Dict[str, Any]:
        """
        Compute the current stage based on user progress.
        
        Stage 1: Profile building - Profile is incomplete
        Stage 2: University discovery - Profile complete, no universities found
        Stage 3: Application preparation - Universities found, preparing applications
        Stage 4: Submission & follow-up - Applications prepared, deadlines approaching/passed
        Stage 5: Visa & scholarship preparation - Applications submitted, focus on visa/scholarships
        """
        
        # Stage 1: Profile building
        if not profile_complete:
            return {
                "number": 1,
                "name": "Profile Building",
                "description": (
                    "The student is building their profile. They need to complete their profile with essential information. "
                    + (f"Missing fields: {', '.join(missing_fields)}" if missing_fields else "")
                ),
                "reasoning": (
                    "Profile is incomplete - missing critical fields"
                    + (f": {', '.join(missing_fields)}" if missing_fields else "")
                )
            }
        
        # Stage 2: University discovery
        if universities_count == 0:
            return {
                "number": 2,
                "name": "University Discovery",
                "description": "The student has completed their profile and is now discovering universities that match their preferences and academic profile.",
                "reasoning": f"Profile is complete but no universities found ({universities_count} universities)"
            }
        
        # Stage 3: Application preparation
        if app_reqs_count == 0:
            return {
                "number": 3,
                "name": "Application Preparation",
                "description": "The student has found universities and is now preparing their applications. They need to gather application requirements and prepare documents.",
                "reasoning": f"Universities found ({universities_count}) but no application requirements gathered yet"
            }
        
        # Stage 4: Submission & follow-up (prioritize only when deadlines are approaching)
        if approaching_deadlines > 0:
            return {
                "number": 4,
                "name": "Submission & Follow-up",
                "description": "The student has prepared applications and is now submitting them or following up on approaching deadlines.",
                "reasoning": f"Application requirements gathered ({app_reqs_count}) with {approaching_deadlines} approaching deadlines"
            }

        # Stage 5: Visa & scholarship preparation
        # Reached when application prep exists and focus shifts to visa/scholarships without urgent submission deadlines
        if app_reqs_count > 0 and (scholarships_count > 0 or visa_count > 0):
            return {
                "number": 5,
                "name": "Visa & Scholarship Preparation",
                "description": "The student has submitted or largely completed applications and is now focusing on visa requirements and scholarship opportunities.",
                "reasoning": f"Applications prepared ({app_reqs_count}), with scholarships ({scholarships_count}) and/or visa info ({visa_count}); no urgent deadlines"
            }
        
        # Fallback: Default to Stage 3 if we have universities but unclear progression
        return {
            "number": 3,
            "name": "Application Preparation",
            "description": "The student is preparing their applications based on discovered universities.",
            "reasoning": f"Universities found ({universities_count}) - defaulting to application preparation stage"
        }

