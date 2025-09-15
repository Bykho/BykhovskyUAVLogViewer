<template>
    <div class="chat-panel" style="display:flex; flex-direction:column; height:100%;">
        <div style="flex:1; overflow:auto; border:1px solid #ddd; padding:8px; border-radius:8px; background: white;">
            <div v-for="(m, i) in messages" :key="i" :style="{ margin: '8px 0' }">
                <div v-if="m.role==='user'" style="font-weight:bold; color: #007bff;">You</div>
                <div v-else style="font-weight:bold; color: #28a745;">Assistant</div>
                <pre v-if="m.isJson"
                     style="white-space:pre-wrap; background:#f8f8f8; padding:8px;
                           border-radius:6px; font-size: 12px; border-left: 3px solid #007bff;">
                    {{ m.text }}
                </pre>
                <div v-else-if="m.role === 'assistant'"
                     style="margin-top: 4px;"
                     v-html="renderMarkdown(m.text)">
                </div>
                <div v-else style="margin-top: 4px;">{{ m.text }}</div>
            </div>
            <div v-if="messages.length === 0" style="text-align: center; color: #666; margin-top: 20px;">
                Ask questions about the flight data. Try: "What was the highest altitude?" or
                "Were there any critical errors?"
            </div>
        </div>

        <div style="margin-bottom: 8px;">
            <div style="display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 8px;">
                <button
                    v-for="preset in presetQuestions"
                    :key="preset"
                    @click="question = preset"
                    style="padding: 4px 8px; border-radius: 4px; background: #f8f9fa;
                           border: 1px solid #dee2e6; cursor: pointer; font-size: 12px;"
                >
                    {{ preset }}
                </button>
            </div>
        </div>

        <div style="display:flex; gap:8px; margin-top:8px;">
            <input
                v-model="question"
                placeholder="Ask about this flight..."
                style="flex:1; padding:8px; border:1px solid #ccc; border-radius:6px;"
                @keydown.enter="send"
                :disabled="loading"
            />
            <button
                @click="send"
                style="padding:8px 12px; border-radius:6px; background: #007bff;
                       color: white; border: none; cursor: pointer;"
                :disabled="loading || !question.trim()"
            >
                {{ loading ? 'Sending...' : 'Send' }}
            </button>
        </div>
    </div>
</template>

<script>
import { store } from './Globals.js'
import { marked } from 'marked'

export default {
    name: 'ChatPanel',
    data () {
        return {
            question: '',
            messages: [],
            loading: false,
            presetQuestions: [
                'What was the highest altitude?',
                'How long was the flight?',
                'When did GPS first get lost?',
                'Which streams are available?',
                'What data can you analyze?'
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

            this.messages.push({ role: 'user', text: q, isJson: false })
            this.question = ''
            this.loading = true

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

                if (tool === 'telemetry_slice') {
                    const sliceResult = await this.executeTelemetrySlice(params)
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

                // Execute all bridge requests concurrently
                const slicePromises = calls.map(async (call) => {
                    if (call.tool === 'telemetry_slice') {
                        const sliceResult = await this.executeTelemetrySlice(call.params)
                        return { callId: call.call_id, tool: call.tool, result: sliceResult }
                    } else if (call.tool === 'analyze_flight_baseline') {
                        // Backend tool - not handled on frontend
                        return { callId: call.call_id, tool: call.tool, result: { error: 'Tool handled on backend' } }
                    } else if (call.tool === 'detect_statistical_outliers') {
                        // Backend tool - not handled on frontend
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
        }
    }
}
</script>

<style scoped>
.chat-panel {
    font-family: 'Nunito Sans', sans-serif;
    color: #333;
}

.chat-panel div {
    color: #333;
}

.chat-panel pre {
    color: #333;
}

input:focus {
    outline: none;
    border-color: #007bff;
}

button:disabled {
    background: #6c757d !important;
    cursor: not-allowed;
}

/* Markdown formatting */
.chat-panel h1, .chat-panel h2, .chat-panel h3 {
    margin: 12px 0 8px 0;
    font-weight: bold;
}

.chat-panel strong {
    font-weight: bold;
}

.chat-panel em {
    font-style: italic;
}

.chat-panel ol, .chat-panel ul {
    margin: 8px 0;
    padding-left: 20px;
}

.chat-panel li {
    margin: 4px 0;
}

.chat-panel code {
    background: #f1f1f1;
    padding: 2px 4px;
    border-radius: 3px;
    font-family: monospace;
}
</style>
