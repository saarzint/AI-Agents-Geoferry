from flask import Flask, request, jsonify
from http import HTTPStatus
import json
import sys
import os
import re
from datetime import datetime, timedelta
from .supabase_client import get_supabase
from .utils import _generate_visa_report, _generate_html_report, _detect_visa_changes

import requests

from app.checklist_formatter import to_json_with_labels, to_markdown

# Add agents module to path
agents_path = os.path.join(os.path.dirname(__file__), '..', 'agents', 'src')
sys.path.append(os.path.abspath(agents_path))

def _validate_user_exists(user_profile_id: int) -> tuple[bool, dict]:
	"""
	Validate if a user profile exists in the database.
	Returns (exists, response_data) where response_data is None if user exists,
	or error response dict if user doesn't exist.
	"""
	try:
		supabase = get_supabase()
		profile_resp = supabase.table("user_profile").select("id").eq("id", user_profile_id).execute()
		
		if not profile_resp.data:
			return False, {
				"error": f"User profile {user_profile_id} not found",
				"user_profile_id": user_profile_id,
				"suggestion": "Please verify the user_profile_id exists in the database"
			}
		
		return True, None
	except Exception as exc:
		return False, {
			"error": f"Failed to validate user profile: {str(exc)}",
			"user_profile_id": user_profile_id
		}

def register_routes(app: Flask) -> None:
	@app.get("/")
	def home():
		return jsonify({
			"message": "Welcome to PG Admit - AI AGENTS",
			"version": "1.0.0",
			"endpoints": {
				"health": "/health",
				"search_universities": "/search_universities",
				"search_scholarships": "/search_scholarships",
				"get_university_results": "/results/<user_profile_id>",
				"get_scholarship_results": "/results/scholarships/<user_profile_id>",
				"fetch_application_requirements": "/fetch_application_requirements",
				"get_application_requirements": "/application_requirements/<university>/<program>",
				"visa_info": "/visa_info",
				"get_visa_info": "/visa_info/<citizenship>/<destination>",
				"visa_report": "/visa_report/<citizenship>/<destination>",
				"get_visa_alerts": "/visa_alerts",
				"mark_visa_alerts_sent": "/visa_alerts/mark_sent",
				"admissions_summary": "/admissions/summary/<user_id>",
				"admissions_next_steps": "/admissions/next_steps/<user_id>",
				"update_admissions_stage": "/admissions/update_stage",
				"log_agent_report": "/admissions/log_agent_report"
			}
		}), HTTPStatus.OK
	
	@app.get("/health")
	def health_check():
		return jsonify({
			"status": "healthy",
			"message": "PG Admit API is running"
		}), HTTPStatus.OK
		
	@app.post("/search_universities")
	def search_universities():
		payload = request.get_json(silent=True) or {}
		user_profile_id = payload.get("user_profile_id")
		
		if not user_profile_id:
			return jsonify({"error": "user_profile_id is required"}), HTTPStatus.BAD_REQUEST
		
		try:
			supabase = get_supabase()
			
			# Get user profile snapshot for logging
			profile_resp = supabase.table("user_profile").select("*").eq("id", user_profile_id).execute()
			if not profile_resp.data:
				return jsonify({"error": f"User profile {user_profile_id} not found"}), HTTPStatus.NOT_FOUND
			
			profile_snapshot = {
				"timestamp": datetime.now().isoformat(),
				"profile": profile_resp.data[0]
			}
			
			# Log search request with profile snapshot
			search_payload = {
				**payload,
				"profile_snapshot": profile_snapshot,
				"request_timestamp": datetime.now().isoformat()
			}
			
			search_result = supabase.table("search_requests").insert({
				"user_profile_id": user_profile_id,
				"request_payload": search_payload,
			}).execute()
			
			if not search_result.data:
				return jsonify({"error": "Failed to log search request"}), HTTPStatus.INTERNAL_SERVER_ERROR
			
			search_id = search_result.data[0]["id"]
			
			# Execute CrewAI agent and store results
			try:
				from agents.crew import SearchCrew
				# Use user-provided search_request if available, else fallback to default
				search_request = payload.get("search_request", "Find universities that match my profile")
				# Run the agent with retry loop for invalid JSON
				inputs = {
					'user_id': user_profile_id,
					'search_request': search_request,
					'current_year': str(datetime.now().year),
					'next_year': str(datetime.now().year + 1)
				}
				
				crew = SearchCrew()
				# Execute only the university search task
				university_task = crew.university_search_task()
				university_agent = crew.university_search_agent()
				
				# Create a crew with just the university agent and task
				from crewai import Crew, Process
				university_crew = Crew(
					agents=[university_agent],
					tasks=[university_task],
					process=Process.sequential,
					verbose=True
				)
				universities = None
				last_error = None
				
				# Try up to 3 times to get valid JSON
				for attempt in range(3):
					try:
						print(f"\nSTARTING CREWAI SEARCH - ATTEMPT {attempt + 1}")
						print(f"User ID: {user_profile_id}")
						print(f"Search inputs: {inputs}")
						print("=" * 60)
						
						result = university_crew.kickoff(inputs=inputs)
						
						# Parse agent output
						if hasattr(result, 'raw'):
							agent_output = result.raw
						else:
							agent_output = str(result)
						
						print(f"\nRAW AGENT OUTPUT - ATTEMPT {attempt + 1}")
						print("=" * 60)
						print(agent_output)
						print("=" * 60)
						
						# Clean and parse JSON
						cleaned_output = agent_output.strip()
						
						# Enhanced JSON extraction to handle various agent output formats
						universities = None
						
						# Strategy 1: Look for JSON array with [ and ]
						start_idx = cleaned_output.find('[')
						end_idx = cleaned_output.rfind(']')
						
						if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
							json_content = cleaned_output[start_idx:end_idx + 1]
							try:
								universities = json.loads(json_content)
								if isinstance(universities, list):
									print(f"✅ Found JSON array using bracket extraction")
								else:
									universities = None
							except:
								universities = None
						
						# Strategy 2: If no array found, check if output contains tool execution metadata
						if universities is None:
							print(f"No JSON array found, checking for tool execution format...")
							if "Action" in cleaned_output and "Profile Query Tool" in cleaned_output:
								print(f"Agent returned tool execution format instead of final results")
								print(f"   This suggests the agent didn't complete the university search task")
								raise ValueError("Agent returned incomplete results - tool execution format detected")
							
							# Strategy 3: Try to parse entire output as fallback
							try:
								universities = json.loads(cleaned_output)
								if not isinstance(universities, list):
									raise ValueError("Expected JSON array")
								print(f"✅ Found JSON using full output parsing")
							except:
								raise ValueError("Could not extract valid JSON array from agent output")
						
						# If we get here, JSON is valid - break out of retry loop
						print(f"\n✅ JSON PARSING SUCCESSFUL - ATTEMPT {attempt + 1}")
						print(f"Found {len(universities)} universities")
						print("=" * 60)
						
						break
						
					except (json.JSONDecodeError, ValueError) as e:
						last_error = e
						if attempt < 2:  # Not the last attempt
							print(f"Retrying... (attempt {attempt + 2}/3)")
							continue
						else:
							# Last attempt failed
							print(f"\nALL ATTEMPTS FAILED - RETURNING ERROR")
							print("=" * 60)
							return jsonify({
								"error": "Agent returned invalid JSON after 3 attempts",
								"search_id": search_id,
								"raw_output": agent_output[:1000] if 'agent_output' in locals() else "No output",
								"json_error": str(last_error)
							}), HTTPStatus.INTERNAL_SERVER_ERROR
				
				# Store university results
				stored_count = 0
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
						
						# Acceptance Rate Formula: (Number of Admitted Students / Total Number of Applicants) × 100
						# This represents the percentage of applicants who are admitted to the university
						# Lower rates indicate more selective/competitive universities
						# Example: 4% = Very selective (Stanford), 50% = Moderately selective (CSU)

						result_data = {
							"user_profile_id": user_profile_id,
							"search_id": search_id,
							"university_name": university.get("name"),
							"location": university.get("location"),
							"tuition": university.get("tuition"),
							"acceptance_rate": university.get("acceptance_rate"),
							"programs": university.get("programs", []),
							"rank_category": university.get("rank_category"),
							"why_fit": university.get("why_fit"),
							"recommendation_metadata": recommendation_metadata,
							"source": {
								"agent_output": agent_output,
								"stored_at": datetime.now().isoformat()
							}
						}
						
						store_result = supabase.table("university_results").insert(result_data).execute()
						if store_result.data:
							stored_count += 1
				
				# Log agent report to agent_reports_log
				from .agent_event_handler import get_event_handler
				get_event_handler().log_agent_report(
					agent_name="University Search Agent",
					user_id=user_profile_id,
					payload={
						"universities_found": len(universities),
						"universities_stored": stored_count,
						"search_id": search_id,
						"stored_at": datetime.now().isoformat()
					}
				)
				
				return jsonify({
					"message": "Search completed and results stored",
					"search_id": search_id,
					"universities_found": len(universities),
					"universities_stored": stored_count,
					"results_endpoint": f"/results/{user_profile_id}"
				}), HTTPStatus.OK
				
			except ImportError:
				return jsonify({
					"error": "CrewAI agents not available",
					"search_id": search_id,
					"message": "Search logged but agent processing failed"
				}), HTTPStatus.INTERNAL_SERVER_ERROR
			except Exception as e:
				return jsonify({
					"error": f"Agent execution failed: {str(e)}",
					"search_id": search_id
				}), HTTPStatus.INTERNAL_SERVER_ERROR
			
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR

	@app.get("/results/<int:user_profile_id>")
	def get_results(user_profile_id: int):
		try:
			supabase = get_supabase()
			
			# Get university results
			resp = supabase.table("university_results").select("*") \
				.eq("user_profile_id", user_profile_id) \
				.order("created_at", desc=True).limit(100).execute()
			
			# Get latest search info for context
			search_resp = supabase.table("search_requests").select("id, created_at, request_payload") \
				.eq("user_profile_id", user_profile_id) \
				.order("created_at", desc=True).limit(1).execute()
			
			response_data = {
				"user_profile_id": user_profile_id,
				"results": resp.data or [],
				"results_count": len(resp.data) if resp.data else 0
			}
			
			# Add latest search context
			if search_resp.data:
				latest_search = search_resp.data[0]
				response_data["latest_search"] = {
					"search_id": latest_search["id"],
					"timestamp": latest_search["created_at"],
					"has_profile_snapshot": "profile_snapshot" in latest_search.get("request_payload", {})
				}
			
			return jsonify(response_data), HTTPStatus.OK
			
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR

	@app.post("/search_scholarships")
	def search_scholarships():
		"""
		Execute scholarship search for a user profile.
		
		POST /search_scholarships
		Body: {
			"user_profile_id": int, 
			"delta_search": bool (optional) - only search based on profile changes,
			"changed_fields": [str] (optional) - which fields changed for delta search
		}
		"""
		payload = request.get_json(silent=True) or {}
		user_profile_id = payload.get("user_profile_id")
		delta_search = payload.get("delta_search", False)
		changed_fields = payload.get("changed_fields", [])
		
		if not user_profile_id:
			return jsonify({"error": "user_profile_id is required"}), HTTPStatus.BAD_REQUEST
		
		try:
			supabase = get_supabase()
			
			# Verify user profile exists
			profile_resp = supabase.table("user_profile").select("*").eq("id", user_profile_id).execute()
			if not profile_resp.data:
				return jsonify({"error": f"User profile {user_profile_id} not found"}), HTTPStatus.NOT_FOUND
			
			user_profile = profile_resp.data[0]
			
			# SIMPLIFIED APPROACH: Always use unified full search logic
			# This eliminates the complex delta vs full search distinction that was causing duplicates
			# Execute Scholarship Search Agent
			try:
				from agents.crew import SearchCrew
				
				# UNIFIED APPROACH: Always use comprehensive 'full' search logic
				# Whether triggered manually or by profile changes, same comprehensive behavior:
				# - Complete scholarship discovery and matching
				# - Automatic duplicate removal and expiration cleanup  
				# - Profile Changes Tool called for audit when change-triggered
				search_type_to_use = "full"  # Unified comprehensive search approach
				
				# Run the scholarship agent
				inputs = {
					'user_id': user_profile_id,
					'search_type': search_type_to_use,  # Always use 'full' for reliability
					'profile_triggered': delta_search,  # Pass if this was triggered by profile changes
					'changed_fields': changed_fields if delta_search else [],  # Pass what changed
					'current_year': str(datetime.now().year),
					'next_year': str(datetime.now().year + 1)
				}
				
				crew = SearchCrew()
				# Execute only the scholarship search task
				scholarship_task = crew.scholarship_search_task()
				scholarship_agent = crew.scholarship_search_agent()
				
				# Create a crew with just the scholarship agent and task
				from crewai import Crew, Process
				scholarship_crew = Crew(
					agents=[scholarship_agent],
					tasks=[scholarship_task],
					process=Process.sequential,
					verbose=True
				)
				
				scholarships = None
				last_error = None
				
				# Try up to 3 times to get valid JSON
				for attempt in range(3):
					try:
						result = scholarship_crew.kickoff(inputs=inputs)
						
						# Parse agent output
						if hasattr(result, 'raw'):
							agent_output = result.raw
						else:
							agent_output = str(result)
						
						# Clean and parse JSON
						cleaned_output = agent_output.strip()
						
						# Extract JSON array
						start_idx = cleaned_output.find('[')
						end_idx = cleaned_output.rfind(']')
						
						if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
							json_content = cleaned_output[start_idx:end_idx + 1]
							try:
								scholarships = json.loads(json_content)
								if isinstance(scholarships, list):
									break
								else:
									scholarships = None
							except:
								scholarships = None
						
						if scholarships is None:
							# Try to parse entire output as fallback
							try:
								scholarships = json.loads(cleaned_output)
								if not isinstance(scholarships, list):
									raise ValueError("Expected JSON array")
								break
							except:
								raise ValueError("Could not extract valid JSON array from scholarship agent output")
						
					except (json.JSONDecodeError, ValueError) as e:
						last_error = e
						if attempt < 2:  # Not the last attempt
							continue
						else:
							# Last attempt failed
							return jsonify({
								"error": "Scholarship agent returned invalid JSON after 3 attempts",
								"user_profile_id": user_profile_id,
								"raw_output": agent_output[:1000] if 'agent_output' in locals() else "No output",
								"json_error": str(last_error)
							}), HTTPStatus.INTERNAL_SERVER_ERROR
				
				# Query database to get total count of scholarships for this user
				try:
					total_scholarships = supabase.table("scholarship_results").select("id").eq("user_profile_id", user_profile_id).execute()
					total_count = len(total_scholarships.data) if total_scholarships.data else 0
				except Exception as e:
					print(f"Error querying scholarship count: {e}")
					total_count = 0
				
				# Log agent report to agent_reports_log
				from .agent_event_handler import get_event_handler
				get_event_handler().log_agent_report(
					agent_name="Scholarship Search Agent",
					user_id=user_profile_id,
					payload={
						"scholarships_found": len(scholarships) if scholarships else 0,
						"total_scholarships_stored": total_count,
						"stored_at": datetime.now().isoformat()
					}
				)
				
				# Return formatted JSON for scholarship search completion
				search_response = {
					"message": "Scholarship search completed successfully",
					"user_profile_id": user_profile_id,
					"total_scholarships_stored": total_count,
					"results_endpoint": f"/results/scholarships/{user_profile_id}",
					"note": "Expired scholarships automatically filtered out before storage",
					"disclaimer": "This system provides scholarship opportunity matching based on eligibility criteria. We cannot guarantee that users will win any scholarships."
				}
				
				return app.response_class(
					response=json.dumps(search_response, indent=2, ensure_ascii=False),
					status=HTTPStatus.OK,
					mimetype='application/json'
				)
				
			except ImportError:
				return jsonify({
					"error": "Scholarship Search Agent not available",
					"message": "Scholarship search infrastructure ready but agent not implemented",
					"user_profile_id": user_profile_id
				}), HTTPStatus.SERVICE_UNAVAILABLE
			except Exception as e:
				return jsonify({
					"error": f"Scholarship search execution failed: {str(e)}",
					"user_profile_id": user_profile_id
				}), HTTPStatus.INTERNAL_SERVER_ERROR
			
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR

	@app.get("/results/scholarships/<int:user_profile_id>")
	def get_scholarship_results(user_profile_id: int):
		"""
		Retrieve scholarship search results for a user.
		
		GET /results/scholarships/{user_profile_id}
		Optional query params:
		- active_only=true (only scholarships with future deadlines)
		- category=Merit|Need-based|Athletic|etc
		- limit=N (max results to return)
		"""
		try:
			supabase = get_supabase()
			
			# Parse query parameters safely
			active_only = request.args.get('active_only', 'false').lower() == 'true'
			category_filter = request.args.get('category')
			try:
				limit = int(request.args.get('limit', '100'))
			except (ValueError, TypeError):
				limit = 100
			
			# Build and execute query
			query = supabase.table("scholarship_results").select("*").eq("user_profile_id", user_profile_id)
			
			if active_only:
				query = query.gte("deadline", datetime.now().date().isoformat())
			if category_filter:
				query = query.eq("category", category_filter)
			
			resp = query.order("deadline", desc=False).order("matched_at", desc=True).limit(limit).execute()
			
			# Get profile changes
			changes_resp = supabase.table("user_profile_changes").select("field_name, changed_at") \
				.eq("user_profile_id", user_profile_id).order("changed_at", desc=True).limit(5).execute()
			
			# Process scholarships
			scholarships = resp.data or []
			
			# If no scholarships found, return simple message
			if not scholarships:
				return app.response_class(
					response=json.dumps({
						"message": f"No scholarship results found for user {user_profile_id}",
						"user_profile_id": user_profile_id,
						"total_scholarships": 0,
						"suggestion": "Try running a scholarship search first with: POST /search_scholarships"
					}, indent=2),
					status=HTTPStatus.OK,
					mimetype='application/json'
				)
			
			urgent_scholarships = []
			upcoming_scholarships = []
			future_scholarships = []
			expired_scholarships = []
			current_date = datetime.now().date()
			
			for scholarship in scholarships:
				if scholarship.get("deadline"):
					try:
						deadline_str = scholarship["deadline"]
						# Handle both string and date objects
						if isinstance(deadline_str, str):
							deadline_date = datetime.fromisoformat(deadline_str).date()
						else:
							deadline_date = deadline_str
						
						days_until_deadline = (deadline_date - current_date).days
						scholarship["days_until_deadline"] = days_until_deadline
						
						if days_until_deadline < 0:
							expired_scholarships.append(scholarship)
						elif days_until_deadline <= 30:
							urgent_scholarships.append(scholarship)
						elif days_until_deadline <= 90:
							upcoming_scholarships.append(scholarship)
						else:
							future_scholarships.append(scholarship)
					except (ValueError, TypeError, AttributeError) as e:
						# If deadline parsing fails, add to future scholarships
						scholarship["days_until_deadline"] = None
						future_scholarships.append(scholarship)
				else:
					scholarship["days_until_deadline"] = None
					future_scholarships.append(scholarship)
			
			# Calculate summary statistics - keep award amounts as text
			active_count = 0
			
			for s in scholarships:
				# Count active scholarships
				if s.get("days_until_deadline") is None or s.get("days_until_deadline", -1) >= 0:
					active_count += 1
			
			response_data = {
				"user_profile_id": user_profile_id,
				"scholarships": {
					"urgent": urgent_scholarships,      # < 30 days
					"upcoming": upcoming_scholarships,  # 30-90 days  
					"future": future_scholarships,      # > 90 days
					"expired": expired_scholarships     # Past deadline
				},
				"summary": {
					"total_scholarships": len(scholarships),
					"active_scholarships": active_count,
					"urgent_count": len(urgent_scholarships),
					"note": "Award amounts displayed as text to preserve original format",
					"categories": list(set(s.get("category") for s in scholarships if s.get("category")))
				},
				"recent_profile_changes": changes_resp.data or [],
				"filters_applied": {
					"active_only": active_only,
					"category": category_filter,
					"limit": limit
				},
				"disclaimer": "This system provides scholarship opportunity matching based on eligibility criteria. We cannot guarantee that users will win any scholarships."
			}
			
			# Return formatted JSON for better readability
			return app.response_class(
				response=json.dumps(response_data, indent=2, ensure_ascii=False),
				status=HTTPStatus.OK,
				mimetype='application/json'
			)
			
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR

	# =======================================================
	# Visa Information Endpoints
	# =======================================================
	@app.post("/visa_info")
	def visa_info():
		"""
		Trigger visa information retrieval for a citizenship → destination pair.
		
		POST /visa_info
		Body: { "citizenship": "India", "destination": "USA", "refresh": bool (optional) }
		"""

		# add logging
		print("Visa info request received")
		print(request.get_json())
		print("=" * 60)
		payload = request.get_json(silent=True) or {}
		citizenship = payload.get("citizenship")
		destination = payload.get("destination")
		user_profile_id = payload.get("user_profile_id")
		refresh = bool(payload.get("refresh", True))

		if not citizenship or not destination:
			return jsonify({"error": "citizenship and destination are required"}), HTTPStatus.BAD_REQUEST
		if not user_profile_id:
			return jsonify({"error": "user_profile_id is required"}), HTTPStatus.BAD_REQUEST
		
		# Validate user exists before proceeding
		user_exists, error_response = _validate_user_exists(user_profile_id)
		if not user_exists:
			return jsonify(error_response), HTTPStatus.NOT_FOUND
		
		try:
			supabase = get_supabase()

			# Attempt to run Visa Agent if available
			agent_used = False
			try:
				from agents.crew import SearchCrew
				crew = SearchCrew()
				print("Crew created")
				print("=" * 60)
				# Use implemented visa search agent/task
				visa_task_getter = getattr(crew, 'visa_search_task', None)
				visa_agent_getter = getattr(crew, 'visa_search_agent', None)
				if visa_task_getter and visa_agent_getter and refresh:
					from crewai import Crew, Process
					visa_task_obj = visa_task_getter()
					visa_agent_obj = visa_agent_getter()
					visa_crew = Crew(
						agents=[visa_agent_obj],
						tasks=[visa_task_obj],
						process=Process.sequential,
						verbose=True
					)
					inputs = {
						'citizenship_country': citizenship,
						'destination_country': destination,
						'user_id': user_profile_id
					}
					print("Inputs:")
					print(inputs)
					print("=" * 60)
					result = visa_crew.kickoff(inputs=inputs)
					agent_output = result.raw if hasattr(result, 'raw') else str(result)
					# Extract JSON object or array from output
					print("Agent output:")
					print(agent_output)
					print("=" * 60)
					cleaned = agent_output.strip()
					stored_rows = 0
					try:
						# Prefer array, else single object
						start_idx = cleaned.find('[')
						end_idx = cleaned.rfind(']')
						if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
							data = json.loads(cleaned[start_idx:end_idx + 1])
						else:
							brace_start = cleaned.find('{')
							brace_end = cleaned.rfind('}')
							data = json.loads(cleaned[brace_start:brace_end + 1])
						# Normalize to list
						if isinstance(data, dict):
							data = [data]
						# Process each visa requirement with change detection
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
							change_info = _detect_visa_changes(supabase, citizenship, destination, user_profile_id, new_data)
							
							row = {
								"user_profile_id": user_profile_id,
								"citizenship_country": citizenship,
								"destination_country": destination,
								**new_data,
								"fetched_at": item.get("fetched_at"),
								"last_updated": item.get("last_updated") or item.get("fetched_at"),
								"alert_sent": not change_info["alert_needed"],  # Set to True if no alert needed
								"change_summary": change_info
							}
							
							ins = supabase.table("visa_requirements").insert(row).execute()
							if ins.data:
								stored_rows += 1
								print(f"Change detection: {change_info}")
						
						# Log agent report to agent_reports_log
						from .agent_event_handler import get_event_handler
						get_event_handler().log_agent_report(
							agent_name="Visa Agent",
							user_id=user_profile_id,
							payload={
								"visa_requirements_stored": stored_rows,
								"citizenship": citizenship,
								"destination": destination,
								"stored_at": datetime.now().isoformat()
							}
						)
						
						agent_used = True
					except Exception:
						# Fall back to cache only
						agent_used = False
			except Exception as e:
				print("Error creating crew")
				print(e)
				print("=" * 60)
				# Agent infra not available; continue with cache
				agent_used = False

			# Return current cached data for the pair
			print("Returning cached data")
			print("=" * 60)
			resp = supabase.table("visa_requirements").select("*") \
				.eq("citizenship_country", citizenship) \
				.eq("destination_country", destination) \
				.eq("user_profile_id", user_profile_id) \
				.order("last_updated", desc=True).limit(50).execute()
			return app.response_class(
				response=json.dumps({
					"citizenship": citizenship,
					"destination": destination,
					"count": len(resp.data) if resp.data else 0,
					"agent_refresh_attempted": agent_used and refresh,
					"results": resp.data or []
				}, indent=2, ensure_ascii=False),
				status=HTTPStatus.OK,
				mimetype='application/json'
			)
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR

	@app.get("/visa_info/<string:citizenship>/<string:destination>")
	def get_visa_info(citizenship: str, destination: str):
		"""
		Return cached or refreshed visa data for citizenship → destination.
		
		Query param: refresh=true to attempt fresh retrieval via agent (if available).
		"""
		try:
			user_profile_id = request.args.get('user_profile_id')
			if not user_profile_id:
				return jsonify({"error": "user_profile_id is required"}), HTTPStatus.BAD_REQUEST
			
			# Validate user exists before proceeding
			user_exists, error_response = _validate_user_exists(int(user_profile_id))
			if not user_exists:
				return jsonify(error_response), HTTPStatus.NOT_FOUND
			
			supabase = get_supabase()
			refresh = request.args.get('refresh', 'false').lower() == 'true'
			agent_used = False
			if refresh:
				try:
					from agents.crew import SearchCrew
					crew = SearchCrew()
					visa_task_getter = getattr(crew, 'visa_search_task', None)
					visa_agent_getter = getattr(crew, 'visa_search_agent', None)
					if visa_task_getter and visa_agent_getter:
						from crewai import Crew, Process
						visa_task_obj = visa_task_getter()
						visa_agent_obj = visa_agent_getter()
						visa_crew = Crew(
							agents=[visa_agent_obj],
							tasks=[visa_task_obj],
							process=Process.sequential,
							verbose=True
						)
						result = visa_crew.kickoff(inputs={'citizenship_country': citizenship, 'destination_country': destination, 'user_id': user_profile_id})
						agent_output = result.raw if hasattr(result, 'raw') else str(result)
						print(agent_output)
						cleaned = agent_output.strip()
						try:
							start_idx = cleaned.find('[')
							end_idx = cleaned.rfind(']')
							if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
								data = json.loads(cleaned[start_idx:end_idx + 1])
							else:
								brace_start = cleaned.find('{')
								brace_end = cleaned.rfind('}')
								data = json.loads(cleaned[brace_start:brace_end + 1])
							if isinstance(data, dict):
								data = [data]
							# Process each visa requirement with change detection
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
								change_info = _detect_visa_changes(supabase, citizenship, destination, user_profile_id, new_data)
								
								row = {
									"user_profile_id": user_profile_id,
									"citizenship_country": citizenship,
									"destination_country": destination,
									**new_data,
									"fetched_at": item.get("fetched_at"),
									"last_updated": item.get("last_updated") or item.get("fetched_at"),
									"alert_sent": not change_info["alert_needed"],  # Set to True if no alert needed
									"change_summary": change_info
								}
								supabase.table("visa_requirements").insert(row).execute()
							agent_used = True
						except Exception:
							agent_used = False
				except Exception:
					agent_used = False

			resp = supabase.table("visa_requirements").select("*") \
				.eq("citizenship_country", citizenship) \
				.eq("destination_country", destination) \
				.eq("user_profile_id", user_profile_id) \
				.order("last_updated", desc=True).limit(50).execute()
			return app.response_class(
				response=json.dumps({
					"citizenship": citizenship,
					"destination": destination,
					"count": len(resp.data) if resp.data else 0,
					"agent_refresh_attempted": agent_used and refresh,
					"results": resp.data or []
				}, indent=2, ensure_ascii=False),
				status=HTTPStatus.OK,
				mimetype='application/json'
			)
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR

	@app.get("/visa_report/<string:citizenship>/<string:destination>")
	def get_visa_report(citizenship: str, destination: str):
		"""
		Generate user-facing visa checklist/report from structured data.
		
		GET /visa_report/{citizenship}/{destination}
		Query params:
		- user_profile_id: required
		- format: json|html (default: json)
		"""
		try:
			user_profile_id = request.args.get('user_profile_id')
			format_type = request.args.get('format', 'json').lower()
			
			if not user_profile_id:
				return jsonify({"error": "user_profile_id is required"}), HTTPStatus.BAD_REQUEST
			
			# Validate user exists before proceeding
			user_exists, error_response = _validate_user_exists(int(user_profile_id))
			if not user_exists:
				return jsonify(error_response), HTTPStatus.NOT_FOUND
			
			supabase = get_supabase()
			
			# Get latest visa requirements
			resp = supabase.table("visa_requirements").select("*") \
				.eq("citizenship_country", citizenship) \
				.eq("destination_country", destination) \
				.eq("user_profile_id", user_profile_id) \
				.order("last_updated", desc=True).limit(1).execute()
			
			if not resp.data:
				return jsonify({
					"error": f"No visa requirements found for {citizenship} → {destination}",
					"suggestion": "Try running a visa search first with: POST /visa_info"
				}), HTTPStatus.NOT_FOUND
			
			visa_data = resp.data[0]
			
			# Generate user-friendly report
			report = _generate_visa_report(visa_data, citizenship, destination)
			
			if format_type == 'html':
				html_report = _generate_html_report(report)
				return app.response_class(
					response=html_report,
					status=HTTPStatus.OK,
					mimetype='text/html'
				)
			else:
				return jsonify(report), HTTPStatus.OK
				
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR

	@app.get("/visa_alerts")
	def get_visa_alerts():
		"""
		Get pending visa policy change alerts for a user.
		
		GET /visa_alerts?user_profile_id=123
		Query params:
		- user_profile_id: required
		- limit: optional (default: 50)
		"""
		print("Getting visa alerts for user request:")
		print("=" * 60)	
		try:
			user_profile_id = request.args.get('user_profile_id')
			limit = int(request.args.get('limit', '50'))
			
			if not user_profile_id:
				return jsonify({"error": "user_profile_id is required"}), HTTPStatus.BAD_REQUEST
			
			# Validate user exists before proceeding
			user_exists, error_response = _validate_user_exists(int(user_profile_id))
			if not user_exists:
				return jsonify(error_response), HTTPStatus.NOT_FOUND
			
			supabase = get_supabase()
			
			# Get visa requirements with pending alerts
			resp = supabase.table("visa_requirements").select("*") \
				.eq("user_profile_id", user_profile_id) \
				.eq("alert_sent", False) \
				.order("last_updated", desc=True).limit(limit).execute()
			print("Last alert:")
			if resp.data:
				print(resp.data[-1])
			else:
				print("No visa requirements found")
			print("=" * 60)
			alerts = []
			for req in resp.data or []:
				if not req['change_summary']:
					continue
				change_summary = req.get("change_summary", {})
				if change_summary.get("alert_needed", False):
					alerts.append({
						"id": req["id"],
						"citizenship": req["citizenship_country"],
						"destination": req["destination_country"],
						"visa_type": req["visa_type"],
						"last_updated": req["last_updated"],
						"source_url": req["source_url"],
						"changes": change_summary.get("changes", []),
						"is_new": change_summary.get("is_new", False),
						"alert_message": f"Visa requirements updated for {req['citizenship_country']} → {req['destination_country']}"
					})
			
			return jsonify({
				"user_profile_id": user_profile_id,
				"alerts_count": len(alerts),
				"alerts": alerts,
				"message": f"Found {len(alerts)} pending visa policy alerts"
			}), HTTPStatus.OK
			
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR

	@app.post("/visa_alerts/mark_sent")
	def mark_visa_alerts_sent():
		"""
		Mark visa alerts as sent (acknowledged by user/counselor).
		
		POST /visa_alerts/mark_sent
		Body: {
			"user_profile_id": int,
			"alert_ids": [int] (optional - if not provided, marks all for user)
		}
		"""
		try:
			payload = request.get_json(silent=True) or {}
			user_profile_id = payload.get("user_profile_id")
			alert_ids = payload.get("alert_ids", [])
			
			if not user_profile_id:
				return jsonify({"error": "user_profile_id is required"}), HTTPStatus.BAD_REQUEST
			
			# Validate user exists before proceeding
			user_exists, error_response = _validate_user_exists(user_profile_id)
			if not user_exists:
				return jsonify(error_response), HTTPStatus.NOT_FOUND
			
			supabase = get_supabase()
			
			# Build update query
			query = supabase.table("visa_requirements").update({"alert_sent": True}) \
				.eq("user_profile_id", user_profile_id) \
				.eq("alert_sent", False)
			
			if alert_ids:
				query = query.in_("id", alert_ids)
			
			result = query.execute()
			
			return jsonify({
				"message": f"Marked {len(result.data)} alerts as sent",
				"user_profile_id": user_profile_id,
				"updated_count": len(result.data)
			}), HTTPStatus.OK
			
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR

	# =======================================================
	# Application Requirements Endpoints
	# =======================================================

	@app.post("/fetch_application_requirements")
	def fetch_application_requirements():
		"""
		Fetch and structure application requirements based on user_profile_id, university, and program.

		POST /fetch_application_requirements
		Body: {
			"user_profile_id": "required",
			"university": "optional - specific university to fetch",
			"program": "optional - specific program to fetch"
		}
		"""
		payload = request.get_json(silent=True) or {}
		user_profile_id = payload.get("user_profile_id")
		university = payload.get("university")
		program = payload.get("program")
		
		if not all([user_profile_id, university, program]):
			return jsonify({
				"error": "Fields 'user_profile_id', 'university', and 'program' are all required."
			}), HTTPStatus.BAD_REQUEST

		try:
			supabase = get_supabase()
			
			# Verify user profile exists
			profile_resp = supabase.table("user_profile").select("*").eq("id", user_profile_id).execute()
			if not profile_resp.data:
				return jsonify({"error": f"User profile {user_profile_id} not found"}), HTTPStatus.NOT_FOUND

			# Sync provided university/program into user's profile if present
			if university and program:
				try:
					update_payload = {
						"university_interests": json.dumps([university]),
						"intended_major": program
					}
					supabase.table("user_profile").update(update_payload).eq("id", user_profile_id).execute()
					print(f"[DEBUG] Updated user_profile {user_profile_id} with latest university/program "
						f"({university} - {program}) for agent context.")
				except Exception as e:
					print(f"[WARN] Failed to update user_profile before agent run: {e}")
			
			try:
				from agents.crew import SearchCrew
				crew = SearchCrew()
				
				app_req_task = crew.application_requirement_task()
				app_req_agent = crew.application_requirement_agent()

				print("[DEBUG] Creating application requirement crew...")
				# Create a crew with just the application requirement agent and task
				from crewai import Crew, Process
				application_requirement_crew = Crew(
					agents=[app_req_agent],
					tasks=[app_req_task],
					process=Process.sequential,
					verbose=True
				)

				# Specific University Flow (only flow since all fields are required)
				inputs = {
					"user_id": user_profile_id,
					"university": university,
					"program": program,
					"search_type": "specific"
				}
				result = application_requirement_crew.kickoff(inputs=inputs)

				requirements_data = []
				formatted_json = None
				formatted_markdown = None

				# Parse agent output
				if hasattr(result, 'raw'):
					agent_output = result.raw
				else:
					agent_output = str(result)

				# Parse and store each requirement
				try:
					cleaned_output = agent_output.strip()

					# Try to extract JSON from text (handles cases where model outputs explanations or markdown)
					match = re.search(r'\{[\s\S]*\}', cleaned_output)
					if not match:
						print("[WARN] No valid JSON object found in agent output.")
						data = []
					else:
						json_text = match.group(0)

						# Clean up JSON text more carefully
						normalized_json = json_text.strip()
						
						# Remove any stray commas before closing brackets
						normalized_json = re.sub(r',(\s*[\]}])', r'\1', normalized_json)
						
						# Fix common JSON issues
						normalized_json = re.sub(r',\s*}', '}', normalized_json)  # Remove trailing commas
						normalized_json = re.sub(r',\s*]', ']', normalized_json)  # Remove trailing commas

						try:
							data = json.loads(normalized_json)
						except json.JSONDecodeError as err:
							print(f"[WARN] JSON decode failed after normalization: {err}")
							print("[DEBUG] Raw extracted text:\n", json_text)
							print("[DEBUG] Normalized text:\n", normalized_json)
							data = []

					if isinstance(data, dict):
						data = [data]  # Convert single result to list
						
					for req in data:
						# Format each requirement using checklist_formatter
						formatted_json = to_json_with_labels(req)
						formatted_markdown = to_markdown(req)
						
						# Structure according to application_requirements table schema
						requirement_data = {
							"user_profile_id": user_profile_id,
							"university": req.get("university"),
							"program": req.get("program"),
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

						requirements_data.append(requirement_data)

						# Check if an entry already exists in the database
						existing_entry_resp = supabase.table("application_requirements").select("id").eq("user_profile_id", user_profile_id).eq("university", req.get("university")).eq("program", req.get("program")).execute()

						if existing_entry_resp.data:
							# Update the existing entry
							existing_entry_id = existing_entry_resp.data[0]["id"]
							supabase.table("application_requirements").update(requirement_data).eq("id", existing_entry_id).execute()
						else:
							# Insert a new record
							supabase.table("application_requirements").insert(requirement_data).execute()

				except Exception as e:
					print(f"[ERROR] Failed to process result: {str(e)}")
					return jsonify({"error": str(e)}), HTTPStatus.INTERNAL_SERVER_ERROR

				# Log agent report to agent_reports_log
				try:
					from .agent_event_handler import get_event_handler
					get_event_handler().log_agent_report(
						agent_name="Application Requirements Agent",
						user_id=user_profile_id,
						payload={
							"application_requirements_stored": len(data) if isinstance(data, list) else 1,
							"university": university,
							"program": program,
							"stored_at": datetime.now().isoformat()
						}
					)
				except Exception as log_error:
					print(f"[WARN] Failed to log agent report: {log_error}")

				response = {
					"message": "Application requirements fetched and stored successfully",
					"user_profile_id": user_profile_id,
					"search_type": "specific",
					"formatted_json": formatted_json,
					"formatted_markdown": formatted_markdown,
					"disclaimer": "All information is sourced from the official university website. Please verify before submitting your application."
				}

				return app.response_class(
					response=json.dumps(response, indent=2, ensure_ascii=False),
					status=HTTPStatus.OK,
					mimetype='application/json'
				)

			except Exception as e:
				print(f"[ERROR] Exception in /fetch_application_requirements: {str(e)}")
				return jsonify({"error": str(e)}), HTTPStatus.INTERNAL_SERVER_ERROR
		
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR

	@app.get("/application_requirements/<string:university>/<string:program>")
	def get_application_requirements(university: str, program: str):
		"""
		Retrieve the latest application requirements checklist for a user profile, university, and program.
		GET /application_requirements?user_profile_id=...&university=...&program=...
		user_profile_id is required, university and program are optional.
		"""
		try:
			user_profile_id = request.args.get("user_profile_id")
			if not user_profile_id:
				return jsonify({"error": "'user_profile_id' is required as a query parameter."}), HTTPStatus.BAD_REQUEST

			supabase = get_supabase()
			query = supabase.table("application_requirements").select("*").eq("user_profile_id", user_profile_id)
			if university:
				query = query.eq("university", university)
			if program:
				query = query.eq("program", program)
			resp = query.order("fetched_at", desc=True).limit(1).execute()

			# If no data, return message indicating no application requirements fetched
			if not resp.data:
				return app.response_class(
					response=json.dumps({
						"message": f"No application requirements fetched for user_profile_id={user_profile_id}, university={university}, program={program}",
						"user_profile_id": user_profile_id,
						"university": university,
						"program": program,
						"requirements": [],
						"refreshed": False
					}, indent=2, ensure_ascii=False),
					status=HTTPStatus.NOT_FOUND,
					mimetype='application/json'
				)

			requirements = resp.data[0]
			fetched_at_str = requirements.get("fetched_at")
			is_stale = False
			if fetched_at_str:
				try:
					fetched_at = datetime.fromisoformat(fetched_at_str)
					if datetime.now() - fetched_at > timedelta(days=30):
						is_stale = True
				except Exception:
					pass

			if is_stale:
				try:
					from agents.crew import SearchCrew
					crew = SearchCrew()
					req_agent = crew.application_requirement_agent()
					result = req_agent.get_requirements(
						user_profile_id=user_profile_id,
						university=university,
						program=program
					)
					update_data = {
						"application_platform": result.get("application_platform"),
						"deadlines": result.get("deadlines", {}),
						"required_documents": result.get("required_documents", []),
						"essay_prompts": result.get("essay_prompts", {}),
						"portfolio_required": result.get("portfolio_required", False),
						"interview": result.get("interview"),
						"fee_info": result.get("fee_info", {}),
						"test_policy": result.get("test_policy"),
						"source_url": result.get("source_url"),
						"fetched_at": result.get("fetched_at"),
						"is_ambiguous": result.get("is_ambiguous", False),
						"reviewed_by": result.get("reviewed_by")
					}
					supabase.table("application_requirements") \
						.update(update_data) \
						.eq("user_profile_id", user_profile_id)
					if university:
						supabase.table("application_requirements").update(update_data).eq("user_profile_id", user_profile_id).eq("university", university)
					if program:
						supabase.table("application_requirements").update(update_data).eq("user_profile_id", user_profile_id).eq("program", program)
					
					# Log agent report to agent_reports_log
					try:
						from .agent_event_handler import get_event_handler
						get_event_handler().log_agent_report(
							agent_name="Application Requirements Agent",
							user_id=user_profile_id,
							payload={
								"application_requirements_stored": 1,
								"university": university,
								"program": program,
								"refreshed": True,
								"stored_at": datetime.now().isoformat()
							}
						)
					except Exception as log_error:
						print(f"[WARN] Failed to log agent report: {log_error}")
					
					# Return the newly refreshed requirements
					refreshed_requirements = requirements.copy()
					refreshed_requirements.update(update_data)
					return app.response_class(
						response=json.dumps({
							"user_profile_id": user_profile_id,
							"university": university,
							"program": program,
							"requirements": refreshed_requirements,
							"refreshed": True,
							"note": "Auto-refreshed because data was older than 30 days."
						}, indent=2, ensure_ascii=False),
						status=HTTPStatus.OK,
						mimetype='application/json'
					)
				except ImportError:
					return jsonify({"error": "Application Requirements Agent not available."}), HTTPStatus.SERVICE_UNAVAILABLE
				except Exception as exc:
					return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR

			# Otherwise, return the latest requirements
			return app.response_class(
				response=json.dumps({
					"user_profile_id": user_profile_id,
					"university": university,
					"program": program,
					"requirements": requirements,
					"refreshed": False
				}, indent=2, ensure_ascii=False),
				status=HTTPStatus.OK,
				mimetype='application/json'
			)
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR

	# =======================================================
	# Admissions Counselor Agent Endpoints
	# =======================================================
	
	@app.get("/admissions/summary/<int:user_id>")
	def admissions_summary(user_id: int):
		"""
		Get the latest overall admissions status for a user.
		Uses the Admissions Counselor Agent to synthesize data from all agents.
		
		GET /admissions/summary/{user_id}
		"""
		try:
			# Validate user exists
			user_exists, error_response = _validate_user_exists(user_id)
			if not user_exists:
				return jsonify(error_response), HTTPStatus.NOT_FOUND
			
			supabase = get_supabase()
			
			# Execute Admissions Counselor Agent with HIERARCHICAL ORCHESTRATION
			try:
				from agents.crew import ManagerCrew
				
				# Use ManagerCrew which has hierarchical process built-in
				manager_crew_instance = ManagerCrew()
				
				print(f"\n=== DEBUG: Using ManagerCrew for Hierarchical Delegation ===")
				print(f"Using ManagerCrew with hierarchical process")
				print(f"========================================================\n")
				
				# Get the crew instance (ready to use with hierarchical process)
				admissions_crew = manager_crew_instance.crew()
				
				inputs = {
					'user_id': user_id,
					'current_year': str(datetime.now().year),
					'next_year': str(datetime.now().year + 1),
					'today': datetime.now().date().isoformat(),  # Provide current date for deadline calculations
					'search_type': 'full',  # For scholarship_search_task
					# Profile data (citizenship_country, destination_country, university, program) will be read by agents from user profile
					# Do not pass empty strings - agents use ProfileQueryTool/ProfileAccessTool to get this data
				}
				
				print(f"\nSTARTING ADMISSIONS COUNSELOR AGENT - User ID: {user_id}")
				print(f"Inputs: {inputs}")
				print("=" * 60)
				
				result = admissions_crew.kickoff(inputs=inputs)
				agent_output = result.raw if hasattr(result, 'raw') else str(result)
				
				print(f"\nADMISSIONS COUNSELOR OUTPUT:")
				print("=" * 60)
				print(agent_output)
				print("=" * 60)
				
				# Store results from delegated agents
				try:
					from .manager_crew_storage import process_and_store_agent_results
					storage_results = process_and_store_agent_results(user_id, result)
					print(f"\n📊 Storage Results:")
					print(f"  Application Requirements: {storage_results['application_requirement']['stored_count']} stored")
					print(f"  Visa Information: {storage_results['visa_information']['stored_count']} stored")
					print(f"  University Search: {storage_results['university_search']['stored_count']} stored")
					print(f"  Scholarship Search: {storage_results['scholarship_search']['stored_count']} stored")
				except Exception as storage_error:
					print(f"⚠️ Failed to store agent results: {storage_error}")
				
				# Parse agent output
				cleaned_output = agent_output.strip()
				start_idx = cleaned_output.find('{')
				end_idx = cleaned_output.rfind('}')
				
				if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
					json_content = cleaned_output[start_idx:end_idx + 1]
					try:
						summary_data = json.loads(json_content)
						print(f"✅ Parsed agent output successfully")
					except json.JSONDecodeError as e:
						print(f"⚠️ Could not parse agent output as JSON: {e}")
						summary_data = None
				else:
					print(f"⚠️ No JSON object found in agent output")
					summary_data = None
				
			except ImportError:
				print("⚠️ CrewAI agents not available, falling back to direct calculation")
				summary_data = None
			except Exception as e:
				print(f"⚠️ Agent execution failed: {e}")
				summary_data = None
			
			# Fallback: try to return cached summary if agent failed
			if summary_data is None:
				print("⚠️ Agent failed, attempting to return cached summary")
				
				# Try to get cached summary from DB
				cached_summary = supabase.table("admissions_summary").select("*").eq("user_id", user_id).order("last_updated", desc=True).limit(1).execute()
				
				if cached_summary.data:
					# Return cached summary
					summary_data = cached_summary.data[0]
				else:
					# Return basic structure if no cache
					summary_data = {
						"current_stage": "Getting Started",
						"progress_score": 0,
						"active_agents": [],
						"stress_flags": {"incomplete_profile": True, "approaching_deadlines": 0, "agent_conflicts": False},
						"next_steps": [],
						"overview": {"universities_found": 0, "scholarships_found": 0, "application_requirements": 0, "visa_info_count": 0}
					}
				
				# If no cached summary, add empty overview to basic structure
				if not summary_data.get("overview"):
					summary_data["overview"] = {"universities_found": 0, "scholarships_found": 0, "application_requirements": 0, "visa_info_count": 0}
			else:
				# Agent provided output - use it, save to database, and add overview data
				supabase = get_supabase()
				universities_resp = supabase.table("university_results").select("id").eq("user_profile_id", user_id).execute()
				scholarships_resp = supabase.table("scholarship_results").select("id").eq("user_profile_id", user_id).gte("deadline", datetime.now().date().isoformat()).execute()
				app_reqs_resp = supabase.table("application_requirements").select("id").eq("user_profile_id", user_id).execute()
				visa_resp = supabase.table("visa_requirements").select("id").eq("user_profile_id", user_id).execute()
				profile_resp = supabase.table("user_profile").select("full_name").eq("id", user_id).execute()
				
				summary_data["overview"] = {
					"universities_found": len(universities_resp.data) if universities_resp.data else 0,
					"scholarships_found": len(scholarships_resp.data) if scholarships_resp.data else 0,
					"application_requirements": len(app_reqs_resp.data) if app_reqs_resp.data else 0,
					"visa_info_count": len(visa_resp.data) if visa_resp.data else 0,
					"profile_name": profile_resp.data[0]["full_name"] if profile_resp.data and len(profile_resp.data) > 0 else None
				}
				
				# Save or update admissions_summary in database
				summary_resp = supabase.table("admissions_summary").select("*").eq("user_id", user_id).order("last_updated", desc=True).limit(1).execute()
				summary_data_db = summary_resp.data[0] if summary_resp.data else None
				
				db_data = {
					"user_id": user_id,
					"current_stage": summary_data.get("current_stage"),
					"progress_score": summary_data.get("progress_score"),
					"active_agents": summary_data.get("active_agents", []),
					"stress_flags": summary_data.get("stress_flags", {}),
					"next_steps": summary_data.get("next_steps", []),
					"last_updated": datetime.now().isoformat()
				}
				
				if not summary_data_db:
					# Create new summary
					supabase.table("admissions_summary").insert(db_data).execute()
				else:
					# Update existing summary
					supabase.table("admissions_summary").update(db_data).eq("id", summary_data_db["id"]).execute()
			
			return app.response_class(
				response=json.dumps(summary_data, indent=2, ensure_ascii=False, default=str),
				status=HTTPStatus.OK,
				mimetype='application/json'
			)
			
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR
	
	@app.get("/admissions/next_steps/<int:user_id>")
	def admissions_next_steps(user_id: int):
		"""
		Get prioritized next actions for a user based on their current stage and progress.
		
		GET /admissions/next_steps/{user_id}
		"""
		try:
			# Validate user exists
			user_exists, error_response = _validate_user_exists(user_id)
			if not user_exists:
				return jsonify(error_response), HTTPStatus.NOT_FOUND
			
			supabase = get_supabase()
			
			# Get current summary to understand stage
			summary_resp = supabase.table("admissions_summary").select("*").eq("user_id", user_id).order("last_updated", desc=True).limit(1).execute()
			
			# Get user profile
			profile_resp = supabase.table("user_profile").select("full_name, gpa, intended_major, budget, citizenship_country, destination_country").eq("id", user_id).execute()
			profile = profile_resp.data[0] if profile_resp.data else {}
			
			# Generate next steps based on current state
			next_steps = []
			
			# Check if profile is complete and list missing fields
			missing_fields = []
			if not profile.get("gpa"):
				missing_fields.append("GPA")
			if not profile.get("intended_major") or str(profile.get("intended_major")).strip() == "":
				missing_fields.append("Intended Major")
			if profile.get("budget") is None:
				missing_fields.append("Budget")
			if not profile.get("citizenship_country"):
				missing_fields.append("Citizenship Country")
			if not profile.get("destination_country"):
				missing_fields.append("Destination Country")
			if not profile.get("test_scores"):
				missing_fields.append("Test Scores")
			if not profile.get("academic_background"):
				missing_fields.append("Academic Background")
			if not profile.get("preferences"):
				missing_fields.append("Preferences")
			
			if missing_fields:
				next_steps.append({
					"priority": "high",
					"action": "Complete your profile",
					"description": f"Add or update the following: {', '.join(missing_fields)}",
					"deadline": None,
					"category": "profile"
				})
			
			# Check university results
			universities_resp = supabase.table("university_results").select("id").eq("user_profile_id", user_id).execute()
			if not universities_resp.data:
				next_steps.append({
					"priority": "high",
					"action": "Search for universities",
					"description": "Start exploring universities that match your profile",
					"deadline": None,
					"category": "research"
				})
			elif len(universities_resp.data) < 3:
				next_steps.append({
					"priority": "medium",
					"action": "Expand your college list",
					"description": "Consider adding more universities to have a balanced list of safety, target, and reach schools",
					"deadline": None,
					"category": "research"
				})
			
			# Check for approaching application deadlines
			app_reqs_resp = supabase.table("application_requirements").select("university, program, deadlines").eq("user_profile_id", user_id).execute()
			urgent_steps = []
			for req in app_reqs_resp.data or []:
				deadlines = req.get("deadlines", {})
				if isinstance(deadlines, dict):
					for key, date_str in deadlines.items():
						try:
							deadline_date = datetime.fromisoformat(date_str).date()
							days_left = (deadline_date - datetime.now().date()).days
							if 0 <= days_left <= 45:
								urgent_steps.append({
									"priority": "high",
									"action": f"Prepare {req.get('university', 'application')} application",
									"description": f"{req.get('program', 'Program')} deadline in {days_left} days",
									"deadline": date_str,
									"category": "application",
									"university": req.get("university"),
									"program": req.get("program")
								})
						except (ValueError, TypeError, AttributeError):
							pass
			
			# Add urgent steps sorted by deadline
			next_steps.extend(sorted(urgent_steps, key=lambda x: x.get("deadline", "")))
			
			# Check for scholarship deadlines
			scholarships_resp = supabase.table("scholarship_results").select("name, deadline, award_amount").eq("user_profile_id", user_id).gte("deadline", datetime.now().date().isoformat()).order("deadline", desc=False).execute()
			for scholarship in scholarships_resp.data or []:
				try:
					deadline_str = scholarship.get("deadline")
					deadline_date = datetime.fromisoformat(deadline_str).date()
					days_left = (deadline_date - datetime.now().date()).days
					if days_left <= 30:
						next_steps.append({
							"priority": "medium",
							"action": f"Apply for {scholarship.get('name', 'scholarship')}",
							"description": f"Deadline in {days_left} days - Award: {scholarship.get('award_amount', 'Amount varies')}",
							"deadline": deadline_str,
							"category": "scholarship"
						})
				except (ValueError, TypeError, AttributeError):
					pass
			
			# If no urgent items, suggest general next steps
			if not next_steps:
				# Check if needs visa info
				visa_resp = supabase.table("visa_requirements").select("id").eq("user_profile_id", user_id).execute()
				if profile.get("citizenship_country") and profile.get("destination_country") and not visa_resp.data:
					next_steps.append({
						"priority": "medium",
						"action": "Research visa requirements",
						"description": f"Learn about visa requirements for {profile.get('citizenship_country')} → {profile.get('destination_country')}",
						"deadline": None,
						"category": "visa"
					})
			
			# Update summary with next steps
			if summary_resp.data:
				supabase.table("admissions_summary").update({
					"next_steps": next_steps, 
					"last_updated": datetime.now().isoformat()
				}).eq("id", summary_resp.data[0]["id"]).execute()
			
			return app.response_class(
				response=json.dumps({
					"user_id": user_id,
					"next_steps": next_steps,
					"total_count": len(next_steps),
					"last_updated": datetime.now().isoformat()
				}, indent=2, ensure_ascii=False, default=str),
				status=HTTPStatus.OK,
				mimetype='application/json'
			)
			
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR
	
	@app.post("/admissions/update_stage")
	def update_admissions_stage():
		"""
		Update the user's admissions progress stage.
		Can be triggered manually or by events.
		
		POST /admissions/update_stage
		Body: {
			"user_id": int,
			"current_stage": str (optional - defaults to calculated),
			"progress_score": float (optional - defaults to calculated),
			"stress_flags": dict (optional)
		}
		"""
		try:
			payload = request.get_json(silent=True) or {}
			user_id = payload.get("user_id")
			
			if not user_id:
				return jsonify({"error": "user_id is required"}), HTTPStatus.BAD_REQUEST
			
			# Validate user exists
			user_exists, error_response = _validate_user_exists(user_id)
			if not user_exists:
				return jsonify(error_response), HTTPStatus.NOT_FOUND
			
			supabase = get_supabase()
			
			# Get or create summary
			summary_resp = supabase.table("admissions_summary").select("*").eq("user_id", user_id).order("last_updated", desc=True).limit(1).execute()
			
			update_data = {
				"last_updated": datetime.now().isoformat()
			}
			
			# Allow manual overrides
			if "current_stage" in payload:
				update_data["current_stage"] = payload.get("current_stage")
			if "progress_score" in payload:
				update_data["progress_score"] = payload.get("progress_score")
			if "stress_flags" in payload:
				update_data["stress_flags"] = payload.get("stress_flags")
			if "next_steps" in payload:
				update_data["next_steps"] = payload.get("next_steps")
			
			if summary_resp.data:
				# Update existing
				result = supabase.table("admissions_summary").update(update_data).eq("id", summary_resp.data[0]["id"]).execute()
				return jsonify({
					"message": "Admissions stage updated",
					"user_id": user_id,
					"updated_data": result.data[0] if result.data else {}
				}), HTTPStatus.OK
			else:
				# Create new
				update_data["user_id"] = user_id
				if "current_stage" not in update_data:
					update_data["current_stage"] = "Getting Started"
				if "progress_score" not in update_data:
					update_data["progress_score"] = 0.0
				result = supabase.table("admissions_summary").insert(update_data).execute()
				return jsonify({
					"message": "Admissions summary created",
					"user_id": user_id,
					"summary_data": result.data[0] if result.data else {}
				}), HTTPStatus.CREATED
			
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR
	
	@app.post("/admissions/log_agent_report")
	def log_agent_report():
		"""
		Accept reports from other agents and log them.
		Detects conflicts between agent reports.
		
		POST /admissions/log_agent_report
		Body: {
			"agent_name": str (e.g., "University Search Agent"),
			"user_id": int,
			"payload": dict,
			"timestamp": str (optional - defaults to now)
		}
		"""
		try:
			payload = request.get_json(silent=True) or {}
			agent_name = payload.get("agent_name")
			user_id = payload.get("user_id")
			report_payload = payload.get("payload", {})
			
			if not agent_name or not user_id:
				return jsonify({"error": "agent_name and user_id are required"}), HTTPStatus.BAD_REQUEST
			
			# Validate user exists
			user_exists, error_response = _validate_user_exists(user_id)
			if not user_exists:
				return jsonify(error_response), HTTPStatus.NOT_FOUND
			
			# Use event handler to log report
			from .agent_event_handler import get_event_handler
			handler = get_event_handler()
			result = handler.log_agent_report(
				agent_name=agent_name,
				user_id=user_id,
				payload=report_payload,
				timestamp=payload.get("timestamp")
			)
			
			return jsonify({
				"message": "Agent report logged",
				"agent_name": agent_name,
				"user_id": user_id,
				"conflict_detected": result.get("conflict_detected", False),
				"report_id": result.get("report_id")
			}), HTTPStatus.CREATED
			
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR
	
	# =======================================================
	# Admissions Counselor Notifications (Optional MVP+)
	# =======================================================
	@app.post("/counselor_notifications")
	def counselor_notifications():
		"""
		Accepts notifications related to application requirements updates or ambiguities for Admissions Counselor workflows.
		
		POST /counselor_notifications
		Body example:
		{
			"event_type": "application_requirements_updated|ambiguity_flagged|manual_refresh_requested",
			"user_profile_id": 1,
			"university": "USC",
			"program": "Data Science B.S.",
			"details": {"note": "Ambiguity detected in test policy"}
		}
		"""
		try:
			payload = request.get_json(silent=True) or {}
			event_type = payload.get("event_type")
			user_profile_id = payload.get("user_profile_id")
			if not event_type or not user_profile_id:
				return jsonify({"error": "'event_type' and 'user_profile_id' are required"}), HTTPStatus.BAD_REQUEST


			# Optional outbound webhook dispatch
			webhook_dispatched = False
			try:
				webhook_url = os.getenv("COUNSELOR_WEBHOOK_URL")
				if webhook_url:
					resp = requests.post(webhook_url, json=payload, timeout=5)
					webhook_dispatched = (200 <= resp.status_code < 300)
			except Exception:
				webhook_dispatched = False

			return app.response_class(
				response=json.dumps({
					"message": "Notification received",
					"webhook_dispatched": webhook_dispatched
				}, indent=2, ensure_ascii=False),
				status=HTTPStatus.ACCEPTED,
				mimetype='application/json'
			)
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR
