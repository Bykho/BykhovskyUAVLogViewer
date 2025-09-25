#!/usr/bin/env python3
"""
Test script to demonstrate the self-healing Data Agent retry mechanism.
This test forces a failure scenario to show the retry loop in action.
"""

import sys
import os
import logging

# Configure logging to see the data agent logs
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')

# Add the backend directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.data_agent import run_data_agent

def test_self_healing():
    """Test the self-healing mechanism with a query that will force a retry"""
    print("Testing Self-Healing Data Agent (Forced Retry)...")
    print("=" * 50)
    
    # Test with a query that will likely generate problematic SQL to force retries
    task_spec = {
        "query": "Show me all GPS messages where the fix type is 0x0 (no fix) using hex literals",
        "type": "diagnostic", 
        "priority": "high"
    }
    
    intent = "Find GPS messages with no fix using hexadecimal notation"
    
    # Call the data agent
    result = run_data_agent(task_spec, intent)
    
    # Display results
    print(f"Result OK: {result.ok}")
    print(f"Data: {result.data}")
    print(f"Errors: {result.errors}")
    print(f"Logs: {result.logs}")
    
    # Show attempt history if available
    if result.attempts:
        print(f"\nAttempt History ({len(result.attempts)} attempts):")
        for i, attempt in enumerate(result.attempts, 1):
            status = "Success" if attempt['success'] else "Failed"
            print(f"  Attempt {i}: {status}")
            if not attempt['success'] and attempt['error']:
                print(f"    Error: {attempt['error'][:100]}...")
            if attempt['generated_code']:
                print(f"    Code: {attempt['generated_code'][:100]}...")
    
    # Show the final generated code
    print("\n" + "=" * 50)
    print("FINAL GENERATED CODE:")
    print("=" * 50)
    if result.executed_code:
        print(result.executed_code)
    else:
        print("No code generated")
    
    print("\nSelf-healing test completed!")

if __name__ == "__main__":
    test_self_healing()
