from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai_tools import TavilySearchTool
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import sys, os
import logging

# Configure logging for the project
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Create logger for this module
logger = logging.getLogger(__name__)

# Add the app directory to the Python path to import supabase_client
app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'app'))
if app_path not in sys.path:
    sys.path.insert(0, app_path)
from supabase_client import get_supabase  # type: ignore

from .tools import ProfileQueryTool, UniversityKnowledgeTool, ProfileChangesTool, \
    ScholarshipMatcherTool, ScholarshipKnowledgeTool, ProfileRequestParsingTool, \
    WebDataRetrievalTool, ApplicationDataExtractionTool, ProfileAccessTool, VisaScraperTool, \
    AdmissionsDataTool, StageComputationTool, OpenAIWebSearchTool
    
from .agents import university_search_agent, scholarship_search_agent, visa_search_agent, \
    application_requirement_agent, admissions_counselor_agent, data_aggregator_agent, \
    next_steps_generator_agent, stage_computation_agent, strategic_advice_agent
    
from .tasks import university_search_task, scholarship_search_task, visa_search_task, \
    application_requirement_task, admissions_counselor_task, data_aggregation_task, \
    next_steps_generator_task, stage_computation_task, manager_task