#!/usr/bin/env python3
"""
Test script for the Data Agent
"""
import sys
import os
import logging

# Configure logging to see the data agent logs
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')

# Add the backend directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.data_agent import run_data_agent

def test_data_agent():
    """Test the data agent with sample inputs"""
    print("Testing Data Agent...")
    print("=" * 50)
    
    # Test inputs
    task_spec = {
        "query": "what was the minimum altitude reached during the flight relative to the starting position?",
        "type": "diagnostic",
        "priority": "high"
    }
    intent = "throughout the entire flight, I want to know what the minimum altitude reached was relative to the starting position"
    
    # Call the data agent
    result = run_data_agent(task_spec, intent)
    
    # Display results
    print(f"Result OK: {result.ok}")
    print(f"Data: {result.data}")
    print(f"Errors: {result.errors}")
    print(f"Logs: {result.logs}")
    
    # Show the full generated code
    print("\n" + "=" * 50)
    print("GENERATED CODE:")
    print("=" * 50)
    if result.executed_code:
        print(result.executed_code)
    else:
        print("No code generated")
    
    print("\nData Agent test completed!")

if __name__ == "__main__":
    test_data_agent()