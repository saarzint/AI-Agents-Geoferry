import sys
import os

# agents_path = os.path.join(os.path.dirname(__file__), 'agents', 'src')
# sys.path.append(os.path.abspath(agents_path))
# print(agents_path)

from agents.src.agents.crew import SearchCrew  
from crewai import Crew, Process 
from app.token_tracker import extract_crewai_tokens, update_user_tokens


def main() -> None:
    # Build a minimal crew with only the university search agent/task
    search_crew = SearchCrew()
    university_task = search_crew.university_search_task()
    university_agent = search_crew.university_search_agent()

    test_crew = Crew(
        agents=[university_agent],
        tasks=[university_task],
        process=Process.sequential,
        verbose=True,
    )

    result = test_crew.kickoff(
        inputs={
            "user_id": 1,
            "search_request": "Find universities that match my profile",
            "current_year": "2025",
        }
    )

    token_info = extract_crewai_tokens(result)
    tokens_used = token_info.get("total_tokens", 0)

    token_update = update_user_tokens(1, tokens_used, "direct_test")
    print(token_update)


if __name__ == "__main__":
    main()