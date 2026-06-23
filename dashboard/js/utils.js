/**
 * Helper utilities for the AEGIS Operator Dashboard
 */

/**
 * Interpolates between green, amber, and red based on a 0-100 risk score.
 * Returns a hex color string.
 */
export function getRiskColor(score) {
    if (score < 40) {
        // Green to yellow-green interpolation
        // score=0 -> #00e676 (rgb 0, 230, 118)
        // score=40 -> #ff9f1c (rgb 255, 159, 28) (warning start)
        const ratio = score / 40.0;
        const r = Math.round(0 + ratio * 255);
        const g = Math.round(230 - ratio * (230 - 159));
        const b = Math.round(118 - ratio * (118 - 28));
        return `rgb(${r}, ${g}, ${b})`;
    } else if (score < 70) {
        // Amber to orange-red interpolation
        const ratio = (score - 40) / 30.0;
        const r = 255;
        const g = Math.round(159 - ratio * (159 - 58));
        const b = Math.round(28 - ratio * (28 - 58));
        return `rgb(${r}, ${g}, ${b})`;
    } else {
        // Red / Critical glow
        const ratio = Math.min(1.0, (score - 70) / 30.0);
        // score=70 -> #ff3a3a (rgb 255, 58, 58)
        // score=100 -> dark solid critical red (rgb 255, 0, 0)
        const r = 255;
        const g = Math.round(58 * (1.0 - ratio));
        const b = Math.round(58 * (1.0 - ratio));
        return `rgb(${r}, ${g}, ${b})`;
    }
}

/**
 * Translates a risk score to a string label
 */
export function getRiskLevel(score) {
    if (score >= 70.0) return "high";
    if (score >= 40.0) return "moderate";
    return "normal";
}

/**
 * Formats a duration in seconds to "Xm Ys" or "Zs"
 */
export function formatTTI(seconds) {
    if (seconds === null || seconds === undefined) {
        return "N/A";
    }
    if (seconds <= 0) {
        return "IMMEDIATE";
    }
    if (seconds < 60) {
        return `${Math.round(seconds)}s`;
    }
    const minutes = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return `${minutes}m ${secs}s`;
}

/**
 * Formats a timestamp into a local HH:MM:SS string
 */
export function formatTimestamp(ts) {
    const d = ts ? new Date(ts * 1000) : new Date();
    return d.toTimeString().split(' ')[0];
}
