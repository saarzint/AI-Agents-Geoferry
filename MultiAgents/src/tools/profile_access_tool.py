from crewai.tools import BaseTool
from typing import Type, Optional, Dict, Any
from pydantic import BaseModel, Field
import traceback
import contextlib
import sys
import os
import json

# Add the app directory to the Python path to import supabase_client
app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'app'))
if app_path not in sys.path:
    sys.path.insert(0, app_path)
from supabase_client import get_supabase  # type: ignore


class ProfileAccessInput(BaseModel):
    """Input schema for ProfileAccessTool."""
    user_id: int = Field(..., description="User ID whose profile should be read.")


class ProfileAccessTool(BaseTool):
    name: str = "Profile Access Tool"
    description: str = (
        "READ-ONLY helper to fetch visa-related fields from a user's profile: "
        "citizenship country and destination country. The tool will look for common "
        "locations of these fields (top-level columns or inside preferences JSON)."
    )
    args_schema: Type[BaseModel] = ProfileAccessInput

    def _run(self, user_id: Optional[int] = None, **kwargs: Dict[str, Any]) -> str:
        try:
            # Handle case where user_id might be passed in kwargs
            if user_id is None:
                if 'user_id' in kwargs:
                    user_id = kwargs['user_id']
                elif len(kwargs) == 1:
                    potential_id = list(kwargs.values())[0]
                    if isinstance(potential_id, (str, int)):
                        try:
                            user_id = int(potential_id)
                        except (ValueError, TypeError):
                            pass
            
            if user_id is None:
                return json.dumps({"error": "user_id is required"})
            
            # Ensure user_id is an integer
            try:
                user_id = int(user_id)
            except (ValueError, TypeError):
                return json.dumps({"error": f"Invalid user_id: {user_id}"})
            
            supabase = get_supabase()
            if not supabase:
                return json.dumps({"error": "Supabase client not available"})

            resp = supabase.table('user_profile').select('*').eq('id', user_id).limit(1).execute()
            if not resp.data:
                return json.dumps({"error": f"No user profile found with ID: {user_id}"})

            profile: Dict[str, Any] = resp.data[0]

            # Attempt multiple keys/locations for robustness
            preferences = profile.get('preferences') or {}
            if isinstance(preferences, str):
                try:
                    preferences = json.loads(preferences)
                except Exception:
                    preferences = {}

            citizenship = (
                profile.get('citizenship')
                or profile.get('citizenship_country')
                or preferences.get('citizenship')
                or preferences.get('citizenship_country')
                or preferences.get('nationality')
            )

            destination = (
                profile.get('destination')
                or profile.get('destination_country')
                or preferences.get('destination')
                or preferences.get('destination_country')
                or preferences.get('target_country')
            )

            result = {
                "user_id": user_id,
                "citizenship_country": citizenship,
                "destination_country": destination
            }

            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})


