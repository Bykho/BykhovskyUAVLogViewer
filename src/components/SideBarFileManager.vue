<template>
    <div>
        <li  v-if="file==null && !sampleLoaded" >
            <a @click="onLoadSample('sample')" class="section"><i class="fas fa-play"></i>  Open Sample </a>
        </li>
        <li v-if="url">
            <a @click="share" class="section"><i class="fas fa-share-alt"></i> {{ shared ? 'Copied to clipboard!' :
                'Share link'}}</a>
        </li>
        <li v-if="url">
            <a :href="'/uploaded/' + url" class="section" target="_blank"><i class="fas fa-download"></i> Download</a>
        </li>
        <div @click="browse" @dragover.prevent @drop="onDrop" id="drop_zone"
        v-if="file==null && uploadpercentage===-1  && !sampleLoaded">
            <p>Drop *.tlog or *.bin file here or click to browse</p>
            <input @change="onChange" id="choosefile" style="opacity: 0;" type="file">
        </div>
        <!--<b-form-checkbox @change="uploadFile()" class="uploadCheckbox" v-if="file!=null && !uploadStarted"> Upload
        </b-form-checkbox>-->
        <VProgress v-bind:complete="transferMessage"
                   v-bind:percent="uploadpercentage"
                   v-if="uploadpercentage > -1">
        </VProgress>
        <VProgress v-bind:complete="state.processStatus"
                   v-bind:percent="state.processPercentage"
                   v-if="state.processPercentage > -1"
        ></VProgress>
    </div>
</template>
<script>
import VProgress from './SideBarFileManagerProgressBar.vue'
import Worker from '../tools/parsers/parser.worker.js'
import { store } from './Globals'

import { MAVLink20Processor as MAVLink } from '../libs/mavlink'

const worker = new Worker()

worker.addEventListener('message', function (event) {
})

export default {
    name: 'Dropzone',
    data: function () {
        return {
            // eslint-disable-next-line no-undef
            mavlinkParser: new MAVLink(),
            uploadpercentage: -1,
            sampleLoaded: false,
            shared: false,
            url: null,
            transferMessage: '',
            state: store,
            file: null,
            uploadStarted: false,
            telemetryDataSent: false, // Flag to prevent multiple data sends
            schemaDataSent: false // Flag to prevent multiple schema sends
        }
    },
    created () {
        this.$eventHub.$on('loadType', this.loadType)
        this.$eventHub.$on('trimFile', this.trimFile)
    },
    beforeDestroy () {
        this.$eventHub.$off('open-sample')
    },
    methods: {
        trimFile () {
            worker.postMessage({ action: 'trimFile', time: this.state.timeRange })
        },
        onLoadSample (file) {
            // Reset flags for new files
            this.telemetryDataSent = false
            this.schemaDataSent = false

            let url
            if (file === 'sample') {
                this.state.file = 'sample'
                url = require('../assets/vtol.tlog').default
                this.state.logType = 'tlog'
            } else {
                url = file
                // Set the file name for display purposes
                const urlParts = url.split('/')
                this.state.file = urlParts[urlParts.length - 1]
            }
            const oReq = new XMLHttpRequest()
            console.log(`loading file from ${url}`)

            // Set the log type based on file extension
            this.state.logType = url.indexOf('.tlog') > 0 ? 'tlog' : 'bin'
            if (url.indexOf('.txt') > 0) {
                this.state.logType = 'dji'
            }

            oReq.open('GET', url, true)
            oReq.responseType = 'arraybuffer'

            // Use arrow function to preserve 'this' context
            oReq.onload = (oEvent) => {
                const arrayBuffer = oReq.response

                this.transferMessage = 'Download Done'
                this.sampleLoaded = true
                worker.postMessage({
                    action: 'parse',
                    file: arrayBuffer,
                    isTlog: (url.indexOf('.tlog') > 0),
                    isDji: (url.indexOf('.txt') > 0)
                })
            }
            oReq.addEventListener('progress', (e) => {
                if (e.lengthComputable) {
                    this.uploadpercentage = 100 * e.loaded / e.total
                }
            }
            , false)
            oReq.onerror = (error) => {
                alert('unable to fetch remote file, check CORS settings in the target server')
                console.log(error)
            }

            oReq.send()
        },
        onChange (ev) {
            const fileinput = document.getElementById('choosefile')
            this.process(fileinput.files[0])
        },
        onDrop (ev) {
            // Prevent default behavior (Prevent file from being opened)
            ev.preventDefault()
            if (ev.dataTransfer.items) {
                // Use DataTransferItemList interface to access the file(s)
                for (let i = 0; i < ev.dataTransfer.items.length; i++) {
                    // If dropped items aren't files, reject them
                    if (ev.dataTransfer.items[i].kind === 'file') {
                        const file = ev.dataTransfer.items[i].getAsFile()
                        this.process(file)
                    }
                }
            } else {
                // Use DataTransfer interface to access the file(s)
                for (let i = 0; i < ev.dataTransfer.files.length; i++) {
                    console.log('... file[' + i + '].name = ' + ev.dataTransfer.files[i].name)
                    console.log(ev.dataTransfer.files[i])
                }
            }
        },
        loadType: function (type) {
            worker.postMessage({
                action: 'loadType',
                type: type
            })
        },
        process: function (file) {
            this.state.file = file.name
            this.state.processStatus = 'Pre-processing...'
            this.state.processPercentage = 100
            this.file = file
            const reader = new FileReader()
            reader.onload = function (e) {
                const data = reader.result
                worker.postMessage({
                    action: 'parse',
                    file: data,
                    isTlog: (file.name.endsWith('tlog')),
                    isDji: (file.name.endsWith('txt'))
                })
            }
            this.state.logType = file.name.endsWith('tlog') ? 'tlog' : 'bin'
            if (file.name.endsWith('.txt')) {
                this.state.logType = 'dji'
            }
            reader.readAsArrayBuffer(file)
        },
        uploadFile () {
            this.uploadStarted = true
            this.transferMessage = 'Upload Done!'
            this.uploadpercentage = 0
            const formData = new FormData()
            formData.append('file', this.file)

            const request = new XMLHttpRequest()
            request.onload = () => {
                if (request.status >= 200 && request.status < 400) {
                    this.uploadpercentage = 100
                    this.url = request.responseText
                } else {
                    alert('error! ' + request.status)
                    this.uploadpercentage = 100
                    this.transferMessage = 'Error Uploading'
                    console.log(request)
                }
            }
            request.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable) {
                    this.uploadpercentage = 100 * e.loaded / e.total
                }
            }
            , false)
            request.open('POST', '/upload')
            request.send(formData)
        },
        fixData (message) {
            if (message.name === 'GLOBAL_POSITION_INT') {
                message.lat = message.lat / 10000000
                message.lon = message.lon / 10000000
                // eslint-disable-next-line
                message.relative_alt = message.relative_alt / 1000
            }
            return message
        },
        browse () {
            document.getElementById('choosefile').click()
        },
        share () {
            const el = document.createElement('textarea')
            el.value = window.location.host + '/#/v/' + this.url
            document.body.appendChild(el)
            el.select()
            document.execCommand('copy')
            document.body.removeChild(el)
            this.shared = true
        },
        downloadFileFromURL (url) {
            const a = document.createElement('a')
            document.body.appendChild(a)
            a.style = 'display: none'
            a.href = url
            a.download = this.state.file + '-trimmed.' + this.state.logType
            a.click()
            document.body.removeChild(a)
            window.URL.revokeObjectURL(url)
        },
        async sendSchemaData () {
            try {
                // Extract schema information from parsed data
                const messageTypes = Object.keys(this.state.messages)
                const fieldStructure = {}

                // Only proceed if we have actual data
                if (messageTypes.length === 0) {
                    console.log('No message types to send schema for, skipping...')
                    return
                }

                // Prevent multiple schema sends
                if (this.schemaDataSent) {
                    console.log('Schema data already sent, skipping...')
                    return
                }
                this.schemaDataSent = true

                // Build field structure for each message type
                for (const messageType of messageTypes) {
                    const message = this.state.messages[messageType]
                    fieldStructure[messageType] = {
                        fields: Object.keys(message),
                        sampleCount: message.time_boot_ms ? message.time_boot_ms.length : 0
                    }
                }

                const schemaData = {
                    messageTypes: messageTypes,
                    logType: this.state.logType,
                    metadata: this.state.metadata,
                    fieldStructure: fieldStructure
                }

                const response = await fetch('http://localhost:8000/schema', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(schemaData)
                })

                const result = await response.json()
                console.log('Schema data sent:', result)

                // Only send telemetry data AFTER schema is completely processed
                if (result.status === 'ok' && Object.keys(result.normalizedSchema).length > 0) {
                    console.log('Schema processing complete, now sending telemetry data...')
                    await this.sendTelemetryData()
                }
            } catch (error) {
                console.error('Error sending schema data:', error)
            }
        },
        async sendTelemetryData () {
            try {
                const messageTypes = Object.keys(this.state.messages)
                console.log(`Sending telemetry data for ${messageTypes.length} message types`)

                // Only proceed if we have actual data
                if (messageTypes.length === 0) {
                    console.log('No message types to send, skipping...')
                    return
                }

                // Prevent multiple data sends
                if (this.telemetryDataSent) {
                    console.log('Telemetry data already sent, skipping...')
                    return
                }

                // Set flag immediately to prevent race conditions
                this.telemetryDataSent = true
                console.log('Starting telemetry data send...')

                // Send data for each message type
                for (const messageType of messageTypes) {
                    const message = this.state.messages[messageType]
                    const fields = Object.keys(message)
                    const rowCount = message[fields[0]] ? message[fields[0]].length : 0

                    // Convert message data to rows format
                    const rows = []
                    for (let i = 0; i < rowCount; i++) {
                        const row = {}
                        for (const field of fields) {
                            // Handle undefined values and ensure we get scalar values, not arrays
                            if (message[field] && message[field][i] !== undefined) {
                                const value = message[field][i]
                                // If it's still an array, take the first element
                                row[field] = Array.isArray(value) ? value[0] : value
                            } else {
                                row[field] = null
                            }
                        }
                        rows.push(row)
                    }

                    // Only send if we have data
                    if (rows.length > 0) {
                        console.log(`Sending ${rows.length} rows for ${messageType}`)
                        console.log('Sample row:', rows[0]) // Debug: show first row structure

                        // Send to backend
                        const response = await fetch('http://localhost:8000/data', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json'
                            },
                            body: JSON.stringify({
                                messageType: messageType,
                                rows: rows
                            })
                        })

                        const result = await response.json()
                        console.log(`Telemetry data sent for ${messageType}:`, result)
                    }
                }
                console.log('Telemetry data sending completed')
            } catch (error) {
                console.error('Error sending telemetry data:', error)
            }
        }
    },
    mounted () {
        window.addEventListener('message', (event) => {
            if (event.data.type === 'arrayBuffer') {
                worker.postMessage({
                    action: 'parse',
                    file: event.data.data,
                    isTlog: false,
                    isDji: false
                })
            }
        })
        worker.onmessage = (event) => {
            if (event.data.percentage) {
                this.state.processPercentage = event.data.percentage
            } else if (event.data.availableMessages) {
                this.$eventHub.$emit('messageTypes', event.data.availableMessages)
            } else if (event.data.metadata) {
                this.state.metadata = event.data.metadata
            } else if (event.data.messages) {
                this.state.messages = event.data.messages
                this.$eventHub.$emit('messages')
                // Don't send telemetry data here - wait for messagesDoneLoading
            } else if (event.data.messagesDoneLoading) {
                this.$eventHub.$emit('messagesDoneLoading')
                this.sendSchemaData()
                // Telemetry data will be sent automatically after schema completes
            } else if (event.data.messageType) {
                this.state.messages[event.data.messageType] = event.data.messageList
                this.$eventHub.$emit('messages')
            } else if (event.data.files) {
                this.state.files = event.data.files
                this.$eventHub.$emit('messages')
            } else if (event.data.url) {
                this.downloadFileFromURL(event.data.url)
            }
        }
        const url = document.location.search.split('?file=')[1]
        if (url) {
            this.onLoadSample(decodeURIComponent(url))
        }
    },
    components: {
        VProgress
    }
}
</script>
<style scoped>

    /* NAVBAR */

    #drop_zone {
        padding-top: 25px;
        padding-left: 10px;
        border: 2px dashed #434b52da;
        width: auto;
        height: 100px;
        margin: 20px;
        border-radius: 5px;
        cursor: default;
        background-color: rgba(0, 0, 0, 0);
    }

    #drop_zone:hover {
        background-color: #171e2450;
    }

    .uploadCheckbox {
        margin-left: 20px;
    }

</style>
