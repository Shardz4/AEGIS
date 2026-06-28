/**
 * Plant Map Renderer — Monochrome schematic style
 *
 * Draws on a Canvas 2D context using only grayscale + muted red for hazard states.
 * Looks like a real SCADA engineering schematic, not a consumer UI.
 */
import { getRiskColor, getSeverity } from './utils.js';
import { PlumeDrawer } from './plume.js';

export class PlantMapManager {
    constructor(canvasEl) {
        this.canvas = canvasEl;
        this.ctx = canvasEl.getContext('2d');
        this.plumeDrawer = new PlumeDrawer();

        this.virtualW = 900;
        this.virtualH = 600;

        // State
        this.zoneRisks = {};
        this.windAngle = 225;
        this.windSpeed = 3.2;
        this.activePlume = null;
        this.operators = [];
        this.evacPaths = {};
        this.blockedZones = [];

        // CCTV cameras coordinates
        this.cameras = [
            { id: 'CAM-A-101', zone_id: 0, x: 250, y: 50 },
            { id: 'CAM-B-201', zone_id: 1, x: 550, y: 50 },
            { id: 'CAM-C-301', zone_id: 2, x: 840, y: 50 },
            { id: 'CAM-D-401', zone_id: 3, x: 250, y: 235 },
            { id: 'CAM-E-501', zone_id: 4, x: 550, y: 235 },
            { id: 'CAM-F-601', zone_id: 5, x: 840, y: 235 },
            { id: 'CAM-G-701', zone_id: 6, x: 250, y: 420 },
            { id: 'CAM-H-801', zone_id: 7, x: 840, y: 420 }
        ];
        this.cameraWarnings = new Set();

        // Zone geometry
        this.zones = {
            0: { label: 'A  TANK FARM',       x:  30, y:  30, w: 250, h: 160, ps: { x: 155, y: 110 } },
            1: { label: 'B  COMPRESSOR HALL',  x: 310, y:  30, w: 270, h: 160, ps: { x: 445, y: 110 } },
            2: { label: 'C  REACTOR AREA',     x: 610, y:  30, w: 260, h: 160, ps: { x: 740, y: 110 } },
            3: { label: 'D  PIPE RACK',        x:  30, y: 215, w: 250, h: 160, ps: { x: 155, y: 295 } },
            4: { label: 'E  CONTROL ROOM',     x: 310, y: 215, w: 270, h: 160, ps: { x: 445, y: 295 } },
            5: { label: 'F  LOADING BAY',      x: 610, y: 215, w: 260, h: 160, ps: { x: 740, y: 295 } },
            6: { label: 'G  UTILITIES',        x:  30, y: 400, w: 250, h: 165, ps: { x: 155, y: 480 } },
            7: { label: 'H  FLARE STACK',      x: 610, y: 400, w: 260, h: 165, ps: { x: 740, y: 480 } },
        };

        // Equipment markers
        this.equipment = [
            { id: 'T-101', x:  85, y:  90 },
            { id: 'T-102', x: 215, y:  90 },
            { id: 'C-201', x: 390, y:  90 },
            { id: 'C-202', x: 500, y:  90 },
            { id: 'R-301', x: 690, y:  95 },
            { id: 'R-302', x: 790, y:  95 },
            { id: 'M-401', x: 150, y: 280 },
            { id: 'C-501', x: 445, y: 285 },
            { id: 'P-601', x: 740, y: 280 },
            { id: 'B-701', x: 150, y: 470 },
            { id: 'F-801', x: 740, y: 470 },
        ];

        this.resize();
        window.addEventListener('resize', () => this.resize());
    }

    resize() {
        const rect = this.canvas.parentElement.getBoundingClientRect();
        let w = rect.width;
        let h = w * (this.virtualH / this.virtualW);
        if (h > rect.height) {
            h = rect.height;
            w = h * (this.virtualW / this.virtualH);
        }
        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = w * dpr;
        this.canvas.height = h * dpr;
        this.canvas.style.width = `${w}px`;
        this.canvas.style.height = `${h}px`;
        this.ctx.scale(dpr, dpr);
        this.scale = w / this.virtualW;
    }

    setZoneRisk(id, score) { this.zoneRisks[id] = score; }
    setEvacPath(startZoneId, path) {
        if (path) {
            this.evacPaths[startZoneId] = path;
        } else {
            delete this.evacPaths[startZoneId];
        }
    }
    setBlockedZones(list) {
        this.blockedZones = list || [];
    }
    setWind(a, s) { this.windAngle = a; this.windSpeed = s; }

    setPlume(zoneId, radius) {
        if (radius > 0) {
            this.activePlume = { zoneId, radius };
            this.plumeDrawer.setTargetRadius(radius);
        } else {
            this.activePlume = null;
            this.plumeDrawer.setTargetRadius(0);
        }
    }

    setOperators(list) { this.operators = list; }

    update(dt) { this.plumeDrawer.update(dt); }

    draw() {
        const ctx = this.ctx;
        ctx.save();
        ctx.scale(this.scale, this.scale);
        ctx.clearRect(0, 0, this.virtualW, this.virtualH);

        // 1. Background grid — very subtle
        ctx.strokeStyle = '#161616';
        ctx.lineWidth = 0.5;
        for (let x = 50; x < this.virtualW; x += 50) {
            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, this.virtualH); ctx.stroke();
        }
        for (let y = 50; y < this.virtualH; y += 50) {
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(this.virtualW, y); ctx.stroke();
        }

        // 2. Zones
        for (const [id, z] of Object.entries(this.zones)) {
            const risk = this.zoneRisks[parseInt(id)] || 0;
            const sev = getSeverity(risk);

            // Fill — very low opacity tint
            if (sev === 'critical') {
                ctx.fillStyle = 'rgba(160, 50, 50, 0.06)';
            } else if (sev === 'warning') {
                ctx.fillStyle = 'rgba(140, 110, 40, 0.04)';
            } else {
                ctx.fillStyle = 'rgba(255, 255, 255, 0.015)';
            }
            ctx.fillRect(z.x, z.y, z.w, z.h);

            // Border
            ctx.strokeStyle = sev === 'critical' ? '#4a2020' : '#222222';
            ctx.lineWidth = sev === 'critical' ? 1.5 : 0.8;
            ctx.strokeRect(z.x, z.y, z.w, z.h);

            // Label
            ctx.fillStyle = sev === 'critical' ? '#884444' : '#444444';
            ctx.font = '500 9px "JetBrains Mono", monospace';
            ctx.fillText(z.label, z.x + 8, z.y + 16);

            // Risk score
            const scoreColor = sev === 'critical' ? '#aa3333' :
                               sev === 'warning'  ? '#886830' : '#444444';
            ctx.fillStyle = scoreColor;
            ctx.font = '600 11px "JetBrains Mono", monospace';
            const scoreText = `${risk.toFixed(1)}%`;
            const scoreW = ctx.measureText(scoreText).width;
            ctx.fillText(scoreText, z.x + z.w - scoreW - 8, z.y + 18);
        }

        // 3. Plume
        if (this.activePlume) {
            const z = this.zones[this.activePlume.zoneId];
            if (z) this.plumeDrawer.draw(ctx, z.ps.x, z.ps.y, 3.5);
        }

        // 4. Equipment markers — small crosses
        this.equipment.forEach(eq => {
            const s = 5;
            ctx.strokeStyle = '#333333';
            ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(eq.x - s, eq.y); ctx.lineTo(eq.x + s, eq.y); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(eq.x, eq.y - s); ctx.lineTo(eq.x, eq.y + s); ctx.stroke();

            ctx.fillStyle = '#333333';
            ctx.font = '400 7px "JetBrains Mono", monospace';
            ctx.fillText(eq.id, eq.x - 10, eq.y - 8);
        });

        // 5. Wind indicator — simple arrow
        this._drawWind(ctx, 830, 530);

        // 6. Operators — small markers
        this.operators.forEach(op => {
            const z = this.zones[op.current_zone];
            if (!z) return;
            const h = hash(op.operator_id);
            const rx = z.x + 25 + (h % (z.w - 50));
            const ry = z.y + 40 + ((h >> 4) % (z.h - 70));

            // Small square marker
            ctx.fillStyle = '#505050';
            ctx.fillRect(rx - 2, ry - 2, 4, 4);

            // Name label
            ctx.fillStyle = '#505050';
            ctx.font = '400 7px "JetBrains Mono", monospace';
            ctx.fillText(op.name, rx + 5, ry + 2);
        });

        // 7. Slashed/Blocked Zones (Ø Overlay)
        ctx.save();
        this.blockedZones.forEach(zId => {
            const z = this.zones[zId];
            if (!z) return;
            
            ctx.strokeStyle = 'rgba(160, 50, 50, 0.4)'; // Muted red-gray block
            ctx.lineWidth = 1.0;
            
            // Diagonal cross lines over the zone boundaries
            ctx.beginPath();
            ctx.moveTo(z.x, z.y);
            ctx.lineTo(z.x + z.w, z.y + z.h);
            ctx.stroke();
            
            ctx.beginPath();
            ctx.moveTo(z.x, z.y + z.h);
            ctx.lineTo(z.x + z.w, z.y);
            ctx.stroke();

            // Blocked Ø symbol in the center
            ctx.strokeStyle = '#884444';
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.arc(z.ps.x, z.ps.y, 16, 0, Math.PI * 2);
            ctx.stroke();
            
            ctx.beginPath();
            ctx.moveTo(z.ps.x - 12, z.ps.y + 12);
            ctx.lineTo(z.ps.x + 12, z.ps.y - 12);
            ctx.stroke();
        });
        ctx.restore();

        // 8. Evacuation Paths
        ctx.save();
        for (const [startId, path] of Object.entries(this.evacPaths)) {
            if (!path || path.length < 2) continue;
            
            ctx.strokeStyle = '#ffffff'; // High-contrast white for evac path
            ctx.lineWidth = 2.0;
            ctx.lineJoin = 'round';
            ctx.lineCap = 'round';
            
            const dashLen = 6;
            const gapLen = 4;
            ctx.setLineDash([dashLen, gapLen]);
            
            // Animate scroll direction
            const speed = 25; // px/sec
            const offset = (Date.now() / 1000 * speed) % (dashLen + gapLen);
            ctx.lineDashOffset = -offset;
            
            ctx.beginPath();
            const startZone = this.zones[path[0]];
            if (startZone) {
                ctx.moveTo(startZone.ps.x, startZone.ps.y);
            }
            for (let i = 1; i < path.length; i++) {
                const nextZone = this.zones[path[i]];
                if (nextZone) {
                    ctx.lineTo(nextZone.ps.x, nextZone.ps.y);
                }
            }
            ctx.stroke();
            
            // Draw directional arrows
            ctx.setLineDash([]);
            for (let i = 0; i < path.length - 1; i++) {
                const z1 = this.zones[path[i]];
                const z2 = this.zones[path[i+1]];
                if (!z1 || !z2) continue;
                
                const midX = (z1.ps.x + z2.ps.x) / 2;
                const midY = (z1.ps.y + z2.ps.y) / 2;
                const angle = Math.atan2(z2.ps.y - z1.ps.y, z2.ps.x - z1.ps.x);
                
                ctx.save();
                ctx.translate(midX, midY);
                ctx.rotate(angle);
                
                ctx.strokeStyle = '#ffffff';
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.moveTo(-4, -3);
                ctx.lineTo(0, 0);
                ctx.lineTo(-4, 3);
                ctx.stroke();
                
                ctx.restore();
            }
        }
        ctx.restore();

        // 9. CCTV Cameras overlay
        this.cameras.forEach(cam => {
            const isWarning = this.cameraWarnings.has(cam.id);
            ctx.save();
            ctx.translate(cam.x, cam.y);
            
            // Camera body
            ctx.fillStyle = isWarning ? '#886830' : '#333333';
            ctx.fillRect(-6, -4, 12, 8);
            
            // Lens
            ctx.fillStyle = isWarning ? '#aa3333' : '#222222';
            ctx.fillRect(6, -2, 3, 4);
            
            // Bracket
            ctx.strokeStyle = isWarning ? '#886830' : '#333333';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(-4, 4);
            ctx.lineTo(-4, 8);
            ctx.lineTo(0, 8);
            ctx.stroke();
            
            // ID label
            ctx.fillStyle = isWarning ? '#886830' : '#333333';
            ctx.font = '400 6px "JetBrains Mono", monospace';
            ctx.fillText(cam.id, -15, -8);
            
            ctx.restore();
        });

        ctx.restore();
    }

    setCameraWarning(camId, active) {
        if (active) {
            this.cameraWarnings.add(camId);
        } else {
            this.cameraWarnings.delete(camId);
        }
    }

    _drawWind(ctx, x, y) {
        ctx.save();
        ctx.translate(x, y);

        // Compass circle
        ctx.beginPath();
        ctx.arc(0, 0, 18, 0, Math.PI * 2);
        ctx.strokeStyle = '#2a2a2a';
        ctx.lineWidth = 0.5;
        ctx.stroke();

        // N label
        ctx.fillStyle = '#444444';
        ctx.font = '500 7px "JetBrains Mono", monospace';
        ctx.fillText('N', -3, -21);

        // Arrow
        const rad = (this.windAngle * Math.PI) / 180;
        ctx.rotate(rad);
        ctx.beginPath();
        ctx.moveTo(0, -13);
        ctx.lineTo(4, -4);
        ctx.lineTo(1, -4);
        ctx.lineTo(1, 12);
        ctx.lineTo(-1, 12);
        ctx.lineTo(-1, -4);
        ctx.lineTo(-4, -4);
        ctx.closePath();
        ctx.fillStyle = '#555555';
        ctx.fill();

        ctx.restore();
    }
}

function hash(str) {
    let h = 0;
    for (let i = 0; i < str.length; i++) h = str.charCodeAt(i) + ((h << 5) - h);
    return Math.abs(h);
}
