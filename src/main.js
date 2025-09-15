// The Vue build version to load with the `import` command
// (runtime-only or standalone) has been set in webpack.base.conf with an alias.
import Vue from 'vue'
import App from './App.vue'
import router from './router'
import { store } from './components/Globals.js'

// Importing Bootstrap Vue
import BootstrapVue from 'bootstrap-vue'
import 'bootstrap/dist/css/bootstrap.min.css'
import 'bootstrap-vue/dist/bootstrap-vue.css'

// Using imported components
import VueRouter from 'vue-router'

Vue.use(VueRouter)
Vue.use(BootstrapVue)

Vue.config.productionTip = false

Vue.prototype.$eventHub = new Vue() // Global event bus

// Expose store globally for debugging
window.store = store

// Telemetry inspection utilities
window.inspectTelemetry = function () {
    console.log('=== TELEMETRY DATA INSPECTION ===')

    // Check if messages exist
    const messages = store.messages || store.state?.messages || {}
    console.log('📊 Available Message Streams:', Object.keys(messages))

    // Count records per stream
    const streamCounts = {}
    Object.entries(messages).forEach(([streamName, streamData]) => {
        if (Array.isArray(streamData)) {
            streamCounts[streamName] = streamData.length
        } else if (streamData && typeof streamData === 'object') {
            // Columnar format - get length from first array property
            const firstKey = Object.keys(streamData)[0]
            streamCounts[streamName] = Array.isArray(streamData[firstKey]) ? streamData[firstKey].length : 0
        } else {
            streamCounts[streamName] = 0
        }
    })
    console.log('📈 Record Counts per Stream:', streamCounts)

    // Check session bundle
    if (store.sessionBundle) {
        console.log('📦 Session Bundle Status:', {
            sessionId: store.sessionBundle.sessionId,
            streams: Object.keys(store.sessionBundle.index || {}),
            events: store.sessionBundle.events?.length || 0,
            downsample1Hz: Object.keys(store.sessionBundle.downsample1Hz || {}),
            duration: store.sessionBundle.meta?.durationMs || 0
        })
    } else {
        console.log('❌ No session bundle found')
    }

    // Check for key streams
    const keyStreams = ['GLOBAL_POSITION_INT', 'GPS_RAW_INT', 'VFR_HUD', 'BATTERY_STATUS', 'RC_CHANNELS', 'STATUSTEXT']
    const missingStreams = keyStreams.filter(stream => !messages[stream])
    if (missingStreams.length > 0) {
        console.log('⚠️ Missing Key Streams:', missingStreams)
    }

    console.log('=== END INSPECTION ===')
}

window.examineStream = function (streamName, count = 5) {
    console.log(`=== EXAMINING STREAM: ${streamName} ===`)

    const messages = store.messages || store.state?.messages || {}
    const streamData = messages[streamName]

    if (!streamData) {
        console.log(`❌ Stream '${streamName}' not found`)
        return
    }

    if (Array.isArray(streamData)) {
        console.log(`📊 Stream type: Array (${streamData.length} records)`)
        console.log('Sample records:', streamData.slice(0, count))
    } else if (streamData && typeof streamData === 'object') {
        console.log('📊 Stream type: Columnar object')
        console.log('Available fields:', Object.keys(streamData))

        // Show sample data
        const firstKey = Object.keys(streamData)[0]
        const length = Array.isArray(streamData[firstKey]) ? streamData[firstKey].length : 0
        console.log(`Total records: ${length}`)

        // Convert to records for inspection
        const records = []
        for (let i = 0; i < Math.min(count, length); i++) {
            const record = {}
            Object.keys(streamData).forEach(key => {
                if (Array.isArray(streamData[key])) {
                    record[key] = streamData[key][i]
                }
            })
            records.push(record)
        }
        console.log('Sample records:', records)
    }

    console.log('=== END STREAM EXAMINATION ===')
}

window.compareUnits = function () {
    console.log('=== UNIT CONVERSION COMPARISON ===')

    const messages = store.messages || store.state?.messages || {}
    const sessionBundle = store.sessionBundle

    if (!sessionBundle) {
        console.log('❌ No session bundle available for comparison')
        return
    }

    // Check altitude units
    const gposRaw = messages.GLOBAL_POSITION_INT
    const gposDownsample = sessionBundle.downsample1Hz?.gpos

    if (gposRaw && gposDownsample) {
        console.log('🛰️ Altitude Unit Analysis:')

        // Get first few raw records
        const firstKey = Object.keys(gposRaw)[0]
        const rawLength = Array.isArray(gposRaw[firstKey]) ? gposRaw[firstKey].length : 0

        if (rawLength > 0) {
            const rawRecord = {}
            Object.keys(gposRaw).forEach(key => {
                if (Array.isArray(gposRaw[key])) {
                    rawRecord[key] = gposRaw[key][0]
                }
            })

            console.log('  Raw GLOBAL_POSITION_INT sample:', {
                time_boot_ms: rawRecord.time_boot_ms, // eslint-disable-line camelcase
                alt: rawRecord.alt,
                relative_alt: rawRecord.relative_alt, // eslint-disable-line camelcase
                lat: rawRecord.lat,
                lon: rawRecord.lon
            })
        }

        if (gposDownsample.length > 0) {
            console.log('  Downsampled gpos sample:', gposDownsample[0])
        }

        // Check VFR_HUD altitude
        const vfrRaw = messages.VFR_HUD
        const altDownsample = sessionBundle.downsample1Hz?.alt

        if (vfrRaw && altDownsample) {
            console.log('📊 VFR_HUD Analysis:')

            const firstKey = Object.keys(vfrRaw)[0]
            const rawLength = Array.isArray(vfrRaw[firstKey]) ? vfrRaw[firstKey].length : 0

            if (rawLength > 0) {
                const rawRecord = {}
                Object.keys(vfrRaw).forEach(key => {
                    if (Array.isArray(vfrRaw[key])) {
                        rawRecord[key] = vfrRaw[key][0]
                    }
                })

                console.log('  Raw VFR_HUD sample:', {
                    alt: rawRecord.alt,
                    airspeed: rawRecord.airspeed,
                    groundspeed: rawRecord.groundspeed
                })
            }

            if (altDownsample.length > 0) {
                console.log('  Downsampled alt sample:', altDownsample[0])
            }
        } else {
            console.log('⚠️ No VFR_HUD data available (expected for this log)')
        }
    } else {
        console.log('⚠️ No GLOBAL_POSITION_INT data available for comparison')
    }

    console.log('=== END UNIT COMPARISON ===')
}

console.log('🔧 Telemetry inspection tools loaded:')
console.log('  - window.inspectTelemetry() - Overview of all data')
console.log('  - window.examineStream(streamName, count) - Examine specific stream')
console.log('  - window.compareUnits() - Check unit conversions')
console.log('  - window.store - Direct access to store data')

/* eslint-disable no-new */
new Vue({
    el: '#app',
    router,
    components: { App },
    template: '<App/>'
})
