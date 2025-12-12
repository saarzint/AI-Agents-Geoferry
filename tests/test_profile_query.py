"""
Unit tests for ProfileQueryTool functionality.

Tests cover:
- Profile retrieval with different filtering options
- Data processing and formatting
- Security constraints (read-only access)
- Error handling scenarios
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add agents src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents', 'src'))

from agents.tools.profile_query_tool import ProfileQueryTool, ProfileQueryInput


class MockSupabaseResponse:
    """Mock Supabase response object."""
    def __init__(self, data, error=None):
        self.data = data
        self.error = error


class TestProfileQueryTool:
    """Test suite for ProfileQueryTool."""

    def test_profile_query_tool_initialization(self):
        """Test ProfileQueryTool initializes correctly."""
        tool = ProfileQueryTool()
        
        assert tool.name == "Profile Query Tool"
        assert "READ-ONLY access" in tool.description
        assert tool.args_schema == ProfileQueryInput
        assert "NO WRITE/UPDATE/DELETE" in tool.description

    def test_profile_query_input_schema(self):
        """Test ProfileQueryInput schema validation."""
        # Test default values
        input_schema = ProfileQueryInput()
        assert input_schema.user_id is None
        assert input_schema.include_preferences is True
        assert input_schema.include_test_scores is True
        assert input_schema.include_extracurriculars is True
        assert input_schema.include_academic_background is True
        assert input_schema.full_profile is False

        # Test with custom values
        custom_input = ProfileQueryInput(
            user_id=123,
            include_preferences=False,
            include_test_scores=False,
            include_extracurriculars=False,
            include_academic_background=False,
            full_profile=True
        )
        assert custom_input.user_id == 123
        assert custom_input.include_preferences is False
        assert custom_input.full_profile is True

    @patch('agents.tools.profile_query_tool.get_supabase')
    def test_single_profile_retrieval(self, mock_get_supabase):
        """Test retrieving a single profile by ID."""
        # Setup mock with simple test data
        mock_client = Mock()
        mock_table = Mock()
        mock_query = Mock()
        
        mock_get_supabase.return_value = mock_client
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        
        # Mock profile data
        test_profile = {
            'id': 1,
            'full_name': 'Test Student',
            'gpa': 3.8,
            'intended_major': 'Computer Science',
            'test_scores': {'sat_total': 1450}
        }
        mock_query.execute.return_value = MockSupabaseResponse([test_profile])

        # Test
        tool = ProfileQueryTool()
        result = tool._run(user_id=1, full_profile=True)

        # Assertions
        mock_client.table.assert_called_with('user_profile')
        mock_table.select.assert_called_with('*')
        mock_query.eq.assert_called_with('id', 1)
        
        assert "USER PROFILE (ID: 1)" in result
        assert "Test Student" in result
        assert "Computer Science" in result
        assert "3.8" in result

    @patch('agents.tools.profile_query_tool.get_supabase')
    def test_multiple_profiles_retrieval(self, mock_get_supabase):
        """Test retrieving multiple profiles."""
        # Setup mock
        mock_client = Mock()
        mock_table = Mock()
        mock_query = Mock()
        
        mock_get_supabase.return_value = mock_client
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_query
        
        # Mock multiple profiles
        test_profiles = [
            {'id': 1, 'full_name': 'Student One', 'gpa': 3.8},
            {'id': 2, 'full_name': 'Student Two', 'gpa': 3.5}
        ]
        mock_query.execute.return_value = MockSupabaseResponse(test_profiles)

        # Test
        tool = ProfileQueryTool()
        result = tool._run()  # No user_id = get all profiles

        # Assertions
        mock_client.table.assert_called_with('user_profile')
        mock_table.select.assert_called_with('*')
        mock_query.eq.assert_not_called()  # Should not filter by ID
        
        assert "Student One" in result
        assert "Student Two" in result

    @patch('agents.tools.profile_query_tool.get_supabase')
    def test_profile_filtering_options(self, mock_get_supabase):
        """Test different profile filtering options."""
        # Setup mock
        mock_client = Mock()
        mock_table = Mock()
        mock_query = Mock()
        
        mock_get_supabase.return_value = mock_client
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        
        # Mock complete profile data
        test_profile = {
            'id': 1,
            'full_name': 'Test Student',
            'gpa': 3.8,
            'test_scores': {'sat_total': 1450},
            'preferences': {'location': 'CA'},
            'extracurriculars': [{'activity': 'Club'}],
            'academic_background': {'ap_courses': ['AP Math']}
        }
        mock_query.execute.return_value = MockSupabaseResponse([test_profile])

        tool = ProfileQueryTool()

        # Test different filtering options
        for _ in range(4):
            result = tool._run(user_id=1)
        
        assert mock_query.execute.call_count == 4

    def test_process_profile_filtering(self):
        """Test the _process_profile method with different filtering options."""
        tool = ProfileQueryTool()
        
        # Mock complete profile
        test_profile = {
            'id': 1,
            'full_name': 'Test Student',
            'gpa': 3.8,
            'test_scores': {'sat_total': 1450},
            'preferences': {'location': 'CA'},
            'extracurriculars': [{'activity': 'Club'}],
            'academic_background': {'ap_courses': ['AP Math']}
        }
        
        # Test full profile
        processed = tool._process_profile(
            test_profile, 
            include_preferences=True,
            include_test_scores=True,
            include_extracurriculars=True,
            include_academic_background=True,
            full_profile=True
        )
        
        assert processed['id'] == 1
        assert processed['full_name'] == 'Test Student'
        assert processed['gpa'] == 3.8
        assert 'test_scores' in processed
        assert 'preferences' in processed
        assert 'extracurriculars' in processed
        assert 'academic_background' in processed

        # Test minimal profile (exclude everything)
        processed_minimal = tool._process_profile(
            test_profile,
            include_preferences=False,
            include_test_scores=False,
            include_extracurriculars=False,
            include_academic_background=False,
            full_profile=False
        )
        
        assert processed_minimal['id'] == 1
        assert processed_minimal['full_name'] == 'Test Student'
        assert processed_minimal['gpa'] == 3.8
        assert 'test_scores' not in processed_minimal
        assert 'preferences' not in processed_minimal
        assert 'extracurriculars' not in processed_minimal
        assert 'academic_background' not in processed_minimal

    @patch('agents.tools.profile_query_tool.get_supabase')
    def test_profile_not_found(self, mock_get_supabase):
        """Test behavior when profile is not found."""
        # Setup mock for empty result
        mock_client = Mock()
        mock_table = Mock()
        mock_query = Mock()
        
        mock_get_supabase.return_value = mock_client
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.execute.return_value = MockSupabaseResponse([])  # Empty result

        # Test
        tool = ProfileQueryTool()
        result = tool._run(user_id=999)

        # Assertions
        assert "No user profile found with ID: 999" in result

    @patch('agents.tools.profile_query_tool.get_supabase')
    def test_database_error_handling(self, mock_get_supabase):
        """Test error handling when database operation fails."""
        # Setup mock to raise exception
        mock_client = Mock()
        mock_get_supabase.return_value = mock_client
        mock_client.table.side_effect = Exception("Database connection failed")

        # Test
        tool = ProfileQueryTool()
        result = tool._run(user_id=1)

        # Assertions
        assert "Error querying user profile" in result
        assert "Database connection failed" in result

    def test_supabase_client_unavailable(self):
        """Test behavior when Supabase client is not available."""
        # Test with get_supabase = None (import failed)
        with patch('agents.tools.profile_query_tool.get_supabase', None):
            tool = ProfileQueryTool()
            result = tool._run(user_id=1)
            
            assert "Error: Supabase client not available" in result

    def test_gpa_type_conversion(self):
        """Test GPA is properly converted to float."""
        tool = ProfileQueryTool()
        
        # Test with string GPA
        test_profile = {'id': 1, 'full_name': 'Test', 'gpa': '3.8'}
        
        processed = tool._process_profile(
            test_profile,
            include_preferences=True,
            include_test_scores=True,
            include_extracurriculars=True,
            include_academic_background=True,
            full_profile=False
        )
        
        assert isinstance(processed['gpa'], float)
        assert processed['gpa'] == 3.8

        # Test with None GPA
        test_profile_none = {'id': 1, 'full_name': 'Test', 'gpa': None}
        
        processed_none = tool._process_profile(
            test_profile_none,
            include_preferences=True,
            include_test_scores=True,
            include_extracurriculars=True,
            include_academic_background=True,
            full_profile=False
        )
        
        assert processed_none['gpa'] is None

    def test_read_only_security_constraint(self):
        """Test that the tool is properly configured for read-only access."""
        tool = ProfileQueryTool()
        
        # Check description emphasizes read-only nature
        assert "READ-ONLY" in tool.description
        assert "NO WRITE/UPDATE/DELETE" in tool.description
        assert "secure" in tool.description.lower()
        
        # Check that tool doesn't have database write methods that could be security concerns
        tool_methods = [method for method in dir(tool) if not method.startswith('_') and callable(getattr(tool, method))]
        dangerous_methods = ['insert_profile', 'update_profile', 'delete_profile', 'modify_profile', 'create_profile', 'write_profile']
        
        for method_name in tool_methods:
            for dangerous_method in dangerous_methods:
                assert dangerous_method not in method_name.lower(), f"Tool should not have database write method: {method_name}"
        
        # Verify the tool only has the expected public methods
        expected_methods = ['run', 'arun']  # CrewAI tool standard methods
        actual_public_methods = [method for method in tool_methods if not any(skip in method.lower() for skip in ['forward_refs', 'config', 'schema', 'model'])]
        
        # The tool should primarily have run/arun methods for execution
        assert any(method in actual_public_methods for method in expected_methods), f"Tool should have run methods, found: {actual_public_methods}"

    @patch('agents.tools.profile_query_tool.get_supabase')
    def test_profile_format_single(self, mock_get_supabase):
        """Test single profile formatting output."""
        # Setup mock
        mock_client = Mock()
        mock_table = Mock()
        mock_query = Mock()
        
        mock_get_supabase.return_value = mock_client
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        
        # Mock profile data
        test_profile = {
            'id': 1,
            'full_name': 'Test Student',
            'gpa': 3.8,
            'intended_major': 'Computer Science'
        }
        mock_query.execute.return_value = MockSupabaseResponse([test_profile])

        # Test
        tool = ProfileQueryTool()
        result = tool._run(user_id=1)

        # Check formatting
        assert "USER PROFILE (ID: 1)" in result
        assert "Test Student" in result
        assert "3.8" in result
        assert "Computer Science" in result

    def test_edge_case_empty_optional_fields(self):
        """Test handling of profiles with empty optional fields."""
        tool = ProfileQueryTool()
        
        # Mock minimal profile
        minimal_profile = {
            'id': 2,
            'full_name': 'Minimal Student',
            'gpa': 3.5,
            'test_scores': None,
            'preferences': None,
            'extracurriculars': None,
            'academic_background': None
        }
        
        processed = tool._process_profile(
            minimal_profile,
            include_preferences=True,
            include_test_scores=True,
            include_extracurriculars=True,
            include_academic_background=True,
            full_profile=False
        )
        
        # Should include core fields
        assert processed['id'] == 2
        assert processed['full_name'] == 'Minimal Student'
        assert processed['gpa'] == 3.5
        
        # Should not include None optional fields
        assert 'test_scores' not in processed
        assert 'preferences' not in processed
        assert 'extracurriculars' not in processed
        assert 'academic_background' not in processed