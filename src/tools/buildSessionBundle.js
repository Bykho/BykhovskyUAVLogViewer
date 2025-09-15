// src/tools/buildSessionBundle.js
// Purpose: Build complete session bundle for agent access

import { makeSessionIdFromFile } from './sessionId.js'
import { buildStreamIndexFromRaw, filterKeyStreams } from './buildStreamIndex.js'
import { buildEventsFromRaw } from './buildEvents.js'
import { convertMessageObjectToRecords } from './telemetryDigest.js'
import { downsampleAltitude1Hz, downsampleGps1Hz, downsampleGpos1Hz, downsampleBattery1Hz } from './downsample1Hz.js'

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

    // Calculate metadata
    const meta = buildMetadata(store, fileName, index)

    const bundle = {
        sessionId,
        meta,
        index,
        downsample1Hz: downsample1Hz,
        events
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
        altData = vfr.map(r => ({
            t: r.time_boot_ms || r.TimeUS || r._timestamp || 0,
            altM: r.alt || r.Alt || r.altitude || null
        })).filter(x => x.t != null && x.altM != null)
    }

    if (altData.length === 0 && gpos.length > 0) {
        altData = gpos.map(r => ({
            t: r.time_boot_ms || r.TimeUS || r._timestamp || 0,
            altM: r.relative_alt || r.relativeAlt || r.rel_alt || null
        })).filter(x => x.t != null && x.altM != null)
    }

    if (altData.length > 0) {
        result.alt = downsampleAltitude1Hz(altData)
        // Guardrail: limit to reasonable number of samples
        if (result.alt.length > 10000) {
            console.warn('Altitude data has many samples, limiting to 10000')
            result.alt = result.alt.slice(0, 10000)
        }
    }

    // GPS data
    if (gps.length > 0) {
        const gpsData = gps.map(r => ({
            t: r.time_boot_ms || r.TimeUS || r._timestamp || 0,
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
        const gposData = gpos.map(r => ({
            t: r.time_boot_ms || r.TimeUS || r._timestamp || 0,
            lat: r.lat || 0,
            lon: r.lon || 0,
            relAltM: r.relative_alt || r.relativeAlt || r.rel_alt || 0
        })).filter(x => x.t != null)

        if (gposData.length > 0) {
            result.gpos = downsampleGpos1Hz(gposData)
            // Guardrail: limit to reasonable number of samples
            if (result.gpos.length > 10000) {
                console.warn('Position data has many samples, limiting to 10000')
                result.gpos = result.gpos.slice(0, 10000)
            }
        }
    }

    // Battery data
    if (battery.length > 0) {
        const batteryData = battery.map(r => ({
            t: r.time_boot_ms || r.TimeUS || r._timestamp || 0,
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

    return result
}

/**
 * Build metadata from store and index
 */
function buildMetadata (store, fileName, index) {
    // Find overall time range
    let tStart = null
    let tEnd = null

    for (const stream of Object.values(index)) {
        if (stream.tFirst != null) {
            if (tStart == null || stream.tFirst < tStart) {
                tStart = stream.tFirst
            }
        }
        if (stream.tLast != null) {
            if (tEnd == null || stream.tLast > tEnd) {
                tEnd = stream.tLast
            }
        }
    }

    const duration = tStart != null && tEnd != null ? tEnd - tStart : 0

    return {
        fileName,
        hash: store?.state?.fileHash || 'unknown',
        tStartMs: tStart || 0,
        tEndMs: tEnd || 0,
        durationMs: duration
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

    return {
        isValid: errors.length === 0,
        errors
    }
}
