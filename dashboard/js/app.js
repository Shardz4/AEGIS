/**
 * AEGIS Application Coordinator
 * 
 * Manages WebSocket connection, zone table rendering, demo scenario,
 * and data flow between map/chart/alert managers.
 */
import { PlantMapManager } from './map.js';
import { SparklineManager } from './charts.js';
import { AlertFeedManager } from './alerts.js';
import { formatTimestamp, getSeverity, getSeverityCode } from './utils.js';

const ZONE_NAMES = [
    'Tank Farm', 'Compressor Hall', 'Reactor Area', 'Pipe Rack',
    'Control Room', 'Loading Bay', 'Utilities', 'Flare Stack'
];

const ZONE_IDS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'];

class AegisApp {
    constructor() {
        // Header elements
        this.connStatus = document.getElementById('conn-status');
        this.connText = document.getElementById('conn-text');
        this.clockEl = document.getElementById('current-clock');
        this.demoBtn = document.getElementById('demo-btn');
        this.leadTimeContainer = document.getElementById('lead-time-container');
        this.leadTimeVal = document.getElementById('lead-time-val');

        // Panel containers
        this.zoneContainer = document.getElementById('zone-table-container');
        this.sparklineContainer = document.getElementById('sparklines-container');
        this.alertContainer = document.getElementById('alert-feed-container');
        this.alertCount = document.getElementById('alert-count');

        // Plume overlay
        this.hazardOverlay = document.getElementById('hazard-overlay');
        this.plumeRadiusEl = document.getElementById('plume-radius');
        this.plumeRateEl = document.getElementById('plume-rate');
        this.plumeGasEl = document.getElementById('plume-gas');
        this.plumeSourceEl = document.getElementById('plume-source');

        // Wind display
        this.windDirEl = document.getElementById('wind-dir');
        this.windSpeedEl = document.getElementById('wind-speed');

        // Managers
        this.mapManager = new PlantMapManager(document.getElementById('map-canvas'));
        this.chartsManager = new SparklineManager();
        this.alertsManager = new AlertFeedManager(this.alertContainer, this.alertCount);

        // State
        this.ws = null;
        this.demoActive = false;
        this.demoTime = 0;
        this.demoTimer = null;
        this.lastFrame = performance.now();

        // Zone state cache (for table rendering)
        this.zoneState = {};
        for (let i = 0; i < 8; i++) {
            this.zoneState[i] = {
                risk_score: 8.5, risk_level: 'normal',
                active_permits: [], worker_count: 0, fatigue_level: 'normal'
            };
        }

        // Bind
        this.demoBtn.addEventListener('click', () => this.toggleDemo());

        // Init
        this.startClock();
        this.connectWebSocket();
        this.initLoop();
        this.renderZoneTable();
        this.mapManager.setWind(225, 3.2);
        this.updateWindDisplay(225, 3.2);

        // Set default risks
        for (let i = 0; i < 8; i++) this.mapManager.setZoneRisk(i, 8.5);

        // Default operators
        this.mapManager.setOperators([
            { operator_id: 'OP_002', name: 'Elena R.', role: 'Control Room', current_zone: 4 },
            { operator_id: 'OP_004', name: 'Marcus A.', role: 'Field Operator', current_zone: 3 },
            { operator_id: 'OP_005', name: 'Sarah C.', role: 'Control Room', current_zone: 4 }
        ]);
    }

    /* --- Clock --- */
    startClock() {
        const tick = () => {
            this.clockEl.textContent = formatTimestamp(Date.now() / 1000);
        };
        tick();
        setInterval(tick, 1000);
    }

    /* --- WebSocket --- */
    connectWebSocket() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${proto}//${location.host}/ws`;

        this.connText.textContent = 'CONNECTING';
        this.connStatus.className = 'header-status';

        this.ws = new WebSocket(url);

        this.ws.onopen = () => {
            log('WebSocket connected');
            this.connText.textContent = 'CONNECTED';
            this.connStatus.className = 'header-status connected';
        };

        this.ws.onmessage = (e) => {
            if (this.demoActive) return;
            try {
                this.handleUpdate(JSON.parse(e.data));
            } catch (err) {
                console.error('WS parse error:', err);
            }
        };

        this.ws.onclose = () => {
            log('WebSocket closed, reconnecting in 3s');
            this.connText.textContent = 'DISCONNECTED';
            this.connStatus.className = 'header-status disconnected';
            setTimeout(() => this.connectWebSocket(), 3000);
        };
    }

    /* --- Data dispatch --- */
    handleUpdate(msg) {
        switch (msg.type) {
            case 'zone_update':
                this.zoneState[msg.zone_id] = msg;
                this.mapManager.setZoneRisk(msg.zone_id, msg.risk_score);
                if (msg.evac_path !== undefined) {
                    this.mapManager.setEvacPath(msg.zone_id, msg.evac_path);
                }
                if (msg.blocked_zones !== undefined) {
                    this.mapManager.setBlockedZones(msg.blocked_zones);
                }
                this.renderZoneTable();
                break;

            case 'sensor_update': {
                const specs = {
                    5:  { label: 'Reactor Temp',   unit: '°C',    threshold: 85 },
                    6:  { label: 'Reactor Press',  unit: ' bar',  threshold: 8 },
                    10: { label: 'Vessel Level',   unit: ' m',    threshold: 12 },
                    15: { label: 'Gas Conc (LEL)', unit: '% LEL', threshold: 20 },
                };
                const spec = specs[msg.signal_id] || { label: `SEN-${msg.signal_id}`, unit: '', threshold: 100 };
                this.chartsManager.updateSensor(msg.signal_id, msg.value, {
                    ...spec, zone_id: msg.zone_id,
                    tti_seconds: msg.tti_seconds, urgency: msg.urgency
                });
                this.chartsManager.render(this.sparklineContainer);
                break;
            }

            case 'plume_update':
                this.mapManager.setPlume(msg.zone_id, msg.hazard_radius_m);
                this.updatePlumeOverlay(msg);
                break;

            case 'alert':
                this.alertsManager.addAlert(msg);
                break;

            case 'fatigue_update':
                break;

            case 'wind_update':
                this.mapManager.setWind(msg.wind_direction, msg.wind_speed);
                this.updateWindDisplay(msg.wind_direction, msg.wind_speed);
                break;

            case 'start_demo':
                if (!this.demoActive) this.startDemo();
                break;
        }
    }

    /* --- Zone Table Rendering (dense tabular rows) --- */
    renderZoneTable() {
        // Remove empty-state placeholder if present
        const empty = this.zoneContainer.querySelector('.empty-state');
        if (empty && Object.keys(this.zoneState).length > 0) {
            this.zoneContainer.innerHTML = '';
        }

        for (let i = 0; i < 8; i++) {
            const data = this.zoneState[i];
            if (!data) continue;

            const score = data.risk_score ?? 8.5;
            const sev = getSeverity(score);
            const sevCode = getSeverityCode(score);
            const permits = data.active_permits || [];
            const permitCode = permits.length > 0
                ? permits.map(p => {
                    if (p === 'HotWork') return 'HW';
                    if (p === 'ConfinedSpace') return 'CS';
                    if (p === 'LineBreak') return 'LB';
                    if (p === 'Lockout') return 'LO';
                    if (p === 'Excavation') return 'EX';
                    return p.substring(0, 2).toUpperCase();
                }).join(' ')
                : '--';
            const workers = data.worker_count ?? 0;
            const fatigue = data.fatigue_level || 'normal';

            let rowEl = document.getElementById(`zone-row-${i}`);
            if (!rowEl) {
                rowEl = document.createElement('div');
                rowEl.id = `zone-row-${i}`;
                this.zoneContainer.appendChild(rowEl);

                // Add detail row
                const detailEl = document.createElement('div');
                detailEl.id = `zone-detail-${i}`;
                detailEl.className = 'zone-detail';
                this.zoneContainer.appendChild(detailEl);
            }

            // Row severity class
            const sevClass = sev === 'critical' ? 'severity-critical' :
                             sev === 'warning'  ? 'severity-warning' : 'severity-nominal';
            const blinkClass = sev === 'critical' ? 'blink-critical' : '';
            rowEl.className = `zone-row ${sevClass} ${blinkClass}`;

            rowEl.innerHTML = `
                <div class="zone-name"><span class="zone-id">${ZONE_IDS[i]}</span>${ZONE_NAMES[i]}</div>
                <div class="zone-score ${sev}">${score.toFixed(1)}</div>
                <div class="zone-status ${sev}">${sevCode}</div>
                <div class="zone-workers">${workers}w</div>
                <div class="zone-permit ${permits.length > 0 ? 'active' : ''}">${permitCode}</div>
            `;

            // Detail row (fatigue + permits detail)
            const detailEl = document.getElementById(`zone-detail-${i}`);
            if (detailEl) {
                const fatigueClass = fatigue === 'high' ? 'high' : '';
                detailEl.innerHTML = `
                    <div class="detail-item">
                        <span class="detail-label">fatigue</span>
                        <span class="detail-val ${fatigueClass}">${fatigue.toUpperCase()}</span>
                    </div>
                `;
            }
        }
    }

    /* --- Plume overlay --- */
    updatePlumeOverlay(data) {
        if (data.hazard_radius_m > 0) {
            this.hazardOverlay.classList.remove('hidden');
            this.plumeSourceEl.textContent = `Zone ${ZONE_IDS[data.zone_id]} ${ZONE_NAMES[data.zone_id]}`;
            this.plumeRadiusEl.textContent = `${data.hazard_radius_m.toFixed(1)} m`;
            this.plumeGasEl.textContent = data.gas_name || 'Hydrocarbon';
            this.plumeRateEl.textContent = data.leak_rate_kgs ? `${data.leak_rate_kgs.toFixed(2)} kg/s` : '---';
        } else {
            this.hazardOverlay.classList.add('hidden');
        }
    }

    updateWindDisplay(angle, speed) {
        const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
        const idx = Math.round(((angle % 360) + 360) % 360 / 45) % 8;
        this.windDirEl.textContent = dirs[idx];
        this.windSpeedEl.textContent = speed.toFixed(1);
    }

    /* --- Render loop --- */
    initLoop() {
        const loop = (ts) => {
            const dt = (ts - this.lastFrame) / 1000;
            this.lastFrame = ts;
            this.mapManager.update(dt);
            this.mapManager.draw();
            requestAnimationFrame(loop);
        };
        requestAnimationFrame(loop);
    }

    /* ============================================================
       DEMO SCENARIO (180 seconds)
       ============================================================ */

    toggleDemo() {
        if (this.demoActive) {
            this.stopDemo();
        } else {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ type: 'start_demo' }));
            }
            this.startDemo();
        }
    }

    startDemo() {
        this.demoActive = true;
        this.demoTime = 0;
        this.demoBtn.textContent = 'STOP DEMO';
        this.demoBtn.className = 'btn-demo active';
        this.connText.textContent = 'DEMO MODE';
        this.connStatus.className = 'header-status disconnected';
        this.leadTimeContainer.classList.remove('hidden');
        this.leadTimeVal.textContent = '0m 00s';

        this.alertsManager.clear();
        this.sparklineContainer.innerHTML = '';
        this.chartsManager = new SparklineManager();

        log('Demo scenario starting');

        this.demoTimer = setInterval(() => this.tickDemo(), 1000);
        this.tickDemo();
    }

    stopDemo() {
        this.demoActive = false;
        clearInterval(this.demoTimer);
        this.demoBtn.textContent = 'RUN DEMO';
        this.demoBtn.className = 'btn-demo';
        this.leadTimeContainer.classList.add('hidden');

        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.connText.textContent = 'CONNECTED';
            this.connStatus.className = 'header-status connected';
        } else {
            this.connText.textContent = 'DISCONNECTED';
            this.connStatus.className = 'header-status disconnected';
        }

        // Reset
        for (let i = 0; i < 8; i++) {
            this.zoneState[i] = {
                risk_score: 8.5, risk_level: 'normal',
                active_permits: [], worker_count: 0, fatigue_level: 'normal'
            };
            this.mapManager.setZoneRisk(i, 8.5);
        }
        this.mapManager.setPlume(2, 0);
        this.hazardOverlay.classList.add('hidden');
        this.renderZoneTable();
        this.alertsManager.clear();
        log('Demo stopped');
    }

    tickDemo() {
        this.demoTime += 1;
        const t = this.demoTime;

        // Sensor trends
        let gasVal = 5.0;
        let pressVal = 2.4;

        if (t >= 10) {
            gasVal = 5.0 + Math.min(1, (t - 10) / 110) * 73.0;
        }
        if (t >= 40) {
            pressVal = 2.4 + Math.min(1, (t - 40) / 140) * 4.4;
        }

        // Gas sensor
        const gasTTI = t >= 10 ? Math.max(15, 300 - (t - 10) * 2.3) : null;
        const gasUrg = gasTTI === null ? 'normal' : gasTTI < 60 ? 'critical' : gasTTI < 180 ? 'warning' : 'watch';
        this.handleUpdate({
            type: 'sensor_update', signal_id: 15, zone_id: 2,
            value: gasVal, tti_seconds: gasTTI, urgency: gasUrg
        });

        // Pressure sensor
        const pressTTI = t >= 40 ? Math.max(45, 600 - (t - 40) * 3) : null;
        const pressUrg = pressTTI === null ? 'normal' : pressTTI < 60 ? 'critical' : pressTTI < 240 ? 'warning' : 'watch';
        this.handleUpdate({
            type: 'sensor_update', signal_id: 6, zone_id: 2,
            value: pressVal, tti_seconds: pressTTI, urgency: pressUrg
        });

        // Lead time display
        if (t >= 10) {
            const lt = (t - 10) * 1.5;
            const ltM = Math.floor(lt / 60);
            const ltS = Math.floor(lt % 60);
            this.leadTimeVal.textContent = `${ltM}m ${String(ltS).padStart(2, '0')}s`;
        }

        // Timeline milestones
        if (t === 1) {
            this.mapManager.setOperators([
                { operator_id: 'OP_001', name: 'Alex Mercer', role: 'Field Operator', current_zone: 2 },
                { operator_id: 'OP_002', name: 'Elena Rostova', role: 'Control Room', current_zone: 4 },
                { operator_id: 'OP_005', name: 'Sarah Connor', role: 'Control Room', current_zone: 4 }
            ]);
            for (let i = 0; i < 8; i++) {
                this.handleUpdate({
                    type: 'zone_update', zone_id: i, risk_score: 8.5,
                    active_permits: [], worker_count: i === 2 ? 1 : i === 4 ? 2 : 0,
                    fatigue_level: 'normal'
                });
            }
        }
        else if (t === 10) {
            this.handleUpdate({
                type: 'zone_update', zone_id: 2, risk_score: 18.4,
                active_permits: [], worker_count: 1, fatigue_level: 'normal'
            });
            log('Gas trend detected in Zone C Reactor Area');
        }
        else if (t === 30) {
            this.handleUpdate({
                type: 'zone_update', zone_id: 2, risk_score: 54.2,
                active_permits: ['HotWork'], worker_count: 3, fatigue_level: 'normal'
            });
            this.mapManager.setOperators([
                { operator_id: 'OP_001', name: 'Alex Mercer', role: 'Field Operator', current_zone: 2 },
                { operator_id: 'OP_CON1', name: 'John C.', role: 'Maintenance', current_zone: 2 },
                { operator_id: 'OP_CON2', name: 'Dave K.', role: 'Maintenance', current_zone: 2 },
                { operator_id: 'OP_002', name: 'Elena Rostova', role: 'Control Room', current_zone: 4 },
                { operator_id: 'OP_005', name: 'Sarah Connor', role: 'Control Room', current_zone: 4 }
            ]);
            log('Hot work permit conflict in Zone C');
        }
        else if (t === 60) {
            this.mapManager.setPlume(2, 15.0);
            this.handleUpdate({
                type: 'plume_update', zone_id: 2,
                hazard_radius_m: 15.0, gas_name: 'Methane', leak_rate_kgs: 0.35
            });
            log('Plume modeling active — Zone C Methane');
        }
        else if (t === 90) {
            this.handleUpdate({
                type: 'zone_update', zone_id: 2, risk_score: 68.5,
                active_permits: ['HotWork'], worker_count: 3, fatigue_level: 'normal',
                evac_path: [2, 1, 4], blocked_zones: [2]
            });
            this.handleUpdate({
                type: 'alert',
                alert_id: 'AL-02-0001',
                timestamp: Date.now() / 1000,
                zone_id: 2,
                risk_score: 68.5,
                situation: 'Combustible gas concentration (LEL) rising in Zone C Reactor Area. Conflicting Hot Work permit active, creating ignition risk.',
                actions: [
                    'Suspend all hot work operations in Zone C Reactor Area immediately.',
                    'Verify fire water deluge network pressure >= 7.0 kg/cm².',
                    'Deploy field operator with portable gas detector to verify local LEL levels.'
                ],
                regulatory_citations: [{
                    source: 'OISD-STD-116',
                    section: 'Section 5.3 — Gas Monitoring and LEL Limits during Hot Work',
                    similarity_score: 0.884,
                    relevance: 'Prior to and during hot work in areas where flammable gases are present, continuous monitoring is mandatory, and concentrations must not exceed 10% LEL. Evacuate and revoke permit immediately if exceeded.'
                }],
                urgency: 'Immediate: TTI below 3 minutes. Halt hot work.',
                abstention_notes: []
            });
            log('Alert generated for Zone C');
        }
        else if (t === 120) {
            this.mapManager.setPlume(2, 28.5);
            this.handleUpdate({
                type: 'plume_update', zone_id: 2,
                hazard_radius_m: 28.5, gas_name: 'Methane', leak_rate_kgs: 0.58
            });
            this.handleUpdate({
                type: 'zone_update', zone_id: 1, risk_score: 46.2,
                active_permits: [], worker_count: 0, fatigue_level: 'normal',
                evac_path: [2, 5, 4], blocked_zones: [2, 1]
            });
            log('Plume expanding — Zone B now in warning');
        }
        else if (t === 150) {
            this.handleUpdate({
                type: 'zone_update', zone_id: 2, risk_score: 79.4,
                active_permits: ['HotWork'], worker_count: 3, fatigue_level: 'high',
                evac_path: [2, 5, 4], blocked_zones: [2, 1]
            });
            log('Operator fatigue critical — Alex Mercer');
        }
        else if (t === 180) {
            this.handleUpdate({
                type: 'zone_update', zone_id: 2, risk_score: 92.5,
                active_permits: ['HotWork'], worker_count: 3, fatigue_level: 'high',
                evac_path: [2, 5, 4], blocked_zones: [2, 1]
            });
            this.handleUpdate({
                type: 'alert',
                alert_id: 'AL-02-0002',
                timestamp: Date.now() / 1000,
                zone_id: 2,
                risk_score: 92.5,
                situation: 'Critical gas LEL breach (78% LEL) in Zone C Reactor Area. Active hot work and extreme operator fatigue. Gas plume dispersing towards Zone B Compressor Hall.',
                actions: [
                    'Evacuate all personnel from Zone C and Zone B immediately.',
                    'Initiate Emergency Shutdown System (ESD) sequence to isolate Reactor inlet feeds.',
                    'Dispatch emergency response crew wearing SCBA equipment.'
                ],
                regulatory_citations: [
                    {
                        source: 'OISD-STD-116',
                        section: 'Section 8.4 — Emergency Shutdown Systems (ESD) Activation',
                        similarity_score: 0.812,
                        relevance: 'Activation of the ESD must occur automatically upon process safety parameters exceeding critical limits, including gas detection high alarms.'
                    },
                    {
                        source: 'OSHA 29 CFR 1910.119',
                        section: '1910.119(f) — Operating Procedures and Emergency Steps',
                        similarity_score: 0.795,
                        relevance: 'Emergency operating procedures must define shutdown trigger limits, evacuation steps, and responder roles for toxic or flammable gas releases.'
                    }
                ],
                urgency: 'CRITICAL: TTI 15 seconds. Immediate evacuation.',
                abstention_notes: [
                    'Confined Space rescue gear not cited — entry is not active.',
                    'No regulatory citation match for operator fatigue limits during high gas. Defaulting to general PSM human factors guidelines.'
                ]
            });
            log('Evacuation order dispatched');
            clearInterval(this.demoTimer);
        }
    }
}

function log(msg) { console.log(`[AEGIS] ${msg}`); }

window.addEventListener('DOMContentLoaded', () => {
    window.app = new AegisApp();
});

export default AegisApp;
