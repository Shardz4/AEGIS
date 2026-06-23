/**
 * Manages the top trending hazard sparklines and TTI progress bars
 */
import { formatTTI } from './utils.js';

export class SparklineManager {
    constructor() {
        this.sensorHistory = {}; // signal_id -> array of values (last 60 seconds)
        this.sensorMeta = {};    // signal_id -> { label, unit, threshold, zone_id, tti_seconds, urgency }
    }

    /**
     * Feed new sensor telemetry data to update history buffers
     */
    updateSensor(signalId, value, metadata) {
        if (!this.sensorHistory[signalId]) {
            this.sensorHistory[signalId] = [];
        }

        const history = this.sensorHistory[signalId];
        history.push(value);

        // Limit history to last 60 readings (approx 60s)
        if (history.length > 60) {
            history.shift();
        }

        // Store latest metadata
        this.sensorMeta[signalId] = {
            label: metadata.label || `Sensor ${signalId}`,
            unit: metadata.unit || '',
            threshold: metadata.threshold || 100.0,
            zone_id: metadata.zone_id,
            tti_seconds: metadata.tti_seconds,
            urgency: metadata.urgency || 'normal'
        };
    }

    /**
     * Renders sparklines and TTI count-downs to the bottom panel container
     */
    render(containerEl) {
        // Collect sensors that have active warnings/TTI or represent the highest values
        const activeSensors = Object.keys(this.sensorMeta).map(id => ({
            id: parseInt(id),
            ...this.sensorMeta[id],
            history: this.sensorHistory[id]
        }));

        // Sort: critical urgency first, then warning, then lowest TTI
        const urgencyOrder = { 'critical': 3, 'warning': 2, 'watch': 1, 'normal': 0 };
        activeSensors.sort((a, b) => {
            // Compare urgency first
            const urgDiff = urgencyOrder[b.urgency] - urgencyOrder[a.urgency];
            if (urgDiff !== 0) return urgDiff;
            
            // Compare TTI second (if present)
            const ttiA = a.tti_seconds !== null ? a.tti_seconds : 99999;
            const ttiB = b.tti_seconds !== null ? b.tti_seconds : 99999;
            return ttiA - ttiB;
        });

        // Limit to top 5 sensors to display
        const top5 = activeSensors.slice(0, 5);

        if (top5.length === 0) {
            containerEl.innerHTML = '<div class="loading-placeholder">No active sensor trends. Normal operation.</div>';
            return;
        }

        // Generate HTML
        containerEl.innerHTML = '';
        
        top5.forEach(sensor => {
            const card = document.createElement('div');
            card.className = `sparkline-card fade-in ${sensor.urgency === 'critical' ? 'danger' : sensor.urgency === 'warning' ? 'warning' : ''}`;
            
            const valueFormatted = `${sensor.history[sensor.history.length - 1].toFixed(1)}${sensor.unit}`;
            const ttiFormatted = sensor.tti_seconds !== null && sensor.tti_seconds < 1800 
                ? `TTI: ${formatTTI(sensor.tti_seconds)}` 
                : 'TTI: Stable';
                
            card.innerHTML = `
                <div class="sparkline-info">
                    <span class="sparkline-label" title="${sensor.label} (Z${sensor.zone_id})">${sensor.label}</span>
                    <span class="sparkline-value font-mono">${valueFormatted}</span>
                    <span class="sparkline-tti font-mono">${ttiFormatted}</span>
                </div>
                <div class="sparkline-chart-container">
                    <canvas class="sparkline-canvas" id="spark-${sensor.id}"></canvas>
                </div>
            `;
            
            containerEl.appendChild(card);
            
            // Draw sparkline canvas on next tick
            setTimeout(() => {
                const canvas = document.getElementById(`spark-${sensor.id}`);
                if (canvas) {
                    this._drawCanvasSpark(canvas, sensor.history, sensor.threshold, sensor.urgency);
                }
            }, 0);
        });
    }

    _drawCanvasSpark(canvas, history, threshold, urgency) {
        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.getBoundingClientRect();
        
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        
        const ctx = canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        
        const width = rect.width;
        const height = rect.height;
        
        ctx.clearRect(0, 0, width, height);

        if (history.length < 2) return;

        // Calculate scales
        // Pad min/max slightly
        const minVal = Math.min(...history) * 0.9;
        const maxVal = Math.max(threshold, ...history) * 1.1;
        const range = maxVal - minVal || 1.0;

        const getX = (idx) => (idx / (history.length - 1)) * width;
        const getY = (val) => height - ((val - minVal) / range) * height;

        // 1. Draw threshold line
        const thresholdY = getY(threshold);
        ctx.beginPath();
        ctx.moveTo(0, thresholdY);
        ctx.lineTo(width, thresholdY);
        ctx.strokeStyle = 'rgba(255, 58, 58, 0.4)';
        ctx.lineWidth = 1.0;
        ctx.setLineDash([2, 2]);
        ctx.stroke();
        ctx.setLineDash([]); // Reset

        // 2. Draw historical trend path
        ctx.beginPath();
        ctx.moveTo(getX(0), getY(history[0]));
        for (let i = 1; i < history.length; i++) {
            ctx.lineTo(getX(i), getY(history[i]));
        }

        // Color scale based on urgency
        let lineColor = '#00d4ff'; // Cyan default
        if (urgency === 'critical') {
            lineColor = '#ff3a3a'; // Red
        } else if (urgency === 'warning') {
            lineColor = '#ff9f1c'; // Amber
        }
        
        ctx.strokeStyle = lineColor;
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // 3. Draw gradient area fill below line
        ctx.lineTo(width, height);
        ctx.lineTo(0, height);
        ctx.closePath();
        
        const fillGradient = ctx.createLinearGradient(0, 0, 0, height);
        if (urgency === 'critical') {
            fillGradient.addColorStop(0, 'rgba(255, 58, 58, 0.15)');
            fillGradient.addColorStop(1, 'rgba(255, 58, 58, 0.0)');
        } else if (urgency === 'warning') {
            fillGradient.addColorStop(0, 'rgba(255, 159, 28, 0.12)');
            fillGradient.addColorStop(1, 'rgba(255, 159, 28, 0.0)');
        } else {
            fillGradient.addColorStop(0, 'rgba(0, 212, 255, 0.1)');
            fillGradient.addColorStop(1, 'rgba(0, 212, 255, 0.0)');
        }
        
        ctx.fillStyle = fillGradient;
        ctx.fill();
    }
}
