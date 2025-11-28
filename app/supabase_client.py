import os
from typing import Optional
from dotenv import load_dotenv
from supabase import create_client, Client  # type: ignore


load_dotenv()

_supabase: Optional[Client] = None

def get_supabase() -> Client:
	global _supabase
	try:
		if _supabase is None:
			url = os.getenv("SUPABASE_URL")
			# Prefer a single SUPABASE_KEY if provided; otherwise fall back to service/anon
			key = (
				os.getenv("SUPABASE_KEY")
				or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
				or os.getenv("SUPABASE_ANON_KEY")
			)
			if not url or not key:
				raise RuntimeError(
					"Supabase credentials are not configured. Set SUPABASE_URL and SUPABASE_KEY."
				)
			_supabase = create_client(url, key)
		return _supabase
	except:
		return None
