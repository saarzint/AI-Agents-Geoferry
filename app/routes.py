from flask import Flask, request, jsonify
from http import HTTPStatus
import json
import sys
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple
from .supabase_client import get_supabase
from .utils import _generate_visa_report, _generate_html_report, _detect_visa_changes

import requests
import stripe

from app.checklist_formatter import to_json_with_labels, to_markdown

# Add agents module to path
agents_path = os.path.join(os.path.dirname(__file__), '..', 'agents', 'src')
sys.path.append(os.path.abspath(agents_path))

# =======================================================
# Token & Billing Configuration
# =======================================================

# Tokens granted per billing cycle for each subscription plan.
# Keep this in sync with frontend plan configuration and Stripe price IDs.
PLAN_TOKEN_GRANTS: Dict[str, int] = {
	"starter": 25,   # Free tier
	"pro": 300,      # Tier 2
	"team": 600,     # Tier 3
}

# Optional: one-time token pack(s) mapped by Stripe price_id → tokens granted.
# Populate these when you create Stripe prices for top-ups.
ONE_TIME_TOKEN_PACKS_BY_PRICE_ID: Dict[str, int] = {
	# "price_xxx": 100,  # Example: 100-token top-up
}

# Token costs per feature (per invocation)
TOKEN_COSTS: Dict[str, Optional[int]] = {
	"university_search": 25,
	"scholarship_search": 25,
	"visa_services": 50,
	"essay_feedback": 25,
	"essay_brainstorm": 10,
	"voice_agent": None,  # TBD – no enforcement yet
}


def _consume_tokens(
	user_profile_id: int,
	feature_key: str,
	source: str,
	metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Dict[str, Any]]:
	"""
	Attempt to consume tokens for a given feature.
	Returns (success, details_json).

	If the consume_tokens RPC or token tables are missing, this will log a warning
	and return (True, {"warning": "TOKENS_NOT_ENFORCED"}) so that agent flows
	keep working until migrations are applied.
	"""
	cost = TOKEN_COSTS.get(feature_key)
	if not cost or cost <= 0:
		# No cost configured – treat as free for now
		return True, {"warning": "NO_COST_CONFIGURED"}

	try:
		supabase = get_supabase()
		payload = {
			"p_user_profile_id": user_profile_id,
			"p_cost": cost,
			"p_feature": feature_key,
			"p_source": source,
			"p_metadata": metadata or {},
		}
		result = supabase.rpc("consume_tokens", payload).execute()
		data = getattr(result, "data", None) or result  # supabase-py may return dict-like
		if isinstance(data, dict) and data.get("success"):
			return True, data

		# If function is missing or table not found, don't block the main flow
		error_msg = (data or {}).get("error") if isinstance(data, dict) else None
		if error_msg and any(k in str(error_msg) for k in ("function consume_tokens", "PGRST", "does not exist")):
			print("⚠️  WARNING: consume_tokens RPC not available. Token enforcement is disabled until migrations are applied.")
			return True, {"warning": "TOKENS_NOT_ENFORCED"}

		# Proper failure – likely insufficient tokens
		return False, data if isinstance(data, dict) else {"error": "TOKEN_CONSUME_FAILED"}
	except Exception as exc:
		error_str = str(exc)
		# Do not break core flows if infra is not ready; just log and allow
		if any(k in error_str for k in ("consume_tokens", "PGRST", "does not exist")):
			print(f"⚠️  WARNING: consume_tokens RPC error – token enforcement disabled: {error_str}")
			return True, {"warning": "TOKENS_NOT_ENFORCED"}
		print(f"❌ ERROR consuming tokens for user {user_profile_id}, feature={feature_key}: {error_str}")
		return False, {"error": "TOKEN_CONSUME_EXCEPTION", "details": error_str}


def _credit_tokens(
	user_profile_id: int,
	amount: int,
	reason: str,
	source: str,
	feature_key: Optional[str] = None,
	metadata: Optional[Dict[str, Any]] = None,
) -> None:
	"""
	Credit tokens to a user.

	Primary path: call the Postgres credit_tokens() function via Supabase RPC.
	Fallback path (if RPC is missing or errors): perform the update directly
	against user_profile and token_transactions tables.
	"""
	if amount is None or amount <= 0:
		return

	def _fallback_db_credit() -> None:
		"""Direct DB update if RPC path is unavailable. Includes retry logic for connection errors."""
		max_retries = 3
		retry_delay = 1  # seconds
		
		for attempt in range(max_retries):
			try:
				supabase = get_supabase()

				# Get current balance
				profile_resp = supabase.table("user_profile").select("token_balance").eq("id", user_profile_id).execute()
				if not profile_resp.data:
					print(f"⚠️  WARNING: Could not credit tokens – user_profile {user_profile_id} not found")
					return

				current_balance = profile_resp.data[0].get("token_balance") or 0
				new_balance = current_balance + amount

				# Update balance
				supabase.table("user_profile").update({
					"token_balance": new_balance,
					"updated_at": datetime.now().isoformat(),
				}).eq("id", user_profile_id).execute()

				# Insert ledger row
				supabase.table("token_transactions").insert({
					"user_profile_id": user_profile_id,
					"delta": amount,
					"balance_after": new_balance,
					"reason": reason,
					"feature": feature_key,
					"source": source,
					"metadata": metadata or {},
				}).execute()

				print(f"✅ Tokens credited via fallback DB path: user={user_profile_id}, amount={amount}, balance={new_balance}")
				return  # Success - exit retry loop
			except Exception as inner_exc:
				error_str = str(inner_exc)
				is_connection_error = any(keyword in error_str.lower() for keyword in [
					"connection", "terminated", "timeout", "network", "remote", "protocol"
				])
				
				if is_connection_error and attempt < max_retries - 1:
					print(f"⚠️  Connection error in fallback token credit (attempt {attempt + 1}/{max_retries}): {error_str}")
					import time
					time.sleep(retry_delay)
					retry_delay *= 2  # Exponential backoff
					continue
				
				# Final attempt failed or non-retryable error
				print(f"❌ ERROR in fallback token credit for user {user_profile_id}: {inner_exc}")
				if attempt == max_retries - 1:
					import traceback
					print(f"Traceback: {traceback.format_exc()}")
				return  # Exit retry loop

	try:
		supabase = get_supabase()
		payload = {
			"p_user_profile_id": user_profile_id,
			"p_amount": amount,
			"p_reason": reason,
			"p_source": source,
			"p_feature": feature_key,
			"p_metadata": metadata or {},
		}
		result = supabase.rpc("credit_tokens", payload).execute()
		data = getattr(result, "data", None) or result

		# If RPC returns a structured result, check success flag
		if isinstance(data, dict):
			if data.get("success"):
				print(f"✅ Tokens credited via RPC: user={user_profile_id}, amount={amount}, balance={data.get('balance')}")
				return

			error_msg = data.get("error")
			if error_msg and any(k in str(error_msg) for k in ("function credit_tokens", "PGRST", "does not exist")):
				print("⚠️  WARNING: credit_tokens RPC not available. Falling back to direct DB credit.")
				_fallback_db_credit()
				return

			print(f"⚠️  WARNING: credit_tokens RPC returned error: {error_msg}. Falling back to direct DB credit.")
			_fallback_db_credit()
			return

		# Unexpected RPC response format – fall back to direct DB credit
		print(f"⚠️  WARNING: Unexpected credit_tokens RPC response format: {data}. Falling back to direct DB credit.")
		_fallback_db_credit()
	except Exception as exc:
		error_str = str(exc)
		if any(k in error_str for k in ("credit_tokens", "PGRST", "does not exist")):
			print(f"⚠️  WARNING: credit_tokens RPC error – falling back to direct DB credit: {error_str}")
			_fallback_db_credit()
		else:
			print(f"❌ ERROR crediting tokens for user {user_profile_id}: {error_str}")
def _validate_user_exists(user_profile_id: int) -> tuple[bool, dict]:
	"""
	Validate if a user profile exists in the database.
	Returns (exists, response_data) where response_data is None if user exists,
	or error response dict if user doesn't exist.
	"""
	max_retries = 3
	retry_delay = 1  # seconds
	
	for attempt in range(max_retries):
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
			error_details = str(exc)
			error_type = type(exc).__name__
			
			# Check if it's a connection error that might be retryable
			is_connection_error = any(keyword in error_details.lower() for keyword in [
				"connection", "terminated", "timeout", "network", "remote", "protocol"
			])
			
			if is_connection_error and attempt < max_retries - 1:
				print(f"⚠️  Connection error in _validate_user_exists (attempt {attempt + 1}/{max_retries}): {error_details}")
				import time
				time.sleep(retry_delay)
				retry_delay *= 2  # Exponential backoff
				continue
			
			# Log the full error for debugging
			import traceback
			print(f"ERROR in _validate_user_exists: {error_details}")
			print(f"Traceback: {traceback.format_exc()}")
			return False, {
				"error": f"Failed to validate user profile: {error_details}",
				"user_profile_id": user_profile_id,
				"error_type": error_type
			}
	
	# Should never reach here, but just in case
	return False, {
		"error": f"Failed to validate user profile after {max_retries} attempts",
		"user_profile_id": user_profile_id,
		"error_type": "MaxRetriesExceeded"
	}

def register_routes(app: Flask) -> None:
	# Handle CORS preflight requests explicitly (Flask has no native app.options helper)
	@app.route("/<path:path>", methods=["OPTIONS"])
	def options_handler(path):
		return "", 200
	
	# API index route – moved to /api so that "/" can serve the frontend SPA
	@app.get("/api")
	def api_index():
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
				"log_agent_report": "/admissions/log_agent_report",
				"stripe_create_payment_intent": "/stripe/create-payment-intent",
				"stripe_create_subscription": "/stripe/create-subscription",
				"stripe_get_subscription": "/stripe/subscription/<user_profile_id>",
				"stripe_get_payment_methods": "/stripe/payment-methods/<user_profile_id>",
				"stripe_get_payment_history": "/stripe/payment-history/<user_profile_id>",
				"stripe_get_billing_info": "/stripe/billing-info/<user_profile_id>",
				"stripe_webhook": "/stripe/webhook",
				"stripe_cancel_subscription": "/stripe/cancel-subscription",
				"token_balance": "/tokens/balance/<user_profile_id>",
				"token_history": "/tokens/history/<user_profile_id>",
				"essay_analyze": "/essay/analyze",
				"essay_generate_ideas": "/essay/generate-ideas"
			}
		}), HTTPStatus.OK
	
	@app.get("/health")
	def health_check():
		return jsonify({
			"status": "healthy",
			"message": "PG Admit API is running"
		}), HTTPStatus.OK

	# =======================================================
	# Essay Services Endpoints (with token consumption)
	# =======================================================

	@app.post("/essay/analyze")
	def analyze_essay():
		"""
		Analyze an essay and provide comprehensive feedback.
		Consumes tokens: essay_feedback (25 tokens)
		
		POST /essay/analyze
		Body: {
			"user_profile_id": int (required),
			"essay_text": str (required),
			"essay_type": str (required)
		}
		"""
		try:
			data = request.get_json()
			if not data:
				return jsonify({"error": "Request body is required"}), HTTPStatus.BAD_REQUEST

			user_profile_id = data.get("user_profile_id")
			essay_text = data.get("essay_text")
			essay_type = data.get("essay_type")

			if not user_profile_id:
				return jsonify({"error": "user_profile_id is required"}), HTTPStatus.BAD_REQUEST
			if not essay_text:
				return jsonify({"error": "essay_text is required"}), HTTPStatus.BAD_REQUEST
			if not essay_type:
				return jsonify({"error": "essay_type is required"}), HTTPStatus.BAD_REQUEST

			# Consume tokens before processing
			success, token_result = _consume_tokens(
				user_profile_id=int(user_profile_id),
				feature_key="essay_feedback",
				source="essay_analyze_api",
				metadata={"essay_type": essay_type},
			)
			if not success:
				return jsonify({
					"error": "Insufficient tokens",
					"details": token_result
				}), HTTPStatus.PAYMENT_REQUIRED

			# Call Cerebras API
			cerebras_api_key = os.getenv("CEREBRAS_API_KEY")
			if not cerebras_api_key:
				return jsonify({"error": "Cerebras API key not configured"}), HTTPStatus.INTERNAL_SERVER_ERROR

			system_prompt = f"""You are an expert college admissions essay coach with years of experience helping students craft compelling personal statements. 

Analyze the following {essay_type} essay and provide detailed feedback. Your response MUST be valid JSON in this exact format:
{{
  "overallScore": <number 0-100>,
  "items": [
    {{"id": "1", "type": "strength", "text": "<specific strength>"}},
    {{"id": "2", "type": "strength", "text": "<another strength>"}},
    {{"id": "3", "type": "improvement", "text": "<area needing improvement>"}},
    {{"id": "4", "type": "improvement", "text": "<another improvement area>"}},
    {{"id": "5", "type": "suggestion", "text": "<actionable suggestion>"}},
    {{"id": "6", "type": "suggestion", "text": "<another suggestion>"}},
    {{"id": "7", "type": "insight", "text": "<admissions insight>"}},
    {{"id": "8", "type": "insight", "text": "<another insight>"}}
  ]
}}

Evaluate on:
- Opening hook and engagement
- Authenticity and personal voice
- Structure and flow
- Specific examples and storytelling
- Grammar and word choice
- Connection to the essay prompt/type
- Overall impact for admissions"""

			user_prompt = f"Please analyze this {essay_type} essay:\n\n{essay_text}"

			cerebras_response = requests.post(
				"https://api.cerebras.ai/v1/chat/completions",
				json={
					"model": "llama3.1-8b",
					"messages": [
						{"role": "system", "content": system_prompt},
						{"role": "user", "content": user_prompt}
					],
					"max_tokens": 2000,
					"temperature": 0.7,
				},
				headers={
					"Authorization": f"Bearer {cerebras_api_key}",
					"Content-Type": "application/json",
				},
				timeout=60,
			)

			if cerebras_response.status_code != 200:
				return jsonify({
					"error": f"Cerebras API error: {cerebras_response.text}"
				}), HTTPStatus.INTERNAL_SERVER_ERROR

			response_data = cerebras_response.json()
			content = response_data.get("choices", [{}])[0].get("message", {}).get("content", "")

			# Parse JSON from response
			import re
			json_match = re.search(r'\{[\s\S]*\}', content)
			if json_match:
				parsed = json.loads(json_match.group(0))
				return jsonify(parsed), HTTPStatus.OK

			return jsonify({"error": "Failed to parse AI response"}), HTTPStatus.INTERNAL_SERVER_ERROR

		except json.JSONDecodeError as e:
			return jsonify({"error": f"Invalid JSON in response: {str(e)}"}), HTTPStatus.INTERNAL_SERVER_ERROR
		except Exception as e:
			print(f"❌ ERROR in /essay/analyze: {str(e)}")
			import traceback
			print(traceback.format_exc())
			return jsonify({"error": str(e)}), HTTPStatus.INTERNAL_SERVER_ERROR

	@app.post("/essay/generate-ideas")
	def generate_essay_ideas():
		"""
		Generate essay ideas based on user input.
		Consumes tokens: essay_brainstorm (10 tokens)
		
		POST /essay/generate-ideas
		Body: {
			"user_profile_id": int (required),
			"topic": str (optional),
			"cogins1": str (optional),
			"cogins2": str (optional),
			"key_experiences": str (optional),
			"tags": list[str] (optional)
		}
		"""
		try:
			data = request.get_json()
			if not data:
				return jsonify({"error": "Request body is required"}), HTTPStatus.BAD_REQUEST

			user_profile_id = data.get("user_profile_id")
			if not user_profile_id:
				return jsonify({"error": "user_profile_id is required"}), HTTPStatus.BAD_REQUEST

			# Consume tokens before processing
			success, token_result = _consume_tokens(
				user_profile_id=int(user_profile_id),
				feature_key="essay_brainstorm",
				source="essay_generate_ideas_api",
				metadata={
					"topic": data.get("topic"),
					"tags": data.get("tags", []),
				},
			)
			if not success:
				return jsonify({
					"error": "Insufficient tokens",
					"details": token_result
				}), HTTPStatus.PAYMENT_REQUIRED

			# Call Cerebras API
			cerebras_api_key = os.getenv("CEREBRAS_API_KEY")
			if not cerebras_api_key:
				return jsonify({"error": "Cerebras API key not configured"}), HTTPStatus.INTERNAL_SERVER_ERROR

			system_prompt = """You are a creative college admissions essay brainstorming coach. Generate unique, compelling essay ideas based on the student's input.

Your response MUST be valid JSON in this exact format:
{
  "ideas": [
    {"id": "1", "text": "<detailed essay idea with angle and approach>"},
    {"id": "2", "text": "<another unique essay idea>"},
    {"id": "3", "text": "<creative alternative approach>"},
    {"id": "4", "text": "<unexpected angle on the topic>"},
    {"id": "5", "text": "<personal growth focused idea>"}
  ]
}

Each idea should be 2-3 sentences explaining the concept, angle, and how to make it compelling."""

			user_prompt = "Generate essay ideas based on:\n"
			if data.get("topic"):
				user_prompt += f"\nTopic/Theme: {data.get('topic')}"
			if data.get("cogins1"):
				user_prompt += f"\nContext 1: {data.get('cogins1')}"
			if data.get("cogins2"):
				user_prompt += f"\nContext 2: {data.get('cogins2')}"
			if data.get("key_experiences"):
				user_prompt += f"\nKey Experiences: {data.get('key_experiences')}"
			if data.get("tags") and len(data.get("tags", [])):
				user_prompt += f"\nThemes to incorporate: {', '.join(data.get('tags', []))}"

			cerebras_response = requests.post(
				"https://api.cerebras.ai/v1/chat/completions",
				json={
					"model": "llama3.1-8b",
					"messages": [
						{"role": "system", "content": system_prompt},
						{"role": "user", "content": user_prompt}
					],
					"max_tokens": 2000,
					"temperature": 0.7,
				},
				headers={
					"Authorization": f"Bearer {cerebras_api_key}",
					"Content-Type": "application/json",
				},
				timeout=60,
			)

			if cerebras_response.status_code != 200:
				return jsonify({
					"error": f"Cerebras API error: {cerebras_response.text}"
				}), HTTPStatus.INTERNAL_SERVER_ERROR

			response_data = cerebras_response.json()
			content = response_data.get("choices", [{}])[0].get("message", {}).get("content", "")

			# Parse JSON from response
			import re
			json_match = re.search(r'\{[\s\S]*\}', content)
			if json_match:
				parsed = json.loads(json_match.group(0))
				ideas = parsed.get("ideas", [])
				return jsonify({"ideas": ideas}), HTTPStatus.OK

			return jsonify({"error": "Failed to parse AI response"}), HTTPStatus.INTERNAL_SERVER_ERROR

		except json.JSONDecodeError as e:
			return jsonify({"error": f"Invalid JSON in response: {str(e)}"}), HTTPStatus.INTERNAL_SERVER_ERROR
		except Exception as e:
			print(f"❌ ERROR in /essay/generate-ideas: {str(e)}")
			import traceback
			print(traceback.format_exc())
			return jsonify({"error": str(e)}), HTTPStatus.INTERNAL_SERVER_ERROR

	@app.get("/tokens/balance/<int:user_profile_id>")
	def get_token_balance(user_profile_id: int):
		"""
		Return the current token balance for a user.
		"""
		try:
			user_exists, error_response = _validate_user_exists(user_profile_id)
			if not user_exists:
				return jsonify(error_response), HTTPStatus.NOT_FOUND
			
			supabase = get_supabase()
			resp = supabase.table("user_profile").select("token_balance").eq("id", user_profile_id).execute()
			if not resp.data:
				return jsonify({"error": f"User profile {user_profile_id} not found"}), HTTPStatus.NOT_FOUND
			
			return jsonify({
				"user_profile_id": user_profile_id,
				"token_balance": resp.data[0].get("token_balance", 0)
			}), HTTPStatus.OK
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR

	@app.get("/tokens/history/<int:user_profile_id>")
	def get_token_history(user_profile_id: int):
		"""
		Return recent token transactions for a user (descending by created_at).
		Optional query param: default 50.
		"""
		try:
			user_exists, error_response = _validate_user_exists(user_profile_id)
			if not user_exists:
				return jsonify(error_response), HTTPStatus.NOT_FOUND

			limit_param = request.args.get("limit", "50")
			try:
				limit = max(1, min(int(limit_param), 200))
			except ValueError:
				continue_limit = 50
				limit = continue_limit

			supabase = get_supabase()
			resp = (
				supabase
				.table("token_transactions")
				.select("*")
				.eq("user_profile_id", user_profile_id)
				.order("created_at", desc=True)
				.limit(limit)
				.execute()
			)
			return jsonify({
				"user_profile_id": user_profile_id,
				"count": len(resp.data) if resp.data else 0,
				"transactions": resp.data or []
			}), HTTPStatus.OK
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR

	@app.post("/search_universities")
	def search_universities():
		payload = request.get_json(silent=True) or {}
		user_profile_id = payload.get("user_profile_id")
		
		if not user_profile_id:
			return jsonify({"error": "user_profile_id is required"}), HTTPStatus.BAD_REQUEST
		
		try:
			supabase = get_supabase()

			# Validate user exists
			user_exists, error_response = _validate_user_exists(user_profile_id)
			if not user_exists:
				return jsonify(error_response), HTTPStatus.NOT_FOUND

			# Token check & debit
			token_ok, token_details = _consume_tokens(
				user_profile_id=user_profile_id,
				feature_key="university_search",
				source="api:/search_universities",
				metadata={"endpoint": "/search_universities"}
			)
			if not token_ok:
				error_code = (token_details or {}).get("error")
				if error_code == "INSUFFICIENT_TOKENS":
					return jsonify({
						"error": "INSUFFICIENT_TOKENS",
						"message": "Not enough tokens to run University Match / Search.",
						"required_tokens": TOKEN_COSTS.get("university_search"),
						"current_balance": token_details.get("balance"),
					}), HTTPStatus.PAYMENT_REQUIRED
				# Fallback generic error
				return jsonify({
					"error": "TOKEN_CONSUME_FAILED",
					"details": token_details,
				}), HTTPStatus.INTERNAL_SERVER_ERROR
			
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
		changed_fields_raw = payload.get("changed_fields", [])
		
		# CRITICAL: Ensure changed_fields is always a list to prevent "argument of type 'int' is not iterable" errors
		if not isinstance(changed_fields_raw, list):
			print(f"WARNING: changed_fields is not a list! Type: {type(changed_fields_raw)}, Value: {changed_fields_raw}. Converting to empty list.")
			changed_fields = []
		else:
			changed_fields = changed_fields_raw
		
		if not user_profile_id:
			return jsonify({"error": "user_profile_id is required"}), HTTPStatus.BAD_REQUEST
		
		try:
			supabase = get_supabase()
			
			# Verify user profile exists
			user_exists, error_response = _validate_user_exists(user_profile_id)
			if not user_exists:
				return jsonify(error_response), HTTPStatus.NOT_FOUND

			profile_resp = supabase.table("user_profile").select("*").eq("id", user_profile_id).execute()
			if not profile_resp.data:
				return jsonify({"error": f"User profile {user_profile_id} not found"}), HTTPStatus.NOT_FOUND
			
			user_profile = profile_resp.data[0]

			# Token check & debit
			token_ok, token_details = _consume_tokens(
				user_profile_id=user_profile_id,
				feature_key="scholarship_search",
				source="api:/search_scholarships",
				metadata={
					"endpoint": "/search_scholarships",
					"delta_search": delta_search,
					"changed_fields": changed_fields,
				},
			)
			if not token_ok:
				error_code = (token_details or {}).get("error")
				if error_code == "INSUFFICIENT_TOKENS":
					return jsonify({
						"error": "INSUFFICIENT_TOKENS",
						"message": "Not enough tokens to run Scholarship Match / Search.",
						"required_tokens": TOKEN_COSTS.get("scholarship_search"),
						"current_balance": token_details.get("balance"),
					}), HTTPStatus.PAYMENT_REQUIRED
				return jsonify({
					"error": "TOKEN_CONSUME_FAILED",
					"details": token_details,
				}), HTTPStatus.INTERNAL_SERVER_ERROR
			
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
				import traceback
				error_traceback = traceback.format_exc()
				print(f"ERROR in scholarship search - Full traceback:")
				print(error_traceback)
				print(f"ERROR Type: {type(e).__name__}")
				print(f"ERROR Message: {str(e)}")
				return jsonify({
					"error": f"Scholarship search execution failed: {str(e)}",
					"error_type": type(e).__name__,
					"traceback": error_traceback,
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

		# Token check & debit
		token_ok, token_details = _consume_tokens(
			user_profile_id=user_profile_id,
			feature_key="visa_services",
			source="api:/visa_info",
			metadata={
				"endpoint": "/visa_info",
				"citizenship": citizenship,
				"destination": destination,
			},
		)
		if not token_ok:
			error_code = (token_details or {}).get("error")
			if error_code == "INSUFFICIENT_TOKENS":
				return jsonify({
					"error": "INSUFFICIENT_TOKENS",
					"message": "Not enough tokens to run Visa Services.",
					"required_tokens": TOKEN_COSTS.get("visa_services"),
					"current_balance": token_details.get("balance"),
				}), HTTPStatus.PAYMENT_REQUIRED
			return jsonify({
				"error": "TOKEN_CONSUME_FAILED",
				"details": token_details,
			}), HTTPStatus.INTERNAL_SERVER_ERROR
		
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
						"overview": {"universities_found": 0, "scholarships_found": 0, "application_requirements": 0, "visa_info_count": 0},
						"advice": ""
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
					"advice": summary_data.get("advice", ""),
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
		Get prioritized next actions for a user using the Next Steps Generator Agent.
		Updates the admissions_summary table with the generated next steps.
		
		GET /admissions/next_steps/{user_id}
		"""
		try:
			# Validate user exists
			user_exists, error_response = _validate_user_exists(user_id)
			if not user_exists:
				return jsonify(error_response), HTTPStatus.NOT_FOUND
			
			supabase = get_supabase()
			
			# Execute Next Steps Generator Agent using SearchCrew
			try:
				from agents.crew import SearchCrew
				from crewai import Crew, Process
				
				# Create SearchCrew instance
				search_crew_instance = SearchCrew()
				
				# Get the next_steps_generator_agent and next_steps_generator_task
				next_steps_agent = search_crew_instance.next_steps_generator_agent()
				next_steps_task = search_crew_instance.next_steps_generator_task()
				
				# Create crew with just the Next Steps Generator Agent and Task
				next_steps_crew = Crew(
					agents=[next_steps_agent],
					tasks=[next_steps_task],
					process=Process.sequential,
					verbose=True
				)
				
				inputs = {
					'user_id': user_id,
					'current_year': str(datetime.now().year),
					'next_year': str(datetime.now().year + 1),
					'today': datetime.now().date().isoformat()
				}
				
				print(f"\n=== GENERATING NEXT STEPS - User ID: {user_id} ===")
				result = next_steps_crew.kickoff(inputs=inputs)
				agent_output = result.raw if hasattr(result, 'raw') else str(result)
				
				print(f"\nNEXT STEPS GENERATOR OUTPUT:")
				print("=" * 60)
				print(agent_output)
				print("=" * 60)
				
				# Parse agent output - extract JSON array
				cleaned_output = agent_output.strip()
				start_idx = cleaned_output.find('[')
				end_idx = cleaned_output.rfind(']')
				
				if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
					json_content = cleaned_output[start_idx:end_idx + 1]
					try:
						next_steps = json.loads(json_content)
						print(f"✅ Parsed next steps successfully: {len(next_steps)} steps")
					except json.JSONDecodeError as e:
						print(f"⚠️ Could not parse agent output as JSON: {e}")
						next_steps = []
				else:
					print(f"⚠️ No JSON array found in agent output")
					next_steps = []
					
			except ImportError:
				print("⚠️ CrewAI agents not available, falling back to empty next steps")
				next_steps = []
			except Exception as e:
				print(f"⚠️ Next Steps Generator Agent execution failed: {e}")
				next_steps = []
			
			# Update admissions_summary table with generated next steps
			summary_resp = supabase.table("admissions_summary").select("*").eq("user_id", user_id).order("last_updated", desc=True).limit(1).execute()
			
			if summary_resp.data:
				# Update existing summary
				supabase.table("admissions_summary").update({
					"next_steps": next_steps,
					"last_updated": datetime.now().isoformat()
				}).eq("id", summary_resp.data[0]["id"]).execute()
			else:
				# Create new summary entry if it doesn't exist
				supabase.table("admissions_summary").insert({
					"user_id": user_id,
					"next_steps": next_steps,
					"last_updated": datetime.now().isoformat()
				}).execute()
			
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

	# =======================================================
	# Stripe Payment Endpoints
	# =======================================================

	@app.post("/stripe/create-payment-intent")
	def create_payment_intent():
		"""
		Create a Stripe Payment Intent for one-time payments.
		
		POST /stripe/create-payment-intent
		Body: {
			"amount": 2000,  # Amount in cents (e.g., 2000 = $20.00)
			"currency": "usd",
			"user_profile_id": 1,
			"metadata": {}  # Optional metadata
		}
		"""
		try:
			payload = request.get_json(silent=True) or {}
			amount = payload.get("amount")
			currency = payload.get("currency", "usd")
			user_profile_id = payload.get("user_profile_id")
			metadata = payload.get("metadata", {})
			
			if not amount or amount <= 0:
				return jsonify({"error": "Valid amount is required (in cents)"}), HTTPStatus.BAD_REQUEST
			
			if not user_profile_id:
				return jsonify({"error": "user_profile_id is required"}), HTTPStatus.BAD_REQUEST
			
			# Validate user exists
			user_exists, error_response = _validate_user_exists(user_profile_id)
			if not user_exists:
				return jsonify(error_response), HTTPStatus.NOT_FOUND
			
			# Initialize Stripe
			stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
			if not stripe.api_key:
				return jsonify({"error": "Stripe secret key not configured"}), HTTPStatus.INTERNAL_SERVER_ERROR
			
			# Create Payment Intent
			payment_intent = stripe.PaymentIntent.create(
				amount=int(amount),
				currency=currency.lower(),
				metadata={
					"user_profile_id": str(user_profile_id),
					**metadata
				},
				automatic_payment_methods={
					"enabled": True,
				},
			)
			
			return jsonify({
				"client_secret": payment_intent.client_secret,
				"payment_intent_id": payment_intent.id,
				"amount": payment_intent.amount,
				"currency": payment_intent.currency
			}), HTTPStatus.OK
			
		except stripe.error.StripeError as e:
			return jsonify({"error": f"Stripe error: {str(e)}"}), HTTPStatus.BAD_REQUEST
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR

	@app.post("/stripe/create-subscription")
	def create_subscription():
		"""
		Create a Stripe Subscription for recurring payments.
		
		POST /stripe/create-subscription
		Body: {
			"price_id": "price_xxxxx",  # Stripe Price ID
			"user_profile_id": 1,
			"payment_method_id": "pm_xxxxx"  # Optional, can be set later
		}
		"""
		try:
			payload = request.get_json(silent=True) or {}
			price_id = payload.get("price_id")
			user_profile_id = payload.get("user_profile_id")
			payment_method_id = payload.get("payment_method_id")
			
			if not price_id:
				return jsonify({"error": "price_id is required"}), HTTPStatus.BAD_REQUEST
			
			if not user_profile_id:
				return jsonify({"error": "user_profile_id is required"}), HTTPStatus.BAD_REQUEST
			
			# Simplified local-dev flow: bypass Supabase and always create
			# a temporary Stripe customer + subscription. This avoids 404s
			# when user_profile isn't seeded yet.
			stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
			if not stripe.api_key:
				return jsonify({"error": "Stripe secret key not configured"}), HTTPStatus.INTERNAL_SERVER_ERROR
			
			customer = stripe.Customer.create(
				email=f"dev-user-{user_profile_id}@example.com",
				metadata={"user_profile_id": str(user_profile_id)}
			)
			
			subscription_data = {
				"customer": customer.id,
				"items": [{"price": price_id}],
				"metadata": {"user_profile_id": str(user_profile_id)},
				# For local/dev: allow subscription creation without an attached
				# payment method. Newer Stripe API versions no longer support
				# expanding latest_invoice.payment_intent, so we avoid using it.
				"payment_behavior": "default_incomplete",
			}
			
			if payment_method_id:
				subscription_data["default_payment_method"] = payment_method_id
			
			subscription = stripe.Subscription.create(**subscription_data)
			
			return jsonify({
				"subscription_id": subscription.id,
				"client_secret": None,  # Not available in newer Stripe API without separate PI creation
				"status": subscription.status,
				"customer_id": customer.id,
				"dev_mode": True
			}), HTTPStatus.OK
			
		except stripe.error.StripeError as e:
			return jsonify({"error": f"Stripe error: {str(e)}"}), HTTPStatus.BAD_REQUEST
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR

	@app.post("/stripe/create-checkout-session")
	def create_checkout_session():
		"""
		Create a Stripe Checkout Session for subscription payments.

		POST /stripe/create-checkout-session
		Body: {
			"price_id": "price_xxx",        # Stripe Price ID (recurring)
			"user_profile_id": 1,           # Optional in dev; used for metadata
			"success_url": "https://...",
			"cancel_url": "https://..."
		}
		Returns: { "url": "https://checkout.stripe.com/..." }
		"""
		try:
			payload = request.get_json(silent=True) or {}
			price_id = payload.get("price_id")
			user_profile_id = payload.get("user_profile_id")
			success_url = payload.get("success_url")
			cancel_url = payload.get("cancel_url")

			if not price_id:
				return jsonify({"error": "price_id is required"}), HTTPStatus.BAD_REQUEST

			if not success_url or not cancel_url:
				return jsonify({"error": "success_url and cancel_url are required"}), HTTPStatus.BAD_REQUEST

			stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
			if not stripe.api_key:
				return jsonify({"error": "Stripe secret key not configured"}), HTTPStatus.INTERNAL_SERVER_ERROR

			supabase = get_supabase()
			customer_id = None
			
			# Get or create Stripe customer
			if user_profile_id:
				# Check if user already has a Stripe customer ID
				# Handle case where stripe_customer_id column might not exist yet
				profile_resp = None
				user_name = ""
				
				# Try to get profile with stripe_customer_id, fallback to just full_name if column doesn't exist
				# First, try to get just full_name to avoid the column error
				try:
					profile_resp = supabase.table("user_profile").select("full_name").eq("id", user_profile_id).execute()
					if profile_resp.data:
						user_name = profile_resp.data[0].get("full_name", "")
				except Exception as e:
					print(f"WARNING: Could not fetch user profile: {str(e)}")
					profile_resp = None
				
				# Now try to get stripe_customer_id if column exists
				try:
					stripe_customer_resp = supabase.table("user_profile").select("stripe_customer_id").eq("id", user_profile_id).execute()
					if stripe_customer_resp.data and stripe_customer_resp.data[0].get("stripe_customer_id"):
						customer_id = stripe_customer_resp.data[0]["stripe_customer_id"]
						# Verify customer exists in Stripe
						try:
							stripe.Customer.retrieve(customer_id)
						except stripe.error.InvalidRequestError:
							# Customer doesn't exist in Stripe, create new one
							customer_id = None
				except Exception as e:
					# Column might not exist yet (PGRST204) - that's okay, we'll create a new customer
					error_str = str(e)
					if "PGRST204" in error_str or "stripe_customer_id" in error_str or "Could not find" in error_str or "does not exist" in error_str or "42703" in error_str:
						print(f"WARNING: stripe_customer_id column not found, creating new customer. Run migration SQL to add column.")
						customer_id = None
					else:
						# Other error - log but continue (don't fail the checkout)
						print(f"WARNING: Error checking stripe_customer_id: {str(e)}")
						customer_id = None
				
				if not customer_id:
					# Create new Stripe customer
					customer = stripe.Customer.create(
						email=f"user-{user_profile_id}@pgadmit.com",
						name=user_name if user_name else None,
						metadata={"user_profile_id": str(user_profile_id)},
					)
					customer_id = customer.id
					
					# Store customer ID in user_profile (if column exists)
					try:
						supabase.table("user_profile").update({
							"stripe_customer_id": customer_id
						}).eq("id", user_profile_id).execute()
					except Exception as e:
						# Column doesn't exist - log warning but continue (this is expected if migration not run)
						error_str = str(e)
						if "PGRST204" in error_str or "stripe_customer_id" in error_str or "does not exist" in error_str or "42703" in error_str:
							print(f"WARNING: Could not save stripe_customer_id - column doesn't exist. Run migration SQL.")
						else:
							# Other error - log but don't fail
							print(f"WARNING: Could not save stripe_customer_id: {str(e)}")
			else:
				# No user_profile_id, create temporary customer
				customer = stripe.Customer.create(
					email=f"dev-checkout-{user_profile_id or 'anon'}@example.com",
					metadata={"user_profile_id": str(user_profile_id)} if user_profile_id else None,
				)
				customer_id = customer.id

			session = stripe.checkout.Session.create(
				mode="subscription",
				payment_method_types=["card"],
				customer=customer_id,
				line_items=[{"price": price_id, "quantity": 1}],
				success_url=success_url,
				cancel_url=cancel_url,
				metadata={
					"user_profile_id": str(user_profile_id) if user_profile_id else "",
				},
			)

			return jsonify({
				"url": session.url,
				"session_id": session.id,
			}), HTTPStatus.OK

		except stripe.error.StripeError as e:
			return jsonify({"error": f"Stripe error: {str(e)}"}), HTTPStatus.BAD_REQUEST
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR

	@app.get("/stripe/subscription/<int:user_profile_id>")
	def get_subscription(user_profile_id: int):
		"""
		Get subscription details for a user from database.
		
		GET /stripe/subscription/<user_profile_id>
		"""
		try:
			# Validate user exists
			user_exists, error_response = _validate_user_exists(user_profile_id)
			if not user_exists:
				return jsonify(error_response), HTTPStatus.NOT_FOUND
			
			supabase = get_supabase()
			
			# Get active subscription from database (handle missing table gracefully)
			try:
				subscription_resp = supabase.table("user_subscriptions").select("*").eq("user_profile_id", user_profile_id).eq("status", "active").order("created_at", desc=True).limit(1).execute()
			except Exception as e:
				if "Could not find the table" in str(e) or "PGRST205" in str(e):
					print(f"WARNING: user_subscriptions table not found. Run migration SQL.")
					return jsonify({"subscription": None, "message": "No active subscription found"}), HTTPStatus.OK
				else:
					raise
			
			if subscription_resp.data and len(subscription_resp.data) > 0:
				sub = subscription_resp.data[0]
				return jsonify({
					"subscription_id": sub["stripe_subscription_id"],
					"plan_id": sub["plan_id"],
					"plan_name": sub["plan_name"],
					"status": sub["status"],
					"current_period_start": sub["current_period_start"],
					"current_period_end": sub["current_period_end"],
					"cancel_at_period_end": sub["cancel_at_period_end"],
					"amount": sub["amount"],
					"currency": sub["currency"],
					"interval": sub["interval"],
					"price_id": sub["price_id"]
				}), HTTPStatus.OK
			else:
				return jsonify({"subscription": None, "message": "No active subscription found"}), HTTPStatus.OK
				
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR

	@app.post("/stripe/webhook")
	def stripe_webhook():
		"""
		Handle Stripe webhook events.
		This endpoint should be configured in Stripe Dashboard with webhook signing secret.
		
		POST /stripe/webhook
		"""
		payload = request.get_data(as_text=True)
		sig_header = request.headers.get("Stripe-Signature")
		webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
		
		if not webhook_secret:
			return jsonify({"error": "Webhook secret not configured"}), HTTPStatus.INTERNAL_SERVER_ERROR
		
		try:
			event = stripe.Webhook.construct_event(
				payload, sig_header, webhook_secret
			)
		except ValueError as e:
			# Invalid payload
			return jsonify({"error": "Invalid payload"}), HTTPStatus.BAD_REQUEST
		except stripe.error.SignatureVerificationError as e:
			# Invalid signature
			return jsonify({"error": "Invalid signature"}), HTTPStatus.BAD_REQUEST
		
		# Handle the event
		event_type = event["type"]
		event_data = event["data"]["object"]
		print(f"📥 Webhook received: {event_type} (event_id={event.get('id')})")
		
		try:
			supabase = get_supabase()
			
			if event_type == "payment_intent.succeeded":
				# Payment succeeded - log in payment_history
				user_profile_id = event_data.get("metadata", {}).get("user_profile_id")
				if user_profile_id:
					# Get subscription if this payment is for a subscription
					subscription_id = None
					if event_data.get("invoice"):
						invoice_id = event_data.get("invoice")
						# Try to find subscription from invoice
						try:
							invoice = stripe.Invoice.retrieve(invoice_id)
							if invoice.subscription:
								try:
									sub_resp = supabase.table("user_subscriptions").select("id").eq("stripe_subscription_id", invoice.subscription).execute()
									if sub_resp.data:
										subscription_id = sub_resp.data[0]["id"]
								except Exception as e:
									if "Could not find the table" in str(e) or "PGRST205" in str(e):
										print(f"WARNING: user_subscriptions table not found when logging payment")
									else:
										pass
						except:
							pass
					
					# Try to log payment (handle missing table gracefully)
					try:
						supabase.table("payment_history").insert({
							"user_profile_id": int(user_profile_id),
							"subscription_id": subscription_id,
							"stripe_payment_intent_id": event_data["id"],
							"amount": event_data["amount"],
							"currency": event_data["currency"],
							"status": "succeeded",
							"description": event_data.get("description"),
							"receipt_url": event_data.get("charges", {}).get("data", [{}])[0].get("receipt_url") if event_data.get("charges") else None
						}).execute()
						print(f"✅ Payment succeeded for user {user_profile_id}")
					except Exception as e:
						error_str = str(e)
						if "Could not find the table" in error_str or "PGRST205" in error_str:
							print(f"WARNING: payment_history table not found. Payment logged in Stripe but not in database.")
						else:
							print(f"WARNING: Could not log payment to database: {str(e)}")
			
			elif event_type == "payment_intent.payment_failed":
				# Payment failed
				user_profile_id = event_data.get("metadata", {}).get("user_profile_id")
				if user_profile_id:
					supabase.table("payment_history").insert({
						"user_profile_id": int(user_profile_id),
						"stripe_payment_intent_id": event_data["id"],
						"amount": event_data["amount"],
						"currency": event_data["currency"],
						"status": "failed",
						"failure_reason": event_data.get("last_payment_error", {}).get("message", "Unknown")
					}).execute()
					print(f"Payment failed for user {user_profile_id}")
			
			elif event_type == "customer.subscription.created":
				# Subscription created - store in database
				subscription_id = event_data["id"]
				customer_id = event_data["customer"]
				
				# Get user_profile_id from customer metadata or lookup
				user_profile_id = event_data.get("metadata", {}).get("user_profile_id")
				if not user_profile_id:
					# Try to get from customer
					try:
						customer = stripe.Customer.retrieve(customer_id)
						user_profile_id = customer.metadata.get("user_profile_id")
					except:
						pass
				
				if user_profile_id:
					# Get price details
					price_id = event_data["items"]["data"][0]["price"]["id"]
					price_obj = event_data["items"]["data"][0]["price"]
					amount = price_obj["unit_amount"]
					currency = price_obj["currency"]
					interval = price_obj["recurring"]["interval"]
					
					# Determine plan_id from price_id (configurable mapping).
					# Keep these in sync with Stripe and frontend Billing.tsx.
					plan_id = "starter"  # Default / Free
					plan_name = "Free"   # Match frontend naming

					# Tier 2 – INR 999/month
					if "price_1SfKELGMytl1afSZ2ZoOMePT" in price_id:
						plan_id = "pro"
						plan_name = "Tier 2"
					# Tier 3 – INR 1,799/month
					elif "price_1SfKEuGMytl1afSZP7SnBVOn" in price_id:
						plan_id = "team"
						plan_name = "Tier 3"
					
					# Helper function to safely convert timestamp to ISO string
					def safe_timestamp_to_iso(timestamp_value):
						if timestamp_value is None:
							return None
						if isinstance(timestamp_value, (int, float)):
							return datetime.fromtimestamp(timestamp_value).isoformat()
						if isinstance(timestamp_value, str):
							return timestamp_value
						return timestamp_value.isoformat() if hasattr(timestamp_value, 'isoformat') else str(timestamp_value)
					
					# Try to insert subscription (handle missing table gracefully)
					try:
						# Safely extract timestamp fields
						current_period_start = safe_timestamp_to_iso(event_data.get("current_period_start"))
						current_period_end = safe_timestamp_to_iso(event_data.get("current_period_end"))
						
						if not current_period_start or not current_period_end:
							# Fallback: use current time if missing
							now = datetime.now().isoformat()
							if not current_period_start:
								current_period_start = now
							if not current_period_end:
								# Add 1 month if interval is month, 1 year if year
								if interval == "month":
									current_period_end = (datetime.now() + timedelta(days=30)).isoformat()
								elif interval == "year":
									current_period_end = (datetime.now() + timedelta(days=365)).isoformat()
								else:
									current_period_end = (datetime.now() + timedelta(days=30)).isoformat()
						
						supabase.table("user_subscriptions").insert({
							"user_profile_id": int(user_profile_id),
							"stripe_subscription_id": subscription_id,
							"stripe_customer_id": customer_id,
							"plan_id": plan_id,
							"plan_name": plan_name,
							"price_id": price_id,
							"status": event_data["status"],
							"current_period_start": current_period_start,
							"current_period_end": current_period_end,
							"cancel_at_period_end": event_data.get("cancel_at_period_end", False),
							"trial_start": safe_timestamp_to_iso(event_data.get("trial_start")),
							"trial_end": safe_timestamp_to_iso(event_data.get("trial_end")),
							"amount": amount,
							"currency": currency,
							"interval": interval,
							"metadata": json.dumps(event_data.get("metadata", {}))
						}).execute()
						print(f"✅ Subscription created for user {user_profile_id}")

						# Credit initial plan tokens
						tokens_to_credit = PLAN_TOKEN_GRANTS.get(plan_id)
						if tokens_to_credit:
							print(f"💰 Crediting {tokens_to_credit} tokens to user {user_profile_id} for subscription_created (plan={plan_name}, plan_id={plan_id})")
							_credit_tokens(
								user_profile_id=int(user_profile_id),
								amount=tokens_to_credit,
								reason="subscription_created",
								source="stripe_webhook",
								feature_key=None,
								metadata={
									"stripe_subscription_id": subscription_id,
									"price_id": price_id,
									"plan_id": plan_id,
									"plan_name": plan_name,
								},
							)
							print(f"✅ Token credit completed for user {user_profile_id}")
						else:
							print(f"⚠️  WARNING: No token grant configured for plan_id={plan_id}")
					except Exception as e:
						error_str = str(e)
						# Always try to credit tokens even if subscription save fails
						tokens_to_credit = PLAN_TOKEN_GRANTS.get(plan_id)
						if tokens_to_credit:
							print(f"💰 Attempting to credit tokens despite subscription save error: {tokens_to_credit} tokens to user {user_profile_id}")
							try:
								_credit_tokens(
									user_profile_id=int(user_profile_id),
									amount=tokens_to_credit,
									reason="subscription_created",
									source="stripe_webhook",
									feature_key=None,
									metadata={
										"stripe_subscription_id": subscription_id,
										"price_id": price_id,
										"plan_id": plan_id,
										"plan_name": plan_name,
										"error": error_str,
										"note": "Credited despite subscription save error"
									},
								)
								print(f"✅ Token credit completed despite subscription save error")
							except Exception as token_error:
								print(f"❌ ERROR crediting tokens: {token_error}")
						
						if "Could not find the table" in error_str or "PGRST205" in error_str:
							print(f"❌ ERROR: user_subscriptions table not found! Subscription {subscription_id} for user {user_profile_id} was created in Stripe but NOT saved to database.")
							print(f"   Run the migration SQL in Supabase to create the table, then manually sync this subscription.")
							print(f"   Subscription details: plan={plan_name}, customer={customer_id}, subscription={subscription_id}")
						else:
							print(f"❌ ERROR: Failed to save subscription to database: {str(e)}")
							# Don't raise - we've already credited tokens, so webhook should return success
			
			elif event_type == "customer.subscription.updated":
				# Subscription updated - update in database
				subscription_id = event_data["id"]
				
				update_data = {
						"status": event_data["status"],
						"current_period_start": datetime.fromtimestamp(event_data["current_period_start"]).isoformat(),
						"current_period_end": datetime.fromtimestamp(event_data["current_period_end"]).isoformat(),
						"cancel_at_period_end": event_data.get("cancel_at_period_end", False),
						"updated_at": datetime.now().isoformat()
					}
				
				if event_data.get("canceled_at"):
					update_data["canceled_at"] = datetime.fromtimestamp(event_data["canceled_at"]).isoformat()
				
				supabase.table("user_subscriptions").update(update_data).eq("stripe_subscription_id", subscription_id).execute()
				print(f"Subscription updated: {subscription_id}")
			
			elif event_type == "customer.subscription.deleted":
				# Subscription cancelled - update status
				subscription_id = event_data["id"]
				supabase.table("user_subscriptions").update({
					"status": "canceled",
					"canceled_at": datetime.fromtimestamp(event_data.get("canceled_at", datetime.now().timestamp())).isoformat(),
					"updated_at": datetime.now().isoformat()
				}).eq("stripe_subscription_id", subscription_id).execute()
				print(f"Subscription cancelled: {subscription_id}")
			
			elif event_type == "invoice.payment_succeeded":
				# Invoice payment succeeded - log in payment_history and credit recurring tokens
				invoice = event_data
				customer_id = invoice["customer"]
				
				# Get user_profile_id from customer
				user_profile_id = None
				try:
					customer = stripe.Customer.retrieve(customer_id)
					user_profile_id = customer.metadata.get("user_profile_id")
				except Exception:
					pass
				
				if user_profile_id:
					subscription_id = None
					plan_id = None
					plan_name = None

					# Find subscription in database (handle missing table gracefully)
					try:
						if invoice.get("subscription"):
							sub_resp = supabase.table("user_subscriptions").select("id, plan_id").eq("stripe_subscription_id", invoice["subscription"]).execute()
							if sub_resp.data:
								subscription_id = sub_resp.data[0]["id"]
								plan_id = sub_resp.data[0].get("plan_id")
								print(f"✅ Found subscription in database: plan_id={plan_id}")
					except Exception as e:
						if "Could not find the table" in str(e) or "PGRST205" in str(e):
							print(f"WARNING: user_subscriptions table not found when logging invoice payment")
						else:
							print(f"WARNING: Error fetching subscription for invoice payment: {e}")
					
					# If plan_id not found from database, try to get it from invoice price_id (fallback)
					if not plan_id and invoice.get("subscription") and invoice.get("lines", {}).get("data"):
						try:
							# Get price_id from invoice line items
							for line in invoice["lines"]["data"]:
								price = line.get("price") or {}
								price_id = price.get("id")
								if price_id:
									# Determine plan_id from price_id (same logic as subscription.created)
									# Tier 2 – INR 999/month
									if "price_1SfKELGMytl1afSZ2ZoOMePT" in price_id:
										plan_id = "pro"
										plan_name = "Tier 2"
										break
									# Tier 3 – INR 1,799/month
									elif "price_1SfKEuGMytl1afSZP7SnBVOn" in price_id:
										plan_id = "team"
										plan_name = "Tier 3"
										break
							if plan_id:
								print(f"✅ Determined plan_id={plan_id} from invoice price_id (fallback method)")
						except Exception as e:
							print(f"WARNING: Error determining plan_id from invoice price_id: {e}")
					
					# Try to log payment (handle missing table gracefully)
					try:
						supabase.table("payment_history").insert({
							"user_profile_id": int(user_profile_id),
							"subscription_id": subscription_id,
							"stripe_invoice_id": invoice["id"],
							"stripe_charge_id": invoice.get("charge"),
							"amount": invoice["amount_paid"],
							"currency": invoice["currency"],
							"status": "succeeded",
							"description": invoice.get("description") or f"Subscription payment",
							"receipt_url": invoice.get("hosted_invoice_url")
						}).execute()
						print(f"✅ Invoice payment succeeded for user {user_profile_id}")
					except Exception as e:
						error_str = str(e)
						if "Could not find the table" in error_str or "PGRST205" in error_str:
							print(f"WARNING: payment_history table not found. Payment logged in Stripe but not in database.")
						else:
							print(f"WARNING: Could not log invoice payment to database: {str(e)}")

					# Credit recurring plan tokens for subscription invoices
					if invoice.get("subscription"):
						if plan_id:
							# Check if this is the first invoice (subscription creation)
							# If billing_reason is "subscription_create", tokens were already credited in customer.subscription.created
							# So we skip crediting here to avoid double-crediting
							billing_reason = invoice.get("billing_reason")
							if billing_reason == "subscription_create":
								print(f"ℹ️  INFO: First invoice (subscription_create) - tokens already credited in customer.subscription.created event. Skipping to avoid double-credit.")
							else:
								# This is a recurring payment - credit tokens
								tokens_to_credit = PLAN_TOKEN_GRANTS.get(plan_id)
								if tokens_to_credit:
									print(f"💰 Crediting {tokens_to_credit} tokens to user {user_profile_id} for subscription_cycle (plan_id={plan_id}, plan_name={plan_name or 'N/A'}, invoice={invoice.get('id')}, billing_reason={billing_reason})")
									_credit_tokens(
										user_profile_id=int(user_profile_id),
										amount=tokens_to_credit,
										reason="subscription_cycle",
										source="stripe_webhook",
										feature_key=None,
										metadata={
											"stripe_invoice_id": invoice["id"],
											"stripe_subscription_id": invoice.get("subscription"),
											"plan_id": plan_id,
											"plan_name": plan_name,
											"billing_reason": billing_reason,
										},
									)
									print(f"✅ Token credit completed for user {user_profile_id}")
								else:
									print(f"⚠️  WARNING: No token grant configured for plan_id={plan_id} in subscription_cycle")
						else:
							print(f"⚠️  WARNING: Could not determine plan_id for subscription invoice {invoice.get('id')} - skipping token credit")
							print(f"   Invoice details: subscription={invoice.get('subscription')}, lines={len(invoice.get('lines', {}).get('data', []))}")
					else:
						print(f"ℹ️  INFO: Invoice {invoice.get('id')} has no subscription (one-time payment) - checking for token packs...")

					# Handle one-time token packs (no subscription) if configured
					if not invoice.get("subscription") and invoice.get("lines"):
						try:
							for line in invoice["lines"]["data"]:
								price = line.get("price") or {}
								price_id = price.get("id")
								if price_id and price_id in ONE_TIME_TOKEN_PACKS_BY_PRICE_ID:
									tokens = ONE_TIME_TOKEN_PACKS_BY_PRICE_ID[price_id]
									_credit_tokens(
										user_profile_id=int(user_profile_id),
										amount=tokens,
										reason="one_time_top_up",
										source="stripe_webhook",
										feature_key=None,
										metadata={
											"stripe_invoice_id": invoice["id"],
											"price_id": price_id,
										},
									)
									print(f"✅ Credited {tokens} tokens to user {user_profile_id} for one-time top-up (price_id={price_id})")
						except Exception as e:
							print(f"WARNING: Failed to credit one-time token pack from invoice {invoice.get('id')}: {e}")
			
			return jsonify({"status": "success"}), HTTPStatus.OK
			
		except Exception as exc:
			print(f"❌ Error processing webhook: {str(exc)}")
			import traceback
			print(f"Traceback: {traceback.format_exc()}")
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR
	
	@app.post("/stripe/sync-subscription")
	def sync_subscription():
		"""
		Manually sync a subscription from Stripe to the database.
		Useful if webhook failed or tables were missing when subscription was created.
		
		POST /stripe/sync-subscription
		Body: {
			"user_profile_id": 1,
			"subscription_id": "sub_xxxxx" (optional - will find from customer)
		}
		"""
		try:
			payload = request.get_json(silent=True) or {}
			user_profile_id = payload.get("user_profile_id")
			subscription_id = payload.get("subscription_id")
			
			if not user_profile_id:
				return jsonify({"error": "user_profile_id is required"}), HTTPStatus.BAD_REQUEST
			
			# Validate user exists
			user_exists, error_response = _validate_user_exists(user_profile_id)
			if not user_exists:
				return jsonify(error_response), HTTPStatus.NOT_FOUND
			
			stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
			if not stripe.api_key:
				return jsonify({"error": "Stripe secret key not configured"}), HTTPStatus.INTERNAL_SERVER_ERROR
			
			supabase = get_supabase()
			
			# Get Stripe customer ID from user profile
			customer_id = None
			try:
				profile_resp = supabase.table("user_profile").select("stripe_customer_id").eq("id", user_profile_id).execute()
				if profile_resp.data and profile_resp.data[0].get("stripe_customer_id"):
					customer_id = profile_resp.data[0]["stripe_customer_id"]
			except Exception as e:
				error_str = str(e)
				if "PGRST204" in error_str or "stripe_customer_id" in error_str:
					# Column doesn't exist - try to find customer by email or metadata
					print(f"WARNING: stripe_customer_id column not found, searching Stripe by metadata...")
				else:
					raise
			
			# If no customer_id, search Stripe by metadata
			# Note: Stripe Customer.list() doesn't support metadata filtering directly
			# We need to list customers and check metadata manually
			if not customer_id:
				try:
					customers = stripe.Customer.list(limit=100)
					for customer in customers.data:
						if customer.metadata and customer.metadata.get("user_profile_id") == str(user_profile_id):
							customer_id = customer.id
							# Try to save it if column exists
							try:
								supabase.table("user_profile").update({
									"stripe_customer_id": customer_id
								}).eq("id", user_profile_id).execute()
							except:
								pass  # Column might not exist
							break
				except Exception as e:
					print(f"WARNING: Error searching Stripe customers: {e}")
			
			if not customer_id:
				return jsonify({"error": "No Stripe customer found for this user"}), HTTPStatus.NOT_FOUND
			
			# Get subscription from Stripe
			if not subscription_id:
				subscriptions = stripe.Subscription.list(customer=customer_id, status="all", limit=1)
				if not subscriptions.data:
					return jsonify({"error": "No subscription found for this customer"}), HTTPStatus.NOT_FOUND
				subscription_id = subscriptions.data[0].id
			
			subscription = stripe.Subscription.retrieve(subscription_id)
			
			# Get price details
			price_id = subscription["items"]["data"][0]["price"]["id"]
			price_obj = subscription["items"]["data"][0]["price"]
			amount = price_obj["unit_amount"]
			currency = price_obj["currency"]
			interval = price_obj["recurring"]["interval"]
			
			# Determine plan_id from price_id (keep in sync with webhook + frontend)
			plan_id = "starter"
			plan_name = "Free"
			# Tier 2 – INR 999/month
			if "price_1SfKELGMytl1afSZ2ZoOMePT" in price_id:
				plan_id = "pro"
				plan_name = "Tier 2"
			# Tier 3 – INR 1,799/month
			elif "price_1SfKEuGMytl1afSZP7SnBVOn" in price_id:
				plan_id = "team"
				plan_name = "Tier 3"
			
			# Helper function to safely convert timestamp to ISO string
			def safe_timestamp_to_iso(timestamp_value):
				if timestamp_value is None:
					return None
				if isinstance(timestamp_value, (int, float)):
					return datetime.fromtimestamp(timestamp_value).isoformat()
				# If already a string or datetime, return as-is or convert
				if isinstance(timestamp_value, str):
					return timestamp_value
				return timestamp_value.isoformat() if hasattr(timestamp_value, 'isoformat') else str(timestamp_value)
			
			# Save to database
			try:
				# Check if subscription already exists
				existing = supabase.table("user_subscriptions").select("id").eq("stripe_subscription_id", subscription_id).execute()
				
				# Safely extract timestamp fields
				current_period_start = safe_timestamp_to_iso(subscription.get("current_period_start"))
				current_period_end = safe_timestamp_to_iso(subscription.get("current_period_end"))
				
				if not current_period_start or not current_period_end:
					# Fallback: use current time if missing
					now = datetime.now().isoformat()
					if not current_period_start:
						current_period_start = now
						print(f"⚠️  WARNING: current_period_start missing, using current time")
					if not current_period_end:
						# Add 1 month if interval is month, 1 year if year
						if interval == "month":
							current_period_end = (datetime.now() + timedelta(days=30)).isoformat()
						elif interval == "year":
							current_period_end = (datetime.now() + timedelta(days=365)).isoformat()
						else:
							current_period_end = (datetime.now() + timedelta(days=30)).isoformat()
						print(f"⚠️  WARNING: current_period_end missing, using estimated end time")
				
				sub_data = {
					"user_profile_id": int(user_profile_id),
					"stripe_subscription_id": subscription_id,
					"stripe_customer_id": customer_id,
					"plan_id": plan_id,
					"plan_name": plan_name,
					"price_id": price_id,
					"status": subscription["status"],
					"current_period_start": current_period_start,
					"current_period_end": current_period_end,
					"cancel_at_period_end": subscription.get("cancel_at_period_end", False),
					"trial_start": safe_timestamp_to_iso(subscription.get("trial_start")),
					"trial_end": safe_timestamp_to_iso(subscription.get("trial_end")),
					"amount": amount,
					"currency": currency,
					"interval": interval,
					"metadata": json.dumps(subscription.get("metadata", {}))
				}
				
				if existing.data:
					# Update existing
					supabase.table("user_subscriptions").update(sub_data).eq("id", existing.data[0]["id"]).execute()
					print(f"✅ Subscription updated in database: {subscription_id}")
				else:
					# Insert new
					supabase.table("user_subscriptions").insert(sub_data).execute()
					print(f"✅ Subscription inserted into database: {subscription_id}")

				# Credit tokens regardless of whether subscription was updated or inserted
				# This ensures tokens are credited even if there was a previous error
				tokens_to_credit = PLAN_TOKEN_GRANTS.get(plan_id)
				if tokens_to_credit and subscription["status"] in ("active", "trialing"):
					print(f"💰 Crediting {tokens_to_credit} tokens to user {user_profile_id} for subscription sync (plan={plan_name}, plan_id={plan_id})")
					_credit_tokens(
						user_profile_id=int(user_profile_id),
						amount=tokens_to_credit,
						reason="subscription_synced",
						source="stripe_sync_subscription",
						feature_key=None,
						metadata={
							"stripe_subscription_id": subscription_id,
							"price_id": price_id,
							"plan_id": plan_id,
							"plan_name": plan_name,
						},
					)
					print(f"✅ Token credit completed for user {user_profile_id}")

				return jsonify({
					"message": "Subscription synced successfully" if not existing.data else "Subscription synced and updated",
					"subscription_id": subscription_id,
					"plan": plan_name,
					"status": subscription["status"],
					"tokens_credited": tokens_to_credit if tokens_to_credit and subscription["status"] in ("active", "trialing") else 0
				}), HTTPStatus.CREATED if not existing.data else HTTPStatus.OK
					
			except Exception as e:
				error_str = str(e)
				if "Could not find the table" in error_str or "PGRST205" in error_str:
					# Even if table is missing, try to credit tokens
					tokens_to_credit = PLAN_TOKEN_GRANTS.get(plan_id)
					if tokens_to_credit and subscription["status"] in ("active", "trialing"):
						print(f"💰 Attempting to credit tokens despite table error: {tokens_to_credit} tokens to user {user_profile_id}")
						_credit_tokens(
							user_profile_id=int(user_profile_id),
							amount=tokens_to_credit,
							reason="subscription_synced",
							source="stripe_sync_subscription",
							feature_key=None,
							metadata={
								"stripe_subscription_id": subscription_id,
								"price_id": price_id,
								"plan_id": plan_id,
								"plan_name": plan_name,
								"note": "Credited despite subscription table error"
							},
						)
					
					return jsonify({
						"error": "user_subscriptions table not found",
						"message": "Run the migration SQL in Supabase to create the table",
						"subscription_id": subscription_id,
						"plan": plan_name,
						"tokens_credited": tokens_to_credit if tokens_to_credit and subscription["status"] in ("active", "trialing") else 0
					}), HTTPStatus.SERVICE_UNAVAILABLE
				else:
					# For other errors, still try to credit tokens
					print(f"❌ ERROR saving subscription: {error_str}")
					tokens_to_credit = PLAN_TOKEN_GRANTS.get(plan_id)
					if tokens_to_credit and subscription["status"] in ("active", "trialing"):
						print(f"💰 Attempting to credit tokens despite error: {tokens_to_credit} tokens to user {user_profile_id}")
						try:
							_credit_tokens(
								user_profile_id=int(user_profile_id),
								amount=tokens_to_credit,
								reason="subscription_synced",
								source="stripe_sync_subscription",
								feature_key=None,
								metadata={
									"stripe_subscription_id": subscription_id,
									"price_id": price_id,
									"plan_id": plan_id,
									"plan_name": plan_name,
									"error": error_str,
									"note": "Credited despite subscription save error"
								},
							)
						except Exception as token_error:
							print(f"❌ ERROR crediting tokens: {token_error}")
					raise
					
		except stripe.error.StripeError as e:
			return jsonify({"error": f"Stripe error: {str(e)}"}), HTTPStatus.BAD_REQUEST
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR

	@app.get("/stripe/payment-methods/<int:user_profile_id>")
	def get_payment_methods(user_profile_id: int):
		"""
		Get payment methods for a user.
		
		GET /stripe/payment-methods/<user_profile_id>
		"""
		try:
			# Validate user exists
			user_exists, error_response = _validate_user_exists(user_profile_id)
			if not user_exists:
				return jsonify(error_response), HTTPStatus.NOT_FOUND
			
			supabase = get_supabase()
			
			# Get payment methods from database (handle missing table gracefully)
			try:
				pm_resp = supabase.table("payment_methods").select("*").eq("user_profile_id", user_profile_id).order("is_default", desc=True).order("created_at", desc=True).execute()
				payment_methods = pm_resp.data or []
			except Exception as e:
				if "Could not find the table" in str(e) or "PGRST205" in str(e):
					print(f"WARNING: payment_methods table not found. Run migration SQL.")
					payment_methods = []
				else:
					raise
			
			return jsonify({
				"payment_methods": payment_methods
			}), HTTPStatus.OK
				
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR
	
	@app.get("/stripe/payment-history/<int:user_profile_id>")
	def get_payment_history(user_profile_id: int):
		"""
		Get payment history for a user.
		
		GET /stripe/payment-history/<user_profile_id>
		"""
		try:
			# Validate user exists
			user_exists, error_response = _validate_user_exists(user_profile_id)
			if not user_exists:
				return jsonify(error_response), HTTPStatus.NOT_FOUND
			
			supabase = get_supabase()
			
			# Get payment history from database (handle missing table gracefully)
			try:
				history_resp = supabase.table("payment_history").select("*").eq("user_profile_id", user_profile_id).order("created_at", desc=True).limit(50).execute()
				payments = history_resp.data or []
			except Exception as e:
				if "Could not find the table" in str(e) or "PGRST205" in str(e):
					print(f"WARNING: payment_history table not found. Run migration SQL.")
					payments = []
				else:
					raise
			
			return jsonify({
				"payments": payments
			}), HTTPStatus.OK
				
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR
	
	@app.get("/stripe/billing-info/<int:user_profile_id>")
	def get_billing_info(user_profile_id: int):
		"""
		Get complete billing information for a user (subscription, payment methods, recent payments).
		
		GET /stripe/billing-info/<user_profile_id>
		"""
		try:
			# Validate user exists
			user_exists, error_response = _validate_user_exists(user_profile_id)
			if not user_exists:
				return jsonify(error_response), HTTPStatus.NOT_FOUND
			
			supabase = get_supabase()
			
			# Initialize with empty defaults in case tables don't exist
			subscription = None
			payment_methods = []
			recent_payments = []
			
			# Get subscription (handle missing table gracefully)
			try:
				sub_resp = supabase.table("user_subscriptions").select("*").eq("user_profile_id", user_profile_id).eq("status", "active").order("created_at", desc=True).limit(1).execute()
				subscription = sub_resp.data[0] if sub_resp.data else None
			except Exception as e:
				if "Could not find the table" in str(e) or "PGRST205" in str(e):
					print(f"WARNING: user_subscriptions table not found. Run migration SQL.")
				else:
					raise
			
			# Get payment methods (handle missing table gracefully)
			try:
				pm_resp = supabase.table("payment_methods").select("*").eq("user_profile_id", user_profile_id).order("is_default", desc=True).order("created_at", desc=True).execute()
				payment_methods = pm_resp.data or []
			except Exception as e:
				if "Could not find the table" in str(e) or "PGRST205" in str(e):
					print(f"WARNING: payment_methods table not found. Run migration SQL.")
				else:
					raise
			
			# Get recent payment history (last 10) (handle missing table gracefully)
			try:
				history_resp = supabase.table("payment_history").select("*").eq("user_profile_id", user_profile_id).order("created_at", desc=True).limit(10).execute()
				recent_payments = history_resp.data or []
			except Exception as e:
				if "Could not find the table" in str(e) or "PGRST205" in str(e):
					print(f"WARNING: payment_history table not found. Run migration SQL.")
				else:
					raise
			
			return jsonify({
				"subscription": subscription,
				"payment_methods": payment_methods,
				"recent_payments": recent_payments
			}), HTTPStatus.OK
				
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR
	
	@app.post("/stripe/cancel-subscription")
	def cancel_subscription():
		"""
		Cancel a user's subscription.
		
		POST /stripe/cancel-subscription
		Body: {
			"user_profile_id": 1,
			"immediately": false  # If true, cancel immediately; if false, cancel at period end
		}
		"""
		try:
			payload = request.get_json(silent=True) or {}
			user_profile_id = payload.get("user_profile_id")
			immediately = payload.get("immediately", False)
			
			if not user_profile_id:
				return jsonify({"error": "user_profile_id is required"}), HTTPStatus.BAD_REQUEST
			
			# Validate user exists
			user_exists, error_response = _validate_user_exists(user_profile_id)
			if not user_exists:
				return jsonify(error_response), HTTPStatus.NOT_FOUND
			
			# Get Stripe customer ID
			supabase = get_supabase()
			profile_resp = supabase.table("user_profile").select("stripe_customer_id").eq("id", user_profile_id).execute()
			
			if not profile_resp.data or not profile_resp.data[0].get("stripe_customer_id"):
				return jsonify({"error": "No Stripe customer found"}), HTTPStatus.NOT_FOUND
			
			stripe_customer_id = profile_resp.data[0]["stripe_customer_id"]
			
			# Initialize Stripe
			stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
			if not stripe.api_key:
				return jsonify({"error": "Stripe secret key not configured"}), HTTPStatus.INTERNAL_SERVER_ERROR
			
			# Get active subscription
			subscriptions = stripe.Subscription.list(
				customer=stripe_customer_id,
				status="active",
				limit=1
			)
			
			if not subscriptions.data:
				return jsonify({"error": "No active subscription found"}), HTTPStatus.NOT_FOUND
			
			subscription_id = subscriptions.data[0].id
			
			# Cancel subscription
			if immediately:
				subscription = stripe.Subscription.delete(subscription_id)
			else:
				subscription = stripe.Subscription.modify(
					subscription_id,
					cancel_at_period_end=True
				)
			
			return jsonify({
				"subscription_id": subscription.id,
				"status": subscription.status,
				"cancel_at_period_end": subscription.cancel_at_period_end,
				"canceled_at": subscription.canceled_at
			}), HTTPStatus.OK
			
		except stripe.error.StripeError as e:
			return jsonify({"error": f"Stripe error: {str(e)}"}), HTTPStatus.BAD_REQUEST
		except Exception as exc:
			return jsonify({"error": str(exc)}), HTTPStatus.INTERNAL_SERVER_ERROR
