from ..imports import *

def university_search_task(self) -> Task:
    return Task(
        config=self.tasks_config['university_search_task'], # type: ignore[index]
        agent=university_search_agent(self)
    )

def scholarship_search_task(self) -> Task:
    return Task(
        config=self.tasks_config['scholarship_search_task'], # type: ignore[index]
        agent=scholarship_search_agent(self)
    )

def visa_search_task(self) -> Task:
    return Task(
        config=self.tasks_config['visa_search_task'], # type: ignore[index]
        agent=visa_search_agent(self)
    )

def application_requirement_task(self) -> Task:
    return Task(
        config=self.tasks_config['application_requirement_task'], # type: ignore[index]
        agent=application_requirement_agent(self)
    )

def admissions_counselor_task(self) -> Task:
    return Task(
        config=self.tasks_config['admissions_counselor_task'], # type: ignore[index]
        agent=admissions_counselor_agent(self)
    )

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
        agent=data_aggregator_agent(self)
    )

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
        agent=next_steps_generator_agent(self)
    )

def manager_task(self) -> Task:
    return Task(
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

def stage_computation_task(self) -> Task:
    return Task(
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
        agent=stage_computation_agent(self)
    )