"""
Integration tests for the complete university search system.

Tests cover:
- End-to-end university search workflow
- Flask API integration with CrewAI agents
- Database logging and result storage
- Sample student profile scenarios
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
import sys
import os
from dotenv import load_dotenv

# Load environment variables before imports
load_dotenv()

# Add project paths
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'app'))
sys.path.insert(0, os.path.join(project_root, 'agents', 'src'))


class TestIntegrationWorkflow:
    """Integration tests for complete university search workflow."""

    def test_complete_university_search_workflow(self):
        """Test complete workflow from profile query to university recommendations."""
        
        # Import and skip if not available
        try:
            from app import create_app
            print("Successfully imported app module")
        except ImportError as e:
            print(f"Import error: {e}")
            pytest.skip("App module not available for integration testing")
        
        # Create Flask test client
        app = create_app()
        app.config['TESTING'] = True
        
        with app.test_client() as client:
            # Test the actual workflow with real user profile ID
            # This should: 
            # 1. Get user profile from Supabase (user_profile_id=1)
            # 2. Run CrewAI to search for universities
            # 3. Store search request in Supabase
            # 4. Store university results in Supabase
            # 5. Return the results
            
            response = client.post('/search_universities', 
                                 json={'user_profile_id': 1},
                                 content_type='application/json')
            
            # Debug: Print response details
            print(f"Response status: {response.status_code}")
            print(f"Response data: {response.get_data(as_text=True)}")
            
            # Verify the response
            assert response.status_code == 200
            data = response.get_json()
            
            # Check the actual response structure from the routes
            assert 'search_id' in data
            assert 'message' in data
            assert 'universities_found' in data
            
            # Verify search was logged and universities were found
            assert data['universities_found'] > 0
            assert data['search_id'] is not None

    def test_university_search_with_different_profile(self):
        """Test university search with different user profile."""
        
        # Import and skip if not available
        try:
            from app import create_app
        except ImportError:
            pytest.skip("App module not available for integration testing")
        
        # Create Flask test client
        app = create_app()
        app.config['TESTING'] = True
        
        with app.test_client() as client:
            # Test with different profile ID
            response = client.post('/search_universities', 
                                 json={'user_profile_id': 3},
                                 content_type='application/json')
            
            print(f"Response status: {response.status_code}")
            print(f"Response data: {response.get_data(as_text=True)}")
            
            # Should either succeed or return appropriate error
            if response.status_code == 200:
                data = response.get_json()
                assert 'search_id' in data
                assert 'universities_found' in data
            elif response.status_code == 404:
                # User profile not found
                data = response.get_json()
                assert 'error' in data
            else:
                # Some other error occurred
                assert response.status_code >= 400

    def test_invalid_user_profile_id(self):
        """Test handling of invalid user profile ID."""
        
        # Import and skip if not available
        try:
            from app import create_app
        except ImportError:
            pytest.skip("App module not available for integration testing")
        
        # Create Flask test client
        app = create_app()
        app.config['TESTING'] = True
        
        with app.test_client() as client:
            # Test with invalid/non-existent user ID
            response = client.post('/search_universities', 
                                 json={'user_profile_id': 99999},
                                 content_type='application/json')
            
            print(f"Response status: {response.status_code}")
            print(f"Response data: {response.get_data(as_text=True)}")
            
            # Should return 404 or error response for non-existent user
            assert response.status_code == 404 or response.status_code >= 400
            if response.status_code == 404:
                data = response.get_json()
                assert 'error' in data

    def test_missing_request_data(self):
        """Test handling of missing request data."""
        
        # Import and skip if not available
        try:
            from app import create_app
        except ImportError:
            pytest.skip("App module not available for integration testing")
        
        # Create Flask test client
        app = create_app()
        app.config['TESTING'] = True
        
        with app.test_client() as client:
            # Test with missing user_profile_id
            response = client.post('/search_universities', 
                                 json={},  # Empty JSON
                                 content_type='application/json')
            
            print(f"Response status: {response.status_code}")
            print(f"Response data: {response.get_data(as_text=True)}")
            
            # Should return 400 Bad Request for missing required data
            assert response.status_code >= 400

    def test_results_endpoint_access(self):
        """Test accessing results endpoint after search."""
        
        # Import and skip if not available
        try:
            from app import create_app
        except ImportError:
            pytest.skip("App module not available for integration testing")
        
        # Create Flask test client
        app = create_app()
        app.config['TESTING'] = True
        
        with app.test_client() as client:
            # First perform a search
            search_response = client.post('/search_universities', 
                                        json={'user_profile_id': 1},
                                        content_type='application/json')
            
            if search_response.status_code == 200:
                search_data = search_response.get_json()
                search_id = search_data.get('search_id')
                
                if search_id:
                    # Now test accessing the results
                    results_response = client.get(f'/results/{search_id}')
                    
                    print(f"Results response status: {results_response.status_code}")
                    print(f"Results response data: {results_response.get_data(as_text=True)}")
                    
                    # Results endpoint should return 200 or 404 (if not implemented)
                    assert results_response.status_code in [200, 404]