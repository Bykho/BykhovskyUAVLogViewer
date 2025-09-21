import os, time, json, logging
from dotenv import load_dotenv
from openai import OpenAI
from typing import Any, Dict, List, Optional, Union
from models import (
    ChatRequest, ChatReply, ToolCallRequest, ToolCallReply,
    ToolReplyRequest, ToolReplyResponse, MetricResult,
    SessionBundle, SessionResponse
)
from metrics_compute import (
    metrics_compute_max_altitude,
    metrics_compute_flight_time,
    metrics_compute_first_gps_loss,
    metrics_compute_max_battery_temp,
    metrics_compute_first_rc_loss,
    metrics_compute_critical_errors,
    metrics_compute_available_streams,
    metrics_compute_missing_segments
)

from prompts import (
    TOOL_DEFINITIONS,
    TOOL_SYSTEM_PROMPT
)
from escalate import escalate
from analysis_functions import (
    analyze_statistical_outliers_pure,
    analyze_baseline_pure,
    trace_causal_chains_pure,
    calculate_rolling_statistics,
    detect_outliers_with_dynamic_thresholds
)

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

sessions: Dict[str, SessionBundle] = {}
pending_conversations: Dict[str, Dict[str, Any]] = {}
escalation_history: Dict[str, List[Dict[str, Any]]] = {}
escalation_counters: Dict[str, int] = {}

TOOL_FUNCTIONS = {
    "telemetry_index": None,
    "metrics_compute": None,
    "telemetry_slice": "bridge_tool",
    "analyze_flight_baseline": None,
    "detect_statistical_outliers": None,
    "trace_causal_chains": None,
}


# Tool implementations
def telemetry_index(session_id: str) -> Dict[str, Any]:
    """Get stream inventory and metadata for a session"""
    if session_id not in sessions:
        return {
            "ok": False,
            "error": f"Session {session_id} not found",
            "streams": {},
            "meta": {}
        }
    
    session = sessions[session_id]
    return {
        "ok": True,
        "streams": session.index,
        "meta": session.meta,
        "event_count": len(session.events),
        "downsample_available": list(session.downsample1Hz.keys())
    }


def metrics_compute(session_id: str, metric: str) -> MetricResult:
    """Compute specific metric from session data"""
    if session_id not in sessions:
        return MetricResult(
            name=metric,
            ok=False,
            value=None,
            units="",
            t_ms=None,
            method="",
            source="",
            notes=f"Session {session_id} not found"
        )
    
    session = sessions[session_id]
    if metric == "max_altitude":
        return metrics_compute_max_altitude(session)
    elif metric == "flight_time":
        return metrics_compute_flight_time(session)
    elif metric == "first_gps_loss":
        return metrics_compute_first_gps_loss(session)
    elif metric == "first_rc_loss":
        return metrics_compute_first_rc_loss(session)
    elif metric == "max_battery_temp":
        return metrics_compute_max_battery_temp(session)
    elif metric == "critical_errors":
        return metrics_compute_critical_errors(session)
    elif metric == "available_streams":
        return metrics_compute_available_streams(session)
    elif metric == "missing_segments":
        return metrics_compute_missing_segments(session)
    else:
        return MetricResult(
            name=metric,
            ok=False,
            value=None,
            units="",
            t_ms=None,
            method="",
            source="",
            notes=f"Unknown metric: {metric}"
        )


# Helper function to clean data for JSON serialization
def clean_for_json_serialization(data):
    """Clean data to ensure it can be JSON serialized"""
    if isinstance(data, dict):
        return {k: clean_for_json_serialization(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [clean_for_json_serialization(item) for item in data]
    elif isinstance(data, float):
        # Handle NaN and Infinity values
        if data != data:  # NaN check
            return None
        elif data == float('inf') or data == float('-inf'):
            return None
        else:
            return data
    elif isinstance(data, (int, str, bool, type(None))):
        return data
    else:
        # Convert other types to string
        return str(data)


# Helper function to get telemetry data internally (backend version of telemetry_slice)
def get_telemetry_data_internal(session_id: str, stream: str, fields: List[str] = None, 
                               start_ms: int = None, end_ms: int = None, max_points: int = 5000) -> Dict[str, Any]:
    """Get telemetry data for analysis - backend version of frontend telemetry_slice"""
    if session_id not in sessions:
        return {"ok": False, "error": f"Session {session_id} not found", "rows": [], "count": 0}
    
    session = sessions[session_id]
    
    # Use the same downsample1Hz data that working metrics use
    # Convert stream name to lowercase key (GLOBAL_POSITION_INT -> global_position_int or gpos)
    stream_key = stream.lower()
    if stream == "GLOBAL_POSITION_INT":
        stream_key = "gpos"  # Use the same key as your working metrics
    elif stream == "GPS_RAW_INT":
        stream_key = "gps"
    elif stream == "VFR_HUD":
        stream_key = "alt"
        
    stream_data = session.downsample1Hz.get(stream_key, [])
    if not stream_data:
        return {"ok": False, "error": f"No data for stream {stream} (key: {stream_key})", "rows": [], "count": 0}
    
    # Convert the downsample format to records format that statistical functions expect
    records = []
    for item in stream_data:
        record = {"time_boot_ms": item.get("t", 0)}  # Add timestamp
        
        # Map downsample fields to expected field names
        if stream == "GLOBAL_POSITION_INT":
            record.update({
                "alt": item.get("relAltM"),  # relative altitude
                "vx": item.get("vx", 0) / 100 if item.get("vx") else 0,  # Convert cm/s to m/s
                "vy": item.get("vy", 0) / 100 if item.get("vy") else 0,
                "vz": item.get("vz", 0) / 100 if item.get("vz") else 0,
            })
        
        # Filter to requested fields if specified
        if fields:
            filtered_record = {"time_boot_ms": record["time_boot_ms"]}
            for field in fields:
                if field in record:
                    filtered_record[field] = record[field]
            record = filtered_record
            
        records.append(record)
    
    # Apply time filtering if specified
    if start_ms is not None or end_ms is not None:
        records = [r for r in records 
                  if (start_ms is None or r["time_boot_ms"] >= start_ms) and 
                     (end_ms is None or r["time_boot_ms"] <= end_ms)]
    
    # Apply max_points limit
    if len(records) > max_points:
        records = records[:max_points]
    
    return {
        "ok": True,
        "rows": records,
        "count": len(records),
        "stream": stream,
        "fields": fields or list(records[0].keys()) if records else []
    }

# Statistical analysis functions that use telemetry_slice internally
def analyze_flight_baseline_impl(session_id: str, stream: str, fields: List[str], window_size_ms: int = 30000) -> Dict[str, Any]:
    """Calculate statistical baselines for telemetry streams within a flight - returns bridge request"""
    if session_id not in sessions:
        return {
            "ok": False,
            "error": f"Session {session_id} not found",
            "methodology": "Session validation",
            "findings": {},
            "confidence": 0.0,
            "data_quality": "Session not found"
        }
    
    # Return bridge request instead of fetching data
    return {
        "type": "bridge_request_with_analysis",
        "tool": "telemetry_slice",
        "analysis_tool": "analyze_flight_baseline",
        "params": {
            "sessionId": session_id,
            "stream": stream,
            "fields": fields,
            "max_points": 10000
        },
        "analysis_params": {
            "fields": fields,
            "window_size_ms": window_size_ms
        }
    }


def detect_statistical_outliers_impl(session_id: str, stream: str, fields: List[str], 
                                   threshold_sigma: float = 2.5, window_size_ms: int = 30000) -> Dict[str, Any]:
    """Detect statistical outliers in telemetry data using dynamic thresholds - returns bridge request"""
    if session_id not in sessions:
        return {
            "ok": False,
            "error": f"Session {session_id} not found",
            "methodology": "Session validation",
            "findings": {},
            "confidence": 0.0,
            "data_quality": "Session not found"
        }
    
    # Return bridge request instead of fetching data
    return {
        "type": "bridge_request_with_analysis",
        "tool": "telemetry_slice",
        "analysis_tool": "detect_statistical_outliers",
        "params": {
            "sessionId": session_id,
            "stream": stream,
            "fields": fields,
            "max_points": 10000
        },
        "analysis_params": {
            "fields": fields,
            "threshold_sigma": threshold_sigma,
            "window_size_ms": window_size_ms
        }
    }


def trace_causal_chains_impl(session_id: str, target_timestamp_ms: int, time_window_ms: int = 30000) -> Dict[str, Any]:
    """Find STATUSTEXT events that may be causally related to a target timestamp - returns bridge request"""
    if session_id not in sessions:
        return {
            "ok": False,
            "error": f"Session {session_id} not found",
            "methodology": "Session validation",
            "findings": {},
            "confidence": 0.0,
            "data_quality": "Session not found"
        }
    
    # Return bridge request instead of fetching data
    # For causal chains, we need events data, so we'll request a special "events" stream
    return {
        "type": "bridge_request_with_analysis",
        "tool": "telemetry_slice",
        "analysis_tool": "trace_causal_chains",
        "params": {
            "sessionId": session_id,
            "stream": "events",  # Special stream for events data
            "fields": ["text", "severity", "t"],  # Event fields we need
            "max_points": 10000
        },
        "analysis_params": {
            "target_timestamp_ms": target_timestamp_ms,
            "time_window_ms": time_window_ms
        }
    }

# Register tool functions
TOOL_FUNCTIONS["telemetry_index"] = telemetry_index
TOOL_FUNCTIONS["metrics_compute"] = metrics_compute
TOOL_FUNCTIONS["analyze_flight_baseline"] = analyze_flight_baseline_impl
TOOL_FUNCTIONS["detect_statistical_outliers"] = detect_statistical_outliers_impl
TOOL_FUNCTIONS["trace_causal_chains"] = trace_causal_chains_impl
TOOL_FUNCTIONS["escalate"] = escalate

# Session management services
def create_session_service(bundle: SessionBundle) -> SessionResponse:
    """Create a new session with session bundle data"""
    # Copy from app.py lines 1285-1306 (def create_session function body)
    # Replace: ValueError(status_code=400, detail="...") -> ValueError("...")
    # Replace: ValueError(status_code=500, detail=str(e)) -> RuntimeError(str(e))
    try:
        # Validate required fields
        if not bundle.sessionId:
            raise ValueError("sessionId is required")
        
        if not bundle.meta or not bundle.index:
            raise ValueError("meta and index are required")
        
        # Store session bundle
        sessions[bundle.sessionId] = bundle
        
        print(f"Session {bundle.sessionId} created with {len(bundle.index)} streams")
        
        return SessionResponse(
            sessionId=bundle.sessionId,
            status="created",
            message=f"Session created with {len(bundle.index)} streams"
        )
        
    except Exception as e:
        raise RuntimeError(str(e))


def get_session_service(session_id: str):
    if session_id not in sessions:
        raise ValueError("Session not found")
    
    return sessions[session_id]


def delete_session_service(session_id: str) -> SessionResponse:
    if session_id not in sessions:
        raise ValueError("Session not found")
    
    del sessions[session_id]
    
    return SessionResponse(
        sessionId=session_id,
        status="deleted",
        message="Session deleted"
    )


def list_sessions_service() -> List[str]:
    return list(sessions.keys())


# Chat and tool calling services
def chat_with_tools_service(req: ToolCallRequest) -> ToolCallReply:
    """New chat endpoint with OpenAI tool-calling"""
    start_time = time.time()
    last_tool_result = None
    tool_execution_log = []  # Track tool execution for frontend widget
    
    try:
        # Clean up any existing pending conversation for this session
        # This prevents state corruption when starting a new conversation
        # BUT preserve conversation if escalation feedback is pending
        if req.sessionId in pending_conversations:
            conversation = pending_conversations[req.sessionId]
            escalation_feedback_pending = conversation.get("escalation_feedback_pending", False)
            
            if escalation_feedback_pending:
                print(f"Preserving conversation for session {req.sessionId} - escalation feedback pending")
            else:
                print(f"Cleaning up existing pending conversation for session {req.sessionId}")
                print(f"Pending calls before cleanup: {list(conversation['pending_calls'].keys())}")
                del pending_conversations[req.sessionId]
                print(f"Successfully cleaned up session {req.sessionId}")
                # Reset escalation counter for new conversation
                if req.sessionId in escalation_counters:
                    del escalation_counters[req.sessionId]
                    print(f"[ESCALATION] Reset counter for session {req.sessionId}")
        else:
            # New conversation - reset escalation counter
            if req.sessionId in escalation_counters:
                del escalation_counters[req.sessionId]
                print(f"[ESCALATION] Reset counter for session {req.sessionId}")
        
        # Initialize messages with system prompt
        system_prompt = TOOL_SYSTEM_PROMPT + f"\n\nCurrent session ID: {req.sessionId}"
        print(f"[SYSTEM PROMPT] Length: {len(system_prompt)} chars")
        print(f"[SYSTEM PROMPT] Contains reasoning instruction: {'reasoning' in system_prompt.lower()}")
        messages = [
            {"role": "system", "content": system_prompt}
        ] + req.messages
        
        # Tool-calling loop with timeout protection
        max_iterations = 5
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            # ADD CONVERSATION STATE LOGGING:
            print(f"[CONVERSATION STATE {iteration}] Messages: {len(messages)}")
            print(f"[CONVERSATION STATE {iteration}] Last 2 message roles: {[m['role'] for m in messages[-2:]]}")
            
            if iteration > 1:  # Only log on resume iterations
                print(f"[RESUME] continuing reasoning; prior_iter={iteration-1} messages={len(messages)}")
            
            # Call OpenAI with tools
            print(f"[ITER {iteration}] -> calling OpenAI; messages={len(messages)}")
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.0,
                max_tokens=15000
            )
            
            # ADD TOKEN USAGE LOGGING:
            print(f"[TOKENS] Used: {response.usage.total_tokens}, Completion: {response.usage.completion_tokens}")
            
            message = response.choices[0].message
            
            # ADD LLM REASONING VISIBILITY:
            print(f"[LLM REASONING {iteration}] Assistant content: {message.content}")
            if message.tool_calls:
                print(f"[LLM REASONING {iteration}] Tool decisions:")
                for tc in message.tool_calls:
                    print(f"  - {tc.function.name}: {tc.function.arguments}")
            
            print(f"[ITER {iteration}] <- assistant: has_tool_calls={bool(message.tool_calls)} "
                  f"content_len={len(message.content or '') if hasattr(message,'content') else 0} "
                  f"tools={[tc.function.name for tc in (message.tool_calls or [])]}")
            
            # Ensure every message has content field (required by OpenAI API)
            message_dict = {
                "role": message.role,
                "content": message.content or ""  # Use empty string if content is None
            }
            
            # Include tool_calls if present
            if message.tool_calls:
                message_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in message.tool_calls
                ]
            
            messages.append(message_dict)

            # If any bridge tools are present, stage ONLY those and defer others
            if message.tool_calls:
                bridge_calls = [
                    tc for tc in message.tool_calls
                    if getattr(tc, "function", None) and tc.function.name == "telemetry_slice"
                ]
                if bridge_calls:
                    # Replace tool_calls in the last assistant message with only the bridge calls
                    filtered_tool_calls = [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in bridge_calls
                    ]
                    messages[-1]["tool_calls"] = filtered_tool_calls

                    # Initialize pending conversation tracking
                    session_id = req.sessionId
                    if session_id not in pending_conversations:
                        pending_conversations[session_id] = {
                            "messages": messages.copy(),
                            "pending_calls": {},
                            "iteration": iteration,
                            "start_time": start_time,
                            "tool_execution_log": tool_execution_log.copy(),
                            "escalation_feedback_pending": False,
                        }
                    else:
                        # Preserve escalation feedback pending flag when updating conversation state
                        existing_escalation_flag = pending_conversations[session_id].get("escalation_feedback_pending", False)
                        
                        pending_conversations[session_id]["messages"] = messages.copy()
                        pending_conversations[session_id]["iteration"] = iteration
                        pending_conversations[session_id]["tool_execution_log"].extend(tool_execution_log)
                        pending_conversations[session_id]["escalation_feedback_pending"] = existing_escalation_flag

                    # Register all bridge calls in pending_calls
                    for tc in bridge_calls:
                        tool_args = json.loads(tc.function.arguments)
                        call_data = {
                            "tool": tc.function.name,
                            "params": tool_args,
                            "result": None,
                        }
                        
                        # Check if this is an analysis tool that returns bridge_request_with_analysis
                        if tc.function.name in ["analyze_flight_baseline", "detect_statistical_outliers", "trace_causal_chains"]:
                            # Execute the tool to get the bridge request with analysis metadata
                            tool_result = TOOL_FUNCTIONS[tc.function.name](**tool_args)
                            if isinstance(tool_result, dict) and tool_result.get("type") == "bridge_request_with_analysis":
                                call_data["analysis_tool"] = tool_result["analysis_tool"]
                                call_data["analysis_params"] = tool_result["analysis_params"]
                                # Update params to use the bridge request params
                                call_data["params"] = tool_result["params"]
                        
                        pending_conversations[session_id]["pending_calls"][tc.id] = call_data

                    # Return a single batch bridge request for the frontend
                    return ToolCallReply(
                        reply="",
                        debug={
                            "type": "batch_bridge_request",
                            "session_id": session_id,
                            "calls": [
                                {
                                    "call_id": call_id,
                                    "tool": data["tool"],
                                    "params": data["params"],
                                }
                                for call_id, data in pending_conversations[session_id]["pending_calls"].items()
                            ],
                        },
                    )

            # Check if model wants to call tools
            if message.tool_calls:
                for tc in message.tool_calls:
                    result = execute_tool_call(tc, req.sessionId)
                    append_tool_result(messages, tc.id, tc.function.name, result)
            else:
                # Model provided final answer
                break
        
        if iteration >= max_iterations:
            print(f"Warning: Tool-calling loop hit max iterations ({max_iterations})")
        
        # Get final response - look for the last assistant message with content
        reply = "I apologize, but I encountered an issue processing your request."
        for message in reversed(messages):
            if message["role"] == "assistant" and message.get("content"):
                reply = message["content"]
                break
        
        # Escalation notes are now handled by the LLM summarizing them in the response
        
        total_duration = time.time() - start_time
        print(f"[DONE] iterations={iteration} final_chars={len(reply)}")
        print(f"[DONE] iterations={iteration} final_chars={len(reply)}")
        print(f"Chat completed in {total_duration:.3f}s after {iteration} iterations")
        
        return ToolCallReply(
            reply=reply,
            debug={
                "iterations": iteration,
                "duration_s": round(total_duration, 3),
                "lastToolResult": last_tool_result,
                "toolExecutionLog": tool_execution_log
            }
        )
        
    except Exception as e:
        print(f"Error in chat_with_tools: {str(e)}")
        raise RuntimeError(str(e))    


def tool_reply_batch_service(req: dict) -> ToolReplyResponse:
    """Handle batch tool replies to prevent duplicate tool_call_id errors"""
    tool_execution_log = []  # Track tool execution for frontend widget
    try:
        print(f"=== BATCH TOOL REPLY DEBUG ===")
        print(f"SessionId: {req.get('sessionId')}")
        print(f"Results count: {len(req.get('results', []))}")
        
        session_id = req.get('sessionId')
        results = req.get('results', [])
        
        # Check if we have a pending conversation
        if session_id not in pending_conversations:
            print(f"ERROR: Session {session_id} not found in pending conversations")
            print(f"Available pending conversations: {list(pending_conversations.keys())}")
            raise ValueError("Session not found in pending conversations")
        
        conversation = pending_conversations[session_id]
        
        # Store all results and process analysis if needed
        for result in results:
            call_id = result.get('callId')
            if call_id in conversation["pending_calls"]:
                call_data = conversation["pending_calls"][call_id]
                bridge_result = result.get('result')
                
                # Check if this is a bridge request with analysis
                if "analysis_tool" in call_data:
                    analysis_tool = call_data["analysis_tool"]
                    analysis_params = call_data["analysis_params"]
                    telemetry_data = bridge_result
                    
                    print(f"[ANALYSIS] Processing {analysis_tool} for call_id={call_id}")
                    
                    # Run the appropriate pure analysis function
                    if analysis_tool == "detect_statistical_outliers":
                        analysis_result = analyze_statistical_outliers_pure(telemetry_data, **analysis_params)
                    elif analysis_tool == "analyze_flight_baseline":
                        analysis_result = analyze_baseline_pure(telemetry_data, **analysis_params)
                    elif analysis_tool == "trace_causal_chains":
                        analysis_result = trace_causal_chains_pure(telemetry_data, **analysis_params)
                    else:
                        print(f"WARNING: Unknown analysis tool: {analysis_tool}")
                        analysis_result = bridge_result
                    
                    call_data["result"] = analysis_result
                    print(f"[ANALYSIS] Completed {analysis_tool} for call_id={call_id}")
                else:
                    # Regular bridge result, no analysis needed
                    call_data["result"] = bridge_result
                
                print(f"[BRIDGE] result received for call_id={call_id} ok={bridge_result.get('ok')} "
                      f"count={bridge_result.get('count')} fields={bridge_result.get('fields')}")
            else:
                print(f"WARNING: Call {call_id} not found in pending calls")
        
        messages = conversation["messages"]
        iteration = conversation["iteration"]
        start_time = conversation["start_time"]
        
        # Check if all pending calls are resolved
        unresolved_calls = [call_id for call_id, data in conversation["pending_calls"].items() if data["result"] is None]
        
        if unresolved_calls:
            print(f"Still waiting for {len(unresolved_calls)} more tool call(s): {unresolved_calls}")
            return ToolReplyResponse(
                status="waiting",
                message=f"Waiting for {len(unresolved_calls)} more tool call(s) to complete"
            )
        
        # All calls resolved - add all tool results to messages
        # Check for existing tool messages to prevent duplicates
        existing_tool_ids = [msg.get('tool_call_id') for msg in messages if msg.get('role') == 'tool']
        print(f"Current message tool_call_ids: {existing_tool_ids}")
        
        # Get all tool_call_ids from the last assistant message that has tool_calls
        # Only consider tool calls from the current conversation turn (not from previous conversations)
        valid_tool_call_ids = set()
        for msg in reversed(messages):
            if msg.get('role') == 'assistant' and msg.get('tool_calls'):
                # Only consider tool calls that are in our pending calls
                for tool_call in msg['tool_calls']:
                    if tool_call['id'] in conversation["pending_calls"]:
                        valid_tool_call_ids.add(tool_call['id'])
                break
        
        print(f"Valid tool_call_ids from last assistant message: {list(valid_tool_call_ids)}")
        
        for call_id, call_data in conversation["pending_calls"].items():
            # Skip if this tool_call_id already exists in the conversation
            if call_id in existing_tool_ids:
                print(f"Skipping duplicate tool_call_id: {call_id}")
                continue
            
            # Skip if this tool_call_id is not in the valid set
            if call_id not in valid_tool_call_ids:
                print(f"Skipping invalid tool_call_id: {call_id} (not found in last assistant message)")
                continue
                
            try:
                # Clean the result data to ensure JSON serialization works
                cleaned_result = clean_for_json_serialization(call_data["result"])
                content = json.dumps(cleaned_result)
                print(f"Successfully serialized result for {call_id}, content length: {len(content)}")
            except Exception as e:
                print(f"ERROR serializing result for {call_id}: {str(e)}")
                print(f"Result data: {call_data['result']}")
                raise RuntimeError(f"Failed to serialize result: {str(e)}")
            
            tool_message = {
                "role": "tool",
                "tool_call_id": call_id,
                "name": call_data["tool"],
                "content": content
            }
            messages.append(tool_message)
            print(f"Added tool message for {call_id} to conversation")
        
        # Continue the OpenAI tool-calling loop
        max_iterations = 5
        
        while iteration < max_iterations:
            iteration += 1
            if iteration > 1:  # Only log on resume iterations
                print(f"[RESUME] continuing reasoning; prior_iter={iteration-1} messages={len(messages)}")
            
            # Call OpenAI with tools
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.0,
                max_tokens=15000
            )
            
            # ADD TOKEN USAGE LOGGING:
            print(f"[TOKENS] Used: {response.usage.total_tokens}, Completion: {response.usage.completion_tokens}")
            
            message = response.choices[0].message
            
            # Ensure every message has content field (required by OpenAI API)
            message_dict = {
                "role": message.role,
                "content": message.content or ""  # Use empty string if content is None
            }
            
            # Include tool_calls if present
            if message.tool_calls:
                message_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in message.tool_calls
                ]
            
            messages.append(message_dict)
            
            # Check if model wants to call tools
            if message.tool_calls:
                for tc in message.tool_calls:
                    result = execute_tool_call(tc, req.get("sessionId"))
                    if isinstance(result, dict) and result.get("type") == "bridge_request_with_analysis":
                        # Do not immediately append a message. Instead, store in pending_conversations:
                        pending_conversations[req.get("sessionId")]["pending_calls"][tc.id] = {
                            "tool": tc.function.name,
                            "params": result["params"],
                            "analysis_tool": result["analysis_tool"],
                            "analysis_params": result["analysis_params"],
                            "result": None,
                        }
                    else:
                        append_tool_result(messages, tc.id, tc.function.name, result)
            
            # If no tool calls, we have a final response
            if not message.tool_calls:
                break
        
        # Find the final assistant message
        reply = "Analysis completed"
        for message in reversed(messages):
            if message["role"] == "assistant" and message.get("content"):
                reply = message["content"]
                break
        
        # Escalation notes are now handled by the LLM summarizing them in the response
        
        # Get the preserved tool execution log before cleanup
        preserved_log = conversation.get("tool_execution_log", [])
        
        # Clear escalation feedback pending flag since conversation is completing
        if "escalation_feedback_pending" in conversation:
            print(f"Clearing escalation feedback pending flag for session {session_id}")
        
        # Clean up the pending conversation
        del pending_conversations[session_id]
        
        total_duration = time.time() - start_time
        print(f"[DONE] iterations={iteration} final_chars={len(reply)}")
        print(f"Chat completed in {total_duration:.3f}s after {iteration} iterations")
        
        return ToolReplyResponse(
            status="completed",
            message=reply,
            debug={
                "toolExecutionLog": preserved_log + tool_execution_log
            }
        )
        
    except Exception as e:
        print(f"ERROR in tool_reply_batch: {str(e)}")
        import traceback
        traceback.print_exc()
        raise RuntimeError(str(e))


def tool_reply_service(req: ToolReplyRequest) -> ToolReplyResponse:
    """Handle tool reply from frontend and resume agent conversation"""
    tool_execution_log = []  # Track tool execution for frontend widget
    try:
        print(f"=== TOOL REPLY DEBUG ===")
        print(f"Received tool reply: call_id={req.call_id}, tool={req.tool}")
        print(f"SessionId: {req.sessionId}")
        print(f"Result type: {type(req.result)}")
        print(f"Result keys: {list(req.result.keys()) if isinstance(req.result, dict) else 'Not a dict'}")
        
        call_id = req.call_id
        session_id = req.sessionId
        
        # Check if we have a pending conversation
        if session_id not in pending_conversations:
            print(f"ERROR: Session {session_id} not found in pending conversations")
            print(f"Available pending conversations: {list(pending_conversations.keys())}")
            raise ValueError("Session not found in pending conversations")
        
        conversation = pending_conversations[session_id]
        
        # Check if this call_id is in the pending calls
        if call_id not in conversation["pending_calls"]:
            print(f"ERROR: Call {call_id} not found in pending calls for session {session_id}")
            print(f"Available pending calls: {list(conversation['pending_calls'].keys())}")
            raise ValueError("Call not found in pending calls")
        
        # Store the result for this call
        conversation["pending_calls"][call_id]["result"] = req.result
        
        messages = conversation["messages"]
        iteration = conversation["iteration"]
        start_time = conversation["start_time"]
        
        print(f"Found bridge data for {call_id}, iteration {iteration}")
        
        # Check if all pending calls are resolved
        unresolved_calls = [call_id for call_id, data in conversation["pending_calls"].items() if data["result"] is None]
        
        if unresolved_calls:
            print(f"Still waiting for {len(unresolved_calls)} more tool call(s): {unresolved_calls}")
            return ToolReplyResponse(
                status="waiting",
                message=f"Waiting for {len(unresolved_calls)} more tool call(s) to complete"
            )
        
        # All calls resolved - add all tool results to messages
        # Check for existing tool messages to prevent duplicates
        existing_tool_ids = [msg.get('tool_call_id') for msg in messages if msg.get('role') == 'tool']
        print(f"Current message tool_call_ids: {existing_tool_ids}")
        
        # Get all tool_call_ids from the last assistant message that has tool_calls
        # Only consider tool calls from the current conversation turn (not from previous conversations)
        valid_tool_call_ids = set()
        for msg in reversed(messages):
            if msg.get('role') == 'assistant' and msg.get('tool_calls'):
                # Only consider tool calls that are in our pending calls
                for tool_call in msg['tool_calls']:
                    if tool_call['id'] in conversation["pending_calls"]:
                        valid_tool_call_ids.add(tool_call['id'])
                break
        
        print(f"Valid tool_call_ids from last assistant message: {list(valid_tool_call_ids)}")
        
        for call_id, call_data in conversation["pending_calls"].items():
            # Skip if this tool_call_id already exists in the conversation
            if call_id in existing_tool_ids:
                print(f"Skipping duplicate tool_call_id: {call_id}")
                continue
            
            # Skip if this tool_call_id is not in the valid set
            if call_id not in valid_tool_call_ids:
                print(f"Skipping invalid tool_call_id: {call_id} (not found in last assistant message)")
                continue
                
            try:
                # Clean the result data to ensure JSON serialization works
                cleaned_result = clean_for_json_serialization(call_data["result"])
                content = json.dumps(cleaned_result)
                print(f"Successfully serialized result for {call_id}, content length: {len(content)}")
            except Exception as e:
                print(f"ERROR serializing result for {call_id}: {str(e)}")
                print(f"Result data: {call_data['result']}")
                raise RuntimeError(f"Failed to serialize result: {str(e)}")
            
            tool_message = {
                "role": "tool",
                "tool_call_id": call_id,
                "name": call_data["tool"],
                "content": content
            }
            messages.append(tool_message)
            print(f"Added tool message for {call_id} to conversation")
        
        # Continue the OpenAI tool-calling loop
        max_iterations = 5
        
        while iteration < max_iterations:
            iteration += 1
            if iteration > 1:  # Only log on resume iterations
                print(f"[RESUME] continuing reasoning; prior_iter={iteration-1} messages={len(messages)}")
            
            # Call OpenAI with tools
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.0,
                max_tokens=15000
            )
            
            # ADD TOKEN USAGE LOGGING:
            print(f"[TOKENS] Used: {response.usage.total_tokens}, Completion: {response.usage.completion_tokens}")
            
            message = response.choices[0].message
            
            # Ensure every message has content field (required by OpenAI API)
            message_dict = {
                "role": message.role,
                "content": message.content or ""  # Use empty string if content is None
            }
            
            # Include tool_calls if present
            if message.tool_calls:
                message_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in message.tool_calls
                ]
            
            messages.append(message_dict)
            
            # Check if model wants to call tools
            if message.tool_calls:
                for tc in message.tool_calls:
                    result = execute_tool_call(tc, req.sessionId)
                    append_tool_result(messages, tc.id, tc.function.name, result)
            else:
                # Model provided final answer
                break
        
        # Get final response - look for the last assistant message with content
        reply = "I apologize, but I encountered an issue processing your request."
        for message in reversed(messages):
            if message["role"] == "assistant" and message.get("content"):
                reply = message["content"]
                break
        
        # Escalation notes are now handled by the LLM summarizing them in the response
        
        # Get the preserved tool execution log before cleanup
        preserved_log = conversation.get("tool_execution_log", [])
        
        # Clear escalation feedback pending flag since conversation is completing
        if "escalation_feedback_pending" in conversation:
            print(f"Clearing escalation feedback pending flag for session {session_id}")
        
        # Clean up the pending conversation
        del pending_conversations[session_id]
        
        total_duration = time.time() - start_time
        print(f"[DONE] iterations={iteration} final_chars={len(reply)}")
        print(f"Chat completed in {total_duration:.3f}s after {iteration} iterations")
        
        return ToolReplyResponse(
            status="completed",
            message=reply,
            debug={
                "toolExecutionLog": preserved_log + tool_execution_log
            }
        )
        
    except Exception as e:
        print(f"ERROR in tool_reply: {str(e)}")
        print(f"Exception type: {type(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        raise RuntimeError(str(e))
    


def execute_tool_call(tool_call, session_id: str):
    """
    Run a tool call and return its raw result (dict, list, str).
    Handles normal backend tools, bridge tools, analysis bridge tools,
    and escalation with counters/history.
    """

    tool_name = tool_call.function.name
    try:
        tool_args = json.loads(tool_call.function.arguments or "{}")
    except Exception as e:
        return {"ok": False, "error": f"Invalid arguments for {tool_name}: {e}"}

    try:
        # ----- Normal Tools -----
        if tool_name == "telemetry_index":
            return TOOL_FUNCTIONS[tool_name](tool_args["sessionId"])

        elif tool_name == "metrics_compute":
            return TOOL_FUNCTIONS[tool_name](
                tool_args["sessionId"], tool_args["metric"]
            )

        # ----- Bridge Tools -----
        elif tool_name == "telemetry_slice":
            return {
                "type": "bridge_request",
                "call_id": tool_call.id,
                "tool": "telemetry_slice",
                "params": tool_args,
            }

        # ----- Analysis Bridge Tools -----
        elif tool_name == "analyze_flight_baseline":
            return {
                "type": "bridge_request_with_analysis",
                "tool": "telemetry_slice",
                "analysis_tool": "analyze_flight_baseline",
                "params": {
                    "sessionId": tool_args["sessionId"],
                    "stream": tool_args["stream"],
                    "fields": tool_args["fields"],
                    "max_points": 10000,
                },
                "analysis_params": {
                    "fields": tool_args["fields"],
                    "window_size_ms": tool_args.get("window_size_ms", 30000),
                },
            }

        elif tool_name == "detect_statistical_outliers":
            return {
                "type": "bridge_request_with_analysis",
                "tool": "telemetry_slice",
                "analysis_tool": "detect_statistical_outliers",
                "params": {
                    "sessionId": tool_args["sessionId"],
                    "stream": tool_args["stream"],
                    "fields": tool_args["fields"],
                    "max_points": 10000,
                },
                "analysis_params": {
                    "fields": tool_args["fields"],
                    "threshold_sigma": tool_args.get("threshold_sigma", 2.5),
                    "window_size_ms": tool_args.get("window_size_ms", 30000),
                },
            }

        elif tool_name == "trace_causal_chains":
            return {
                "type": "bridge_request_with_analysis",
                "tool": "telemetry_slice",
                "analysis_tool": "trace_causal_chains",
                "params": {
                    "sessionId": tool_args["sessionId"],
                    "stream": "events",
                    "fields": ["text", "severity", "t"],
                    "max_points": 10000,
                },
                "analysis_params": {
                    "target_timestamp_ms": tool_args["target_timestamp_ms"],
                    "time_window_ms": tool_args.get("time_window_ms", 30000),
                },
            }

        # ----- Escalation -----
        elif tool_name == "escalate":
            if session_id not in escalation_counters:
                escalation_counters[session_id] = 0
            if session_id not in escalation_history:
                escalation_history[session_id] = []

            if escalation_counters[session_id] >= 3:
                return {
                    "verdict": "reject",
                    "notes": "Escalation limit reached for this session",
                }

            escalation_counters[session_id] += 1
            context = {
                "current": tool_args.get("context", {}),
                "history": escalation_history[session_id],
            }
            result = TOOL_FUNCTIONS["escalate"](context)
            escalation_history[session_id].append(result)
            return result

        # ----- Unknown Tool -----
        else:
            return {"ok": False, "error": f"Unknown tool: {tool_name}"}

    except Exception as e:
        return {"ok": False, "error": f"Error running {tool_name}: {e}"}


def append_tool_result(messages: list, call_id: str, tool_name: str, result):
    """
    Serialize a tool result and append it to the messages list as a tool message.
    """

    try:
        content = json.dumps(result) if isinstance(result, (dict, list)) else str(result)
    except Exception as e:
        content = str(result)

    messages.append({
        "role": "tool",
        "tool_call_id": call_id,
        "name": tool_name,
        "content": content,
    })
