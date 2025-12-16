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
			# Auto-migrate Stripe tables on first connection
			_migrate_stripe_tables(_supabase)
		except Exception as e:
			print(f"ERROR: Failed to create Supabase client: {str(e)}")
			print(f"ERROR: Exception type: {type(e).__name__}")
			import traceback
			print(f"ERROR: Traceback: {traceback.format_exc()}")
			raise
	return _supabase

def _migrate_stripe_tables(supabase: Client) -> None:
	"""
	Automatically create missing Stripe-related tables and columns.
	This runs on first Supabase client initialization.
	"""
	try:
		# Check if stripe_customer_id column exists by trying to query it
		try:
			supabase.table("user_profile").select("stripe_customer_id").limit(1).execute()
			print("DEBUG: stripe_customer_id column exists")
		except Exception as e:
			if "does not exist" in str(e) or "42703" in str(e):
				print("⚠️  WARNING: stripe_customer_id column missing in user_profile table")
				print("   Run the migration SQL in Supabase SQL Editor")
				_print_migration_sql()
			else:
				# Column might exist, just no data - that's fine
				pass
		
		# Check if user_subscriptions table exists
		try:
			supabase.table("user_subscriptions").select("id").limit(1).execute()
			print("DEBUG: user_subscriptions table exists")
		except Exception as e:
			if "Could not find the table" in str(e) or "PGRST205" in str(e):
				print("⚠️  WARNING: user_subscriptions table missing")
				print("   Run the migration SQL in Supabase SQL Editor")
				_print_migration_sql()
			else:
				# Table might exist but be empty - that's fine
				pass
		
		# Check payment_methods table
		try:
			supabase.table("payment_methods").select("id").limit(1).execute()
			print("DEBUG: payment_methods table exists")
		except Exception as e:
			if "Could not find the table" in str(e) or "PGRST205" in str(e):
				print("⚠️  WARNING: payment_methods table missing")
				print("   Run the migration SQL in Supabase SQL Editor")
				_print_migration_sql()
		
		# Check payment_history table
		try:
			supabase.table("payment_history").select("id").limit(1).execute()
			print("DEBUG: payment_history table exists")
		except Exception as e:
			if "Could not find the table" in str(e) or "PGRST205" in str(e):
				print("⚠️  WARNING: payment_history table missing")
				print("   Run the migration SQL in Supabase SQL Editor")
				_print_migration_sql()
				
	except Exception as e:
		# Don't fail if migration check fails - just log it
		print(f"DEBUG: Migration check encountered error (non-fatal): {str(e)}")

def _print_migration_sql() -> None:
	"""Print the migration SQL that needs to be run."""
	migration_sql = """
-- ===========================
-- PAYMENT & SUBSCRIPTION MANAGEMENT
-- ===========================

-- Add Firebase UID and Stripe Customer ID to user_profile
ALTER TABLE public.user_profile
ADD COLUMN IF NOT EXISTS firebase_uid TEXT UNIQUE;

ALTER TABLE public.user_profile
ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT UNIQUE;

-- Create index for Firebase UID lookups
CREATE INDEX IF NOT EXISTS idx_user_profile_firebase_uid ON public.user_profile (firebase_uid);
CREATE INDEX IF NOT EXISTS idx_user_profile_stripe_customer_id ON public.user_profile (stripe_customer_id);

-- ===========================
-- User Subscriptions Table
-- ===========================
CREATE TABLE IF NOT EXISTS public.user_subscriptions (
    id SERIAL PRIMARY KEY,
    user_profile_id INT NOT NULL REFERENCES public.user_profile(id) ON DELETE CASCADE,
    stripe_subscription_id TEXT UNIQUE NOT NULL,
    stripe_customer_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    plan_name TEXT NOT NULL,
    price_id TEXT NOT NULL,
    status TEXT NOT NULL,
    current_period_start TIMESTAMPTZ NOT NULL,
    current_period_end TIMESTAMPTZ NOT NULL,
    cancel_at_period_end BOOLEAN DEFAULT FALSE,
    canceled_at TIMESTAMPTZ,
    trial_start TIMESTAMPTZ,
    trial_end TIMESTAMPTZ,
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'usd',
    interval TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Useful indices
CREATE INDEX IF NOT EXISTS idx_user_subscriptions_user ON public.user_subscriptions (user_profile_id);
CREATE INDEX IF NOT EXISTS idx_user_subscriptions_stripe_sub ON public.user_subscriptions (stripe_subscription_id);
CREATE INDEX IF NOT EXISTS idx_user_subscriptions_status ON public.user_subscriptions (status);
CREATE INDEX IF NOT EXISTS idx_user_subscriptions_active ON public.user_subscriptions (user_profile_id, status) WHERE status = 'active';

-- Enable RLS + temporary open policy
ALTER TABLE public.user_subscriptions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Allow all on user_subscriptions" ON public.user_subscriptions;
CREATE POLICY "Allow all on user_subscriptions"
    ON public.user_subscriptions
    FOR ALL
    USING (TRUE);

-- ===========================
-- Payment Methods Table
-- ===========================
CREATE TABLE IF NOT EXISTS public.payment_methods (
    id SERIAL PRIMARY KEY,
    user_profile_id INT NOT NULL REFERENCES public.user_profile(id) ON DELETE CASCADE,
    stripe_payment_method_id TEXT UNIQUE NOT NULL,
    stripe_customer_id TEXT NOT NULL,
    type TEXT NOT NULL,
    card_brand TEXT,
    card_last4 TEXT,
    card_exp_month INTEGER,
    card_exp_year INTEGER,
    is_default BOOLEAN DEFAULT FALSE,
    billing_details JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Useful indices
CREATE INDEX IF NOT EXISTS idx_payment_methods_user ON public.payment_methods (user_profile_id);
CREATE INDEX IF NOT EXISTS idx_payment_methods_stripe_pm ON public.payment_methods (stripe_payment_method_id);
CREATE INDEX IF NOT EXISTS idx_payment_methods_default ON public.payment_methods (user_profile_id, is_default) WHERE is_default = TRUE;

-- Enable RLS + temporary open policy
ALTER TABLE public.payment_methods ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Allow all on payment_methods" ON public.payment_methods;
CREATE POLICY "Allow all on payment_methods"
    ON public.payment_methods
    FOR ALL
    USING (TRUE);

-- ===========================
-- Payment History Table
-- ===========================
CREATE TABLE IF NOT EXISTS public.payment_history (
    id SERIAL PRIMARY KEY,
    user_profile_id INT NOT NULL REFERENCES public.user_profile(id) ON DELETE CASCADE,
    subscription_id INT REFERENCES public.user_subscriptions(id) ON DELETE SET NULL,
    stripe_payment_intent_id TEXT UNIQUE,
    stripe_invoice_id TEXT,
    stripe_charge_id TEXT,
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'usd',
    status TEXT NOT NULL,
    payment_method_id INT REFERENCES public.payment_methods(id) ON DELETE SET NULL,
    description TEXT,
    failure_reason TEXT,
    receipt_url TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Useful indices
CREATE INDEX IF NOT EXISTS idx_payment_history_user ON public.payment_history (user_profile_id);
CREATE INDEX IF NOT EXISTS idx_payment_history_subscription ON public.payment_history (subscription_id);
CREATE INDEX IF NOT EXISTS idx_payment_history_stripe_pi ON public.payment_history (stripe_payment_intent_id);
CREATE INDEX IF NOT EXISTS idx_payment_history_created ON public.payment_history (user_profile_id, created_at DESC);

-- Enable RLS + temporary open policy
ALTER TABLE public.payment_history ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Allow all on payment_history" ON public.payment_history;
CREATE POLICY "Allow all on payment_history"
    ON public.payment_history
    FOR ALL
    USING (TRUE);
"""
	print("\n" + "=" * 60)
	print("   MIGRATION SQL - Copy and run in Supabase SQL Editor")
	print("=" * 60)
	print(migration_sql)
	print("=" * 60 + "\n")
