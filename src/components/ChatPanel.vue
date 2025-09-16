<template>
    <div class="chat-panel" ref="chatPanel">
        <!-- Message Area -->
        <div class="message-area">
            <div v-for="(m, i) in messages" :key="i" class="message-group">
                <div v-if="m.role === 'user'" class="message-bubble user-message">
                    <div class="message-header">You</div>
                    <div class="message-content">{{ m.text }}</div>
                </div>
                <div v-else-if="m.role === 'assistant'" class="message-bubble assistant-message">
                    <div class="message-header">Assistant</div>
                    <pre v-if="m.isJson" class="json-content">{{ m.text }}</pre>
                    <div v-else class="message-content" v-html="renderMarkdown(m.text)"></div>
                </div>

                <!-- Show "Sending..." indicator under the last user message when loading -->
                <div v-if="loading && i === messages.length - 1 && m.role === 'user'" class="sending-indicator">
                    <div class="sending-text">Sending...</div>
                </div>

                <!-- Add divider line after each conversation turn (user + assistant pair) -->
                <div v-if="i < messages.length - 1 && m.role === 'assistant'" class="conversation-divider"></div>
            </div>
            <div v-if="messages.length === 0" class="empty-state">
                <p>Ask questions about the flight data. Try:</p>
                <p class="suggestion">"What was the highest altitude?" or "Were there any critical errors?"</p>
            </div>
        </div>

        <!-- Preset Questions -->
        <div class="preset-section">
            <div class="preset-header">Quick Questions:</div>
            <div class="preset-buttons">
                <button
                    v-for="preset in presetQuestions"
                    :key="preset"
                    @click="question = preset"
                    class="preset-button"
                >
                    {{ preset }}
                </button>
            </div>
        </div>

        <!-- Input Section -->
        <div class="input-section">
            <div class="input-container">
            <input
                v-model="question"
                placeholder="Ask about this flight..."
                    class="message-input"
                @keydown.enter="send"
                :disabled="loading"
            />
            <button
                @click="send"
                    class="send-button"
                :disabled="loading || !question.trim()"
            >
                Send
            </button>
        </div>
            <div class="tool-widget-container">
                <ToolActivityWidget
                    :loading="loading"
                    :current-tool="currentTool"
                    :completed-tools="completedTools"
                    :total-iterations="totalIterations"
                    :has-new-message="hasNewMessage"
                    :tool-execution-details="toolExecutionDetails"
                />
            </div>
        </div>

        <!-- Resize Handle -->
        <div v-if="messages.length > 0" class="chat-resize-handle" @mousedown="startChatResize"></div>
    </div>
</template>

<script>
import { store } from './Globals.js'
import { marked } from 'marked'
import ToolActivityWidget from './ToolActivityWidget.vue'

export default {
    name: 'ChatPanel',
    components: {
        ToolActivityWidget
    },
    data () {
        return {
            question: '',
            messages: [],
            loading: false,
            currentTool: '',
            completedTools: [],
            totalIterations: 0,
            hasNewMessage: false,
            toolExecutionDetails: [],
            presetQuestions: [
                'What was the maximum altitude and flight duration?',
                'Are there any anomalies in this flight?',
                'How do the velocity patterns correlate with flight events?'
            ]
        }
    },
    mounted () {
        this.configureMarkdown()
    },
    methods: {
        configureMarkdown () {
            marked.setOptions({
                breaks: true, // Convert line breaks to <br>
                gfm: true, // GitHub Flavored Markdown
                sanitize: false, // We control the input, so this is safe
                smartypants: false // Disable smart quotes to avoid issues
            })
        },
        renderMarkdown (text) {
            return marked(text)
        },
        startChatResize (e) {
            e.preventDefault()
            const sidebar = this.$el.closest('.nav-side-menu')
            const chatPanel = this.$el
            const startX = e.clientX
            const startY = e.clientY
            const startWidth = sidebar.offsetWidth
            const startHeight = chatPanel.offsetHeight

            // Use the current width as the natural minimum instead of hardcoding 400px
            const naturalMinWidth = startWidth
            const naturalMinHeight = startHeight

            // Debug: log the initial state
            console.log('Resize start - startWidth:', startWidth, 'startHeight:', startHeight)
            console.log('naturalMinWidth:', naturalMinWidth, 'naturalMinHeight:', naturalMinHeight)

            const handleMouseMove = (e) => {
                const deltaX = e.clientX - startX
                const deltaY = e.clientY - startY
                const newWidth = startWidth + deltaX
                const newHeight = startHeight + deltaY

                const minWidthConstraint = naturalMinWidth // Use the natural minimum width
                const maxWidthConstraint = window.innerWidth * 0.6
                const minHeightConstraint = naturalMinHeight // Use the natural minimum height
                const maxHeightConstraint = window.innerHeight * 0.8

                // Only apply constraints if there's significant movement (threshold of 5px)
                const dragThreshold = 5
                const hasSignificantMovement = Math.abs(deltaX) > dragThreshold || Math.abs(deltaY) > dragThreshold

                let clampedWidth, clampedHeight
                if (hasSignificantMovement) {
                    clampedWidth = Math.max(minWidthConstraint, Math.min(maxWidthConstraint, newWidth))
                    clampedHeight = Math.max(minHeightConstraint, Math.min(maxHeightConstraint, newHeight))
                } else {
                    // For small movements, don't apply min constraints, just max
                    clampedWidth = Math.min(maxWidthConstraint, newWidth)
                    clampedHeight = Math.min(maxHeightConstraint, newHeight)
                }

                // Debug: log the calculation
                console.log('Mouse move - deltaX:', deltaX, 'deltaY:', deltaY)
                console.log('  - newWidth:', newWidth, 'newHeight:', newHeight)
                console.log('  - hasSignificantMovement (>5px):', hasSignificantMovement)
                console.log('  - clampedWidth:', clampedWidth, 'clampedHeight:', clampedHeight)

                // Apply width changes to sidebar with !important to override CSS media queries
                sidebar.style.setProperty('width', clampedWidth + 'px', 'important')
                sidebar.style.setProperty('max-width', clampedWidth + 'px', 'important')
                sidebar.style.setProperty('flex-basis', clampedWidth + 'px', 'important')
                sidebar.style.setProperty('flex', '0 0 ' + clampedWidth + 'px', 'important')

                // Apply height changes to chat panel
                chatPanel.style.height = clampedHeight + 'px'
                chatPanel.style.minHeight = clampedHeight + 'px'
            }

            const handleMouseUp = () => {
                document.removeEventListener('mousemove', handleMouseMove)
                document.removeEventListener('mouseup', handleMouseUp)
            }

            document.addEventListener('mousemove', handleMouseMove)
            document.addEventListener('mouseup', handleMouseUp)
        },
        async send () {
            const q = this.question && this.question.trim()
            if (!q || this.loading) return

            // Check if we have a sessionId
            console.log('Store object:', store)
            console.log('Store sessionId:', store.sessionId)
            const sessionId = store.sessionId
            if (!sessionId) {
                this.messages.push({
                    role: 'assistant',
                    text: 'Error: No flight data loaded. Please load a flight log first.',
                    isJson: false
                })
                return
            }

            // Hide the previous widget when starting new message
            this.hasNewMessage = true

            this.messages.push({ role: 'user', text: q, isJson: false })
            this.question = ''
            this.loading = true

            // Reset for new analysis after adding user message
            this.hasNewMessage = false
            this.resetToolState()

            try {
                console.log('Sending tool-calling request to backend...')
                console.log('Session ID:', sessionId)
                console.log('Question:', q)

                const res = await fetch('http://127.0.0.1:8000/chat-tools', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        sessionId: sessionId,
                        messages: this.messages.map(m => ({
                            role: m.role,
                            content: m.text
                        }))
                    })
                })

                console.log('Backend response status:', res.status)
                if (!res.ok) {
                    throw new Error(`HTTP ${res.status}: ${res.statusText}`)
                }

                const data = await res.json()
                console.log('Backend response:', data)

                // Extract tool execution information for widget
                if (data.debug && data.debug.toolExecutionLog) {
                    data.debug.toolExecutionLog.forEach(toolLog => {
                        this.updateToolState(toolLog.tool, true, toolLog)
                    })
                }

                // Check if this is a bridge request
                if (data.debug && data.debug.type === 'bridge_request') {
                    console.log('Bridge request detected:', data.debug)
                    await this.handleBridgeRequest(data.debug)
                    return
                }

                // Check if this is a batch bridge request
                if (data.debug && data.debug.type === 'batch_bridge_request') {
                    console.log('Batch bridge request detected:', data.debug)
                    await this.handleBatchBridgeRequest(data.debug)
                    return
                }

                // Add the assistant's reply
                this.messages.push({ role: 'assistant', text: data.reply, isJson: false })

                // Show debug information if available
                if (data.debug && data.debug.lastToolResult) {
                    console.log('Last tool result:', data.debug.lastToolResult)
                    console.log('Tool call iterations:', data.debug.iterations)
                    console.log('Total duration:', data.debug.duration_s + 's')
                }
            } catch (e) {
                console.error('Chat error:', e)
                this.messages.push({ role: 'assistant', text: `Error: ${e.message}`, isJson: false })
            } finally {
                this.loading = false
            }
        },
        async handleBridgeRequest (bridgeData) {
            console.log('Handling bridge request:', bridgeData)

            // Show loading message
            this.messages.push({
                role: 'assistant',
                text: 'Analyzing telemetry...',
                isJson: false
            })

            try {
                const { call_id: callId, tool, params } = bridgeData
                this.updateToolState(tool)

                if (tool === 'telemetry_slice') {
                    const sliceResult = await this.executeTelemetrySlice(params)
                    this.updateToolState(tool, true)
                    await this.sendToolReply(callId, tool, sliceResult)
                } else {
                    throw new Error(`Unknown bridge tool: ${tool}`)
                }
            } catch (error) {
                console.error('Bridge request error:', error)
                this.messages.push({
                    role: 'assistant',
                    text: `Error processing telemetry slice: ${error.message}`,
                    isJson: false
                })
            }
        },
        async handleBatchBridgeRequest (batchData) {
            console.log('Handling batch bridge request:', batchData)

            try {
                const { calls } = batchData

                // Track tools being executed
                calls.forEach(call => {
                    this.updateToolState(call.tool)
                })

                // Execute all bridge requests concurrently
                const slicePromises = calls.map(async (call) => {
                    if (call.tool === 'telemetry_slice') {
                        const sliceResult = await this.executeTelemetrySlice(call.params)
                        this.updateToolState(call.tool, true)
                        return { callId: call.call_id, tool: call.tool, result: sliceResult }
                    } else if (call.tool === 'analyze_flight_baseline') {
                        // Backend tool - not handled on frontend
                        this.updateToolState(call.tool, true)
                        return { callId: call.call_id, tool: call.tool, result: { error: 'Tool handled on backend' } }
                    } else if (call.tool === 'detect_statistical_outliers') {
                        // Backend tool - not handled on frontend
                        this.updateToolState(call.tool, true)
                        return { callId: call.call_id, tool: call.tool, result: { error: 'Tool handled on backend' } }
                    } else {
                        throw new Error(`Unknown bridge tool: ${call.tool}`)
                    }
                })

                // Wait for all slices to complete
                const results = await Promise.all(slicePromises)

                // Send batch tool reply
                await this.sendBatchToolReply(results)

                console.log('Batch bridge request completed successfully')
            } catch (error) {
                console.error('Batch bridge request error:', error)
                this.messages.push({
                    role: 'assistant',
                    text: `Error processing batch telemetry slices: ${error.message}`,
                    isJson: false
                })
            }
        },
        async executeTelemetrySlice (params) {
            const { stream, fields, start_ms: startMs, end_ms: endMs, max_points: maxPoints = 5000 } = params

            console.log('Executing telemetry slice:', params)

            // Get the session bundle from store
            const sessionBundle = store.sessionBundle
            if (!sessionBundle) {
                return {
                    ok: false,
                    stream: stream,
                    fields: fields || [],
                    rows: [],
                    count: 0,
                    truncated: false,
                    summary: {},
                    notes: 'No session bundle available'
                }
            }

            // Validate stream exists
            if (!sessionBundle.index[stream]) {
                return {
                    ok: false,
                    stream: stream,
                    fields: fields || [],
                    rows: [],
                    count: 0,
                    truncated: false,
                    summary: {},
                    notes: `Stream '${stream}' not found in session`
                }
            }

            // Get raw messages from store
            const messages = store.messages
            if (!messages || !messages[stream]) {
                return {
                    ok: false,
                    stream: stream,
                    fields: fields || [],
                    rows: [],
                    count: 0,
                    truncated: false,
                    summary: {},
                    notes: `No raw data available for stream '${stream}'`
                }
            }

            // Convert columnar data to records with unit conversions
            const records = this.convertMessageObjectToRecords(messages[stream], stream)
            if (records.length === 0) {
                return {
                    ok: false,
                    stream: stream,
                    fields: fields || [],
                    rows: [],
                    count: 0,
                    truncated: false,
                    summary: {},
                    notes: `No records found in stream '${stream}'`
                }
            }

            // Filter by time bounds if provided
            let filteredRecords = records
            if (startMs !== undefined || endMs !== undefined) {
                filteredRecords = records.filter(record => {
                    const t = record.time_boot_ms || record.TimeUS || record._timestamp || 0
                    if (startMs !== undefined && t < startMs) return false
                    if (endMs !== undefined && t > endMs) return false
                    return true
                })
            }

            // Filter by fields if provided
            let processedRecords = filteredRecords
            if (fields && fields.length > 0) {
                processedRecords = filteredRecords.map(record => {
                    const filtered = {}
                    fields.forEach(field => {
                        if (record[field] !== undefined) {
                            filtered[field] = record[field]
                        }
                    })
                    return filtered
                })
            }

            // Apply maxPoints limit
            let truncated = false
            if (processedRecords.length > maxPoints) {
                processedRecords = processedRecords.slice(0, maxPoints)
                truncated = true
            }

            // Calculate summary
            const summary = this.calculateSliceSummary(processedRecords)

            return {
                ok: true,
                stream: stream,
                fields: fields || Object.keys(processedRecords[0] || {}),
                rows: processedRecords,
                count: processedRecords.length,
                truncated: truncated,
                summary: summary,
                notes: truncated ? `Data truncated to ${maxPoints} points` : ''
            }
        },
        convertMessageObjectToRecords (messageObj, stream) {
            if (!messageObj || typeof messageObj !== 'object') return []
            const keys = Object.keys(messageObj)
            if (keys.length === 0) return []
            const firstKey = keys[0]
            const length = Array.isArray(messageObj[firstKey]) ? messageObj[firstKey].length : 0
            if (length === 0) return []
            const records = []
            for (let i = 0; i < length; i++) {
                const record = {}
                for (const key of keys) {
                    if (Array.isArray(messageObj[key])) {
                        let value = messageObj[key][i]

                        // Apply unit conversions based on stream type and field
                        if (stream === 'GLOBAL_POSITION_INT') {
                            if (key === 'lat' || key === 'lon') {
                                value = value / 10000000
                            } else if (key === 'relative_alt') { // eslint-disable-line camelcase
                                value = value / 1000
                            } else if (key === 'vx' || key === 'vy' || key === 'vz') {
                                value = value / 100 // Convert cm/s to m/s
                            }
                        } else if (stream === 'GPS_RAW_INT') {
                            if (key === 'lat' || key === 'lon') {
                                value = value / 10000000
                            } else if (key === 'alt') {
                                value = value / 1000
                            } else if (key === 'vel') {
                                value = value / 100 // Convert cm/s to m/s
                            }
                        } else if (stream === 'VFR_HUD') {
                            if (key === 'alt') {
                                value = value / 1000
                            } else if (key === 'airspeed' || key === 'groundspeed') {
                                value = value / 100 // Convert cm/s to m/s
                            }
                        }

                        record[key] = value
                    }
                }
                records.push(record)
            }
            return records
        },
        calculateSliceSummary (records) {
            if (records.length === 0) return {}

            const summary = {}
            const firstRecord = records[0]
            const lastRecord = records[records.length - 1]

            // Calculate time bounds
            const firstTime = firstRecord.time_boot_ms || firstRecord.TimeUS || firstRecord._timestamp || 0
            const lastTime = lastRecord.time_boot_ms || lastRecord.TimeUS || lastRecord._timestamp || 0

            summary.tFirst = firstTime
            summary.tLast = lastTime

            // Calculate per-field min/max for numeric fields
            const numericFields = Object.keys(firstRecord).filter(key =>
                typeof firstRecord[key] === 'number' && !isNaN(firstRecord[key])
            )

            numericFields.forEach(field => {
                const values = records.map(r => r[field]).filter(v => typeof v === 'number' && !isNaN(v))
                if (values.length > 0) {
                    summary[`${field}_min`] = Math.min(...values)
                    summary[`${field}_max`] = Math.max(...values)
                }
            })

            return summary
        },
        async sendBatchToolReply (results) {
            try {
                console.log('Sending batch tool reply:', results)

                const res = await fetch('http://127.0.0.1:8000/tool-reply-batch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        sessionId: store.sessionId,
                        results: results
                    })
                })

                if (!res.ok) {
                    throw new Error(`HTTP ${res.status}: ${res.statusText}`)
                }

                const data = await res.json()
                console.log('Batch tool reply response:', data)

                // Extract tool execution information for widget
                if (data.debug && data.debug.toolExecutionLog) {
                    data.debug.toolExecutionLog.forEach(toolLog => {
                        this.updateToolState(toolLog.tool, true, toolLog)
                    })
                }

                if (data.status === 'completed') {
                    // Add the final response (keep the "Analyzing telemetry..." message)
                    this.messages.push({ role: 'assistant', text: data.message, isJson: false })
                } else if (data.status === 'bridge_request') {
                    // Handle nested bridge request from batch reply
                    console.log('Bridge request from batch reply, continuing conversation...')
                    this.messages.push({
                        role: 'assistant',
                        text: 'Processing additional telemetry...',
                        isJson: false
                    })
                    // Continue the conversation by making another request to the backend
                    // This will trigger the backend to continue processing the bridge request
                    setTimeout(() => {
                        this.continueConversation()
                    }, 100)
                }
            } catch (error) {
                console.error('Batch tool reply error:', error)
                this.messages.push({
                    role: 'assistant',
                    text: `Error sending batch tool reply: ${error.message}`,
                    isJson: false
                })
            }
        },
        async continueConversation () {
            try {
                console.log('Continuing conversation after bridge request...')

                const res = await fetch('http://127.0.0.1:8000/chat-tools', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        sessionId: store.sessionId,
                        messages: this.messages.map(m => ({
                            role: m.role,
                            content: m.text
                        }))
                    })
                })

                if (!res.ok) {
                    throw new Error(`HTTP ${res.status}: ${res.statusText}`)
                }

                const data = await res.json()
                console.log('Continue conversation response:', data)

                // Extract tool execution information for widget
                if (data.debug && data.debug.toolExecutionLog) {
                    data.debug.toolExecutionLog.forEach(toolLog => {
                        this.updateToolState(toolLog.tool, true, toolLog)
                    })
                }

                // Handle the response the same way as the initial send method
                if (data.debug && data.debug.type === 'bridge_request') {
                    console.log('Bridge request detected in continue:', data.debug)
                    await this.handleBridgeRequest(data.debug)
                } else if (data.debug && data.debug.type === 'batch_bridge_request') {
                    console.log('Batch bridge request detected in continue:', data.debug)
                    await this.handleBatchBridgeRequest(data.debug)
                } else {
                    // Add the assistant's reply
                    this.messages.push({ role: 'assistant', text: data.reply, isJson: false })
                }
            } catch (error) {
                console.error('Continue conversation error:', error)
                this.messages.push({
                    role: 'assistant',
                    text: `Error continuing conversation: ${error.message}`,
                    isJson: false
                })
            }
        },
        async sendToolReply (callId, tool, result) {
            try {
                console.log('Sending tool reply:', { callId, tool, result })

                const res = await fetch('http://127.0.0.1:8000/tool-reply', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        call_id: callId, // eslint-disable-line camelcase
                        tool: tool,
                        sessionId: store.sessionId,
                        result: result
                    })
                })

                if (!res.ok) {
                    throw new Error(`HTTP ${res.status}: ${res.statusText}`)
                }

                const data = await res.json()
                console.log('Tool reply response:', data)

                // Extract tool execution information for widget
                if (data.debug && data.debug.toolExecutionLog) {
                    data.debug.toolExecutionLog.forEach(toolLog => {
                        this.updateToolState(toolLog.tool, true, toolLog)
                    })
                }

                if (data.status === 'completed') {
                    // Add the final response (keep the "Analyzing telemetry..." message)
                    this.messages.push({ role: 'assistant', text: data.message, isJson: false })
                } else if (data.status === 'bridge_request') {
                    // Add processing message
                    this.messages.push({
                        role: 'assistant',
                        text: 'Processing additional telemetry...',
                        isJson: false
                    })
                    // Note: In a full implementation, you'd handle nested bridge requests here
                }
            } catch (error) {
                console.error('Tool reply error:', error)
                this.messages.push({
                    role: 'assistant',
                    text: `Error sending telemetry analysis: ${error.message}`,
                    isJson: false
                })
            }
        },
        resetToolState () {
            this.currentTool = ''
            this.completedTools = []
            this.totalIterations = 0
            this.toolExecutionDetails = []
            // Don't reset hasNewMessage here - it's managed in send()
        },
        updateToolState (toolName, isCompleted = false, details = null) {
            if (isCompleted && !this.completedTools.includes(toolName)) {
                this.completedTools.push(toolName)
                this.totalIterations++
                if (details) {
                    this.toolExecutionDetails.push(details)
                }
            }
            this.currentTool = toolName
        }
    }
}
</script>

<style scoped>
/* Design Tokens */
:root {
    --chat-primary: #007bff;
    --chat-success: #28a745;
    --chat-border: #e9ecef;
    --chat-bg: #ffffff;
    --chat-bg-alt: #f8f9fa;
    --chat-bg-dark: #2c3e50;
    --chat-text: #333333;
    --chat-text-muted: #6c757d;
    --chat-text-light: #868e96;
    --chat-text-white: #ffffff;
    --space-xs: 4px;
    --space-sm: 8px;
    --space-md: 16px;
    --space-lg: 24px;
    --radius-sm: 6px;
    --radius-md: 8px;
    --radius-lg: 12px;
    --font-main: 'Nunito Sans', sans-serif;
    --font-size-sm: 12px;
    --font-size-base: 14px;
    --font-size-lg: 16px;
}

/* Main Layout */
.chat-panel {
    display: flex;
    flex-direction: column;
    min-height: 400px;
    height: 400px;
    min-width: 100%;
    width: 100%;
    background: #1a2332;
    resize: horizontal;
    overflow: auto;
    border: 2px solid var(--chat-primary);
    border-radius: var(--radius-lg);
    font-family: var(--font-main);
    color: #ffffff;
    position: relative;
    overflow: visible;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    z-index: 1100;
}

/* Message Area */
.message-area {
    flex: 1;
    overflow-y: auto;
    padding: var(--space-md);
    display: flex;
    flex-direction: column;
    gap: calc(var(--space-md) + 8px);
}

.message-group {
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
}

.message-bubble {
    max-width: 95%;
    padding: var(--space-sm) var(--space-md);
    border-radius: var(--radius-md);
    position: relative;
}

.user-message {
    align-self: flex-end;
    background: var(--chat-primary);
    border: 1px solid var(--chat-primary);
    border-left: 3px solid #3a7bc8;
    margin-left: calc(auto + 20px);
    padding-left: calc(var(--space-md) + 8px);
    color: var(--chat-text-white);
}

.assistant-message {
    align-self: flex-start;
    background: var(--chat-bg-alt);
    border: 1px solid var(--chat-border);
    margin-right: auto;
}

.message-header {
    font-size: var(--font-size-sm);
    font-weight: 600;
    margin-bottom: var(--space-xs);
    color: var(--chat-text-muted);
}

.user-message .message-header {
    color: var(--chat-text-white);
}

.user-message .message-content {
    color: var(--chat-text-white);
}

.assistant-message .message-header {
    color: var(--chat-success);
}

.message-content {
    font-size: var(--font-size-base);
    line-height: 1.5;
    word-wrap: break-word;
}

.json-content {
    background: #f8f8f8;
    padding: var(--space-sm);
    border-radius: var(--radius-sm);
    font-size: var(--font-size-sm);
    border-left: 3px solid var(--chat-primary);
    white-space: pre-wrap;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    overflow-x: auto;
}

.empty-state {
    text-align: center;
    color: var(--chat-text-muted);
    margin-top: var(--space-lg);
}

.empty-state p {
    margin: var(--space-sm) 0;
}

.suggestion {
    font-style: italic;
    color: var(--chat-text-light);
}

/* Sending Indicator */
.sending-indicator {
    display: flex;
    justify-content: flex-end;
    margin-top: var(--space-xs);
    margin-bottom: var(--space-sm);
}

.sending-text {
    font-size: var(--font-size-sm);
    color: var(--chat-text-muted);
    font-style: italic;
    padding: 2px 8px;
    background: var(--chat-bg-alt);
    border-radius: var(--radius-sm);
    border: 1px solid var(--chat-border);
}

/* Conversation Divider */
.conversation-divider {
    height: 1px;
    background: linear-gradient(to right, transparent, var(--chat-border), transparent);
    margin: calc(var(--space-md) + 4px) 0;
    opacity: 0.6;
}

/* Preset Section */
.preset-section {
    padding: var(--space-sm) var(--space-md);
    border-bottom: 1px solid var(--chat-border);
    background: var(--chat-bg-alt);
    z-index: 10;
    position: relative;
}

.preset-header {
    font-size: var(--font-size-sm);
    font-weight: 600;
    color: var(--chat-text-muted);
    margin-bottom: var(--space-xs);
}

.preset-buttons {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    max-height: none;
    overflow: visible;
}

.preset-button {
    padding: 3px 6px;
    border-radius: 12px;
    background: #2c5aa0;
    border: 1px solid #2c5aa0;
    cursor: pointer;
    font-size: 12px;
    color: var(--chat-text-white);
    transition: all 0.2s ease;
    white-space: nowrap;
    line-height: 1.2;
}

.preset-button:hover {
    background: #0056b3;
    color: var(--chat-text-white);
    border-color: #0056b3;
}

.preset-button:active {
    transform: translateY(1px);
}

/* Input Section */
.input-section {
    padding: var(--space-md);
    padding-top: calc(var(--space-md) + 8px);
    border-top: 1px solid var(--chat-border);
    background: var(--chat-bg);
}

.input-container {
    display: flex;
    gap: var(--space-sm);
    align-items: center;
    margin-bottom: var(--space-sm);
}

.message-input {
    flex: 1;
    padding: var(--space-sm) var(--space-md);
    border: 1px solid var(--chat-border);
    border-radius: var(--radius-sm);
    font-size: var(--font-size-base);
    font-family: var(--font-main);
    min-width: 0;
    transition: border-color 0.2s ease;
}

.message-input:focus {
    outline: none;
    border-color: var(--chat-primary);
    box-shadow: 0 0 0 2px rgba(0, 123, 255, 0.1);
}

.message-input:disabled {
    background: var(--chat-bg-alt);
    cursor: not-allowed;
}

.send-button {
    padding: var(--space-sm) var(--space-md);
    border-radius: var(--radius-sm);
    background: var(--chat-primary);
    color: white;
    border: none;
    cursor: pointer;
    font-size: var(--font-size-base);
    font-family: var(--font-main);
    font-weight: 500;
    transition: all 0.2s ease;
    min-width: 80px;
    flex-shrink: 0;
}

.send-button:hover:not(:disabled) {
    background: #0056b3;
    transform: translateY(-1px);
}

.send-button:active:not(:disabled) {
    transform: translateY(0);
}

.send-button:disabled {
    background: var(--chat-text-muted);
    cursor: not-allowed;
    transform: none;
}

.tool-widget-container {
    display: flex;
    justify-content: center;
    position: relative;
    z-index: 1004;
}

/* Chat Resize Handle */
.chat-resize-handle {
    position: absolute;
    bottom: 0;
    right: 0;
    width: 20px;
    height: 20px;
    background: linear-gradient(-45deg, transparent 30%, #4a90e2 30%,
                                #4a90e2 40%, transparent 40%, transparent 60%,
                                #4a90e2 60%, #4a90e2 70%, transparent 70%);
    cursor: se-resize;
    opacity: 0.7;
    transition: opacity 0.2s ease;
    z-index: 1101;
}

.chat-resize-handle:hover {
    opacity: 1;
}

/* Markdown Styling */
.message-content h1,
.message-content h2,
.message-content h3 {
    margin: var(--space-md) 0 var(--space-sm) 0;
    font-weight: 600;
    color: var(--chat-text);
}

.message-content h1 {
    font-size: 1.5em;
    border-bottom: 2px solid var(--chat-border);
    padding-bottom: var(--space-xs);
}

.message-content h2 {
    font-size: 1.3em;
}

.message-content h3 {
    font-size: 1.1em;
}

.message-content strong {
    font-weight: 600;
    color: var(--chat-text);
}

.message-content em {
    font-style: italic;
}

.message-content ol,
.message-content ul {
    margin: var(--space-sm) 0;
    padding-left: var(--space-lg);
}

.message-content li {
    margin: var(--space-xs) 0;
    line-height: 1.5;
}

.message-content code {
    background: #f1f1f1;
    padding: 2px var(--space-xs);
    border-radius: 3px;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: 0.9em;
    color: #d63384;
}

.message-content pre {
    background: #f8f9fa;
    padding: var(--space-sm);
    border-radius: var(--radius-sm);
    border: 1px solid var(--chat-border);
    overflow-x: auto;
    margin: var(--space-sm) 0;
}

.message-content pre code {
    background: none;
    padding: 0;
    color: var(--chat-text);
}

.message-content blockquote {
    border-left: 4px solid var(--chat-primary);
    margin: var(--space-sm) 0;
    padding-left: var(--space-md);
    color: var(--chat-text-muted);
    font-style: italic;
}

.message-content table {
    border-collapse: collapse;
    width: 100%;
    margin: var(--space-sm) 0;
}

.message-content th,
.message-content td {
    border: 1px solid var(--chat-border);
    padding: var(--space-xs) var(--space-sm);
    text-align: left;
}

.message-content th {
    background: var(--chat-bg-alt);
    font-weight: 600;
}

/* Responsive Design */
@media (max-width: 768px) {
.chat-panel {
        min-height: 300px;
        height: 300px;
    }

    .message-bubble {
        max-width: 95%;
    }

    .preset-buttons {
        max-height: 80px;
    }

    .input-container {
        flex-direction: column;
        gap: var(--space-sm);
    }

    .message-input {
        width: 100%;
    }

    .send-button {
        width: 100%;
    }
}

/* Scrollbar Styling */
.message-area::-webkit-scrollbar {
    width: 6px;
}

.message-area::-webkit-scrollbar-track {
    background: var(--chat-bg-alt);
}

.message-area::-webkit-scrollbar-thumb {
    background: var(--chat-border);
    border-radius: 3px;
}

.message-area::-webkit-scrollbar-thumb:hover {
    background: var(--chat-text-muted);
}

/* Animation */
.message-bubble {
    animation: fadeInUp 0.3s ease-out;
}

@keyframes fadeInUp {
    from {
        opacity: 0;
        transform: translateY(10px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}
</style>
