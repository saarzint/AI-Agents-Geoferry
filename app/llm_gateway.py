import os
import json
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import requests
from flask import Flask, request, jsonify

from .supabase_client import get_supabase


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
TAVILY_API_BASE = os.getenv("TAVILY_API_BASE", "https://api.tavily.com")
# Approximate cost per Tavily request expressed in "token units" for accounting
TAVILY_COST_TOKENS = int(os.getenv("TAVILY_COST_TOKENS", "100"))

if not OPENAI_API_KEY:
	print("⚠️  OPENAI_API_KEY is not set. Gateway will return 500 for OpenAI calls.")
if not TAVILY_API_KEY:
	print("⚠️  TAVILY_API_KEY is not set. Tavily proxy calls will return 500.")


def _get_user_id_and_payload() -> Tuple[Optional[int], Dict[str, Any]]:
	"""Extract user_id from header or body, and return JSON payload."""
	payload = request.get_json(silent=True) or {}
	user_id_raw = request.headers.get("X-User-Id") or payload.get("user_id")
	try:
		user_id = int(user_id_raw) if user_id_raw is not None else None
	except (ValueError, TypeError):
		user_id = None
	return user_id, payload


def _update_user_tokens(user_id: int, tokens_used: int, endpoint: str, api_provider: str = "openai") -> Dict[str, Any]:
	"""Atomically update user token balance and log usage."""
	supabase = get_supabase()
	try:
		profile = supabase.table("user_profile").select("token_balance").eq("id", user_id).execute()
		current_balance = profile.data[0].get("token_balance", 0) if profile.data else 0
		new_balance = max(0, current_balance - tokens_used)

		supabase.table("user_profile").update({
			"token_balance": new_balance
		}).eq("id", user_id).execute()

		supabase.table("user_token_usage").insert({
			"user_id": user_id,
			"user_profile_id": user_id,  # keep compatibility if column name differs
			"endpoint": endpoint,
			"api_provider": api_provider,
			"tokens_used": tokens_used,
			"created_at": datetime.now().isoformat()
		}).execute()

		return {
			"tokens_used": tokens_used,
			"previous_balance": current_balance,
			"remaining_tokens": new_balance,
			"success": True
		}
	except Exception as e:
		print(f"Warning: failed to update tokens for user {user_id}: {e}")
		return {
			"tokens_used": tokens_used,
			"remaining_tokens": None,
			"success": False,
			"error": str(e)
		}


def _forward_to_openai(path: str, payload: Dict[str, Any], user_id: Optional[int]) -> Tuple[Any, int]:
	if not OPENAI_API_KEY:
		return {"error": "OPENAI_API_KEY not configured"}, 500

	url = f"{OPENAI_API_BASE}{path}"
	headers = {
		"Authorization": f"Bearer {OPENAI_API_KEY}",
		"Content-Type": "application/json"
	}

	resp = requests.post(url, headers=headers, json=payload, timeout=120)
	status = resp.status_code
	try:
		data = resp.json()
		usage = data.get("usage", {}) if isinstance(data, dict) else {}
		tokens_used = usage.get("total_tokens", 0)
		if user_id is not None and tokens_used is not None:
			_update_user_tokens(user_id, tokens_used, path, api_provider="openai")
		return data, status
	except Exception:
		# If response is not JSON, return raw text
		return resp.text, status


def _forward_to_tavily(path: str, payload: Dict[str, Any], user_id: Optional[int]) -> Tuple[Any, int]:
	if not TAVILY_API_KEY:
		return {"error": "TAVILY_API_KEY not configured"}, 500

	# Tavily base API path; default search endpoint is /search
	url = f"{TAVILY_API_BASE}{path}"
	headers = {
		"Content-Type": "application/json",
		"X-API-Key": TAVILY_API_KEY
	}

	resp = requests.post(url, headers=headers, json=payload, timeout=60)
	status = resp.status_code
	try:
		data = resp.json()
	except Exception:
		data = resp.text

	# Account one Tavily call as configured cost
	if user_id is not None:
		_update_user_tokens(user_id, TAVILY_COST_TOKENS, path, api_provider="tavily")

	if isinstance(data, (dict, list)):
		return data, status
	return data, status


def create_app() -> Flask:
	app = Flask(__name__)

	@app.post("/v1/chat/completions")
	def proxy_chat_completions():
		user_id, payload = _get_user_id_and_payload()
		if user_id is None:
			return jsonify({"error": "user_id required (header X-User-Id or in JSON body)"}), 400
		data, status = _forward_to_openai("/v1/chat/completions", payload, user_id)
		# Return exactly what OpenAI returned
		if isinstance(data, (dict, list)):
			return jsonify(data), status
		return data, status

	@app.post("/v1/responses")
	def proxy_responses():
		user_id, payload = _get_user_id_and_payload()
		if user_id is None:
			return jsonify({"error": "user_id required (header X-User-Id or in JSON body)"}), 400
		data, status = _forward_to_openai("/v1/responses", payload, user_id)
		if isinstance(data, (dict, list)):
			return jsonify(data), status
		return data, status

	@app.post("/tavily/search")
	def proxy_tavily_search():
		user_id, payload = _get_user_id_and_payload()
		if user_id is None:
			return jsonify({"error": "user_id required (header X-User-Id or in JSON body)"}), 400
		data, status = _forward_to_tavily("/search", payload, user_id)
		if isinstance(data, (dict, list)):
			return jsonify(data), status
		return data, status

	@app.get("/health")
	def health():
		return jsonify({"status": "ok"}), 200

	return app


app = create_app()


if __name__ == "__main__":
	port = int(os.getenv("GATEWAY_PORT", "8000"))
	app.run(host="0.0.0.0", port=port)

