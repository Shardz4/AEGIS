/**
 * Main Application Coordinator for AEGIS Dashboard
 */
import { PlantMapManager } from './map.js';
import { SparklineManager } from './charts.js';
import { AlertFeedManager } from './alerts.js';
import { formatTimestamp, getRiskLevel } from './utils.js';

class AegisApp {
    constructor() {
        // Elements
        this.connDot = document.getElementById('conn-dot');
        this.connText = document.getElementById('conn-text');
        this.clockEl = document.getElementById('current-clock');
        this.demoBtn = document.getElementById('demo-btn');
        this.leadTimeContainer = document.getElementById('lead-time-container');
        this.leadTimeVal = document.getElementById('lead-time-val');
        this.zoneContainer = document.getElementById('zone-cards-container');
        this.sparklineContainer = document.getElementById('sparklines-container');
        this.alertContainer = document.getElementById('alert-feed-container');
        this.alertCountBadge = document.getElementById('alert-count-badge');
        this.hazardOverlay = document.getElementById('hazard-overlay');
        this.plumeRadiusEl = document.getElementById('plume-radius');
        this.plumeRateEl = document.getElementById('plume-rate');
        this.plumeGasEl = document.getElementById('plume-gas');
        this.plumeSourceEl = document.getElementById('plume-source');

        // Managers
        const canvas = document.getElementById('map-canvas');
        this.mapManager = new PlantMapManager(canvas);
        this.chartsManager = new SparklineManager();
        this.alertsManager = new AlertFeedManager(this.alertContainer, this.alertCountBadge);

        // State
        this.websocket = null;
        this.demoActive = false;
        this.demoTime = 0;
        this.demoTimerId = null;
        this.lastFrameTime = performance.now();

        // Bind events
        this.demoBtn.addEventListener('click', () => this.toggleDemo());

        // Initial setup
        this.startClock();
        this.connectWebSocket();
        this.initLoop();
        this.initializeDefaultData();
    }

    startClock() {
        setInterval(() => {
            this.clockEl.textContent = formatTimestamp(Date.now() / 1000);
        }, 1000);
    }

    initializeDefaultData() {
        // Set all 8 zones to healthy default values
        for (let i = 0; i < 8; i++) {
            this.mapManager.setZoneRisk(i, 8.5);
            this.updateZoneCardUI(i, {
                zone_id: i,
                risk_score: 8.5,
                risk_level: 'normal',
                active_permits: [],
                worker_count: 0,
                fatigue_level: 'normal'
            });
        }
        
        // Define some default active workers on map
        this.mapManager.setOperators([
            { operator_id: "OP_002", name: "Elena R.", role: "Control Room", current_zone: 4 },
            { operator_id: "OP_004", name: "Marcus A.", role: "Field Operator", current_zone: 3 },
            { operator_id: "OP_005", name: "Sarah C.", role: "Control Room", current_zone: 4 }
        ]);

        this.mapManager.setWind(225, 3.2);
    }

    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        
        this.connText.textContent = "Connecting...";
        this.connDot.className = "dot dot-warning";

        this.websocket = new WebSocket(wsUrl);

        this.websocket.onopen = () => {
            logger("WebSocket connected.");
            this.connDot.className = "dot dot-safe";
            this.connText.textContent = "Live Feed Connected";
        };

        this.websocket.onmessage = (event) => {
            if (this.demoActive) return; // Ignore live telemetry during demo playback
            
            try {
                const msg = jsonParse(event.data);
                this.handleUpdate(msg);
            } catch (err) {
                console.error("Error handling websocket payload:", err);
            }
        };

        this.websocket.onclose = () => {
            logger("WebSocket disconnected. Reconnecting in 3 seconds...");
            this.connDot.className = "dot dot-danger";
            this.connText.textContent = "Disconnected (Retrying)";
            
            setTimeout(() => this.connectWebSocket(), 3000);
        };
    }

    handleUpdate(msg) {
        switch (msg.type) {
            case 'zone_update':
                this.mapManager.setZoneRisk(msg.zone_id, msg.risk_score);
                this.updateZoneCardUI(msg.zone_id, msg);
                break;
            case 'sensor_update':
                const sensorLabels = {
                    5: { label: "Reactor Temp", unit: "°C", threshold: 85.0 },
                    6: { label: "Reactor Pressure", unit: " bar", threshold: 8.0 },
                    10: { label: "Vessel Level", unit: "m", threshold: 12.0 },
                    15: { label: "Gas Concentration (LEL)", unit: "% LEL", threshold: 20.0 }
                };
                const spec = sensorLabels[msg.signal_id] || { label: `Sensor ${msg.signal_id}`, unit: '', threshold: 100.0 };
                
                this.chartsManager.updateSensor(msg.signal_id, msg.value, {
                    label: spec.label,
                    unit: spec.unit,
                    threshold: spec.threshold,
                    zone_id: msg.zone_id,
                    tti_seconds: msg.tti_seconds,
                    urgency: msg.urgency
                });
                this.chartsManager.render(this.sparklineContainer);
                break;
            case 'plume_update':
                this.mapManager.setPlume(msg.zone_id, msg.hazard_radius_m);
                this.updatePlumeOverlayUI(msg);
                break;
            case 'alert':
                this.alertsManager.addAlert(msg);
                break;
            case 'fatigue_update':
                // We handle fatigue updates within zone updates or map
                break;
            case 'start_demo':
                if (!this.demoActive) {
                    this.startDemoScenario();
                }
                break;
        }
    }

    updateZoneCardUI(zoneId, data) {
        let card = document.getElementById(`zone-card-${zoneId}`);
        const zonesInfo = {
            0: "Zone A - Tank Farm",
            1: "Zone B - Compressor Hall",
            2: "Zone C - Reactor Area",
            3: "Zone D - Pipe Rack",
            4: "Zone E - Control Room",
            5: "Zone F - Loading Bay",
            6: "Zone G - Utilities",
            7: "Zone H - Flare Stack",
        };
        const zoneName = zonesInfo[zoneId] || `Zone ${zoneId}`;

        if (!card) {
            card = document.createElement('div');
            card.id = `zone-card-${zoneId}`;
            this.zoneContainer.appendChild(card);
        }

        const riskLevel = getRiskLevel(data.risk_score);
        card.className = `zone-card level-${riskLevel}`;

        const permitsList = data.active_permits && data.active_permits.length > 0 
            ? data.active_permits.join(', ') 
            : 'None';

        card.innerHTML = `
            <div class="zone-card-header">
                <span class="zone-card-title">${zoneName}</span>
                <span class="zone-card-score text-${riskLevel === 'high' ? 'danger' : riskLevel === 'moderate' ? 'warning' : 'accent'}">${data.risk_score.toFixed(1)}%</span>
            </div>
            <div class="zone-card-details">
                <div class="zone-card-row">
                    <span>Permits</span>
                    <span class="val font-mono">${permitsList}</span>
                </div>
                <div class="zone-card-row">
                    <span>Workers</span>
                    <span class="val font-mono">${data.worker_count}</span>
                </div>
                <div class="zone-card-row">
                    <span>Fatigue Level</span>
                    <span class="val font-mono text-${data.fatigue_level === 'high' ? 'danger' : data.fatigue_level === 'moderate' ? 'warning' : 'primary'}">${data.fatigue_level.toUpperCase()}</span>
                </div>
            </div>
        `;
    }

    updatePlumeOverlayUI(plumeData) {
        if (plumeData.hazard_radius_m > 0) {
            this.hazardOverlay.classList.remove('hidden');
            this.plumeSourceEl.textContent = `Zone ${plumeData.zone_id}`;
            this.plumeRadiusEl.textContent = `${plumeData.hazard_radius_m.toFixed(1)}m`;
            this.plumeGasEl.textContent = plumeData.gas_name || 'Hydrocarbon';
            this.plumeRateEl.textContent = plumeData.leak_rate_kgs ? `${plumeData.leak_rate_kgs.toFixed(2)} kg/s` : '0.45 kg/s';
        } else {
            this.hazardOverlay.classList.add('hidden');
        }
    }

    initLoop() {
        const loop = (timestamp) => {
            const dt = (timestamp - this.lastFrameTime) / 1000.0;
            this.lastFrameTime = timestamp;

            // Update map and animations
            this.mapManager.update(dt);
            this.mapManager.draw();

            requestAnimationFrame(loop);
        };
        requestAnimationFrame(loop);
    }

    /* DEMO SCENARIO LOGIC */
    toggleDemo() {
        if (this.demoActive) {
            this.stopDemoScenario();
        } else {
            // Send trigger to server so other connected browsers run it too
            if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
                this.websocket.send(JSON.stringify({ type: 'start_demo' }));
            }
            this.startDemoScenario();
        }
    }

    startDemoScenario() {
        this.demoActive = true;
        this.demoTime = 0;
        this.demoBtn.innerHTML = '🛑 Stop Demo';
        this.demoBtn.className = 'btn btn-primary';
        this.connDot.className = 'dot dot-danger';
        this.connText.textContent = 'DEMO MODE RUNNING';
        this.leadTimeContainer.classList.remove('hidden');
        this.leadTimeVal.textContent = '0m 00s';

        // Clear alert feed
        this.alertsManager.clear();
        
        // Clear sparklines
        this.sparklineContainer.innerHTML = '';
        this.chartsManager = new SparklineManager();

        logger("Demo scenario starting...");

        // Run 1Hz interval ticks
        this.demoTimerId = setInterval(() => {
            this.tickDemo();
        }, 1000);
        
        // Immediate tick to establish baseline
        this.tickDemo();
    }

    stopDemoScenario() {
        this.demoActive = false;
        clearInterval(this.demoTimerId);
        this.demoBtn.innerHTML = '🚀 Run Demo Scenario';
        this.demoBtn.className = 'btn btn-demo';
        this.leadTimeContainer.classList.add('hidden');
        
        // Re-establish websocket status
        if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
            this.connDot.className = 'dot dot-safe';
            this.connText.textContent = 'Live Feed Connected';
        } else {
            this.connDot.className = 'dot dot-danger';
            this.connText.textContent = 'Disconnected';
        }

        this.initializeDefaultData();
        this.alertsManager.clear();
        logger("Demo scenario stopped. Reverted to baseline.");
    }

    tickDemo() {
        this.demoTime += 1;
        const t = this.demoTime;

        // 1. Tick sparklines with simulated sensor climbs
        let gasVal = 5.0; // % LEL baseline
        let pressVal = 2.4; // bar baseline
        
        if (t >= 10) {
            // Gas leak starts rising from 5% LEL to 78% LEL at t=120
            const gasProgress = Math.min(1.0, (t - 10) / 110);
            gasVal = 5.0 + gasProgress * 73.0;
        }
        if (t >= 40) {
            // Pressure starts rising from 2.4 bar to 6.8 bar at t=180
            const pressProgress = Math.min(1.0, (t - 40) / 140);
            pressVal = 2.4 + pressProgress * 4.4;
        }

        // Send sensor updates
        const gasTTI = t >= 10 ? Math.max(15, 300 - (t - 10) * 2.3) : null;
        const gasUrgency = gasTTI === null ? 'normal' : gasTTI < 60 ? 'critical' : gasTTI < 180 ? 'warning' : 'watch';
        this.handleUpdate({
            type: 'sensor_update',
            signal_id: 15,
            zone_id: 2,
            value: gasVal,
            tti_seconds: gasTTI,
            urgency: gasUrgency
        });

        const pressTTI = t >= 40 ? Math.max(45, 600 - (t - 40) * 3) : null;
        const pressUrgency = pressTTI === null ? 'normal' : pressTTI < 60 ? 'critical' : pressTTI < 240 ? 'warning' : 'watch';
        this.handleUpdate({
            type: 'sensor_update',
            signal_id: 6,
            zone_id: 2,
            value: pressVal,
            tti_seconds: pressTTI,
            urgency: pressUrgency
        });

        // Update Lead Time Display
        if (t >= 10) {
            // "Lead Time" represents the duration the system predicts the breach *before* it actually hits 100% threshold.
            // We simulate a growing lead time metric
            const ltSecs = (t - 10) * 1.5;
            const ltMin = Math.floor(ltSecs / 60);
            const ltSec = Math.floor(ltSecs % 60);
            this.leadTimeVal.textContent = `${ltMin}m ${ltSec.toString().padStart(2, '0')}s`;
        }

        // 2. Timeline milestones
        if (t === 1) {
            // Baseline setup
            this.mapManager.setOperators([
                { operator_id: "OP_001", name: "Alex Mercer", role: "Field Operator", current_zone: 2 },
                { operator_id: "OP_002", name: "Elena Rostova", role: "Control Room", current_zone: 4 },
                { operator_id: "OP_005", name: "Sarah Connor", role: "Control Room", current_zone: 4 }
            ]);
            
            // All zones safe
            for (let i = 0; i < 8; i++) {
                this.mapManager.setZoneRisk(i, 8.5);
                this.handleUpdate({
                    type: 'zone_update',
                    zone_id: i,
                    risk_score: 8.5,
                    active_permits: [],
                    worker_count: i === 2 ? 1 : i === 4 ? 2 : 0,
                    fatigue_level: 'normal'
                });
            }
        }
        else if (t === 10) {
            // Leak starts. Zone 2 risk creeps up slightly
            this.mapManager.setZoneRisk(2, 18.4);
            this.handleUpdate({
                type: 'zone_update',
                zone_id: 2,
                risk_score: 18.4,
                active_permits: [],
                worker_count: 1,
                fatigue_level: 'normal'
            });
            logger("Gas level alert trend detected in Zone 2 Reactor Area.");
        }
        else if (t === 30) {
            // Hot work active in Zone 2
            this.mapManager.setZoneRisk(2, 54.2);
            this.handleUpdate({
                type: 'zone_update',
                zone_id: 2,
                risk_score: 54.2,
                active_permits: ['HotWork'],
                worker_count: 3, // 2 contractors joined
                fatigue_level: 'normal'
            });
            
            // Add contractors to operators list
            this.mapManager.setOperators([
                { operator_id: "OP_001", name: "Alex Mercer", role: "Field Operator", current_zone: 2 },
                { operator_id: "OP_CON1", name: "John C.", role: "Maintenance", current_zone: 2 },
                { operator_id: "OP_CON2", name: "Dave K.", role: "Maintenance", current_zone: 2 },
                { operator_id: "OP_002", name: "Elena Rostova", role: "Control Room", current_zone: 4 },
                { operator_id: "OP_005", name: "Sarah Connor", role: "Control Room", current_zone: 4 }
            ]);
            logger("Conflict: Hot work authorized in Zone 2 with rising LEL trend.");
        }
        else if (t === 60) {
            // TTI drops, Plume starts rendering
            this.mapManager.setPlume(2, 15.0);
            this.handleUpdate({
                type: 'plume_update',
                zone_id: 2,
                hazard_radius_m: 15.0,
                gas_name: 'Methane',
                leak_rate_kgs: 0.35
            });
            logger("Gaussian Plume modeling: Zone 2 Methane dispersion active.");
        }
        else if (t === 90) {
            // First alert generated with citations (OISD-STD-116 Section 5.3)
            this.mapManager.setZoneRisk(2, 68.5);
            this.handleUpdate({
                type: 'zone_update',
                zone_id: 2,
                risk_score: 68.5,
                active_permits: ['HotWork'],
                worker_count: 3,
                fatigue_level: 'normal'
            });

            this.handleUpdate({
                type: 'alert',
                alert_id: "AL-02-0001",
                timestamp: Date.now() / 1000,
                zone_id: 2,
                risk_score: 68.5,
                situation: "A combustible gas concentration (LEL) anomaly is growing in Zone 2 Reactor Area. A conflicting Hot Work permit is active in this zone, creating an immediate ignition risk.",
                actions: [
                    "Order immediate stop to all hot work operations in Zone 2 Reactor Area.",
                    "Verify the fire water deluge network pressure is >= 7.0 kg/cm².",
                    "Deploy field operator with portable gas detector to verify local LEL levels."
                ],
                regulatory_citations: [
                    {
                        source: "OISD-STD-116",
                        section: "Section 5.3 - Gas Monitoring and LEL Limits during Hot Work",
                        similarity_score: 0.884,
                        relevance: "Prior to and during hot work in areas where flammable gases are present, continuous monitoring is mandatory, and concentrations must not exceed 10% LEL. Evacuate and revoke permit immediately if exceeded."
                    }
                ],
                urgency: "Immediate: TTI is less than 3 minutes. Halt hot work operations.",
                abstention_notes: []
            });
            logger("LLM safety narrative generated for Zone 2.");
        }
        else if (t === 120) {
            // Plume grows, Zone 1 warning
            this.mapManager.setPlume(2, 28.5);
            this.handleUpdate({
                type: 'plume_update',
                zone_id: 2,
                hazard_radius_m: 28.5,
                gas_name: 'Methane',
                leak_rate_kgs: 0.58
            });

            // Zone 1 enters Warning (risk score = 45%)
            this.mapManager.setZoneRisk(1, 46.2);
            this.handleUpdate({
                type: 'zone_update',
                zone_id: 1,
                risk_score: 46.2,
                active_permits: [],
                worker_count: 0,
                fatigue_level: 'normal'
            });
            logger("Zone 2 Methane plume boundary expanding. Adjacent Zone 1 in warning.");
        }
        else if (t === 150) {
            // Fatigue warning for Alex Mercer (11 hours on night shift)
            this.mapManager.setZoneRisk(2, 79.4);
            this.handleUpdate({
                type: 'zone_update',
                zone_id: 2,
                risk_score: 79.4,
                active_permits: ['HotWork'],
                worker_count: 3,
                fatigue_level: 'high'
            });
            logger("Human factors warning: Field operator Alex Mercer fatigue score is critical.");
        }
        else if (t === 180) {
            // Full cascade, risk score hits 92%, second alert with evacuation
            this.mapManager.setZoneRisk(2, 92.5);
            this.handleUpdate({
                type: 'zone_update',
                zone_id: 2,
                risk_score: 92.5,
                active_permits: ['HotWork'],
                worker_count: 3,
                fatigue_level: 'high'
            });

            this.handleUpdate({
                type: 'alert',
                alert_id: "AL-02-0002",
                timestamp: Date.now() / 1000,
                zone_id: 2,
                risk_score: 92.5,
                situation: "Critical gas LEL breach (78% LEL) in Zone 2 Reactor Area coupled with active hot work and extreme field operator fatigue. Gas plume is dispersing downwind towards Zone 1 Compressor Hall.",
                actions: [
                    "Evacuate all personnel from Zone 2 Reactor Area and Zone 1 Compressor Hall immediately.",
                    "Initiate automated Emergency Shutdown System (ESD) sequence to isolate Reactor inlet feeds.",
                    "Dispatch emergency response crew wearing SCBA equipment."
                ],
                regulatory_citations: [
                    {
                        source: "OISD-STD-116",
                        section: "Section 8.4 - Emergency Shutdown Systems (ESD) Activation",
                        similarity_score: 0.812,
                        relevance: "Activation of the ESD must occur automatically upon process safety parameters exceeding critical limits, including gas detection high alarms."
                    },
                    {
                        source: "OSHA 29 CFR 1910.119",
                        section: "1910.119(f) - Operating Procedures and Emergency Steps",
                        similarity_score: 0.795,
                        relevance: "Emergency operating procedures must define shutdown trigger limits, evacuation steps, and responder roles for toxic or flammable gas releases."
                    }
                ],
                urgency: "CRITICAL: TTI is 15 seconds. Immediate evacuation ordered.",
                abstention_notes: [
                    "Confined Space rescue gear was not cited as entry is not active.",
                    "No regulatory citation matches found for operator fatigue limits during high gas, defaulting to general PSM human factors guidelines."
                ]
            });
            
            logger("Evacuation recommendation dispatched. ESD trigger active.");
            
            // Loop completed, stop and let it sit at final state
            clearInterval(this.demoTimerId);
        }
    }
}

function logger(msg) {
    console.log(`[AEGIS APP] ${msg}`);
}

function jsonParse(str) {
    try {
        return JSON.parse(str);
    } catch (e) {
        return {};
    }
}

// Instantiate App
window.addEventListener('DOMContentLoaded', () => {
    window.app = new AegisApp();
});
export default AegisApp;
