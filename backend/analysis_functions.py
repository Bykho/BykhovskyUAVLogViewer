
from typing import Dict, List, Any

def analyze_statistical_outliers_pure(data: Dict, fields: List[str], threshold_sigma: float, window_size_ms: int) -> Dict[str, Any]:
    """Analyze telemetry data for statistical outliers - pure function version"""
    rows = data.get('rows', [])
    stream = data.get('stream', 'unknown')
    
    if not rows:
        return {
            "ok": False,
            "error": "No data provided",
            "methodology": "Data validation",
            "findings": {},
            "confidence": 0.0,
            "data_quality": "No records in dataset"
        }
    
    if len(rows) < 10:
        return {
            "ok": False,
            "error": f"Insufficient data for analysis: {len(rows)} records",
            "methodology": "Data sufficiency check",
            "findings": {},
            "confidence": 0.0,
            "data_quality": f"Only {len(rows)} records available, need at least 10"
        }
    
    try:
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


def analyze_baseline_pure(data: Dict, fields: List[str], window_size_ms: int) -> Dict[str, Any]:
    """Analyze telemetry data for baselines - pure function version"""
    rows = data.get('rows', [])
    stream = data.get('stream', 'unknown')
    
    if not rows:
        return {
            "ok": False,
            "error": "No data provided",
            "methodology": "Data validation",
            "findings": {},
            "confidence": 0.0,
            "data_quality": "No records in dataset"
        }
    
    if len(rows) < 10:
        return {
            "ok": False,
            "error": f"Insufficient data for analysis: {len(rows)} records",
            "methodology": "Data sufficiency check",
            "findings": {},
            "confidence": 0.0,
            "data_quality": f"Only {len(rows)} records available, need at least 10"
        }
    
    try:
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


def trace_causal_chains_pure(data: Dict, target_timestamp_ms: int, time_window_ms: int = 30000) -> Dict[str, Any]:
    """Find STATUSTEXT events that may be causally related to a target timestamp - pure function version"""
    events = data.get('events', [])
    stream = data.get('stream', 'unknown')
    
    if not events:
        return {
            "ok": False,
            "error": "No events provided",
            "methodology": "Data validation",
            "findings": {},
            "confidence": 0.0,
            "data_quality": "No events in dataset"
        }
    
    try:
        # Search for STATUSTEXT events within the time window
        nearby_events = []
        window_start = target_timestamp_ms - time_window_ms
        window_end = target_timestamp_ms + time_window_ms
        
        # Look through events for STATUSTEXT messages
        for event in events:
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
            "data_quality": f"Analyzed {len(events)} total events in dataset. " +
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


