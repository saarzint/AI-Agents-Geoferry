from .imports import *


@CrewBase
class SearchCrew():
    """AI Agents crew"""
    agents: List[BaseAgent]
    tasks: List[Task]
    
    # Config paths for both agents and tasks
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    @agent
    def university_search_agent(self) -> Agent:
        return university_search_agent(self)

    @agent
    def scholarship_search_agent(self) -> Agent:
        return scholarship_search_agent(self)

    @agent
    def visa_search_agent(self) -> Agent:
        return visa_search_agent(self)
        
    @agent
    def application_requirement_agent(self) -> Agent:
        return application_requirement_agent(self)

    @agent
    def admissions_counselor_agent(self) -> Agent:
        return admissions_counselor_agent(self)

    @agent
    def data_aggregator_agent(self) -> Agent:
        return data_aggregator_agent(self)

    @agent
    def next_steps_generator_agent(self) -> Agent:
        return next_steps_generator_agent(self)

    @agent
    def stage_computation_agent(self) -> Agent:
        return stage_computation_agent(self)
    
    @agent
    def strategic_advice_agent(self) -> Agent:
        return strategic_advice_agent(self)


    @task
    def university_search_task(self) -> Task:
        return university_search_task(self)

    @task
    def scholarship_search_task(self) -> Task:
        return scholarship_search_task(self)

    @task
    def visa_search_task(self) -> Task:
        return visa_search_task(self)

    @task
    def application_requirement_task(self) -> Task:
        return application_requirement_task(self)
    
    @task
    def admissions_counselor_task(self) -> Task:
        return admissions_counselor_task(self)

    @task
    def data_aggregation_task(self) -> Task:
        return data_aggregation_task(self)

    @task
    def next_steps_generator_task(self) -> Task:
        return next_steps_generator_task(self)

    @task
    def stage_computation_task(self) -> Task:
        return stage_computation_task(self)
    
    @task
    def manager_task(self) -> Task:
        return manager_task(self)

    @crew
    def crew(self) -> Crew:
        """Creates the Search crew with ai agents"""
        return Crew(
            agents=self.agents, 
            tasks=self.tasks, 
            process=Process.sequential,
            verbose=True,
        )




class ManagerCrew():
    """AI Agents manager crew with hierarchical process"""
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'
    
    def __init__(self):
        """Initialize ManagerCrew and load agent configs from YAML"""
        search_crew = SearchCrew()
        self.agents_config = search_crew.agents_config
        self.tasks_config = search_crew.tasks_config
        self._search_crew = search_crew
    
    def crew(self) -> Crew:
        """Creates the Manager crew with hierarchical process"""
        
        # Define data aggregator agent
        data_aggregator = data_aggregator_agent(self)

        # Define stage computation agent
        computation_agent = stage_computation_agent(self)

        # Load university search agent from YAML config
        university_config = self.agents_config['university_search_agent'].copy() # type: ignore[index]
        if 'role' in university_config:
            university_config['role'] = university_config['role'].strip()
        university_agent = Agent(
            config=university_config,
            tools=[
                ProfileQueryTool(),
                UniversityKnowledgeTool(),
                OpenAIWebSearchTool()
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
        computation_task = stage_computation_task(self)

        # Define the manager task
        manager_task_ = manager_task(self)
        # Define Next Steps Generator agent
        next_steps_generator_agent_ = next_steps_generator_agent(self)

        # Define Strategic Advice Generator agent (mentor-style guidance)
        strategic_advice_agent_ = strategic_advice_agent(self)

        # Build and return the crew
        return Crew(
            agents=[
                data_aggregator,
                computation_agent,
                university_agent,
                scholarship_agent,
                visa_agent,
                application_agent,
                next_steps_generator_agent_,
                strategic_advice_agent_
            ],
            tasks=[manager_task_],
            manager_agent=manager,
            process=Process.hierarchical,
            verbose=True,
        )

if __name__ == "__main__":
    import logging
    logger = logging.getLogger(__name__)
    crew = SearchCrew()
    print(crew)
    logger.info(f"Crew initialized: {crew}")