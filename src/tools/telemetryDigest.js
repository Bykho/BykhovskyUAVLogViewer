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

export function buildDigest (store) {
    // Grab arrays (defensively) - try multiple possible field names
    const storeData = store?.state || store || {}

    // Try different possible field names for VFR_HUD
    const vfr = storeData.VFR_HUD || storeData.VFRHUD || storeData.vfr_hud || storeData.vfrhud || []

    // Try different possible field names for GPS_RAW_INT
    const gps = storeData.GPS_RAW_INT || storeData.GPSRAWINT || storeData.gps_raw_int || storeData.gpsrawint || []

    // Try different possible field names for GLOBAL_POSITION_INT
    const gpos = storeData.GLOBAL_POSITION_INT || storeData.GLOBALPOSITIONINT ||
                 storeData.global_position_int || storeData.globalpositionint || []

    // Try different possible field names for STATUSTEXT
    const events = storeData.STATUSTEXT || storeData.StatusText || storeData.statustext || storeData.status_text || []

    const meta = storeData.metadata || storeData.meta || {}

    // Debug logging
    console.log('Digest debug - VFR_HUD count:', vfr.length)
    console.log('Digest debug - GPS_RAW_INT count:', gps.length)
    console.log('Digest debug - GLOBAL_POSITION_INT count:', gpos.length)
    console.log('Digest debug - STATUSTEXT count:', events.length)
    if (vfr.length > 0) console.log('Digest debug - First VFR_HUD row:', vfr[0])
    if (gpos.length > 0) console.log('Digest debug - First GLOBAL_POSITION_INT row:', gpos[0])

    // 1 Hz downsampling with computed t (ms) - try multiple altitude field names
    const alt = downsample1Hz(
        vfr.map(r => {
            const t = pickTimeMs(r)
            const a = r?.alt ?? r?.Alt ?? r?.altitude ?? null
            return { t, altM: (a != null) ? Number(a) : null }
        }),
        (r) => r.t
    ).filter(x => x.t != null && Number.isFinite(x.altM))

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

    const eventsArr = (events || []).map(r => ({
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
