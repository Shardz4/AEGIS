/**
 * AEGIS Application Coordinator
 * 
 * Manages WebSocket connection, zone table rendering, demo scenario,
 * and data flow between map/chart/alert managers.
 */
import { PlantMapManager } from './map.js';
import { SparklineManager } from './charts.js';
import { AlertFeedManager } from './alerts.js';
import { VoiceAnnouncer } from './voice.js';
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
        this.voiceAnnouncer = new VoiceAnnouncer(document.getElementById('voice-btn'));

        // State
        this.ws = null;
        this.demoActive = false;
        this.demoTime = 0;
        this.demoTimer = null;
        this.lastFrame = performance.now();
        this.malfunctioningSensors = new Set();

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
        this.alertContainer.addEventListener('click', (e) => this.handleMitigationClick(e));

        // State for closed-loop mitigations
        this.mitigatedZones = new Set();
        this.cancelledPermits = new Set();
        this.recalibratedSensors = new Set();
        this.calibrationSettleTimer = null;

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
        // Apply local overrides in Demo Mode
        if (this.demoActive) {
            if (msg.type === 'zone_update' && msg.zone_id === 2) {
                if (this.cancelledPermits.has('PTW-8022')) {
                    msg.active_permits = (msg.active_permits || []).filter(p => p !== 'HotWork');
                    msg.risk_score = Math.max(8.5, msg.risk_score - 25.0);
                    msg.worker_count = Math.max(0, msg.worker_count - 2);
                }
                if (this.mitigatedZones.has(2)) {
                    msg.active_permits = [];
                    msg.risk_score = 8.5;
                    msg.worker_count = 0;
                    msg.evac_path = null;
                    msg.blocked_zones = (msg.blocked_zones || []).filter(z => z !== 2);
                }
            } else if (msg.type === 'sensor_update' && msg.zone_id === 2) {
                if (this.mitigatedZones.has(2)) {
                    msg.value = (msg.signal_id === 15) ? 5.0 : 2.4;
                    msg.tti_seconds = null;
                    msg.urgency = 'normal';
                }
            } else if (msg.type === 'plume_update' && msg.zone_id === 2) {
                if (this.mitigatedZones.has(2)) {
                    msg.hazard_radius_m = 0;
                    msg.leak_rate_kgs = 0;
                }
            }
        }

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

            case 'cctv_update': {
                const zoneChar = ZONE_IDS[msg.zone_id] || String(msg.zone_id);
                const camId = msg.camera_id || `CAM-${zoneChar}-301`;
                
                // Update map
                this.mapManager.setCameraWarning(camId, msg.active);
                this.mapManager.draw();
                
                // Update monitor HUD widget
                const camIdEl = document.getElementById('cctv-cam-id');
                const camStatusEl = document.getElementById('cctv-cam-status');
                const hudEl = document.getElementById('cctv-hud');
                const bboxEl = document.getElementById('cctv-bbox');
                
                if (camIdEl) camIdEl.textContent = camId;
                if (camStatusEl) {
                    camStatusEl.textContent = msg.active ? 'VIOLATION DETECTED' : 'NOMINAL';
                }
                if (hudEl) {
                    hudEl.className = msg.active ? 'cctv-hud state-breached' : 'cctv-hud';
                }
                if (bboxEl) {
                    if (msg.active) {
                        bboxEl.style.display = 'block';
                        bboxEl.className = 'cctv-bbox state-breached';
                        bboxEl.style.left = '30%';
                        bboxEl.style.top = '25%';
                        bboxEl.style.width = '40%';
                        bboxEl.style.height = '50%';
                        
                        const labelEl = document.getElementById('cctv-bbox-label');
                        if (labelEl) {
                            labelEl.textContent = msg.signal_id === 1001 
                                ? `PPE BREACH: ${msg.violator_role} (${(msg.confidence*100).toFixed(0)}%)` 
                                : `VISUAL SMOKE (${(msg.confidence*100).toFixed(0)}%)`;
                        }
                    } else {
                        bboxEl.style.display = 'none';
                    }
                }
                break;
            }

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
                    tti_seconds: msg.tti_seconds, urgency: msg.urgency,
                    malfunctioning: msg.malfunctioning || this.malfunctioningSensors.has(msg.signal_id),
                    calibration_state: msg.calibration_state || 'NOMINAL'
                });
                this.chartsManager.render(this.sparklineContainer);
                break;
            }

            case 'malfunctions_update':
                this.malfunctioningSensors = new Set(msg.malfunctioning_sensors || []);
                for (const signalId of Object.keys(this.chartsManager.sensorMeta)) {
                    const id = parseInt(signalId);
                    this.chartsManager.sensorMeta[id].malfunctioning = this.malfunctioningSensors.has(id);
                }
                this.renderZoneTable();
                this.chartsManager.render(this.sparklineContainer);
                break;

            case 'plume_update':
                this.mapManager.setPlume(msg.zone_id, msg.hazard_radius_m);
                this.updatePlumeOverlay(msg);
                break;

            case 'alert':
                this.alertsManager.addAlert(msg);
                this.voiceAnnouncer.announce(msg);
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

            case 'mitigated':
                this.applyMitigationState(msg);
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
                const zoneFaults = Array.from(this.malfunctioningSensors).filter(id => (id % 8) === i);
                let faultHtml = '';
                if (zoneFaults.length > 0) {
                    faultHtml = `
                        <div class="detail-item">
                            <span class="detail-label">faults</span>
                            <span class="detail-val fault">${zoneFaults.length} SEN</span>
                        </div>
                    `;
                }
                detailEl.innerHTML = `
                    <div class="detail-item">
                        <span class="detail-label">fatigue</span>
                        <span class="detail-val ${fatigueClass}">${fatigue.toUpperCase()}</span>
                    </div>
                    ${faultHtml}
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
        this.mitigatedZones.clear();
        this.cancelledPermits.clear();
        this.malfunctioningSensors.clear();
        this.recalibratedSensors.clear();
        if (this.calibrationSettleTimer) {
            clearTimeout(this.calibrationSettleTimer);
            this.calibrationSettleTimer = null;
        }
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
        this.mitigatedZones.clear();
        this.cancelledPermits.clear();
        this.malfunctioningSensors.clear();
        this.recalibratedSensors.clear();
        if (this.calibrationSettleTimer) {
            clearTimeout(this.calibrationSettleTimer);
            this.calibrationSettleTimer = null;
        }
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
        let tempVal = 25.0;

        if (t >= 10) {
            gasVal = 5.0 + Math.min(1, (t - 10) / 110) * 73.0;
        }
        if (t >= 40) {
            pressVal = 2.4 + Math.min(1, (t - 40) / 140) * 4.4;
        }

        let tempCalibration = 'NOMINAL';
        if (this.recalibratedSensors.has(5)) {
            tempCalibration = 'NOMINAL';
        } else if (t >= 30) {
            if (t >= 70) {
                tempCalibration = 'DRIFTING';
            }
            
            // If SEN-5 is recalibrating, settle it
            if (this.chartsManager.sensorMeta[5]?.calibration_state === 'CALIBRATING') {
                tempCalibration = 'CALIBRATING';
                tempVal = 25.0;
                if (!this.calibrationSettleTimer) {
                    this.calibrationSettleTimer = setTimeout(() => {
                        this.recalibratedSensors.add(5);
                        this.handleUpdate({
                            type: 'sensor_update', signal_id: 5, zone_id: 2,
                            value: 25.0, tti_seconds: null, urgency: 'normal',
                            calibration_state: 'NOMINAL'
                        });
                        this.calibrationSettleTimer = null;
                    }, 2000);
                }
            } else {
                tempVal = 25.0 + (t - 30) * 1.5;
            }
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

        // Temperature sensor
        const tempTTI = tempCalibration === 'DRIFTING' ? 240 : null;
        const tempUrg = tempCalibration === 'DRIFTING' ? 'warning' : 'normal';
        this.handleUpdate({
            type: 'sensor_update', signal_id: 5, zone_id: 2,
            value: tempVal, tti_seconds: tempTTI, urgency: tempUrg,
            calibration_state: tempCalibration
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
        else if (t === 15) {
            this.handleUpdate({
                type: 'cctv_update',
                zone_id: 2,
                signal_id: 1001,
                value: 1.0,
                active: true,
                camera_id: 'CAM-C-301',
                confidence: 0.94,
                violator_role: 'Contractor'
            });
            log('CCTV PPE Breach event detected in Zone C');
        }
        else if (t === 20) {
            this.handleUpdate({
                type: 'malfunctions_update',
                malfunctioning_sensors: [18]
            });
            this.handleUpdate({
                type: 'sensor_update',
                signal_id: 18,
                zone_id: 2,
                value: 95.0,
                tti_seconds: 30,
                urgency: 'critical',
                malfunctioning: true
            });
            this.handleUpdate({
                type: 'zone_update',
                zone_id: 2,
                risk_score: 8.5,
                active_permits: [],
                worker_count: 1,
                fatigue_level: 'normal'
            });
            log('Simulated sensor malfunction injected on SEN-18 (Zone C)');
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
        else if (t === 45) {
            this.handleUpdate({
                type: 'cctv_update',
                zone_id: 2,
                signal_id: 1002,
                value: 1.0,
                active: true,
                camera_id: 'CAM-C-301',
                confidence: 0.96,
                violator_role: ''
            });
            log('CCTV Visual Smoke event detected in Zone C');
        }
        else if (t === 70) {
            if (!this.recalibratedSensors.has(5)) {
                this.handleUpdate({
                    type: 'alert',
                    alert_id: 'AL-CUSUM-05',
                    timestamp: Date.now() / 1000,
                    zone_id: 2,
                    risk_score: 18.5,
                    active_permits: [],
                    situation: 'CUSUM drift threshold breached on Reactor Temperature sensor (SEN-5). Slow upward signal drift detected, indicating loss of sensor calibration.',
                    actions: [
                        'Initiate field calibration query for SEN-5.',
                        'Compare readings with local dial thermometer TI-205.'
                    ],
                    regulatory_citations: [],
                    urgency: 'Low: Slow CUSUM drift detected. Recalibration required.',
                    abstention_notes: [],
                    is_drift_alert: true,
                    sensor_id: 5
                });
                log('CUSUM drift warning generated for SEN-5');
            }
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
                type: 'malfunctions_update',
                malfunctioning_sensors: []
            });
            this.handleUpdate({
                type: 'sensor_update',
                signal_id: 18,
                zone_id: 2,
                value: 2.4,
                tti_seconds: null,
                urgency: 'normal',
                malfunctioning: false
            });
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
                active_permits: ['PTW-8022'],
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
                active_permits: ['PTW-8022'],
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

    handleMitigationClick(e) {
        const btn = e.target.closest('.btn-mitigate');
        if (!btn || btn.disabled) return;

        const permitId = btn.dataset.permitId;
        const zoneIdStr = btn.dataset.zoneId;
        const sensorIdStr = btn.dataset.sensorId;

        if (btn.classList.contains('btn-ack-cctv')) {
            const zoneId = parseInt(zoneIdStr, 10);
            const sensorId = parseInt(sensorIdStr, 10);
            if (this.demoActive) {
                document.querySelectorAll(`.btn-ack-cctv[data-zone-id="${zoneId}"][data-sensor-id="${sensorId}"]`).forEach(b => {
                    b.disabled = true;
                    b.textContent = `Acknowledged`;
                });
                
                const zoneChar = ZONE_IDS[zoneId] || String(zoneId);
                const alertCard = document.getElementById(`alert-AL-CCTV-${zoneChar}-${sensorId}`);
                if (alertCard) alertCard.remove();
                
                // Reset camera warning
                this.mapManager.setCameraWarning(`CAM-${zoneChar}-301`, false);
                this.mapManager.draw();
                
                // Clear HUD
                const hud = document.getElementById('cctv-hud');
                const bbox = document.getElementById('cctv-bbox');
                if (hud) hud.className = 'cctv-hud';
                const camStatus = document.getElementById('cctv-cam-status');
                if (camStatus) camStatus.textContent = 'NOMINAL';
                if (bbox) bbox.style.display = 'none';
                
                log(`Demo Mode: Acknowledged CCTV Event in Zone ${zoneId}`);
            } else {
                if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                    this.ws.send(JSON.stringify({
                        type: 'mitigate',
                        action: 'ack_cctv',
                        zone_id: zoneId,
                        sensor_id: sensorId
                    }));
                }
            }
        } else if (permitId) {
            // Cancel permit
            if (this.demoActive) {
                this.cancelledPermits.add(permitId);
                // Disable all cancel buttons for this permit
                document.querySelectorAll(`.btn-cancel-permit[data-permit-id="${permitId}"]`).forEach(b => {
                    b.disabled = true;
                    b.textContent = `Permit ${permitId} Cancelled`;
                });
                log(`Demo Mode: Cancelled permit ${permitId}`);
                this.applyDemoMitigationEffects();
            } else {
                if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                    this.ws.send(JSON.stringify({
                        type: 'mitigate',
                        action: 'cancel_permit',
                        permit_id: permitId
                    }));
                }
            }
        } else if (zoneIdStr !== undefined) {
            // Isolate feed
            const zoneId = parseInt(zoneIdStr, 10);
            if (this.demoActive) {
                this.mitigatedZones.add(zoneId);
                // Disable all isolate buttons for this zone
                document.querySelectorAll(`.btn-isolate-feed[data-zone-id="${zoneId}"]`).forEach(b => {
                    b.disabled = true;
                    b.textContent = `Zone isolated`;
                });
                log(`Demo Mode: Isolated Zone ${zoneId}`);
                this.applyDemoMitigationEffects();
            } else {
                if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                    this.ws.send(JSON.stringify({
                        type: 'mitigate',
                        action: 'isolate_feed',
                        zone_id: zoneId
                    }));
                }
            }
        } else if (sensorIdStr !== undefined) {
            // Recalibrate sensor
            const sensorId = parseInt(sensorIdStr, 10);
            if (this.demoActive) {
                this.recalibratedSensors.add(sensorId);
                document.querySelectorAll(`.btn-recalibrate[data-sensor-id="${sensorId}"]`).forEach(b => {
                    b.disabled = true;
                    b.textContent = `Sensor recalibrating`;
                });
                log(`Demo Mode: Recalibrating sensor ${sensorId}`);
                
                // Directly remove the drift warning alert card
                const card = document.getElementById('alert-AL-CUSUM-05');
                if (card) card.remove();
                
                this.chartsManager.updateSensor(sensorId, 25.0, {
                    calibration_state: 'CALIBRATING',
                    zone_id: 2,
                    urgency: 'normal'
                });
                this.chartsManager.render(this.sparklineContainer);
            } else {
                if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                    this.ws.send(JSON.stringify({
                        type: 'mitigate',
                        action: 'recalibrate',
                        sensor_id: sensorId
                    }));
                }
            }
        }
    }

    applyMitigationState(msg) {
        if (msg.action === 'cancel_permit') {
            const pId = msg.permit_id;
            this.cancelledPermits.add(pId);
            document.querySelectorAll(`.btn-cancel-permit[data-permit-id="${pId}"]`).forEach(b => {
                b.disabled = true;
                b.textContent = `Permit ${pId} Cancelled`;
            });
            log(`Live Mode: Permit ${pId} Cancelled`);
        } else if (msg.action === 'isolate_feed') {
            const zId = parseInt(msg.zone_id, 10);
            this.mitigatedZones.add(zId);
            document.querySelectorAll(`.btn-isolate-feed[data-zone-id="${zId}"]`).forEach(b => {
                b.disabled = true;
                b.textContent = `Zone isolated`;
            });
            log(`Live Mode: Zone ${zId} Isolated`);
        } else if (msg.action === 'recalibrate') {
            const sId = parseInt(msg.sensor_id, 10);
            this.recalibratedSensors.add(sId);
            document.querySelectorAll(`.btn-recalibrate[data-sensor-id="${sId}"]`).forEach(b => {
                b.disabled = true;
                b.textContent = `Sensor recalibrating`;
            });
            log(`Live Mode: Recalibrated Sensor ${sId}`);
            
            // Remove the drift warning alert card if present
            const card = document.getElementById('alert-AL-CUSUM-05');
            if (card) card.remove();
        } else if (msg.action === 'ack_cctv') {
            const zId = parseInt(msg.zone_id, 10);
            const sId = parseInt(msg.sensor_id, 10);
            document.querySelectorAll(`.btn-ack-cctv[data-zone-id="${zId}"][data-sensor-id="${sId}"]`).forEach(b => {
                b.disabled = true;
                b.textContent = `Acknowledged`;
            });
            const zoneChar = ZONE_IDS[zId] || String(zId);
            const card = document.getElementById(`alert-AL-CCTV-${zoneChar}-${sId}`);
            if (card) card.remove();
            
            // Reset camera warning
            this.mapManager.setCameraWarning(`CAM-${zoneChar}-301`, false);
            this.mapManager.draw();
            
            // Reset HUD
            const hud = document.getElementById('cctv-hud');
            const bbox = document.getElementById('cctv-bbox');
            if (hud) hud.className = 'cctv-hud';
            const camStatus = document.getElementById('cctv-cam-status');
            if (camStatus) camStatus.textContent = 'NOMINAL';
            if (bbox) bbox.style.display = 'none';
        }
    }
    }

    applyDemoMitigationEffects() {
        // Re-send current values through handleUpdate so the overrides get applied immediately
        const currentZoneState = this.zoneState[2];
        if (currentZoneState) {
            this.handleUpdate({
                type: 'zone_update',
                ...currentZoneState
            });
        }
        // Force update the plume to 0 if isolated
        if (this.mitigatedZones.has(2)) {
            this.handleUpdate({
                type: 'plume_update', zone_id: 2,
                hazard_radius_m: 0, gas_name: 'Methane', leak_rate_kgs: 0
            });
            this.handleUpdate({
                type: 'sensor_update', signal_id: 15, zone_id: 2,
                value: 5.0, tti_seconds: null, urgency: 'normal'
            });
            this.handleUpdate({
                type: 'sensor_update', signal_id: 6, zone_id: 2,
                value: 2.4, tti_seconds: null, urgency: 'normal'
            });
        }
    }
}

function log(msg) { console.log(`[AEGIS] ${msg}`); }

window.addEventListener('DOMContentLoaded', () => {
    window.app = new AegisApp();
});

export default AegisApp;
