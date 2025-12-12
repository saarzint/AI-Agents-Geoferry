"""
Test runner for pgadmit testing suite.

Simple script to run the test suite and verify functionality.
"""

import pytest
import sys
import os

def run_tests():
    """Run the test suite."""
    
    # Add current directory to path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    sys.path.insert(0, project_root)
    
    print("Running pgadmit Test Suite")
    print("=" * 50)
    
    # Run tests with verbose output
    test_args = [
        "-v",  # Verbose output
        "--tb=short",  # Short traceback format
        "--color=yes",  # Colored output
        current_dir  # Test directory
    ]
    
    # Run pytest
    exit_code = pytest.main(test_args)
    
    if exit_code == 0:
        print("\n✅ All tests passed!")
    else:
        print(f"\n❌ Tests failed with exit code: {exit_code}")
    
    return exit_code

if __name__ == "__main__":
    exit_code = run_tests()
    sys.exit(exit_code)