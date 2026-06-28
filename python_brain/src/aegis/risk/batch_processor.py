import time
import msgpack
import numpy as np
from aegis.ipc.reader import RingBufferReader
from aegis.graph.equipment_graph import EquipmentGraph
from aegis.permits.permit_store import PermitStore
from aegis.risk.bayesian_net import RiskEngine, RiskAssessment
from aegis.rag.corpus import get_mock_corpus
from aegis.rag.retriever import RegulatoryRetriever
from aegis.narrator.narrator import AlertNarrator
from aegis.fatigue.fatigue_monitor import FatigueMonitor

def map_gas_level(val: float) -> str:
    if val < 20.0: return "low"
    if val < 50.0: return "medium"
    if val < 80.0: return "high"
    return "critical"

def map_temp_level(val: float) -> str:
    if val < 50.0: return "normal"
    if val < 75.0: return "elevated"
    if val < 85.0: return "high"
    return "critical"

def map_press_level(val: float) -> str:
    if val < 4.0: return "normal"
    if val < 6.0: return "elevated"
    if val < 8.0: return "high"
    return "critical"

FACTOR_QUERY_MAP = {
    "GasLevel": "gas leak LEL monitoring",
    "HotWorkActive": "hot work permit",
    "ConfinedSpace": "confined space entry",
    "Temperature": "temperature high critical",
    "Pressure": "pressure high critical",
    "TTI_Urgency": "time to incident emergency",
    "WorkerCount": "workers exposed",
    "FatigueScore": "operator fatigue"
}

class BatchProcessor:
    def __init__(self, ring_reader: RingBufferReader, risk_engine: RiskEngine, 
                 equipment_graph: EquipmentGraph, permit_store: PermitStore):
        self.ring_reader = ring_reader
        self.risk_engine = risk_engine
        self.equipment_graph = equipment_graph
        self.permit_store = permit_store
        
        # State tracking
        self.latest_signals: dict[int, dict] = {}   # zone_id -> {sensor_type: val}
        self.latest_tti: dict[int, dict] = {}       # zone_id -> {sensor_type: (tti_seconds, slope, urgency_str)}
        self.latest_plumes: dict[int, dict] = {}    # zone_id -> plume_res_dict
        self.alert_queue: list[RiskAssessment] = []
        
        # Malfunction detection states
        self.zone_sensor_values: dict[int, dict[int, float]] = {}  # zone_id -> {sensor_id: val}
        self.sensor_tti: dict[int, tuple] = {}                     # sensor_id -> (tti, slope, urgency)
        self.malfunctioning_sensors: set[int] = set()

        # Sensor drift / calibration states
        self.cusum_high: dict[int, float] = {}
        self.cusum_low: dict[int, float] = {}
        self.sensor_calibration_state: dict[int, str] = {}

        # CCTV Vision Analytics state
        self.latest_cctv_events: dict[int, dict[str, dict]] = {}

        # RAG and Narrator initialization
        self.corpus = get_mock_corpus()
        self.retriever = RegulatoryRetriever(self.corpus)
        self.narrator = AlertNarrator(self.retriever)
        self.alert_history = []
        self.last_alert_time: dict[int, float] = {}  # zone_id -> timestamp of last LLM call

        # Fatigue monitor initialization
        self.fatigue_monitor = FatigueMonitor()

        # Wind state tracking
        self.current_wind_speed = 3.2
        self.current_wind_direction = 225.0

        # Telemetry updates buffer for dashboard HTTP POST bridge
        self.pending_updates = []

    def process_events(self):
        """Reads a batch of events from the ring buffer and updates local state."""
        batch = self.ring_reader.read_batch()
        
        # 1. Update state from the batch events
        for event in batch:
            src = event.get("src")
            zone_id = event.get("zone")
            signal_id = event.get("signal_id")
            val = event.get("value")
            meta = event.get("meta")

            if zone_id is None:
                continue

            if zone_id == 255:
                if signal_id == 900:
                    self.current_wind_speed = val
                elif signal_id == 901:
                    self.current_wind_direction = val
                
                # Queue wind update for dashboard
                self.pending_updates.append({
                    "type": "wind_update",
                    "wind_speed": self.current_wind_speed,
                    "wind_direction": self.current_wind_direction
                })
                continue

            # Ensure tracking dicts exist for this zone
            if zone_id not in self.latest_signals:
                self.latest_signals[zone_id] = {}
            if zone_id not in self.latest_tti:
                self.latest_tti[zone_id] = {}

            if src == 0:  # SCADA telemetry
                s_node = f"SENSOR_{signal_id}"
                if s_node in self.equipment_graph.g.nodes:
                    s_type = self.equipment_graph.g.nodes[s_node]["sensor_type"]
                    
                    if zone_id not in self.zone_sensor_values:
                        self.zone_sensor_values[zone_id] = {}
                    self.zone_sensor_values[zone_id][signal_id] = val

                    # Unpack TTI metadata
                    tti_secs = None
                    urgency_str = "normal"
                    if meta:
                        try:
                            tti_res = msgpack.unpackb(meta, raw=False)
                            tti_secs = tti_res.get("tti_seconds")
                            slope = tti_res.get("slope", 0.0)
                            urgency_code = tti_res.get("urgency", 0)
                            urgency_map = {0: "normal", 1: "watch", 2: "warning", 3: "critical"}
                            urgency_str = urgency_map.get(urgency_code, "normal")
                            
                            self.sensor_tti[signal_id] = (tti_secs, slope, urgency_str)
                            self.latest_tti[zone_id][s_type] = (tti_secs, slope, urgency_str)
                        except Exception as e:
                            print(f"Error decoding TTI metadata for sensor {signal_id}: {e}")

            elif src == 1:  # CCTV Vision Event
                if meta:
                    try:
                        import json
                        cctv_meta = {}
                        try:
                            cctv_meta = msgpack.unpackb(meta, raw=False)
                        except Exception:
                            meta_str = meta.decode('utf-8') if isinstance(meta, bytes) else meta
                            cctv_meta = json.loads(meta_str)
                            
                        event_type = "PPEBreach" if signal_id == 1001 else "VisualSmoke" if signal_id == 1002 else None
                        if event_type:
                            ZONE_CHARS_MAP = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
                            cam_id = cctv_meta.get("camera_id", f"CAM-{ZONE_CHARS_MAP[zone_id]}-{(signal_id%10)+1}")
                            conf = cctv_meta.get("confidence", 0.95)
                            role = cctv_meta.get("violator_role", "Contractor")
                            
                            if val > 0.0:
                                self.latest_cctv_events.setdefault(zone_id, {})[event_type] = {
                                    "active": True,
                                    "camera_id": cam_id,
                                    "confidence": conf,
                                    "violator_role": role
                                }
                                
                                # Generate and queue alert
                                cctv_alert_id = f"AL-CCTV-{ZONE_CHARS_MAP[zone_id]}-{signal_id}"
                                situation_desc = (
                                    f"PPE Violation detected by CCTV Analytics in Zone {ZONE_CHARS_MAP[zone_id]} (camera {cam_id}). "
                                    f"Worker role: {role}. Confidence: {conf*100:.1f}%."
                                ) if signal_id == 1001 else (
                                    f"Visual smoke/haze detected by CCTV Analytics in Zone {ZONE_CHARS_MAP[zone_id]} (camera {cam_id}). "
                                    f"Confidence: {conf*100:.1f}%."
                                )
                                
                                self.pending_updates.append({
                                    "type": "alert",
                                    "alert_id": cctv_alert_id,
                                    "timestamp": time.time(),
                                    "zone_id": zone_id,
                                    "risk_score": 65.0 if signal_id == 1001 else 85.0,
                                    "situation": situation_desc,
                                    "actions": [
                                        "Dispatch field supervisor to verify safety compliance." if signal_id == 1001 else "Deploy emergency deluge/water systems and check gas concentration.",
                                        "Acknowledge and dismiss alert once verified."
                                    ],
                                    "regulatory_citations": [
                                        {
                                            "source": "OSHA 1910.132",
                                            "section": "General requirements for PPE",
                                            "similarity_score": 0.98,
                                            "relevance": "Protective equipment, including personal protective equipment for eyes, face, head, and extremities, shall be provided, used, and maintained in a sanitary and reliable condition."
                                        }
                                    ] if signal_id == 1001 else [
                                        {
                                            "source": "NFPA 72",
                                            "section": "National Fire Alarm and Signaling Code",
                                            "similarity_score": 0.95,
                                            "relevance": "Visual flame or smoke detection systems shall be installed in accordance with manufacturer specifications and shall supplement thermal/gas detection sensors."
                                        }
                                    ],
                                    "urgency": "warning" if signal_id == 1001 else "critical",
                                    "abstention_notes": [],
                                    "is_cctv_alert": True,
                                    "sensor_id": signal_id
                                })
                            else:
                                if zone_id in self.latest_cctv_events and event_type in self.latest_cctv_events[zone_id]:
                                    self.latest_cctv_events[zone_id][event_type]["active"] = False
                                    
                            self.pending_updates.append({
                                "type": "cctv_update",
                                "zone_id": zone_id,
                                "signal_id": signal_id,
                                "value": val,
                                "active": val > 0.0,
                                "camera_id": cam_id,
                                "confidence": conf if val > 0.0 else 0.0,
                                "violator_role": role if val > 0.0 else ""
                            })
                    except Exception as e:
                        print(f"Error decoding CCTV metadata in zone {zone_id}: {e}")

            elif src == 4:  # PLUME consequence event
                if meta:
                    try:
                        plume_res = msgpack.unpackb(meta, raw=False)
                        self.latest_plumes[zone_id] = plume_res
                        
                        # Queue plume update for dashboard
                        self.pending_updates.append({
                            "type": "plume_update",
                            "zone_id": zone_id,
                            "hazard_radius_m": plume_res.get("hazard_radius_m", 0.0),
                            "gas_name": plume_res.get("gas_name", "Hydrocarbon"),
                            "leak_rate_kgs": plume_res.get("leak_rate_kgs", 0.0)
                        })
                    except Exception as e:
                        print(f"Error decoding Plume metadata in zone {zone_id}: {e}")

        # 2. Detect malfunctioning sensors
        self.detect_malfunctions()

        # 3. Detect sensor drift
        self.detect_sensor_drift()

        # 4. Queue sensor updates with malfunctioning and calibration status
        for event in batch:
            src = event.get("src")
            zone_id = event.get("zone")
            signal_id = event.get("signal_id")
            val = event.get("value")

            if zone_id is None or zone_id == 255:
                continue

            if src == 0:
                tti_secs = None
                urgency_str = "normal"
                if signal_id in self.sensor_tti:
                    tti_secs, _, urgency_str = self.sensor_tti[signal_id]

                self.pending_updates.append({
                    "type": "sensor_update",
                    "signal_id": signal_id,
                    "zone_id": zone_id,
                    "value": val,
                    "tti_seconds": tti_secs,
                    "urgency": urgency_str,
                    "malfunctioning": signal_id in self.malfunctioning_sensors,
                    "calibration_state": self.sensor_calibration_state.get(signal_id, 'NOMINAL')
                })

    def detect_malfunctions(self):
        """Perform spatial outlier detection and voting across all zones."""
        BASELINES = {
            "GasConcentration": 5.0,
            "Temperature": 25.0,
            "Pressure": 1.5,
            "FlowRate": 100.0,
            "Vibration": 2.0,
            "PH": 7.0,
            "Level": 50.0,
            "Humidity": 45.0
        }

        self.malfunctioning_sensors = set()

        for zone_id, sensors_dict in self.zone_sensor_values.items():
            if not sensors_dict or len(sensors_dict) < 3:
                continue
            
            # Resolve sensor type from first sensor in zone
            first_s_id = next(iter(sensors_dict.keys()))
            first_s_node = f"SENSOR_{first_s_id}"
            if first_s_node not in self.equipment_graph.g.nodes:
                continue
            s_type = self.equipment_graph.g.nodes[first_s_node]["sensor_type"]
            baseline = BASELINES.get(s_type, 1.0)
            dev_floor = 0.1 * baseline

            # Median / MAD
            vals = list(sensors_dict.values())
            median_val = np.median(vals)
            abs_deviations = [abs(v - median_val) for v in vals]
            mad = np.median(abs_deviations)

            outliers = []
            for s_id, v in sensors_dict.items():
                dev = abs(v - median_val)
                if dev > max(3.5 * mad, dev_floor):
                    outliers.append(s_id)

            # Spatial Voting: only classify as malfunction if 2 or fewer sensors deviate
            if len(outliers) <= 2:
                self.malfunctioning_sensors.update(outliers)

    def detect_sensor_drift(self):
        """Perform CUSUM drift detection across all active sensors."""
        BASELINES = {
            "GasConcentration": 5.0,
            "Temperature": 25.0,
            "Pressure": 1.5,
            "FlowRate": 100.0,
            "Vibration": 2.0,
            "PH": 7.0,
            "Level": 50.0,
            "Humidity": 45.0
        }

        # Noise standard deviations per sensor type
        STD_DEVS = {
            "GasConcentration": 0.5,
            "Temperature": 1.0,
            "Pressure": 0.1,
            "FlowRate": 2.0,
            "Vibration": 0.1,
            "PH": 0.2,
            "Level": 1.0,
            "Humidity": 1.0
        }

        for zone_id, sensors_dict in self.zone_sensor_values.items():
            for s_id, val in sensors_dict.items():
                if s_id in self.malfunctioning_sensors:
                    continue

                s_node = f"SENSOR_{s_id}"
                if s_node not in self.equipment_graph.g.nodes:
                    continue
                s_type = self.equipment_graph.g.nodes[s_node]["sensor_type"]
                baseline = BASELINES.get(s_type, 1.0)
                std_dev = STD_DEVS.get(s_type, 1.0)

                # Initialize CUSUM statistics if not present
                if s_id not in self.cusum_high:
                    self.cusum_high[s_id] = 0.0
                if s_id not in self.cusum_low:
                    self.cusum_low[s_id] = 0.0

                # CUSUM parameters: K = 0.5 * std_dev, H = 4.0 * std_dev
                K = 0.5 * std_dev
                H = 4.0 * std_dev

                # Update CUSUM accumulators
                self.cusum_high[s_id] = max(0.0, self.cusum_high[s_id] + val - (baseline + K))
                self.cusum_low[s_id] = max(0.0, self.cusum_low[s_id] + (baseline - K) - val)

                # Trigger drifting status if threshold breached
                if self.cusum_high[s_id] > H or self.cusum_low[s_id] > H:
                    if self.sensor_calibration_state.get(s_id) != 'CALIBRATING':
                        self.sensor_calibration_state[s_id] = 'DRIFTING'
                else:
                    if self.sensor_calibration_state.get(s_id) == 'DRIFTING':
                        self.sensor_calibration_state[s_id] = 'NOMINAL'

                # Transition CALIBRATING -> NOMINAL when value returns close to baseline
                if self.sensor_calibration_state.get(s_id) == 'CALIBRATING':
                    if abs(val - baseline) <= 2.0 * std_dev:
                        self.sensor_calibration_state[s_id] = 'NOMINAL'

    def recalibrate_sensor(self, s_id: int):
        """Trigger calibration for a sensor, resetting CUSUM stats."""
        self.cusum_high[s_id] = 0.0
        self.cusum_low[s_id] = 0.0
        self.sensor_calibration_state[s_id] = 'CALIBRATING'

    def evaluate_risk(self) -> list[RiskAssessment]:
        """Compute the Bayesian Risk Assessment for all 8 zones."""
        BASELINES = {
            "GasConcentration": 5.0,
            "Temperature": 25.0,
            "Pressure": 1.5,
            "FlowRate": 100.0,
            "Vibration": 2.0,
            "PH": 7.0,
            "Level": 50.0,
            "Humidity": 45.0
        }

        # Update representative signals for risk calculation
        for zone_id in range(8):
            sensors_dict = self.zone_sensor_values.get(zone_id, {})
            s_type = None
            if sensors_dict:
                for s_id in sensors_dict:
                    s_node = f"SENSOR_{s_id}"
                    if s_node in self.equipment_graph.g.nodes:
                        s_type = self.equipment_graph.g.nodes[s_node]["sensor_type"]
                        break

            if s_type:
                active_vals = [v for s_id, v in sensors_dict.items() if s_id not in self.malfunctioning_sensors]
                if active_vals:
                    rep_val = np.median(active_vals)
                else:
                    all_vals = list(sensors_dict.values())
                    rep_val = np.median(all_vals) if all_vals else BASELINES.get(s_type, 1.0)
                
                if zone_id not in self.latest_signals:
                    self.latest_signals[zone_id] = {}
                self.latest_signals[zone_id][s_type] = rep_val

        assessments = []
        now = time.time()

        # Step A: Precompute all evidences and active plume zones to build global context
        zone_evidences = {}
        zone_permits = {}
        zone_workers = {}
        zone_fatigues = {}
        all_plumes = {}

        for zone_id in range(8):
            evidence = {}
            
            # SCADA readings
            zone_signals = self.latest_signals.get(zone_id, {})
            if "GasConcentration" in zone_signals:
                evidence["GasLevel"] = map_gas_level(zone_signals["GasConcentration"])
            if "Temperature" in zone_signals:
                evidence["Temperature"] = map_temp_level(zone_signals["Temperature"])
            if "Pressure" in zone_signals:
                evidence["Pressure"] = map_press_level(zone_signals["Pressure"])

            # TTI Urgency (ignoring malfunctioning sensors)
            max_urgency = "normal"
            max_tti_val = None
            urgency_levels = {"normal": 0, "watch": 1, "warning": 2, "critical": 3}
            
            sensors_dict = self.zone_sensor_values.get(zone_id, {})
            for s_id in sensors_dict.keys():
                if s_id in self.malfunctioning_sensors:
                    continue
                if s_id in self.sensor_tti:
                    tti_secs, _, urg_str = self.sensor_tti[s_id]
                    if urgency_levels.get(urg_str, 0) > urgency_levels.get(max_urgency, 0):
                        max_urgency = urg_str
                        max_tti_val = tti_secs

            evidence["TTI_Urgency"] = max_urgency
            evidence["_tti_seconds"] = max_tti_val
            evidence["EquipAge"] = "mid"

            # Permits & Workers
            active_permits = self.permit_store.get_active_for_zone(zone_id)
            has_hotwork = any(p.permit_type == "HotWork" for p in active_permits)
            has_confined = any(p.permit_type == "ConfinedSpace" for p in active_permits)
            total_workers = sum(p.worker_count for p in active_permits)

            evidence["HotWorkActive"] = "yes" if has_hotwork else "no"
            evidence["ConfinedSpace"] = "yes" if has_confined else "no"
            
            if total_workers == 0:
                evidence["WorkerCount"] = "none"
            elif total_workers <= 4:
                evidence["WorkerCount"] = "few"
            else:
                evidence["WorkerCount"] = "many"

            evidence["_affected_workers"] = total_workers

            # Plume Consequence
            plume = self.latest_plumes.get(zone_id)
            if plume:
                evidence["_plume_radius_m"] = plume.get("hazard_radius_m")
                affected_zones = plume.get("affected_zones", [])
                plume_ctx = self.equipment_graph.get_affected_by_plume(affected_zones)
                evidence["_affected_workers"] += plume_ctx["total_workers_at_risk"]
                all_plumes[zone_id] = plume

            # Fatigue Score
            zone_fatigue = self.fatigue_monitor.get_zone_fatigue(zone_id)
            evidence["FatigueScore"] = zone_fatigue.fatigue_level
            evidence["_max_fatigue"] = zone_fatigue.max_fatigue_score

            # CCTV Vision evidence
            ppe_breached = "no"
            smoke_detected = "no"
            cctv_state = self.latest_cctv_events.get(zone_id, {})
            if cctv_state.get("PPEBreach", {}).get("active", False):
                ppe_breached = "yes"
            if cctv_state.get("VisualSmoke", {}).get("active", False):
                smoke_detected = "yes"
                
            evidence["PPEBreachActive"] = ppe_breached
            evidence["VisualSmoke"] = smoke_detected
            evidence["_avg_fatigue"] = zone_fatigue.avg_fatigue_score
            evidence["_most_fatigued_operator"] = zone_fatigue.most_fatigued_operator

            zone_evidences[zone_id] = evidence
            zone_permits[zone_id] = active_permits
            zone_workers[zone_id] = total_workers
            zone_fatigues[zone_id] = zone_fatigue

        # Step B: Calculate risk assessments for all zones using pre-assembled evidence
        zone_risk_metrics = {}
        for zone_id in range(8):
            assessment = self.risk_engine.compute_risk(zone_id, now, zone_evidences[zone_id])
            assessments.append(assessment)
            zone_risk_metrics[zone_id] = assessment.risk_score

        # Collect all plume zones dynamically
        plume_zones = []
        for p_res in all_plumes.values():
            affected = p_res.get("affected_zones", [])
            plume_zones.extend(affected)
        plume_zones = list(set(plume_zones))

        # Collect blocked zones (risk score >= 70 or plume is active)
        blocked_zones = [z for z in range(8) if zone_risk_metrics.get(z, 0.0) >= 70.0 or z in plume_zones]

        # Step C: Queue updates and perform pathfinding (Plan 1)
        for assessment in assessments:
            zone_id = assessment.zone_id
            active_permits = zone_permits[zone_id]
            total_workers = zone_workers[zone_id]
            zone_fatigue = zone_fatigues[zone_id]

            # Safe evacuation routing:
            # Calculate path if there are active workers AND (risk is elevated OR zone in plume) AND start is not Zone 4
            evac_path = None
            if total_workers > 0 and (assessment.risk_score >= 40.0 or zone_id in plume_zones) and zone_id != 4:
                evac_path = self.equipment_graph.find_safe_evacuation_path(
                    start_zone_id=zone_id,
                    target_zone_id=4,
                    zone_risk_metrics=zone_risk_metrics,
                    plume_zones=plume_zones
                )

            # Queue zone update for dashboard
            self.pending_updates.append({
                "type": "zone_update",
                "zone_id": zone_id,
                "risk_score": assessment.risk_score,
                "risk_level": assessment.recommendation_urgency.lower(),
                "active_permits": [p.permit_type for p in active_permits],
                "worker_count": total_workers,
                "fatigue_level": zone_fatigue.fatigue_level,
                "evac_path": evac_path,
                "blocked_zones": blocked_zones
            })
            
            # Queue fatigue update for dashboard
            self.pending_updates.append({
                "type": "fatigue_update",
                "zone_id": zone_id,
                "max_fatigue": zone_fatigue.max_fatigue_score,
                "avg_fatigue": zone_fatigue.avg_fatigue_score,
                "worker_count": zone_fatigue.worker_count
            })

            # If risk is critical or warning, add to alert queue
            if assessment.risk_score > 60.0:
                self.alert_queue.append(assessment)

                # Rate-limiting check: max 1 call per zone per 30 seconds
                last_alert = self.last_alert_time.get(zone_id, 0.0)
                if now - last_alert >= 30.0:
                    self.last_alert_time[zone_id] = now
                    
                    zones_info = {
                        0: "Zone A - Tank Farm",
                        1: "Zone B - Compressor Hall",
                        2: "Zone C - Reactor Area",
                        3: "Zone D - Pipe Rack",
                        4: "Zone E - Control Room",
                        5: "Zone F - Loading Bay",
                        6: "Zone G - Utilities",
                        7: "Zone H - Flare Stack",
                    }
                    zone_name = zones_info.get(zone_id, f"Zone {zone_id}")
                    
                    # Extract hazard factors from contributing factors and expand them to descriptive terms
                    factors = []
                    for factor_str in assessment.contributing_factors:
                        parts = factor_str.split(":")
                        if parts:
                            name = parts[0].strip()
                            factors.append(FACTOR_QUERY_MAP.get(name, name))
                    
                    # Include permit details in the query context
                    active_permits = self.permit_store.get_active_for_zone(zone_id)
                    permit_types = [FACTOR_QUERY_MAP.get(p.permit_type, p.permit_type) for p in active_permits]
                    
                    query_terms = list(set(factors + permit_types))
                    query = f"{' '.join(query_terms)} in {zone_name}"
                    
                    # Retrieve relevant docs
                    retrieved = self.retriever.retrieve(query)
                    
                    # Generate operator alert narrative
                    try:
                        operator_alert = self.narrator.generate_alert(assessment, retrieved)
                        self.alert_history.append(operator_alert)
                        
                        # Queue alert update for dashboard
                        self.pending_updates.append({
                            "type": "alert",
                            "alert_id": operator_alert.alert_id,
                            "timestamp": operator_alert.timestamp,
                            "zone_id": operator_alert.zone_id,
                            "risk_score": operator_alert.risk_score,
                            "active_permits": [p.permit_id for p in self.permit_store.get_active_for_zone(operator_alert.zone_id)],
                            "situation": operator_alert.situation,
                            "actions": operator_alert.actions,
                            "regulatory_citations": [
                                {
                                    "source": c.source,
                                    "section": c.section,
                                    "similarity_score": c.similarity_score,
                                    "relevance": c.relevance
                                } for c in operator_alert.regulatory_citations
                            ],
                            "urgency": operator_alert.urgency,
                            "abstention_notes": operator_alert.abstention_notes
                        })
                        
                        # Print formatted alert to console
                        print("\n" + "!" * 80)
                        print(f"!!! AEGIS safety alert trigger: {operator_alert.alert_id} !!!".center(80))
                        print(f"Location: {zone_name} (Zone {zone_id}) | Risk Score: {operator_alert.risk_score:.1f}% ({assessment.recommendation_urgency})".center(80))
                        print(f"Urgency Statement: {operator_alert.urgency}".center(80))
                        print("!" * 80)
                        print(f"SITUATION SUMMARY:\n{operator_alert.situation}")
                        print("-" * 80)
                        print("PRIORITIZED ACTION ITEMS:")
                        for i, action in enumerate(operator_alert.actions, 1):
                            print(f"  {i}. {action}")
                        print("-" * 80)
                        print("REGULATORY BASES & COMPLIANCE CITATIONS:")
                        if operator_alert.regulatory_citations:
                            for c in operator_alert.regulatory_citations:
                                print(f"  - [{c.source} - {c.section}] (Similarity: {c.similarity_score:.3f})")
                                print(f"    Relevance: {c.relevance}")
                        else:
                            print("  No regulatory reference available for this condition.")
                        if operator_alert.abstention_notes:
                            print("-" * 80)
                            print("RAG ABSTENTION / HALLUCINATION SAFETY FLAGS:")
                            for note in operator_alert.abstention_notes:
                                print(f"  - {note}")
                        print("=" * 80 + "\n")
                    except Exception as e:
                        print(f"Error executing LLM Alert Narrator for Zone {zone_id}: {e}")

        # Queue malfunctions update
        self.pending_updates.append({
            "type": "malfunctions_update",
            "malfunctioning_sensors": list(self.malfunctioning_sensors)
        })

        # Flush all queued updates to dashboard
        if self.pending_updates:
            self.flush_dashboard_updates()

        return assessments

    def flush_dashboard_updates(self):
        """Send all queued dashboard updates in a single HTTP POST request to server.py."""
        import urllib.request
        import json
        try:
            data = json.dumps(self.pending_updates).encode('utf-8')
            req = urllib.request.Request(
                "http://localhost:8080/api/update",
                data=data,
                headers={'Content-Type': 'application/json'}
            )
            # 200ms timeout to avoid blocking SCADA loop
            with urllib.request.urlopen(req, timeout=0.2) as f:
                pass
        except Exception:
            # Quietly ignore if dashboard server is down
            pass
        finally:
            self.pending_updates = []

    def run(self, duration_seconds: float = 60.0):
        start = time.time()
        last_eval = time.time()
        last_permit_tick = time.time()

        print("Python BatchProcessor started. Monitoring ring buffer...")
        print("---------------------------------------------------------")

        while time.time() - start < duration_seconds:
            # 1. Process new events from shared memory
            try:
                self.process_events()
            except Exception as e:
                print(f"Error processing ring buffer events: {e}")

            # Check for control overrides (permit cancellations and sensor recalibrations)
            try:
                import os
                import json
                if os.path.exists("control_override.json"):
                    with open("control_override.json", "r", encoding="utf-8") as f:
                        content = f.read().strip()
                        if content:
                            override_data = json.loads(content)
                            
                            # 1. Permit cancellations
                            cancelled = override_data.get("cancelled_permits", [])
                            for p_id in cancelled:
                                if p_id in self.permit_store.active_permits:
                                    permit = self.permit_store.active_permits[p_id]
                                    if permit.status == "ACTIVE":
                                        print(f"Applying control override: Revoking permit {p_id}")
                                        self.permit_store.revoke_permit(p_id)
                                        
                            # 2. Sensor recalibrations
                            recalibrated = override_data.get("recalibrated_sensors", [])
                            for s_id in recalibrated:
                                try:
                                    s_id = int(s_id)
                                    if self.sensor_calibration_state.get(s_id) not in ('CALIBRATING', 'NOMINAL'):
                                        print(f"Applying control override: Recalibrating sensor {s_id}")
                                        self.recalibrate_sensor(s_id)
                                except ValueError:
                                    pass

                            # 3. CCTV acknowledgements
                            acked_cctv = override_data.get("acked_cctv_events", [])
                            for event_key in acked_cctv:
                                try:
                                    z_id, sig_id = map(int, event_key.split(":"))
                                    event_type = "PPEBreach" if sig_id == 1001 else "VisualSmoke" if sig_id == 1002 else None
                                    if event_type and z_id in self.latest_cctv_events and event_type in self.latest_cctv_events[z_id]:
                                        if self.latest_cctv_events[z_id][event_type].get("active", False):
                                            print(f"Applying control override: Acknowledging and clearing CCTV {event_type} in Zone {z_id}")
                                            self.latest_cctv_events[z_id][event_type]["active"] = False
                                            
                                            self.pending_updates.append({
                                                "type": "cctv_update",
                                                "zone_id": z_id,
                                                "signal_id": sig_id,
                                                "value": 0.0,
                                                "active": False,
                                                "camera_id": self.latest_cctv_events[z_id][event_type].get("camera_id", ""),
                                                "confidence": 0.0,
                                                "violator_role": ""
                                            })
                                except Exception:
                                    pass
            except Exception as e:
                print(f"Error reading control overrides: {e}")

            now = time.time()

            # 2. Every 1 second, run risk assessments
            if now - last_eval >= 1.0:
                last_eval = now
                assessments = self.evaluate_risk()

                 # Print dashboard table to stdout
                print("\033[H\033[J", end="") # Clean console screen
                print("================================ AEGIS REASONING BRAIN ================================")
                print(f"Active Permits: {len(self.permit_store.active_permits)}")
                print("---------------------------------------------------------------------------------------")
                print(f"{'ZONE':<8} | {'INCIDENT PROBABILITY':<25} | {'RISK SCORE':<10} | {'URGENCY':<16} | {'FATIGUE':<10}")
                print("---------------------------------------------------------------------------------------")
                
                for ra in assessments:
                    zone_name = f"ZONE {ra.zone_id}"
                    # Format probability distribution
                    prob_str = f"{ra.max_probability_state} ({ra.max_probability_value*100:.1f}%)"
                    fatigue_level = ra.raw_evidence.get("FatigueScore", "normal")
                    print(f"{zone_name:<8} | {prob_str:<25} | {ra.risk_score:<10.1f} | {ra.recommendation_urgency:<16} | {fatigue_level:<10}")
                print("=======================================================================================")

            # 3. Every 10 seconds, tick permit store (expire old permits) and fatigue monitor
            if now - last_permit_tick >= 10.0:
                last_permit_tick = now
                self.permit_store.tick()
                self.fatigue_monitor.tick()

            time.sleep(0.01)
