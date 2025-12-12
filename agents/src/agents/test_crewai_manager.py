import os
from crewai import Agent, Task, Crew, Process
from dotenv import load_dotenv


class TestEnv:
    """Factory for building the Crew used by this project."""

    def __init__(self) -> None:
        # Load environment variables from project root .env (one directory above src)
        load_dotenv(
            os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", ".env")
            )
        )

    def crew(self) -> Crew:
        """Create and return the Crew instance."""

        # Define agents
        researcher = Agent(
            role="Researcher",
            goal="Conduct thorough research and analysis on AI and AI agents",
            backstory=(
                "You're an expert researcher, specialized in technology, software "
                "engineering, AI, and startups. You work as a freelancer and are "
                "currently researching for a new client."
            ),
            allow_delegation=False,
        )

        writer = Agent(
            role="Senior Writer",
            goal="Create compelling content about AI and AI agents",
            backstory=(
                "You're a senior writer, specialized in technology, software "
                "engineering, AI, and startups. You work as a freelancer and are "
                "currently writing content for a new client."
            ),
            allow_delegation=False,
        )

        # Define the content task
        task = Task(
            description=(
                "Generate a list of 5 interesting ideas for an article, then write "
                "one captivating paragraph for each idea that showcases the potential "
                "of a full article on this topic. Return the list of ideas with their "
                "paragraphs and your notes."
            ),
            expected_output=(
                "5 bullet points, each with a paragraph and accompanying notes."
            ),
        )

        # Define the manager agent
        manager = Agent(
            role="Project Manager",
            goal="Efficiently manage the crew and ensure high-quality task completion",
            backstory=(
                "You're an experienced project manager, skilled in overseeing complex "
                "projects and guiding teams to success. Your role is to coordinate the "
                "efforts of the crew members, ensuring that each task is completed on "
                "time and to the highest standard."
            ),
            allow_delegation=True,
        )

        # Build and return the crew
        return Crew(
            agents=[researcher, writer],
            tasks=[task],
            manager_agent=manager,
            process=Process.hierarchical,
            verbose=True,
        )

def run():
    """
    Run the crew.
    """
    try:
        TestEnv().crew().kickoff()
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")

if __name__ == "__main__":
    run()