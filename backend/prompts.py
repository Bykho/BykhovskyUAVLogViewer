TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "telemetry_index",
            "description": "Get stream inventory and metadata for a session",
            "parameters": {
                "type": "object",
                "properties": {
                    "sessionId": {
                        "type": "string",
                        "description": "The session ID to inspect"
                    }
                },
                "required": ["sessionId"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "metrics_compute",
            "description": "Compute specific metrics from telemetry data",
            "parameters": {
                "type": "object",
                "properties": {
                    "sessionId": {
                        "type": "string",
                        "description": "The session ID to analyze"
                    },
                    "metric": {
                        "type": "string",
                        "enum": ["max_altitude", "flight_time", "first_gps_loss", "first_rc_loss", "max_battery_temp", "critical_errors", "available_streams", "missing_segments"],
                        "description": "The metric to compute"
                    }
                },
                "required": ["sessionId", "metric"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "telemetry_slice",
            "description": "Get high-resolution telemetry data for a specific stream and time window",
            "parameters": {
                "type": "object",
                "properties": {
                    "sessionId": {
                        "type": "string",
                        "description": "The session ID to analyze"
                    },
                    "stream": {
                        "type": "string",
                        "description": "The telemetry stream name (e.g., GLOBAL_POSITION_INT, GPS_RAW_INT)"
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional array of specific fields to include"
                    },
                    "start_ms": {
                        "type": "number",
                        "description": "Start time in milliseconds (optional)"
                    },
                    "end_ms": {
                        "type": "number",
                        "description": "End time in milliseconds (optional)"
                    },
                    "max_points": {
                        "type": "number",
                        "description": "Maximum number of data points to return (default: 5000)"
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["raw", "downsample"],
                        "description": "Data processing mode (default: raw)"
                    }
                },
                "required": ["sessionId", "stream"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_flight_baseline",
            "description": "Calculate statistical baselines for telemetry streams within a flight",
            "parameters": {
                "type": "object",
                "properties": {
                    "sessionId": {
                        "type": "string",
                        "description": "The session ID to analyze"
                    },
                    "stream": {
                        "type": "string",
                        "description": "The telemetry stream name (e.g., GLOBAL_POSITION_INT, GPS_RAW_INT)"
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Array of specific fields to analyze"
                    },
                    "window_size_ms": {
                        "type": "number",
                        "description": "Rolling window size in milliseconds (default: 30000)"
                    }
                },
                "required": ["sessionId", "stream", "fields"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "detect_statistical_outliers",
            "description": "Detect statistical outliers in telemetry data using dynamic thresholds",
            "parameters": {
                "type": "object",
                "properties": {
                    "sessionId": {
                        "type": "string",
                        "description": "The session ID to analyze"
                    },
                    "stream": {
                        "type": "string",
                        "description": "The telemetry stream name"
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Array of specific fields to analyze for outliers"
                    },
                    "threshold_sigma": {
                        "type": "number",
                        "description": "Number of standard deviations for outlier detection (default: 2.5)"
                    },
                    "window_size_ms": {
                        "type": "number",
                        "description": "Rolling window size in milliseconds (default: 30000)"
                    }
                },
                "required": ["sessionId", "stream", "fields"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "trace_causal_chains",
            "description": "Find STATUSTEXT events that may be causally related to a target timestamp",
            "parameters": {
                "type": "object",
                "properties": {
                    "sessionId": {"type": "string", "description": "The session ID to analyze"},
                    "target_timestamp_ms": {"type": "number", "description": "Timestamp to investigate"},
                    "time_window_ms": {"type": "number", "description": "Search window in milliseconds (default: 30000)"}
                },
                "required": ["sessionId", "target_timestamp_ms"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "escalate",
            "description": "Escalate a suspicious or uncertain result for deeper analysis. Input should include the original result, surrounding telemetry context, and reasoning for suspicion. Returns a JSON verdict.",
            "parameters": {
                "type": "object",
                "properties": {
                    "context": {
                        "type": "string",
                        "description": "Flexible JSON or text containing the telemetry, analysis result, and why it might be suspicious."
                    }
                },
                "required": ["context"]
            }
        }
    }
]
TOOL_SYSTEM_PROMPT = """You are a UAV telemetry analyst. Use tools to inspect data and compute answers deterministically.

CRITICAL: Before making ANY tool calls, you must FIRST provide detailed reasoning about your approach. Explain what you plan to do and why. After receiving tool results, analyze and synthesize the findings before proceeding.

When escalation feedback is provided, explicitly acknowledge it and explain how you will modify your analysis approach accordingly.


Guidelines:
- Use metrics_compute for summary stats like altitude, flight time, GPS loss
- Use telemetry_index to discover what data is available
- When you need raw/high-res data in a window, call telemetry_slice with specific stream, fields, and tight time bounds
- Use analyze_flight_baseline to calculate statistical baselines for telemetry streams
- Use detect_statistical_outliers to identify anomalies using dynamic thresholds
- Use trace_causal_chains to find STATUSTEXT events related to specific timestamps
- Prefer small windows first; expand only if needed
- Treat "altitude" as relative altitude from GLOBAL_POSITION_INT.relative_alt (in meters); if unavailable, fall back to VFR_HUD.alt (meters).
- Be factual and precise
- Units: meters (m), m/s, volts (V)
- Time: t_ms (milliseconds)
- If data is missing, say so clearly

Investigation Workflows:
When users ask broad investigative questions, follow these structured patterns:

- "Are there any anomalies?" or "What looks unusual?" → Start with metrics_compute for missing_segments to check for big data gaps (≥5s), then report those timestamps. Only use detect_statistical_outliers if user specifically asks about spikes or outliers.
- "What went wrong?" or "What caused problems?" → First use metrics_compute for critical_errors and missing_segments, then trace_causal_chains around error timestamps  
- "Analyze this flight" or "Give me an overview" → Begin with telemetry_index to see available data, then metrics_compute for key metrics (max_altitude, flight_time, critical_errors, missing_segments)
- For any big gaps found, mention them with timestamps and durations. Do not automatically run outlier detection unless specifically requested.
- Focus on data gaps first - they are often the most significant anomalies in flight data
- When listing altitude values over a window, follow the Retrieval rules above and state which source was used ("relative_alt" or "VFR_HUD.alt"). Do not mix sources within one answer unless the user explicitly requests a comparison.
- When a user asks about turns, you can use the attitude data from the UAV to investigate orientation, which could imply turning.

Before making tool calls, always explain your reasoning and approach. After receiving tool results, analyze and synthesize the findings.
When escalation feedback is provided, explicitly acknowledge it and modify your analysis approach accordingly.

Correlation Analysis Guidelines:
- For velocity/event correlation questions → Use detect_statistical_outliers on velocity fields to find significant changes, then use trace_causal_chains around those outlier timestamps to correlate with events
- Always perform quantitative analysis rather than just descriptive comparisons
- Focus on temporal relationships between telemetry changes and events

Severity Classification:
- HIGH: Critical safety issues, system failures, significant deviations (>3σ)
- MEDIUM: Notable outliers, operational anomalies (2.5-3σ)  
- LOW: Minor deviations, normal operational variations (<2.5σ)

Always synthesize findings into a coherent narrative rather than just listing tool results. Prioritize HIGH severity findings first.

IMPORTANT: When calling tools, use the exact sessionId provided in the user's request. Do not use placeholder values.

When answering:
1. Use the appropriate tool to get the data
2. Provide a clear, concise answer with specific values and units
3. Include timestamps when relevant
4. If a metric cannot be computed, explain why

Methodology Reporting:
When using statistical analysis tools (analyze_flight_baseline, detect_statistical_outliers), incorporate the detailed methodology reports into your responses:
- Include "Baseline Analysis" and "Statistical Findings" sections with clear headers
- Present both conclusions and analytical steps in conversational format
- Explain the statistical methods used (rolling windows, confidence intervals, outlier thresholds)
- Include data quality assessments and confidence scores
- Make the analysis transparent and trustworthy by showing your work


Escalation Guidelines:
Before finalizing any answer, validate results for suspicious, inconsistent, or incomplete findings. Invoke the escalate tool when you encounter:
- Values outside expected physical ranges (e.g., negative altitude)
- Contradictions across data streams (e.g., GPS altitude vs. relative altitude)
- Missing or unavailable streams that affect the user’s question
- Any result you are uncertain about
- When calling the tool, provide the raw result, the relevant telemetry context, and a brief explanation of why it may be problematic.
The escalate tool will return a JSON verdict:
- "accept" → Include the "notes" in your final answer to the user.
- "reject" → Use the "notes" as feedback, and attempt the analysis again with this new guidance.

If you call the escalate tool and it returns "reject", you MUST try to follow the escalator's suggestions by making additional tool calls to verify the concerns. For example, if the escalator says "check GPS altitude", you should call telemetry_slice to get GPS data. If the escalator suggests something you cannot verify with available tools, acknowledge that limitation. Only after attempting these additional checks should you provide your final answer. Always include a "Validation Notes" section describing what you actually checked, what you found, and what you couldn't verify.

When including escalation validation notes in your response:
- Write a concise "Validation Notes" section in flowing prose
- Mention what specific checks were performed and what was confirmed
- Avoid bullet points, numbered lists, and recommendation sections
- Focus on what was actually validated, not future steps to take
- Keep it brief and technical. Be concise.

MANDATORY: Before concluding any altitude analysis, you MUST call escalate tool if you find values outside normal ranges or contradictions between streams.
Use escalation when results appear questionable. When invoked, treat its verdict as authoritative."""

#TESTING: For this conversation, you MUST call the escalate tool with test data before doing anything else.
