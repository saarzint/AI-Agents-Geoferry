-- Schema: University Search Agent (MVP aligned)

-- user_profile managed here for MVP (read-only to the agent runtime)
create table if not exists public.user_profile (
    id serial primary key,
    full_name text not null,
    citizenship_country text default null,
    destination_country text default null,
    gpa numeric(3,2),                               -- GPA
    test_scores jsonb,                              -- SAT, GRE, TOEFL, IELTS, etc.
    academic_background jsonb,                      -- subjects, grades, coursework
    intended_major text,                            -- Intended major/field of study
    extracurriculars text[],                        -- Clubs, volunteering, leadership, awards
    financial_aid_eligibility boolean default false,-- Interested/eligible for aid/scholarships
    budget integer,                                 -- Tuition/budget
    preferences jsonb,                              -- location, campus size, environment, etc.
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

-- reference table for universities (optional bootstrap/mock data)
create table if not exists public.universities (
	id serial primary key,
	name text not null,
	location text,
	acceptance_rate numeric(5,2),
	tuition integer,
	programs text[],
	ranking int,
	metadata jsonb,									-- additional info (e.g., website, contact, address, ranking source, notes)
	created_at timestamptz default now()
);

-- search_requests: each search invocation (linked to user_profile)
create table if not exists public.search_requests (
	id serial primary key,
	user_profile_id int not null references public.user_profile(id) on delete cascade,
	request_payload jsonb not null,
	created_at timestamptz not null default now()
);
create index if not exists idx_search_requests_user_created on public.search_requests (user_profile_id, created_at desc);

-- university_results: per-university rows for a given search
create table if not exists public.university_results (
	id serial primary key,
	user_profile_id int not null references public.user_profile(id) on delete cascade,
	search_id int not null references public.search_requests(id) on delete cascade,
	university_name text not null,
	location text,
	tuition integer,
	acceptance_rate numeric(5,2),
	programs text[],
	rank_category text check (rank_category in ('Safety','Target','Reach','Near-Fit')),
	why_fit text,
	source jsonb,
	created_at timestamptz not null default now()
);
create index if not exists idx_university_results_user_created on public.university_results (user_profile_id, created_at desc);
create index if not exists idx_university_results_search on public.university_results (search_id);

-- Enable Row Level Security (RLS)
alter table public.user_profile enable row level security;
alter table public.universities enable row level security;
alter table public.search_requests enable row level security;
alter table public.university_results enable row level security;

-- Temporary open policies (tighten later)
create policy "Allow all on user_profile" on public.user_profile for all using (true);
create policy "Allow all on universities" on public.universities for all using (true);
create policy "Allow all on search_requests" on public.search_requests for all using (true);
create policy "Allow all on university_results" on public.university_results for all using (true);

-- Note: search_requests and universities are included to support better logging and mocking, but are not required by the MVP contract.


-- ALTER TABLE to add recommendation metadata for special case handling
-- This will store data_completeness, recommendation_confidence, preference_conflicts, etc.

ALTER TABLE public.university_results 
ADD COLUMN recommendation_metadata JSONB DEFAULT '{}';

-- Add a comment to document the field structure
COMMENT ON COLUMN public.university_results.recommendation_metadata IS 
'JSONB field containing recommendation metadata including:
- data_completeness: "High"|"Medium"|"Low" 
- recommendation_confidence: "High"|"Medium"|"Low"
- preference_conflicts: ["conflict1", "conflict2"] or null
- search_broadened: true|false
- missing_criteria: ["criteria1", "criteria2"] or null
- additional agent metadata';

-- Example of what the recommendation_metadata will contain:
-- {
--   "data_completeness": "Low",
--   "recommendation_confidence": "Medium", 
--   "preference_conflicts": ["budget vs tuition"],
--   "search_broadened": false,
--   "missing_criteria": ["GPA"]
-- }


------------------------------------------------
-- Schema: Scholarship Search Agent 

-- =======================================================
-- Scholarship Results Table
-- =======================================================
create table if not exists public.scholarship_results (
    id serial primary key,
    user_profile_id int not null references public.user_profile(id) on delete cascade,
    -- scholarship_id text not null,                   -- External or internal ID (removed as redundant)
    name text not null,
    category text,                                  -- Merit, Need-based, Athletic, etc.
    award_amount text,
    deadline date,
    renewable_flag boolean default false,
    eligibility_summary jsonb,                  -- JSONB for structured criteria
    source_url text,
    matched_at timestamptz not null default now()
);

-- Index for quick lookup by user and deadline
create index if not exists idx_scholarship_results_user_deadline
    on public.scholarship_results (user_profile_id, deadline);

-- Enable RLS + temporary open policy
alter table public.scholarship_results enable row level security;
create policy "Allow all on scholarship_results" on public.scholarship_results for all using (true);

-- =======================================================
-- Change Tracking for user_profile
-- =======================================================

-- Create a table to store audit logs for user_profile changes
create table if not exists public.user_profile_changes (
    id serial primary key,
    user_profile_id int not null references public.user_profile(id) on delete cascade,
    field_name text not null,                       -- e.g., 'gpa', 'extracurriculars', 'budget'
    old_value text,
    new_value text,
    changed_at timestamptz not null default now()
);

ALTER TABLE public.user_profile_changes ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow all on user_profile_changes" ON public.user_profile_changes FOR ALL USING (true);

-- Trigger function to log changes
create or replace function log_user_profile_changes()
returns trigger as $$
begin
    -- Track GPA changes
    if new.gpa is distinct from old.gpa then
        insert into public.user_profile_changes (user_profile_id, field_name, old_value, new_value)
        values (old.id, 'gpa', old.gpa::text, new.gpa::text);
    end if;

    -- Track Extracurricular changes
    if new.extracurriculars is distinct from old.extracurriculars then
        insert into public.user_profile_changes (user_profile_id, field_name, old_value, new_value)
        values (old.id, 'extracurriculars', array_to_string(old.extracurriculars, ','),
                                      array_to_string(new.extracurriculars, ','));
    end if;

    -- Track Budget (financial bracket) changes
    if new.budget is distinct from old.budget then
        insert into public.user_profile_changes (user_profile_id, field_name, old_value, new_value)
        values (old.id, 'budget', old.budget::text, new.budget::text);
    end if;

    return new;
end;
$$ language plpgsql;

-- Attach trigger to user_profile
drop trigger if exists trg_user_profile_changes on public.user_profile;
create trigger trg_user_profile_changes
after update on public.user_profile
for each row
when (old.* is distinct from new.*) -- only fire if something actually changes
execute function log_user_profile_changes();

-- =======================================================
-- Visa Requirements Table
-- =======================================================
create table if not exists public.visa_requirements (
    id serial primary key,
    user_profile_id int references public.user_profile(id) on delete cascade,
    citizenship_country text not null,
    destination_country text not null,
    visa_type text,
    documents jsonb,
    process_steps jsonb,
    fees jsonb,
    timelines jsonb,
    interview jsonb,
    post_graduation jsonb,
    source_url text,
    fetched_at timestamptz not null default now(),
    last_updated timestamptz not null default now(),
    disclaimer text,
    alert_sent boolean default false,
    notes text,
    change_summary jsonb,
);

-- Useful indices
create index if not exists idx_visa_req_cit_dest on public.visa_requirements (citizenship_country, destination_country);
create index if not exists idx_visa_req_type on public.visa_requirements (visa_type);
create index if not exists idx_visa_req_user on public.visa_requirements (user_profile_id);

-- Enable RLS + temporary open policy
alter table public.visa_requirements enable row level security;
create policy "Allow all on visa_requirements" on public.visa_requirements for all using (true);

-- =======================================================
--  Application Requirements Table
-- =======================================================
create table if not exists public.application_requirements (
    id serial primary key,
    university text not null,                         -- University name (e.g., "University of Southern California")
    program text not null,                            -- Program name (e.g., "Computer Science B.S.")
    application_platform text,                        -- e.g., Common App, Coalition App, University Portal
    deadlines jsonb,                                  -- {"early_decision": "2025-11-01", "regular": "2026-01-15"}
    required_documents text[],                        -- ["Transcripts", "Recommendation Letters", "Test Scores"]
    essay_prompts jsonb,                              -- {"personal_statement": {"word_limit": 650}, "program_specific": "Describe your goals..."}
    portfolio_required boolean default false,         -- Whether a portfolio is required
    interview text,                                   -- e.g., "Required for honors programs only" or "Optional virtual interview available"
    fee_info jsonb,                                   -- {"amount": 75, "currency": "USD", "waiver_available": true}
    test_policy text,                                 -- e.g., "Test-Optional", "Test-Blind", "Required"
    source_url text,                                  -- Source (official program/admissions page)
    fetched_at timestamptz not null default now(),    -- Used for 30-day freshness check
    is_ambiguous boolean default false,               -- True if conflicting or unclear data found
    reviewed_by text                                  -- Name or ID of human/agent reviewer
);

-- =======================================================
--  Enable Row Level Security (RLS)
-- =======================================================
alter table public.application_requirements enable row level security;

-- Temporary open policy (same as other MVP tables)
create policy "Allow all on application_requirements"
    on public.application_requirements
    for all
    using (true);

-- =======================================================
-- Add university_interests column to user_profile table
-- =======================================================
alter table public.user_profile
add column if not exists university_interests jsonb;  -- e.g., ["Stanford University", "MIT", "Harvard University"]


-- =======================================================
-- Add user_profile_id foreign key to application_requirements table
-- =======================================================
ALTER TABLE public.application_requirements
ADD COLUMN user_profile_id INT REFERENCES public.user_profile(id) ON DELETE CASCADE;

-- Add index for optimizing queries by user_profile_id and fetched_at
CREATE INDEX IF NOT EXISTS idx_application_requirements_user_freshness
    ON public.application_requirements (user_profile_id, fetched_at);

-- ===========================
-- ADMISSIONS COUNSELLOR AGENT
-- ===========================

-- ===========================
-- Admissions Summary Table 
-- ===========================
CREATE TABLE IF NOT EXISTS public.admissions_summary (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES public.user_profile(id) ON DELETE CASCADE,  -- Link to user
    current_stage TEXT,                     -- e.g., "Application Submitted", "Documents Pending"
    next_steps JSONB,                       -- e.g., {"action": "Submit transcripts", "deadline": "2025-12-01"}
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(), -- Timestamp for updates
    progress_score NUMERIC(5,2),            -- e.g., 85.5 (% progress towards completion)
    active_agents TEXT[],                   -- e.g., ["Profile Parser", "Scholarship Agent"]
    advice TEXT,                            -- Strategic guidance generated by manager agent
    stress_flags JSONB                      -- e.g., {"deadline_risk": true, "missing_docs": false}
);

-- Useful indices
CREATE INDEX IF NOT EXISTS idx_admissions_summary_user ON public.admissions_summary (user_id);

-- Enable RLS + temporary open policy
ALTER TABLE public.admissions_summary ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow all on admissions_summary"
    ON public.admissions_summary
    FOR ALL
    USING (TRUE);

ALTER TABLE public.admissions_summary
    ADD COLUMN IF NOT EXISTS advice TEXT;


-- ==========================
-- Agent Reports Log Table 
-- ==========================
CREATE TABLE IF NOT EXISTS public.agent_reports_log (
    id SERIAL PRIMARY KEY,
    agent_name TEXT NOT NULL,                -- e.g., "Scholarship Agent", "Visa Agent"
    user_id INT REFERENCES public.user_profile(id) ON DELETE CASCADE,
    payload JSONB,                           -- Full report or data payload from the agent
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(), -- When the report was received
    conflict_flag BOOLEAN DEFAULT FALSE,     -- True if conflicting data among agents
    verified BOOLEAN DEFAULT FALSE           -- True after Admissions Counselor review
);

-- Useful indices
CREATE INDEX IF NOT EXISTS idx_agent_reports_log_user ON public.agent_reports_log (user_id);
CREATE INDEX IF NOT EXISTS idx_agent_reports_log_agent ON public.agent_reports_log (agent_name);

-- Enable RLS + temporary open policy
ALTER TABLE public.agent_reports_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow all on agent_reports_log"
    ON public.agent_reports_log
    FOR ALL
    USING (TRUE);


-- ==========================
-- TOKEN TRACKING SCHEMA
-- ==========================

-- Add token_balance column to user_profile
ALTER TABLE public.user_profile
ADD COLUMN IF NOT EXISTS token_balance INTEGER DEFAULT 10000;  -- Default 10k tokens for new users

-- User Token Usage Log Table
CREATE TABLE IF NOT EXISTS public.user_token_usage (
    id SERIAL PRIMARY KEY,
    user_profile_id INT NOT NULL REFERENCES public.user_profile(id) ON DELETE CASCADE,
    endpoint TEXT NOT NULL,                     -- e.g., "/search_universities", "/search_scholarships"
    api_provider TEXT DEFAULT 'openai',         -- e.g., "openai", "anthropic"
    tokens_used INTEGER NOT NULL,               -- Tokens consumed (negative for additions)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Useful indices
CREATE INDEX IF NOT EXISTS idx_user_token_usage_user ON public.user_token_usage (user_profile_id);
CREATE INDEX IF NOT EXISTS idx_user_token_usage_created ON public.user_token_usage (created_at DESC);

-- Enable RLS + temporary open policy
ALTER TABLE public.user_token_usage ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow all on user_token_usage"
    ON public.user_token_usage
    FOR ALL
    USING (TRUE);
