// src/tools/sessionApi.js
// Purpose: API client for session bundle management

const API_BASE_URL = 'http://127.0.0.1:8000'

/**
 * Post session bundle to backend
 */
export async function postSession (bundle) {
    try {
        console.log('Posting session bundle to backend:', bundle.sessionId)

        const response = await fetch(`${API_BASE_URL}/session`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(bundle)
        })

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`)
        }

        const result = await response.json()
        console.log('Session bundle posted successfully:', result)

        return result
    } catch (error) {
        console.error('Failed to post session bundle:', error)
        throw error
    }
}

/**
 * Get session bundle from backend
 */
export async function getSession (sessionId) {
    try {
        const response = await fetch(`${API_BASE_URL}/session/${sessionId}`)

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`)
        }

        return await response.json()
    } catch (error) {
        console.error('Failed to get session bundle:', error)
        throw error
    }
}

/**
 * Delete session bundle from backend
 */
export async function deleteSession (sessionId) {
    try {
        const response = await fetch(`${API_BASE_URL}/session/${sessionId}`, {
            method: 'DELETE'
        })

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`)
        }

        return await response.json()
    } catch (error) {
        console.error('Failed to delete session bundle:', error)
        throw error
    }
}

/**
 * List all sessions
 */
export async function listSessions () {
    try {
        const response = await fetch(`${API_BASE_URL}/sessions`)

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`)
        }

        return await response.json()
    } catch (error) {
        console.error('Failed to list sessions:', error)
        throw error
    }
}

/**
 * Check if backend is available
 */
export async function checkBackendHealth () {
    try {
        const response = await fetch(`${API_BASE_URL}/health`)
        return response.ok
    } catch (error) {
        return false
    }
}
