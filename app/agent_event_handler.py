"""
Agent Event Handler - Listens for agent reports and updates admissions summary.
This module handles incoming agent data and orchestrates updates to the admissions dashboard.
"""

from datetime import datetime
from typing import Dict, Any, Optional
from supabase_client import get_supabase


class AgentEventHandler:
    """Handles events from all agents and updates admissions summary accordingly."""
    
    def __init__(self):
        self.supabase = get_supabase()
    
    def log_agent_report(
        self,
        agent_name: str,
        user_id: int,
        payload: Dict[str, Any],
        timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Log an agent report to the database and update admissions summary.
        
        Args:
            agent_name: Name of the agent (e.g., "University Search Agent")
            user_id: User ID
            payload: Report data from the agent
            timestamp: Optional timestamp (defaults to now)
        
        Returns:
            Dict with report_id, conflict_detected status
        """
        if not timestamp:
            timestamp = datetime.now().isoformat()
        
        # Check for conflicts with recent reports from other agents
        conflict_flag = self._detect_conflicts(user_id, agent_name, payload)
        
        # Insert the report
        insert_data = {
            "agent_name": agent_name,
            "user_id": user_id,
            "payload": payload,
            "timestamp": timestamp,
            "conflict_flag": conflict_flag,
            "verified": False
        }
        
        result = self.supabase.table("agent_reports_log").insert(insert_data).execute()
        report_id = result.data[0]["id"] if result.data else None
        
        # Get conflict details if detected
        conflict_details = None
        if conflict_flag:
            conflict_details = self._get_conflict_details(user_id, agent_name, payload)
        
        # Update admissions summary if conflict detected
        if conflict_flag:
            # Mark for manual review and update stress flags
            self._mark_for_review(report_id, user_id)
            self._update_stress_flags(user_id, {"agent_conflicts": True})
            print(f"[ALERT] Conflict detected for user {user_id}, agent {agent_name}. Manual review recommended.")
            if conflict_details:
                print(f"[CONFLICT DETAILS] {conflict_details}")
        
        # Trigger admissions summary refresh
        self._trigger_summary_update(user_id)
        
        return {
            "report_id": report_id,
            "conflict_detected": conflict_flag
        }
    
    def _detect_conflicts(
        self,
        user_id: int,
        agent_name: str,
        new_payload: Dict[str, Any]
    ) -> bool:
        """
        Detect conflicts between new report and existing reports from other agents.
        Prioritizes data by most recent timestamp and detects actual content conflicts.
        """
        conflict_flag = False
        
        # Get recent reports for this user (ordered by timestamp, most recent first)
        recent_reports = self.supabase.table("agent_reports_log").select(
            "agent_name, payload, timestamp"
        ).eq("user_id", user_id).order("timestamp", desc=True).limit(20).execute()
        
        # Current timestamp for comparison
        current_timestamp = datetime.now().isoformat()
        
        # Check for conflicts with reports from different agents
        for report in recent_reports.data or []:
            if report.get("agent_name") == agent_name:
                continue  # Skip same agent reports
            
            prev_payload = report.get("payload", {})
            prev_timestamp = report.get("timestamp")
            
            if not isinstance(prev_payload, dict) or not isinstance(new_payload, dict):
                continue
            
            # CRITICAL CONFLICT DETECTION: Check for actual discrepancies
            
            # 1. Conflict: Different deadlines for the same university/program
            if self._check_deadline_conflict(prev_payload, new_payload):
                conflict_flag = True
                print(f"[CONFLICT] Deadline mismatch detected for user {user_id} between agents")
                break
            
            # 2. Conflict: Different university/program data
            if self._check_university_program_conflict(prev_payload, new_payload):
                conflict_flag = True
                print(f"[CONFLICT] University/program data mismatch for user {user_id}")
                break
            
            # 3. Conflict: Different financial data (scholarship amounts, tuition, etc.)
            if self._check_financial_conflict(prev_payload, new_payload):
                conflict_flag = True
                print(f"[CONFLICT] Financial data mismatch for user {user_id}")
                break
            
            # 4. Conflict: Different visa requirements for same route
            if self._check_visa_conflict(prev_payload, new_payload):
                conflict_flag = True
                print(f"[CONFLICT] Visa requirements mismatch for user {user_id}")
                break
        
        return conflict_flag
    
    def _check_deadline_conflict(
        self,
        prev_payload: Dict[str, Any],
        new_payload: Dict[str, Any]
    ) -> bool:
        """
        Check for deadline conflicts between payloads.
        Returns True if same university/program but different deadlines.
        """
        # Extract university/program from both payloads
        prev_uni = prev_payload.get("university")
        prev_prog = prev_payload.get("program")
        new_uni = new_payload.get("university")
        new_prog = new_payload.get("program")
        
        # Only check if we have university/program info
        if not (prev_uni or prev_prog) or not (new_uni or new_prog):
            return False
        
        # Check if it's the same university/program
        if prev_uni and new_uni and prev_uni == new_uni:
            # Same university - check deadlines
            prev_deadlines = prev_payload.get("application_requirements_stored", 0)
            new_deadlines = new_payload.get("application_requirements_stored", 0)
            
            # If both mention application requirements but different counts, potential conflict
            if prev_deadlines > 0 and new_deadlines > 0 and prev_deadlines != new_deadlines:
                return True
        
        return False
    
    def _check_university_program_conflict(
        self,
        prev_payload: Dict[str, Any],
        new_payload: Dict[str, Any]
    ) -> bool:
        """
        Check for conflicts in university/program data.
        Returns True if conflicting data about the same entity.
        """
        prev_uni = prev_payload.get("university", "").lower()
        new_uni = new_payload.get("university", "").lower()
        
        # Check if both are about universities but provide different counts
        if "universities" in prev_payload.get("universities_found", "") or \
           "universities" in new_payload.get("universities_found", ""):
            prev_count = prev_payload.get("universities_found", 0)
            new_count = new_payload.get("universities_found", 0)
            
            # Significant difference in counts could indicate a conflict
            if prev_count > 0 and new_count > 0 and abs(prev_count - new_count) > 10:
                return True
        
        return False
    
    def _check_financial_conflict(
        self,
        prev_payload: Dict[str, Any],
        new_payload: Dict[str, Any]
    ) -> bool:
        """
        Check for conflicts in financial data (scholarship amounts, tuition, etc.).
        Returns True if significant discrepancies found.
        """
        # Check for scholarship conflicts
        prev_scholarships = prev_payload.get("scholarships_found", 0)
        new_scholarships = new_payload.get("scholarships_found", 0)
        
        if prev_scholarships > 0 and new_scholarships > 0:
            # Major discrepancy could indicate data quality issue
            if abs(prev_scholarships - new_scholarships) > 50:
                return True
        
        return False
    
    def _check_visa_conflict(
        self,
        prev_payload: Dict[str, Any],
        new_payload: Dict[str, Any]
    ) -> bool:
        """
        Check for conflicts in visa requirements.
        Returns True if different requirements for the same route.
        """
        prev_citizenship = prev_payload.get("citizenship", "").lower()
        prev_destination = prev_payload.get("destination", "").lower()
        new_citizenship = new_payload.get("citizenship", "").lower()
        new_destination = new_payload.get("destination", "").lower()
        
        # Check if it's the same route
        if prev_citizenship and prev_destination and \
           new_citizenship and new_destination and \
           prev_citizenship == new_citizenship and \
           prev_destination == new_destination:
            
            # Same route but different visa requirements stored
            prev_count = prev_payload.get("visa_requirements_stored", 0)
            new_count = new_payload.get("visa_requirements_stored", 0)
            
            if prev_count != new_count:
                return True
        
        return False
    
    def _update_stress_flags(self, user_id: int, flags: Dict[str, Any]):
        """Update stress flags in admissions summary."""
        try:
            # Get existing stress flags
            summary_resp = self.supabase.table("admissions_summary").select(
                "id, stress_flags"
            ).eq("user_id", user_id).order("last_updated", desc=True).limit(1).execute()
            
            if summary_resp.data:
                existing_flags = summary_resp.data[0].get("stress_flags", {})
                existing_flags.update(flags)
                
                self.supabase.table("admissions_summary").update({
                    "stress_flags": existing_flags,
                    "last_updated": datetime.now().isoformat()
                }).eq("id", summary_resp.data[0]["id"]).execute()
        except Exception as e:
            print(f"Error updating stress flags: {e}")
    
    def _get_conflict_details(
        self,
        user_id: int,
        agent_name: str,
        new_payload: Dict[str, Any]
    ) -> Optional[str]:
        """Get details about detected conflicts for logging and alerts."""
        try:
            recent_reports = self.supabase.table("agent_reports_log").select(
                "agent_name, payload, timestamp"
            ).eq("user_id", user_id).order("timestamp", desc=True).limit(20).execute()
            
            for report in recent_reports.data or []:
                if report.get("agent_name") == agent_name:
                    continue
                
                prev_payload = report.get("payload", {})
                if not isinstance(prev_payload, dict) or not isinstance(new_payload, dict):
                    continue
                
                # Check deadline conflicts
                if self._check_deadline_conflict(prev_payload, new_payload):
                    return f"Deadline conflict between {report.get('agent_name')} and {agent_name}"
                
                # Check university conflicts
                if self._check_university_program_conflict(prev_payload, new_payload):
                    return f"University data conflict between {report.get('agent_name')} and {agent_name}"
                
                # Check financial conflicts
                if self._check_financial_conflict(prev_payload, new_payload):
                    return f"Financial data conflict between {report.get('agent_name')} and {agent_name}"
                
                # Check visa conflicts
                if self._check_visa_conflict(prev_payload, new_payload):
                    return f"Visa requirements conflict between {report.get('agent_name')} and {agent_name}"
            
        except Exception as e:
            print(f"Error getting conflict details: {e}")
        
        return None
    
    def _mark_for_review(self, report_id: Optional[int], user_id: int):
        """
        Mark conflict report for manual review.
        Prioritizes most recent data by default.
        """
        try:
            # Update the report with a review flag
            if report_id:
                self.supabase.table("agent_reports_log").update({
                    "verified": False  # Mark as unverified pending review
                }).eq("id", report_id).execute()
            
            # Log the conflict details for tracking
            print(f"[REVIEW] User {user_id} has conflicting agent data requiring manual verification")
            print(f"[INFO] Most recent timestamp takes priority for conflict resolution")
            
        except Exception as e:
            print(f"Error marking report for review: {e}")
    
    def _trigger_summary_update(self, user_id: int):
        """Trigger a refresh of the admissions summary."""
        try:
            # This will be handled by the next GET /admissions/summary/{user_id} call
            # or can be triggered programmatically here if needed
            print(f"Summary update triggered for user {user_id}")
        except Exception as e:
            print(f"Error triggering summary update: {e}")


# Singleton instance
_event_handler = None

def get_event_handler() -> AgentEventHandler:
    """Get singleton instance of AgentEventHandler."""
    global _event_handler
    if _event_handler is None:
        _event_handler = AgentEventHandler()
    return _event_handler

