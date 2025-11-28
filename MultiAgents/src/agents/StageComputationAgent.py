from ..imports import *

def stage_computation_agent(self) -> Agent:
    return Agent(
        role="Stage Computation Agent",
        goal="Determine the current stage of a student's admissions journey by using the Stage Computation Tool.",
        backstory="A specialist that analyzes user progress and determines which stage of the admissions journey they are in. When asked to compute the stage, you MUST use the Stage Computation Tool with the provided user_id to determine the current stage. Always return the stage information as JSON format with current_stage, stage_number, stage_description, and reasoning fields.",
        tools=[StageComputationTool()],
        verbose=True,
        allow_delegation=False
    )