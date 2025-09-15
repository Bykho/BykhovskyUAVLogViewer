// src/tools/buildStreamIndex.js
// Purpose: Build stream indexes for telemetry data discovery

/**
 * Build stream index from converted message records
 */
export function buildStreamIndex (messages) {
    const index = {}

    for (const [streamName, records] of Object.entries(messages)) {
        if (!Array.isArray(records) || records.length === 0) continue

        // Find records with valid timestamps
        const validRecords = records.filter(r => r.t != null && Number.isFinite(r.t))
        if (validRecords.length === 0) continue

        // Sort by timestamp
        validRecords.sort((a, b) => a.t - b.t)

        const first = validRecords[0]
        const last = validRecords[validRecords.length - 1]
        const duration = last.t - first.t

        // Calculate sample rate
        const sampleHz = duration > 0 ? (validRecords.length / (duration / 1000)) : 0

        // Get available fields (exclude timestamp fields)
        const fields = Object.keys(first).filter(key =>
            !['t', 't_ms', 'timestamp', '_timestamp', 'ts'].includes(key)
        )

        index[streamName] = {
            count: validRecords.length,
            tFirst: first.t,
            tLast: last.t,
            sampleHz: Math.round(sampleHz * 10) / 10, // Round to 1 decimal
            fields: fields
        }
    }

    return index
}

/**
 * Build stream index from raw message objects (columnar format)
 */
export function buildStreamIndexFromRaw (rawMessages) {
    const index = {}

    for (const [streamName, messageObj] of Object.entries(rawMessages)) {
        if (!messageObj || typeof messageObj !== 'object') continue

        // Check if this looks like a columnar message object
        const keys = Object.keys(messageObj)
        if (keys.length === 0) continue

        // Find timestamp field
        const timeFields = ['time_boot_ms', 'TimeUS', 'time_unix_ms', 'time_unix_usec', '_timestamp']
        let timeArray = null

        for (const field of timeFields) {
            if (Array.isArray(messageObj[field]) && messageObj[field].length > 0) {
                timeArray = messageObj[field]
                break
            }
        }

        if (!timeArray) continue

        // Find valid timestamps
        const validTimes = timeArray.filter(t => t != null && Number.isFinite(t))
        if (validTimes.length === 0) continue

        const sortedTimes = [...validTimes].sort((a, b) => a - b)
        const first = sortedTimes[0]
        const last = sortedTimes[sortedTimes.length - 1]
        const duration = last - first

        // Calculate sample rate
        const sampleHz = duration > 0 ? (validTimes.length / (duration / 1000)) : 0

        // Get available fields (exclude timestamp fields)
        const fields = keys.filter(key => !timeFields.includes(key))

        index[streamName] = {
            count: validTimes.length,
            tFirst: first,
            tLast: last,
            sampleHz: Math.round(sampleHz * 10) / 10,
            fields: fields
        }
    }

    return index
}

/**
 * Get key telemetry streams for session bundle
 */
export function getKeyStreams () {
    return [
        'GLOBAL_POSITION_INT',
        'GPS_RAW_INT',
        'VFR_HUD',
        'STATUSTEXT',
        'ATTITUDE',
        'HEARTBEAT'
    ]
}

/**
 * Filter index to only include key streams
 */
export function filterKeyStreams (index) {
    const keyStreams = getKeyStreams()
    const filtered = {}

    for (const stream of keyStreams) {
        if (index[stream]) {
            filtered[stream] = index[stream]
        }
    }

    return filtered
}
