"""
Tool for Admissions Counselor Agent to aggregate data from all other agents.
Provides read-only access to university_results, scholarship_results, 
application_requirements, and visa_requirements tables.
"""

import os
from typing import Optional, Dict, Any
from crewai.tools import BaseTool
from typing import Type, Dict, Any
from pydantic import BaseModel, Field
import sys
import os

# Add the app directory to the Python path to import supabase_client
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'app'))

try:
    from supabase_client import get_supabase
except ImportError:
    print("Warning: Could not import supabase_client. Make sure the app module is in the Python path.")
    get_supabase = None

from datetime import datetime, timedelta
from dateutil import parser as date_parser
import re


class AdmissionsDataInput(BaseModel):
    """Input schema for Admissions Data Tool"""
    
    user_id: int = Field(..., description="User ID to query all admissions data for")
    
class AdmissionsDataTool(BaseTool):
    name: str = "Admissions Data Aggregation Tool"
    description: str = (
        "READ-ONLY access to aggregated admissions data from all agents. "
        "Returns university recommendations, scholarship opportunities, application requirements, "
        "and visa information for a user. Use this tool to get a comprehensive view of the user's "
        "admissions journey. No write operations allowed."
    )
    args_schema: type[BaseModel] = AdmissionsDataInput
    
    def _run(self, **kwargs) -> str:
        """Query all admissions data for a user"""
        user_id = kwargs.get("user_id")
        output_mode = kwargs.get("output", "json")  # 'text' | 'json' (default json for programmatic use)
        
        if not user_id:
            return "Error: user_id is required"
        
        if get_supabase is None:
            return "Error: Supabase client not available"
        
        try:
            supabase = get_supabase()
            
            # Query all data sources
            universities_resp = supabase.table("university_results").select("*").eq("user_profile_id", user_id).order("created_at", desc=True).execute()
            scholarships_resp = supabase.table("scholarship_results").select("*").eq("user_profile_id", user_id).gte("deadline", datetime.now().date().isoformat()).order("deadline", desc=False).execute()
            app_reqs_resp = supabase.table("application_requirements").select("*").eq("user_profile_id", user_id).order("fetched_at", desc=True).execute()
            visa_resp = supabase.table("visa_requirements").select("*").eq("user_profile_id", user_id).order("fetched_at", desc=True).execute()
            profile_resp = supabase.table("user_profile").select(
                "gpa,intended_major,budget,citizenship_country,destination_country,test_scores,academic_background,preferences"
            ).eq("id", user_id).execute()
            
            # Compute counts and missing agents
            universities = universities_resp.data or []
            scholarships = scholarships_resp.data or []
            app_reqs = app_reqs_resp.data or []
            visas = visa_resp.data or []

            counts = {
                "universities_found": len(universities),
                "scholarships_found": len(scholarships),
                "application_requirements": len(app_reqs),
                "visa_info_count": len(visas),
            }

            # Profile completeness (collect missing fields)
            gpa_val = None
            major_val = None
            budget_val = None
            citizen_val = None
            dest_val = None
            test_scores_val = None
            academic_background_val = None
            preferences_val = None
            if profile_resp.data:
                prof = profile_resp.data[0]
                gpa_val = prof.get("gpa")
                major_val = prof.get("intended_major")
                budget_val = prof.get("budget")
                citizen_val = prof.get("citizenship_country")
                dest_val = prof.get("destination_country")
                test_scores_val = prof.get("test_scores")
                academic_background_val = prof.get("academic_background")
                preferences_val = prof.get("preferences")

            missing_profile_fields: list[str] = []
            if (gpa_val is None):
                missing_profile_fields.append("gpa")
            if (major_val is None) or (str(major_val).strip() == ""):
                missing_profile_fields.append("intended_major")
            if (budget_val is None):
                missing_profile_fields.append("budget")
            if (citizen_val is None) or (str(citizen_val).strip() == ""):
                missing_profile_fields.append("citizenship_country")
            if (dest_val is None) or (str(dest_val).strip() == ""):
                missing_profile_fields.append("destination_country")
            if (not test_scores_val):
                missing_profile_fields.append("test_scores")
            if (not academic_background_val):
                missing_profile_fields.append("academic_background")
            if (not preferences_val):
                missing_profile_fields.append("preferences")

            incomplete_profile = len(missing_profile_fields) > 0

            missing_agents: list[str] = []
            # Use agent ROLE names so the delegation tool can find coworkers
            if counts["universities_found"] == 0:
                missing_agents.append("University Search Agent")
            if counts["scholarships_found"] == 0:
                missing_agents.append("Scholarship Search Agent")
            if counts["application_requirements"] == 0:
                missing_agents.append("Application Requirement Agent")
            if counts["visa_info_count"] == 0:
                missing_agents.append("Visa Information Agent")

            # Count approaching deadlines (within 45 days) and collect details
            approaching_deadlines_count, approaching_deadlines_details = self._count_approaching_deadlines(scholarships, app_reqs)

            if output_mode == "json":
                import json
                return json.dumps({
                    "user_id": user_id,
                    **counts,
                    "missing_agents": missing_agents,
                    "incomplete_profile": incomplete_profile,
                    "missing_profile_fields": missing_profile_fields,
                    "approaching_deadlines": approaching_deadlines_count,
                    "approaching_deadlines_details": approaching_deadlines_details
                })

            # Fallback: human-readable text
            output = f"""
ADMISSIONS DATA AGGREGATION FOR USER {user_id}
===============================================================

UNIVERSITY RESULTS: {counts['universities_found']} universities found
"""
            if universities:
                for uni in universities[:10]:  # Show first 10
                    output += f"  - {uni.get('university_name', 'Unknown')} ({uni.get('rank_category', 'Unknown')})\n"
            
            output += f"\nSCHOLARSHIP RESULTS: {counts['scholarships_found']} active scholarships\n"
            if scholarships:
                for schol in scholarships[:10]:  # Show first 10
                    deadline_str = f" (Deadline: {schol.get('deadline', 'Unknown')})" if schol.get('deadline') else ""
                    output += f"  - {schol.get('name', 'Unknown')}{deadline_str}\n"
            
            output += f"\nAPPLICATION REQUIREMENTS: {counts['application_requirements']} requirements found\n"
            if app_reqs:
                for req in app_reqs[:10]:  # Show first 10
                    uni_name = req.get('university', 'Unknown')
                    program_name = req.get('program', 'Unknown')
                    deadlines = req.get('deadlines', {})
                    
                    # Extract and format deadline info
                    deadline_list = []
                    if isinstance(deadlines, dict):
                        for key, value in deadlines.items():
                            if value and value not in [None, "None", "", False]:
                                if isinstance(value, str):
                                    deadline_list.append(f"{key}: {value}")
                    
                    deadline_str = " | ".join(deadline_list) if deadline_list else ""
                    if deadline_str:
                        output += f"  - {uni_name}: {program_name} (Deadlines: {deadline_str})\n"
                    else:
                        output += f"  - {uni_name}: {program_name}\n"
            
            output += f"\nVISA INFORMATION: {counts['visa_info_count']} visa records\n"
            if visas:
                for visa in visas[:5]:  # Show first 5
                    output += f"  - {visa.get('citizenship_country', 'Unknown')} → {visa.get('destination_country', 'Unknown')}: {visa.get('visa_type', 'Student Visa')}\n"
            
            return output
            
        except Exception as e:
            return f"Error querying admissions data: {str(e)}"
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse various date formats into datetime object"""
        if not date_str or date_str in [None, "None", "", False]:
            return None
        try:
            # Try parsing with dateutil
            return date_parser.parse(str(date_str))
        except:
            try:
                # Try regex patterns for common formats
                date_str_clean = str(date_str).strip()
                # ISO format: 2025-11-01
                if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str_clean):
                    return datetime.strptime(date_str_clean, '%Y-%m-%d')
                # US format: 11/01/2025
                if re.match(r'^\d{1,2}/\d{1,2}/\d{4}$', date_str_clean):
                    return datetime.strptime(date_str_clean, '%m/%d/%Y')
                # Alternative: 12/01/2025
                if re.match(r'^\d{1,2}/\d{1,2}/\d{4}$', date_str_clean):
                    return datetime.strptime(date_str_clean, '%d/%m/%Y')
            except:
                pass
        return None
    
    def _count_approaching_deadlines(self, scholarships: list, app_reqs: list, days_threshold: int = 45):
        """Count deadlines within specified days and return details"""
        today = datetime.now().date()
        count = 0
        details = []
        
        # Check scholarship deadlines
        for schol in scholarships:
            deadline = schol.get('deadline')
            if deadline:
                parsed_date = self._parse_date(deadline)
                if parsed_date:
                    days_left = (parsed_date.date() - today).days
                    if 0 <= days_left <= days_threshold:
                        count += 1
                        details.append({
                            "type": "scholarship",
                            "name": schol.get('name', 'Unknown Scholarship'),
                            "deadline": schol.get('deadline'),
                            "days_left": days_left
                        })
        
        # Check application requirements deadlines
        for req in app_reqs:
            university = req.get('university', 'Unknown University')
            program = req.get('program', 'Unknown Program')
            deadlines = req.get('deadlines', {})
            
            if isinstance(deadlines, dict):
                for deadline_type, deadline_value in deadlines.items():
                    if deadline_value and deadline_value not in [None, "None", "", False]:
                        parsed_date = self._parse_date(deadline_value)
                        if parsed_date:
                            days_left = (parsed_date.date() - today).days
                            if 0 <= days_left <= days_threshold:
                                count += 1
                                details.append({
                                    "type": "application",
                                    "university": university,
                                    "program": program,
                                    "deadline_type": deadline_type,
                                    "deadline": deadline_value,
                                    "days_left": days_left
                                })
        
        return count, details

