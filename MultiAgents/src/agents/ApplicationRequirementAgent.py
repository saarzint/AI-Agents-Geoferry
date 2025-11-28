from ..imports import *

def application_requirement_agent(self) -> Agent:
    # Be resilient if YAML key is missing by providing a minimal fallback config
    try:
        config = self.agents_config['application_requirement_agent'].copy()  # type: ignore[index]
    except Exception:
        config = {
            'role': 'Application Requirement Agent',
            'goal': 'Compile accurate application requirements and deadlines for specific university programs.',
            'backstory': 'A specialist focused on extracting structured admissions requirements from official sources.'
        }
    # Fix: Strip newlines from role name to ensure proper delegation matching
    if 'role' in config:
        config['role'] = config['role'].strip()
    return Agent(
        config=config,
        tools=[
            ProfileRequestParsingTool(),           # Gets user's university interests and intended major
            WebDataRetrievalTool(),               # Uses Tavily search to find and retrieve content from university websites
            ApplicationDataExtractionTool()        # Extracts structured data using OpenAI
        ],
        verbose=True,
        allow_delegation=False  # Specialist agent - cannot delegate to others
    )