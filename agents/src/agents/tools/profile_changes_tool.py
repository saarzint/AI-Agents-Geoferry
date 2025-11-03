from crewai.tools import BaseTool
from typing import Type, Optional
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


class ProfileChangesInput(BaseModel):
    """Input schema for ProfileChangesTool."""
    user_id: int = Field(..., description="User ID to query profile changes for")
    limit: Optional[int] = Field(10, description="Maximum number of recent changes to return (default: 10)")


class ProfileChangesTool(BaseTool):
    name: str = "Profile Changes Tool"
    description: str = (
        "READ-ONLY access to user profile changes from the Supabase database. This tool provides "
        "secure, read-only access to the change history for a user's profile including what fields "
        "changed, their old and new values, and when the changes occurred. Use this tool to understand "
        "recent profile modifications for delta scholarship searches. NO WRITE/UPDATE/DELETE operations allowed."
    )
    args_schema: Type[BaseModel] = ProfileChangesInput

    def _run(self, user_id: int, limit: int = 10) -> str:
        """
        Query user profile changes from Supabase database with SECURE READ-ONLY access.
        
        SECURITY NOTE: This tool provides READ-ONLY access to profile change history. 
        No modification, insertion, or deletion of change data is permitted.
        
        Args:
            user_id: User ID to query changes for
            limit: Maximum number of recent changes to return (default: 10)
            
        Returns:
            Formatted JSON string containing change history for the user
        """
        
        if get_supabase is None:
            return "Error: Supabase client not available. Please check your configuration."
        
        try:
            supabase = get_supabase()
            
            print(f"ProfileChangesTool: Querying changes for user {user_id} (limit: {limit})")
            
            # Query user_profile_changes table
            query = supabase.table('user_profile_changes').select(
                'id, user_profile_id, field_name, old_value, new_value, changed_at'
            ).eq('user_profile_id', user_id).order('changed_at', desc=True).limit(limit)
            
            # Execute the query
            response = query.execute()
            
            if not response.data:
                return f"No profile changes found for user {user_id}"
            
            # Process and format the results
            changes = []
            for change in response.data:
                formatted_change = {
                    'change_id': change['id'],
                    'user_id': change['user_profile_id'],
                    'field_name': change['field_name'],
                    'old_value': change['old_value'],
                    'new_value': change['new_value'],
                    'changed_at': change['changed_at']
                }
                changes.append(formatted_change)
            
            return self._format_changes_output(user_id, changes)
                
        except Exception as e:
            error_msg = f"Error querying profile changes: {str(e)}"
            print(f"ProfileChangesTool Error: {error_msg}")
            return error_msg
    
    def _format_changes_output(self, user_id: int, changes: list) -> str:
        """Format profile changes for display."""
        
        output = f"""
PROFILE CHANGES FOR USER {user_id}
==================================

Total Changes Found: {len(changes)}

Recent Changes (most recent first):
"""
        
        for i, change in enumerate(changes, 1):
            output += f"""
{i}. Field: {change['field_name']}
   Changed At: {change['changed_at']}
   Old Value: {change['old_value'] or 'None'}
   New Value: {change['new_value'] or 'None'}
   Change ID: {change['change_id']}
"""
        
        # Summary by field
        field_counts = {}
        for change in changes:
            field_name = change['field_name']
            field_counts[field_name] = field_counts.get(field_name, 0) + 1
        
        if field_counts:
            output += f"\nChange Summary by Field:\n"
            for field, count in field_counts.items():
                output += f"- {field}: {count} change(s)\n"
        
        output += f"\nNote: This tool provides read-only access to profile change history."
        output += f"\nUse this data to understand what has changed for delta scholarship searches."
        
        return output