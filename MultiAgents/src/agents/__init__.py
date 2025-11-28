# Import all agent functions
from .UniversitySearchAgent import university_search_agent
from .ScholarshipSearchAgent import scholarship_search_agent
from .VisaSearchAgent import visa_search_agent
from .ApplicationRequirementAgent import application_requirement_agent
from .AdmissionCouncelorAgent import admissions_counselor_agent
from .DataAggregatorAgent import data_aggregator_agent
from .NextStepsGeneratorAgent import next_steps_generator_agent
from .StageComputationAgent import stage_computation_agent
from .StrategicAdviceAgent import strategic_advice_agent

__all__ = [
    'university_search_agent',
    'scholarship_search_agent',
    'visa_search_agent',
    'application_requirement_agent',
    'admissions_counselor_agent',
    'data_aggregator_agent',
    'next_steps_generator_agent',
    'stage_computation_agent',
    'strategic_advice_agent'
]