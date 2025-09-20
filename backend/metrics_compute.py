from typing import Any, Dict, List, Optional, Union
from models import SessionBundle, MetricResult


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

