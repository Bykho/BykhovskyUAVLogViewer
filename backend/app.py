from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Dict, List, Optional, Union
import os
import time
import logging
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    question: str
    digest: Dict[str, Any]

class ChatReply(BaseModel):
    reply: str

# New tool-calling models
class ToolCallRequest(BaseModel):
    sessionId: str
    messages: List[Dict[str, Any]]

class ToolCallReply(BaseModel):
    reply: str
    debug: Optional[Dict[str, Any]] = None

class ToolReplyRequest(BaseModel):
    call_id: str
    tool: str
    sessionId: str
    result: Dict[str, Any]

class ToolReplyResponse(BaseModel):
    status: str
    message: str
    debug: Optional[dict] = None

class MetricResult(BaseModel):
    name: str
    ok: bool
    value: Optional[Union[float, int]] = None
    units: Optional[str] = None
    t_ms: Optional[int] = None
    method: Optional[str] = None
    source: Optional[str] = None
    notes: Optional[str] = None

class SessionBundle(BaseModel):
    sessionId: str
    meta: Dict[str, Any]
    index: Dict[str, Any]
    downsample1Hz: Dict[str, Any]
    events: List[Dict[str, Any]]
    gaps: Optional[Dict[str, Any]] = None

class SessionResponse(BaseModel):
    sessionId: str
    status: str
    message: str

# In-memory storage for session bundles
sessions: Dict[str, SessionBundle] = {}

# In-memory storage for pending bridge requests
# Structure: {session_id: {"messages": [...], "pending_calls": {call_id: {...}}, "iteration": 1, "start_time": time}}
pending_conversations: Dict[str, Dict[str, Any]] = {}

# Tool function registry
TOOL_FUNCTIONS = {
    "telemetry_index": None,  # Will be set below
    "metrics_compute": None,  # Will be set below
    "telemetry_slice": "bridge_tool",  # Bridge tool - handled specially
    "analyze_flight_baseline": None,  # Will be set below
    "detect_statistical_outliers": None,  # Will be set below
    "trace_causal_chains": None,  # Will be set below
}

# Tool definitions for OpenAI
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
    }
]

# New system prompt for tool-calling
# New system prompt for tool-calling
TOOL_SYSTEM_PROMPT = """You are a UAV telemetry analyst. Use tools to inspect data and compute answers deterministically.

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
- Make the analysis transparent and trustworthy by showing your work"""



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

def metrics_compute_max_altitude(session: SessionBundle) -> MetricResult:
    """Compute maximum altitude from session data"""
    try:
        # Try VFR_HUD altitude first
        alt_data = session.downsample1Hz.get("alt", [])
        if alt_data:
            max_alt = max((item["altM"] for item in alt_data if item.get("altM") is not None), default=None)
            if max_alt is not None:
                # Find the timestamp of max altitude
                max_item = max((item for item in alt_data if item.get("altM") == max_alt), key=lambda x: x.get("t", 0))
                return MetricResult(
                    name="max_altitude",
                    ok=True,
                    value=round(max_alt, 1),
                    units="m",
                    t_ms=max_item.get("t"),
                    method="VFR_HUD.alt (1Hz extrema-preserving downsample)",
                    source="downsample1Hz.alt",
                    notes=""
                )
        
        # Fallback to GLOBAL_POSITION_INT relative altitude
        gpos_data = session.downsample1Hz.get("gpos", [])
        if gpos_data:
            max_rel_alt = max((item["relAltM"] for item in gpos_data if item.get("relAltM") is not None), default=None)
            if max_rel_alt is not None:
                max_item = max((item for item in gpos_data if item.get("relAltM") == max_rel_alt), key=lambda x: x.get("t", 0))
                return MetricResult(
                    name="max_altitude",
                    ok=True,
                    value=round(max_rel_alt, 1),
                    units="m",
                    t_ms=max_item.get("t"),
                    method="GLOBAL_POSITION_INT.relative_alt/1000 (1Hz extrema-preserving downsample)",
                    source="downsample1Hz.gpos",
                    notes="Using relative altitude as fallback"
                )
        
        return MetricResult(
            name="max_altitude",
            ok=False,
            value=None,
            units="m",
            t_ms=None,
            method="",
            source="",
            notes="No altitude data available in VFR_HUD or GLOBAL_POSITION_INT"
        )
    except Exception as e:
        return MetricResult(
            name="max_altitude",
            ok=False,
            value=None,
            units="m",
            t_ms=None,
            method="",
            source="",
            notes=f"Error computing max altitude: {str(e)}"
        )

def metrics_compute_flight_time(session: SessionBundle) -> MetricResult:
    """Compute flight time from session metadata"""
    try:
        meta = session.meta
        t_start = meta.get("tStartMs")
        t_end = meta.get("tEndMs")
        
        if t_start is not None and t_end is not None and t_end > t_start:
            duration_ms = t_end - t_start
            duration_s = duration_ms / 1000.0
            return MetricResult(
                name="flight_time",
                ok=True,
                value=round(duration_s, 1),
                units="s",
                t_ms=None,
                method="tEndMs - tStartMs from session metadata",
                source="session.meta",
                notes=""
            )
        
        return MetricResult(
            name="flight_time",
            ok=False,
            value=None,
            units="s",
            t_ms=None,
            method="",
            source="",
            notes="Invalid or missing timestamp data in session metadata"
        )
    except Exception as e:
        return MetricResult(
            name="flight_time",
            ok=False,
            value=None,
            units="s",
            t_ms=None,
            method="",
            source="",
            notes=f"Error computing flight time: {str(e)}"
        )

def metrics_compute_first_gps_loss(session: SessionBundle) -> MetricResult:
    """Find first GPS loss (fix_type < 3)"""
    try:
        gps_data = session.downsample1Hz.get("gps", [])
        if not gps_data:
            return MetricResult(
                name="first_gps_loss",
                ok=False,
                value=None,
                units="",
                t_ms=None,
                method="",
                source="",
                notes="No GPS data available"
            )
        
        # Find first occurrence where fix < 3
        for item in sorted(gps_data, key=lambda x: x.get("t", 0)):
            fix = item.get("fix")
            if fix is not None and fix < 3:
                return MetricResult(
                    name="first_gps_loss",
                    ok=True,
                    value=fix,
                    units="fix_type",
                    t_ms=item.get("t"),
                    method="First GPS_RAW_INT.fix_type < 3",
                    source="downsample1Hz.gps",
                    notes=f"GPS fix dropped to {fix}"
                )
        
        return MetricResult(
            name="first_gps_loss",
            ok=True,
            value=None,
            units="",
            t_ms=None,
            method="GPS_RAW_INT.fix_type analysis",
            source="downsample1Hz.gps",
            notes="No GPS loss detected (all fix_type >= 3)"
        )
    except Exception as e:
        return MetricResult(
            name="first_gps_loss",
            ok=False,
            value=None,
            units="",
            t_ms=None,
            method="",
            source="",
            notes=f"Error computing first GPS loss: {str(e)}"
        )

def metrics_compute_max_battery_temp(session: SessionBundle) -> MetricResult:
    """Find maximum battery temperature from session data"""
    try:
        # Check multiple possible battery streams
        battery_streams = ["BATTERY_STATUS", "SYS_STATUS", "BAT", "BATT", "BATTERY"]
        max_temp = None
        max_temp_t_ms = None
        source_used = ""
        method_used = ""
        
        # First check downsample1Hz data
        # Check the new battery section first
        if "battery" in session.downsample1Hz:
            battery_data = session.downsample1Hz["battery"]
            if battery_data:
                for item in battery_data:
                    if "temp" in item and item["temp"] is not None:
                        temp_val = float(item["temp"])
                        if max_temp is None or temp_val > max_temp:
                            max_temp = temp_val
                            max_temp_t_ms = item.get("t")
                            source_used = "downsample1Hz.battery"
                            method_used = "Max of temp field from battery stream"
        
        # Also check individual battery streams
        for stream_name in battery_streams:
            if stream_name.lower() in session.downsample1Hz:
                stream_data = session.downsample1Hz[stream_name.lower()]
                if stream_data:
                    # Look for temperature fields
                    temp_fields = ["temp", "temperature", "tempC", "temp_c", "battery_temp"]
                    for item in stream_data:
                        for field in temp_fields:
                            if field in item and item[field] is not None:
                                temp_val = float(item[field])
                                if max_temp is None or temp_val > max_temp:
                                    max_temp = temp_val
                                    max_temp_t_ms = item.get("t")
                                    source_used = f"downsample1Hz.{stream_name.lower()}"
                                    method_used = f"Max of {field} field from {stream_name} stream"
        
        # If not found in downsample1Hz, check raw index for available streams
        if max_temp is None:
            available_streams = []
            for stream_name in battery_streams:
                if stream_name in session.index:
                    available_streams.append(stream_name)
            
            if available_streams:
                return MetricResult(
                    name="max_battery_temp",
                    ok=False,
                    value=None,
                    units="°C",
                    t_ms=None,
                    method=f"Checked streams: {', '.join(available_streams)}",
                    source="session.index",
                    notes="Battery temperature data found in streams but not processed in downsample1Hz. Raw data available for telemetry_slice analysis."
                )
            else:
                return MetricResult(
                    name="max_battery_temp",
                    ok=False,
                    value=None,
                    units="°C",
                    t_ms=None,
                    method="Checked standard battery streams",
                    source="session.index",
                    notes="No battery temperature streams found. Checked: BATTERY_STATUS, SYS_STATUS, BAT, BATT, BATTERY"
                )
        
        return MetricResult(
            name="max_battery_temp",
            ok=True,
            value=round(max_temp, 1),
            units="°C",
            t_ms=max_temp_t_ms,
            method=method_used,
            source=source_used,
            notes=""
        )
        
    except Exception as e:
        return MetricResult(
            name="max_battery_temp",
            ok=False,
            value=None,
            units="°C",
            t_ms=None,
            method="",
            source="",
            notes=f"Error computing max battery temperature: {str(e)}"
        )

def metrics_compute_first_rc_loss(session: SessionBundle) -> MetricResult:
    """Find first RC signal loss from session data"""
    try:
        # Strategy 1: Check STATUSTEXT events for RC-related messages
        rc_loss_events = []
        for event in session.events:
            if event.get("text"):
                text = event["text"].upper()
                if ("RC" in text and ("FAILSAFE" in text or "LOST" in text or "DISCONNECT" in text)):
                    rc_loss_events.append({
                        "t_ms": event.get("t"),
                        "severity": event.get("severity"),
                        "text": event.get("text")
                    })
        
        if rc_loss_events:
            # Sort by timestamp and return first
            rc_loss_events.sort(key=lambda x: x.get("t_ms", 0))
            first_event = rc_loss_events[0]
            return MetricResult(
                name="first_rc_loss",
                ok=True,
                value=1,  # Indicates RC loss detected
                units="detected",
                t_ms=first_event["t_ms"],
                method="STATUSTEXT event analysis",
                source="session.events",
                notes=f"RC loss detected via status message: '{first_event['text']}'"
            )
        
        # Strategy 2: Check for RC_CHANNELS stream in index
        if "RC_CHANNELS" in session.index:
            return MetricResult(
                name="first_rc_loss",
                ok=False,
                value=None,
                units="",
                t_ms=None,
                method="RC_CHANNELS stream analysis",
                source="session.index",
                notes="RC_CHANNELS stream available but not processed in downsample1Hz. Use telemetry_slice to analyze RC channel values for failsafe detection."
            )
        
        # Strategy 3: Check for SYS_STATUS stream
        if "SYS_STATUS" in session.index:
            return MetricResult(
                name="first_rc_loss",
                ok=False,
                value=None,
                units="",
                t_ms=None,
                method="SYS_STATUS stream analysis",
                source="session.index",
                notes="SYS_STATUS stream available but not processed in downsample1Hz. Use telemetry_slice to analyze RC_RECEIVER status bits."
            )
        
        # No RC loss detected and no RC-related streams
        return MetricResult(
            name="first_rc_loss",
            ok=True,
            value=None,
            units="",
            t_ms=None,
            method="STATUSTEXT event analysis",
            source="session.events",
            notes="No RC signal loss detected in status messages. No RC_CHANNELS or SYS_STATUS streams available for detailed analysis."
        )
        
    except Exception as e:
        return MetricResult(
            name="first_rc_loss",
            ok=False,
            value=None,
            units="",
            t_ms=None,
            method="",
            source="",
            notes=f"Error computing first RC loss: {str(e)}"
        )

def metrics_compute_critical_errors(session: SessionBundle) -> MetricResult:
    """Find all critical errors from session events"""
    try:
        critical_keywords = [
            "FAILSAFE", "GPS", "EKF", "BATTERY", "CRASH", "VIBRATION", 
            "COMPASS", "GYRO", "ACCEL", "ERROR", "CRITICAL", "WARNING"
        ]
        
        critical_events = []
        
        for event in session.events:
            if not event.get("text"):
                continue
                
            text = event["text"].upper()
            severity = event.get("severity")
            
            # Check severity level (0-3 are critical)
            is_critical_severity = severity is not None and severity <= 3
            
            # Check for critical keywords
            has_critical_keyword = any(keyword in text for keyword in critical_keywords)
            
            if is_critical_severity or has_critical_keyword:
                critical_events.append({
                    "t_ms": event.get("t"),
                    "severity": severity,
                    "text": event.get("text")
                })
        
        # Sort by timestamp
        critical_events.sort(key=lambda x: x.get("t_ms", 0))
        
        return MetricResult(
            name="critical_errors",
            ok=True,
            value=len(critical_events),  # Count of critical events
            units="count",
            t_ms=critical_events[0]["t_ms"] if critical_events else None,
            method="STATUSTEXT event analysis with severity and keyword filtering",
            source="session.events",
            notes=f"Found {len(critical_events)} critical events. Keywords checked: {', '.join(critical_keywords)}"
        )
        
    except Exception as e:
        return MetricResult(
            name="critical_errors",
            ok=False,
            value=None,
            units="count",
            t_ms=None,
            method="",
            source="",
            notes=f"Error computing critical errors: {str(e)}"
        )

def metrics_compute_available_streams(session: SessionBundle) -> MetricResult:
    """Get list of available telemetry streams in the session"""
    try:
        streams = list(session.index.keys())
        streams.sort()
        
        # Categorize streams
        categories = {
            "position": [],
            "attitude": [],
            "battery": [],
            "rc": [],
            "gps": [],
            "system": [],
            "other": []
        }
        
        for stream in streams:
            stream_upper = stream.upper()
            if any(x in stream_upper for x in ["POSITION", "GPS", "LOCAL"]):
                categories["position"].append(stream)
            elif any(x in stream_upper for x in ["ATTITUDE", "ATT", "EULER", "QUATERNION"]):
                categories["attitude"].append(stream)
            elif any(x in stream_upper for x in ["BATTERY", "BAT", "BATT", "SYS_STATUS"]):
                categories["battery"].append(stream)
            elif any(x in stream_upper for x in ["RC", "CHANNEL", "RADIO"]):
                categories["rc"].append(stream)
            elif "GPS" in stream_upper:
                categories["gps"].append(stream)
            elif any(x in stream_upper for x in ["SYS", "STATUS", "HEARTBEAT", "PARAM"]):
                categories["system"].append(stream)
            else:
                categories["other"].append(stream)
        
        return MetricResult(
            name="available_streams",
            ok=True,
            value=len(streams),
            units="count",
            t_ms=None,
            method="Session index analysis",
            source="session.index",
            notes=f"Total streams: {len(streams)}. Categories: {', '.join([f'{k}: {len(v)}' for k, v in categories.items() if v])}"
        )
        
    except Exception as e:
        return MetricResult(
            name="available_streams",
            ok=False,
            value=None,
            units="count",
            t_ms=None,
            method="",
            source="",
            notes=f"Error computing available streams: {str(e)}"
        )

def metrics_compute_missing_segments(session: SessionBundle) -> MetricResult:
    """Find big gaps (≥5s) in telemetry streams"""
    try:
        if not session.gaps:
            return MetricResult(
                name="missing_segments",
                ok=True,
                value=0,
                units="count",
                t_ms=None,
                method="Big gap analysis (≥5s only)",
                source="session.gaps",
                notes="No gap data available"
            )
        
        # Collect only big gaps (≥5s) from all streams
        gaps = []
        for stream, arr in session.gaps.items():
            for g in arr or []:
                if g.get("durationMs", 0) >= 5000:  # Only gaps ≥5 seconds
                    gaps.append({"stream": stream, **g})
        
        # Sort by start time
        gaps.sort(key=lambda x: x.get('startMs', 0))
        
        return MetricResult(
            name="missing_segments",
            ok=True,
            value=len(gaps),
            units="count",
            t_ms=None,
            method="Big gap analysis (≥5s only)",
            source="session.gaps",
            notes=f"Found {len(gaps)} big gaps (≥5s). " +
                  (f"Gaps: {[f'{g['stream']}@{g['startMs']}ms({g['durationMs']}ms)' for g in gaps[:5]]}" if gaps else "No big gaps found.")
        )
        
    except Exception as e:
        return MetricResult(
            name="missing_segments",
            ok=False,
            value=None,
            units="count",
            t_ms=None,
            method="",
            source="",
            notes=f"Error computing missing segments: {str(e)}"
        )


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

def calculate_rolling_statistics(rows: List[Dict], fields: List[str], window_size_ms: int) -> Dict[str, Any]:
    """Calculate rolling statistics for telemetry data"""
    if not rows:
        return {"windows": [], "duration_ms": 0}
    
    # Get time range
    times = [row.get('time_boot_ms', row.get('TimeUS', row.get('_timestamp', 0))) for row in rows]
    first_time = min(times)
    last_time = max(times)
    duration_ms = last_time - first_time
    
    # Calculate number of windows
    num_windows = max(1, duration_ms // window_size_ms)
    window_step = duration_ms / num_windows
    
    windows = []
    for i in range(num_windows):
        window_start = first_time + (i * window_step)
        window_end = window_start + window_size_ms
        
        # Filter records for this window
        window_records = [row for row in rows 
                         if window_start <= row.get('time_boot_ms', row.get('TimeUS', row.get('_timestamp', 0))) <= window_end]
        
        window_data = {
            "window_index": i,
            "start_ms": window_start,
            "end_ms": window_end,
            "fields": {}
        }
        
        # Calculate statistics for each field
        for field in fields:
            values = [row.get(field) for row in window_records 
                     if row.get(field) is not None and isinstance(row.get(field), (int, float))]
            
            if len(values) < 2:
                window_data["fields"][field] = {
                    "field": field,
                    "sample_count": len(values),
                    "mean": None,
                    "std": None,
                    "min": None,
                    "max": None
                }
                continue
            
            # Calculate basic statistics
            mean = sum(values) / len(values)
            variance = sum((x - mean) ** 2 for x in values) / len(values)
            std = variance ** 0.5
            
            window_data["fields"][field] = {
                "field": field,
                "sample_count": len(values),
                "mean": round(mean, 3),
                "std": round(std, 3),
                "min": min(values),
                "max": max(values)
            }
        
        windows.append(window_data)
    
    return {
        "stream": rows[0].get('stream', 'unknown') if rows else 'unknown',
        "fields": fields,
        "window_size_ms": window_size_ms,
        "total_records": len(rows),
        "duration_ms": duration_ms,
        "num_windows": num_windows,
        "windows": windows
    }

def detect_outliers_with_dynamic_thresholds(rows: List[Dict], fields: List[str], 
                                          threshold_sigma: float, window_size_ms: int) -> Dict[str, Any]:
    """Detect outliers using dynamic thresholds based on rolling statistics"""
    if not rows:
        return {"outliers": [], "total_outliers": 0}
    
    # Get time range
    times = [row.get('time_boot_ms', row.get('TimeUS', row.get('_timestamp', 0))) for row in rows]
    first_time = min(times)
    last_time = max(times)
    duration_ms = last_time - first_time
    
    # Calculate number of windows
    num_windows = max(1, duration_ms // window_size_ms)
    window_step = duration_ms / num_windows
    
    outliers = []
    total_outliers = 0
    
    for i in range(num_windows):
        window_start = first_time + (i * window_step)
        window_end = window_start + window_size_ms
        
        # Filter records for this window
        window_records = [row for row in rows 
                         if window_start <= row.get('time_boot_ms', row.get('TimeUS', row.get('_timestamp', 0))) <= window_end]
        
        # For each field, detect outliers
        for field in fields:
            values = [row.get(field) for row in window_records 
                     if row.get(field) is not None and isinstance(row.get(field), (int, float))]
            
            if len(values) < 3:
                continue
            
            # Calculate baseline statistics
            mean = sum(values) / len(values)
            variance = sum((x - mean) ** 2 for x in values) / len(values)
            std = variance ** 0.5
            
            # Calculate thresholds
            threshold_upper = mean + (threshold_sigma * std)
            threshold_lower = mean - (threshold_sigma * std)
            
            # Find outliers
            outlier_points = []
            for record in window_records:
                value = record.get(field)
                if value is not None and isinstance(value, (int, float)):
                    if value > threshold_upper or value < threshold_lower:
                        deviation = abs(value - mean) / std if std > 0 else 0
                        outlier_points.append({
                            "timestamp": record.get('time_boot_ms', record.get('TimeUS', record.get('_timestamp', 0))),
                            "value": value,
                            "deviation_sigma": round(deviation, 2),
                            "deviation_magnitude": round(abs(value - mean), 3)
                        })
            
            total_outliers += len(outlier_points)
            
            outliers.append({
                "field": field,
                "window_index": i,
                "start_ms": window_start,
                "end_ms": window_end,
                "outlier_count": len(outlier_points),
                "outlier_points": outlier_points,
                "baseline_mean": round(mean, 3),
                "baseline_std": round(std, 3),
                "threshold_upper": round(threshold_upper, 3),
                "threshold_lower": round(threshold_lower, 3)
            })
    
    return {
        "stream": rows[0].get('stream', 'unknown') if rows else 'unknown',
        "fields": fields,
        "threshold_sigma": threshold_sigma,
        "window_size_ms": window_size_ms,
        "total_records": len(rows),
        "duration_ms": duration_ms,
        "num_windows": num_windows,
        "outliers": outliers,
        "total_outliers": total_outliers
    }

# Statistical analysis functions that use telemetry_slice internally
def analyze_flight_baseline_impl(session_id: str, stream: str, fields: List[str], window_size_ms: int = 30000) -> Dict[str, Any]:
    """Calculate statistical baselines for telemetry streams within a flight"""
    if session_id not in sessions:
        return {
            "ok": False,
            "error": f"Session {session_id} not found",
            "methodology": "Session validation",
            "findings": {},
            "confidence": 0.0,
            "data_quality": "Session not found"
        }
    
    session = sessions[session_id]
    
    try:
        # Use telemetry_slice internally to get data
        # This calls the same logic that the frontend telemetry_slice uses
        slice_result = get_telemetry_data_internal(session_id, stream, fields, max_points=10000)
        
        if not slice_result.get("ok", False):
            return {
                "ok": False,
                "error": f"Failed to get data for stream {stream}",
                "methodology": "Data access via internal telemetry_slice",
                "findings": {},
                "confidence": 0.0,
                "data_quality": slice_result.get("error", "Data access failed")
            }
        
        # Perform rolling window analysis on the data
        rows = slice_result.get("rows", [])
        if len(rows) < 10:
            return {
                "ok": False,
                "error": f"Insufficient data for analysis: {len(rows)} records",
                "methodology": "Data sufficiency check",
                "findings": {},
                "confidence": 0.0,
                "data_quality": f"Only {len(rows)} records available, need at least 10"
            }
        
        # Calculate rolling statistics
        baseline_results = calculate_rolling_statistics(rows, fields, window_size_ms)
        
        return {
            "ok": True,
            "methodology": f"Rolling window analysis with {window_size_ms}ms windows. " +
                          f"Analyzed {len(rows)} records across {len(baseline_results['windows'])} windows. " +
                          f"Calculated mean, std dev, and basic statistics for {len(fields)} fields.",
            "findings": baseline_results,
            "confidence": min(1.0, len(rows) / 1000.0),
            "data_quality": f"Stream {stream} contains {len(rows)} records. " +
                           f"Data density: {len(rows) / (baseline_results.get('duration_ms', 1) / 1000):.1f} Hz"
        }
        
    except Exception as e:
        return {
            "ok": False,
            "error": f"Analysis failed: {str(e)}",
            "methodology": "Statistical analysis execution",
            "findings": {},
            "confidence": 0.0,
            "data_quality": f"Exception during analysis: {str(e)}"
        }

def detect_statistical_outliers_impl(session_id: str, stream: str, fields: List[str], 
                                   threshold_sigma: float = 2.5, window_size_ms: int = 30000) -> Dict[str, Any]:
    """Detect statistical outliers in telemetry data using dynamic thresholds"""
    if session_id not in sessions:
        return {
            "ok": False,
            "error": f"Session {session_id} not found",
            "methodology": "Session validation",
            "findings": {},
            "confidence": 0.0,
            "data_quality": "Session not found"
        }
    
    session = sessions[session_id]
    
    try:
        # Use telemetry_slice internally to get data
        slice_result = get_telemetry_data_internal(session_id, stream, fields, max_points=10000)
        
        if not slice_result.get("ok", False):
            return {
                "ok": False,
                "error": f"Failed to get data for stream {stream}",
                "methodology": "Data access via internal telemetry_slice",
                "findings": {},
                "confidence": 0.0,
                "data_quality": slice_result.get("error", "Data access failed")
            }
        
        rows = slice_result.get("rows", [])
        if len(rows) < 10:
            return {
                "ok": False,
                "error": f"Insufficient data for analysis: {len(rows)} records",
                "methodology": "Data sufficiency check",
                "findings": {},
                "confidence": 0.0,
                "data_quality": f"Only {len(rows)} records available, need at least 10"
            }
        
        # Detect outliers using dynamic thresholds
        outlier_results = detect_outliers_with_dynamic_thresholds(rows, fields, threshold_sigma, window_size_ms)
        
        return {
            "ok": True,
            "methodology": f"Dynamic threshold outlier detection using {threshold_sigma}σ thresholds. " +
                          f"Analyzed {len(rows)} records in {window_size_ms}ms windows. " +
                          f"Outliers identified as points exceeding {threshold_sigma} standard deviations from rolling mean.",
            "findings": outlier_results,
            "confidence": min(1.0, len(rows) / 500.0),
            "data_quality": f"Stream {stream} analyzed for outliers. " +
                           f"{outlier_results.get('total_outliers', 0)} outliers found out of {len(rows)} total records."
        }
        
    except Exception as e:
        return {
            "ok": False,
            "error": f"Outlier detection failed: {str(e)}",
            "methodology": "Statistical analysis execution",
            "findings": {},
            "confidence": 0.0,
            "data_quality": f"Exception during analysis: {str(e)}"
        }

def trace_causal_chains_impl(session_id: str, target_timestamp_ms: int, time_window_ms: int = 30000) -> Dict[str, Any]:
    """Find STATUSTEXT events that may be causally related to a target timestamp"""
    if session_id not in sessions:
        return {
            "ok": False,
            "error": f"Session {session_id} not found",
            "methodology": "Session validation",
            "findings": {},
            "confidence": 0.0,
            "data_quality": "Session not found"
        }
    
    session = sessions[session_id]
    
    try:
        # Search for STATUSTEXT events within the time window
        nearby_events = []
        window_start = target_timestamp_ms - time_window_ms
        window_end = target_timestamp_ms + time_window_ms
        
        # Look through session events for STATUSTEXT messages
        for event in session.events:
            if event.get("text"):  # Check if the event has text content
                event_time = event.get("t", 0)  # Use "t" for timestamp
                
                # Check if event is within time window
                if window_start <= event_time <= window_end:
                    time_delta = event_time - target_timestamp_ms
                    nearby_events.append({
                        "timestamp_ms": event_time,
                        "text": event.get("text", ""),
                        "severity": event.get("severity", 0),
                        "time_delta_ms": time_delta,
                        "time_delta_seconds": round(time_delta / 1000, 1),
                        "direction": "before" if time_delta < 0 else "after"
                    })
        
        # Sort by proximity to target timestamp
        nearby_events.sort(key=lambda x: abs(x["time_delta_ms"]))
        
        # Calculate proximity ranking
        for i, event in enumerate(nearby_events):
            event["proximity_rank"] = i + 1
        
        return {
            "ok": True,
            "methodology": f"Event correlation analysis for timestamp {target_timestamp_ms}. " +
                          f"Searched for STATUSTEXT events within ±{time_window_ms}ms window. " +
                          f"Found {len(nearby_events)} events, sorted by temporal proximity.",
            "findings": {
                "target_timestamp_ms": target_timestamp_ms,
                "time_window_ms": time_window_ms,
                "events_found": len(nearby_events),
                "nearby_events": nearby_events
            },
            "confidence": min(1.0, len(nearby_events) / 10.0),  # Higher confidence with more events
            "data_quality": f"Analyzed {len(session.events)} total events in session. " +
                           f"Found {len(nearby_events)} STATUSTEXT events within ±{time_window_ms}ms of target."
        }
        
    except Exception as e:
        return {
            "ok": False,
            "error": f"Event correlation failed: {str(e)}",
            "methodology": "Event correlation execution",
            "findings": {},
            "confidence": 0.0,
            "data_quality": f"Exception during analysis: {str(e)}"
        }

# Register tool functions
TOOL_FUNCTIONS["telemetry_index"] = telemetry_index
TOOL_FUNCTIONS["metrics_compute"] = metrics_compute
TOOL_FUNCTIONS["analyze_flight_baseline"] = analyze_flight_baseline_impl
TOOL_FUNCTIONS["detect_statistical_outliers"] = detect_statistical_outliers_impl
TOOL_FUNCTIONS["trace_causal_chains"] = trace_causal_chains_impl

@app.get("/health")
def health_check():
    return {"status": "healthy", "sessions": len(sessions)}

@app.post("/session", response_model=SessionResponse)
def create_session(bundle: SessionBundle):
    try:
        # Validate required fields
        if not bundle.sessionId:
            raise HTTPException(status_code=400, detail="sessionId is required")
        
        if not bundle.meta or not bundle.index:
            raise HTTPException(status_code=400, detail="meta and index are required")
        
        # Store session bundle
        sessions[bundle.sessionId] = bundle
        
        print(f"Session {bundle.sessionId} created with {len(bundle.index)} streams")
        
        return SessionResponse(
            sessionId=bundle.sessionId,
            status="created",
            message=f"Session created with {len(bundle.index)} streams"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/session/{session_id}", response_model=SessionBundle)
def get_session(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return sessions[session_id]

@app.delete("/session/{session_id}", response_model=SessionResponse)
def delete_session(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    del sessions[session_id]
    
    return SessionResponse(
        sessionId=session_id,
        status="deleted",
        message="Session deleted"
    )

@app.get("/sessions", response_model=List[str])
def list_sessions():
    return list(sessions.keys())


@app.post("/chat-tools", response_model=ToolCallReply)
def chat_with_tools(req: ToolCallRequest):
    """New chat endpoint with OpenAI tool-calling"""
    start_time = time.time()
    last_tool_result = None
    tool_execution_log = []  # Track tool execution for frontend widget
    
    try:
        # Clean up any existing pending conversation for this session
        # This prevents state corruption when starting a new conversation
        if req.sessionId in pending_conversations:
            print(f"Cleaning up existing pending conversation for session {req.sessionId}")
            print(f"Pending calls before cleanup: {list(pending_conversations[req.sessionId]['pending_calls'].keys())}")
            del pending_conversations[req.sessionId]
            print(f"Successfully cleaned up session {req.sessionId}")
        
        # Initialize messages with system prompt
        system_prompt = TOOL_SYSTEM_PROMPT + f"\n\nCurrent session ID: {req.sessionId}"
        messages = [
            {"role": "system", "content": system_prompt}
        ] + req.messages
        
        # Tool-calling loop with timeout protection
        max_iterations = 5
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            # Call OpenAI with tools
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.1,
                max_tokens=1000
            )
            
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
                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments)
                    
                    # Log tool call
                    tool_start = time.time()
                    print(f"Tool call: {tool_name}({tool_args})")
                    
                    # Execute tool
                    try:
                        if tool_name == "telemetry_index":
                            result = TOOL_FUNCTIONS[tool_name](tool_args["sessionId"])
                        elif tool_name == "metrics_compute":
                            result = TOOL_FUNCTIONS[tool_name](tool_args["sessionId"], tool_args["metric"])
                        elif tool_name == "telemetry_slice":
                            # Bridge tool - return special response format
                            result = {
                                "type": "bridge_request",
                                "call_id": tool_call.id,
                                "tool": "telemetry_slice",
                                "params": tool_args
                            }
                        elif tool_name == "analyze_flight_baseline":
                            # Regular backend tool - execute directly
                            result = TOOL_FUNCTIONS[tool_name](tool_args["sessionId"], tool_args["stream"], 
                                                               tool_args["fields"], tool_args.get("window_size_ms", 30000))
                        elif tool_name == "detect_statistical_outliers":
                            # Regular backend tool - execute directly
                            result = TOOL_FUNCTIONS[tool_name](tool_args["sessionId"], tool_args["stream"],
                                                                    tool_args["fields"], tool_args.get("threshold_sigma", 2.5),
                                                                    tool_args.get("window_size_ms", 30000))
                        elif tool_name == "trace_causal_chains":
                            # Regular backend tool - execute directly
                            result = TOOL_FUNCTIONS[tool_name](tool_args["sessionId"], tool_args["target_timestamp_ms"],
                                                                    tool_args.get("time_window_ms", 30000))
                        else:
                            result = {"status": "not_implemented", "tool": tool_name}
                    except Exception as e:
                        print(f"Error executing tool {tool_name}: {str(e)}")
                        result = {"status": "error", "tool": tool_name, "error": str(e)}
                    
                    tool_duration = time.time() - tool_start
                    print(f"Tool {tool_name} completed in {tool_duration:.3f}s")
                    
                    # Log tool execution for frontend widget (only for non-bridge tools)
                    if not (isinstance(result, dict) and result.get("type") == "bridge_request"):
                        tool_execution_log.append({
                            "tool": tool_name,
                            "duration": round(tool_duration, 3),
                            "status": "completed"
                        })
                    
                    # Handle bridge requests specially
                    if isinstance(result, dict) and result.get("type") == "bridge_request":
                        session_id = tool_args["sessionId"]
                        
                        # Initialize conversation tracking if not exists
                        if session_id not in pending_conversations:
                            pending_conversations[session_id] = {
                                "messages": messages.copy(),
                                "pending_calls": {},
                                "iteration": iteration,
                                "start_time": start_time,
                                "tool_execution_log": tool_execution_log.copy()
                            }
                        else:
                            # Preserve existing tool execution log
                            pending_conversations[session_id]["tool_execution_log"].extend(tool_execution_log)
                        
                        # Add this tool call to pending calls
                        pending_conversations[session_id]["pending_calls"][tool_call.id] = {
                            "tool": tool_name,
                            "params": tool_args,
                            "result": None
                        }
                        
                        # Check if this is the last tool call in this turn
                        remaining_tool_calls = [tc for tc in message.tool_calls if tc.id not in pending_conversations[session_id]["pending_calls"]]
                        
                        if not remaining_tool_calls:
                            # All tool calls are now pending - return batch bridge request
                            return ToolCallReply(
                                reply="",
                                debug={
                                    "type": "batch_bridge_request",
                                    "session_id": session_id,
                                    "calls": [
                                        {
                                            "call_id": call_id,
                                            "tool": data["tool"],
                                            "params": data["params"]
                                        }
                                        for call_id, data in pending_conversations[session_id]["pending_calls"].items()
                                    ]
                                }
                            )
                        else:
                            # More tool calls coming - continue processing
                            continue
                    
                    # Add tool result to messages
                    try:
                        content = json.dumps(result) if isinstance(result, (dict, list)) else str(result)
                    except Exception as e:
                        content = f"Error serializing result: {str(e)}"
                    
                    tool_message = {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": content
                    }
                    messages.append(tool_message)
                    last_tool_result = result
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
        
        total_duration = time.time() - start_time
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
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tool-reply-batch", response_model=ToolReplyResponse)
def tool_reply_batch(req: dict):
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
            raise HTTPException(status_code=404, detail="Session not found in pending conversations")
        
        conversation = pending_conversations[session_id]
        
        # Store all results
        for result in results:
            call_id = result.get('callId')
            if call_id in conversation["pending_calls"]:
                conversation["pending_calls"][call_id]["result"] = result.get('result')
                print(f"Stored result for {call_id}")
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
                raise HTTPException(status_code=500, detail=f"Failed to serialize result: {str(e)}")
            
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
            
            # Call OpenAI with tools
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.1,
                max_tokens=1000
            )
            
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
                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments)
                    
                    # Log tool call
                    tool_start = time.time()
                    print(f"Tool call: {tool_name}({tool_args})")
                    
                    # Execute tool
                    try:
                        if tool_name == "telemetry_index":
                            result = TOOL_FUNCTIONS[tool_name](tool_args["sessionId"])
                        elif tool_name == "metrics_compute":
                            result = TOOL_FUNCTIONS[tool_name](tool_args["sessionId"], tool_args["metric"])
                        elif tool_name == "telemetry_slice":
                            # Bridge tool - return special response format
                            result = {
                                "type": "bridge_request",
                                "call_id": tool_call.id,
                                "tool": tool_name,
                                "params": tool_args
                            }
                        elif tool_name == "analyze_flight_baseline":
                            # Regular backend tool - execute directly
                            result = TOOL_FUNCTIONS[tool_name](tool_args["sessionId"], tool_args["stream"], 
                                                               tool_args["fields"], tool_args.get("window_size_ms", 30000))
                        elif tool_name == "detect_statistical_outliers":
                            # Regular backend tool - execute directly
                            result = TOOL_FUNCTIONS[tool_name](tool_args["sessionId"], tool_args["stream"],
                                                                    tool_args["fields"], tool_args.get("threshold_sigma", 2.5),
                                                                    tool_args.get("window_size_ms", 30000))
                        elif tool_name == "trace_causal_chains":
                            # Regular backend tool - execute directly
                            result = TOOL_FUNCTIONS[tool_name](tool_args["sessionId"], tool_args["target_timestamp_ms"],
                                                                    tool_args.get("time_window_ms", 30000))
                        else:
                            result = {"status": "error", "tool": tool_name, "error": f"Unknown tool: {tool_name}"}
                    except Exception as e:
                        print(f"Tool execution error: {str(e)}")
                        result = {"status": "error", "tool": tool_name, "error": str(e)}
                    
                    tool_duration = time.time() - tool_start
                    print(f"Tool {tool_name} completed in {tool_duration:.3f}s")
                    
                    # Log tool execution for frontend widget (only for non-bridge tools)
                    if not (isinstance(result, dict) and result.get("type") == "bridge_request"):
                        tool_execution_log.append({
                            "tool": tool_name,
                            "duration": round(tool_duration, 3),
                            "status": "completed"
                        })
                    
                    # Handle bridge requests specially
                    if isinstance(result, dict) and result.get("type") == "bridge_request":
                        session_id = tool_args["sessionId"]
                        
                        # Initialize conversation tracking if not exists
                        if session_id not in pending_conversations:
                            pending_conversations[session_id] = {
                                "messages": messages.copy(),
                                "pending_calls": {},
                                "iteration": iteration,
                                "start_time": start_time,
                                "tool_execution_log": tool_execution_log.copy()
                            }
                        else:
                            # Preserve existing tool execution log
                            pending_conversations[session_id]["tool_execution_log"].extend(tool_execution_log)
                        
                        # Add this tool call to pending calls
                        pending_conversations[session_id]["pending_calls"][tool_call.id] = {
                            "tool": tool_name,
                            "params": tool_args,
                            "result": None
                        }
                        
                        # Return bridge request response immediately
                        return ToolReplyResponse(
                            status="bridge_request",
                            message=f"New bridge request: {tool_name}"
                        )
                    
                    # Add tool result to messages
                    try:
                        content = json.dumps(result) if isinstance(result, (dict, list)) else str(result)
                    except Exception as e:
                        print(f"Error serializing tool result: {str(e)}")
                        content = str(result)
                    
                    tool_message = {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": content
                    }
                    messages.append(tool_message)
                    print(f"Added tool result to conversation")
            
            # If no tool calls, we have a final response
            if not message.tool_calls:
                break
        
        # Find the final assistant message
        reply = "Analysis completed"
        for message in reversed(messages):
            if message["role"] == "assistant" and message.get("content"):
                reply = message["content"]
                break
        
        # Get the preserved tool execution log before cleanup
        preserved_log = conversation.get("tool_execution_log", [])
        
        # Clean up the pending conversation
        del pending_conversations[session_id]
        
        total_duration = time.time() - start_time
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
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tool-reply", response_model=ToolReplyResponse)
def tool_reply(req: ToolReplyRequest):
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
            raise HTTPException(status_code=404, detail="Session not found in pending conversations")
        
        conversation = pending_conversations[session_id]
        
        # Check if this call_id is in the pending calls
        if call_id not in conversation["pending_calls"]:
            print(f"ERROR: Call {call_id} not found in pending calls for session {session_id}")
            print(f"Available pending calls: {list(conversation['pending_calls'].keys())}")
            raise HTTPException(status_code=404, detail="Call not found in pending calls")
        
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
                raise HTTPException(status_code=500, detail=f"Failed to serialize result: {str(e)}")
            
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
            
            # Call OpenAI with tools
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.1,
                max_tokens=1000
            )
            
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
                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments)
                    
                    # Log tool call
                    tool_start = time.time()
                    print(f"Tool call: {tool_name}({tool_args})")
                    
                    # Execute tool
                    try:
                        if tool_name == "telemetry_index":
                            result = TOOL_FUNCTIONS[tool_name](tool_args["sessionId"])
                        elif tool_name == "metrics_compute":
                            result = TOOL_FUNCTIONS[tool_name](tool_args["sessionId"], tool_args["metric"])
                        elif tool_name == "telemetry_slice":
                            # Bridge tool - return special response format
                            result = {
                                "type": "bridge_request",
                                "call_id": tool_call.id,
                                "tool": "telemetry_slice",
                                "params": tool_args
                            }
                        elif tool_name == "analyze_flight_baseline":
                            # Regular backend tool - execute directly
                            result = TOOL_FUNCTIONS[tool_name](tool_args["sessionId"], tool_args["stream"], 
                                                               tool_args["fields"], tool_args.get("window_size_ms", 30000))
                        elif tool_name == "detect_statistical_outliers":
                            # Regular backend tool - execute directly
                            result = TOOL_FUNCTIONS[tool_name](tool_args["sessionId"], tool_args["stream"],
                                                                    tool_args["fields"], tool_args.get("threshold_sigma", 2.5),
                                                                    tool_args.get("window_size_ms", 30000))
                        elif tool_name == "trace_causal_chains":
                            # Regular backend tool - execute directly
                            result = TOOL_FUNCTIONS[tool_name](tool_args["sessionId"], tool_args["target_timestamp_ms"],
                                                                    tool_args.get("time_window_ms", 30000))
                        else:
                            result = {"status": "not_implemented", "tool": tool_name}
                    except Exception as e:
                        print(f"Error executing tool {tool_name}: {str(e)}")
                        result = {"status": "error", "tool": tool_name, "error": str(e)}
                    
                    tool_duration = time.time() - tool_start
                    print(f"Tool {tool_name} completed in {tool_duration:.3f}s")
                    
                    # Log tool execution for frontend widget (only for non-bridge tools)
                    if not (isinstance(result, dict) and result.get("type") == "bridge_request"):
                        tool_execution_log.append({
                            "tool": tool_name,
                            "duration": round(tool_duration, 3),
                            "status": "completed"
                        })
                    
                    # Handle bridge requests specially
                    if isinstance(result, dict) and result.get("type") == "bridge_request":
                        session_id = tool_args["sessionId"]
                        
                        # Initialize conversation tracking if not exists
                        if session_id not in pending_conversations:
                            pending_conversations[session_id] = {
                                "messages": messages.copy(),
                                "pending_calls": {},
                                "iteration": iteration,
                                "start_time": start_time,
                                "tool_execution_log": tool_execution_log.copy()
                            }
                        else:
                            # Preserve existing tool execution log
                            pending_conversations[session_id]["tool_execution_log"].extend(tool_execution_log)
                        
                        # Add this tool call to pending calls
                        pending_conversations[session_id]["pending_calls"][tool_call.id] = {
                            "tool": tool_name,
                            "params": tool_args,
                            "result": None
                        }
                        
                        # Return bridge request response immediately
                        return ToolReplyResponse(
                            status="bridge_request",
                            message=f"New bridge request: {tool_name}"
                        )
                    
                    # Add tool result to messages
                    try:
                        content = json.dumps(result) if isinstance(result, (dict, list)) else str(result)
                    except Exception as e:
                        content = f"Error serializing result: {str(e)}"
                    
                    tool_message = {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": content
                    }
                    messages.append(tool_message)
            else:
                # Model provided final answer
                break
        
        # Get final response - look for the last assistant message with content
        reply = "I apologize, but I encountered an issue processing your request."
        for message in reversed(messages):
            if message["role"] == "assistant" and message.get("content"):
                reply = message["content"]
                break
        
        # Get the preserved tool execution log before cleanup
        preserved_log = conversation.get("tool_execution_log", [])
        
        # Clean up the pending conversation
        del pending_conversations[session_id]
        
        total_duration = time.time() - start_time
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
        raise HTTPException(status_code=500, detail=str(e))