import os
from typing import Optional
from dotenv import load_dotenv
from supabase import create_client, Client


load_dotenv()

_supabase: Optional[Client] = None

def get_supabase() -> Client:
	global _supabase
	if _supabase is None:
		url = os.getenv("SUPABASE_URL")
		# Prefer a single SUPABASE_KEY if provided; otherwise fall back to service/anon
		key = (
			os.getenv("SUPABASE_KEY")
			or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
			or os.getenv("SUPABASE_ANON_KEY")
		)
		if not url or not key:
			# Debug: log what we found
			print(f"DEBUG: SUPABASE_URL={url}")
			print(f"DEBUG: SUPABASE_KEY exists={bool(os.getenv('SUPABASE_KEY'))}")
			print(f"DEBUG: SUPABASE_SERVICE_ROLE_KEY exists={bool(os.getenv('SUPABASE_SERVICE_ROLE_KEY'))}")
			print(f"DEBUG: SUPABASE_ANON_KEY exists={bool(os.getenv('SUPABASE_ANON_KEY'))}")
			raise RuntimeError(
				"Supabase credentials are not configured. Set SUPABASE_URL and SUPABASE_KEY."
			)
		# Strip whitespace from key (common issue with copy-paste)
		url = url.strip() if url else url
		key = key.strip() if key else key
		# Debug: log key format (first/last 10 chars only for security)
		print(f"DEBUG: Supabase URL={url}")
		print(f"DEBUG: Supabase Key length={len(key)}, format: {key[:10]}...{key[-10:] if len(key) > 20 else 'SHORT'}")
		try:
			_supabase = create_client(url, key)
			print("DEBUG: Supabase client created successfully")
		except Exception as e:
			print(f"ERROR: Failed to create Supabase client: {str(e)}")
			print(f"ERROR: Exception type: {type(e).__name__}")
			import traceback
			print(f"ERROR: Traceback: {traceback.format_exc()}")
			raise
	return _supabase
