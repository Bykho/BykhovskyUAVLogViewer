import logging
from typing import Dict, List, Any, Optional
from openai import OpenAI
import os
import json
import time
import textwrap
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI()

@dataclass
class AgentResult:
    """Container for Data Agent results"""
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


class ExecutorAgent:
    """Intelligent, self-aware Executor with tool-based reasoning"""
    
    def __init__(self):
        self.conversation_history: List[Dict[str, Any]] = []
        self.mental_model = {
            "hypotheses": [],  # List of theories about how to solve the task
            "failed_approaches": [],  # What didn't work and why
            "insights": [],  # Learnings from each round
            "confidence_by_approach": {}  # Confidence scores for different strategies
        }
        self.current_round = 0
        self.max_rounds = 3
        self.all_data_agent_results: List[AgentResult] = []
        self.task_spec = None
        self.schema_bundle = None
        self.intent = None
        self.planned_subtasks = None
        self.last_action = None  # Track last tool call for enforcement
        self.has_dispatched_this_round = False
        
    def _get_system_prompt(self) -> str:
        """Generate dynamic system prompt with current context"""
        
        # Format mental model for readability
        mental_model_text = self._format_mental_model()
        
        # Format schema bundle for injection
        schema_text = json.dumps(self.schema_bundle, indent=2) if self.schema_bundle else "Schema unavailable - operating without domain knowledge"
        
        # Build urgency context based on round
        urgency = ""
        if self.current_round == 1:
            urgency = "This is Round 1 of 3. Take time to form solid hypotheses."
        elif self.current_round == 2:
            urgency = "This is Round 2 of 3. Review what worked/failed in Round 1 and adapt."
        elif self.current_round >= 3:
            urgency = "This is Round 3 of 3 (FINAL ROUND). Be decisive - accept consistent results or declare impossible."
        
        return f"""You are an EXPERT Executor Agent with meta-cognitive capabilities for UAV telemetry analysis.

YOUR ROLE:
You receive high-level tasks from the Planner Agent and must solve them by:
1. Forming testable hypotheses about the data
2. Planning specific queries to test those hypotheses
3. Dispatching Data Agents to execute queries
4. Deeply analyzing results to learn what works
5. Pivoting strategy when approaches fail
6. Resolving with final answers or declaring tasks impossible

CURRENT TASK:
{json.dumps(self.task_spec, indent=2)}

PLANNER'S INTENT (why this matters, what success looks like):
{self.intent}

DOMAIN KNOWLEDGE - Enriched UAV Telemetry Schema:
{schema_text}

CRITICAL SCHEMA UNDERSTANDING:
- **Units matter**: altitude in mm (divide by 1000 for meters), speeds in cm/s, angles can be radians OR degrees
- **Field semantics**: 
  * attitude.yaw = rotation in radians (-π to π, WRAPS around)
  * global_position_int.hdg = vehicle heading in centidegrees (0-35999, MONOTONIC for full rotations)
  * relative_alt vs alt = different altitude references
  * lat/lon in degE7 = divide by 10^7 for actual coordinates
- **Data quality**: Higher sampleCount = more authoritative source
- **Table relationships**: attitude has orientation, GPS has position, system_time has timestamps

USE SCHEMA TO:
1. Choose the RIGHT fields (hdg for loops, not yaw)
2. Convert units correctly (mm to m, centidegrees to degrees)
3. Identify authoritative sources (highest sample count)
4. Avoid field confusion (multiple altitude/heading fields exist)

YOUR MENTAL MODEL (what you know so far):
{mental_model_text}

{urgency}

AVAILABLE TOOLS:
1. **form_hypothesis** - State a theory about how to solve this task (REQUIRED before dispatching)
2. **plan_subtasks** - Break hypothesis into specific executable queries
3. **dispatch_data_agents** - Execute planned queries in parallel
4. **analyze_results** - Deep reflection on what data agents returned (REQUIRED after dispatching)
5. **pivot_strategy** - Abandon failing approach, try fundamentally different method
6. **declare_resolved** - Task complete with final answer and evidence
7. **declare_impossible** - Cannot complete with available data

META-REASONING RULES:
- BEFORE dispatch_data_agents: MUST call form_hypothesis to explain what you're testing
- AFTER dispatch_data_agents: MUST call analyze_results to interpret outcomes
- If same result appears 2+ times: Accept it OR pivot to different approach (don't endlessly retry)
- Empty results mean: wrong query OR wrong table OR phenomenon doesn't exist (determine which!)
- Confidence scoring: Track which approaches seem promising vs failing

THINKING PATTERN (use this EVERY time):
1. "What am I trying to learn from this action?"
2. "What would each possible result tell me?"
3. "If I get the same result as last time, what does that mean?"
4. "What's my backup plan if this fails?"

EXAMPLE INTELLIGENCE:
Task: "Detect loops in flight"
- Round 1: Hypothesis "loops = yaw accumulation ±360°" → Query attitude.yaw → Get 1732 crossings → Analyze: "TOO MANY - yaw wraps at ±π, counting noise not maneuvers"
- Round 2: Pivot "loops = spatial return to origin" → Query GPS lat/lon clusters → Get 4 position clusters → "MATCHES user observation!"
- Resolved: "Found 4 loops using spatial method, not rotational"

CRITICAL: Think like a SCIENTIST conducting experiments:
- Form explicit hypotheses BEFORE running queries
- Predict outcomes and what they'd mean
- Learn from failures to inform next attempt
- Don't retry blindly - pivot strategically

Be transparent about your reasoning. Explain WHY you're doing what you're doing."""

    def _format_mental_model(self) -> str:
        """Format mental model for injection into prompt"""
        if not any(self.mental_model.values()):
            return "No mental model yet - this is your first analysis."
        
        parts = []
        
        if self.mental_model["hypotheses"]:
            parts.append("HYPOTHESES FORMED:")
            for h in self.mental_model["hypotheses"]:
                parts.append(f"  - {h}")
        
        if self.mental_model["failed_approaches"]:
            parts.append("\nFAILED APPROACHES (don't retry these):")
            for f in self.mental_model["failed_approaches"]:
                parts.append(f"  - {f}")
        
        if self.mental_model["insights"]:
            parts.append("\nINSIGHTS LEARNED:")
            for i in self.mental_model["insights"]:
                parts.append(f"  - {i}")
        
        if self.mental_model["confidence_by_approach"]:
            parts.append("\nCONFIDENCE SCORES:")
            for approach, confidence in self.mental_model["confidence_by_approach"].items():
                parts.append(f"  - {approach}: {confidence}")
        
        return "\n".join(parts)

    def execute_task(self, task_spec: dict, schema_bundle: dict, intent: str) -> dict:
        """Main execution loop with agentic reasoning"""
        logger.info(f"Executor V2: {task_spec.get('query', 'Unknown task')[:60]}...")
        
        # Store context
        self.task_spec = task_spec
        self.schema_bundle = schema_bundle
        self.intent = intent
        
        # Define tools
        tools = self._get_tool_definitions()
        
        # Initialize conversation with system prompt
        system_prompt = self._get_system_prompt()
        self.conversation_history = [
            {"role": "system", "content": system_prompt}
        ]
        
        # Execution loop
        start_time = time.time()
        max_iterations = 20  # Safety limit for tool calling loop
        
        # Increment round at start (not in dispatch)
        self.current_round = 1
        
        for iteration in range(max_iterations):
            try:
                # Check max rounds enforcement
                if self.current_round > self.max_rounds:
                    logger.warning(f"Exceeded max rounds ({self.max_rounds})")
                    total_duration = time.time() - start_time
                    return {
                        "ok": False,
                        "task": task_spec,
                        "final_data": None,
                        "reasoning_trace": self.mental_model,
                        "executed_code": [r.executed_code for r in self.all_data_agent_results if r.executed_code],
                        "errors": ["Exceeded maximum rounds"],
                        "logs": [f"Stopped at round {self.current_round}"],
                        "agents": self._format_agent_results(),
                        "iterations": self.current_round,
                        "failure_reason": f"Exceeded maximum rounds ({self.max_rounds}) without resolution",
                        "duration_sec": total_duration
                    }
                
                logger.info(f"Round {self.current_round}/{self.max_rounds}, Iteration {iteration + 1}")
                
                # Update system prompt with current state
                self.conversation_history[0]["content"] = self._get_system_prompt()
                
                # Call LLM with tools
                response = client.chat.completions.create(
                    model="gpt-4o",  # Will upgrade to GPT-5 when available
                    messages=self.conversation_history,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.1  # Low temp for analytical reasoning
                )
                
                message = response.choices[0].message
                
                # Store message in history
                message_dict = {
                    "role": message.role,
                    "content": message.content
                }
                if hasattr(message, 'tool_calls') and message.tool_calls:
                    message_dict["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        } for tc in message.tool_calls
                    ]
                
                self.conversation_history.append(message_dict)
                
                # Process tool calls
                if message.tool_calls:
                    logger.info(f"Processing {len(message.tool_calls)} tool calls")
                    
                    for tool_call in message.tool_calls:
                        function_name = tool_call.function.name
                        
                        try:
                            function_args = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse tool arguments: {e}")
                            tool_message = {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": f"Error: Invalid JSON in tool arguments: {str(e)}"
                            }
                            self.conversation_history.append(tool_message)
                            continue
                        
                        logger.info(f"Tool: {function_name}")
                        
                        # Enforce tool order constraints
                        if function_name == "dispatch_data_agents":
                            if not self.planned_subtasks:
                                tool_message = {
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": "Error: Cannot dispatch without planning subtasks first. Call plan_subtasks."
                                }
                                self.conversation_history.append(tool_message)
                                continue
                        
                        if function_name in ["declare_resolved", "declare_impossible"]:
                            if self.has_dispatched_this_round and self.last_action != "analyze_results":
                                tool_message = {
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": "Error: Must call analyze_results after dispatch before declaring resolution. Analyze what you learned first."
                                }
                                self.conversation_history.append(tool_message)
                                continue
                        
                        # Execute tool
                        try:
                            result = self._execute_tool(function_name, function_args)
                            self.last_action = function_name
                        except Exception as tool_error:
                            logger.error(f"Tool execution error: {tool_error}")
                            import traceback
                            traceback.print_exc()
                            result = f"Tool execution failed: {str(tool_error)}"
                        
                        # Add tool result to conversation
                        tool_message = {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": str(result)
                        }
                        self.conversation_history.append(tool_message)
                        
                        # Check for terminal tools
                        if function_name in ["declare_resolved", "declare_impossible"]:
                            total_duration = time.time() - start_time
                            return self._build_final_response(
                                function_name == "declare_resolved",
                                result,
                                total_duration
                            )
                    
                    # Continue conversation loop
                    continue
                    
                else:
                    # No tool calls - LLM gave text response (shouldn't happen with proper prompting)
                    logger.warning("LLM provided text without tool calls - continuing")
                    continue
                    
            except Exception as e:
                logger.error(f"Error in execution loop: {e}")
                import traceback
                traceback.print_exc()
                
                total_duration = time.time() - start_time
                return {
                    "ok": False,
                    "task": task_spec,
                    "final_data": None,
                    "reasoning_trace": self.mental_model,
                    "executed_code": [r.executed_code for r in self.all_data_agent_results if r.executed_code],
                    "errors": [str(e)],
                    "logs": ["Executor error"],
                    "agents": self._format_agent_results(),
                    "iterations": self.current_round,
                    "failure_reason": f"Executor exception: {str(e)}",
                    "duration_sec": total_duration
                }
        
        # Max iterations reached
        total_duration = time.time() - start_time
        logger.warning(f"Max iterations reached ({max_iterations})")
        return {
            "ok": False,
            "task": task_spec,
            "final_data": None,
            "reasoning_trace": self.mental_model,
            "executed_code": [r.executed_code for r in self.all_data_agent_results if r.executed_code],
            "errors": ["Max iterations reached"],
            "logs": ["Executor exhausted iteration limit"],
            "agents": self._format_agent_results(),
            "iterations": self.current_round,
            "failure_reason": "Exceeded maximum iterations without resolution",
            "duration_sec": total_duration
        }

    def _get_tool_definitions(self) -> List[dict]:
        """Define tools for the executor"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "form_hypothesis",
                    "description": "Form an explicit hypothesis about how to solve this task. Required before dispatching data agents.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "hypothesis": {"type": "string", "description": "Your theory about how to solve the task"},
                            "reasoning": {"type": "string", "description": "Why you think this approach will work"},
                            "confidence": {"type": "number", "description": "Confidence level 0-1"},
                            "expected_outcome": {"type": "string", "description": "What results would validate this hypothesis"}
                        },
                        "required": ["hypothesis", "reasoning", "confidence"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "plan_subtasks",
                    "description": "Break hypothesis into specific executable queries for data agents",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subtasks": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "query": {"type": "string"},
                                        "type": {"type": "string"},
                                        "priority": {"type": "string"}
                                    }
                                }
                            }
                        },
                        "required": ["subtasks"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "dispatch_data_agents",
                    "description": "Execute planned subtasks using data agents in parallel",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "analyze_results",
                    "description": "Deeply analyze data agent results. Required after dispatching.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "analysis": {"type": "string", "description": "What do the results mean?"},
                            "validates_hypothesis": {"type": "boolean", "description": "Did results support your hypothesis?"},
                            "insights": {"type": "string", "description": "What did you learn?"},
                            "next_action": {"type": "string", "description": "What should happen next?"}
                        },
                        "required": ["analysis", "validates_hypothesis", "insights"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "pivot_strategy",
                    "description": "Abandon current approach and try fundamentally different method",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "failed_approach": {"type": "string", "description": "What approach failed"},
                            "why_failed": {"type": "string", "description": "Why it failed based on evidence"},
                            "new_strategy": {"type": "string", "description": "Fundamentally different approach to try"},
                            "why_better": {"type": "string", "description": "Why this should work better"}
                        },
                        "required": ["failed_approach", "why_failed", "new_strategy"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "declare_resolved",
                    "description": "Task is complete with final answer",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "final_answer": {"type": "string", "description": "The answer to the task"},
                            "supporting_evidence": {"type": "string", "description": "Data that supports this answer"},
                            "confidence": {"type": "number", "description": "Confidence in answer 0-1"}
                        },
                        "required": ["final_answer", "supporting_evidence"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "declare_impossible",
                    "description": "Cannot complete task with available data",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reason": {"type": "string", "description": "Why task cannot be completed"},
                            "attempted_approaches": {"type": "string", "description": "What strategies were tried"},
                            "missing_data": {"type": "string", "description": "What data would be needed"}
                        },
                        "required": ["reason", "attempted_approaches"]
                    }
                }
            }
        ]

    def _execute_tool(self, function_name: str, function_args: dict) -> str:
        """Execute a tool and return result"""
        
        if function_name == "form_hypothesis":
            return self._tool_form_hypothesis(function_args)
        elif function_name == "plan_subtasks":
            return self._tool_plan_subtasks(function_args)
        elif function_name == "dispatch_data_agents":
            return self._tool_dispatch_data_agents(function_args)
        elif function_name == "analyze_results":
            return self._tool_analyze_results(function_args)
        elif function_name == "pivot_strategy":
            return self._tool_pivot_strategy(function_args)
        elif function_name == "declare_resolved":
            return function_args  # Return args for final response building
        elif function_name == "declare_impossible":
            return function_args  # Return args for final response building
        else:
            return f"Unknown tool: {function_name}"

    def _tool_form_hypothesis(self, args: dict) -> str:
        """Tool: Form hypothesis"""
        hypothesis = args.get("hypothesis", "")
        reasoning = args.get("reasoning", "")
        confidence = args.get("confidence", 0.5)
        
        # Store in mental model
        self.mental_model["hypotheses"].append({
            "round": self.current_round,
            "hypothesis": hypothesis,
            "reasoning": reasoning,
            "confidence": confidence
        })
        
        logger.info(f"Hypothesis: {textwrap.shorten(hypothesis, width=80, placeholder='...')}")
        return f"Hypothesis recorded with confidence {confidence}. You may now plan subtasks to test it."

    def _tool_plan_subtasks(self, args: dict) -> str:
        """Tool: Plan subtasks"""
        subtasks = args.get("subtasks", [])
        
        # Store planned subtasks for dispatch
        self.planned_subtasks = subtasks
        
        logger.info(f"Planned {len(subtasks)} subtasks")
        return f"Planned {len(subtasks)} subtasks. Call dispatch_data_agents to execute them."

    def _tool_dispatch_data_agents(self, args: dict) -> str:
        """Tool: Dispatch data agents"""
        if not self.planned_subtasks:
            return "Error: No subtasks planned. Call plan_subtasks first."
        
        # Import here to avoid circular dependency
        from services.data_agent import run_data_agent
        
        # Mark that we've dispatched this round
        self.has_dispatched_this_round = True
        
        # Run data agents in parallel
        results = []
        logger.info(f"Dispatching {len(self.planned_subtasks)} data agents")
        
        try:
            with ThreadPoolExecutor(max_workers=min(5, len(self.planned_subtasks))) as executor:
                future_to_task = {
                    executor.submit(run_data_agent, subtask, self.intent): subtask 
                    for subtask in self.planned_subtasks
                }
                
                for future in as_completed(future_to_task):
                    subtask = future_to_task[future]
                    try:
                        result = future.result()
                        agent_result = AgentResult(
                            subtask=subtask,
                            ok=result.ok,
                            data=result.data,
                            executed_code=result.executed_code,
                            errors=result.errors,
                            logs=result.logs,
                            duration_sec=result.duration_sec or 0.0
                        )
                        results.append(agent_result)
                        self.all_data_agent_results.append(agent_result)
                    except Exception as e:
                        logger.error(f"Data agent execution failed: {e}")
                        agent_result = AgentResult(
                            subtask=subtask,
                            ok=False,
                            errors=[f"Agent execution error: {str(e)}"],
                            duration_sec=0.0
                        )
                        results.append(agent_result)
                        self.all_data_agent_results.append(agent_result)
        except Exception as e:
            logger.error(f"Fatal error during dispatch: {e}")
            return f"Error: Failed to dispatch data agents: {str(e)}"
        
        # Clear planned subtasks after dispatch
        self.planned_subtasks = None
        
        # Format results for LLM
        results_summary = self._format_results_for_llm(results)
        
        # Increment round counter AFTER successful dispatch
        self.current_round += 1
        
        logger.info(f"Dispatched {len(results)} agents, moving to round {self.current_round}")
        return f"Data agents executed. Results:\n{results_summary}\n\nYou MUST now call analyze_results to interpret these outcomes."

    def _tool_analyze_results(self, args: dict) -> str:
        """Tool: Analyze results"""
        analysis = args.get("analysis", "")
        validates = args.get("validates_hypothesis", False)
        insights = args.get("insights", "")
        
        # Store insights
        self.mental_model["insights"].append({
            "round": self.current_round - 1,  # Previous round since we increment after dispatch
            "analysis": analysis,
            "validates_hypothesis": validates,
            "insights": insights
        })
        
        # Reset dispatch flag after analysis
        self.has_dispatched_this_round = False
        
        logger.info(f"Analysis: {'Validated' if validates else 'Invalidated'} hypothesis")
        return f"Analysis recorded. Based on your insights: {insights}\n\nDecide next action: declare_resolved, pivot_strategy, or form new hypothesis for round {self.current_round}."

    def _tool_pivot_strategy(self, args: dict) -> str:
        """Tool: Pivot strategy"""
        failed = args.get("failed_approach", "")
        why_failed = args.get("why_failed", "")
        new_strategy = args.get("new_strategy", "")
        
        # Record failure
        self.mental_model["failed_approaches"].append({
            "round": self.current_round,
            "approach": failed,
            "reason": why_failed
        })
        
        logger.info(f"Pivoting from '{failed[:50]}...' to '{new_strategy[:50]}...'")
        return f"Strategy pivot recorded. Previous approach failed: {why_failed}\n\nNew strategy: {new_strategy}\n\nForm a hypothesis for this new approach."

    def _format_results_for_llm(self, results: List[AgentResult]) -> str:
        """Format data agent results for LLM consumption"""
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"\nSubtask {i}: {r.subtask['query']}")
            lines.append(f"  Success: {r.ok}")
            lines.append(f"  Duration: {r.duration_sec:.1f}s")
            
            if r.ok and r.data:
                data_str = str(r.data)[:300]
                lines.append(f"  Data: {data_str}{'...' if len(str(r.data)) > 300 else ''}")
            else:
                lines.append(f"  Data: None")
            
            if r.errors:
                lines.append(f"  Errors: {', '.join(r.errors[:2])}")
        
        return "\n".join(lines)

    def _format_agent_results(self) -> List[dict]:
        """Format all agent results for final response"""
        return [
            {
                "subtask": r.subtask,
                "ok": r.ok,
                "data": r.data,
                "executed_code": r.executed_code,
                "errors": r.errors,
                "logs": r.logs,
                "duration": r.duration_sec
            }
            for r in self.all_data_agent_results
        ]

    def _build_final_response(self, resolved: bool, tool_result: dict, duration: float) -> dict:
        """Build final response structure"""
        return {
            "ok": resolved,
            "task": self.task_spec,
            "final_data": tool_result.get("final_answer") if resolved else None,
            "reasoning_trace": self.mental_model,
            "executed_code": [r.executed_code for r in self.all_data_agent_results if r.executed_code],
            "errors": [] if resolved else [tool_result.get("reason", "Unknown error")],
            "logs": [f"Round {self.current_round}: {'Resolved' if resolved else 'Impossible'}"],
            "agents": self._format_agent_results(),
            "iterations": self.current_round,
            "failure_reason": None if resolved else tool_result.get("reason"),
            "duration_sec": duration,
            "confidence": tool_result.get("confidence", 0.0) if resolved else 0.0,
            "supporting_evidence": tool_result.get("supporting_evidence") if resolved else None
        }


# Drop-in replacement function for backwards compatibility
def execute_task_v2(task_spec: dict, schema_bundle: dict, intent: str) -> dict:
    """Drop-in replacement for old executor_agent function"""
    executor = ExecutorAgent()
    return executor.execute_task(task_spec, schema_bundle, intent)