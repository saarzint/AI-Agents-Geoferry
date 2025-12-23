-- Migration: Add Token Tracking Support
-- Run this in your Supabase SQL Editor

-- Add token_balance column to user_profile
ALTER TABLE public.user_profile 
ADD COLUMN IF NOT EXISTS token_balance INT DEFAULT 0;

-- Create token usage log table
CREATE TABLE IF NOT EXISTS public.user_token_usage (
    id SERIAL PRIMARY KEY,
    user_profile_id INT NOT NULL REFERENCES public.user_profile(id) ON DELETE CASCADE,
    endpoint TEXT NOT NULL,
    api_provider TEXT NOT NULL DEFAULT 'openai',
    tokens_used INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create index for performance
CREATE INDEX IF NOT EXISTS idx_token_usage_user ON public.user_token_usage (user_profile_id, created_at DESC);

-- Enable RLS on user_token_usage table
ALTER TABLE public.user_token_usage ENABLE ROW LEVEL SECURITY;

-- Create policy for user_token_usage (adjust as needed for your security requirements)
CREATE POLICY "Allow all on user_token_usage" 
    ON public.user_token_usage 
    FOR ALL 
    USING (true);

