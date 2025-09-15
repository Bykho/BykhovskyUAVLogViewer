// src/tools/downsample1Hz.js
// Purpose: Extrema-preserving 1Hz downsampling for telemetry data

/**
 * Downsample data to 1Hz while preserving extrema (min, max, first, last)
 * Buckets data by integer second and keeps key data points
 */
export function downsample1HzExtrema (rows, getT, getValue) {
    if (!Array.isArray(rows) || rows.length === 0) return []

    const buckets = new Map()

    // Group data by second
    for (const row of rows) {
        const t = getT(row)
        if (t == null) continue

        const second = Math.floor(t / 1000)
        const value = getValue(row)

        if (!buckets.has(second)) {
            buckets.set(second, {
                first: { t, value, row },
                last: { t, value, row },
                min: { t, value, row },
                max: { t, value, row },
                count: 0
            })
        }

        const bucket = buckets.get(second)
        bucket.count++
        bucket.last = { t, value, row }

        if (value != null && Number.isFinite(value)) {
            if (bucket.min.value == null || value < bucket.min.value) {
                bucket.min = { t, value, row }
            }
            if (bucket.max.value == null || value > bucket.max.value) {
                bucket.max = { t, value, row }
            }
        }
    }

    // Convert buckets to array, keeping extrema
    const result = []
    for (const [, bucket] of buckets) {
        // Always include first and last
        result.push(bucket.first)
        result.push(bucket.last)

        // Include min and max if they're different from first/last
        if (bucket.min.t !== bucket.first.t && bucket.min.t !== bucket.last.t) {
            result.push(bucket.min)
        }
        if (bucket.max.t !== bucket.first.t && bucket.max.t !== bucket.last.t &&
            bucket.max.t !== bucket.min.t) {
            result.push(bucket.max)
        }
    }

    // Sort by timestamp and remove duplicates
    return result
        .sort((a, b) => a.t - b.t)
        .filter((item, index, arr) =>
            index === 0 || item.t !== arr[index - 1].t
        )
}

/**
 * Simple 1Hz downsampling (existing function, kept for compatibility)
 */
export function downsample1Hz (rows, getT) {
    if (!Array.isArray(rows) || rows.length === 0) return []

    const buckets = new Map()

    for (const row of rows) {
        const t = getT(row)
        if (t == null) continue

        const second = Math.floor(t / 1000)
        if (!buckets.has(second)) {
            buckets.set(second, row)
        }
    }

    return Array.from(buckets.values())
        .sort((a, b) => getT(a) - getT(b))
}

/**
 * Downsample altitude data with extrema preservation
 */
export function downsampleAltitude1Hz (altitudeRows) {
    return downsample1HzExtrema(
        altitudeRows,
        (row) => row.t,
        (row) => row.altM
    ).map(item => ({
        t: item.t,
        altM: item.value
    }))
}

/**
 * Downsample GPS data with extrema preservation
 */
export function downsampleGps1Hz (gpsRows) {
    return downsample1HzExtrema(
        gpsRows,
        (row) => row.t,
        (row) => row.fix
    ).map(item => ({
        t: item.t,
        fix: item.row.fix,
        sats: item.row.sats
    }))
}

/**
 * Downsample position data with extrema preservation
 */
export function downsampleGpos1Hz (gposRows) {
    return downsample1HzExtrema(
        gposRows,
        (row) => row.t,
        (row) => row.lat
    ).map(item => ({
        t: item.t,
        lat: item.row.lat,
        lon: item.row.lon,
        relAltM: item.row.relAltM
    }))
}

/**
 * Downsample battery data with extrema preservation
 */
export function downsampleBattery1Hz (batteryRows) {
    return downsample1HzExtrema(
        batteryRows,
        (row) => row.t,
        (row) => row.voltage || row.temp || row.current || row.remaining
    ).map(item => ({
        t: item.t,
        voltage: item.row.voltage,
        current: item.row.current,
        temp: item.row.temp,
        remaining: item.row.remaining
    }))
}
