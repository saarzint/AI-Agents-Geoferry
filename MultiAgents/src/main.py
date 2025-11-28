#!/usr/bin/env python
import sys
import warnings
import logging
from .imports import *


from datetime import datetime

from .crews import SearchCrew, ManagerCrew

# Set up logger for this module
logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# This main file is intended to be a way for you to run your
# crew locally, so refrain from adding unnecessary logic into this file.
# Replace with inputs you want to test with, it will automatically
# interpolate any tasks and agents information

def run():
    """
    Run the search crew.
    """
    inputs = {
        'user_id': 1,  # Example user ID - the agent will query this profile
        'search_request': 'Find universities that match my profile',  # Can be broad or specific
        'current_year': str(datetime.now().year)
    }
    
    try:
        SearchCrew().crew().kickoff(inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")


def run_manager():
    """
    Run the manager crew with hierarchical process.
    """
    inputs = {
        'user_id': 1,  # Example user ID - the manager will delegate to agents
        'current_year': str(datetime.now().year)
    }
    
    try:
        ManagerCrew().crew().kickoff(inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while running the manager crew: {e}")


def run_profile_query_demo():
    """
    Demo function to test the Profile Query Tool implementation.
    """
    from .tools.profile_query_tool import ProfileQueryTool
    
    tool = ProfileQueryTool()
    
    print("=== PROFILE QUERY TOOL DEMO ===\n")
    logger.info("=== PROFILE QUERY TOOL DEMO ===\n")
    
    # Test 1: University Search Agent gets specific user profile
    print("1. University Search Agent queries user profile (typical workflow):")
    logger.info("1. University Search Agent queries user profile (typical workflow):")
    result = tool._run(user_id=1, full_profile=True)
    print(result)
    logger.info(result)
    print("\n" + "="*50 + "\n")
    logger.info("\n" + "="*50 + "\n")
    
    # Test 2: Performance-optimized query (academic data only)
    print("2. Academic-focused query (performance optimized):")
    logger.info("2. Academic-focused query (performance optimized):")
    result = tool._run(user_id=1, include_preferences=False, include_extracurriculars=False)
    print(result)
    logger.info(result)
    print("\n" + "="*50 + "\n")
    logger.info("\n" + "="*50 + "\n")
    
    # Test 3: Agent needs to check if user exists
    print("3. Check for non-existent user (error handling):")
    logger.info("3. Check for non-existent user (error handling):")
    result = tool._run(user_id=999)
    print(result)
    logger.info(result)


def train():
    """
    Train the crew for a given number of iterations.
    Uses SearchCrew for training.
    """
    inputs = {
        "topic": "AI LLMs",
        'current_year': str(datetime.now().year)
    }
    try:
        SearchCrew().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")

def replay():
    """
    Replay the crew execution from a specific task.
    Uses SearchCrew for replay.
    """
    try:
        SearchCrew().crew().replay(task_id=sys.argv[1])
    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")

def test():
    """
    Test the crew execution and returns the results.
    Uses SearchCrew for testing.
    """
    inputs = {
        "topic": "AI LLMs",
        "current_year": str(datetime.now().year)
    }
    try:
        SearchCrew().crew().test(n_iterations=int(sys.argv[1]), eval_llm=sys.argv[2], inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")
