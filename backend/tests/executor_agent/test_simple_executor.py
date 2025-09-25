#!/usr/bin/env python3
"""
Simple test for the Executor Agent - tests basic functionality without long execution
"""

import sys
import os
import logging

# Configure logging to see the executor agent logs
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')

# Add the backend directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.executor_agent import executor_agent
from services import db

def test_simple_executor():
    """Test the executor agent with a simple task and limited rounds"""
    print("Testing Simple Executor Agent...")
    print("=" * 50)
    
    # Get schema bundle (same as Data Agent does)
    conn = db.get_connection()
    tables = conn.execute("SHOW TABLES").fetchall()
    schema_info = {}
    
    for table in tables:
        table_name = table[0]
        schema = conn.execute(f"DESCRIBE {table_name}").fetchall()
        schema_info[table_name] = {
            "columns": [{"name": col[0], "type": col[1]} for col in schema]
        }
    
    conn.close()
    
    schema_bundle = {
        "message_types": [table[0] for table in tables],
        "enriched_schema": schema_info,
        "normalized_schema": schema_info
    }
    
    # Test inputs - simple task
    task_spec = {
        "query": "Show me the first 5 rows from any altitude table",
        "type": "analysis",
        "priority": "low"
    }
    
    intent = "Quick test of the Executor Agent"
    
    # Call the executor agent with limited rounds
    result = executor_agent(task_spec, schema_bundle, intent, max_rounds=1)
    
    # Display results
    print(f"Result OK: {result['ok']}")
    print(f"Final Data: {result.get('final_data', 'None')}")
    print(f"Iterations: {result.get('iterations', 0)}")
    print(f"Errors: {result['errors']}")
    print(f"Logs: {result['logs']}")
    print(f"Agents: {len(result['agents'])}")
    
    # Show reasoning trace
    if 'reasoning_trace' in result:
        print(f"\nReasoning Trace ({len(result['reasoning_trace'])} rounds):")
        for trace in result['reasoning_trace']:
            print(f"  Round {trace['round']}: {trace['decision']}")
            print(f"    Reasoning: {trace['reasoning']}")
    
    # Show failure reason if applicable
    if not result['ok'] and 'failure_reason' in result:
        print(f"\nFailure Reason: {result['failure_reason']}")
    
    print("\nSimple Executor Agent test completed!")

if __name__ == "__main__":
    test_simple_executor()
