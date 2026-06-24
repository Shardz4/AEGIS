/**
 * AEGIS Utilities — Monochrome functional helpers
 */

/**
 * Returns a CSS color for a risk score (0–100).
 * Uses grayscale for low scores, muted amber for moderate, red for critical.
 */
export function getRiskColor(score) {
    if (score < 30) {
        // Low: dark gray (doesn't draw attention)
        const brightness = 40 + (score / 30) * 20;
        return `rgb(${brightness}, ${brightness}, ${brightness})`;
    } else if (score < 60) {
        // Moderate: fade from gray toward warm amber
        const t = (score - 30) / 30;
        const r = Math.round(60 + t * 116);  // -> 176
        const g = Math.round(60 + t * 76);   // -> 136
        const b = Math.round(60 - t * 12);   // -> 48
        return `rgb(${r}, ${g}, ${b})`;
    } else {
        // High/Critical: muted red
        const t = Math.min(1, (score - 60) / 40);
        const r = Math.round(176 + t * 28);  // -> 204
        const g = Math.round(136 - t * 85);  // -> 51
        const b = Math.round(48 - t * 0);    // -> 48
        return `rgb(${r}, ${g}, ${b})`;
    }
}

/**
 * Maps score to a severity class name
 */
export function getSeverity(score) {
    if (score >= 70) return 'critical';
    if (score >= 40) return 'warning';
    if (score >= 20) return 'watch';
    return 'nominal';
}

/**
 * 3-char severity abbreviation for dense display
 */
export function getSeverityCode(score) {
    if (score >= 70) return 'CRT';
    if (score >= 40) return 'WRN';
    if (score >= 20) return 'WCH';
    return 'NOM';
}

/**
 * Format seconds to compact TTI string
 */
export function formatTTI(seconds) {
    if (seconds === null || seconds === undefined) return '---';
    if (seconds <= 0) return 'NOW';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m${s > 0 ? ' ' + s + 's' : ''}`;
}

/**
 * Format timestamp to HH:MM:SS
 */
export function formatTimestamp(ts) {
    const d = ts ? new Date(ts * 1000) : new Date();
    return d.toTimeString().split(' ')[0];
}
