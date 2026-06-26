/**
 * Sparkline Trend Charts — Monochrome functional style
 */
import { formatTTI } from './utils.js';

export class SparklineManager {
    constructor() {
        this.sensorHistory = {};
        this.sensorMeta = {};
    }

    updateSensor(signalId, value, metadata) {
        if (!this.sensorHistory[signalId]) {
            this.sensorHistory[signalId] = [];
        }
        const hist = this.sensorHistory[signalId];
        hist.push(value);
        if (hist.length > 60) hist.shift();

        this.sensorMeta[signalId] = {
            label: metadata.label || `SEN-${signalId}`,
            unit: metadata.unit || '',
            threshold: metadata.threshold || 100,
            zone_id: metadata.zone_id,
            tti_seconds: metadata.tti_seconds,
            urgency: metadata.urgency || 'normal',
            malfunctioning: metadata.malfunctioning || false
        };
    }

    render(container) {
        const sensors = Object.keys(this.sensorMeta).map(id => ({
            id: parseInt(id),
            ...this.sensorMeta[id],
            history: this.sensorHistory[id]
        }));

        const urgOrder = { 'critical': 3, 'warning': 2, 'watch': 1, 'normal': 0 };
        sensors.sort((a, b) => {
            const d = (urgOrder[b.urgency] || 0) - (urgOrder[a.urgency] || 0);
            if (d !== 0) return d;
            return (a.tti_seconds || 99999) - (b.tti_seconds || 99999);
        });

        const top = sensors.slice(0, 5);
        if (!top.length) {
            container.innerHTML = '<div class="empty-state" style="height:auto;padding:0"><span class="empty-desc">No active trends</span></div>';
            return;
        }

        container.innerHTML = '';
        top.forEach(s => {
            const el = document.createElement('div');
            let stateClass = s.urgency === 'critical' ? 'state-critical' :
                             s.urgency === 'warning' ? 'state-warning' : '';
            if (s.malfunctioning) {
                stateClass = 'state-malfunctioning';
            }
            el.className = `sparkline-widget ${stateClass} data-enter`;

            let val = `${s.history[s.history.length - 1].toFixed(1)}${s.unit}`;
            let tti = s.tti_seconds !== null && s.tti_seconds < 1800
                ? `TTI ${formatTTI(s.tti_seconds)}`
                : 'TTI ---';

            if (s.malfunctioning) {
                val = '[FAULT]';
                tti = 'FAULTY SENSOR';
            }

            el.innerHTML = `
                <div class="sparkline-info">
                    <span class="sparkline-label">${s.label}</span>
                    <span class="sparkline-value">${val}</span>
                    <span class="sparkline-tti">${tti}</span>
                </div>
                <div class="sparkline-chart-box">
                    <canvas class="sparkline-canvas" id="spark-${s.id}"></canvas>
                </div>
            `;
            container.appendChild(el);

            setTimeout(() => {
                const c = document.getElementById(`spark-${s.id}`);
                if (c) this._drawSpark(c, s.history, s.threshold, s.urgency, s.malfunctioning);
            }, 0);
        });
    }

    _drawSpark(canvas, history, threshold, urgency, malfunctioning) {
        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        const w = rect.width, h = rect.height;
        ctx.clearRect(0, 0, w, h);

        if (history.length < 2) return;

        const minV = Math.min(...history) * 0.9;
        const maxV = Math.max(threshold, ...history) * 1.1;
        const range = maxV - minV || 1;
        const gx = i => (i / (history.length - 1)) * w;
        const gy = v => h - ((v - minV) / range) * h;

        // Threshold line
        ctx.beginPath();
        ctx.moveTo(0, gy(threshold));
        ctx.lineTo(w, gy(threshold));
        ctx.strokeStyle = 'rgba(160, 50, 50, 0.25)';
        ctx.lineWidth = 0.5;
        ctx.setLineDash([2, 2]);
        ctx.stroke();
        ctx.setLineDash([]);

        // Data line
        ctx.beginPath();
        ctx.moveTo(gx(0), gy(history[0]));
        for (let i = 1; i < history.length; i++) {
            ctx.lineTo(gx(i), gy(history[i]));
        }

        if (malfunctioning) {
            ctx.strokeStyle = '#888888';
            ctx.lineWidth = 0.5;
            ctx.setLineDash([2, 2]);
        } else {
            const color = urgency === 'critical' ? '#884444' :
                          urgency === 'warning'  ? '#886830' : '#555555';
            ctx.strokeStyle = color;
            ctx.lineWidth = 1;
            ctx.setLineDash([]);
        }
        ctx.stroke();
        ctx.setLineDash([]); // clear dash for subsequent drawings

        // Area fill
        if (!malfunctioning) {
            ctx.lineTo(w, h);
            ctx.lineTo(0, h);
            ctx.closePath();
            const fill = urgency === 'critical' ? 'rgba(160, 50, 50, 0.06)' :
                         urgency === 'warning'  ? 'rgba(140, 110, 40, 0.04)' :
                                                  'rgba(100, 100, 100, 0.03)';
            ctx.fillStyle = fill;
            ctx.fill();
        }
    }
}
