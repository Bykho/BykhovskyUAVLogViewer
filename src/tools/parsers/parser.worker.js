// Worker.js
// import MavlinkParser from 'mavlinkParser'
const mavparser = require('./mavlinkParser')
const DataflashParser = require('./JsDataflashParser/parser').default
const DjiParser = require('./djiParser').default

let parser
let pendingActions = [] // Buffer actions until parser is ready
self.addEventListener('message', async function (event) {
    if (event.data === null) {
        console.log('got bad file message!')
    } else if (event.data.action === 'parse') {
        const data = event.data.file
        if (event.data.isTlog) {
            parser = new mavparser.MavlinkParser()
            parser.processData(data)
        } else if (event.data.isDji) {
            parser = new DjiParser()
            await parser.processData(data)
        } else {
            parser = new DataflashParser(true)
            parser.processData(data, ['CMD', 'MSG', 'FILE', 'MODE', 'AHR2', 'ATT', 'GPS', 'POS',
                'XKQ1', 'XKQ', 'NKQ1', 'NKQ2', 'XKQ2', 'PARM', 'MSG', 'STAT', 'EV', 'XKF4', 'FNCE'])
        }
        // Flush any actions queued before parser was ready
        if (pendingActions.length && parser) {
            try {
                for (const act of pendingActions) {
                    if (act.action === 'loadType') {
                        parser.loadType(act.type)
                    } else if (act.action === 'trimFile') {
                        parser.trimFile(act.time)
                    }
                }
            } finally {
                pendingActions = []
            }
        }
    } else if (event.data.action === 'loadType') {
        if (!parser) {
            // Queue until parser is initialized
            pendingActions.push({ action: 'loadType', type: event.data && event.data.type && event.data.type.split('[')[0] })
            return
        }
        parser.loadType(event.data.type.split('[')[0])
    } else if (event.data.action === 'trimFile') {
        if (!parser) {
            pendingActions.push({ action: 'trimFile', time: event.data && event.data.time })
            return
        }
        parser.trimFile(event.data.time)
    }
})
