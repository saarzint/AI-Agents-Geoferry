from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai_tools import TavilySearchTool
from typing import List
from .tools import ProfileQueryTool, UniversityKnowledgeTool, ProfileChangesTool, ScholarshipMatcherTool, ScholarshipKnowledgeTool, ProfileRequestParsingTool, WebDataRetrievalTool, ApplicationDataExtractionTool, ProfileAccessTool, VisaScraperTool, AdmissionsDataTool, StageComputationTool

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
                    ],
                    max_tokens=10000,
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
                    ],
                    max_tokens=10000,
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
                    ],
                    max_tokens=10000,
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

    @agent
    def next_steps_generator_agent(self) -> Agent:
        """
        Next Steps Generator Agent - Specialist
        Generates actionable, prioritized next steps for students based on their current admissions journey stage and progress.
        """
        return Agent(
            role="Next Steps Generator Agent",
            goal="Generate actionable, prioritized next steps for students based on their current admissions journey stage and progress.",
            backstory=(
                "You are a strategic planning specialist with expertise in admissions counseling. "
                "You analyze the student's current stage, deadlines, profile completeness, and agent outputs "
                "to generate specific, actionable next steps. Each step you create includes priority level, "
                "calculated due dates, and references to the appropriate agent that should handle the task. "
                "You use rule-based logic combined with LLM reasoning to ensure steps are realistic, timely, "
                "and aligned with the student's goals and deadlines. "
                "CRITICAL: You MUST return ONLY a valid JSON array - no markdown, no code blocks, no explanations outside the JSON. "
                "Start your response immediately with [ and end with ]. "
                "Each object in the array must have: action, priority, due_date, related_agent, and reasoning fields."
            ),
            tools=[AdmissionsDataTool(), ProfileQueryTool(), StageComputationTool()],
            verbose=True,
            allow_delegation=False  # Specialist agent - generates steps, doesn't delegate
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

    @task
    def next_steps_generator_task(self) -> Task:
        """Generates detailed, actionable next steps for a user based on their current admissions journey."""
        return Task(
            description=(
                "Generate detailed, actionable next steps for user_id={user_id} based on their current admissions journey. "
                "STEP 1 - GET CURRENT STAGE: Use the Stage Computation Tool with user_id={user_id} to determine the current stage. "
                "STEP 2 - GET DATA AGGREGATION: Use the Admissions Data Aggregation Tool with user_id={user_id} to get: "
                "approaching_deadlines_details (deadlines within 45 days), missing_profile_fields, and current progress. "
                "STEP 3 - GENERATE ACTIONABLE NEXT STEPS: Create 3-5 specific, actionable next steps. "
                "Each next step MUST include: "
                "- action: A clear, specific action description "
                "- priority: 'High', 'Medium', or 'Low' based on urgency (High for deadlines within 14 days, Medium for 30 days, Low for beyond) "
                "- due_date: Calculated date (YYYY-MM-DD format) - set 7-10 days before actual deadlines, 3-7 days for urgent profile fields "
                "- related_agent: Reference to the agent (e.g., 'Application Requirement Agent', 'Scholarship Search Agent', 'University Search Agent', 'Visa Information Agent', or 'Profile Update') "
                "- reasoning: Brief explanation of why this step is needed and when it should be completed "
                "Order steps by priority (High first) and then by due_date (earliest first). "
                "Return ONLY a valid JSON array starting with [ and ending with ]."
            ),
            expected_output=(
                "Return a JSON array of next steps objects. Each object must have: "
                '{"action": "Clear, specific action description", "priority": "High|Medium|Low", '
                '"due_date": "YYYY-MM-DD", "related_agent": "Agent name or Profile Update", '
                '"reasoning": "Brief explanation of why and when"}. '
                "Minimum 3 next steps, maximum 5 next steps. "
                "Start with [ and end with ]. No markdown, no code blocks."
            ),
            agent=self.next_steps_generator_agent()
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

    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'
    
    def __init__(self):
        """Initialize ManagerCrew and load agent configs from YAML"""
        # Reuse SearchCrew's loaded config (it uses @CrewBase which auto-loads YAML)
        search_crew = SearchCrew()
        self.agents_config = search_crew.agents_config
    
    def crew(self) -> Crew:
        """Creates the Manager crew with hierarchical process"""
        
        # Define data aggregator agent
        data_aggregator = Agent(
            role="Data Aggregator Agent",
            goal="Aggregate admissions data (universities, scholarships, requirements, visas) for synthesis by using the Admissions Data Aggregation Tool.",
            backstory="A focused data specialist that reads and summarizes cross-agent data for the manager. When asked to aggregate data, you MUST use the Admissions Data Aggregation Tool with the provided user_id to get comprehensive admissions data including counts, missing agents, deadlines, and profile information. Always return the data as JSON format.",
            tools=[AdmissionsDataTool()],
            verbose=True,
            allow_delegation=False
        )

        # Define stage computation agent
        stage_computation_agent = Agent(
            role="Stage Computation Agent",
            goal="Determine the current stage of a student's admissions journey by using the Stage Computation Tool.",
            backstory="A specialist that analyzes user progress and determines which stage of the admissions journey they are in. When asked to compute the stage, you MUST use the Stage Computation Tool with the provided user_id to determine the current stage. Always return the stage information as JSON format with current_stage, stage_number, stage_description, and reasoning fields.",
            tools=[StageComputationTool()],
            verbose=True,
            allow_delegation=False
        )

        # Load university search agent from YAML config
        university_config = self.agents_config['university_search_agent'].copy() # type: ignore[index]
        if 'role' in university_config:
            university_config['role'] = university_config['role'].strip()
        university_agent = Agent(
            config=university_config,
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

        # Load scholarship search agent from YAML config
        scholarship_config = self.agents_config['scholarship_search_agent'].copy() # type: ignore[index]
        if 'role' in scholarship_config:
            scholarship_config['role'] = scholarship_config['role'].strip()
        scholarship_agent = Agent(
            config=scholarship_config,
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

        # Load visa search agent from YAML config
        visa_config = self.agents_config['visa_search_agent'].copy() # type: ignore[index]
        if 'role' in visa_config:
            visa_config['role'] = visa_config['role'].strip()
        visa_agent = Agent(
            config=visa_config,
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

        # Load application requirement agent from YAML config
        application_config = self.agents_config['application_requirement_agent'].copy() # type: ignore[index]
        if 'role' in application_config:
            application_config['role'] = application_config['role'].strip()
        application_agent = Agent(
            config=application_config,
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

        # Define stage computation task
        stage_computation_task = Task(
            description=(
                "Compute the current stage of the student's admissions journey for user_id={user_id}. "
                "Use the Stage Computation Tool to determine which stage the student is in based on their profile completeness and progress. "
                "The stages are: "
                "1. Profile Building - Profile is incomplete "
                "2. University Discovery - Profile complete, discovering universities "
                "3. Application Preparation - Universities found, preparing applications "
                "4. Submission & Follow-up - Applications prepared, submitting or following up "
                "5. Visa & Scholarship Preparation - Applications submitted, focusing on visa and scholarships. "
                "Return ONLY the stage information as JSON with current_stage, stage_number, stage_description, and reasoning fields."
            ),
            expected_output=(
                'Return a JSON object with: current_stage (string - e.g., "Profile Building", "University Discovery", etc.), '
                'stage_number (integer 1-5), stage_description (string), reasoning (string explaining why this stage)'
            ),
            agent=stage_computation_agent
        )

        # Define the manager task
        manager_task = Task(
            description=(
                "Guide the student with user_id={user_id} through their admissions journey. "
                "CRITICAL USER_ID RULE: The user_id passed to this task is {user_id}. You MUST use this EXACT user_id value (the numeric value, not the placeholder) when delegating to ALL other agents. "
                "STEP 1 - GET CURRENT STAGE: First delegate to the Stage Computation Agent with this exact task: 'Use the Stage Computation Tool with user_id={user_id} to determine the current stage of the student's admissions journey. Return the stage information as JSON.' "
                "Store the current_stage value from their response - you will use this in your final output. "
                "STEP 2 - GET DATA AGGREGATION: Then delegate to the Data Aggregator Agent with this exact task: 'Use the Admissions Data Aggregation Tool with user_id={user_id} to get current data including counts (universities_found, scholarships_found, application_requirements, visa_info_count), missing_agents array, approaching_deadlines count, approaching_deadlines_details array, incomplete_profile boolean, and missing_profile_fields array. Return the data as JSON.' "
                "CRITICAL: When delegating to Data Aggregator Agent, you MUST explicitly tell them to use the Admissions Data Aggregation Tool with user_id={user_id}. "
                "When delegating to any agent, ALWAYS include 'user_id={user_id}' in the context string, replacing {user_id} with the actual numeric value. "
                "STEP 3 - DELEGATE TO MISSING AGENTS: After getting the data aggregation results, check the missing_agents array. "
                "CRITICAL DELEGATION RULES: "
                "- ONLY delegate to agents that are listed in the missing_agents array from the Data Aggregator Agent's response. "
                "- NEVER delegate to agents that are NOT in missing_agents (these agents already have data and are active). "
                "- If missing_agents is empty, skip all delegation and proceed directly to synthesis. "
                "- When delegating to missing agents, ALWAYS include the actual user_id value in the context (e.g., 'user_id=10' not 'user_id={user_id}'). "
                "- For each missing agent, delegate with a clear task description and user_id={user_id}. Track each delegated agent name in a delegated_agents list. "
                "STEP 4 - GENERATE DETAILED NEXT STEPS: After delegation (or if missing_agents is empty), delegate to the Next Steps Generator Agent to create detailed, actionable next steps. "
                "Delegate with this exact task: 'Generate detailed, actionable next steps for user_id={user_id} based on the current stage, approaching deadlines, and student progress. "
                "You MUST return ONLY a valid JSON array (no markdown, no code blocks, no explanations). Start with [ and end with ]. "
                "Each object must have: action (string), priority (High/Medium/Low), due_date (YYYY-MM-DD), related_agent (string), and reasoning (string). "
                "Current stage: [use the current_stage from Stage Computation Agent]. "
                "Approaching deadlines: [use the approaching_deadlines_details from Data Aggregator Agent]. "
                "Active agents: [list active agents based on available agents minus remaining missing_agents, making sure to include every agent whose task you delegated in this run even if they still appear in missing_agents because their data was not persisted]. "
                "Missing profile fields: [list missing_profile_fields]. "
                "Priority rules: High for deadlines within 14 days, Medium for 30 days, Low for beyond 30 days. "
                "Due date rules: Set 7-10 days before actual deadlines, 3-7 days for urgent profile fields, 14 days for less urgent. "
                "Related agent mapping: University tasks → University Search Agent, Scholarship tasks → Scholarship Search Agent, "
                "Application/essay tasks → Application Requirement Agent, Visa tasks → Visa Information Agent, Profile tasks → Profile Update. "
                "Return 3-5 next steps, ordered by priority (High first) then by due_date (earliest first).' "
                "CRITICAL: The Next Steps Generator Agent's response should be a JSON array. If it includes markdown or extra text, extract only the JSON array portion. "
                "Store the next_steps array from their response - you will use this in your final output. "
                "STEP 5 - GENERATE STRATEGIC ADVICE: Delegate to the Strategic Advice Generator Agent with this exact task: 'Provide mentor-style strategic admissions advice for user_id={user_id}. "
                "Use the Stage Computation Tool and Admissions Data Tool as needed. The student's current stage is: <CURRENT_STAGE>. Summarize the biggest opportunities or risks from approaching deadlines and missing profile fields. "
                "Deliver 2-3 sentences in a supportive tone that balance academics, extracurriculars, and wellbeing. Return ONLY plain text.' Replace <CURRENT_STAGE> with the actual current_stage string you received. "
                "Capture the advice string exactly as returned - you will include it in your final output. "
                "STEP 6 - SYNTHESIS: Synthesize a clear summary incorporating the detailed next steps and the strategic advice. "
                "CRITICAL: Use the current_stage from the Stage Computation Agent's response - DO NOT compute or guess the stage yourself. "
                "CRITICAL: Use the next_steps array from the Next Steps Generator Agent's response - DO NOT generate next steps yourself. "
                "CRITICAL: Use the advice string from the Strategic Advice Generator Agent exactly as returned - DO NOT rewrite or generate your own. "
                "Compute stress_flags as an object with keys: incomplete_profile (true if the refreshed data shows the profile is incomplete), approaching_deadlines (true if any refreshed approaching_deadlines_details exist), and agent_conflicts (true only if you detect conflicting agent outputs). "
                "Your output must include: current_stage (use the exact value from Stage Computation Agent), progress_score (numeric 0-100), active_agents, overview, missing_profile_fields, approaching_deadlines_details, stress_flags (use the rules above), next_steps (use the exact array from Next Steps Generator Agent), and advice (string from Strategic Advice Generator Agent). "
                "ACTIVE_AGENTS RULES: "
                "- active_agents should contain agent names that have data (i.e., agents NOT in missing_agents) plus any agents you delegated tasks to during this run (track them via delegated_agents). "
                "- Available agents: 'University Search Agent', 'Scholarship Search Agent', 'Visa Information Agent', 'Application Requirement Agent'. "
                "- DO NOT include 'Data Aggregator Agent', 'Stage Computation Agent', 'Next Steps Generator Agent', or 'Strategic Advice Generator Agent' in active_agents (these are internal helper agents). "
                "- Example: If missing_agents=['Visa Information Agent'], then active_agents=['University Search Agent', 'Scholarship Search Agent', 'Application Requirement Agent']."
            ),
            expected_output=(
                "Return a JSON object with: current_stage (string - MUST use the value from Stage Computation Agent), progress_score (numeric 0-100, not a percentage string), "
                "active_agents (array of strings - must exclude Data Aggregator Agent, Stage Computation Agent, and Next Steps Generator Agent), overview (string), missing_profile_fields (array of strings), "
                "approaching_deadlines_details (array of objects), stress_flags (object with incomplete_profile, approaching_deadlines, agent_conflicts booleans), next_steps (array of objects - MUST use the exact array from Next Steps Generator Agent, each with action, priority, due_date, related_agent, and reasoning), "
                "advice (string - MUST use the mentor-style strategic advice exactly as returned by the Strategic Advice Generator Agent)"
            )
        )

        # Define Next Steps Generator agent
        next_steps_generator_agent = Agent(
            role="Next Steps Generator Agent",
            goal="Generate actionable, prioritized next steps for students based on their current admissions journey stage and progress.",
            backstory=(
                "You are a strategic planning specialist with expertise in admissions counseling. "
                "You analyze the student's current stage, deadlines, profile completeness, and agent outputs "
                "to generate specific, actionable next steps. Each step you create includes priority level, "
                "calculated due dates, and references to the appropriate agent that should handle the task. "
                "You use rule-based logic combined with LLM reasoning to ensure steps are realistic, timely, "
                "and aligned with the student's goals and deadlines. "
                "CRITICAL: You MUST return ONLY a valid JSON array - no markdown, no code blocks, no explanations outside the JSON. "
                "Start your response immediately with [ and end with ]. "
                "Each object in the array must have: action, priority, due_date, related_agent, and reasoning fields."
            ),
            tools=[AdmissionsDataTool(), ProfileQueryTool()],  # Access to data for generating informed next steps
            verbose=True,
            allow_delegation=False  # Specialist agent - generates steps, doesn't delegate
        )

        # Define Strategic Advice Generator agent (mentor-style guidance)
        strategic_advice_agent = Agent(
            role="Strategic Advice Generator Agent",
            goal="Provide high-level, mentor-style admissions advice that balances academics, extracurriculars, and wellbeing.",
            backstory=(
                "You are a supportive admissions mentor who distills insights from the student's stage, deadlines, and profile data. "
                "Deliver 2-3 sentences of strategic, big-picture guidance that encourages balance (academics, extracurriculars, self-care) "
                "and highlights how to focus efforts over the coming weeks. Maintain an encouraging, mentor-like tone. "
                "Always return plain text without markdown and avoid reiterating detailed task lists."
            ),
            tools=[AdmissionsDataTool(), ProfileQueryTool(), StageComputationTool()],
            verbose=True,
            allow_delegation=False
        )

        # Build and return the crew
        return Crew(
            agents=[
                data_aggregator,
                stage_computation_agent,
                university_agent,
                scholarship_agent,
                visa_agent,
                application_agent,
                next_steps_generator_agent,
                strategic_advice_agent
            ],
            tasks=[manager_task],
            manager_agent=manager,
            process=Process.hierarchical,
            verbose=True,
        )

if __name__ == "__main__":
    crew = SearchCrew()
    print(crew)