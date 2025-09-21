
import json
from typing import Any, Dict, List

def execute_tool_call(tool_call, session_id: str, TOOL_FUNCTIONS: Dict[str, Any], 
                     escalation_counters: Dict[str, int], escalation_history: Dict[str, List[Dict[str, Any]]]):
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
