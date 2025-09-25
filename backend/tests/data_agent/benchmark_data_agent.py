#!/usr/bin/env python3
"""
Benchmark harness for the Data Agent.
Runs a suite of representative tasks and reports success/failure.
"""

import logging
import sys
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Optional, Any

# Add the backend directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.data_agent import run_data_agent

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

@dataclass
class TaskResult:
    """Result object for each benchmark task"""
    name: str
    query: str
    intent: str
    ok: bool
    data: Optional[Any] = None
    executed_code: Optional[str] = None
    errors: List[str] = None
    logs: List[str] = None
    timing: dict = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.logs is None:
            self.logs = []
        if self.timing is None:
            self.timing = {}

# Define a suite of test tasks
TASKS = [
    {
        "name": "Simple altitude retrieval",
        "task_spec": {"query": "Show me the altitude data", "type": "analysis"},
        "intent": "Analyze flight altitude"
    },
    {
        "name": "Maximum altitude",
        "task_spec": {"query": "What was the maximum altitude reached during the flight?", "type": "analysis"},
        "intent": "Find highest altitude reached"
    },
    {
        "name": "First GPS loss",
        "task_spec": {"query": "When did the GPS signal first get lost?", "type": "diagnostic"},
        "intent": "Detect GPS failures"
    },
    {
        "name": "Total flight time",
        "task_spec": {"query": "How long was the total flight time?", "type": "analysis"},
        "intent": "Measure flight duration"
    },
    {
        "name": "Critical errors",
        "task_spec": {"query": "List all critical errors that happened mid-flight", "type": "diagnostic"},
        "intent": "Extract STATUS text logs for anomalies"
    },
    {
        "name": "RC signal loss",
        "task_spec": {"query": "When was the first instance of RC signal loss?", "type": "diagnostic"},
        "intent": "Detect RC link issues"
    },
    {
        "name": "Pitch/Roll/Yaw sample",
        "task_spec": {"query": "Show me a sample of roll, pitch, yaw values during the flight", "type": "analysis"},
        "intent": "Explore attitude measurements"
    },
    {
        "name": "Average climb rate",
        "task_spec": {"query": "What was the average climb rate (vz)?", "type": "analysis"},
        "intent": "Analyze vertical speed"
    },
    {
        "name": "GPS satellite counts",
        "task_spec": {"query": "Show me how many satellites were visible over time", "type": "analysis"},
        "intent": "Check GPS quality"
    },
    {
        "name": "EKF messages",
        "task_spec": {"query": "Show all EKF-related warnings or errors", "type": "diagnostic"},
        "intent": "Check estimator consistency"
    }
]


def run_single_task(task: dict) -> TaskResult:
    """Run a single task and return structured result"""
    start_time = time.time()
    
    try:
        # Run the data agent
        result = run_data_agent(task["task_spec"], task["intent"])
        
        # Calculate timing
        end_time = time.time()
        duration = end_time - start_time
        
        # Create structured result
        task_result = TaskResult(
            name=task["name"],
            query=task["task_spec"]["query"],
            intent=task["intent"],
            ok=result.ok,
            data=result.data,
            executed_code=result.executed_code,
            errors=result.errors,
            logs=result.logs,
            timing={
                "start": start_time,
                "end": end_time,
                "duration_sec": duration
            }
        )
        
        return task_result
        
    except Exception as e:
        # Handle any exceptions during task execution
        end_time = time.time()
        duration = end_time - start_time
        
        return TaskResult(
            name=task["name"],
            query=task["task_spec"]["query"],
            intent=task["intent"],
            ok=False,
            errors=[f"Exception: {str(e)}"],
            logs=[],
            timing={
                "start": start_time,
                "end": end_time,
                "duration_sec": duration
            }
        )


def benchmark():
    print("Running Data Agent benchmark (parallel execution)...")
    print("=" * 60)
    
    # Start timing the entire benchmark
    benchmark_start = time.time()
    
    # Run all tasks in parallel
    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        # Submit all tasks
        future_to_task = {executor.submit(run_single_task, task): task for task in TASKS}
        
        # Collect results as they complete
        for future in as_completed(future_to_task):
            task = future_to_task[future]
            try:
                result = future.result()
                results.append(result)
                print(f"✓ Completed: {result.name} ({result.timing['duration_sec']:.1f}s)")
            except Exception as e:
                print(f"✗ Failed: {task['name']} - {e}")
                # Create a failed result
                results.append(TaskResult(
                    name=task["name"],
                    query=task["task_spec"]["query"],
                    intent=task["intent"],
                    ok=False,
                    errors=[f"Future exception: {str(e)}"]
                ))
    
    # Sort results by name for consistent output
    results.sort(key=lambda x: x.name)
    
    # Calculate total benchmark time
    benchmark_end = time.time()
    total_duration = benchmark_end - benchmark_start
    
    # Print detailed results
    print("\n" + "=" * 60)
    print("Detailed Results")
    print("=" * 60)
    
    for result in results:
        print(f"\nTask: {result.name}")
        print(f"  Query: {result.query}")
        print(f"  OK: {result.ok}")
        print(f"  Duration: {result.timing.get('duration_sec', 0):.1f}s")
        
        if result.ok:
            # Show a preview of the data
            data_preview = str(result.data)[:200] + "..." if len(str(result.data)) > 200 else str(result.data)
            print(f"  Data sample: {data_preview}")
            print(f"  Code length: {len(result.executed_code) if result.executed_code else 0} chars")
        else:
            print(f"  Errors: {result.errors}")
            if result.executed_code:
                print(f"  Generated code: {result.executed_code[:100]}...")
    
    # Aggregate benchmark summary
    print("\n" + "=" * 60)
    print("Benchmark Summary")
    print("=" * 60)

    total = len(results)
    successes = sum(1 for r in results if r.ok)
    failures = total - successes
    avg_duration = sum(r.timing.get('duration_sec', 0) for r in results) / total if results else 0

    print(f"Total tasks: {total}")
    print(f"Successes : {successes}")
    print(f"Failures  : {failures}")
    print(f"Success rate: {successes/total*100:.1f}%")
    print(f"Total benchmark time: {total_duration:.1f}s")
    print(f"Average task time: {avg_duration:.1f}s")

    if failures > 0:
        print("\nFailed tasks:")
        for result in results:
            if not result.ok:
                print(f" - {result.name}: {result.errors}")

    print("\nSuccessful tasks:")
    for result in results:
        if result.ok:
            print(f" - {result.name}")

    print(f"\nBenchmark complete! (Total time: {total_duration:.1f}s)")


if __name__ == "__main__":
    benchmark()
