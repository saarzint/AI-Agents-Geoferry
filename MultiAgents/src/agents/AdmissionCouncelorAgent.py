from ..imports import *

def admissions_counselor_agent(self) -> Agent:
    """
    Admissions Counselor - manager agent (allow_delegation=True).
    Simple purpose:
    - Read the data aggregation step first (DB-first)
    - Delegate only to agents listed as missing
    - Then produce a short, useful summary for the student
    """
    # Be resilient if YAML key is missing by providing a minimal fallback config
    try:
        config = self.agents_config['admissions_counselor_agent'].copy()  # type: ignore[index]
    except Exception:
        config = {
            'role': 'Admissions Counselor Agent (Master Orchestrator)',
            'goal': 'Orchestrate and guide students through their complete admissions journey.',
            'backstory': 'Master strategic advisor synthesizing all agent outputs to provide holistic guidance.'
        }
    # Fix: Strip newlines from role name to ensure proper delegation matching
    if 'role' in config:
        config['role'] = config['role'].strip()
    # Create worker agents first to get their role names for allowed_agents
    # Note: This will be set when crew is instantiated, but we need to ensure
    # the manager can see all worker agents
    return Agent(
        config=config,
        tools=[],  # Manager doesn't use tools in hierarchical mode
        verbose=True,
        allow_delegation=True,  # CRITICAL: Manager MUST delegate in hierarchical mode
        max_iter=5,  # Allow multiple delegation attempts if needed
        memory=False  # Disable memory to avoid state issues
        # Note: allowed_agents parameter should be set in routes.py when creating Crew
    )