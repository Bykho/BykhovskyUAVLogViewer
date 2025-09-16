// src/tools/buildSessionBundle.js
// Purpose: Build complete session bundle for agent access

import { makeSessionIdFromFile } from './sessionId.js'
import { buildStreamIndexFromRaw, filterKeyStreams } from './buildStreamIndex.js'
import { buildEventsFromRaw } from './buildEvents.js'
import { convertMessageObjectToRecords } from './telemetryDigest.js'
import { downsampleAltitude1Hz, downsampleGps1Hz, downsampleGpos1Hz, downsampleBattery1Hz } from './downsample1Hz.js'

/**
 * Normalize timestamp to milliseconds (same logic as telemetryDigest)
 */
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

/**
 * Calculate median time delta for robust period estimation
 */
function medianDtMs (sortedRows, getT) {
    const dts = []
    for (let i = 0; i < sortedRows.length - 1; i++) {
        const t0 = getT(sortedRows[i])
        const t1 = getT(sortedRows[i + 1])
        if (t0 == null || t1 == null) continue
        const dt = t1 - t0
        if (dt > 0) dts.push(dt)
    }
    if (dts.length === 0) return 1000 // fallback ~1s
    dts.sort((a, b) => a - b)
    return dts[Math.floor(dts.length / 2)]
}

/**
 * Find gaps in time series data using actual series cadence
 */
function findGaps (rows, getT, minMs = 5000, factor = 3) {
    if (!Array.isArray(rows) || rows.length < 2) {
        return []
    }

    // Sort by timestamp and remove duplicates
    const sortedRows = rows
        .filter(r => r != null && getT(r) != null && Number.isFinite(getT(r)))
        .sort((a, b) => getT(a) - getT(b))
        .filter((r, i, arr) => i === 0 || getT(r) !== getT(arr[i - 1]))

    if (sortedRows.length < 2) {
        return []
    }

    // Calculate threshold based on actual series cadence
    const medDt = medianDtMs(sortedRows, getT)
    const thresholdMs = Math.max(minMs, Math.round(factor * medDt))

    const gaps = []

    for (let i = 0; i < sortedRows.length - 1; i++) {
        const t0 = getT(sortedRows[i])
        const t1 = getT(sortedRows[i + 1])
        const dt = t1 - t0

        if (dt > thresholdMs) {
            gaps.push({
                startMs: t0,
                endMs: t1,
                durationMs: dt,
                thresholdMs: thresholdMs
            })
        }
    }

    return gaps
}

/**
 * Build complete session bundle from store data
 */
export function buildSessionBundle (store, fileName = 'unknown') {
    // Get messages from store
    const messages = store?.state?.messages || store?.messages || store?.state || store || {}

    // Generate session ID
    const sessionId = makeSessionIdFromFile({ name: fileName })

    // Build stream index
    const fullIndex = buildStreamIndexFromRaw(messages)
    const index = filterKeyStreams(fullIndex)

    // Extract and convert key message types
    const vfr = convertMessageObjectToRecords(messages.VFR_HUD || messages.VFRHUD)
    const gps = convertMessageObjectToRecords(messages.GPS_RAW_INT || messages.GPSRAWINT)
    const gpos = convertMessageObjectToRecords(messages.GLOBAL_POSITION_INT || messages.GLOBALPOSITIONINT)

    // Extract battery data from multiple possible streams
    const battery = convertMessageObjectToRecords(
        messages.BATTERY_STATUS || messages.BATTERYSTATUS ||
        messages.SYS_STATUS || messages.SYSSTATUS ||
        messages.BAT || messages.BATT || messages.BATTERY
    )

    let events = buildEventsFromRaw(messages.STATUSTEXT || messages.StatusText)

    // Guardrail: limit events to reasonable number
    if (events.length > 1000) {
        console.warn('Too many events, limiting to 1000 most recent')
        events = events.slice(-1000)
    }

    // Build 1Hz downsampled data
    const downsample1Hz = buildDownsampledData(vfr, gps, gpos, battery)

    // Run gap detection on the 1Hz series
    const gapReport = {
        alt: findGaps(downsample1Hz.alt, r => r.t),
        gps: findGaps(downsample1Hz.gps, r => r.t),
        gpos: findGaps(downsample1Hz.gpos, r => r.t),
        battery: findGaps(downsample1Hz.battery, r => r.t)
    }

    // Calculate metadata
    const meta = buildMetadata(store, fileName, downsample1Hz)
    console.log('META durationMs:', meta.durationMs)

    const bundle = {
        sessionId,
        meta,
        index,
        downsample1Hz: downsample1Hz,
        events,
        gaps: gapReport
    }

    // Add guardrails and validation
    const validation = validateSessionBundle(bundle)
    if (!validation.isValid) {
        console.warn('Session bundle validation warnings:', validation.errors)
    }

    // Ensure no high-rate raw data slipped in
    const bundleSize = JSON.stringify(bundle).length
    if (bundleSize > 1000000) { // 1MB limit
        console.warn('Session bundle is large:', bundleSize, 'bytes')
    }

    return bundle
}

/**
 * Build downsampled 1Hz data
 */
function buildDownsampledData (vfr, gps, gpos, battery) {
    const result = {
        alt: [],
        gps: [],
        gpos: [],
        battery: []
    }

    // Altitude data (try VFR_HUD first, fallback to GLOBAL_POSITION_INT)
    let altData = []
    if (vfr.length > 0) {
        console.log('RAW VFR_HUD SAMPLE:', vfr.slice(0, 5))
        altData = vfr.map(r => ({
            t: pickTimeMs(r) || 0,
            altM: r.alt || r.Alt || r.altitude || null
        })).filter(x => x.t != null && x.altM != null)
    }

    if (altData.length === 0 && gpos.length > 0) {
        console.log('RAW GPOS SAMPLE:', gpos.slice(0, 5))
        altData = gpos.map(r => {
            const relRaw = r.relative_alt ?? r.relativeAlt ?? r.rel_alt ?? null
            return {
                t: pickTimeMs(r) || 0,
                altM: relRaw != null ? Number(relRaw) : null
            }
        }).filter(x => x.t != null && x.altM != null)
    }

    if (altData.length > 0) {
        console.log('ALT DATA after mapping:', altData.slice(0, 5))
        result.alt = downsampleAltitude1Hz(altData)
        console.log('DOWNSAMPLED ALT:', result.alt.slice(0, 5))
        // Guardrail: limit to reasonable number of samples
        if (result.alt.length > 10000) {
            console.warn('Altitude data has many samples, limiting to 10000')
            result.alt = result.alt.slice(0, 10000)
        }
    }

    // GPS data
    if (gps.length > 0) {
        const gpsData = gps.map(r => ({
            t: pickTimeMs(r) || 0,
            fix: r.fix_type || r.fixType || null,
            sats: r.satellites_visible || r.satellitesVisible || null
        })).filter(x => x.t != null)

        if (gpsData.length > 0) {
            result.gps = downsampleGps1Hz(gpsData)
            // Guardrail: limit to reasonable number of samples
            if (result.gps.length > 10000) {
                console.warn('GPS data has many samples, limiting to 10000')
                result.gps = result.gps.slice(0, 10000)
            }
        }
    }

    // Position data
    if (gpos.length > 0) {
        const gposData = gpos.map(r => {
            const relRaw = r.relative_alt ?? r.relativeAlt ?? r.rel_alt ?? null
            return {
                t: pickTimeMs(r) || 0,
                lat: r.lat || 0,
                lon: r.lon || 0,
                relAltM: relRaw != null ? Number(relRaw) : null
            }
        }).filter(x => x.t != null)

        console.log('GPOS DATA relAltM values (first 5):', gposData.slice(0, 5).map(x => x.relAltM))
        console.log('VERIFICATION: relAltM values should be ~10-100 meters, not ~0.006')

        if (gposData.length > 0) {
            result.gpos = downsampleGpos1Hz(gposData)
            // Guardrail: limit to reasonable number of samples
            if (result.gpos.length > 10000) {
                console.warn('Position data has many samples, limiting to 10000')
                result.gpos = result.gpos.slice(0, 10000)
            }
        }
    }

    // Sanity check: verify altitude scaling
    if (result.alt && result.alt.length > 0) {
        console.log('[SANITY] maxAltM', Math.max(...result.alt.map(x => x.altM)))
    }
    if (result.gpos && result.gpos.length > 0) {
        console.log('[SANITY] maxRelAltM', Math.max(...result.gpos.map(x => x.relAltM)))
    }

    // Battery data
    if (battery.length > 0) {
        const batteryData = battery.map(r => ({
            t: pickTimeMs(r) || 0,
            voltage: r.voltage || r.voltage_battery || r.voltageV || null,
            current: r.current_battery || r.current || r.currentA || null,
            temp: r.temperature || r.temp || r.tempC || r.battery_temp || null,
            remaining: r.battery_remaining || r.remaining || r.percent || null
        })).filter(x => x.t != null)

        if (batteryData.length > 0) {
            result.battery = downsampleBattery1Hz(batteryData)
            // Guardrail: limit to reasonable number of samples
            if (result.battery.length > 10000) {
                console.warn('Battery data has many samples, limiting to 10000')
                result.battery = result.battery.slice(0, 10000)
            }
        }
    }

    // --- SANITY: show first values and maxima ---
    try {
        const altHead = (result.alt || []).slice(0, 5)
        const gposHead = (result.gpos || []).slice(0, 5)

        const maxAltM = result.alt?.length
            ? Math.max(...result.alt.map(r => (r?.altM ?? -Infinity)))
            : null

        const maxRelAltM = result.gpos?.length
            ? Math.max(...result.gpos.map(r => (r?.relAltM ?? -Infinity)))
            : null

        console.log('[SANITY] ALT head:', altHead)
        console.log('[SANITY] GPOS head:', gposHead)
        console.log('[SANITY] maxAltM (from result.alt.altM):', maxAltM)
        console.log('[SANITY] maxRelAltM (from result.gpos.relAltM):', maxRelAltM)
    } catch (e) {
        console.warn('[SANITY] error computing maxima:', e)
    }

    return result
}

/**
 * Build metadata from store and index
 */
function buildMetadata (store, fileName, downsample1Hz) {
    // Find overall time range from downsampled data (which is in ms via pickTimeMs)
    let tStart = null
    let tEnd = null

    // Check all downsampled streams for time range
    for (const streamData of Object.values(downsample1Hz)) {
        if (Array.isArray(streamData) && streamData.length > 0) {
            for (const point of streamData) {
                if (point.t != null) {
                    if (tStart == null || point.t < tStart) {
                        tStart = point.t
                    }
                    if (tEnd == null || point.t > tEnd) {
                        tEnd = point.t
                    }
                }
            }
        }
    }

    const duration = tStart != null && tEnd != null ? tEnd - tStart : 0

    return {
        fileName,
        hash: store?.state?.fileHash || 'unknown',
        tStartMs: tStart || 0,
        tEndMs: tEnd || 0,
        durationMs: duration,
        schemaVersion: 2 // Indicates support for gaps field
    }
}

/**
 * Validate session bundle
 */
export function validateSessionBundle (bundle) {
    const errors = []

    if (!bundle.sessionId) errors.push('Missing sessionId')
    if (!bundle.meta) errors.push('Missing meta')
    if (!bundle.index) errors.push('Missing index')
    if (!bundle.downsample1Hz) errors.push('Missing downsample1Hz')
    if (!bundle.events) errors.push('Missing events')

    if (bundle.meta && !bundle.meta.fileName) errors.push('Missing fileName in meta')
    if (bundle.meta && bundle.meta.durationMs < 0) errors.push('Invalid durationMs')

    // Gap validation - just check structure, no percentages
    if (bundle.gaps && typeof bundle.gaps !== 'object') {
        console.warn('Gaps field should be an object with stream arrays')
    }

    return {
        isValid: errors.length === 0,
        errors
    }
}
