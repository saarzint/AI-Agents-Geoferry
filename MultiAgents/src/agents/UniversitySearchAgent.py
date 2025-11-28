from ..imports import *

def university_search_agent(self) -> Agent:
    config = self.agents_config['university_search_agent'].copy() # type: ignore[index]
    # Fix: Strip newlines from role name to ensure proper delegation matching
    if 'role' in config:
        config['role'] = config['role'].strip()
    return Agent(
        config=config,
        tools=[
            ProfileQueryTool(),           # Gets user profile from Supabase
            UniversityKnowledgeTool(),    # Static university knowledge base
            OpenAIWebSearchTool()        # OpenAI's built-in web search using Responses API
        ],
        verbose=True,
        allow_delegation=False  # Specialist agent - cannot delegate to others
    )
    