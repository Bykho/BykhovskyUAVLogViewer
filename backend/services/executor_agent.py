import logging
from typing import Dict, List, Any, Optional
from services.data_agent import run_data_agent
from openai import OpenAI
import os
import json
import re
import json_repair
import time
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI()

@dataclass
class AgentResult:
    """Unified container for Data Agent results"""
    subtask: dict
    ok: bool
    data: Optional[Any] = None
    executed_code: Optional[str] = None
    errors: List[str] = None
    logs: List[str] = None
    duration_sec: float = 0.0
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.logs is None:
            self.logs = []

def extract_json_block(text: str) -> dict:
    """
    Bulletproof JSON extraction from LLM output using json_repair.
    Handles malformed JSON, trailing commas, single quotes, comments, etc.
    """
    # Clean up markdown code fences
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = re.sub(r'```\s*$', '', text)
    text = text.strip()
    
    # First try standard JSON parsing
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Try json_repair for malformed JSON
    try:
        return json_repair.loads(text)
    except Exception as e:
        logger.error(f"JSON repair failed: {e}, text[:200]={text[:200]!r}")
        return {"error": "Failed to parse JSON"}

def run_agents_in_parallel(subtasks: List[dict], intent: str) -> List[AgentResult]:
    """
    Run Data Agents in parallel for one Executor round.
    Returns structured results for all subtasks.
    """
    results = []
    logger.info(f"=== DISPATCHING {len(subtasks)} DATA AGENTS IN PARALLEL ===")
    
    with ThreadPoolExecutor(max_workers=min(5, len(subtasks))) as executor:
        # Submit all tasks
        future_to_task = {
            executor.submit(run_data_agent, subtask, intent): subtask 
            for subtask in subtasks
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_task):
            subtask = future_to_task[future]
            start_time = time.time()
            
            try:
                result = future.result()
                duration = time.time() - start_time
                
                agent_result = AgentResult(
                    subtask=subtask,
                    ok=result.ok,
                    data=result.data,
                    executed_code=result.executed_code,
                    errors=result.errors,
                    logs=result.logs,
                    duration_sec=duration
                )
                results.append(agent_result)
                
                status = "✓" if result.ok else "✗"
                logger.info(f"{status} Completed: {subtask['query'][:60]}... ({duration:.1f}s)")
                
            except Exception as e:
                duration = time.time() - start_time
                agent_result = AgentResult(
                    subtask=subtask,
                    ok=False,
                    errors=[f"Executor exception: {str(e)}"],
                    logs=[],
                    duration_sec=duration
                )
                results.append(agent_result)
                logger.error(f"✗ Failed: {subtask['query'][:60]}... ({duration:.1f}s) - {e}")
    
    # Sort results by subtask order for consistent output
    results.sort(key=lambda x: subtasks.index(x.subtask))
    
    success_count = sum(1 for r in results if r.ok)
    logger.info(f"=== ROUND COMPLETE: {success_count}/{len(results)} agents succeeded ===")
    
    return results

def ledger_from_results(results: List[AgentResult], round_num: int) -> str:
    """
    Build human-readable ledger for logs and LLM review.
    """
    ledger = f"=== Round {round_num} Data Agent Results ===\n"
    
    for i, r in enumerate(results, 1):
        ledger += f"\nSubtask {i}:\n"
        ledger += f"- Query: \"{r.subtask['query']}\"\n"
        ledger += f"- Success: {r.ok}\n"
        ledger += f"- Duration: {r.duration_sec:.1f}s\n"
        
        if r.ok and r.data:
            data_str = str(r.data)
            if len(data_str) > 200:
                data_str = data_str[:200] + "..."
            ledger += f"- Data (sample):\n  {data_str}\n"
        else:
            ledger += f"- Data: None\n"
        
        if r.executed_code:
            code_str = r.executed_code
            if len(code_str) > 300:
                code_str = code_str[:300] + "..."
            ledger += f"- Executed Code:\n  {code_str}\n"
        
        if r.errors:
            ledger += f"- Errors:\n  {', '.join(r.errors)}\n"
        else:
            ledger += f"- Errors: None\n"
        
        ledger += "\n"
    
    return ledger

def executor_agent(task_spec: dict, schema_bundle: dict, intent: str, max_rounds: int = 3) -> dict:
    """
    Persistent Executor Agent - Owns the full lifecycle of one Planner task.
    
    Runs multiple layers of Data Agents until task is resolved, impossible, or max_rounds exceeded.
    Maintains persistent memory across all rounds.
    
    Args:
        task_spec: Task description from Planner
        schema_bundle: Schema context from Schema Agent  
        intent: High-level goal from Planner
        max_rounds: Maximum number of Executor rounds before giving up
        
    Returns:
        Structured response with full reasoning trace
    """
    logger.info("=== PERSISTENT EXECUTOR AGENT STARTING ===")
    logger.info(f"Task: {task_spec}")
    logger.info(f"Intent: {intent}")
    logger.info(f"Schema keys: {list(schema_bundle.keys()) if schema_bundle else 'None'}")
    logger.info(f"Max rounds: {max_rounds}")
    
    # Initialize persistent memory
    reasoning_trace = []
    all_executed_code = []
    all_errors = []
    all_logs = []
    all_agents = []
    
    # Main Executor loop
    for round_num in range(1, max_rounds + 1):
        logger.info(f"=== EXECUTOR ROUND {round_num}/{max_rounds} ===")
        
        # 1. Plan subtasks for this round
        subtasks = plan_subtasks(task_spec, schema_bundle, intent, reasoning_trace, round_num)
        logger.info(f"Generated {len(subtasks)} subtasks for round {round_num}")
        
        # 2. Dispatch Data Agents in parallel
        round_results = run_agents_in_parallel(subtasks, intent)
        
        # 3. Build ledger-style summary for Executor LLM
        ledger = ledger_from_results(round_results, round_num)
        
        # 4. Aggregate results for persistent memory
        for result in round_results:
            all_executed_code.append(result.executed_code)
            all_errors.extend(result.errors)
            all_logs.extend(result.logs)
        
        # 4. Review results and decide next action
        decision = review_and_decide(task_spec, schema_bundle, intent, reasoning_trace, ledger, round_num)
        
        # 5. Record this round in memory
        reasoning_trace.append({
            "round": round_num,
            "subtasks": subtasks,
            "results": [{"subtask": r.subtask, "ok": r.ok, "duration": r.duration_sec} for r in round_results],
            "ledger": ledger,
            "decision": decision["action"],
            "reasoning": decision["reasoning"]
        })
        
        # 5. Check termination conditions
        if decision["action"] == "resolved":
            logger.info(f"=== TASK RESOLVED IN ROUND {round_num} ===")
            return {
                "ok": True,
                "task": task_spec,
                "final_data": decision["final_data"],
                "reasoning_trace": reasoning_trace,
                "executed_code": all_executed_code,
                "errors": all_errors,
                "logs": all_logs,
                "agents": all_agents + [{"subtask": r.subtask, "ok": r.ok, "data": r.data, "executed_code": r.executed_code, "errors": r.errors, "logs": r.logs, "duration": r.duration_sec} for r in round_results],
                "iterations": round_num
            }
        elif decision["action"] == "impossible":
            logger.info(f"=== TASK DECLARED IMPOSSIBLE IN ROUND {round_num} ===")
            return {
                "ok": False,
                "task": task_spec,
                "final_data": None,
                "reasoning_trace": reasoning_trace,
                "executed_code": all_executed_code,
                "errors": all_errors,
                "logs": all_logs,
                "agents": all_agents + [{"subtask": r.subtask, "ok": r.ok, "data": r.data, "executed_code": r.executed_code, "errors": r.errors, "logs": r.logs, "duration": r.duration_sec} for r in round_results],
                "iterations": round_num,
                "failure_reason": decision["reasoning"]
            }
        elif round_num == max_rounds:
            logger.info(f"=== MAX ROUNDS EXCEEDED ===")
            return {
                "ok": False,
                "task": task_spec,
                "final_data": None,
                "reasoning_trace": reasoning_trace,
                "executed_code": all_executed_code,
                "errors": all_errors,
                "logs": all_logs,
                "agents": all_agents + [{"subtask": r.subtask, "ok": r.ok, "data": r.data, "executed_code": r.executed_code, "errors": r.errors, "logs": r.logs, "duration": r.duration_sec} for r in round_results],
                "iterations": round_num,
                "failure_reason": f"Exceeded maximum rounds ({max_rounds})"
            }
        
        # Continue to next round
        logger.info(f"=== CONTINUING TO ROUND {round_num + 1} ===")
    
    # This should never be reached due to the max_rounds check above
    return {"ok": False, "error": "Unexpected end of Executor loop"}


def plan_subtasks(task_spec: dict, schema_bundle: dict, intent: str, 
                  reasoning_trace: List[dict], round_num: int) -> List[dict]:
    """
    Use Executor LLM to plan subtasks for this round.
    Takes into account previous rounds and results.
    """
    # Build context from previous rounds
    previous_context = ""
    if reasoning_trace:
        previous_context = "\nPrevious rounds:\n"
        for trace in reasoning_trace:
            previous_context += f"Round {trace['round']}: {trace['decision']}\n"
            previous_context += f"  Reasoning: {trace['reasoning']}\n"
    
    prompt = f"""
You are the Executor Agent, planning subtasks for round {round_num}.

Original task: {task_spec}
Intent: {intent}
Schema available: {list(schema_bundle.get('message_types', []))}

{previous_context}

Generate 2-4 specific subtasks that will help resolve the original task.
Each subtask should be a focused query that can be executed by a Data Agent.

Return as a JSON list of subtasks, each with:
- "query": specific question to answer
- "type": "analysis" or "diagnostic" 
- "priority": "high", "medium", or "low"

Focus on:
- If round 1: break down the main task into logical components
- If round 2+: refine based on what was learned, resolve conflicts, or fill gaps
- Make subtasks specific and actionable
- Avoid redundancy with previous rounds
"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an Executor Agent that plans subtasks for UAV telemetry analysis. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000
        )
        
        content = response.choices[0].message.content.strip()
        logger.info(f"LLM response: {content[:200]}...")
        
        # Use robust JSON extraction
        subtasks = extract_json_block(content)
        
        # Handle extraction errors with safe fallback
        if "error" in subtasks or not isinstance(subtasks, list):
            logger.error(f"JSON extraction failed: {subtasks}")
            return [{"query": task_spec.get("query", "Analyze the data"), "type": "analysis", "priority": "high"}]
        
        # Ensure all subtasks have required fields
        safe_subtasks = []
        for subtask in subtasks:
            if isinstance(subtask, dict):
                safe_subtasks.append({
                    "query": subtask.get("query", "Analyze the data"),
                    "type": subtask.get("type", "analysis"),
                    "priority": subtask.get("priority", "medium")
                })
        
        logger.info(f"Generated {len(safe_subtasks)} subtasks for round {round_num}")
        return safe_subtasks
        
    except Exception as e:
        logger.error(f"Failed to generate subtasks: {e}")
        logger.error(f"Raw response: {response.choices[0].message.content}")
        # Fallback: return a simple subtask
        return [{"query": task_spec.get("query", "Analyze the data"), "type": "analysis", "priority": "high"}]




def review_and_decide(task_spec: dict, schema_bundle: dict, intent: str, 
                      reasoning_trace: List[dict], ledger: str, round_num: int) -> dict:
    """
    Use Executor LLM to review results and decide next action.
    Now uses ledger-style format for much better LLM reasoning.
    """
    # Build context from previous rounds
    previous_context = ""
    if reasoning_trace:
        previous_context = "\nPrevious rounds:\n"
        for trace in reasoning_trace:
            previous_context += f"Round {trace['round']}: {trace['decision']}\n"
            previous_context += f"  Reasoning: {trace['reasoning']}\n"
    
    prompt = f"""
You are the Executor Agent. Review the round's ledger of Data Agent results below.

Original Task: {task_spec}
Intent: {intent}

{ledger}

{previous_context}

Your job:
- Decide if the task is RESOLVED, needs to CONTINUE, or is IMPOSSIBLE.
- If resolved, provide the final_data.
- If continue, explain what new subtasks are needed next round.
- If impossible, explain why.

Respond in JSON:
{{
  "action": "resolved" | "continue" | "impossible",
  "reasoning": "...",
  "final_data": ... (only if resolved)
}}
"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an Executor Agent that reviews results and makes decisions. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000
        )
        
        content = response.choices[0].message.content.strip()
        logger.info(f"LLM response: {content[:200]}...")
        
        # Use robust JSON extraction
        decision = extract_json_block(content)
        
        # Handle extraction errors with safe fallback
        if "error" in decision or not isinstance(decision, dict):
            logger.error(f"JSON extraction failed: {decision}")
            # Fallback: analyze the ledger to determine success
            if "Success: True" in ledger:
                return {"action": "continue", "reasoning": "Fallback: continuing due to some success"}
            else:
                return {"action": "impossible", "reasoning": "Fallback: no successful results"}
        
        # Ensure required fields exist with safe defaults
        action = decision.get("action", "continue")
        reasoning = decision.get("reasoning", "No reasoning provided")
        final_data = decision.get("final_data")
        
        logger.info(f"Round {round_num} decision: {action} - {reasoning}")
        return {
            "action": action,
            "reasoning": reasoning,
            "final_data": final_data
        }
        
    except Exception as e:
        logger.error(f"Failed to review results: {e}")
        logger.error(f"Raw response: {response.choices[0].message.content}")
        # Fallback: analyze the ledger to determine success
        if "Success: True" in ledger:
            return {"action": "continue", "reasoning": "Fallback: continuing due to some success"}
        else:
            return {"action": "impossible", "reasoning": "Fallback: no successful results"}
