#!/usr/bin/env python3
"""
Visa Policy Change Scheduler

This script runs periodic checks for visa policy changes and triggers alerts.
It can be run as a cron job or scheduled task.

Usage:
    python visa_scheduler.py --check-all
    python visa_scheduler.py --user-id 123
    python visa_scheduler.py --citizenship India --destination USA
"""

import argparse
import sys
import os
import requests
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

def get_supabase():
    """Get Supabase client."""
    from supabase_client import get_supabase
    return get_supabase()

def check_visa_changes_for_user(user_profile_id: int, supabase) -> Dict[str, Any]:
    """Check visa changes for a specific user."""
    print(f"Checking visa changes for user {user_profile_id}...")
    
    # Get user's visa requirements
    resp = supabase.table("visa_requirements").select("*") \
        .eq("user_profile_id", user_profile_id) \
        .order("last_updated", desc=True).execute()
    
    if not resp.data:
        return {"user_id": user_profile_id, "checked": 0, "alerts": 0}
    
    alerts_generated = 0
    checked_pairs = set()
    
    for req in resp.data:
        citizenship = req["citizenship_country"]
        destination = req["destination_country"]
        pair_key = f"{citizenship}→{destination}"
        
        if pair_key in checked_pairs:
            continue  # Skip duplicates
        checked_pairs.add(pair_key)
        
        # Trigger refresh for this pair
        try:
            print(f"citizenship: {citizenship}, destination: {destination}")
            print("=" * 60)
            refresh_url = f"http://localhost:5000/visa_info/{citizenship}/{destination}"
            params = {
                "user_profile_id": user_profile_id,
                "refresh": "true"
            }
            
            response = requests.get(refresh_url, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("agent_refresh_attempted"):
                    print(f"  ✓ Refreshed {pair_key}")
                    alerts_generated += 1
                else:
                    print(f"  - No refresh for {pair_key}")
            else:
                print(f"  ✗ Failed to refresh {pair_key}: {response.status_code}")
                
        except Exception as e:
            print(f"  ✗ Error refreshing {pair_key}: {e}")
    
    return {
        "user_id": user_profile_id,
        "checked": len(checked_pairs),
        "alerts": alerts_generated
    }

def check_visa_changes_for_pair(citizenship: str, destination: str, supabase) -> Dict[str, Any]:
    """Check visa changes for a specific citizenship→destination pair."""
    print(f"Checking visa changes for {citizenship} → {destination}...")
    
    # Get all users with this visa requirement
    resp = supabase.table("visa_requirements").select("user_profile_id") \
        .eq("citizenship_country", citizenship) \
        .eq("destination_country", destination) \
        .execute()
    
    if not resp.data:
        return {"pair": f"{citizenship}→{destination}", "checked": 0, "alerts": 0}
    
    user_ids = list(set([req["user_profile_id"] for req in resp.data]))
    alerts_generated = 0
    
    for user_id in user_ids:
        try:
            refresh_url = f"http://localhost:5000/visa_info/{citizenship}/{destination}"
            params = {
                "user_profile_id": user_id,
                "refresh": "true"
            }
            
            response = requests.get(refresh_url, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get("agent_refresh_attempted"):
                    print(f"  ✓ Refreshed for user {user_id}")
                    alerts_generated += 1
                else:
                    print(f"  - No refresh for user {user_id}")
            else:
                print(f"  ✗ Failed to refresh for user {user_id}: {response.status_code}")
                
        except Exception as e:
            print(f"  ✗ Error refreshing for user {user_id}: {e}")
    
    return {
        "pair": f"{citizenship}→{destination}",
        "checked": len(user_ids),
        "alerts": alerts_generated
    }

def check_all_visa_changes(supabase) -> Dict[str, Any]:
    """Check visa changes for all users."""
    print("Checking visa changes for all users...")
    
    # Get all unique user IDs with visa requirements
    resp = supabase.table("visa_requirements").select("user_profile_id") \
        .order("last_updated", desc=True).execute()
    
    if not resp.data:
        return {"total_users": 0, "total_alerts": 0}
    
    user_ids = list(set([req["user_profile_id"] for req in resp.data]))
    total_alerts = 0
    
    for user_id in user_ids:
        result = check_visa_changes_for_user(user_id, supabase)
        total_alerts += result["alerts"]
    
    return {
        "total_users": len(user_ids),
        "total_alerts": total_alerts
    }

def get_pending_alerts_summary(supabase) -> Dict[str, Any]:
    """Get summary of pending alerts."""
    print("Getting pending alerts summary...")
    
    # Get all pending alerts
    resp = supabase.table("visa_requirements").select("*") \
        .eq("alert_sent", False) \
        .order("last_updated", desc=True).execute()
    
    if not resp.data:
        return {"pending_alerts": 0, "users_with_alerts": 0}
    
    users_with_alerts = set()
    for req in resp.data:
        change_summary = req.get("change_summary", {})
        if change_summary.get("alert_needed", False):
            users_with_alerts.add(req["user_profile_id"])
    
    return {
        "pending_alerts": len(resp.data),
        "users_with_alerts": len(users_with_alerts),
        "alerts": resp.data
    }

def main():
    parser = argparse.ArgumentParser(description="Visa Policy Change Scheduler")
    parser.add_argument("--check-all", action="store_true", 
                       help="Check visa changes for all users")
    parser.add_argument("--user-id", type=int, 
                       help="Check visa changes for specific user ID")
    parser.add_argument("--citizenship", type=str, 
                       help="Check visa changes for specific citizenship")
    parser.add_argument("--destination", type=str, 
                       help="Check visa changes for specific destination")
    parser.add_argument("--summary", action="store_true", 
                       help="Get summary of pending alerts")
    parser.add_argument("--api-url", default="http://localhost:5000", 
                       help="API base URL")
    
    args = parser.parse_args()
    
    if not any([args.check_all, args.user_id, args.citizenship, args.destination, args.summary]):
        parser.print_help()
        return
    
    try:
        supabase = get_supabase()
        print(f"Visa Policy Change Scheduler - {datetime.now().isoformat()}")
        print("=" * 60)
        
        if args.summary:
            result = get_pending_alerts_summary(supabase)
            print(f"Pending alerts: {result['pending_alerts']}")
            print(f"Users with alerts: {result['users_with_alerts']}")
            
        elif args.check_all:
            result = check_all_visa_changes(supabase)
            print(f"Checked {result['total_users']} users")
            print(f"Generated {result['total_alerts']} alerts")
            
        elif args.user_id:
            result = check_visa_changes_for_user(args.user_id, supabase)
            print(f"Checked {result['checked']} visa pairs for user {result['user_id']}")
            print(f"Generated {result['alerts']} alerts")
            
        elif args.citizenship and args.destination:
            result = check_visa_changes_for_pair(args.citizenship, args.destination, supabase)
            print(f"Checked {result['checked']} users for {result['pair']}")
            print(f"Generated {result['alerts']} alerts")
            
        else:
            print("Error: --citizenship and --destination must be provided together")
            return
        
        print("=" * 60)
        print("Scheduler completed successfully")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
