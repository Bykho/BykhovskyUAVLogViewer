// src/tools/buildEvents.js
// Purpose: Extract events from STATUSTEXT messages

/**
 * Extract events from STATUSTEXT records
 */
export function buildEvents (statustextRecords) {
    if (!Array.isArray(statustextRecords) || statustextRecords.length === 0) {
        return []
    }

    return statustextRecords
        .map(record => {
            const t = record.t || record.time_boot_ms || record.TimeUS
            const severity = record.severity || record.Severity
            const text = record.text || record.Text

            if (t == null || text == null) return null

            return {
                t: Number(t),
                severity: severity != null ? Number(severity) : null,
                text: String(text).trim()
            }
        })
        .filter(event => event != null && event.text.length > 0)
        .sort((a, b) => a.t - b.t)
}

/**
 * Extract events from raw STATUSTEXT message object (columnar format)
 */
export function buildEventsFromRaw (statustextObj) {
    if (!statustextObj || typeof statustextObj !== 'object') {
        return []
    }

    // Find timestamp field
    const timeFields = ['time_boot_ms', 'TimeUS', 'time_unix_ms', 'time_unix_usec', '_timestamp']
    let timeArray = null

    for (const field of timeFields) {
        if (Array.isArray(statustextObj[field]) && statustextObj[field].length > 0) {
            timeArray = statustextObj[field]
            break
        }
    }

    if (!timeArray) return []

    const severityArray = statustextObj.severity || statustextObj.Severity || []
    const textArray = statustextObj.text || statustextObj.Text || []

    const events = []
    const length = Math.min(timeArray.length, textArray.length)

    for (let i = 0; i < length; i++) {
        const t = timeArray[i]
        const severity = severityArray[i]
        const text = textArray[i]

        if (t == null || text == null) continue

        const trimmedText = String(text).trim()
        if (trimmedText.length === 0) continue

        events.push({
            t: Number(t),
            severity: severity != null ? Number(severity) : null,
            text: trimmedText
        })
    }

    return events.sort((a, b) => a.t - b.t)
}

/**
 * Filter events by severity level
 */
export function filterEventsBySeverity (events, minSeverity = 0) {
    return events.filter(event =>
        event.severity == null || event.severity >= minSeverity
    )
}

/**
 * Get critical events (high severity)
 */
export function getCriticalEvents (events) {
    return filterEventsBySeverity(events, 3) // Severity 3+ are typically critical
}

/**
 * Get error events
 */
export function getErrorEvents (events) {
    return events.filter(event =>
        event.text.toLowerCase().includes('error') ||
        event.text.toLowerCase().includes('fail') ||
        event.text.toLowerCase().includes('fault')
    )
}
