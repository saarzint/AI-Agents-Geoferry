"""
Scholarship Matcher Unit Tests - Simple Version
Tests scholarship matching logic with knowledge base data
"""

import sys
import os
import json

# Add the agents source directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents', 'src', 'agents', 'tools'))

from scholarship_matcher_tool import ScholarshipMatcherTool

class ScholarshipMatcherTest:
    def __init__(self):
        self.tool = ScholarshipMatcherTool()
        self.kb_scholarships = []
        self.test_results = []
        self.load_knowledge_base_data()
    
    def load_knowledge_base_data(self):
        """Load scholarship data from knowledge base"""
        knowledge_base_path = os.path.join(os.path.dirname(__file__), '..', 'agents', 'knowledge', 'scholarships.json')
        
        try:
            with open(knowledge_base_path, 'r') as f:
                data = json.load(f)
                self.kb_scholarships = data['scholarships']
                print(f"Loaded {len(self.kb_scholarships)} scholarships from knowledge base")
        except Exception as e:
            print(f"Failed to load knowledge base: {e}")
            self.kb_scholarships = []
    
    def convert_kb_scholarship_format(self, kb_scholarship):
        """Convert knowledge base scholarship to matcher tool format"""
        eligibility = kb_scholarship.get('eligibility_summary', '')
        min_gpa = None
        
        if 'minimum 3.0 gpa' in eligibility.lower():
            min_gpa = 3.0
        elif 'minimum 2.8 gpa' in eligibility.lower():
            min_gpa = 2.8
        elif 'minimum 2.5 gpa' in eligibility.lower():
            min_gpa = 2.5
        elif 'minimum 3.2 gpa' in eligibility.lower():
            min_gpa = 3.2
        elif 'minimum 3.5 gpa' in eligibility.lower():
            min_gpa = 3.5
        
        eligible_majors = []
        eligibility_lower = eligibility.lower()
        
        major_keywords = [
            'computer science', 'software engineering', 'information technology',
            'engineering', 'mathematics', 'physics', 'chemistry', 'biology',
            'environmental science', 'sustainability studies', 'environmental engineering',
            'business administration', 'economics', 'finance', 'marketing', 'management',
            'pre-med', 'nursing', 'public health', 'pharmacy', 'medical technology'
        ]
        
        for keyword in major_keywords:
            if keyword in eligibility_lower:
                eligible_majors.append(keyword)
        
        need_based = 'financial need' in eligibility_lower or 'family income' in eligibility_lower
        
        max_family_income = None
        if '$60,000' in eligibility:
            max_family_income = 60000
        elif '$80,000' in eligibility:
            max_family_income = 80000
        
        demographic_requirements = []
        if kb_scholarship['category'] == 'Demographic-Specific':
            if 'women' in kb_scholarship['name'].lower() or 'female' in eligibility_lower:
                demographic_requirements.extend(['women', 'female'])
            if 'first-generation' in eligibility_lower or 'first-gen' in eligibility_lower:
                demographic_requirements.extend(['first-generation', 'first-gen'])
        
        essay_required = 'essay' in eligibility_lower or kb_scholarship['category'] == 'Essay Required'
        
        return {
            'name': kb_scholarship['name'],
            'description': kb_scholarship['description'],
            'min_gpa': min_gpa,
            'eligible_majors': eligible_majors,
            'need_based': need_based,
            'max_family_income': max_family_income,
            'demographic_requirements': demographic_requirements,
            'location_restrictions': [],
            'amount': int(kb_scholarship['award_amount']),
            'deadline': kb_scholarship['deadline'],
            'source_url': kb_scholarship['source_url'],
            'essay_required': essay_required,
            'renewable_flag': kb_scholarship['renewable_flag'],
            'category': kb_scholarship['category']
        }
    
    def record_test_result(self, test_name, passed, details=""):
        """Record test result for final summary"""
        self.test_results.append({
            'name': test_name,
            'passed': passed,
            'details': details
        })
        status = "PASS" if passed else "FAIL"
        print(f"Test {len(self.test_results)}: {test_name} - {status}")
        if details:
            print(f"   Details: {details}")
    
    def test_1_knowledge_base_loading(self):
        """Test 1: Knowledge base data loading"""
        print("\n" + "="*50)
        print("TEST 1: Knowledge Base Loading")
        print("="*50)
        
        kb_loaded = len(self.kb_scholarships) > 0
        expected_min_scholarships = 5
        sufficient_data = len(self.kb_scholarships) >= expected_min_scholarships
        
        print(f"Scholarships loaded: {len(self.kb_scholarships)}")
        
        self.record_test_result(
            "Knowledge Base Loading", 
            kb_loaded and sufficient_data,
            f"Loaded {len(self.kb_scholarships)} scholarships (minimum {expected_min_scholarships} required)"
        )
        
        return kb_loaded and sufficient_data
    
    def test_2_basic_matching_functionality(self):
        """Test 2: Basic matching functionality"""
        print("\n" + "="*50)
        print("TEST 2: Basic Matching Functionality")
        print("="*50)
        
        if not self.kb_scholarships:
            self.record_test_result("Basic Matching", False, "No scholarships available")
            return False
        
        test_profile = {
            'gpa': 3.5,
            'intended_major': 'computer science',
            'budget': 25000,
            'financial_aid_eligibility': True,
            'preferences': {
                'state': 'California',
                'student_status': 'undergraduate'
            }
        }
        
        matches_found = 0
        total_scholarships = len(self.kb_scholarships)
        
        for kb_scholarship in self.kb_scholarships:
            scholarship = self.convert_kb_scholarship_format(kb_scholarship)
            result = self.tool._evaluate_scholarship_match(test_profile, scholarship)
            
            if result['match_score'] >= 70:
                matches_found += 1
        
        matching_works = matches_found > 0
        print(f"Scholarships tested: {total_scholarships}")
        print(f"Good matches found: {matches_found}")
        
        self.record_test_result(
            "Basic Matching", 
            matching_works,
            f"Found {matches_found} matches from {total_scholarships} scholarships"
        )
        
        return matching_works
    
    def test_3_merit_vs_need_based(self):
        """Test 3: Merit-based vs Need-based matching"""
        print("\n" + "="*50)
        print("TEST 3: Merit vs Need-Based Matching")
        print("="*50)
        
        merit_profile = {
            'gpa': 3.9,
            'intended_major': 'computer science',
            'budget': 50000,
            'financial_aid_eligibility': False,
            'preferences': {
                'state': 'California',
                'family_income': 120000,
                'student_status': 'undergraduate'
            }
        }
        
        need_profile = {
            'gpa': 3.1,
            'intended_major': 'engineering',
            'budget': 12000,
            'financial_aid_eligibility': True,
            'preferences': {
                'state': 'Texas',
                'family_income': 35000,
                'student_status': 'undergraduate'
            }
        }
        
        merit_matches = 0
        need_matches = 0
        
        for kb_scholarship in self.kb_scholarships:
            scholarship = self.convert_kb_scholarship_format(kb_scholarship)
            
            merit_result = self.tool._evaluate_scholarship_match(merit_profile, scholarship)
            if merit_result['match_score'] >= 70:
                merit_matches += 1
            
            need_result = self.tool._evaluate_scholarship_match(need_profile, scholarship)
            if need_result['match_score'] >= 70:
                need_matches += 1
        
        print(f"Merit profile matches: {merit_matches}")
        print(f"Need-based profile matches: {need_matches}")
        
        both_find_matches = merit_matches > 0 and need_matches > 0
        
        self.record_test_result(
            "Merit vs Need-Based", 
            both_find_matches,
            f"Merit: {merit_matches} matches, Need-based: {need_matches} matches"
        )
        
        return both_find_matches
    
    def test_4_renewable_flag_validation(self):
        """Test 4: Renewable flag validation"""
        print("\n" + "="*50)
        print("TEST 4: Renewable Flag Validation")
        print("="*50)
        
        renewable_count = 0
        onetime_count = 0
        
        for scholarship in self.kb_scholarships:
            if scholarship.get('renewable_flag', False):
                renewable_count += 1
            else:
                onetime_count += 1
        
        print(f"Renewable scholarships: {renewable_count}")
        print(f"One-time scholarships: {onetime_count}")
        
        has_diversity = renewable_count > 0 and onetime_count > 0
        
        self.record_test_result(
            "Renewable Flag Validation", 
            has_diversity,
            f"{renewable_count} renewable, {onetime_count} one-time scholarships"
        )
        
        return has_diversity
    
    def test_5_edge_case_handling(self):
        """Test 5: Edge case handling"""
        print("\n" + "="*50)
        print("TEST 5: Edge Case Handling")
        print("="*50)
        
        edge_cases = [
            {'name': 'Perfect GPA', 'gpa': 4.0, 'major': 'computer science', 'budget': 30000},
            {'name': 'Low GPA', 'gpa': 2.0, 'major': 'liberal arts', 'budget': 10000},
            {'name': 'High Budget', 'gpa': 3.3, 'major': 'business', 'budget': 200000},
            {'name': 'Low Budget', 'gpa': 3.1, 'major': 'social work', 'budget': 5000},
            {'name': 'Uncommon Major', 'gpa': 3.4, 'major': 'art history', 'budget': 25000}
        ]
        
        cases_with_matches = 0
        
        for case in edge_cases:
            profile = {
                'gpa': case['gpa'],
                'intended_major': case['major'],
                'budget': case['budget'],
                'financial_aid_eligibility': True,
                'preferences': {'state': 'California', 'student_status': 'undergraduate'}
            }
            
            matches = 0
            for kb_scholarship in self.kb_scholarships:
                scholarship = self.convert_kb_scholarship_format(kb_scholarship)
                result = self.tool._evaluate_scholarship_match(profile, scholarship)
                if result['match_score'] >= 70:
                    matches += 1
            
            print(f"{case['name']}: {matches} matches")
            if matches > 0:
                cases_with_matches += 1
        
        robust_handling = cases_with_matches >= (len(edge_cases) * 0.7)  # 70% should find matches
        
        self.record_test_result(
            "Edge Case Handling", 
            robust_handling,
            f"{cases_with_matches}/{len(edge_cases)} edge cases found matches"
        )
        
        return robust_handling
    
    def test_6_data_validation(self):
        """Test 6: Data validation and error handling"""
        print("\n" + "="*50)
        print("TEST 6: Data Validation")
        print("="*50)
        
        validation_cases = [
            {'name': 'Negative GPA', 'gpa': -1.0},
            {'name': 'High GPA', 'gpa': 5.0},
            {'name': 'None GPA', 'gpa': None},
            {'name': 'Zero Budget', 'budget': 0},
            {'name': 'Negative Budget', 'budget': -5000},
            {'name': 'None Budget', 'budget': None}
        ]
        
        valid_handled = 0
        
        for case in validation_cases:
            try:
                profile = {
                    'gpa': case.get('gpa', 3.5),
                    'intended_major': 'computer science',
                    'budget': case.get('budget', 25000),
                    'financial_aid_eligibility': True,
                    'preferences': {'state': 'California'}
                }
                
                if self.kb_scholarships:
                    scholarship = self.convert_kb_scholarship_format(self.kb_scholarships[0])
                    result = self.tool._evaluate_scholarship_match(profile, scholarship)
                    
                    if 0 <= result['match_score'] <= 100:
                        valid_handled += 1
                        print(f"{case['name']}: Handled correctly (Score: {result['match_score']:.1f}%)")
                    else:
                        print(f"{case['name']}: Invalid score range")
                
            except Exception as e:
                valid_handled += 1
                print(f"{case['name']}: Exception handled - {type(e).__name__}")
        
        validation_rate = valid_handled / len(validation_cases)
        validation_passed = validation_rate >= 0.8
        
        self.record_test_result(
            "Data Validation", 
            validation_passed,
            f"{valid_handled}/{len(validation_cases)} cases handled correctly ({validation_rate:.1%})"
        )
        
        return validation_passed
    
    def test_7_individual_methods(self):
        """Test 7: Individual method functionality"""
        print("\n" + "="*50)
        print("TEST 7: Individual Methods")
        print("="*50)
        
        if not self.kb_scholarships:
            self.record_test_result("Individual Methods", False, "No scholarships available")
            return False
        
        # Test categorization
        test_scholarship = self.kb_scholarships[0]
        categories = self.tool._categorize_scholarship(test_scholarship)
        expected_category = test_scholarship['category']
        categorization_works = expected_category in categories
        
        # Test summary generation
        summary = self.tool.generate_scholarship_summary(test_scholarship)
        required_fields = ['name', 'category', 'award_amount', 'deadline', 'renewable_flag']
        summary_works = all(field in summary for field in required_fields)
        
        # Test name normalization
        test_names = [
            "Global Tech Innovators Scholarship",
            "GLOBAL TECH INNOVATORS SCHOLARSHIP",
            "Global-Tech Innovators Scholarship"
        ]
        normalized = [self.tool._normalize_scholarship_name(name) for name in test_names]
        normalization_works = len(set(normalized)) == 1
        
        print(f"Categorization: {'PASS' if categorization_works else 'FAIL'}")
        print(f"Summary generation: {'PASS' if summary_works else 'FAIL'}")
        print(f"Name normalization: {'PASS' if normalization_works else 'FAIL'}")
        
        all_methods_work = categorization_works and summary_works and normalization_works
        
        self.record_test_result(
            "Individual Methods", 
            all_methods_work,
            f"Categorization: {categorization_works}, Summary: {summary_works}, Normalization: {normalization_works}"
        )
        
        return all_methods_work
    
    def run_all_tests(self):
        """Run all tests in order and provide final summary"""
        print("SCHOLARSHIP MATCHER UNIT TESTS")
        print("="*50)
        print(f"Testing with {len(self.kb_scholarships)} scholarships from knowledge base")
        
        # Run tests in order
        self.test_1_knowledge_base_loading()
        self.test_2_basic_matching_functionality()
        self.test_3_merit_vs_need_based()
        self.test_4_renewable_flag_validation()
        self.test_5_edge_case_handling()
        self.test_6_data_validation()
        self.test_7_individual_methods()
        
        # Final summary
        print("\n" + "="*50)
        print("FINAL TEST SUMMARY")
        print("="*50)
        
        total_tests = len(self.test_results)
        passed_tests = len([r for r in self.test_results if r['passed']])
        failed_tests = total_tests - passed_tests
        
        print(f"Total Tests Run: {total_tests}")
        print(f"Tests Passed: {passed_tests}")
        print(f"Tests Failed: {failed_tests}")
        print(f"Success Rate: {passed_tests}/{total_tests} ({(passed_tests/total_tests)*100:.1f}%)")
        
        if failed_tests > 0:
            print("\nFAILED TESTS:")
            for result in self.test_results:
                if not result['passed']:
                    print(f"  - {result['name']}: {result['details']}")
        
        overall_success = passed_tests == total_tests
        print(f"\nOVERALL RESULT: {'ALL TESTS PASSED' if overall_success else 'SOME TESTS FAILED'}")
        
        return overall_success

if __name__ == "__main__":
    tester = ScholarshipMatcherTest()
    tester.run_all_tests()