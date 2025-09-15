// src/tools/sessionId.js
// Purpose: Generate unique session IDs for telemetry bundles

/**
 * Generate a session ID based on file characteristics
 * Uses simple hash of file metadata for deterministic IDs
 */
export function makeSessionId (fileName, fileSize, firstBytes) {
    // Create a deterministic hash from file characteristics
    const fileInfo = `${fileName}_${fileSize}_${firstBytes}`
    const hash = simpleHash(fileInfo)
    return `session_${hash}`
}

/**
 * Simple hash function for deterministic session IDs
 * Not cryptographically secure, but sufficient for session identification
 */
function simpleHash (str) {
    let hash = 0
    if (str.length === 0) return hash.toString()

    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i)
        hash = ((hash << 5) - hash) + char
        hash = hash & hash // Convert to 32-bit integer
    }

    return Math.abs(hash).toString(16)
}

/**
 * Generate session ID from file object
 */
export function makeSessionIdFromFile (file) {
    if (!file) {
        return makeSessionId('unknown', 0, '')
    }

    // Try to get first few bytes for more unique identification
    let firstBytes = ''
    if (file instanceof File && file.size > 0) {
        // For now, use file name and size
        // In a full implementation, you'd read the first few bytes
        firstBytes = file.name.substring(0, 10)
    }

    return makeSessionId(file.name || 'unknown', file.size || 0, firstBytes)
}
