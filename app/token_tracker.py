"""
Token Tracking Module

Tracks token usage for AI agent calls and manages user token balances.
"""

from datetime import datetime
from typing import Dict, Any
from .supabase_client import get_supabase


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

        # Handle None balance
        if current_balance is None:
            current_balance = 0

        # Calculate new balance
        new_balance = max(0, current_balance - tokens_used)  # Prevent negative

        # Update balance atomically
        supabase.table("user_profile").update({
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


def get_user_token_balance(user_profile_id: int) -> Dict[str, Any]:
    """
    Get user's current token balance and usage history.
    """
    supabase = get_supabase()

    try:
        # Get current balance
        profile = supabase.table("user_profile").select("token_balance").eq("id", user_profile_id).execute()

        if not profile.data:
            return {
                "success": False,
                "error": f"User profile {user_profile_id} not found"
            }

        current_balance = profile.data[0].get("token_balance", 0)
        if current_balance is None:
            current_balance = 0

        # Get recent usage history (last 10 entries)
        usage_resp = supabase.table("user_token_usage") \
            .select("*") \
            .eq("user_profile_id", user_profile_id) \
            .order("created_at", desc=True) \
            .limit(10) \
            .execute()

        # Calculate total tokens used
        total_usage_resp = supabase.table("user_token_usage") \
            .select("tokens_used") \
            .eq("user_profile_id", user_profile_id) \
            .execute()

        total_used = sum(r.get("tokens_used", 0) for r in total_usage_resp.data) if total_usage_resp.data else 0

        return {
            "success": True,
            "user_profile_id": user_profile_id,
            "token_balance": current_balance,
            "total_tokens_used": total_used,
            "recent_usage": usage_resp.data if usage_resp.data else []
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def add_tokens_to_user(user_profile_id: int, tokens_to_add: int, reason: str = "manual_add") -> Dict[str, Any]:
    """
    Add tokens to user's balance (for purchases, bonuses, etc.)
    """
    supabase = get_supabase()

    try:
        # Get current balance
        profile = supabase.table("user_profile").select("token_balance").eq("id", user_profile_id).execute()

        if not profile.data:
            return {
                "success": False,
                "error": f"User profile {user_profile_id} not found"
            }

        current_balance = profile.data[0].get("token_balance", 0)
        if current_balance is None:
            current_balance = 0

        new_balance = current_balance + tokens_to_add

        # Update balance
        supabase.table("user_profile").update({
            "token_balance": new_balance
        }).eq("id", user_profile_id).execute()

        # Log the addition
        try:
            supabase.table("user_token_usage").insert({
                "user_profile_id": user_profile_id,
                "endpoint": reason,
                "api_provider": "system",
                "tokens_used": -tokens_to_add,  # Negative to indicate addition
                "created_at": datetime.now().isoformat()
            }).execute()
        except Exception as log_error:
            print(f"Warning: Failed to log token addition: {log_error}")

        return {
            "success": True,
            "tokens_added": tokens_to_add,
            "previous_balance": current_balance,
            "new_balance": new_balance
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
