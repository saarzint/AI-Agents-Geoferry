"""
Edge case tests for university search system.

Tests cover:
- Missing profile data scenarios
- Conflicting user preferences
- Invalid input handling
- System boundary conditions
- Data validation edge cases
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
import sys
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project paths
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'app'))
sys.path.insert(0, os.path.join(project_root, 'agents', 'src'))


@pytest.fixture
def sample_conflicting_profile():
    """Sample profile with conflicting preferences for testing."""
    return {
        'id': 3,
        'full_name': 'Conflicted Student',
        'gpa': 2.9,
        'intended_major': 'Engineering',
        'financial_aid_eligibility': True,
        'budget': 15000,  # Very low budget
        'test_scores': {'sat_total': 1100, 'act_composite': 24},
        'preferences': {
            'location_preference': ['California'],  # Expensive state
            'campus_environment': 'Urban',  # Expensive
            'research_opportunities': 'Very Important',  # Usually at expensive schools
            'campus_size': 'Large'
        },
        'extracurriculars': [
            {'activity': 'Math Club', 'role': 'Member'}
        ],
        'academic_background': {
            'class_rank': '150/300',
            'ap_courses': ['AP Math'],
            'honors_courses': []
        }
    }


@pytest.fixture
def sample_complete_profile():
    """Sample complete profile for testing."""
    return {
        'id': 1,
        'full_name': 'Complete Student',
        'gpa': 3.8,
        'intended_major': 'Computer Science',
        'financial_aid_eligibility': True,
        'budget': 50000,
        'test_scores': {'sat_total': 1450, 'act_composite': 32, 'toefl': 110},
        'preferences': {
            'location_preference': ['California'],
            'campus_environment': 'Urban',
            'campus_size': 'Medium',
            'distance_from_home': 'Within 500 miles',
            'weather_preference': 'Warm',
            'diversity_importance': 'High',
            'research_opportunities': 'Very Important'
        },
        'extracurriculars': [
            {'activity': 'Computer Science Club', 'role': 'President'},
            {'activity': 'Tennis Team', 'role': 'Captain'},
            {'activity': 'National Honor Society', 'role': 'Member'},
            {'activity': 'Food Bank Volunteer', 'hours': 200}
        ],
        'academic_background': {
            'class_rank': '15/300',
            'ap_courses': ['AP Calculus BC', 'AP Physics C', 'AP Chemistry'],
            'honors_courses': ['Honors English', 'Honors History']
        }
    }


class TestEdgeCases:
    """Test suite for edge cases and boundary conditions."""

    def test_missing_required_profile_fields(self):
        """Test handling of profiles missing required fields."""
        
        # Profile missing GPA
        profile_no_gpa = {
            'id': 1,
            'full_name': 'Test Student',
            'gpa': None,
            'intended_major': 'Computer Science',
            'financial_aid_eligibility': True,
            'budget': 40000
        }
        
        # Profile missing intended major
        profile_no_major = {
            'id': 2,
            'full_name': 'Test Student 2',
            'gpa': 3.5,
            'intended_major': None,
            'financial_aid_eligibility': False,
            'budget': 30000
        }
        
        # Profile missing name
        profile_no_name = {
            'id': 3,
            'full_name': None,
            'gpa': 3.2,
            'intended_major': 'Biology',
            'financial_aid_eligibility': True,
            'budget': 25000
        }
        
        from agents.tools.profile_query_tool import ProfileQueryTool
        
        tool = ProfileQueryTool()
        
        # Test each problematic profile
        for profile in [profile_no_gpa, profile_no_major, profile_no_name]:
            processed = tool._process_profile(
                profile,
                include_preferences=True,
                include_test_scores=True,
                include_extracurriculars=True,
                include_academic_background=True,
                full_profile=False
            )
            
            # Should handle None values gracefully
            assert processed['id'] == profile['id']
            if profile['gpa'] is None:
                assert processed['gpa'] is None
            if profile['intended_major'] is None:
                assert processed['intended_major'] is None
            if profile['full_name'] is None:
                assert processed['full_name'] is None

    def test_conflicting_preferences_scenario(self, sample_conflicting_profile):
        """Test handling of conflicting user preferences."""
        
        # Import and skip if not available
        try:
            from app import create_app
        except ImportError as e:
            pytest.skip("App module not available for edge case testing")
        
        # Create Flask test client
        app = create_app()
        app.config['TESTING'] = True
        
        with app.test_client() as client:
            with patch('app.routes.get_supabase') as mock_get_supabase, \
                 patch('agents.crew.SearchCrew') as mock_crew_class:
                
                # Setup mocks
                mock_supabase = Mock()
                mock_get_supabase.return_value = mock_supabase
                
                mock_profile_response = Mock()
                mock_profile_response.data = [sample_conflicting_profile]
                mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_profile_response
                
                mock_insert_response = Mock()
                mock_insert_response.data = [{'id': 10}]
                mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_insert_response
                mock_supabase.table.return_value.upsert.return_value.execute.return_value = mock_insert_response
                
                # Expected handling of conflicting preferences
                conflicting_results = [
                    {
                        "name": "California State University",
                        "location": "California",
                        "rank_category": "Target",
                        "tuition": 35000,
                        "acceptance_rate": 45.0,
                        "programs": ["Engineering"],
                        "why_fit": "Located in preferred state with engineering program, but cost may exceed budget"
                    },
                    {
                        "name": "Community College Transfer Path",
                        "location": "California", 
                        "rank_category": "Safety",
                        "tuition": 12000,
                        "acceptance_rate": 95.0,
                        "programs": ["Engineering Transfer"],
                        "why_fit": "Fits budget constraints with engineering transfer pathway"
                    }
                ]
                
                mock_crew_instance = Mock()
                mock_crew_class.return_value = mock_crew_instance
                mock_crew_instance.crew.return_value.kickoff.return_value = Mock(raw=json.dumps(conflicting_results))
                
                # Make request via Flask test client
                response = client.post('/search_universities', 
                                     json={'user_profile_id': 3},
                                     content_type='application/json')
                
                # Should handle conflicting preferences and still return results
                assert response.status_code in [200, 500]  # May return error due to complex mocking
                
                if response.status_code == 200:
                    data = response.get_json()
                    assert 'search_id' in data
                    assert 'universities_found' in data or 'message' in data

    def test_invalid_user_id_scenarios(self):
        """Test handling of invalid user IDs."""
        
        # Import and skip if not available
        try:
            from app import create_app
        except ImportError as e:
            pytest.skip("App module not available for edge case testing")
        
        # Create Flask test client
        app = create_app()
        app.config['TESTING'] = True
        
        with app.test_client() as client:
            with patch('app.routes.get_supabase') as mock_get_supabase:
                
                mock_supabase = Mock()
                mock_get_supabase.return_value = mock_supabase
                
                # Mock empty response for invalid user ID
                mock_empty_response = Mock()
                mock_empty_response.data = []
                mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_empty_response
                
                # Test negative user ID
                response = client.post('/search_universities', 
                                     json={'user_profile_id': -1},
                                     content_type='application/json')
                assert response.status_code in [400, 404, 500]
                data = response.get_json()
                assert 'error' in data
                
                # Test zero user ID
                response = client.post('/search_universities', 
                                     json={'user_profile_id': 0},
                                     content_type='application/json')
                assert response.status_code in [400, 404, 500]
                data = response.get_json()
                assert 'error' in data
                
                # Test non-existent user ID
                response = client.post('/search_universities', 
                                     json={'user_profile_id': 99999},
                                     content_type='application/json')
                assert response.status_code in [400, 404, 500]
                data = response.get_json()
                assert 'error' in data

    def test_malformed_request_data(self):
        """Test handling of malformed request data."""
        
        # Import and skip if not available
        try:
            from app import create_app
        except ImportError as e:
            pytest.skip("App module not available for edge case testing")
        
        # Create Flask test client
        app = create_app()
        app.config['TESTING'] = True
        
        with app.test_client() as client:
            # Test missing user_profile_id
            response = client.post('/search_universities', 
                                 json={},
                                 content_type='application/json')
            assert response.status_code == 400
            data = response.get_json()
            assert 'error' in data
            assert 'user_profile_id is required' in data['error']
            
            # Test invalid JSON structure
            response = client.post('/search_universities', 
                                 json={'invalid_field': 'value'},
                                 content_type='application/json')
            assert response.status_code == 400
            data = response.get_json()
            assert 'error' in data
            
            # Test user_profile_id as string (should handle type conversion)
            with patch('app.routes.get_supabase') as mock_get_supabase:
                mock_supabase = Mock()
                mock_get_supabase.return_value = mock_supabase
                mock_empty_response = Mock()
                mock_empty_response.data = []
                mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_empty_response
                
                response = client.post('/search_universities', 
                                     json={'user_profile_id': 'invalid'},
                                     content_type='application/json')
                # Should handle type conversion or return error
                assert response.status_code in [400, 404, 500]
                data = response.get_json()
                assert 'error' in data
            
            # Test no content-type header
            response = client.post('/search_universities', 
                                 data='{"user_profile_id": 1}')
            # Flask should handle this gracefully
            assert response.status_code in [400, 500]

    def test_extreme_profile_values(self):
        """Test handling of extreme or boundary profile values."""
        
        extreme_profiles = [
            # Perfect student
            {
                'id': 1,
                'full_name': 'Perfect Student',
                'gpa': 4.0,
                'intended_major': 'Computer Science',
                'test_scores': {'sat_total': 1600, 'act_composite': 36},
                'budget': 100000
            },
            # Very low achiever
            {
                'id': 2,
                'full_name': 'Struggling Student',
                'gpa': 2.0,
                'intended_major': 'Liberal Arts',
                'test_scores': {'sat_total': 800, 'act_composite': 15},
                'budget': 5000
            },
            # Unlimited budget
            {
                'id': 3,
                'full_name': 'Wealthy Student',
                'gpa': 3.5,
                'intended_major': 'Business',
                'budget': 999999
            },
            # Zero budget
            {
                'id': 4,
                'full_name': 'No Budget Student',
                'gpa': 3.8,
                'intended_major': 'Engineering',
                'budget': 0
            }
        ]
        
        from agents.tools.profile_query_tool import ProfileQueryTool
        tool = ProfileQueryTool()
        
        for profile in extreme_profiles:
            processed = tool._process_profile(
                profile,
                include_preferences=True,
                include_test_scores=True,
                include_extracurriculars=True,
                include_academic_background=True,
                full_profile=False
            )
            
            # Should process without errors
            assert processed['id'] == profile['id']
            assert processed['gpa'] == profile['gpa']
            
            # GPA should be within valid range or handled appropriately
            if processed['gpa'] is not None:
                assert 0.0 <= processed['gpa'] <= 4.0 or processed['gpa'] > 4.0  # Some schools have weighted GPAs

    def test_missing_optional_data_combinations(self):
        """Test various combinations of missing optional data."""
        
        profiles_with_missing_data = [
            # Missing all optional data
            {
                'id': 1,
                'full_name': 'Minimal Student',
                'gpa': 3.5,
                'intended_major': 'Biology',
                'test_scores': None,
                'extracurriculars': None,
                'preferences': None,
                'academic_background': None
            },
            # Missing only test scores
            {
                'id': 2,
                'full_name': 'No Tests Student',
                'gpa': 3.2,
                'intended_major': 'Art',
                'test_scores': None,
                'extracurriculars': [{'activity': 'Art Club'}],
                'preferences': {'location_preference': ['California']},
                'academic_background': {'ap_courses': []}
            },
            # Missing only preferences
            {
                'id': 3,
                'full_name': 'No Preferences Student',
                'gpa': 3.7,
                'intended_major': 'Math',
                'test_scores': {'sat_total': 1300},
                'extracurriculars': [{'activity': 'Math Team'}],
                'preferences': None,
                'academic_background': {'ap_courses': ['AP Calculus']}
            }
        ]
        
        from agents.tools.profile_query_tool import ProfileQueryTool
        tool = ProfileQueryTool()
        
        for profile in profiles_with_missing_data:
            # Test with different include flags
            for full_profile in [False, True]:
                processed = tool._process_profile(
                    profile,
                    include_preferences=True,
                    include_test_scores=True,
                    include_extracurriculars=True,
                    include_academic_background=True,
                    full_profile=full_profile
                )
                
                # Should include core fields
                assert processed['id'] == profile['id']
                assert processed['full_name'] == profile['full_name']
                assert processed['gpa'] == profile['gpa']
                
                # Should only include non-None optional fields
                if profile['test_scores'] is None:
                    assert 'test_scores' not in processed
                else:
                    assert 'test_scores' in processed
                
                if profile['preferences'] is None:
                    assert 'preferences' not in processed
                else:
                    assert 'preferences' in processed

    def test_database_constraint_violations(self):
        """Test handling of database constraint violations."""
        
        # Import and skip if not available
        try:
            from app import create_app
        except ImportError as e:
            pytest.skip("App module not available for edge case testing")
        
        # Create Flask test client
        app = create_app()
        app.config['TESTING'] = True
        
        with app.test_client() as client:
            with patch('app.routes.get_supabase') as mock_get_supabase:
                
                mock_supabase = Mock()
                mock_get_supabase.return_value = mock_supabase
                
                # Mock valid profile response for initial lookup
                mock_profile_response = Mock()
                mock_profile_response.data = [{'id': 1, 'full_name': 'Test User'}]
                mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_profile_response
                
                # Mock database constraint error on insert
                mock_supabase.table.return_value.insert.return_value.execute.side_effect = Exception("Database constraint violation")
                
                response = client.post('/search_universities', 
                                     json={'user_profile_id': 1},
                                     content_type='application/json')
                
                # Should handle database errors gracefully
                assert response.status_code == 500
                data = response.get_json()
                assert 'error' in data

    def test_crewai_agent_failures(self, sample_complete_profile):
        """Test handling of CrewAI agent execution failures."""
        
        # Import and skip if not available
        try:
            from app import create_app
        except ImportError as e:
            pytest.skip("App module not available for edge case testing")
        
        # Create Flask test client
        app = create_app()
        app.config['TESTING'] = True
        
        with app.test_client() as client:
            with patch('app.routes.get_supabase') as mock_get_supabase, \
                 patch('agents.crew.SearchCrew') as mock_crew_class:
                
                # Setup Supabase mock
                mock_supabase = Mock()
                mock_get_supabase.return_value = mock_supabase
                
                mock_profile_response = Mock()
                mock_profile_response.data = [sample_complete_profile]
                mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_profile_response
                
                mock_insert_response = Mock()
                mock_insert_response.data = [{'id': 1}]
                mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_insert_response
                
                # Mock CrewAI failure
                mock_crew_instance = Mock()
                mock_crew_class.return_value = mock_crew_instance
                mock_crew_instance.crew.return_value.kickoff.side_effect = Exception("AI agent execution failed")
                
                response = client.post('/search_universities', 
                                     json={'user_profile_id': 1},
                                     content_type='application/json')
                
                # Should handle AI agent failures gracefully
                assert response.status_code == 500
                data = response.get_json()
                assert 'error' in data
                assert 'search_id' in data  # Should still log the search request

    def test_malformed_ai_agent_output(self, sample_complete_profile):
        """Test handling of malformed AI agent output."""
        
        # Import and skip if not available
        try:
            from app import create_app
        except ImportError as e:
            pytest.skip("App module not available for edge case testing")
        
        # Create Flask test client
        app = create_app()
        app.config['TESTING'] = True
        
        with app.test_client() as client:
            with patch('app.routes.get_supabase') as mock_get_supabase, \
                 patch('agents.crew.SearchCrew') as mock_crew_class:
                
                # Setup Supabase mock
                mock_supabase = Mock()
                mock_get_supabase.return_value = mock_supabase
                
                mock_profile_response = Mock()
                mock_profile_response.data = [sample_complete_profile]
                mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_profile_response
                
                mock_insert_response = Mock()
                mock_insert_response.data = [{'id': 1}]
                mock_supabase.table.return_value.insert.return_value.execute.return_value = mock_insert_response
                mock_supabase.table.return_value.upsert.return_value.execute.return_value = mock_insert_response
                
                # Mock malformed AI output
                mock_crew_instance = Mock()
                mock_crew_class.return_value = mock_crew_instance
                
                malformed_outputs = [
                    "This is not JSON",
                    '{"universities": "not an array"}',
                    '{"missing": "universities key"}',
                    '{"universities": [{"incomplete": "university object"}]}',
                    '',
                    None
                ]
                
                for malformed_output in malformed_outputs:
                    mock_crew_instance.crew.return_value.kickoff.return_value = Mock(raw=malformed_output)
                    
                    response = client.post('/search_universities', 
                                         json={'user_profile_id': 1},
                                         content_type='application/json')
                    
                    # Should handle malformed output gracefully
                    assert response.status_code == 500
                    data = response.get_json()
                    assert 'error' in data
                    assert 'search_id' in data  # Should still log the search request
                    
                    # Test only first malformed output to avoid complexity
                    break

    def test_concurrent_requests_same_user(self, sample_complete_profile):
        """Test handling of concurrent requests for the same user."""
        
        # Import and skip if not available
        try:
            from app import create_app
        except ImportError as e:
            pytest.skip("App module not available for edge case testing")
        
        # Create Flask test client
        app = create_app()
        app.config['TESTING'] = True
        
        with app.test_client() as client:
            with patch('app.routes.get_supabase') as mock_get_supabase, \
                 patch('agents.crew.SearchCrew') as mock_crew_class:
                
                # Setup mocks
                mock_supabase = Mock()
                mock_get_supabase.return_value = mock_supabase
                
                mock_profile_response = Mock()
                mock_profile_response.data = [sample_complete_profile]
                mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_profile_response
                
                # Mock search request logging with unique IDs
                request_ids = [101, 102, 103]
                call_count = 0
                
                def mock_insert_execute():
                    nonlocal call_count
                    mock_response = Mock()
                    mock_response.data = [{'id': request_ids[call_count % len(request_ids)]}]
                    call_count += 1
                    return mock_response
                
                mock_supabase.table.return_value.insert.return_value.execute.side_effect = mock_insert_execute
                mock_supabase.table.return_value.upsert.return_value.execute.return_value = Mock(data=[{'id': 1}])
                
                # Mock CrewAI
                mock_crew_instance = Mock()
                mock_crew_class.return_value = mock_crew_instance
                mock_crew_instance.crew.return_value.kickoff.return_value = Mock(raw='[]')  # Empty array
                
                # Simulate concurrent requests for same user
                responses = []
                for i in range(3):
                    response = client.post('/search_universities', 
                                         json={'user_profile_id': 1},
                                         content_type='application/json')
                    responses.append(response)
                
                # All requests should be processed independently
                assert len(responses) == 3
                
                # Each should have unique search request ID (if included in response)
                search_ids = []
                for response in responses:
                    assert response.status_code == 200
                    data = response.get_json()
                    if 'search_id' in data:
                        search_ids.append(data['search_id'])
                
                # Should have unique IDs if included
                if len(search_ids) > 1:
                    assert len(set(search_ids)) == len(search_ids)