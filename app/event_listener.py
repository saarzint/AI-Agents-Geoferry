"""
Event Listener for Profile Changes

Monitors user_profile_changes table and triggers scholarship search
when significant profile updates occur.
"""

import time
import requests
import threading
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from .supabase_client import get_supabase
import os


class ProfileChangeListener:
    """
    Simple polling-based listener that monitors profile changes.
    """
    
    def __init__(self, polling_interval: int = 30):
        """
        Initialize the profile change listener.
        
        Args:
            polling_interval: Seconds between database polls
        """
        self.polling_interval = polling_interval
        self.api_base_url = f"http://localhost:{os.getenv('PORT', '5000')}"
        self.is_running = False
        self.last_check_time = None
        self.thread = None
        
        # Fields that trigger scholarship re-evaluation
        self.significant_fields = {"gpa", "extracurriculars", "budget", "intended_major"}
        
        # Anti-infinite-loop protection
        self.processed_change_ids = set()  # Track processed changes
        self.last_trigger_time = {}  # Track last trigger time per user
        self.cooldown_seconds = 60  # Minimum seconds between triggers for same user
    
    def _has_existing_scholarship_results(self, user_id: int) -> bool:
        """
        Check if user has any existing scholarship results.
        
        Args:
            user_id: User ID to check
            
        Returns:
            True if user has previous scholarship results, False otherwise
        """
        try:
            supabase = get_supabase()
            
            # Check if user has any scholarship results
            results = supabase.table('scholarship_results')\
                .select('id')\
                .eq('user_profile_id', user_id)\
                .limit(1)\
                .execute()
            
            has_results = len(results.data) > 0
            print(f"User {user_id} has existing scholarship results: {has_results}")
            return has_results
            
        except Exception as e:
            print(f"Error checking existing scholarship results for user {user_id}: {e}")
            # If error checking, assume no results (conservative approach)
            return False
    
    def start_listening(self) -> None:
        """Start the event listener."""
        if self.is_running:
            print("Event listener already running")
            return
        
        self.is_running = False # temporarily disable for testing
        self.last_check_time = datetime.now(timezone.utc)  # Use UTC time to match database
        self.thread = threading.Thread(target=self._polling_loop, daemon=True)
        self.thread.start()
        
        print(f"Profile Change Listener started (polling every {self.polling_interval}s)")
        print(f"Initial check time set to: {self.last_check_time} (UTC)")
    
    def stop_listening(self) -> None:
        """Stop the event listener."""
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        print("Profile Change Listener stopped")
    
    def _polling_loop(self) -> None:
        """Main polling loop."""
        while self.is_running:
            try:
                self._check_for_changes()
                time.sleep(self.polling_interval)
            except Exception as e:
                print(f"Error in polling: {str(e)}")
                time.sleep(self.polling_interval)
    
    def _check_for_changes(self) -> None:
        """Check for new profile changes."""
        try:
            supabase = get_supabase()
            
            print(f"Checking for changes since: {self.last_check_time} (UTC)")
            
            # Convert to ISO format for database query
            check_time_iso = self.last_check_time.isoformat().replace('+00:00', 'Z')
            
            # Get changes since last check
            changes_resp = supabase.table("user_profile_changes").select("*") \
                .gte("changed_at", check_time_iso) \
                .order("changed_at", desc=False).execute()
            
            print(f"Query: changed_at >= '{check_time_iso}'")
            print(f"Found {len(changes_resp.data) if changes_resp.data else 0} changes")
            
            if not changes_resp.data:
                return
            
            # Process each change with anti-loop protection
            for change in changes_resp.data:
                change_id = change["id"]
                field_name = change["field_name"]
                user_id = change["user_profile_id"]
                changed_at = change["changed_at"]
                
                # Skip if we've already processed this exact change (early exit)
                if change_id in self.processed_change_ids:
                    print(f"⚪ SKIP: Already processed change ID {change_id}")
                    continue
                
                print(f"Processing change: User {user_id} - {field_name} at {changed_at} (ID: {change_id})")
                
                # Check if it's a significant field
                if field_name in self.significant_fields:
                    # Check cooldown period
                    current_time = datetime.now(timezone.utc)
                    last_trigger = self.last_trigger_time.get(user_id)
                    
                    if last_trigger:
                        time_since_last = (current_time - last_trigger).total_seconds()
                        if time_since_last < self.cooldown_seconds:
                            print(f"🕒 COOLDOWN: User {user_id} triggered {time_since_last:.1f}s ago, need {self.cooldown_seconds}s cooldown")
                            continue
                    
                    print(f"🎯 SIGNIFICANT CHANGE: User {user_id}: {field_name} changed - triggering scholarship search")
                    
                    # Update trigger time (but don't mark as processed yet - let _trigger_scholarship_update decide)
                    self.last_trigger_time[user_id] = current_time
                    
                    self._trigger_scholarship_update(user_id, [field_name], change_id)
                else:
                    print(f"⚪ Non-significant change: {field_name}")
                    # Still mark non-significant changes as processed to avoid reprocessing
                    self.processed_change_ids.add(change_id)
            
            # Update last check time to UTC timestamp of latest processed change
            # Add a small buffer to avoid edge cases
            if changes_resp.data:
                latest_change = max(changes_resp.data, key=lambda x: x["changed_at"])
                latest_timestamp_str = latest_change["changed_at"]
                if latest_timestamp_str.endswith('Z'):
                    latest_timestamp_str = latest_timestamp_str[:-1] + '+00:00'
                
                new_last_check = datetime.fromisoformat(latest_timestamp_str)
                # Add 1 second buffer to ensure we don't reprocess the same timestamp
                new_last_check = new_last_check.replace(microsecond=0) + timedelta(seconds=1)
                
                print(f"Updating last_check_time from {self.last_check_time} to {new_last_check} (UTC)")
                self.last_check_time = new_last_check
            
        except Exception as e:
            print(f"Error checking changes: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def _trigger_scholarship_update(self, user_id: int, changed_fields: List[str], change_id: int) -> None:
        """Trigger delta scholarship search via API."""
        try:
            # Double-check we haven't already processed this change
            if change_id in self.processed_change_ids:
                print(f"🛑 DUPLICATE PREVENTION: Change ID {change_id} already processed, skipping")
                return
            
            # Check if user has existing scholarship results
            if not self._has_existing_scholarship_results(user_id):
                print(f"⏭️  SKIPPING: User {user_id} has no existing scholarship results - delta search not applicable")
                print(f"   Tip: User should manually run initial scholarship search first")
                # Still mark as processed to avoid repeated checks
                self.processed_change_ids.add(change_id)
                return
                
            print(f"🚀 TRIGGERING: Delta scholarship search for user {user_id}, change ID {change_id}")
            
            # Mark as being processed now that we've decided to trigger it
            self.processed_change_ids.add(change_id)
            
            url = f"{self.api_base_url}/search_scholarships"
            payload = {
                "user_profile_id": user_id,
                "delta_search": True,
                "changed_fields": changed_fields
            }
            
            print(f"   URL: {url}")
            print(f"   Payload: {payload}")
            
            response = requests.post(url, json=payload, timeout=180)  # 3 minutes for complex AI operations
            
            if response.status_code == 200:
                print(f"✅ SUCCESS: Delta scholarship search completed for user {user_id}")
                # Change already marked as processed when we started the API call
                try:
                    result = response.json()
                    if 'scholarships' in result:
                        scholarship_count = len(result['scholarships'])
                        print(f"   Found {scholarship_count} scholarships in delta search")
                        print(f"   Change ID {change_id} fully processed")
                except:
                    print("   Response received but couldn't parse scholarship count")
                    print(f"   Change ID {change_id} processed")
            else:
                print(f"❌ ERROR: Delta search failed for user {user_id}: {response.status_code}")
                print(f"   Response: {response.text[:200]}...")
                # Remove from processed set if API call failed to allow retry
                self.processed_change_ids.discard(change_id)
                
        except Exception as e:
            print(f"💥 ERROR triggering delta search for user {user_id}: {str(e)}")
            # Remove from processed set if there was an error to allow retry
            self.processed_change_ids.discard(change_id)
            import traceback
            traceback.print_exc()


# Global listener instance
_profile_listener: Optional[ProfileChangeListener] = None


def start_profile_listener(polling_interval: int = 30) -> ProfileChangeListener:
    """Start the profile change listener with reload safety."""
    global _profile_listener
    
    # Stop existing listener before starting new one (for Flask reloads)
    if _profile_listener and _profile_listener.is_running:
        _profile_listener.stop_listening()
    
    _profile_listener = ProfileChangeListener(polling_interval)
    _profile_listener.start_listening()
    return _profile_listener


def stop_profile_listener() -> None:
    """Stop the profile change listener."""
    global _profile_listener
    
    if _profile_listener:
        _profile_listener.stop_listening()
        _profile_listener = None