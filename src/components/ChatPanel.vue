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
import { buildDigest } from '../tools/telemetryDigest.js'

export default {
    name: 'ChatPanel',
    data () {
        return {
            question: '',
            messages: [],
            loading: false,
            presetQuestions: [
                'What was the highest altitude?',
                'Were there any critical errors?',
                'How long was the flight?',
                'Any GPS issues?',
                'What was the flight path?'
            ]
        }
    },
    methods: {
        async send () {
            const q = this.question && this.question.trim()
            if (!q || this.loading) return

            this.messages.push({ role: 'user', text: q, isJson: false })
            this.question = ''
            this.loading = true

            try {
                // Debug: Log what we actually have in the store
                console.log('=== CHAT DEBUG START ===')
                console.log('store keys', Object.keys((store.state || store) || {}))
                console.log('sample VFR_HUD row', (store.state?.VFR_HUD || [])[0])
                console.log('sample GLOBAL_POSITION_INT row', (store.state?.GLOBAL_POSITION_INT || [])[0])
                console.log('sample STATUSTEXT row', (store.state?.STATUSTEXT || [])[0])

                // Let's see what altitude-related keys exist
                const storeData = store.state || store
                const allKeys = Object.keys(storeData)
                console.log('All store keys:', allKeys)
                const altitudeKeys = allKeys.filter(key =>
                    key.toLowerCase().includes('alt') ||
                    key.toLowerCase().includes('vfr') ||
                    key.toLowerCase().includes('hud') ||
                    key.toLowerCase().includes('position') ||
                    key.toLowerCase().includes('gps') ||
                    key.toLowerCase().includes('height') ||
                    key.toLowerCase().includes('elevation')
                )
                console.log('Altitude-related keys:', altitudeKeys)
                // Let's also look for any keys that might contain arrays of data
                const arrayKeys = allKeys.filter(key => Array.isArray(storeData[key]) && storeData[key].length > 0)
                console.log('Keys with array data:', arrayKeys)

                // Show sample data from altitude-related keys
                altitudeKeys.forEach(key => {
                    const data = storeData[key]
                    if (Array.isArray(data) && data.length > 0) {
                        console.log(`Sample ${key} row:`, data[0])
                    }
                })

                // Show sample data from first few array keys to understand the data structure
                arrayKeys.slice(0, 5).forEach(key => {
                    const data = storeData[key]
                    if (Array.isArray(data) && data.length > 0) {
                        console.log(`Sample ${key} row:`, data[0])
                    }
                })
                // Build a fresh digest from the current store
                console.log('Building digest...')
                const digest = buildDigest(store)
                console.log('Digest built successfully:', digest)
                console.log('=== CHAT DEBUG END ===')

                console.log('Sending request to backend...')
                const res = await fetch('http://127.0.0.1:8000/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ question: q, digest })
                })

                console.log('Backend response status:', res.status)
                if (!res.ok) {
                    throw new Error(`HTTP ${res.status}: ${res.statusText}`)
                }

                const data = await res.json()
                const full = data.reply || ''

                // Split into the natural language part and the fenced JSON (optional)
                const match = full.match(/```json([\s\S]*?)```/i)
                if (match) {
                    const before = full.slice(0, match.index).trim()
                    const jsonBlock = match[1].trim()
                    if (before) this.messages.push({ role: 'assistant', text: before, isJson: false })
                    this.messages.push({ role: 'assistant', text: jsonBlock, isJson: true })
                } else {
                    this.messages.push({ role: 'assistant', text: full, isJson: false })
                }
            } catch (e) {
                this.messages.push({ role: 'assistant', text: `Error: ${e.message}`, isJson: false })
            } finally {
                this.loading = false
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
</style>
