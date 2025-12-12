from crewai.tools import BaseTool
from typing import Type, Dict, Any, Optional, List
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


class ProfileQueryInput(BaseModel):
    """Input schema for ProfileQueryTool."""
    user_id: Optional[int] = Field(None, description="Specific user ID to query. If not provided, will return all profiles.")
    include_preferences: bool = Field(True, description="Whether to include user preferences in the response.")
    include_test_scores: bool = Field(True, description="Whether to include test scores in the response.")
    include_extracurriculars: bool = Field(True, description="Whether to include extracurricular activities.")
    include_academic_background: bool = Field(True, description="Whether to include academic background details.")
    full_profile: bool = Field(False, description="When True, includes ALL fields regardless of other include flags (complete read-only access).")


class ProfileQueryTool(BaseTool):
    name: str = "Profile Query Tool"
    description: str = (
        "READ-ONLY access to user profiles from the Supabase database. This tool provides secure, "
        "read-only access to student academic profiles including GPA, test scores, intended major, "
        "extracurricular activities, financial information, and personal preferences. Use this tool "
        "to retrieve user data before performing university searches. NO WRITE/UPDATE/DELETE operations allowed."
    )
    args_schema: Type[BaseModel] = ProfileQueryInput

    def _run(self, **kwargs) -> str:
        """
        Handle both structured and unstructured input to the tool.
        CrewAI agents sometimes pass parameters differently than expected.
        """
        
        # Handle case where all params come as a single argument
        if len(kwargs) == 1 and isinstance(list(kwargs.values())[0], str):
            # If we get a single string parameter, try to parse it as user_id
            try:
                single_value = list(kwargs.values())[0]
                # Try to extract user_id from the string
                if single_value.isdigit():
                    return self._execute_query(user_id=int(single_value))
                else:
                    return f"Error: Expected user_id as integer, got: {single_value}"
            except Exception as e:
                return f"Error parsing tool input: {str(e)}"
        
        # Normal parameter handling
        return self._execute_query(**kwargs)
    
    def _execute_query(
        self, 
        user_id: Optional[int] = None, 
        include_preferences: bool = True,
        include_test_scores: bool = True,
        include_extracurriculars: bool = True,
        include_academic_background: bool = True,
        full_profile: bool = False
    ) -> str:
        """
        Query user profile(s) from Supabase database with SECURE READ-ONLY access.
        
        SECURITY NOTE: This tool provides READ-ONLY access to user profiles. 
        No modification, insertion, or deletion of user data is permitted.
        
        Args:
            user_id: Specific user ID to query. If None, returns all profiles.
            include_preferences: Whether to include user preferences (location, campus size, etc.)
            include_test_scores: Whether to include test scores (SAT, ACT, TOEFL, etc.)
            include_extracurriculars: Whether to include extracurricular activities
            include_academic_background: Whether to include academic background (AP courses, honors, etc.)
            full_profile: When True, overrides all include flags and returns COMPLETE profile data
            
        Returns:
            Formatted string containing user profile data from all user_profile table fields
        """
        
        # Debug: Log the input types to help diagnose the issue
        try:
            debug_info = f"ProfileQueryTool Debug - Input types: user_id={type(user_id)} ({user_id}), include_preferences={type(include_preferences)} ({include_preferences})"
            print(debug_info)
        except Exception as debug_e:
            print(f"Debug logging failed: {debug_e}")
        
        if get_supabase is None:
            return "Error: Supabase client not available. Please check your configuration."
        
        try:
            supabase = get_supabase()
            
            # Build the query
            query = supabase.table('user_profile').select('*')
            
            if user_id:
                query = query.eq('id', user_id)
            
            # Execute the query
            response = query.execute()
            
            if not response.data:
                if user_id:
                    return f"No user profile found with ID: {user_id}"
                else:
                    return "No user profiles found in the database."
            
            # Process the results
            profiles = []
            for profile in response.data:
                # Add error handling for profile processing
                try:
                    processed_profile = self._process_profile(
                        profile, 
                        include_preferences if not full_profile else True, 
                        include_test_scores if not full_profile else True, 
                        include_extracurriculars if not full_profile else True,
                        include_academic_background if not full_profile else True,
                        full_profile
                    )
                    profiles.append(processed_profile)
                except Exception as process_e:
                    return f"Error processing profile data: {str(process_e)}. Profile type: {type(profile)}, Profile content: {str(profile)[:200]}"
            
            if user_id and len(profiles) == 1:
                return self._format_single_profile(profiles[0])
            else:
                return self._format_multiple_profiles(profiles)
                
        except Exception as e:
            return f"Error querying user profile: {str(e)}"
    
    def _process_profile(
        self, 
        profile: Dict[str, Any], 
        include_preferences: bool,
        include_test_scores: bool,
        include_extracurriculars: bool,
        include_academic_background: bool,
        full_profile: bool
    ) -> Dict[str, Any]:
        """Process and filter profile data based on include flags. Ensures complete read-only access to ALL user_profile fields."""
        
        # Add type checking and error handling
        if not isinstance(profile, dict):
            raise TypeError(f"Expected profile to be a dictionary, but received {type(profile)}: {str(profile)[:200]}")
        
        # Core fields - ALWAYS included (complete read-only access to basic profile)
        try:
            processed = {
                'id': profile.get('id'),
                'full_name': profile.get('full_name'),
                'gpa': float(profile.get('gpa', 0)) if profile.get('gpa') else None,
                'intended_major': profile.get('intended_major'),
                'financial_aid_eligibility': profile.get('financial_aid_eligibility', False),
                'budget': profile.get('budget'),
                'created_at': profile.get('created_at'),
                'updated_at': profile.get('updated_at')
            }
        except AttributeError as e:
            raise AttributeError(f"Error accessing profile fields. Profile type: {type(profile)}, Error: {str(e)}")
        
        # Conditional fields based on flags (or full_profile override)
        if (include_test_scores or full_profile) and profile.get('test_scores'):
            processed['test_scores'] = profile['test_scores']
        
        if (include_extracurriculars or full_profile) and profile.get('extracurriculars'):
            processed['extracurriculars'] = profile['extracurriculars']
        
        if (include_preferences or full_profile) and profile.get('preferences'):
            processed['preferences'] = profile['preferences']
        
        if (include_academic_background or full_profile) and profile.get('academic_background'):
            processed['academic_background'] = profile['academic_background']
        

        
        return processed
    
    def _format_single_profile(self, profile: Dict[str, Any]) -> str:
        """Format a single profile for display."""
        
        output = f"""
USER PROFILE (ID: {profile['id']})
================================

Basic Information:
- Name: {profile['full_name']}
- GPA: {profile['gpa'] if profile['gpa'] else 'Not provided'}
- Intended Major: {profile['intended_major'] if profile['intended_major'] else 'Not specified'}

Financial Information:
- Budget: {f'${profile["budget"]:,} per year' if profile['budget'] else 'Not specified'}
- Financial Aid Eligible: {'Yes' if profile['financial_aid_eligibility'] else 'No'}
"""
        
        if profile.get('test_scores'):
            output += f"\nTest Scores:\n"
            for test, score in profile['test_scores'].items():
                output += f"- {test.upper()}: {score}\n"
        
        if profile.get('extracurriculars'):
            output += f"\nExtracurricular Activities:\n"
            for activity in profile['extracurriculars']:
                output += f"- {activity}\n"
        
        if profile.get('preferences'):
            output += f"\nPreferences:\n"
            for pref_key, pref_value in profile['preferences'].items():
                output += f"- {pref_key.replace('_', ' ').title()}: {pref_value}\n"
        
        if profile.get('academic_background'):
            output += f"\nAcademic Background:\n"
            for bg_key, bg_value in profile['academic_background'].items():
                output += f"- {bg_key.replace('_', ' ').title()}: {bg_value}\n"
        
        output += f"\nProfile Last Updated: {profile['updated_at']}"
        
        return output
    
    def _format_multiple_profiles(self, profiles: List[Dict[str, Any]]) -> str:
        """Format multiple profiles for display."""
        
        output = f"FOUND {len(profiles)} USER PROFILES\n"
        output += "=" * 50 + "\n\n"
        
        for i, profile in enumerate(profiles, 1):
            output += f"{i}. {profile['full_name']} (ID: {profile['id']})\n"
            output += f"   GPA: {profile['gpa'] if profile['gpa'] else 'N/A'}\n"
            output += f"   Major: {profile['intended_major'] if profile['intended_major'] else 'Not specified'}\n"
            output += f"   Budget: ${profile['budget']:,}" if profile['budget'] else "   Budget: Not specified"
            output += f"\n   Updated: {profile['updated_at']}\n\n"
        
        output += "Use user_id parameter to get detailed information for a specific profile."
        output += "\nUse full_profile=True to get complete read-only access to ALL user_profile fields."
        
        return output


