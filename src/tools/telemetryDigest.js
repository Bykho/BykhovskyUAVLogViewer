// src/tools/telemetryDigest.js
// Purpose: Convert the global store's parsed telemetry into a tiny, stable JSON digest.
// Keep it tolerant of missing fields; compute t (ms) from any available time field.

function pickTimeMs (r) {
    // Absolute first
    if (r?.time_unix_usec != null) return Math.floor(Number(r.time_unix_usec) / 1000)
    if (r?.time_unix_ms != null) return Math.floor(Number(r.time_unix_ms))
    if (r?.time_usec != null) return Math.floor(Number(r.time_usec) / 1000)
    if (r?.TimeUS != null) return Math.floor(Number(r.TimeUS) / 1000) // Dataflash-style

    // Common viewer-attached fields
    if (r?._timestamp != null) return Math.floor(Number(r._timestamp))
    if (r?.timestamp != null) return Math.floor(Number(r.timestamp))
    if (r?.ts != null) return Math.floor(Number(r.ts))
    if (r?.t != null) return Math.floor(Number(r.t))

    // Relative boot time (fallback)
    if (r?.time_boot_ms != null) return Math.floor(Number(r.time_boot_ms))

    return null
}

function downsample1Hz (rows, getT) {
    if (!Array.isArray(rows) || rows.length === 0) return []
    const out = []
    let lastSec = -Infinity
    for (const r of rows) {
        const t = getT(r)
        if (t == null) continue
        const sec = Math.floor(t / 1000)
        if (sec > lastSec) {
            out.push({ r, t })
            lastSec = sec
        }
    }
    // flatten back to simple objects with ensured t
    return out.map(({ r, t }) => ({ ...r, t }))
}

export function convertMessageObjectToRecords (messageObj) {
    if (!messageObj || typeof messageObj !== 'object') return []

    const keys = Object.keys(messageObj)
    if (keys.length === 0) return []

    // Get the length from the first array property
    const firstKey = keys[0]
    const length = Array.isArray(messageObj[firstKey]) ? messageObj[firstKey].length : 0

    if (length === 0) return []

    // Convert to array of records
    const records = []
    for (let i = 0; i < length; i++) {
        const record = {}
        for (const key of keys) {
            if (Array.isArray(messageObj[key])) {
                record[key] = messageObj[key][i]
            }
        }
        records.push(record)
    }

    return records
}

export function buildDigest (store) {
    // Look for messages in the correct location - they're nested under store.state.messages
    const messages = store?.state?.messages || store?.messages || store?.state || store || {}

    // Enhanced debugging
    console.log('=== DIGEST DEBUG ===')
    console.log('Store structure:', Object.keys(store?.state || {}))
    console.log('Messages object exists:', !!messages)
    console.log('Messages keys:', Object.keys(messages || {}))
    console.log('Messages object sample:', messages)

    // Check if we have arrays or objects for the key message types
    const messageKeys = ['VFR_HUD', 'GLOBAL_POSITION_INT', 'GPS_RAW_INT', 'STATUSTEXT']
    messageKeys.forEach(key => {
        const data = messages[key]
        console.log(`${key}:`, {
            exists: !!data,
            type: typeof data,
            isArray: Array.isArray(data),
            length: data?.length,
            keys: data ? Object.keys(data) : null,
            sample: data?.[0] || data
        })
    })
    console.log('=== END DIGEST DEBUG ===')

    // Convert message objects to record arrays
    const vfr = convertMessageObjectToRecords(messages.VFR_HUD || messages.VFRHUD)
    const gps = convertMessageObjectToRecords(messages.GPS_RAW_INT || messages.GPSRAWINT)
    const gpos = convertMessageObjectToRecords(messages.GLOBAL_POSITION_INT || messages.GLOBALPOSITIONINT)
    const events = convertMessageObjectToRecords(messages.STATUSTEXT || messages.StatusText)

    const meta = store?.state?.metadata || store?.metadata || store?.state?.meta || store?.meta || {}

    // Debug logging
    console.log('Digest debug - VFR_HUD count:', vfr.length)
    console.log('Digest debug - GPS_RAW_INT count:', gps.length)
    console.log('Digest debug - GLOBAL_POSITION_INT count:', gpos.length)
    console.log('Digest debug - STATUSTEXT count:', events.length)
    if (vfr.length > 0) console.log('Digest debug - First VFR_HUD row:', vfr[0])
    if (gpos.length > 0) console.log('Digest debug - First GLOBAL_POSITION_INT row:', gpos[0])

    // 1 Hz downsampling with computed t (ms) - try multiple altitude field names
    let alt = downsample1Hz(
        vfr.map(r => {
            const t = pickTimeMs(r)
            const a = r?.alt ?? r?.Alt ?? r?.altitude ?? null
            return { t, altM: (a != null) ? Number(a) : null }
        }),
        (r) => r.t
    ).filter(x => x.t != null && Number.isFinite(x.altM))

    // If no VFR_HUD altitude data, fallback to GLOBAL_POSITION_INT.relative_alt
    if (alt.length === 0) {
        console.log('No VFR_HUD altitude data, using GLOBAL_POSITION_INT.relative_alt as fallback')
        alt = downsample1Hz(
            gpos.map(r => {
                const t = pickTimeMs(r)
                const relAltMm = r?.relative_alt ?? r?.relativeAlt ?? r?.rel_alt ?? null
                return { t, altM: (relAltMm != null) ? Number(relAltMm) : null }
            }),
            (r) => r.t
        ).filter(x => x.t != null && Number.isFinite(x.altM))
    }

    const gpsArr = downsample1Hz(
        gps.map(r => ({
            t: pickTimeMs(r),
            fix: (r?.fix_type != null) ? Number(r.fix_type) : null,
            sats: (r?.satellites_visible != null) ? Number(r.satellites_visible) : null
        })),
        (r) => r.t
    ).filter(x => x.t != null)

    const gposArr = downsample1Hz(
        gpos.map(r => {
            const t = pickTimeMs(r)
            const relRaw = r?.relative_alt ?? r?.relativeAlt ?? r?.rel_alt ?? null // mm
            return {
                t,
                lat: (r?.lat != null) ? Number(r.lat) / 1e7 : null,
                lon: (r?.lon != null) ? Number(r.lon) / 1e7 : null,
                relAltM: (relRaw != null) ? Number(relRaw) / 1000 : null
            }
        }),
        (r) => r.t
    ).filter(x => x.t != null)

    const eventsArr = events.map(r => ({
        t: pickTimeMs(r),
        severity: (r?.severity != null) ? Number(r.severity) : null,
        text: (r?.text != null) ? String(r.text) : null
    })).filter(x => x.t != null && x.text)

    // Optionally compute meta.startMs / meta.endMs if not present
    const allTs = [
        ...alt.map(x => x.t),
        ...gpsArr.map(x => x.t),
        ...gposArr.map(x => x.t),
        ...eventsArr.map(x => x.t)
    ].filter(Number.isFinite)
    const startMs = (meta.start_ms != null)
        ? Number(meta.start_ms)
        : (allTs.length ? Math.min(...allTs) : null)
    const endMs = (meta.end_ms != null)
        ? Number(meta.end_ms)
        : (allTs.length ? Math.max(...allTs) : null)

    const metaOut = { ...meta }
    if (startMs != null) metaOut.startMs = startMs
    if (endMs != null) metaOut.endMs = endMs

    const digest = {
        alt, // [{t, altM}]
        gps: gpsArr, // [{t, fix, sats}]
        gpos: gposArr, // [{t, lat, lon, relAltM}]
        events: eventsArr, // [{t, severity, text}]
        meta: metaOut
    }

    // Debug logging
    console.log('Digest debug - Final alt count:', alt.length)
    console.log('Digest debug - Final gpos count:', gposArr.length)
    console.log('Digest debug - Final digest:', digest)

    return digest
}
