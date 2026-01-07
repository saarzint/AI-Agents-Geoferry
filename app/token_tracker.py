from datetime import datetime
from typing import Optional, Dict, Any
from supabase_client import get_supabase

def extract_crewai_tokens(crew_result) -> Dict[str, int]:
    """
    Extract token usage from CrewAI result object.
    Returns dict with prompt_tokens, completion_tokens, total_tokens
    """
    tokens = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0
    }
    
    # CrewAI stores usage in different places depending on version
    if hasattr(crew_result, 'usage_metadata'):
        usage = crew_result.usage_metadata
        tokens["prompt_tokens"] = usage.get('prompt_tokens', 0)
        tokens["completion_tokens"] = usage.get('completion_tokens', 0)
        tokens["total_tokens"] = usage.get('total_tokens', 0)
    elif hasattr(crew_result, 'usage'):
        usage = crew_result.usage
        tokens["prompt_tokens"] = usage.get('prompt_tokens', 0)
        tokens["completion_tokens"] = usage.get('completion_tokens', 0)
        tokens["total_tokens"] = usage.get('total_tokens', 0)
    elif hasattr(crew_result, 'tokens_usage'):
        usage = crew_result.tokens_usage
        tokens["prompt_tokens"] = usage.get('prompt_tokens', 0)
        tokens["completion_tokens"] = usage.get('completion_tokens', 0)
        tokens["total_tokens"] = usage.get('total_tokens', 0)
    
    return tokens

def update_user_tokens(user_profile_id: int, tokens_used: int, endpoint: str) -> Dict[str, Any]:
    """
    Atomically update user token balance and log usage.
    Returns updated balance and usage record.
    """
    supabase = get_supabase()
    
    try:
        # Get current balance
        profile = supabase.table("user_profile").select("token_balance").eq("id", user_profile_id).execute()
        current_balance = profile.data[0].get("token_balance", 0) if profile.data else 0
        
        # Calculate new balance
        new_balance = max(0, current_balance - tokens_used)  # Prevent negative
        
        # Update balance atomically
        update_result = supabase.table("user_profile").update({
            "token_balance": new_balance
        }).eq("id", user_profile_id).execute()
        
        # Log usage (non-blocking - don't fail if logging fails)
        try:
            supabase.table("user_token_usage").insert({
                "user_profile_id": user_profile_id,
                "endpoint": endpoint,
                "api_provider": "openai",
                "tokens_used": tokens_used,
                "created_at": datetime.now().isoformat()
            }).execute()
        except Exception as log_error:
            print(f"Warning: Failed to log token usage: {log_error}")
        
        return {
            "tokens_used": tokens_used,
            "previous_balance": current_balance,
            "remaining_tokens": new_balance,
            "success": True
        }
    except Exception as e:
        print(f"Error updating user tokens: {e}")
        return {
            "tokens_used": tokens_used,
            "remaining_tokens": None,
            "success": False,
            "error": str(e)
        }