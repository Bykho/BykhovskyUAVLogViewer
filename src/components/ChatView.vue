<template>
    <div class="chat-view">
        <h3>Planner Sandbox</h3>

        <!-- Connection Status Indicator -->
        <div class="connection-status" :class="connectionState">
            <span v-if="connectionState === 'connected'">🟢 Connected</span>
            <span v-else-if="connectionState === 'connecting'">🟡 Connecting...</span>
            <span v-else-if="connectionState === 'disconnected'">🔴 Disconnected</span>
            <span v-else-if="connectionState === 'error'">🔴 Connection Error</span>
            <span v-else-if="connectionState === 'failed'">🔴 Connection Failed</span>
            <button v-if="connectionState !== 'connected'" @click="reconnectWebSocket" class="reconnect-btn">
                Reconnect
            </button>
        </div>

        <!-- Plan Display -->
        <div class="plan-section">
            <h4>Plan Steps:</h4>
            <p v-if="loading">Loading plan...</p>
            <ul v-else class="plan-steps">
                <li v-for="step in plan" :key="step.id"
                    :class="['plan-step', `status-${step.status}`]">
                    <span class="step-text">{{ step.text }}</span>
                    <span v-if="step.status === 'done'" class="checkmark">✔</span>
                </li>
            </ul>
        </div>

        <!-- Chat Interface -->
        <div class="chat-section">
            <h4>Chat with Planner:</h4>
            <div class="chat-messages">
                <div v-for="message in messages" :key="message.id"
                     :class="['message', message.type]">
                    <strong>{{ message.type === 'user' ? 'You' : 'Planner' }}:</strong>
                    {{ message.text }}
                </div>
            </div>

            <div class="chat-input">
                <input
                    v-model="newMessage"
                    @keyup.enter="sendMessage"
                    :disabled="sending"
                    placeholder="Type your message here..."
                    class="message-input"
                />
                <button
                    @click="sendMessage"
                    :disabled="sending || !newMessage.trim()"
                    class="send-button"
                >
                    {{ sending ? 'Sending...' : 'Send' }}
                </button>
            </div>
        </div>
    </div>
</template>

<script>
export default {
    name: 'ChatView',
    data () {
        return {
            plan: [],
            loading: true,
            websocket: null,
            messages: [],
            newMessage: '',
            sending: false,
            messageId: 0,
            reconnectAttempts: 0,
            maxReconnectAttempts: 5,
            reconnectInterval: 1000,
            connectionState: 'disconnected'
        }
    },
    mounted () {
        this.connectWebSocket()
    },
    beforeDestroy () {
        if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
            this.websocket.close(1000, 'Component destroyed') // Clean close
        }
    },
    methods: {
        connectWebSocket () {
            try {
                console.log(`🔄 Connecting to WebSocket... (attempt ${this.reconnectAttempts + 1})`)
                this.connectionState = 'connecting'
                this.websocket = new WebSocket('ws://localhost:8000/ws/plan')

                this.websocket.onopen = () => {
                    console.log('✅ WebSocket connection opened successfully')
                    console.log('WebSocket state:', this.websocket.readyState)
                    this.connectionState = 'connected'
                    this.reconnectAttempts = 0
                    this.reconnectInterval = 1000 // Reset to initial interval
                }

                this.websocket.onmessage = (event) => {
                    console.log('Received message:', event.data)
                    const data = JSON.parse(event.data)

                    if (Array.isArray(data)) {
                        // This is a valid plan update (legacy format)
                        console.log('📋 Plan updated:', data)
                        this.plan = data
                        this.loading = false
                    } else if (data.plan) {
                        // This is a new format with plan and optional final_answer
                        console.log('📋 Plan updated:', data.plan)
                        this.plan = data.plan
                        this.loading = false

                        // Check for status messages
                        if (data.status_message) {
                            console.log('Status message received:', data.status_message)
                            this.messages.push({
                                id: this.messageId++,
                                type: 'planner',
                                text: data.status_message
                            })
                        }

                        // Check for final answer
                        if (data.final_answer) {
                            console.log('Final answer received:', data.final_answer)
                            this.messages.push({
                                id: this.messageId++,
                                type: 'planner',
                                text: data.final_answer
                            })
                        }
                    } else if (data.type === 'ping') {
                        // Ignore keepalive pings
                        console.log('Ping received, keeping connection alive')
                    } else {
                        console.warn('Unknown message type:', data)
                    }
                }

                this.websocket.onerror = (error) => {
                    console.error('❌ WebSocket error:', error)
                    console.log('WebSocket state on error:', this.websocket.readyState)
                    this.connectionState = 'error'
                    this.loading = false
                }

                this.websocket.onclose = (event) => {
                    console.log('🔌 WebSocket connection closed')
                    console.log('Close code:', event.code)
                    console.log('Close reason:', event.reason)
                    console.log('Was clean:', event.wasClean)
                    console.log('WebSocket state on close:', this.websocket.readyState)
                    this.connectionState = 'disconnected'

                    // Attempt to reconnect if not a clean close and we haven't exceeded max attempts
                    if (!event.wasClean && this.reconnectAttempts < this.maxReconnectAttempts) {
                        this.scheduleReconnect()
                    } else if (this.reconnectAttempts >= this.maxReconnectAttempts) {
                        console.error('❌ Max reconnection attempts reached. WebSocket connection failed.')
                        this.connectionState = 'failed'
                    }
                }
            } catch (error) {
                console.error('Failed to connect to WebSocket:', error)
                this.connectionState = 'error'
                this.loading = false
            }
        },

        scheduleReconnect () {
            this.reconnectAttempts++
            console.log(`🔄 Scheduling reconnection in ${this.reconnectInterval}ms ` +
                `(attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`)

            setTimeout(() => {
                if (this.connectionState !== 'connected') {
                    this.connectWebSocket()
                    // Exponential backoff: increase interval after each attempt
                    this.reconnectInterval = Math.min(this.reconnectInterval * 2, 10000)
                }
            }, this.reconnectInterval)
        },

        reconnectWebSocket () {
            console.log('🔄 Manual reconnection requested')
            this.reconnectAttempts = 0
            this.reconnectInterval = 1000
            this.connectionState = 'disconnected'
            this.connectWebSocket()
        },

        async sendMessage () {
            if (!this.newMessage.trim() || this.sending) return

            const userMessage = this.newMessage.trim()
            this.newMessage = ''
            this.sending = true

            // Check WebSocket connection state before sending
            console.log('🔍 WebSocket state before sending message:', this.websocket?.readyState)
            console.log('🔍 WebSocket connection exists:', !!this.websocket)

            // Warn if WebSocket isn't connected
            if (this.connectionState !== 'connected') {
                console.warn('⚠️ WebSocket not connected - real-time updates may not work')
            }

            // Add user message to chat
            this.messages.push({
                id: this.messageId++,
                type: 'user',
                text: userMessage
            })

            try {
                const response = await fetch('http://localhost:8000/chat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ message: userMessage })
                })

                const data = await response.json()

                // Add planner response to chat
                this.messages.push({
                    id: this.messageId++,
                    type: 'planner',
                    text: data.response
                })
            } catch (error) {
                console.error('Failed to send message:', error)
                this.messages.push({
                    id: this.messageId++,
                    type: 'planner',
                    text: 'Sorry, I encountered an error. Please try again.'
                })
            } finally {
                this.sending = false
            }
        }
    }
}
</script>

<style scoped>
.chat-view {
    padding: 20px;
}

.connection-status {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 12px;
    border-radius: 5px;
    margin-bottom: 15px;
    font-size: 14px;
    font-weight: 500;
}

.connection-status.connected {
    background-color: #e6ffe6;
    color: #28a745;
    border: 1px solid #28a745;
}

.connection-status.connecting {
    background-color: #fff3cd;
    color: #856404;
    border: 1px solid #ffc107;
}

.connection-status.disconnected,
.connection-status.error,
.connection-status.failed {
    background-color: #f8d7da;
    color: #721c24;
    border: 1px solid #dc3545;
}

.reconnect-btn {
    padding: 4px 8px;
    background-color: #007bff;
    color: white;
    border: none;
    border-radius: 3px;
    cursor: pointer;
    font-size: 12px;
}

.reconnect-btn:hover {
    background-color: #0056b3;
}

.plan-steps {
    list-style: none;
    padding: 0;
    margin: 0;
}

.plan-step {
    padding: 10px;
    margin: 5px 0;
    border-radius: 5px;
    border-left: 4px solid #ccc;
    background-color: #f9f9f9;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.plan-step.status-pending {
    color: #666;
    border-left-color: #ccc;
    background-color: #f5f5f5;
}

.plan-step.status-active {
    color: #0066cc;
    border-left-color: #0066cc;
    background-color: #e6f3ff;
    font-weight: bold;
}

.plan-step.status-done {
    color: #28a745;
    border-left-color: #28a745;
    background-color: #e6ffe6;
}

.plan-step.status-dropped {
    color: #999;
    border-left-color: #999;
    background-color: #f0f0f0;
    text-decoration: line-through;
    opacity: 0.7;
}

.step-text {
    flex: 1;
}

.checkmark {
    color: #28a745;
    font-weight: bold;
    margin-left: 10px;
}

h4 {
    margin-bottom: 15px;
    color: white;
}

/* Chat Interface Styles */
.chat-section {
    margin-top: 30px;
    border-top: 1px solid #ddd;
    padding-top: 20px;
}

.chat-messages {
    height: 200px;
    overflow-y: auto;
    border: 1px solid #ddd;
    border-radius: 5px;
    padding: 10px;
    margin-bottom: 10px;
    background-color: #f9f9f9;
}

.message {
    margin-bottom: 10px;
    padding: 8px;
    border-radius: 5px;
    color: #333;
}

.message.user {
    background-color: #e3f2fd;
    text-align: right;
    color: #333;
}

.message.planner {
    background-color: #f1f8e9;
    text-align: left;
    color: #333;
}

.chat-input {
    display: flex;
    gap: 10px;
}

.message-input {
    flex: 1;
    padding: 8px;
    border: 1px solid #ddd;
    border-radius: 5px;
    font-size: 14px;
}

.message-input:focus {
    outline: none;
    border-color: #0066cc;
}

.send-button {
    padding: 8px 16px;
    background-color: #0066cc;
    color: white;
    border: none;
    border-radius: 5px;
    cursor: pointer;
    font-size: 14px;
}

.send-button:hover:not(:disabled) {
    background-color: #0052a3;
}

.send-button:disabled {
    background-color: #ccc;
    cursor: not-allowed;
}

.plan-section {
    margin-bottom: 20px;
}
</style>
