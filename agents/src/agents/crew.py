from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai_tools import TavilySearchTool
from typing import List
from .tools import ProfileQueryTool, UniversityKnowledgeTool, ProfileChangesTool, ScholarshipMatcherTool, ScholarshipKnowledgeTool, ProfileRequestParsingTool, WebDataRetrievalTool, ApplicationDataExtractionTool, ProfileAccessTool, VisaScraperTool, AdmissionsDataTool

# If you want to run a snippet of code before or after the crew starts,
# you can use the @before_kickoff and @after_kickoff decorators
# https://docs.crewai.com/concepts/crews#example-crew-class-with-decorators

@CrewBase
class SearchCrew():
    """AI Agents crew"""

    agents: List[BaseAgent]
    tasks: List[Task]
    
    # Config paths for both agents and tasks
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    # Learn more about YAML configuration files here:
    # Agents: https://docs.crewai.com/concepts/agents#yaml-configuration-recommended
    # Tasks: https://docs.crewai.com/concepts/tasks#yaml-configuration-recommended
    
    # If you would like to add tools to your agents, you can learn more about it here:
    # https://docs.crewai.com/concepts/agents#agent-tools
    @agent
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
                TavilySearchTool(             # AI-powered web search for comprehensive university discovery
                    search_depth="advanced",
                    max_results=8,
                    include_answer=True,
                    topic="general",
                    include_domains=[
                        "usnews.com", "niche.com", "collegeboard.org", 
                        "petersons.com", "princetonreview.com", "cappex.com"
                    ]
                )
            ],
            verbose=True,
            allow_delegation=False  # Specialist agent - cannot delegate to others
        )

    @agent
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
                    ]
                )
            ],
            verbose=True,
            allow_delegation=False  # Specialist agent - cannot delegate to others
        )

    @agent
    def visa_search_agent(self) -> Agent:
        config = self.agents_config['visa_search_agent'].copy() # type: ignore[index]
        # Fix: Strip newlines from role name to ensure proper delegation matching
        if 'role' in config:
            config['role'] = config['role'].strip()
        return Agent(
            config=config,
            tools=[
                ProfileAccessTool(),           # Gets user profile from Supabase
                TavilySearchTool(             # AI-powered web search for visa discovery
                    search_depth="advanced",
                    max_results=8,
                    include_answer=True,
                    topic="general",
                    # include_domains should be general for searching for visa information. Any embassy or government website should be included.
                    include_domains=[
                        "usembassy.gov", "state.gov", "gov.uk", "immigration.gov.au", "canada.ca/ircc",
                        "uk.embassy.gov.au", "uk.gov.au", "uk.gov.uk", "uk.gov.uk/immigration", "uk.gov.uk/visa", "uk.gov.uk/visa/student", "uk.gov.uk/visa/student/requirements", "uk.gov.uk/visa/student/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/requirements/general/visa-types/f-1/requirements/general/requirements/general/requirements/general", "uk.gov.uk/visa/student/",
                    ]
                ),
                VisaScraperTool(),
            ],
            verbose=True,
            allow_delegation=False  # Specialist agent - cannot delegate to others
        )
        
    @agent
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
    
    @agent
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

    @agent
    def data_aggregator_agent(self) -> Agent:
        """
        Data Aggregator Agent - Specialist
        Provides aggregated read access to admissions data across agents/tables.
        """
        return Agent(
            role="Data Aggregator Agent",
            goal="Aggregate admissions data (universities, scholarships, requirements, visas) for synthesis.",
            backstory="A focused data specialist that reads and summarizes cross-agent data for the manager.",
            tools=[
                AdmissionsDataTool(),
                ProfileQueryTool(),
                ProfileAccessTool(),
            ],
            verbose=True,
            allow_delegation=False
        )

    # To learn more about structured task outputs,
    # task dependencies, and task callbacks, check out the documentation:
    # https://docs.crewai.com/concepts/tasks#overview-of-a-task
    @task
    def university_search_task(self) -> Task:
        return Task(
            config=self.tasks_config['university_search_task'], # type: ignore[index]
            agent=self.university_search_agent()
        )

    @task
    def scholarship_search_task(self) -> Task:
        return Task(
            config=self.tasks_config['scholarship_search_task'], # type: ignore[index]
            agent=self.scholarship_search_agent()
        )

    @task
    def visa_search_task(self) -> Task:
        return Task(
            config=self.tasks_config['visa_search_task'], # type: ignore[index]
            agent=self.visa_search_agent()
        )

    @task
    def application_requirement_task(self) -> Task:
        return Task(
            config=self.tasks_config['application_requirement_task'], # type: ignore[index]
            agent=self.application_requirement_agent()
        )
    
    @task
    def admissions_counselor_task(self) -> Task:
        return Task(
            config=self.tasks_config['admissions_counselor_task'], # type: ignore[index]
            agent=self.admissions_counselor_agent()
        )

    @task
    def data_aggregation_task(self) -> Task:
        """Runs AdmissionsDataTool via the data_aggregator_agent and returns JSON counts + missing agents."""
        return Task(
            description=(
                "Aggregate stored admissions data for user_id={user_id} from Supabase using AdmissionsDataTool. "
                "Return ONLY JSON with keys: universities_found, scholarships_found, application_requirements, "
                "visa_info_count, missing_agents (array of strings), approaching_deadlines (number), "
                "approaching_deadlines_details (array of objects with type, name/university, deadline, days_left), "
                "incomplete_profile (boolean), missing_profile_fields (array of strings). "
                "Do NOT delegate or call coworker tools in this task; only read via Admissions Data Aggregation Tool."
            ),
            expected_output=(
                '{"universities_found":number,"scholarships_found":number,"application_requirements":number,'
                '"visa_info_count":number,"missing_agents":["..."],"approaching_deadlines":number,'
                '"approaching_deadlines_details":[{"type":"scholarship|application","name":"...","days_left":5,...}],'
                '"incomplete_profile":boolean,"missing_profile_fields":["..."]}'
            ),
            agent=self.data_aggregator_agent()
        )

    @crew
    def crew(self) -> Crew:
        """Creates the Search crew with ai agents"""
        return Crew(
            agents=self.agents, # Automatically created by the @agent decorator
            tasks=self.tasks, # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=True,
        )

class ManagerCrew():
    """AI Agents manager crew with hierarchical process"""

    def crew(self) -> Crew:
        """Creates the Manager crew with hierarchical process"""
        
        # Define data aggregator agent
        data_aggregator = Agent(
            role="Data Aggregator Agent",
            goal="Aggregate admissions data (universities, scholarships, requirements, visas) for synthesis.",
            backstory="A focused data specialist that reads and summarizes cross-agent data for the manager.",
            tools=[AdmissionsDataTool()],
            verbose=True,
            allow_delegation=False
        )

        # Define university search agent
        university_agent = Agent(
            role="University Search Agent",
            goal="Identify higher education institutions that align with a student's profile and preferences.",
            backstory="Specialized university counseling agent with expertise in matching students to appropriate universities.",
            tools=[
                ProfileQueryTool(),
                UniversityKnowledgeTool(),
                TavilySearchTool(
                    search_depth="advanced",
                    max_results=8,
                    include_answer=True,
                    topic="general",
                    include_domains=["usnews.com", "niche.com", "collegeboard.org", "petersons.com", "princetonreview.com", "cappex.com"]
                )
            ],
            verbose=True,
            allow_delegation=False
        )

        # Define scholarship search agent
        scholarship_agent = Agent(
            role="Scholarship Search Agent",
            goal="Find relevant scholarships and financial aid opportunities that match a student's profile.",
            backstory="Specialized scholarship discovery agent with expertise in matching students to financial aid opportunities.",
            tools=[
                ProfileQueryTool(),
                ProfileChangesTool(),
                ScholarshipMatcherTool(),
                ScholarshipKnowledgeTool(),
                TavilySearchTool(
                    search_depth="advanced",
                    max_results=8,
                    include_answer=True,
                    topic="general",
                    include_domains=["fastweb.com", "scholarships.com", "collegeboard.org", "cappex.com", "niche.com", "petersons.com"]
                )
            ],
            verbose=True,
            allow_delegation=False
        )

        # Define visa search agent
        visa_agent = Agent(
            role="Visa Information Agent",
            goal="Retrieve, validate, and structure official student visa requirements.",
            backstory="Specializes in gathering student visa information from official and authoritative sources.",
            tools=[
                ProfileAccessTool(),
                TavilySearchTool(
                    search_depth="advanced",
                    max_results=8,
                    include_answer=True,
                    topic="general",
                    include_domains=["usembassy.gov", "state.gov", "gov.uk", "immigration.gov.au", "canada.ca/ircc"]
                ),
                VisaScraperTool(),
            ],
            verbose=True,
            allow_delegation=False
        )

        # Define application requirement agent
        application_agent = Agent(
            role="Application Requirement Agent",
            goal="Compile comprehensive application requirements and deadlines for university programs.",
            backstory="Meticulous data-gathering specialist with expertise in university admissions requirements.",
            tools=[
                ProfileRequestParsingTool(),
                WebDataRetrievalTool(),
                ApplicationDataExtractionTool()
            ],
            verbose=True,
            allow_delegation=False
        )

        # Define the manager agent
        manager = Agent(
            role="Admissions Counselor Agent",
            goal="Guide students through their complete admissions journey with strategic coordination.",
            backstory="Master strategic advisor synthesizing all agent outputs to provide holistic guidance.",
            verbose=True,
            allow_delegation=True,

        )

        # Define the manager task
        manager_task = Task(
            description=(
                "Guide the student with user_id={user_id} through their admissions journey. "
                "First delegate to the Data Aggregator Agent to get current data (counts, missing_agents, deadlines, profile flags) for user_id={user_id}. "
                "Then delegate ONLY to agents listed in missing_agents - do NOT delegate to agents already present. "
                "Finally synthesize a clear summary with current_stage, progress_score (numeric 0-100), active_agents, stress_flags, and next_steps."
            ),
            expected_output=(
                "Return a JSON object with: current_stage (string), progress_score (numeric 0-100, not a percentage string), "
                "active_agents (array of strings), overview (string), missing_profile_fields (array of strings), "
                "approaching_deadlines_details (array of objects), next_steps (array of objects)"
            )
        )

        # Build and return the crew
        return Crew(
            agents=[data_aggregator, university_agent, scholarship_agent, visa_agent, application_agent],
            tasks=[manager_task],
            manager_agent=manager,
            process=Process.hierarchical,
            verbose=True,
        )

if __name__ == "__main__":
    crew = SearchCrew()
    print(crew)