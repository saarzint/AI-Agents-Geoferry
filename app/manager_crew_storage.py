"""
Storage functions for ManagerCrew coworker agent results.
These functions parse and store results from delegated agents into the database.
"""
import json
import re
from datetime import datetime
from .supabase_client import get_supabase
from .checklist_formatter import to_json_with_labels, to_markdown
from .utils import _detect_visa_changes


def store_application_requirement_results(user_id: int, agent_output: str) -> dict:
    """
    Store application requirement results from Application Requirement Agent.
    
    Args:
        user_id: User profile ID
        agent_output: Raw output from Application Requirement Agent
        
    Returns:
        dict with stored_count and status
    """
    try:
        supabase = get_supabase()
        stored_count = 0
        
        # Try to extract JSON from agent output
        cleaned_output = agent_output.strip()
        
        # Look for JSON objects in the output
        # Try to find structured JSON first
        json_match = re.search(r'\{[\s\S]*"university_name"[\s\S]*"program_name"[\s\S]*\}', cleaned_output)
        if not json_match:
            # Try to find any JSON object
            json_match = re.search(r'\{[\s\S]*\}', cleaned_output)
        
        if json_match:
            try:
                json_text = json_match.group(0)
                # Clean up JSON text
                normalized_json = json_text.strip()
                normalized_json = re.sub(r',(\s*[\]}])', r'\1', normalized_json)
                normalized_json = re.sub(r',\s*}', '}', normalized_json)
                normalized_json = re.sub(r',\s*]', ']', normalized_json)
                
                data = json.loads(normalized_json)
                
                # Convert single dict to list
                if isinstance(data, dict):
                    data = [data]
                
                for req in data:
                    # Extract university and program names
                    university = req.get("university_name") or req.get("university") or "Unknown"
                    program = req.get("program_name") or req.get("program") or "Unknown"
                    
                    # Format using checklist_formatter
                    formatted_json = to_json_with_labels(req)
                    formatted_markdown = to_markdown(req)
                    
                    # Structure according to application_requirements table schema
                    requirement_data = {
                        "user_profile_id": user_id,
                        "university": university,
                        "program": program,
                        "application_platform": req.get("application_platform"),
                        "deadlines": req.get("deadlines", {}),
                        "required_documents": req.get("required_documents", []),
                        "essay_prompts": req.get("essay_prompts", {}),
                        "portfolio_required": req.get("portfolio_required", False),
                        "interview": req.get("interview"),
                        "fee_info": req.get("fee_info", {}),
                        "test_policy": req.get("test_policy"),
                        "source_url": req.get("source_url"),
                        "fetched_at": datetime.now().isoformat(),
                        "is_ambiguous": req.get("is_ambiguous", False),
                        "reviewed_by": req.get("reviewed_by")
                    }
                    
                    # Check if entry exists
                    existing_entry_resp = supabase.table("application_requirements").select("id").eq("user_profile_id", user_id).eq("university", university).eq("program", program).execute()
                    
                    if existing_entry_resp.data:
                        # Update existing entry
                        existing_entry_id = existing_entry_resp.data[0]["id"]
                        supabase.table("application_requirements").update(requirement_data).eq("id", existing_entry_id).execute()
                    else:
                        # Insert new record
                        supabase.table("application_requirements").insert(requirement_data).execute()
                    
                    stored_count += 1
                    
            except (json.JSONDecodeError, Exception) as e:
                print(f"[ERROR] Failed to parse Application Requirement Agent output: {e}")
                return {"stored_count": 0, "status": "error", "error": str(e)}
        
        # Log agent report
        try:
            from .agent_event_handler import get_event_handler
            get_event_handler().log_agent_report(
                agent_name="Application Requirement Agent",
                user_id=user_id,
                payload={
                    "application_requirements_stored": stored_count,
                    "stored_at": datetime.now().isoformat(),
                    "source": "ManagerCrew delegation"
                }
            )
        except Exception as log_error:
            print(f"[WARN] Failed to log agent report: {log_error}")
        
        return {"stored_count": stored_count, "status": "success" if stored_count > 0 else "no_data"}
        
    except Exception as e:
        print(f"[ERROR] Exception in store_application_requirement_results: {str(e)}")
        return {"stored_count": 0, "status": "error", "error": str(e)}


def store_visa_information_results(user_id: int, agent_output: str) -> dict:
    """
    Store visa information results from Visa Information Agent.
    
    Args:
        user_id: User profile ID
        agent_output: Raw output from Visa Information Agent
        
    Returns:
        dict with stored_count and status
    """
    try:
        supabase = get_supabase()
        stored_count = 0
        
        # Get user profile to extract citizenship and destination
        profile_resp = supabase.table("user_profile").select("citizenship_country, destination_country").eq("id", user_id).execute()
        
        citizenship = None
        destination = None
        
        if profile_resp.data:
            citizenship = profile_resp.data[0].get("citizenship_country")
            destination = profile_resp.data[0].get("destination_country")
        
        # If citizenship/destination not in profile, try to extract from output or use defaults
        if not citizenship or not destination:
            # Try to extract from output text
            citizenship_match = re.search(r'citizenship[:\s]+([A-Za-z\s]+)', agent_output, re.IGNORECASE)
            destination_match = re.search(r'destination[:\s]+([A-Za-z\s]+)', agent_output, re.IGNORECASE)
            if citizenship_match:
                citizenship = citizenship_match.group(1).strip()
            if destination_match:
                destination = destination_match.group(1).strip()
        
        # If still not available, we can't store visa info without citizenship/destination
        if not citizenship or not destination:
            return {"stored_count": 0, "status": "skipped", "reason": "Missing citizenship_country or destination_country in profile"}
        
        # Try to extract JSON array from agent output
        cleaned_output = agent_output.strip()
        
        # Look for JSON array
        start_idx = cleaned_output.find('[')
        end_idx = cleaned_output.rfind(']')
        
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_content = cleaned_output[start_idx:end_idx + 1]
            try:
                data = json.loads(json_content)
                if isinstance(data, dict):
                    data = [data]
            except json.JSONDecodeError:
                # Try to find single JSON object
                brace_start = cleaned_output.find('{')
                brace_end = cleaned_output.rfind('}')
                if brace_start != -1 and brace_end != -1:
                    try:
                        data = json.loads(cleaned_output[brace_start:brace_end + 1])
                        if isinstance(data, dict):
                            data = [data]
                    except json.JSONDecodeError:
                        data = []
                else:
                    data = []
        else:
            # Try to parse as single object
            brace_start = cleaned_output.find('{')
            brace_end = cleaned_output.rfind('}')
            if brace_start != -1 and brace_end != -1:
                try:
                    data = json.loads(cleaned_output[brace_start:brace_end + 1])
                    if isinstance(data, dict):
                        data = [data]
                except json.JSONDecodeError:
                    data = []
            else:
                data = []
        
        # Process each visa requirement
        for item in data:
            new_data = {
                "visa_type": item.get("visa_type"),
                "documents": item.get("required_documents"),
                "process_steps": item.get("application_process"),
                "fees": item.get("application_fees"),
                "timelines": item.get("processing_time"),
                "interview": item.get("interview_required"),
                "post_graduation": item.get("post_graduation_options"),
                "source_url": item.get("source_url"),
                "disclaimer": item.get("disclaimer"),
                "notes": item.get("notes", [])
            }
            
            # Detect changes
            change_info = _detect_visa_changes(supabase, citizenship, destination, user_id, new_data)
            
            row = {
                "user_profile_id": user_id,
                "citizenship_country": citizenship,
                "destination_country": destination,
                **new_data,
                "fetched_at": item.get("fetched_at") or datetime.now().isoformat(),
                "last_updated": item.get("last_updated") or item.get("fetched_at") or datetime.now().isoformat(),
                "alert_sent": not change_info["alert_needed"],
                "change_summary": change_info
            }
            
            ins = supabase.table("visa_requirements").insert(row).execute()
            if ins.data:
                stored_count += 1
        
        # Log agent report
        try:
            from .agent_event_handler import get_event_handler
            get_event_handler().log_agent_report(
                agent_name="Visa Information Agent",
                user_id=user_id,
                payload={
                    "visa_requirements_stored": stored_count,
                    "citizenship": citizenship,
                    "destination": destination,
                    "stored_at": datetime.now().isoformat(),
                    "source": "ManagerCrew delegation"
                }
            )
        except Exception as log_error:
            print(f"[WARN] Failed to log agent report: {log_error}")
        
        return {"stored_count": stored_count, "status": "success" if stored_count > 0 else "no_data"}
        
    except Exception as e:
        print(f"[ERROR] Exception in store_visa_information_results: {str(e)}")
        return {"stored_count": 0, "status": "error", "error": str(e)}


def store_university_search_results(user_id: int, agent_output: str) -> dict:
    """
    Store university search results from University Search Agent.
    
    Args:
        user_id: User profile ID
        agent_output: Raw output from University Search Agent
        
    Returns:
        dict with stored_count and status
    """
    try:
        supabase = get_supabase()
        stored_count = 0
        
        # Try to extract JSON array from agent output
        cleaned_output = agent_output.strip()
        
        # Look for JSON array
        start_idx = cleaned_output.find('[')
        end_idx = cleaned_output.rfind(']')
        
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_content = cleaned_output[start_idx:end_idx + 1]
            try:
                universities = json.loads(json_content)
                if not isinstance(universities, list):
                    universities = []
            except json.JSONDecodeError:
                universities = []
        else:
            universities = []
        
        # Store university results
        for university in universities:
            if university.get("name"):  # Basic validation
                # Extract recommendation metadata
                recommendation_metadata = {
                    "data_completeness": university.get("data_completeness"),
                    "recommendation_confidence": university.get("recommendation_confidence"),
                    "preference_conflicts": university.get("preference_conflicts"),
                    "search_broadened": university.get("search_broadened"),
                    "missing_criteria": university.get("missing_criteria")
                }
                
                result_data = {
                    "user_profile_id": user_id,
                    "university_name": university.get("name"),
                    "location": university.get("location"),
                    "tuition": university.get("tuition"),
                    "acceptance_rate": university.get("acceptance_rate"),
                    "programs": university.get("programs", []),
                    "rank_category": university.get("rank_category"),
                    "why_fit": university.get("why_fit"),
                    "recommendation_metadata": recommendation_metadata,
                    "source": {
                        "agent_output": agent_output[:500],  # Store first 500 chars
                        "stored_at": datetime.now().isoformat(),
                        "source": "ManagerCrew delegation"
                    }
                }
                
                store_result = supabase.table("university_results").insert(result_data).execute()
                if store_result.data:
                    stored_count += 1
        
        # Log agent report
        try:
            from .agent_event_handler import get_event_handler
            get_event_handler().log_agent_report(
                agent_name="University Search Agent",
                user_id=user_id,
                payload={
                    "universities_found": len(universities),
                    "universities_stored": stored_count,
                    "stored_at": datetime.now().isoformat(),
                    "source": "ManagerCrew delegation"
                }
            )
        except Exception as log_error:
            print(f"[WARN] Failed to log agent report: {log_error}")
        
        return {"stored_count": stored_count, "status": "success" if stored_count > 0 else "no_data"}
        
    except Exception as e:
        print(f"[ERROR] Exception in store_university_search_results: {str(e)}")
        return {"stored_count": 0, "status": "error", "error": str(e)}


def store_scholarship_search_results(user_id: int, agent_output: str) -> dict:
    """
    Store scholarship search results from Scholarship Search Agent.
    Note: Scholarship results are typically stored by ScholarshipMatcherTool,
    but this function can parse and store if needed from direct agent output.
    
    Args:
        user_id: User profile ID
        agent_output: Raw output from Scholarship Search Agent
        
    Returns:
        dict with stored_count and status
    """
    try:
        supabase = get_supabase()
        stored_count = 0
        
        # Try to extract JSON array from agent output
        cleaned_output = agent_output.strip()
        
        # Look for JSON array
        start_idx = cleaned_output.find('[')
        end_idx = cleaned_output.rfind(']')
        
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_content = cleaned_output[start_idx:end_idx + 1]
            try:
                scholarships = json.loads(json_content)
                if not isinstance(scholarships, list):
                    scholarships = []
            except json.JSONDecodeError:
                scholarships = []
        else:
            scholarships = []
        
        # Note: ScholarshipMatcherTool usually handles storage, but we can store here if needed
        # For now, just log that scholarships were found
        # The actual storage happens via ScholarshipMatcherTool which the agent uses
        
        # Log agent report
        try:
            from .agent_event_handler import get_event_handler
            get_event_handler().log_agent_report(
                agent_name="Scholarship Search Agent",
                user_id=user_id,
                payload={
                    "scholarships_found": len(scholarships),
                    "stored_at": datetime.now().isoformat(),
                    "source": "ManagerCrew delegation",
                    "note": "Storage handled by ScholarshipMatcherTool"
                }
            )
        except Exception as log_error:
            print(f"[WARN] Failed to log agent report: {log_error}")
        
        return {"stored_count": stored_count, "status": "success", "note": "Storage handled by ScholarshipMatcherTool"}
        
    except Exception as e:
        print(f"[ERROR] Exception in store_scholarship_search_results: {str(e)}")
        return {"stored_count": 0, "status": "error", "error": str(e)}


def process_and_store_agent_results(user_id: int, crew_result) -> dict:
    """
    Process CrewAI execution result and store results from delegated agents.
    
    Args:
        user_id: User profile ID
        crew_result: CrewAI crew execution result object
        
    Returns:
        dict with storage results for each agent type
    """
    storage_results = {
        "application_requirement": {"stored_count": 0, "status": "not_found"},
        "visa_information": {"stored_count": 0, "status": "not_found"},
        "university_search": {"stored_count": 0, "status": "not_found"},
        "scholarship_search": {"stored_count": 0, "status": "not_found"}
    }
    
    try:
        # Access tasks from crew result
        if hasattr(crew_result, 'tasks'):
            for task in crew_result.tasks:
                agent_role = None
                agent_output = None
                
                # Get agent role from task
                if hasattr(task, 'agent') and task.agent:
                    agent_role = getattr(task.agent, 'role', None)
                
                # Get output from task
                if hasattr(task, 'output'):
                    agent_output = task.output
                elif hasattr(task, 'result'):
                    agent_output = task.result
                elif hasattr(task, 'raw'):
                    agent_output = task.raw
                
                if agent_output:
                    agent_output_str = str(agent_output) if not isinstance(agent_output, str) else agent_output
                    
                    # Route to appropriate storage function based on agent role
                    if agent_role == "Application Requirement Agent":
                        storage_results["application_requirement"] = store_application_requirement_results(user_id, agent_output_str)
                    elif agent_role == "Visa Information Agent":
                        storage_results["visa_information"] = store_visa_information_results(user_id, agent_output_str)
                    elif agent_role == "University Search Agent":
                        storage_results["university_search"] = store_university_search_results(user_id, agent_output_str)
                    elif agent_role == "Scholarship Search Agent":
                        storage_results["scholarship_search"] = store_scholarship_search_results(user_id, agent_output_str)
        
        # Also try to parse from raw output if tasks don't have structured output
        if hasattr(crew_result, 'raw'):
            raw_output = str(crew_result.raw)
            
            # First, try to extract JSON from tool outputs (more reliable than final answers)
            # Application Data Extraction Tool output
            if storage_results["application_requirement"]["status"] == "not_found":
                # Try multiple patterns to find the JSON
                app_patterns = [
                    r'Application Data Extraction Tool[\s\S]*?Tool Output:[\s\S]*?(\{[\s\S]*?"university_name"[\s\S]*?"program_name"[\s\S]*?"extracted_at"[\s\S]*?\})',
                    r'Application Data Extraction Tool[\s\S]*?Tool Output:[\s\S]*?(\{[\s\S]{100,5000}?\})',  # Fallback: any JSON object of reasonable size
                ]
                for pattern in app_patterns:
                    app_tool_match = re.search(pattern, raw_output, re.IGNORECASE | re.DOTALL)
                    if app_tool_match:
                        tool_json = app_tool_match.group(1)
                        # Try to find the complete JSON object by finding matching braces
                        brace_count = tool_json.count('{') - tool_json.count('}')
                        if brace_count > 0:
                            # Need to find more closing braces
                            remaining = raw_output[app_tool_match.end():]
                            for i, char in enumerate(remaining):
                                if char == '}':
                                    brace_count -= 1
                                    if brace_count == 0:
                                        tool_json = raw_output[app_tool_match.start(1):app_tool_match.end(1) + i + 1]
                                        break
                        print(f"[DEBUG] Found Application Data Extraction Tool output: {tool_json[:200]}...")
                        storage_results["application_requirement"] = store_application_requirement_results(user_id, tool_json)
                        break
                if storage_results["application_requirement"]["status"] == "not_found":
                    print(f"[DEBUG] Application Data Extraction Tool output not found in raw output")
            
            # Visa Scraper Tool output
            if storage_results["visa_information"]["status"] == "not_found":
                # Try multiple patterns to find the JSON
                visa_patterns = [
                    r'Visa Scraper Tool[\s\S]*?Tool Output:[\s\S]*?(\{[\s\S]*?"visa_type"[\s\S]*?"fetched_at"[\s\S]*?\})',
                    r'Visa Scraper Tool[\s\S]*?Tool Output:[\s\S]*?(\{[\s\S]{100,5000}?\})',  # Fallback: any JSON object of reasonable size
                ]
                for pattern in visa_patterns:
                    visa_tool_match = re.search(pattern, raw_output, re.IGNORECASE | re.DOTALL)
                    if visa_tool_match:
                        tool_json = visa_tool_match.group(1)
                        # Try to find the complete JSON object by finding matching braces
                        brace_count = tool_json.count('{') - tool_json.count('}')
                        if brace_count > 0:
                            # Need to find more closing braces
                            remaining = raw_output[visa_tool_match.end():]
                            for i, char in enumerate(remaining):
                                if char == '}':
                                    brace_count -= 1
                                    if brace_count == 0:
                                        tool_json = raw_output[visa_tool_match.start(1):visa_tool_match.end(1) + i + 1]
                                        break
                        print(f"[DEBUG] Found Visa Scraper Tool output: {tool_json[:200]}...")
                        storage_results["visa_information"] = store_visa_information_results(user_id, tool_json)
                        break
                if storage_results["visa_information"]["status"] == "not_found":
                    print(f"[DEBUG] Visa Scraper Tool output not found in raw output")
            
            # University Search Agent - look for JSON array in Final Answer
            if storage_results["university_search"]["status"] == "not_found":
                university_pattern = r'Agent: University Search Agent[\s\S]*?Final Answer:[\s\S]*?(\[[\s\S]*?\]|[\s\S]*?\{[\s\S]*?"safety_universities"[\s\S]*?\}[\s\S]*?\{[\s\S]*?"target_universities"[\s\S]*?\}[\s\S]*?\{[\s\S]*?"reach_universities"[\s\S]*?\})'
                university_match = re.search(university_pattern, raw_output, re.IGNORECASE | re.DOTALL)
                if university_match:
                    agent_output = university_match.group(0)
                    storage_results["university_search"] = store_university_search_results(user_id, agent_output)
            
            # Scholarship Search Agent - ScholarshipMatcherTool handles storage, but check final answer
            if storage_results["scholarship_search"]["status"] == "not_found":
                scholarship_pattern = r'Agent: Scholarship Search Agent[\s\S]*?Final Answer:[\s\S]*?(?=Agent:|$)'
                scholarship_match = re.search(scholarship_pattern, raw_output, re.IGNORECASE | re.DOTALL)
                if scholarship_match:
                    agent_output = scholarship_match.group(0)
                    storage_results["scholarship_search"] = store_scholarship_search_results(user_id, agent_output)
            
            # Fallback: Try to find agent final answers if tool outputs weren't found
            agent_patterns = [
                (r'Agent: Application Requirement Agent[\s\S]*?Final Answer:[\s\S]*?(?=Agent:|$)', "Application Requirement Agent"),
                (r'Agent: Visa Information Agent[\s\S]*?Final Answer:[\s\S]*?(?=Agent:|$)', "Visa Information Agent"),
                (r'Agent: University Search Agent[\s\S]*?Final Answer:[\s\S]*?(?=Agent:|$)', "University Search Agent"),
                (r'Agent: Scholarship Search Agent[\s\S]*?Final Answer:[\s\S]*?(?=Agent:|$)', "Scholarship Search Agent"),
            ]
            
            for pattern, agent_name in agent_patterns:
                if agent_name == "Application Requirement Agent" and storage_results["application_requirement"]["status"] == "not_found":
                    matches = re.finditer(pattern, raw_output, re.IGNORECASE | re.DOTALL)
                    for match in matches:
                        agent_output = match.group(0)
                        storage_results["application_requirement"] = store_application_requirement_results(user_id, agent_output)
                        break
                elif agent_name == "Visa Information Agent" and storage_results["visa_information"]["status"] == "not_found":
                    matches = re.finditer(pattern, raw_output, re.IGNORECASE | re.DOTALL)
                    for match in matches:
                        agent_output = match.group(0)
                        storage_results["visa_information"] = store_visa_information_results(user_id, agent_output)
                        break
                elif agent_name == "University Search Agent" and storage_results["university_search"]["status"] == "not_found":
                    matches = re.finditer(pattern, raw_output, re.IGNORECASE | re.DOTALL)
                    for match in matches:
                        agent_output = match.group(0)
                        storage_results["university_search"] = store_university_search_results(user_id, agent_output)
                        break
                elif agent_name == "Scholarship Search Agent" and storage_results["scholarship_search"]["status"] == "not_found":
                    matches = re.finditer(pattern, raw_output, re.IGNORECASE | re.DOTALL)
                    for match in matches:
                        agent_output = match.group(0)
                        storage_results["scholarship_search"] = store_scholarship_search_results(user_id, agent_output)
                        break
        
        return storage_results
        
    except Exception as e:
        print(f"[ERROR] Exception in process_and_store_agent_results: {str(e)}")
        return storage_results

