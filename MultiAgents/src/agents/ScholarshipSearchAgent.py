from ..imports import *


def scholarship_search_agent(self) -> Agent:
    config = self.agents_config['scholarship_search_agent'].copy() # type: ignore[index]
    # Fix: Strip newlines from role name to ensure proper delegation matching
    if 'role' in config:
        config['role'] = config['role'].strip()
    return Agent(
        config=config,
        tools=[
            ProfileQueryTool(),           # Gets user profile from Supabase
            ProfileChangesTool(),         # Gets profile changes for delta searches
            ScholarshipMatcherTool(),     # Advanced matching and filtering algorithms
            ScholarshipKnowledgeTool(),   # Fallback scholarship knowledge base
            TavilySearchTool(             # AI-powered web search for scholarship discovery
                search_depth="advanced",
                max_results=8,
                include_answer=True,
                topic="general",
                include_domains=[
                    "fastweb.com", "scholarships.com", "collegeboard.org", 
                    "cappex.com", "niche.com", "petersons.com"
                ],
                max_tokens=10000,
            )
        ],
        verbose=True,
        allow_delegation=False  # Specialist agent - cannot delegate to others
    )