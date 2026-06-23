/**
 * Renders safety alerts to the Recommendations side panel feed
 */
import { formatTimestamp } from './utils.js';

export class AlertFeedManager {
    constructor(containerEl, badgeEl) {
        this.containerEl = containerEl;
        this.badgeEl = badgeEl;
        this.alerts = []; // List of received alerts
    }

    /**
     * Appends a new operator alert card to the feed
     */
    addAlert(alertData) {
        // Prevent duplicate alert IDs (e.g. if websocket retransmits)
        if (this.alerts.some(a => a.alert_id === alertData.alert_id)) {
            return;
        }

        this.alerts.unshift(alertData); // Latest alert first

        // Update badge count
        this.badgeEl.textContent = `${this.alerts.length} Alert${this.alerts.length !== 1 ? 's' : ''}`;
        
        // Remove no-alerts placeholder if it is present
        const placeholder = this.containerEl.querySelector('.no-alerts-placeholder');
        if (placeholder) {
            this.containerEl.innerHTML = '';
        }

        // Render card
        const card = document.createElement('div');
        const isCritical = alertData.risk_score >= 70.0;
        card.className = `alert-card ${isCritical ? 'critical' : 'warning'}`;
        card.id = `alert-${alertData.alert_id}`;

        // Format citations
        let citationsHtml = '';
        if (alertData.regulatory_citations && alertData.regulatory_citations.length > 0) {
            citationsHtml = `
                <div class="alert-section">
                    <h4>Regulatory Compliance Citations</h4>
                    <div class="citation-list">
                        ${alertData.regulatory_citations.map(c => `
                            <div class="citation-badge">
                                <div class="citation-badge-header">
                                    <span>📋 ${c.source} — ${c.section}</span>
                                    <span class="font-mono">sim: ${c.similarity_score.toFixed(3)}</span>
                                </div>
                                <div class="citation-badge-relevance">
                                    "${c.relevance}"
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        } else {
            citationsHtml = `
                <div class="alert-section">
                    <h4>Regulatory Compliance Basis</h4>
                    <p class="text-secondary italic">No specific regulatory citations available for this condition.</p>
                </div>
            `;
        }

        // Format abstentions
        let abstentionsHtml = '';
        if (alertData.abstention_notes && alertData.abstention_notes.length > 0) {
            abstentionsHtml = `
                <div class="alert-section">
                    <div class="abstention-banner">
                        <strong>⚠️ RAG Safety Warnings:</strong>
                        <ul>
                            ${alertData.abstention_notes.map(note => `<li>${note}</li>`).join('')}
                        </ul>
                    </div>
                </div>
            `;
        }

        // Format actions
        const actionsHtml = alertData.actions && alertData.actions.length > 0
            ? `
                <div class="alert-section">
                    <h4>Prioritized Actions</h4>
                    <ul>
                        ${alertData.actions.map(act => `<li>${act}</li>`).join('')}
                    </ul>
                </div>
            `
            : '';

        // Risk and TTI
        const footerInfo = `
            <div class="alert-card-footer">
                <span>Risk Score: <strong class="${isCritical ? 'text-danger' : 'text-warning'} font-mono">${alertData.risk_score.toFixed(1)}%</strong></span>
                <span>ID: <span class="font-mono">${alertData.alert_id}</span></span>
            </div>
        `;

        card.innerHTML = `
            <div class="alert-card-header">
                <div class="title-area">
                    <span class="badge ${isCritical ? 'badge-critical' : 'badge-warning'}">
                        ${isCritical ? '🔴 CRITICAL ALERT' : '⚠️ WARNING'}
                    </span>
                    <h3 class="text-primary" style="margin-top: 6px;">Zone ${alertData.zone_id} Incident Risk</h3>
                    <span class="timestamp font-mono">${formatTimestamp(alertData.timestamp)}</span>
                </div>
            </div>
            
            <div class="alert-section">
                <h4>Situation Summary</h4>
                <p class="text-primary">${alertData.situation}</p>
            </div>
            
            ${actionsHtml}
            ${citationsHtml}
            ${abstentionsHtml}
            ${footerInfo}
        `;

        this.containerEl.insertBefore(card, this.containerEl.firstChild);
    }

    clear() {
        this.alerts = [];
        this.badgeEl.textContent = '0 Alerts';
        this.containerEl.innerHTML = `
            <div class="no-alerts-placeholder fade-in">
                <div class="placeholder-icon">✓</div>
                <p class="placeholder-title">Systems Operating Normally</p>
                <p class="placeholder-desc">No high-risk conditions detected. All zone scores nominal.</p>
            </div>
        `;
    }
}
