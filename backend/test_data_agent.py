#!/usr/bin/env python3
"""
Test script for the Data Agent
"""
import sys
import os

# Add the backend directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.data_agent import run_data_agent

def test_data_agent():
    """Test the data agent with sample inputs"""
    print("🧪 Testing Data Agent...")
    print("=" * 50)
    
    # Test inputs
    task_spec = {
        "query": "Show me the altitude data from the flight",
        "type": "analysis",
        "priority": "high"
    }
    
    intent = "I want to analyze the flight altitude to understand the aircraft's performance"
    
    # Call the data agent
    result = run_data_agent(task_spec, intent)
    
    # Display results
    print(f"✅ Result OK: {result.ok}")
    print(f"📊 Data: {result.data}")
    print(f"💻 Executed Code: {result.executed_code}")
    print(f"❌ Errors: {result.errors}")
    print(f"📝 Logs: {result.logs}")
    
    print("\n🎯 Data Agent test completed!")

if __name__ == "__main__":
    test_data_agent()