import logging
from typing import List, Dict, Any, Optional
from openai import OpenAI
import os
import json
import json_repair
import asyncio
from dotenv import load_dotenv
from services.executor_agent import executor_agent
from services.data_agent import get_schema_bundle

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI()



def extract_json_block(text: str) -> dict:
    """
    Bulletproof JSON extraction from LLM output using json_repair.
    Handles malformed JSON, trailing commas, single quotes, comments, etc.
    """
    import re
    
    # Clean up markdown code fences
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = re.sub(r'```\s*$', '', text)
    text = text.strip()
    
    # First try standard JSON parsing
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Use json_repair for robust parsing
    try:
        return json_repair.loads(text)
    except Exception as e:
        logger.error(f"Could not extract JSON: {e}, text[:200]={text[:200]!r}")
        return {"error": "Failed to parse JSON"}


class PlannerAgent:
    """LLM-driven Planner Agent for generating and managing execution plans"""
    
    def __init__(self):
        self.current_plan: List[Dict[str, Any]] = []
        self.plan_id_counter: int = 0
        self.collected_results: List[Dict[str, Any]] = []
        self.broadcast_callback = None
        self.conversation_history: List[Dict[str, Any]] = []
        self._pending_broadcast: bool = False
        self._pending_status: Optional[str] = None

    def _get_system_prompt(self) -> str:
        """Generate current system prompt with latest context"""
        # Build current plan context
        if self.current_plan:
            plan_context = "\n".join([f"- {step['text']} ({step['status']})" for step in self.current_plan])
        else:
            plan_context = "No current plan exists."
        
        # Get schema context
        try:
            schema_context = json.dumps(get_schema_bundle(), indent=2)
        except Exception as e:
            logger.error(f"Could not load schema bundle: {e}")
            schema_context = "{}"
        
        return f"""You are the Planner Agent in a multi-agent system for analyzing UAV (unmanned aerial vehicle) flight logs.

    The system has multiple roles:
    - Planner Agent (you): Creates and manages the execution plan. You use tools to update plans and execute steps.
    - Executor Agent: Takes one of your tasks, spawns Data Agents, and performs the actual queries/analyses against the database.
    - Data Agents: Perform atomic queries or analyses on the database (SQL, computations).
    - Frontend: Displays the plan and its live updates to the user.

    Keep the plan minimal, ideally 1–3 steps. If you can get the answer with 1 step, do not create a plan with more than 1 step.
    But, if the tasks needs multiple steps, create a plan with multiple steps or add more steps to the plan once you get more information.
    ALSO THE PLAN SHOULD CONSIST OF LIKE BROAD SEMANTIC STEPS. NOT REALLY SPECIFIC ON THE DATA. EACH STEP IN THE PLAN GETS HANDED OFF TO THE EXECUTOR AGENT.

    You have access to these tools:
    - update_plan: Create or modify the execution plan
    - execute_step: Execute a single step using the executor agent
    - broadcast_status: Send status messages to the frontend

    Current plan:
    {plan_context}

    Schema bundle (tables, fields, metadata):
    {schema_context}

    Your workflow:
    1. Understand the user's request and create a plan using update_plan
    2. Execute steps one by one using execute_step
    3. Use broadcast_status to keep users informed of progress
    4. Adapt the plan based on results by calling update_plan again if needed
    5. Provide a final comprehensive answer

    When the Executor finishes a step, it will return a detailed report
    including: final_data, reasoning_trace, executed_code, errors, and iterations.
    Use this information to:
    - Decide if the step resolved the user’s question or if more steps are needed
    - Adjust future steps if errors occurred or if the Executor struggled
    - Include Executor reasoning and executed_code summaries in your final answer for transparency

    

    Use broadcast_status sparingly for brief explanations of your reasoning:
    - "Checking GPS data for alt readings..."
    - "Found multiple alt sources, comparing values..."
    - "Found a anomaly in x data source, adjusting plan..."
    - "Calculating maximum from 1,247 GPS readings..."

    Keep messages under 10 words and focus on what you're analyzing, not what tools you're using.
    

    Rules:
    - Never write SQL or code yourself
    - Keep plan steps semantic and high-level
    - Always broadcast plan updates so the frontend stays current
    - Execute steps sequentially and adapt based on results
    - Provide clear, comprehensive final answers
    
    When you call execute_step, also provide a detailed intent explaining why this step matters, what its scope is, and what outcome is expected. 
    Think of it as briefing the Executor so it shares your reasoning. Please construct a natural language intent that includes four layers: 
    high-level purpose (why the user wants this), role of this step (how it contributes to the plan), expected outcome (what success looks like), 
    and scope/constraints (what to focus on and ignore)."""


    # This method serves as the main entry point for generating a planner agent response to a user's message.
    # It initiates a continuous conversation loop with tool access, handling plan creation, step execution, and broadcasting updates.
    async def generate_response(self, user_message: str, broadcast_callback=None) -> str:
        """Generate a planner response using continuous conversation with tools"""
        logger.info(f"Planner Agent processing: {user_message}")
        
        # Set broadcast callback for tools
        self.broadcast_callback = broadcast_callback
        
        # Use continuous conversation with tools
        response = await self._continuous_conversation(user_message)
                
        logger.info(f"Planner Agent response: {response}")
        return response


    # Continuous conversation is an iterative loop where the planner agent interacts with the LLM, 
    # invoking tools (like plan updates, step execution, and status broadcasts) as needed to fulfill the user's request. 
    # This approach enables dynamic, adaptive planning and execution by allowing the agent to reason, update its plan, 
    # and respond to results in real time, ensuring a flexible and robust workflow.
    async def _continuous_conversation(self, user_message: str) -> str:
        """Continuous conversation with tool access"""

        # Define tools for the LLM: update_plan, execute_step, broadcast_status
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "update_plan",
                    "description": "Update the current plan with new steps. IDs will be auto-generated.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "steps": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "text": {"type": "string"},
                                        "status": {"type": "string", "enum": ["pending", "active", "done", "failed"]}
                                    },
                                    "required": ["text", "status"]
                                }
                            }
                        },
                        "required": ["steps"]
                    }
                }
            },
            {
                "type": "function", 
                "function": {
                    "name": "execute_step",
                    "description": "Execute a single step using the executor agent. Pass the step ID from the current plan.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "step_id": {"type": "integer", "description": "The numeric ID of the step from the plan"}
                        },
                        "required": ["step_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "broadcast_status", 
                    "description": "Send status message to frontend",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {"type": "string"}
                        },
                        "required": ["message"]
                    }
                }
            }
        ]
        
        # Always update system prompt with current context
        current_system_prompt = self._get_system_prompt()
        
        # Update or create system message
        if self.conversation_history and self.conversation_history[0]["role"] == "system":
            self.conversation_history[0]["content"] = current_system_prompt
        else:
            self.conversation_history.insert(0, {"role": "system", "content": current_system_prompt})
        
        # Add user message to history
        self.conversation_history.append({"role": "user", "content": user_message})
        
        # Use conversation history for messages
        messages = self.conversation_history.copy()
        
        # Conversation loop
        max_iterations = 20
        for iteration in range(max_iterations):
            try:
                logger.info(f"Conversation iteration {iteration + 1}/{max_iterations}")
                
                response = client.chat.completions.create(
                    model="gpt-4.1-mini",
                    messages=messages,
                    tools=tools,
                    tool_choice="auto"
                    )
                
                message = response.choices[0].message
                logger.info(f"LLM response - has tool calls: {bool(message.tool_calls)}")
                
                # Convert message object to dict for proper storage
                message_dict = {
                    "role": message.role,
                    "content": message.content
                }
                
                # Handle tool_calls if present
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
                
                # Add to both message lists
                messages.append(message)  # Use original for API compatibility
                self.conversation_history.append(message_dict)  # Store dict version for persistence
                
                # Check if LLM wants to use tools
                if message.tool_calls:
                    logger.info(f"Processing {len(message.tool_calls)} tool calls")
                    
                    for tool_call in message.tool_calls:
                        try:
                            function_name = tool_call.function.name
                            function_args_str = tool_call.function.arguments
                            
                            logger.info(f"Executing tool: {function_name}")
                            logger.info(f"Tool arguments: {function_args_str}")
                            
                            # Parse tool arguments
                            try:
                                function_args = json.loads(function_args_str)
                            except json.JSONDecodeError as parse_error:
                                logger.error(f"Failed to parse tool arguments: {parse_error}")
                                result = f"Error: Invalid JSON in tool arguments: {str(parse_error)}"
                            else:
                                # Execute tool
                                if function_name == "update_plan":
                                    if "steps" in function_args:
                                        result = await self.update_plan(function_args["steps"])
                                    else:
                                        result = "Error: Missing 'steps' parameter for update_plan"
                                        
                                elif function_name == "execute_step":
                                    if "step_id" in function_args:
                                        result = await self.execute_step(function_args["step_id"])
                                    else:
                                        result = "Error: Missing 'step_id' parameter for execute_step"
                                        
                                elif function_name == "broadcast_status":
                                    if "message" in function_args:
                                        result = await self.broadcast_status(function_args["message"])
                                    else:
                                        result = "Error: Missing 'message' parameter for broadcast_status"
                                else:
                                    result = f"Error: Unknown tool function '{function_name}'"
                                    logger.error(f"Unknown tool function: {function_name}")
                            
                            # Add tool result to conversation
                            tool_message = {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": str(result)
                            }
                            
                            messages.append(tool_message)
                            self.conversation_history.append(tool_message)
                            
                            logger.info(f"Tool {function_name} result: {str(result)}...")
                            
                        except Exception as tool_error:
                            logger.error(f"Error executing tool {tool_call.function.name}: {tool_error}")
                            import traceback
                            traceback.print_exc()
                            
                            # Add error result to conversation
                            error_message = {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": f"Tool execution error: {str(tool_error)}"
                            }
                            messages.append(error_message)
                            self.conversation_history.append(error_message)
                    
                    # Continue conversation loop after processing tools
                    continue
                    
                else:
                    # LLM provided final response without tool calls
                    logger.info("LLM provided final response")
                    final_response = message.content if message.content else "Analysis complete."
                    return final_response
                    
            except Exception as e:
                logger.error(f"Error in conversation iteration {iteration + 1}: {e}")
                import traceback
                traceback.print_exc()
                return f"Error during analysis: {str(e)}"
        
        # Max iterations reached
        logger.warning(f"Conversation reached maximum iterations ({max_iterations})")
        return "Analysis incomplete - maximum iterations reached. Please try asking a simpler question or break your request into smaller parts."

    def _generate_intent_briefing(self, step_description: str, user_query: str, step_id: int) -> str:
        """Generate rich but lightweight intent briefing for Executor"""
        briefing = {
            "conversation": self._extract_conversation_context(),
            "previous_results": self._get_previous_step_context(step_id),
            "planner_reasoning": step_description,   # this is the Planner's own reasoning
            "execute": step_description,
            "step_linkage": f"Step {step_id} connects prior context to this action"
        }
        return json.dumps(briefing, indent=2)
    
    def _extract_conversation_context(self) -> str:
        """Extract user's deeper intent from conversation history"""
        user_messages = [msg for msg in self.conversation_history if msg.get("role") == "user"]
        if len(user_messages) > 1:
            return f"User's evolving intent: {user_messages[-1].get('content', '')}"
        return ""
    
    def _get_previous_step_context(self, current_step_id: int) -> str:
        """Get context from previous step results"""
        if current_step_id > 1 and self.collected_results:
            last_result = self.collected_results[-1]
            return f"From step {current_step_id - 1}: {last_result.get('data', 'No data')}..."
        return ""
    
    def _split_step_description(self, step_text: str) -> tuple:
        """Split step description into reasoning and action components"""
        # For now, treat the entire step text as both reasoning and action
        # This can be enhanced later to parse structured step descriptions
        return step_text, step_text
    



    def get_current_plan(self) -> List[Dict[str, Any]]:
        """Get the current plan"""
        return self.current_plan.copy()
        
    def set_plan(self, plan: List[Dict[str, Any]]) -> None:
        """Set a new plan"""
        self.current_plan = plan.copy()
        if plan:
            self.plan_id_counter = max(step.get('id', 0) for step in plan)
        else:
            self.plan_id_counter = 0
        
            

    async def update_plan(self, steps: List[Dict[str, Any]]) -> str:
        """Tool: Update the current plan with new steps"""
        # DON'T reset counter - just keep incrementing
        new_steps = []
        
        for step in steps:
            self.plan_id_counter += 1  # Keeps going: 1,2,3 then 4,5,6 etc
            new_steps.append({
                "id": self.plan_id_counter,
                "text": step["text"],
                "status": step.get("status", "pending")
            })
        
        self.current_plan = new_steps
        
        if self.broadcast_callback:
            await self.broadcast_callback()
        
        logger.info(f"Plan updated with {len(new_steps)} steps: {[step['text'] for step in new_steps]}")
        plan_summary = [f"ID {step['id']}: {step['text']} ({step['status']})" for step in new_steps]
        return f"Plan updated with {len(new_steps)} steps. Current plan: {plan_summary}"


    async def execute_step(self, step_id: int) -> str:
        """Tool: Execute a single step using the executor agent"""
        logger.info(f"Executing step ID: {step_id}")

        # Track step failures by ID
        if not hasattr(self, '_step_failures'):
            self._step_failures = {}
        self._step_failures[step_id] = self._step_failures.get(step_id, 0) + 1

        if self._step_failures[step_id] >= 2:
            step_obj = next((s for s in self.current_plan if s["id"] == step_id), None)
            if step_obj:
                step_obj["status"] = "failed"
            if self.broadcast_callback:
                await self.broadcast_callback()
            return "Step failed twice - moving to next step"

        # Find the step by ID
        step_obj = next((s for s in self.current_plan if s["id"] == step_id), None)
        if not step_obj:
            logger.warning(f"Step ID not found in plan: {step_id}")
            return f"Error: Step ID {step_id} not found in plan"

        # Mark active
        step_obj["status"] = "active"
        if self.broadcast_callback:
            await self.broadcast_callback()

        try:
            schema_bundle = get_schema_bundle()
            if not schema_bundle:
                step_obj["status"] = "failed"
                if self.broadcast_callback:
                    await self.broadcast_callback()
                return "Error: No schema available - cannot execute without data context"

            # Build task spec
            reasoning, action = self._split_step_description(step_obj["text"])
            task_spec = {
                "query": action,
                "type": "analysis",
                "priority": "medium"
            }

            # Get most recent user query
            current_user_query = next(
                (msg.get("content", "Unknown query") for msg in reversed(self.conversation_history) if msg.get("role") == "user"),
                "Unknown query"
            )

            # Build intent briefing
            intent = self._generate_intent_briefing(step_obj["text"], current_user_query, step_id)
            logger.debug("Here is the intent: " + intent)

            # Call executor agent
            result = await asyncio.get_event_loop().run_in_executor(
                None, executor_agent, task_spec, schema_bundle, intent
            )

            # Update status
            step_obj["status"] = "done" if result.get("ok", False) else "failed"
            if self.broadcast_callback:
                await self.broadcast_callback()

            if result.get("ok", False):
                if "final_data" in result:
                    self.collected_results.append({
                        "step": step_obj["text"],
                        "data": result.get("final_data", "No data"),
                        "executor_reasoning": result.get("reasoning_trace", []),
                        "errors": result.get("errors", []),
                        "executed_code": result.get("executed_code", []),
                        "iterations": result.get("iterations", 1)
                    })
                logger.info(f"Step completed successfully: {step_obj['text']}")
                return f"Step executed successfully. Results: {result.get('final_data', 'No data returned')}"
            else:
                logger.error(f"Step failed: {step_obj['text']} - {result.get('error', 'Unknown error')}")
                return f"Step execution failed: {result.get('error', 'Unknown error')}"

        except Exception as e:
            logger.error(f"Error executing step: {e}")
            step_obj["status"] = "failed"
            if self.broadcast_callback:
                await self.broadcast_callback()
            return f"Step execution error: {str(e)}"



    async def broadcast_status(self, message: str) -> str:
        """Tool: Send status message to frontend"""
        logger.info(f"Broadcasting status: {message}")
        # IMMEDIATE broadcast instead of pending
        if self.broadcast_callback:
            await self.broadcast_callback({"status_message": message})
        return f"Status message sent: {message}"



# Global planner instance
planner_agent = PlannerAgent()
