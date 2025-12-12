from crewai.tools import BaseTool
from typing import Type, Dict, Any, Optional
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

class ProfileRequestParsingInput(BaseModel):
    """Input schema for ProfileRequestParsingTool."""
    user_id: Optional[int] = Field(None, description="User ID to query university interests and intended major.")

class ProfileRequestParsingTool(BaseTool):
    name: str = "Profile Request Parsing Tool"
    description: str = (
        "CrewAI tool to interpret the user's university/program query. "
        "Read-only access to the university_interests and intended_major fields in the user_profile table. "
        "No modification is allowed. Use this tool to retrieve a user's chosen universities and intended majors."
    )
    args_schema: Type[BaseModel] = ProfileRequestParsingInput

    def _run(self, **kwargs) -> str:
        user_id = kwargs.get("user_id")
        if not user_id:
            return "Error: user_id is required."
        if get_supabase is None:
            return "Error: Supabase client not available. Please check your configuration."
        try:
            supabase = get_supabase()
            query = supabase.table('user_profile').select('id, university_interests, intended_major').eq('id', user_id)
            response = query.execute()
            if not response.data:
                return f"No user profile found with ID: {user_id}"
            profile = response.data[0]
            # Format output as a readable string
            output = f"""
USER UNIVERSITY INTERESTS & INTENDED MAJOR (ID: {profile.get('id')})
===============================================================

University Interests:
"""
            interests = profile.get('university_interests')
            if interests:
                if isinstance(interests, list):
                    for uni in interests:
                        output += f"- {uni}\n"
                else:
                    output += f"- {interests}\n"
            else:
                output += "- None specified\n"
            output += f"\nIntended Major: {profile.get('intended_major') or 'Not specified'}\n"
            return output
        except Exception as e:
            return f"Error querying user university interests: {str(e)}"
