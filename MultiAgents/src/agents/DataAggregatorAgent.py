from ..imports import *

def data_aggregator_agent(self) -> Agent:
    """
    Data Aggregator Agent - Specialist
    Provides aggregated read access to admissions data across agents/tables.
    """
    return Agent(
        role="Data Aggregator Agent",
        goal="Aggregate admissions data (universities, scholarships, requirements, visas) for synthesis.",
        backstory=(
            "A focused data specialist that reads and summarizes cross-agent data for the manager. "
            "When asked to aggregate data, you MUST use the Admissions Data Aggregation Tool, "
            "with the provided user_id to get comprehensive admissions data including counts, "
            "missing agents, deadlines, and profile information. Always return the data as JSON format. "
            ),
        tools=[
            AdmissionsDataTool(),
            ProfileQueryTool(),
            ProfileAccessTool(),
        ],
        verbose=True,
        allow_delegation=False
    )