from crewai.tools import BaseTool
from typing import Type, Optional, Dict, Any
from pydantic import BaseModel, Field
import sys
import os
import json

# Add the app directory to the Python path to import supabase_client
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'app'))

try:
    from supabase_client import get_supabase
except ImportError:
    print("Warning: Could not import supabase_client. Make sure the app module is in the Python path.")
    get_supabase = None


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

    def _run(self, **kwargs) -> str:
        try:
            # Normalize CrewAI calling conventions
            if 'user_id' not in kwargs and len(kwargs) == 1 and isinstance(list(kwargs.values())[0], (str, int)):
                candidate = list(kwargs.values())[0]
                kwargs = {'user_id': int(candidate)}
        except Exception:
            pass

        user_id: Optional[int] = kwargs.get('user_id')
        if user_id is None:
            return json.dumps({"error": "user_id is required"})

        if get_supabase is None:
            return json.dumps({"error": "Supabase client not available"})

        try:
            supabase = get_supabase()
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


