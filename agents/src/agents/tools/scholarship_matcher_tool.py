from crewai.tools import BaseTool
from typing import Type, Dict, Any, List, Optional
from pydantic import BaseModel, Field
import sys
import os
import re
import json
import requests
from datetime import datetime, date

# Add the app directory to the Python path to import supabase_client
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'app'))

try:
    from supabase_client import get_supabase
except ImportError:
    print("Warning: Could not import supabase_client. Make sure the app module is in the Python path.")
    get_supabase = None


class ScholarshipMatcherInput(BaseModel):
    """Input schema for ScholarshipMatcherTool."""
    user_id: int = Field(..., description="User ID to match scholarships for")
    scholarships_data: List[Dict[str, Any]] = Field(..., description="List of scholarship data to match against user profile")
    matching_mode: str = Field("comprehensive", description="Matching mode: 'comprehensive' or 'delta'")


class ScholarshipMatcherTool(BaseTool):
    name: str = "Scholarship Matcher Tool"
    description: str = (
        "Advanced scholarship matching and filtering tool that applies eligibility criteria, "
        "academic thresholds, demographic requirements, and identifies near-miss opportunities. "
        "This tool takes raw scholarship data and user profile to perform intelligent matching "
        "with categorization (High/Medium/Low/Near Match) based on multiple criteria."
    )
    args_schema: Type[BaseModel] = ScholarshipMatcherInput

    def _normalize_deadline(self, deadline: Any) -> Optional[str]:
        """
        Normalize deadline values to None if they represent unknown/invalid deadlines.
        
        Args:
            deadline: Deadline value (can be str, date, None, or "Unknown Deadline")
            
        Returns:
            Normalized deadline string (YYYY-MM-DD format) or None if unknown/invalid
        """
        if deadline is None:
            return None
        
        # Convert "Unknown Deadline" strings to None
        if isinstance(deadline, str):
            deadline_lower = deadline.strip().lower()
            if deadline_lower in ['unknown deadline', 'unknown', 'tbd', 'tba', 'n/a', 'na', '']:
                return None
        
        # If it's already a date object, convert to string
        if isinstance(deadline, date):
            return deadline.isoformat()
        
        # If it's a string, try to validate it's a proper date format
        if isinstance(deadline, str):
            deadline_str = deadline.strip()
            # Try to parse as date to validate
            try:
                for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%B %d, %Y', '%m-%d-%Y', '%Y/%m/%d']:
                    try:
                        datetime.strptime(deadline_str, fmt).date()
                        return deadline_str if fmt == '%Y-%m-%d' else datetime.strptime(deadline_str, fmt).date().isoformat()
                    except ValueError:
                        continue
                # If no format matched and it's not "Unknown Deadline", return None
                return None
            except Exception:
                return None
        
        # For any other type, return None
        return None

    def _run(self, user_id: int, scholarships_data: List[Dict[str, Any]], matching_mode: str = "comprehensive") -> str:
        """
        Perform advanced scholarship matching with eligibility filtering.
        
        Args:
            user_id: User ID to match scholarships for
            scholarships_data: List of scholarship data from web search or other sources
            matching_mode: 'comprehensive' for full matching, 'delta' for change-based matching
            
        Returns:
            JSON string with matched and categorized scholarships
        """
        
        if get_supabase is None:
            return "Error: Supabase client not available. Please check your configuration."
        
        # Always clean expired scholarships first - simple and effective
        cleanup_result = self.clean_expired_scholarships(user_id)
        print(f"Expired scholarship cleanup: {cleanup_result}")
        
        supabase = get_supabase()
        
        # Get user profile for matching
        profile_resp = supabase.table('user_profile').select('*').eq('id', user_id).execute()
        
        if not profile_resp.data:
            return f"Error: User profile {user_id} not found"
        
        user_profile = profile_resp.data[0]
        
        print(f"ScholarshipMatcherTool: Received {len(scholarships_data)} scholarships for user {user_id}")
        
        # STEP 1: Extract real scholarship data from URLs
        enhanced_scholarships = []
        for scholarship in scholarships_data:
            enhanced_scholarship = self._extract_real_scholarship_data(scholarship)
            enhanced_scholarships.append(enhanced_scholarship)
        
        # STEP 2: Filter out expired scholarships
        active_scholarships = self._filter_active_scholarships(enhanced_scholarships)
        print(f"ScholarshipMatcherTool: After deadline filtering: {len(active_scholarships)} active scholarships")
        
        # Apply matching algorithms to active scholarships only
        matched_scholarships = []
        
        for scholarship in active_scholarships:
            # Validate scholarship data quality
            validated_scholarship = self._validate_scholarship_data(scholarship)
            
            # Skip scholarships without URLs
            if not validated_scholarship.get('application_url') and not validated_scholarship.get('source_url'):
                continue
            
            match_result = self._evaluate_scholarship_match(user_profile, validated_scholarship)
            
            # Generate structured summary matching database schema
            scholarship_summary = self.generate_scholarship_summary(validated_scholarship)
            
            # Add categorization to the scholarship
            scholarship_categories = self._categorize_scholarship(validated_scholarship)
            
            if match_result["eligible"]:
                matched_scholarships.append({
                    **scholarship_summary,  # Use structured summary instead of raw data
                    "match_category": match_result["match_category"],
                    "match_score": match_result["match_score"],
                    "scholarship_categories": scholarship_categories,
                    "eligibility_analysis": match_result["analysis"],
                    "near_miss_reasons": match_result.get("near_miss_reasons", []),
                    "why_match": match_result["explanation"]
                })
        
        # Sort by match score (highest first)
        matched_scholarships.sort(key=lambda x: x.get("match_score", 0), reverse=True)
        
        # Only save scholarships with valid URLs to database
        # Final filter: Remove any expired scholarships that might have slipped through
        final_scholarships = []
        current_date = datetime.now().date()
        
        for scholarship in matched_scholarships:
            # Normalize deadline - convert "Unknown Deadline" to None
            deadline_str = self._normalize_deadline(scholarship.get('deadline'))
            scholarship['deadline'] = deadline_str  # Update scholarship with normalized deadline
            
            if deadline_str:
                deadline_date = datetime.strptime(deadline_str, '%Y-%m-%d').date()
                if deadline_date > current_date:
                    final_scholarships.append(scholarship)
                else:
                    print(f"Final filter: Excluded expired scholarship '{scholarship.get('name')}' (deadline: {deadline_str})")
            else:
                # No deadline specified (or was "Unknown Deadline"), include it
                final_scholarships.append(scholarship)
        
        print(f"💾 Saving {len(final_scholarships)} scholarships to database")
        self._save_scholarships_to_database(user_id, final_scholarships)
        
        return self._format_matching_output(user_id, matched_scholarships, matching_mode)
    
    def _evaluate_scholarship_match(self, user_profile: Dict[str, Any], scholarship: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate how well a scholarship matches a user profile.
        
        Returns:
            Dict with eligibility, match_category, match_score, analysis, and explanation
        """
        
        # CRITICAL: Normalize list fields to prevent "argument of type 'int' is not iterable" errors
        # Some database fields (JSONB) may return integers (0/1) instead of lists
        list_fields_to_normalize = [
            'eligible_majors', 'field_keywords', 'demographic_requirements',
            'location_restrictions', 'applicant_requirements', 'application_steps',
            'required_documents', 'eligibility_requirements', 'requirements'
        ]
        for field in list_fields_to_normalize:
            value = scholarship.get(field)
            if value is not None and not isinstance(value, list):
                # If it's an int, bool, or other non-list type, convert to empty list
                scholarship[field] = []
        
        # Initialize scoring
        match_score = 0
        max_possible_score = 0
        eligibility_issues = []
        match_strengths = []
        near_miss_reasons = []
        
        # 1. ACADEMIC THRESHOLDS (Weight: 28%)
        academic_weight = 28
        max_possible_score += academic_weight
        
        user_gpa = user_profile.get('gpa')
        required_gpa = scholarship.get('min_gpa') or scholarship.get('gpa_requirement')
        
        if required_gpa and user_gpa:
            if user_gpa >= required_gpa:
                match_score += academic_weight
                match_strengths.append(f"GPA {user_gpa} meets requirement of {required_gpa}")
            elif user_gpa >= (required_gpa - 0.2):  # Near miss within 0.2 points
                match_score += academic_weight * 0.7
                near_miss_reasons.append(f"GPA {user_gpa} is close to requirement of {required_gpa}")
            else:
                eligibility_issues.append(f"GPA {user_gpa} below requirement of {required_gpa}")
        elif required_gpa and not user_gpa:
            eligibility_issues.append("GPA requirement exists but user GPA unknown")
        elif user_gpa and not required_gpa:
            match_score += academic_weight * 0.8  # Bonus for having GPA when not required
            match_strengths.append(f"Strong GPA of {user_gpa}")
        
        # 2. MAJOR/FIELD MATCHING (Weight: 25%)
        major_weight = 25
        max_possible_score += major_weight
        
        user_major = user_profile.get('intended_major', '').lower()
        
        # DEBUG: Check types before processing
        eligible_majors_raw = scholarship.get('eligible_majors', [])
        print(f"DEBUG Line 234: eligible_majors type={type(eligible_majors_raw)}, value={eligible_majors_raw}")
        if not isinstance(eligible_majors_raw, list):
            print(f"ERROR: eligible_majors is not a list! Type: {type(eligible_majors_raw)}, Value: {eligible_majors_raw}")
            raise TypeError(f"eligible_majors must be a list, got {type(eligible_majors_raw)}: {eligible_majors_raw}")
        
        scholarship_fields = [f.lower() for f in eligible_majors_raw]
        
        field_keywords_raw = scholarship.get('field_keywords', [])
        print(f"DEBUG Line 235: field_keywords type={type(field_keywords_raw)}, value={field_keywords_raw}")
        if not isinstance(field_keywords_raw, list):
            print(f"ERROR: field_keywords is not a list! Type: {type(field_keywords_raw)}, Value: {field_keywords_raw}")
            raise TypeError(f"field_keywords must be a list, got {type(field_keywords_raw)}: {field_keywords_raw}")
        
        scholarship_keywords = field_keywords_raw
        
        if scholarship_fields or scholarship_keywords:
            print(f"DEBUG Line 238: Checking if any field in {scholarship_fields} or keyword in {scholarship_keywords}")
            if any(field in user_major for field in scholarship_fields) or \
               any(keyword.lower() in user_major for keyword in scholarship_keywords):
                match_score += major_weight
                match_strengths.append(f"Major '{user_major}' matches scholarship field requirements")
            else:
                # Check for related fields (near miss)
                print(f"DEBUG Line 245: Combining {scholarship_fields} + {scholarship_keywords}")
                related_match = self._check_related_majors(user_major, scholarship_fields + scholarship_keywords)
                if related_match:
                    match_score += major_weight * 0.6
                    near_miss_reasons.append(f"Major '{user_major}' is related to required fields")
                else:
                    eligibility_issues.append(f"Major '{user_major}' doesn't match required fields")
        else:
            match_score += major_weight * 0.9  # Most scholarships available to all majors
        
        # 3. FINANCIAL NEED (Weight: 22%)
        financial_weight = 22
        max_possible_score += financial_weight
        
        # Extract financial data from user profile
        user_budget = user_profile.get('budget')
        seeks_financial_aid = user_profile.get('financial_aid_eligibility', False)
        
        scholarship_need_based = scholarship.get('need_based', False)
        scholarship_income_limit = scholarship.get('max_family_income')
        
        if scholarship_need_based:
            # Need-based scholarship - check if user is seeking aid
            if seeks_financial_aid:
                # User is actively seeking financial aid
                if scholarship_income_limit and user_budget:
                    # More sophisticated budget analysis for need assessment
                    # Budget likely represents annual education cost (tuition + living expenses)
                    # Family income estimation: Conservative approach
                    if user_budget <= 15000:  # Very low budget
                        estimated_income = user_budget * 2.5  # Likely very low income
                    elif user_budget <= 30000:  # Low-moderate budget
                        estimated_income = user_budget * 3.0  # Moderate income
                    elif user_budget <= 50000:  # Moderate budget
                        estimated_income = user_budget * 3.5  # Above moderate income
                    else:  # High budget
                        estimated_income = user_budget * 4.0  # Higher income but still seeking aid
                    
                    if estimated_income <= scholarship_income_limit:
                        match_score += financial_weight
                        match_strengths.append(f"Seeking financial aid and estimated income meets need-based requirements")
                    elif estimated_income <= (scholarship_income_limit * 1.15):  # 15% buffer for near miss
                        match_score += financial_weight * 0.7
                        near_miss_reasons.append(f"Seeking aid and close to income requirements (estimated: ${estimated_income:,}, limit: ${scholarship_income_limit:,})")
                    else:
                        match_score += financial_weight * 0.3  # Still give some credit for seeking aid
                        near_miss_reasons.append(f"Seeking aid but estimated income may exceed requirements")
                        
                elif scholarship_income_limit and not user_budget:
                    # User seeks aid but no budget data - assume eligible
                    match_score += financial_weight * 0.8
                    match_strengths.append("Seeking financial aid - likely eligible for need-based scholarship")
                    
                else:
                    # Need-based scholarship but no income limits specified
                    match_score += financial_weight * 0.9
                    match_strengths.append("Seeking financial aid and scholarship has flexible need requirements")
                    
            else:
                # Need-based scholarship but user not seeking aid
                if user_budget and user_budget > 60000:  # High budget suggests no need
                    eligibility_issues.append("Need-based scholarship but user not seeking financial aid (high budget suggests no need)")
                else:
                    # Lower budget but not seeking aid - might be eligible
                    match_score += financial_weight * 0.4
                    near_miss_reasons.append("Need-based scholarship - consider applying for financial aid to improve eligibility")
                    
        else:
            # Merit-based scholarship - financial need not a factor
            if seeks_financial_aid:
                # User seeking aid for merit scholarship (good - shows financial motivation)
                match_score += financial_weight * 0.95
                match_strengths.append("Merit-based scholarship with financial need motivation")
            else:
                # Standard merit-based evaluation
                match_score += financial_weight * 0.85
                match_strengths.append("Merit-based scholarship - no financial need requirements")
        
        # 4. DEMOGRAPHICS (Weight: 13%)
        demographic_weight = 13
        max_possible_score += demographic_weight
        
        # Extract demographic data from user preferences JSONB
        user_preferences = user_profile.get('preferences', {})
        if isinstance(user_preferences, str):
            import json
            try:
                user_preferences = json.loads(user_preferences)
            except:
                user_preferences = {}
        # Cloud Run stores some JSONB defaults as 0/1; ensure we always work with a dict
        if not isinstance(user_preferences, dict):
            user_preferences = {}
        
        demographic_requirements_raw = scholarship.get('demographic_requirements', [])
        print(f"DEBUG Line 355: demographic_requirements type={type(demographic_requirements_raw)}, value={demographic_requirements_raw}")
        if not isinstance(demographic_requirements_raw, list):
            print(f"ERROR: demographic_requirements is not a list! Type: {type(demographic_requirements_raw)}, Value: {demographic_requirements_raw}")
            raise TypeError(f"demographic_requirements must be a list, got {type(demographic_requirements_raw)}: {demographic_requirements_raw}")
        
        scholarship_demographics = demographic_requirements_raw
        
        if not scholarship_demographics:
            match_score += demographic_weight * 0.95  # Open to all demographics
            match_strengths.append("No specific demographic restrictions - open to all students")
        else:
            # Check for demographic matches using preferences data
            demographic_matches = []
            demographic_hints = []
            
            # Extract demographic information from preferences
            user_background = user_preferences.get('background', '').lower() if user_preferences else ''
            user_identity = user_preferences.get('identity', '').lower() if user_preferences else ''
            user_status = user_preferences.get('student_status', '').lower() if user_preferences else ''
            user_military = user_preferences.get('military_status', '').lower() if user_preferences else ''
            user_demographics = user_preferences.get('demographics', '').lower() if user_preferences else ''
            
            # Combine all demographic info for analysis
            user_demo_text = f"{user_background} {user_identity} {user_status} {user_military} {user_demographics}".strip()
            
            # Check each scholarship demographic requirement
            print(f"DEBUG Line 372: Iterating over scholarship_demographics: {scholarship_demographics}")
            for demo_req in scholarship_demographics:
                demo_req_lower = demo_req.lower()
                
                # Direct keyword matching
                if any(keyword in user_demo_text for keyword in demo_req_lower.split()):
                    demographic_matches.append(demo_req)
                    
                # Specific demographic category matching
                elif 'women' in demo_req_lower or 'female' in demo_req_lower:
                    if any(term in user_demo_text for term in ['female', 'woman', 'women']):
                        demographic_matches.append(demo_req)
                    elif 'gender' in user_preferences:
                        demographic_hints.append(f"Gender information available for {demo_req}")
                        
                elif 'minority' in demo_req_lower or 'underrepresented' in demo_req_lower:
                    if any(term in user_demo_text for term in ['minority', 'underrepresented', 'diverse', 'ethnicity']):
                        demographic_matches.append(demo_req)
                    elif 'ethnicity' in user_preferences or 'race' in user_preferences:
                        demographic_hints.append(f"Ethnicity information available for {demo_req}")
                        
                elif 'first generation' in demo_req_lower or 'first-gen' in demo_req_lower:
                    if any(term in user_demo_text for term in ['first generation', 'first-gen', 'first gen']):
                        demographic_matches.append(demo_req)
                        
                elif 'veteran' in demo_req_lower or 'military' in demo_req_lower:
                    if any(term in user_demo_text for term in ['veteran', 'military', 'armed forces']):
                        demographic_matches.append(demo_req)
                        
                elif 'international' in demo_req_lower:
                    if any(term in user_demo_text for term in ['international', 'foreign', 'visa']):
                        demographic_matches.append(demo_req)
                    elif 'citizenship' in user_preferences or 'visa_status' in user_preferences:
                        demographic_hints.append(f"Citizenship information available for {demo_req}")
            
            # Calculate demographic score based on matches
            if demographic_matches:
                match_percentage = len(demographic_matches) / len(scholarship_demographics)
                match_score += demographic_weight * match_percentage
                match_strengths.append(f"Meets demographic requirements: {', '.join(demographic_matches[:2])}")
                
            elif demographic_hints:
                # User has relevant demographic info but unclear match
                match_score += demographic_weight * 0.6
                near_miss_reasons.append(f"May qualify for demographic requirements - review: {', '.join(scholarship_demographics[:2])}")
                
            elif user_demo_text.strip():
                # User has some demographic info but no clear matches
                match_score += demographic_weight * 0.4
                near_miss_reasons.append(f"Demographic requirements exist ({', '.join(scholarship_demographics[:2])}) - verify eligibility")
                
            else:
                # No user demographic information available
                match_score += demographic_weight * 0.3
                near_miss_reasons.append(f"Demographic requirements may apply: {', '.join(scholarship_demographics[:2])} - update profile for better matching")
        
        # 5. LOCATION (Weight: 12%)
        location_weight = 12
        max_possible_score += location_weight
        
        # Extract location data from user preferences JSONB (already loaded above)
        location_restrictions_raw = scholarship.get('location_restrictions', [])
        print(f"DEBUG Line 440: location_restrictions type={type(location_restrictions_raw)}, value={location_restrictions_raw}")
        if not isinstance(location_restrictions_raw, list):
            print(f"ERROR: location_restrictions is not a list! Type: {type(location_restrictions_raw)}, Value: {location_restrictions_raw}")
            raise TypeError(f"location_restrictions must be a list, got {type(location_restrictions_raw)}: {location_restrictions_raw}")
        
        scholarship_location = location_restrictions_raw
        
        if not scholarship_location:
            match_score += location_weight
            match_strengths.append("No location restrictions - available nationwide")
        else:
            # Extract multiple location fields from preferences
            user_state = user_preferences.get('state', '') if user_preferences else ''
            user_region = user_preferences.get('region', '') if user_preferences else ''
            user_location_pref = user_preferences.get('location_preference', '') if user_preferences else ''
            user_residence = user_preferences.get('residence', '') if user_preferences else ''
            user_home_state = user_preferences.get('home_state', '') if user_preferences else ''
            
            # Combine all location information
            user_location_data = f"{user_state} {user_region} {user_location_pref} {user_residence} {user_home_state}".lower().strip()
            
            location_matches = []
            location_hints = []
            
            # Check each scholarship location requirement
            for loc_req in scholarship_location:
                loc_req_lower = loc_req.lower()
                
                # Direct matching for states, regions, cities
                if any(keyword in user_location_data for keyword in loc_req_lower.split()):
                    location_matches.append(loc_req)
                    
                # State abbreviation matching (common in scholarships)
                elif len(loc_req.strip()) == 2:  # Likely state abbreviation
                    state_abbrev = loc_req.strip().upper()
                    if state_abbrev in user_location_data.upper():
                        location_matches.append(loc_req)
                        
                # Region-based matching
                elif 'northeast' in loc_req_lower and any(region in user_location_data for region in ['northeast', 'new england', 'mid-atlantic']):
                    location_matches.append(loc_req)
                elif 'southeast' in loc_req_lower and any(region in user_location_data for region in ['southeast', 'south', 'atlantic']):
                    location_matches.append(loc_req)
                elif 'midwest' in loc_req_lower and any(region in user_location_data for region in ['midwest', 'great lakes', 'plains']):
                    location_matches.append(loc_req)
                elif 'west' in loc_req_lower and any(region in user_location_data for region in ['west', 'pacific', 'mountain']):
                    location_matches.append(loc_req)
                    
                # National/broad matching
                elif any(broad_term in loc_req_lower for broad_term in ['us', 'usa', 'united states', 'national', 'nationwide']):
                    location_matches.append(loc_req)
                    
                # Potential matches that need verification
                elif user_location_data and len(user_location_data) > 3:
                    location_hints.append(loc_req)
            
            # Calculate location score
            if location_matches:
                match_score += location_weight
                match_strengths.append(f"Location requirements met: {', '.join(location_matches[:2])}")
                
            elif location_hints:
                # Potential location match but needs verification
                match_score += location_weight * 0.6
                near_miss_reasons.append(f"Location requirements may apply: {', '.join(scholarship_location[:2])} - verify your residence eligibility")
                
            elif user_location_data:
                # User has location info but no clear matches
                match_score += location_weight * 0.3
                near_miss_reasons.append(f"Location restrictions apply: {', '.join(scholarship_location[:2])} (Your location: {user_state or 'Not specified'})")
                
            else:
                # No location information available
                match_score += location_weight * 0.2
                near_miss_reasons.append(f"Location requirements exist ({', '.join(scholarship_location[:2])}) - add location to profile for accurate matching")
        
        # Calculate final match percentage
        match_percentage = (match_score / max_possible_score) * 100 if max_possible_score > 0 else 0
        
        # Determine eligibility and match category
        eligible = len(eligibility_issues) == 0
        
        if not eligible and len(near_miss_reasons) > 0:
            # Near miss - close but missing 1-2 criteria
            eligible = True  # Include as "Near Match"
            match_category = "Near Match"
        elif match_percentage >= 85:
            match_category = "High Match"
        elif match_percentage >= 70:
            match_category = "Medium Match"
        elif match_percentage >= 50:
            match_category = "Low Match"
        else:
            eligible = False
            match_category = "Not Eligible"
        
        # Generate explanation
        explanation = self._generate_match_explanation(match_category, match_strengths, near_miss_reasons, eligibility_issues)
        
        return {
            "eligible": eligible,
            "match_category": match_category,
            "match_score": round(match_percentage, 1),
            "analysis": {
                "strengths": match_strengths,
                "eligibility_issues": eligibility_issues,
                "near_miss_count": len(near_miss_reasons)
            },
            "near_miss_reasons": near_miss_reasons,
            "explanation": explanation
        }
    
    def _categorize_scholarship(self, scholarship: Dict[str, Any]) -> List[str]:
        """
        Categorize scholarship into types: Merit-Based, Need-Based, Major-Specific, 
        Demographic-Specific, Essay Required.
        
        Args:
            scholarship: Scholarship data dictionary
            
        Returns:
            List of applicable categories
        """
        # CRITICAL: Normalize list fields to prevent "argument of type 'int' is not iterable" errors
        list_fields_to_normalize = [
            'eligible_majors', 'field_keywords', 'demographic_requirements',
            'location_restrictions', 'requirements', 'eligibility_requirements'
        ]
        for field in list_fields_to_normalize:
            value = scholarship.get(field)
            if value is not None and not isinstance(value, list):
                scholarship[field] = []
        
        categories = []
        
        # PRIORITY 1: Use agent-provided category if available and valid
        agent_category = scholarship.get('category', '')
        valid_categories = ['Merit-Based', 'Need-Based', 'Major-Specific', 'Demographic-Specific', 'Essay Required']
        
        if agent_category in valid_categories:
            categories.append(agent_category)
            return categories
        
        # PRIORITY 2: Fallback to content analysis if agent category is not provided or invalid
        # Get scholarship fields for analysis
        name = scholarship.get('name', '').lower()
        description = scholarship.get('description', '').lower()
        requirements = scholarship.get('requirements', [])
        eligibility = scholarship.get('eligibility_criteria', {})
        
        # Combine text fields for keyword analysis
        text_content = f"{name} {description} {' '.join(requirements) if isinstance(requirements, list) else str(requirements)}"
        
        # 1. MERIT-BASED: Academic achievement, GPA, test scores, academic excellence
        merit_keywords = [
            'merit', 'academic', 'gpa', 'grade', 'achievement', 'excellence', 'honor', 
            'scholar', 'dean', 'valedictorian', 'academic achievement', 'high achiever',
            'sat', 'act', 'gre', 'test score', 'academic performance', 'top student'
        ]
        
        # Check for GPA requirements or merit indicators
        has_gpa_requirement = (
            scholarship.get('min_gpa') or 
            scholarship.get('gpa_requirement') or
            any(keyword in text_content for keyword in merit_keywords)
        )
        
        if has_gpa_requirement:
            categories.append('Merit-Based')
        
        # 2. NEED-BASED: Financial need, income limits, economic hardship
        need_keywords = [
            'need', 'financial', 'income', 'hardship', 'low income', 'economic',
            'disadvantaged', 'pell grant', 'fafsa', 'family income', 'poverty',
            'financial aid', 'financial assistance', 'need-based'
        ]
        
        # Check for need-based indicators
        has_need_requirement = (
            scholarship.get('need_based') or
            scholarship.get('max_family_income') or
            any(keyword in text_content for keyword in need_keywords)
        )
        
        if has_need_requirement:
            categories.append('Need-Based')
        
        # 3. MAJOR-SPECIFIC: Specific fields of study, majors, career paths
        major_keywords = [
            'engineering', 'business', 'nursing', 'education', 'computer science',
            'medicine', 'law', 'arts', 'science', 'mathematics', 'psychology',
            'communications', 'journalism', 'agriculture', 'pharmacy', 'dentistry'
        ]
        
        # Check for major restrictions or field-specific requirements
        has_major_requirement = (
            scholarship.get('eligible_majors') or
            scholarship.get('field_keywords') or
            scholarship.get('required_major') or
            any(keyword in text_content for keyword in major_keywords)
        )
        
        if has_major_requirement:
            categories.append('Major-Specific')
        
        # 4. DEMOGRAPHIC-SPECIFIC: Identity, ethnicity, gender, first-gen, military
        demographic_keywords = [
            'women', 'female', 'male', 'hispanic', 'latino', 'african american', 'black',
            'asian', 'native american', 'indigenous', 'minority', 'first generation',
            'veteran', 'military', 'disability', 'lgbtq', 'immigrant', 'refugee',
            'single parent', 'non-traditional', 'underrepresented'
        ]
        
        # Check for demographic requirements
        has_demographic_requirement = (
            scholarship.get('demographic_requirements') or
            scholarship.get('gender_requirement') or
            scholarship.get('ethnicity_requirement') or
            any(keyword in text_content for keyword in demographic_keywords)
        )
        
        if has_demographic_requirement:
            categories.append('Demographic-Specific')
        
        # 5. ESSAY REQUIRED: Written components, essays, personal statements
        essay_keywords = [
            'essay', 'personal statement', 'written', 'write', 'composition',
            'statement of purpose', 'letter of intent', 'narrative', 'reflection',
            'writing sample', 'creative writing', 'application essay'
        ]
        
        # Check for essay requirements
        has_essay_requirement = (
            scholarship.get('essay_required') or
            scholarship.get('requires_essay') or
            any(keyword in text_content for keyword in essay_keywords)
        )
        
        if has_essay_requirement:
            categories.append('Essay Required')
        
        # If no categories identified, default to Merit-Based (most common)
        if not categories:
            categories.append('Merit-Based')
        
        return categories

    def _check_related_majors(self, user_major: str, scholarship_fields: List[str]) -> bool:
        """Check if user major is related to scholarship fields."""
        
        # Define related major clusters
        major_clusters = {
            'engineering': ['computer science', 'software', 'mechanical', 'electrical', 'civil', 'aerospace', 'biomedical engineering', 'chemical engineering', 'industrial engineering', 'environmental engineering'],
            'business': ['finance', 'accounting', 'marketing', 'management', 'economics', 'entrepreneurship', 'business administration', 'supply chain', 'operations management'],
            'science': ['biology', 'chemistry', 'physics', 'mathematics', 'statistics', 'data science', 'environmental science', 'materials science', 'biotechnology'],
            'health': ['nursing', 'medicine', 'pharmacy', 'dentistry', 'therapy', 'pre-med', 'public health', 'health administration', 'medical technology', 'physical therapy', 'occupational therapy'],
            'arts': ['art', 'design', 'music', 'theater', 'creative', 'fine arts', 'graphic design', 'film', 'photography', 'creative writing', 'digital arts'],
            'social_sciences': ['psychology', 'sociology', 'political science', 'anthropology', 'social work', 'criminal justice', 'international relations'],
            'education': ['education', 'teaching', 'elementary education', 'special education', 'educational leadership', 'curriculum development'],
            'technology': ['information technology', 'cybersecurity', 'software development', 'artificial intelligence', 'machine learning', 'data analytics']
        }
        
        # Find user major cluster
        user_cluster = None
        for cluster, majors in major_clusters.items():
            if any(major in user_major for major in majors):
                user_cluster = cluster
                break
        
        if not user_cluster:
            return False
        
        # Check if any scholarship field is in the same cluster
        cluster_majors = major_clusters[user_cluster]
        return any(any(major in field.lower() for major in cluster_majors) for field in scholarship_fields)
    
    def _generate_match_explanation(self, match_category: str, strengths: List[str], near_misses: List[str], issues: List[str]) -> str:
        """Generate human-readable explanation for the match."""
        
        if match_category == "High Match":
            explanation = f"Excellent fit. {'. '.join(strengths[:2])}"
        elif match_category == "Medium Match":
            explanation = f"Good fit. {'. '.join(strengths[:2])}"
        elif match_category == "Low Match":
            explanation = f"Possible fit. {'. '.join(strengths[:1])}"
        elif match_category == "Near Match":
            explanation = f"Close match with minor gaps. {'. '.join(near_misses[:2])}"
        else:
            explanation = f"Not eligible. {'. '.join(issues[:2])}"
        
        return explanation
    
    def _format_matching_output(self, user_id: int, matched_scholarships: List[Dict[str, Any]], matching_mode: str) -> str:
        """Format the matching results for output with categorization."""
        
        # Categorize scholarships by match type
        high_matches = [s for s in matched_scholarships if s.get("match_category") == "High Match"]
        medium_matches = [s for s in matched_scholarships if s.get("match_category") == "Medium Match"]
        low_matches = [s for s in matched_scholarships if s.get("match_category") == "Low Match"]
        near_matches = [s for s in matched_scholarships if s.get("match_category") == "Near Match"]
        
        # Categorize scholarships by type
        category_breakdown = {
            'Merit-Based': [],
            'Need-Based': [],
            'Major-Specific': [],
            'Demographic-Specific': [],
            'Essay Required': []
        }
        
        for scholarship in matched_scholarships:
            categories = scholarship.get('scholarship_categories', [])
            for category in categories:
                if category in category_breakdown:
                    category_breakdown[category].append(scholarship)
        
        output = f"""
SCHOLARSHIP MATCHING RESULTS FOR USER {user_id}
=============================================

Matching Mode: {matching_mode}
Total Scholarships Processed: {len(matched_scholarships)}

MATCH CATEGORIES:
- High Match: {len(high_matches)} scholarships
- Medium Match: {len(medium_matches)} scholarships  
- Low Match: {len(low_matches)} scholarships
- Near Match: {len(near_matches)} scholarships

SCHOLARSHIP TYPE BREAKDOWN:
- Merit-Based: {len(category_breakdown['Merit-Based'])} scholarships
- Need-Based: {len(category_breakdown['Need-Based'])} scholarships
- Major-Specific: {len(category_breakdown['Major-Specific'])} scholarships
- Demographic-Specific: {len(category_breakdown['Demographic-Specific'])} scholarships
- Essay Required: {len(category_breakdown['Essay Required'])} scholarships

DETAILED RESULTS:

High Matches ({len(high_matches)}):
"""
        
        for i, scholarship in enumerate(high_matches[:3], 1):  # Show top 3
            categories = ', '.join(scholarship.get('scholarship_categories', []))
            amount = scholarship.get('award_amount') or scholarship.get('amount', 'TBD')
            # Format amount safely (handle both numbers and strings)
            try:
                formatted_amount = f"${int(amount):,}" if str(amount).isdigit() else f"${amount}"
            except (ValueError, TypeError):
                formatted_amount = str(amount)
            renewable = " (Renewable)" if scholarship.get('renewable_flag') else ""
            output += f"""
{i}. {scholarship.get('name', 'Unknown Scholarship')}
   Amount: {formatted_amount}{renewable}
   Deadline: {scholarship.get('deadline', 'Not specified')}
   Categories: {categories}
   Match Score: {scholarship.get('match_score', 0)}%
   Why Match: {scholarship.get('why_match', 'N/A')}
"""
        
        if medium_matches:
            output += f"\nMedium Matches ({len(medium_matches)}):\n"
            for i, scholarship in enumerate(medium_matches[:2], 1):  # Show top 2
                categories = ', '.join(scholarship.get('scholarship_categories', []))
                amount = scholarship.get('award_amount') or scholarship.get('amount', 'TBD')
                # Format amount safely (handle both numbers and strings)
                try:
                    formatted_amount = f"${int(amount):,}" if str(amount).isdigit() else f"${amount}"
                except (ValueError, TypeError):
                    formatted_amount = str(amount)
                renewable = " (Renewable)" if scholarship.get('renewable_flag') else ""
                output += f"""
{i}. {scholarship.get('name', 'Unknown Scholarship')}
   Amount: {formatted_amount}{renewable}
   Deadline: {scholarship.get('deadline', 'Not specified')}
   Categories: {categories}
   Match Score: {scholarship.get('match_score', 0)}%
"""
        
        if near_matches:
            output += f"\nNear Matches ({len(near_matches)}) - Consider applying with additional qualifications:\n"
            for i, scholarship in enumerate(near_matches[:2], 1):  # Show top 2
                categories = ', '.join(scholarship.get('scholarship_categories', []))
                amount = scholarship.get('award_amount') or scholarship.get('amount', 'TBD')
                output += f"""
{i}. {scholarship.get('name', 'Unknown Scholarship')}
   Amount: ${amount:,}
   Deadline: {scholarship.get('deadline', 'Not specified')}
   Categories: {categories}
   Near Miss Reasons: {', '.join(scholarship.get('near_miss_reasons', []))}
"""
        
        # Add category-specific insights
        output += f"""

CATEGORY-SPECIFIC INSIGHTS:

Merit-Based Scholarships ({len(category_breakdown['Merit-Based'])}):
Focus on academic achievements, GPA improvements, and test scores.

Need-Based Scholarships ({len(category_breakdown['Need-Based'])}):
Ensure FAFSA completion and income documentation ready.

Major-Specific Scholarships ({len(category_breakdown['Major-Specific'])}):
Highlight relevant coursework and career goals in applications.

Demographic-Specific Scholarships ({len(category_breakdown['Demographic-Specific'])}):
Emphasize unique background and community involvement.

Essay Required Scholarships ({len(category_breakdown['Essay Required'])}):
Prepare compelling personal narratives and writing samples.

MATCHING SUMMARY:
- Advanced eligibility filtering applied
- Academic thresholds validated
- Major/field compatibility checked
- Financial need assessment performed
- Scholarship categorization completed
- Near-miss opportunities identified and saved
- Match categories and scores stored in database
- Results saved to scholarship_results.eligibility_summary (JSONB)
- Matched timestamps logged for refresh tracking

DATABASE STORAGE INCLUDES:
- match_category (High/Medium/Low/Near Match)
- match_score (percentage)
- near_miss_reasons (detailed explanations)
- eligibility_analysis (strengths, issues, near_miss_count)
- why_match (human-readable explanation)
- scholarship_categories (Merit-Based, Need-Based, etc.)

Note: All near-miss analysis is preserved in the eligibility_summary JSONB field
for future retrieval and detailed scholarship recommendation explanations.
"""
        
        return output

    def generate_scholarship_summary(self, scholarship_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate structured JSON summary for a scholarship that matches database schema.
        
        Args:
            scholarship_data: Raw scholarship data from search or other sources
            
        Returns:
            Dict with standardized scholarship summary matching scholarship_results table
        """
        
        # Extract basic info
        name = scholarship_data.get('name', 'Unknown Scholarship')
        description = scholarship_data.get('description', '')
        
        # Award amount - preserve text values like "Full-Tuition", convert numeric strings to integers
        award_amount = scholarship_data.get('amount') or scholarship_data.get('award_amount')
        if isinstance(award_amount, str):
            # Extract number from string like "$5,000" or "5000"
            import re
            amount_match = re.search(r'[\d,]+', str(award_amount).replace('$', '').replace(',', ''))
            if amount_match:
                award_amount = int(amount_match.group())
            # If no numeric value found, preserve the original string (e.g., "Full-Tuition", "Variable")
            # award_amount remains as the original string value
        
        # Deadline - normalize "Unknown Deadline" to None and ensure proper date format
        deadline = self._normalize_deadline(scholarship_data.get('deadline'))
        
        # Renewable flag
        renewable_flag = scholarship_data.get('renewable_flag', False) or \
                        scholarship_data.get('renewable', False) or \
                        'renewable' in description.lower()
        
        # Generate eligibility highlights
        eligibility_highlights = []
        
        if scholarship_data.get('min_gpa'):
            eligibility_highlights.append(f"Minimum GPA: {scholarship_data['min_gpa']}")
        
        if scholarship_data.get('eligible_majors'):
            majors = scholarship_data['eligible_majors'][:3]  # Limit to first 3
            eligibility_highlights.append(f"Majors: {', '.join(majors)}")
        
        if scholarship_data.get('demographic_requirements'):
            demographics = scholarship_data['demographic_requirements'][:2]  # Limit to first 2
            eligibility_highlights.append(f"Demographics: {', '.join(demographics)}")
        
        if scholarship_data.get('essay_required'):
            eligibility_highlights.append("Essay required")
        
        if scholarship_data.get('need_based'):
            eligibility_highlights.append("Financial need based")
        
        # Create eligibility summary as JSONB
        eligibility_summary = {
            "highlights": eligibility_highlights,
            "gpa_requirement": scholarship_data.get('min_gpa'),
            "major_restrictions": scholarship_data.get('eligible_majors', []),
            "demographic_requirements": scholarship_data.get('demographic_requirements', []),
            "essay_required": scholarship_data.get('essay_required', False),
            "need_based": scholarship_data.get('need_based', False)
        }
        
        # Get primary category
        categories = self._categorize_scholarship(scholarship_data)
        primary_category = categories[0] if categories else 'Merit-Based'
        
        # Generate short description (max 200 chars)
        short_description = description[:200] + "..." if len(description) > 200 else description
        
        # Return structured summary matching database schema
        return {
            "name": name,
            "category": primary_category,
            "award_amount": award_amount,
            "deadline": deadline,
            "renewable_flag": renewable_flag,
            "eligibility_summary": eligibility_summary,
            "short_description": short_description,
            "source_url": scholarship_data.get('source_url') or scholarship_data.get('application_url', '')
        }

    def _save_scholarships_to_database(self, user_id: int, matched_scholarships: List[Dict[str, Any]]) -> None:
        """
        Save matched scholarships to scholarship_results table with smart duplicate removal.
        
        Args:
            user_id: User ID for the scholarships
            matched_scholarships: List of matched scholarship data
        """
        
        if get_supabase is None:
            print("Warning: Cannot save to database - Supabase client not available")
            return
        
        try:
            supabase = get_supabase()
            
            # Step 1: Get ALL existing scholarships for this user
            existing_scholarships = supabase.table('scholarship_results').select('*').eq(
                'user_profile_id', user_id
            ).execute()
            
            # Step 2: Create a set of normalized names from existing scholarships
            existing_normalized_names = set()
            existing_by_normalized = {}
            
            for existing in existing_scholarships.data:
                normalized = self._normalize_scholarship_name(existing['name'])
                existing_normalized_names.add(normalized)
                if normalized not in existing_by_normalized:
                    existing_by_normalized[normalized] = []
                existing_by_normalized[normalized].append(existing)
            
            # Step 3: Prepare records for database insertion (filter out duplicates within new records too)
            records_to_insert = []
            new_normalized_names = set()
            
            for scholarship in matched_scholarships:
                # Enhanced eligibility_summary with all matching analysis
                enhanced_eligibility_summary = scholarship.get("eligibility_summary", {})
                
                # Add near-miss and matching analysis data
                enhanced_eligibility_summary.update({
                    "match_category": scholarship.get("match_category"),
                    "match_score": scholarship.get("match_score"),
                    "near_miss_reasons": scholarship.get("near_miss_reasons", []),
                    "eligibility_analysis": scholarship.get("eligibility_analysis", {}),
                    "why_match": scholarship.get("why_match", ""),
                    "scholarship_categories": scholarship.get("scholarship_categories", [])
                })
                
                # Normalize deadline - convert "Unknown Deadline" to None
                normalized_deadline = self._normalize_deadline(scholarship.get("deadline"))
                
                record = {
                    "user_profile_id": user_id,
                    "name": scholarship.get("name", "Unknown Scholarship"),
                    "category": scholarship.get("category"),
                    "award_amount": scholarship.get("award_amount"),
                    "deadline": normalized_deadline,  # Normalized to None if "Unknown Deadline" or invalid
                    "renewable_flag": scholarship.get("renewable_flag", False),
                    "eligibility_summary": enhanced_eligibility_summary,
                    "source_url": scholarship.get("source_url") or scholarship.get("application_url", "")
                }
                
                # Check for duplicates within new records
                normalized_name = self._normalize_scholarship_name(record['name'])
                print(f"DEBUG: Processing scholarship '{record['name']}' with normalized name '{normalized_name}'")
                
                if normalized_name not in new_normalized_names:
                    new_normalized_names.add(normalized_name)
                    records_to_insert.append(record)
                    print(f"DEBUG: Added to insertion list: '{record['name']}'")
                else:
                    print(f"Skipped duplicate within new records: '{record['name']}'")
            
            # Step 4: Delete existing duplicates before inserting new records
            for record in records_to_insert:
                normalized_name = self._normalize_scholarship_name(record['name'])
                print(f"DEBUG: Checking for existing duplicates of '{record['name']}' (normalized: '{normalized_name}')")
                
                if normalized_name in existing_by_normalized:
                    print(f"DEBUG: Found {len(existing_by_normalized[normalized_name])} existing duplicate(s)")
                    for existing in existing_by_normalized[normalized_name]:
                        supabase.table('scholarship_results').delete().eq(
                            'id', existing['id']
                        ).execute()
                        print(f"Deleted existing duplicate: '{existing['name']}' (id: {existing['id']})")
                else:
                    print(f"DEBUG: No existing duplicates found for '{record['name']}'")
            
            # Step 5: Insert all new records
            if records_to_insert:
                result = supabase.table('scholarship_results').insert(
                    records_to_insert
                ).execute()
                
                print(f"Saved {len(records_to_insert)} unique scholarships to database for user {user_id}")
            else:
                print(f"No new scholarships to save for user {user_id}")
                
        except Exception as e:
            print(f"Error saving scholarships to database: {str(e)}")

    def _normalize_scholarship_name(self, name: str) -> str:
        """
        Normalize scholarship names for better duplicate detection.
        Handles common variations in scholarship names.
        
        Args:
            name: Original scholarship name
            
        Returns:
            Normalized name for comparison
        """
        if not name:
            return ""
        
        # Convert to lowercase and strip whitespace
        normalized = name.lower().strip()
        
        # Remove common punctuation and extra spaces
        import re
        normalized = re.sub(r'[^\w\s]', '', normalized)  # Remove punctuation
        normalized = re.sub(r'\s+', ' ', normalized)     # Normalize spaces
        
        # Handle common name variations using pattern-based normalization
        # Remove all spaces for better matching (organizations often vary in spacing)
        normalized_compact = re.sub(r'\s+', '', normalized)
        
        # Handle common title variations automatically
        title_variations = [
            (r'\bcol\b', 'colonel'),           # Col. -> Colonel
            (r'\bdr\b', 'doctor'),             # Dr. -> Doctor  
            (r'\bprof\b', 'professor'),        # Prof. -> Professor
            (r'\bmr\b', 'mister'),             # Mr. -> Mister
            (r'\bms\b', 'miss'),               # Ms. -> Miss
            (r'\bmrs\b', 'missus'),            # Mrs. -> Missus
            (r'\bst\b', 'saint'),              # St. -> Saint
            (r'\buniv\b', 'university'),       # Univ. -> University
            (r'\bcoll\b', 'college'),          # Coll. -> College
        ]
        
        # Apply title normalizations
        for pattern, replacement in title_variations:
            normalized = re.sub(pattern, replacement, normalized)
            normalized_compact = re.sub(pattern, replacement, normalized_compact)
        
        # Use the more compact version for final comparison (no spaces)
        normalized = normalized_compact
        
        # Remove common words that don't add meaning for deduplication
        common_words = ['scholarship', 'award', 'grant', 'fellowship', 'program', 'foundation']
        for word in common_words:
            normalized = normalized.replace(f' {word}', '')
            normalized = normalized.replace(f'{word} ', '')
            if normalized == word:  # If the name is just the common word
                normalized = name.lower().strip()  # Keep original
                break
        
        return normalized.strip()

    def clean_expired_scholarships(self, user_id: int) -> str:
        """
        Remove scholarships with expired deadlines from database.
        Simple cleanup function - no complex refresh logic.
        
        Args:
            user_id: User ID to clean scholarships for
            
        Returns:
            Summary of cleanup actions taken
        """
        
        if get_supabase is None:
            return "Error: Supabase client not available for cleanup"
        
        try:
            supabase = get_supabase()
            current_date = date.today()
            
            # Get existing scholarships for user
            existing_scholarships = supabase.table('scholarship_results')\
                .select('*')\
                .eq('user_profile_id', user_id)\
                .execute()
            
            if not existing_scholarships.data:
                return f"No existing scholarships found for user {user_id}"
            
            expired_count = 0
            
            # Check each scholarship for expired deadlines
            for scholarship in existing_scholarships.data:
                deadline_str = scholarship.get('deadline')
                
                if deadline_str:
                    try:
                        from datetime import datetime
                        deadline_date = datetime.strptime(deadline_str, '%Y-%m-%d').date()
                        
                        # Delete if deadline has passed
                        if deadline_date < current_date:
                            supabase.table('scholarship_results')\
                                .delete()\
                                .eq('id', scholarship['id'])\
                                .execute()
                            expired_count += 1
                            
                    except ValueError:
                        # Invalid date format, skip
                        continue
            
            return f"Cleanup complete: {expired_count} expired scholarships removed"
            
        except Exception as e:
            return f"Error during cleanup: {str(e)}"

    def get_existing_scholarships(self, user_id: int, days_since_match: int = 7) -> List[Dict[str, Any]]:
        """
        Get existing scholarships for a user, optionally filtered by recency.
        
        Args:
            user_id: User ID to get scholarships for
            days_since_match: Only return scholarships matched within this many days
            
        Returns:
            List of existing scholarship records
        """
        
        if get_supabase is None:
            return []
        
        try:
            supabase = get_supabase()
            
            # Calculate cutoff date using UTC timezone
            from datetime import datetime, timedelta, timezone
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_since_match)
            
            # Get recent scholarships for user
            result = supabase.table('scholarship_results')\
                .select('*')\
                .eq('user_profile_id', user_id)\
                .gte('matched_at', cutoff_date.isoformat())\
                .order('matched_at', desc=True)\
                .execute()
            
            return result.data if result.data else []
            
        except Exception as e:
            print(f"Error retrieving existing scholarships: {str(e)}")
            return []

    def _extract_real_scholarship_data(self, scholarship: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract real scholarship data from website URLs using web scraping.
        
        Args:
            scholarship: Original scholarship data with URL
            
        Returns:
            Enhanced scholarship data with real website content
        """
        import requests
        from bs4 import BeautifulSoup
        import re
        
        enhanced_scholarship = scholarship.copy()
        source_url = scholarship.get('source_url') or scholarship.get('application_url')
        
        if not source_url:
            return enhanced_scholarship
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(source_url, timeout=15, headers=headers)
            if response.status_code != 200:
                return enhanced_scholarship
                
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract scholarship names from the page
            scholarship_names = self._extract_scholarship_names(soup)
            
            # Extract award amounts from the page
            award_amounts = self._extract_award_amounts(soup)
            
            # Extract deadlines from the page
            deadlines = self._extract_deadlines(soup)
            
            # If we found real data, update the scholarship
            if scholarship_names:
                # Use the first scholarship found on the page
                enhanced_scholarship['name'] = scholarship_names[0]
                enhanced_scholarship['extracted_from_website'] = True
                
            if award_amounts:
                # Use the first award amount found
                enhanced_scholarship['amount'] = award_amounts[0]
                enhanced_scholarship['award_amount'] = award_amounts[0]
                
            if deadlines:
                # Use the first deadline found
                enhanced_scholarship['deadline'] = deadlines[0]
                
            # Add source information
            enhanced_scholarship['content_source'] = 'extracted_from_website'
            enhanced_scholarship['extraction_url'] = source_url
            
        except Exception as e:
            # If extraction fails, keep original data
            enhanced_scholarship['extraction_error'] = str(e)
            enhanced_scholarship['content_source'] = 'original_agent_data'
            
        return enhanced_scholarship
    
    def _extract_scholarship_names(self, soup) -> List[str]:
        """Extract scholarship names from website content."""
        names = []
        
        # Look for common scholarship name patterns
        name_selectors = [
            'h1', 'h2', 'h3',  # Headers
            '.scholarship-title', '.title', '.name',  # Common CSS classes
            '[class*="scholarship"]', '[class*="title"]',  # Partial class matches
        ]
        
        for selector in name_selectors:
            elements = soup.select(selector)
            for element in elements:
                text = element.get_text(strip=True)
                # Filter for scholarship-like names
                if any(keyword in text.lower() for keyword in ['scholarship', 'grant', 'fellowship', 'award', 'prize']):
                    if len(text) > 10 and len(text) < 100:  # Reasonable length
                        names.append(text)
                        
        # Remove duplicates while preserving order
        return list(dict.fromkeys(names))[:5]  # Return top 5
    
    def _extract_award_amounts(self, soup) -> List[str]:
        """Extract award amounts from website content."""
        amounts = []
        
        # Look for dollar amounts in text
        text_content = soup.get_text()
        
        # Regex patterns for different amount formats
        amount_patterns = [
            r'\$[\d,]+(?:\.\d{2})?',  # $5,000 or $5,000.00
            r'USD?\s*[\d,]+',        # USD 5000
            r'[\d,]+\s*dollars?',    # 5000 dollars
            r'Up to \$[\d,]+',       # Up to $5,000
            r'Amount:\s*\$[\d,]+',   # Amount: $5,000
        ]
        
        for pattern in amount_patterns:
            matches = re.findall(pattern, text_content, re.IGNORECASE)
            for match in matches:
                # Clean up the amount
                cleaned_amount = re.sub(r'[^\d,]', '', match)
                if cleaned_amount and len(cleaned_amount) >= 3:  # At least $100
                    amounts.append(match.strip())
                    
        # Remove duplicates and return top 5
        return list(dict.fromkeys(amounts))[:5]
    
    def _extract_deadlines(self, soup) -> List[str]:
        """Extract deadlines from website content."""
        deadlines = []
        
        text_content = soup.get_text()
        
        # Regex patterns for dates
        date_patterns = [
            r'(?:deadline|due|apply by):?\s*([A-Za-z]+ \d{1,2},? \d{4})',  # December 1, 2025
            r'(?:deadline|due|apply by):?\s*(\d{1,2}/\d{1,2}/\d{4})',      # 12/01/2025
            r'(?:deadline|due|apply by):?\s*(\d{4}-\d{2}-\d{2})',          # 2025-12-01
            r'([A-Za-z]+ \d{1,2},? \d{4})',  # General date format
        ]
        
        for pattern in date_patterns:
            matches = re.findall(pattern, text_content, re.IGNORECASE)
            for match in matches:
                if isinstance(match, str) and len(match) > 6:
                    deadlines.append(match.strip())
                    
        # Filter for future dates and return top 3
        return list(dict.fromkeys(deadlines))[:3]

    def _validate_scholarship_data(self, scholarship: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate scholarship data quality including URLs and dates.
        
        Args:
            scholarship: Scholarship data to validate
            
        Returns:
            Dict with validation results and cleaned data
        """
        import requests
        
        validated_scholarship = scholarship.copy()
        validation_notes = []
        is_valid_url = False
        
        # Basic URL validation - just check if URL exists and looks valid
        source_url = scholarship.get('source_url') or scholarship.get('application_url')
        
        if source_url:
            if isinstance(source_url, str) and len(source_url) > 10 and ('http://' in source_url or 'https://' in source_url):
                is_valid_url = True
            else:
                validation_notes.append("Invalid URL format")
        else:
            validation_notes.append("No application URL provided")
        
        # Add validation status
        validated_scholarship['url_valid'] = is_valid_url
        validated_scholarship['has_valid_url'] = is_valid_url
        
        # Add validation notes to scholarship
        if validation_notes:
            if 'eligibility_summary' not in validated_scholarship:
                validated_scholarship['eligibility_summary'] = {}
            validated_scholarship['eligibility_summary']['validation_notes'] = validation_notes
        
        return validated_scholarship
    
    def _filter_active_scholarships(self, scholarships_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter out scholarships with expired deadlines.
        
        Args:
            scholarships_data: List of scholarship data
            
        Returns:
            List of scholarships with valid (future) deadlines
        """
        try:
            current_date = date.today()
            active_scholarships = []
            
            for scholarship in scholarships_data:
                # Normalize deadline - convert "Unknown Deadline" to None
                deadline_str = self._normalize_deadline(scholarship.get('deadline'))
                scholarship['deadline'] = deadline_str  # Update scholarship with normalized deadline
                
                if not deadline_str:
                    # If no deadline specified (or was "Unknown Deadline"), include but mark as unknown
                    scholarship['deadline_status'] = 'Unknown Deadline'
                    active_scholarships.append(scholarship)
                    continue
                
                try:
                    # Parse deadline (handle various formats)
                    if isinstance(deadline_str, str):
                        # Try different date formats
                        for date_format in ['%Y-%m-%d', '%m/%d/%Y', '%m-%d-%Y', '%Y/%m/%d']:
                            try:
                                deadline_date = datetime.strptime(deadline_str, date_format).date()
                                break
                            except ValueError:
                                continue
                        else:
                            # If no format worked, include with unknown status
                            scholarship['deadline_status'] = 'Unknown Deadline Format'
                            active_scholarships.append(scholarship)
                            continue
                    elif isinstance(deadline_str, date):
                        deadline_date = deadline_str
                    else:
                        scholarship['deadline_status'] = 'Unknown Deadline Format'
                        active_scholarships.append(scholarship)
                        continue
                    
                    # Check if deadline is in the future
                    if deadline_date > current_date:
                        scholarship['deadline_status'] = 'Active'
                        active_scholarships.append(scholarship)
                    else:
                        print(f"Filtered out expired scholarship: {scholarship.get('name', 'Unknown')} (deadline: {deadline_str})")
                        
                except Exception as e:
                    print(f"Error parsing deadline for scholarship {scholarship.get('name', 'Unknown')}: {str(e)}")
                    # Include scholarship with unknown status if deadline parsing fails
                    scholarship['deadline_status'] = 'Unknown Deadline Format'
                    active_scholarships.append(scholarship)
            
            print(f"Deadline filtering: {len(scholarships_data)} total -> {len(active_scholarships)} active scholarships")
            return active_scholarships
            
        except Exception as e:
            print(f"Error in deadline filtering: {str(e)}")
            # Return original list if filtering fails
            return scholarships_data