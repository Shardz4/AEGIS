/**
 * Manages the top-down plant map rendering using Canvas 2D
 */
import { getRiskColor } from './utils.js';
import { PlumeDrawer } from './plume.js';

export class PlantMapManager {
    constructor(canvasEl) {
        this.canvas = canvasEl;
        this.ctx = canvasEl.getContext('2d');
        this.plumeDrawer = new PlumeDrawer();
        
        // Plant virtual coordinates size
        this.virtualWidth = 900;
        this.virtualHeight = 600;
        
        // State
        this.zoneRisks = {}; // zone_id -> score (0-100)
        this.sensors = {};   // sensor_id -> { zone_id, type, value, status }
        this.windAngle = 225; // default in degrees (blowing from SW to NE)
        this.windSpeed = 3.2; // m/s
        this.activePlume = null; // { zone_id, radius }
        this.operators = []; // list of operator profiles
        
        // Configure standard zone boundaries
        this.zones = {
            0: { name: "Zone A - Tank Farm", x: 30, y: 30, w: 250, h: 160, plumeSource: {x: 155, y: 110} },
            1: { name: "Zone B - Compressor Hall", x: 310, y: 30, w: 270, h: 160, plumeSource: {x: 445, y: 110} },
            2: { name: "Zone C - Reactor Area", x: 610, y: 30, w: 260, h: 160, plumeSource: {x: 740, y: 110} },
            3: { name: "Zone D - Pipe Rack", x: 30, y: 215, w: 250, h: 160, plumeSource: {x: 155, y: 295} },
            4: { name: "Zone E - Control Room", x: 310, y: 215, w: 270, h: 160, plumeSource: {x: 445, y: 295} },
            5: { name: "Zone F - Loading Bay", x: 610, y: 215, w: 260, h: 160, plumeSource: {x: 740, y: 295} },
            6: { name: "Zone G - Utilities", x: 30, y: 400, w: 250, h: 165, plumeSource: {x: 155, y: 480} },
            7: { name: "Zone H - Flare Stack", x: 610, y: 400, w: 260, h: 165, plumeSource: {x: 740, y: 480} }
        };

        // Static equipment list
        this.equipment = [
            { id: "T-101", type: "Tank", zone: 0, x: 85, y: 90 },
            { id: "T-102", type: "Tank", zone: 0, x: 215, y: 90 },
            { id: "C-201", type: "Compressor", zone: 1, x: 390, y: 90 },
            { id: "C-202", type: "Compressor", zone: 1, x: 500, y: 90 },
            { id: "R-301", type: "Reactor", zone: 2, x: 690, y: 95 },
            { id: "R-302", type: "Reactor", zone: 2, x: 790, y: 95 },
            { id: "M-401", type: "Pipe", zone: 3, x: 150, y: 280 },
            { id: "C-501", type: "Console", zone: 4, x: 445, y: 285 },
            { id: "P-601", type: "Pump", zone: 5, x: 740, y: 280 },
            { id: "B-701", type: "Reactor", zone: 6, x: 150, y: 470 }, // Utilities boiler
            { id: "F-801", type: "Flare", zone: 7, x: 740, y: 470 }   // Flare stack
        ];

        // Resize handler setup
        this.resize();
        window.addEventListener('resize', () => this.resize());
    }

    resize() {
        const rect = this.canvas.parentElement.getBoundingClientRect();
        
        // Keep 3:2 aspect ratio
        let w = rect.width;
        let h = rect.width * (this.virtualHeight / this.virtualWidth);
        
        if (h > rect.height) {
            h = rect.height;
            w = rect.height * (this.virtualWidth / this.virtualHeight);
        }
        
        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = w * dpr;
        this.canvas.height = h * dpr;
        this.canvas.style.width = `${w}px`;
        this.canvas.style.height = `${h}px`;
        
        this.ctx.scale(dpr, dpr);
        this.currentScale = w / this.virtualWidth;
    }

    setZoneRisk(zoneId, score) {
        this.zoneRisks[zoneId] = score;
    }

    setWind(angle, speed) {
        this.windAngle = angle;
        this.windSpeed = speed;
    }

    setPlume(zoneId, radiusMeters) {
        if (radiusMeters > 0) {
            this.activePlume = { zoneId, radius: radiusMeters };
            this.plumeDrawer.setTargetRadius(radiusMeters);
        } else {
            this.activePlume = null;
            this.plumeDrawer.setTargetRadius(0);
        }
    }

    setOperators(operatorsList) {
        this.operators = operatorsList;
    }

    update(dt) {
        this.plumeDrawer.update(dt);
    }

    draw() {
        const ctx = this.ctx;
        ctx.save();
        ctx.scale(this.currentScale, this.currentScale);
        
        // Clear canvas
        ctx.clearRect(0, 0, this.virtualWidth, this.virtualHeight);
        
        // 1. Draw Grid lines (fine background grid)
        ctx.strokeStyle = 'rgba(42, 59, 90, 0.15)';
        ctx.lineWidth = 1;
        for (let x = 50; x < this.virtualWidth; x += 50) {
            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x, this.virtualHeight);
            ctx.stroke();
        }
        for (let y = 50; y < this.virtualHeight; y += 50) {
            ctx.beginPath();
            ctx.moveTo(0, y);
            ctx.lineTo(this.virtualWidth, y);
            ctx.stroke();
        }

        // 2. Draw Zones (rectangles with color gradient matching risk)
        for (const [id, zone] of Object.entries(this.zones)) {
            const zoneId = parseInt(id);
            const risk = this.zoneRisks[zoneId] || 0.0;
            const zoneColor = getRiskColor(risk);
            
            // Draw background fill with low opacity
            ctx.fillStyle = zoneColor.replace('rgb', 'rgba').replace(')', ', 0.08)');
            ctx.fillRect(zone.x, zone.y, zone.w, zone.h);
            
            // Draw border
            ctx.strokeStyle = risk > 70.0 ? 'rgba(255, 58, 58, 0.4)' : 'rgba(42, 59, 90, 0.6)';
            ctx.lineWidth = risk > 70.0 ? 2 : 1.5;
            ctx.strokeRect(zone.x, zone.y, zone.w, zone.h);
            
            // Draw label
            ctx.fillStyle = risk > 70.0 ? '#ff3a3a' : 'rgba(232, 234, 237, 0.7)';
            ctx.font = `600 10.5px "Inter", sans-serif`;
            ctx.fillText(zone.name.toUpperCase(), zone.x + 10, zone.y + 20);
            
            // Draw risk score badge
            ctx.fillStyle = zoneColor;
            ctx.font = `700 12px "JetBrains Mono", monospace`;
            ctx.fillText(`${risk.toFixed(1)}%`, zone.x + zone.w - 55, zone.y + 22);
        }

        // 3. Draw Consequence Plume (RAG visualizer)
        // 1 meter = 3.5 pixels virtual coordinate scale
        const scalePixelsPerMeter = 3.5;
        if (this.activePlume) {
            const z = this.zones[this.activePlume.zoneId];
            if (z) {
                this.plumeDrawer.draw(ctx, z.plumeSource.x, z.plumeSource.y, scalePixelsPerMeter);
            }
        }

        // 4. Draw Static Equipment icons/circles
        this.equipment.forEach(eq => {
            ctx.beginPath();
            ctx.arc(eq.x, eq.y, 8, 0, Math.PI * 2);
            ctx.fillStyle = '#1e2a3a';
            ctx.strokeStyle = '#8b95a5';
            ctx.lineWidth = 1.5;
            ctx.fill();
            ctx.stroke();
            
            // Label
            ctx.fillStyle = '#8b95a5';
            ctx.font = `500 8.5px "JetBrains Mono", monospace`;
            ctx.fillText(eq.id, eq.x - 12, eq.y - 12);
        });

        // 5. Draw Wind Direction Arrow
        this._drawWindIndicator(ctx, 830, 520);

        // 6. Draw Workers / Operators inside zones
        this.operators.forEach(op => {
            const zone = this.zones[op.current_zone];
            if (zone) {
                // Determine a position inside the zone based on operator hash
                const h = hashString(op.operator_id);
                // Keep offset well within the zone card bounds
                const offsetX = 30 + (h % (zone.w - 60));
                const offsetY = 50 + ((h >> 4) % (zone.h - 90));
                const rx = zone.x + offsetX;
                const ry = zone.y + offsetY;
                
                // Draw operator pin
                this._drawWorkerPin(ctx, rx, ry, op.name, op.role);
            }
        });

        ctx.restore();
    }

    _drawWindIndicator(ctx, x, y) {
        ctx.save();
        ctx.translate(x, y);

        // Draw outer compass ring
        ctx.beginPath();
        ctx.arc(0, 0, 24, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(139, 149, 165, 0.4)';
        ctx.lineWidth = 1;
        ctx.stroke();

        ctx.fillStyle = 'rgba(139, 149, 165, 0.7)';
        ctx.font = `600 8px "Inter", sans-serif`;
        ctx.fillText('N', -3, -27);

        // Rotate arrow to wind angle (wind blows towards)
        // Convert to radians
        const angleRad = (this.windAngle * Math.PI) / 180.0;
        ctx.rotate(angleRad);

        // Draw arrow pointing downwind
        ctx.beginPath();
        ctx.moveTo(0, -18);
        ctx.lineTo(6, -6);
        ctx.lineTo(2, -6);
        ctx.lineTo(2, 16);
        ctx.lineTo(-2, 16);
        ctx.lineTo(-2, -6);
        ctx.lineTo(-6, -6);
        ctx.closePath();
        ctx.fillStyle = '#00d4ff';
        ctx.fill();

        ctx.restore();
    }

    _drawWorkerPin(ctx, x, y, name, role) {
        ctx.save();
        
        // Pin body
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.fillStyle = '#00e676'; // safe green
        ctx.strokeStyle = '#0a0e17';
        ctx.lineWidth = 1.0;
        ctx.fill();
        ctx.stroke();

        // Worker tooltip (name/role)
        ctx.fillStyle = 'rgba(20, 27, 45, 0.85)';
        const textWidth = ctx.measureText(name).width;
        ctx.fillRect(x - textWidth/2 - 4, y + 6, textWidth + 8, 12);
        ctx.strokeStyle = 'rgba(42, 59, 90, 0.5)';
        ctx.lineWidth = 0.5;
        ctx.strokeRect(x - textWidth/2 - 4, y + 6, textWidth + 8, 12);

        ctx.fillStyle = '#e8eaed';
        ctx.font = `600 7.5px "Inter", sans-serif`;
        ctx.fillText(name, x - textWidth/2, y + 14);

        ctx.restore();
    }
}

// Simple hash helper to distribute operators inside zones stably
function hashString(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        hash = str.charCodeAt(i) + ((hash << 5) - hash);
    }
    return Math.abs(hash);
}
