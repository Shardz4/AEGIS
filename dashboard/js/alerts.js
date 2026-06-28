/**
 * Alert Feed Renderer — Structured text, no decoration
 *
 * Each alert is a structured text block with severity indicated by
 * a left border and text weight — no emoji, no colored badges.
 */
import { formatTimestamp } from './utils.js';

const ZONE_NAMES = {
    0: "Tank Farm",
    1: "Compressor Hall",
    2: "Reactor Area",
    3: "Pipe Rack",
    4: "Control Room",
    5: "Loading Bay",
    6: "Utilities",
    7: "Flare Stack"
};
const ZONE_CHARS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'];

export class AlertFeedManager {
    constructor(containerEl, countEl) {
        this.container = containerEl;
        this.countEl = countEl;
        this.alerts = [];
    }

    addAlert(data) {
        // Deduplicate
        if (this.alerts.some(a => a.alert_id === data.alert_id)) return;

        this.alerts.unshift(data);
        this.countEl.textContent = String(this.alerts.length);

        // Remove empty state
        const empty = this.container.querySelector('.empty-state');
        if (empty) this.container.innerHTML = '';

        const isCritical = data.risk_score >= 70;
        const severityClass = isCritical ? 'severity-critical' : 'severity-warning';
        const severityLabel = isCritical ? 'CRITICAL' : 'WARNING';
        const severityTextClass = isCritical ? 'critical' : 'warning';
        const blinkClass = isCritical ? 'blink-critical' : '';

        // Build citations HTML
        let citationsHtml = '';
        if (data.regulatory_citations && data.regulatory_citations.length) {
            const entries = data.regulatory_citations.map(c => `
                <div class="citation-entry">
                    <div class="citation-header">
                        <span>${c.source} — ${c.section}</span>
                        <span class="citation-sim">sim ${c.similarity_score.toFixed(3)}</span>
                    </div>
                    <div class="citation-text">${c.relevance}</div>
                </div>
            `).join('');

            citationsHtml = `
                <div class="alert-section">
                    <div class="alert-section-label">Regulatory basis</div>
                    ${entries}
                </div>
            `;
        } else {
            citationsHtml = `
                <div class="alert-section">
                    <div class="alert-section-label">Regulatory basis</div>
                    <p style="color:var(--text-3); font-style:italic">No matching regulatory citations for this condition.</p>
                </div>
            `;
        }

        // Build abstention HTML
        let abstentionHtml = '';
        if (data.abstention_notes && data.abstention_notes.length) {
            abstentionHtml = `
                <div class="alert-section">
                    <div class="abstention-block">
                        <strong>RAG abstention flags</strong>
                        <ul>${data.abstention_notes.map(n => `<li>${n}</li>`).join('')}</ul>
                    </div>
                </div>
            `;
        }

        // Build actions HTML
        let actionsHtml = '';
        if (data.actions && data.actions.length) {
            actionsHtml = `
                <div class="alert-section">
                    <div class="alert-section-label">Recommended actions</div>
                    <ol>${data.actions.map(a => `<li>${a}</li>`).join('')}</ol>
                </div>
            `;
        }

        // Build mitigation HTML
        let mitigationHtml = '';
        if (data.is_drift_alert) {
            mitigationHtml = `
                <div class="alert-mitigation">
                    <div class="alert-section-label">Mitigation controls</div>
                    <button class="btn-mitigate btn-recalibrate" data-sensor-id="${data.sensor_id}">Recalibrate Sensor SEN-${data.sensor_id}</button>
                </div>
            `;
        } else if (data.is_cctv_alert) {
            mitigationHtml = `
                <div class="alert-mitigation">
                    <div class="alert-section-label">Mitigation controls</div>
                    <button class="btn-mitigate btn-ack-cctv" data-zone-id="${data.zone_id}" data-sensor-id="${data.sensor_id}">Acknowledge & Clear Violation</button>
                </div>
            `;
        } else if (data.zone_id !== undefined) {
            const zoneChar = ZONE_CHARS[data.zone_id] || String(data.zone_id);
            const zoneName = ZONE_NAMES[data.zone_id] || `Zone ${zoneChar}`;
            
            let permitButtons = '';
            if (data.active_permits && data.active_permits.length) {
                permitButtons = data.active_permits.map(pId => `
                    <button class="btn-mitigate btn-cancel-permit" data-permit-id="${pId}">Cancel Permit ${pId}</button>
                `).join('');
            }
            
            mitigationHtml = `
                <div class="alert-mitigation">
                    <div class="alert-section-label">Mitigation controls</div>
                    ${permitButtons}
                    <button class="btn-mitigate btn-isolate-feed" data-zone-id="${data.zone_id}">Isolate ${zoneName} Feed</button>
                </div>
            `;
        }

        const entry = document.createElement('div');
        entry.className = `alert-entry ${severityClass} ${blinkClass} data-enter`;
        entry.id = `alert-${data.alert_id}`;

        entry.innerHTML = `
            <div class="alert-header">
                <span class="alert-severity ${severityTextClass}">${severityLabel}</span>
                <span class="alert-meta">${data.alert_id}</span>
            </div>
            <div class="alert-title">Zone ${ZONE_CHARS[data.zone_id] || data.zone_id} Incident Risk</div>
            <div class="alert-risk-line">
                ${formatTimestamp(data.timestamp)} &mdash;
                Risk <span class="risk-val ${severityTextClass}">${data.risk_score.toFixed(1)}%</span>
            </div>

            <div class="alert-section">
                <div class="alert-section-label">Situation</div>
                <p>${data.situation}</p>
            </div>

            ${actionsHtml}
            ${citationsHtml}
            ${abstentionHtml}
            ${mitigationHtml}
        `;

        this.container.insertBefore(entry, this.container.firstChild);
    }

    clear() {
        this.alerts = [];
        this.countEl.textContent = '0';
        this.container.innerHTML = `
            <div class="empty-state" id="alert-empty">
                <span class="empty-label">Nominal</span>
                <span class="empty-desc">No actionable conditions detected</span>
            </div>
        `;
    }
}
