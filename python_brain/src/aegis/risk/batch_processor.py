import time
import msgpack
from aegis.ipc.reader import RingBufferReader
from aegis.graph.equipment_graph import EquipmentGraph
from aegis.permits.permit_store import PermitStore
from aegis.risk.bayesian_net import RiskEngine, RiskAssessment

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

    def process_events(self):
        """Reads a batch of events from the ring buffer and updates local state."""
        batch = self.ring_reader.read_batch()
        for event in batch:
            src = event.get("src")
            zone_id = event.get("zone")
            signal_id = event.get("signal_id")
            val = event.get("value")
            meta = event.get("meta")

            if zone_id is None:
                continue

            # Ensure tracking dicts exist for this zone
            if zone_id not in self.latest_signals:
                self.latest_signals[zone_id] = {}
            if zone_id not in self.latest_tti:
                self.latest_tti[zone_id] = {}

            if src == 0:  # SCADA telemetry with TTI annotation
                # Get sensor info from equipment graph to resolve type
                s_node = f"SENSOR_{signal_id}"
                if s_node in self.equipment_graph.g.nodes:
                    s_type = self.equipment_graph.g.nodes[s_node]["sensor_type"]
                    self.latest_signals[zone_id][s_type] = val

                    # Unpack TTI metadata
                    if meta:
                        try:
                            tti_res = msgpack.unpackb(meta, raw=False)
                            # tti_res = {tti_seconds, slope, r_squared, urgency, ...}
                            tti_secs = tti_res.get("tti_seconds")
                            slope = tti_res.get("slope", 0.0)
                            urgency_code = tti_res.get("urgency", 0)
                            
                            urgency_map = {0: "normal", 1: "watch", 2: "warning", 3: "critical"}
                            urgency_str = urgency_map.get(urgency_code, "normal")
                            
                            self.latest_tti[zone_id][s_type] = (tti_secs, slope, urgency_str)
                        except Exception as e:
                            print(f"Error decoding TTI metadata for sensor {signal_id}: {e}")

            elif src == 4:  # PLUME consequence event
                if meta:
                    try:
                        plume_res = msgpack.unpackb(meta, raw=False)
                        self.latest_plumes[zone_id] = plume_res
                    except Exception as e:
                        print(f"Error decoding Plume metadata in zone {zone_id}: {e}")

    def evaluate_risk(self) -> list[RiskAssessment]:
        """Compute the Bayesian Risk Assessment for all 8 zones."""
        assessments = []
        now = time.time()

        for zone_id in range(8):
            # 1. Build evidence dictionary
            evidence = {}
            
            # SCADA readings
            zone_signals = self.latest_signals.get(zone_id, {})
            if "GasConcentration" in zone_signals:
                evidence["GasLevel"] = map_gas_level(zone_signals["GasConcentration"])
            if "Temperature" in zone_signals:
                evidence["Temperature"] = map_temp_level(zone_signals["Temperature"])
            if "Pressure" in zone_signals:
                evidence["Pressure"] = map_press_level(zone_signals["Pressure"])

            # TTI Urgency
            zone_ttis = self.latest_tti.get(zone_id, {})
            max_urgency = "normal"
            max_tti_val = None
            
            # Map TTI urgency to highest active state across all sensors in this zone
            urgency_levels = {"normal": 0, "watch": 1, "warning": 2, "critical": 3}
            for s_type, (tti_secs, _, urg_str) in zone_ttis.items():
                if urgency_levels.get(urg_str, 0) > urgency_levels.get(max_urgency, 0):
                    max_urgency = urg_str
                    max_tti_val = tti_secs

            evidence["TTI_Urgency"] = max_urgency
            evidence["_tti_seconds"] = max_tti_val

            # Equipment Age (Mocked from graph: get age of oldest equipment in zone)
            # For simplicity, default to mid
            evidence["EquipAge"] = "mid"

            # Permits
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
                # If plume overlaps with other zones, we add the workers in those zones to risk
                affected_zones = plume.get("affected_zones", [])
                plume_ctx = self.equipment_graph.get_affected_by_plume(affected_zones)
                evidence["_affected_workers"] += plume_ctx["total_workers_at_risk"]

            # Fatigue Score (Default to normal for now)
            evidence["FatigueScore"] = "normal"

            # Compute risk
            assessment = self.risk_engine.compute_risk(zone_id, now, evidence)
            assessments.append(assessment)

            # If risk is critical or warning, add to alert queue
            if assessment.risk_score > 60.0:
                self.alert_queue.append(assessment)

        return assessments

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

            now = time.time()

            # 2. Every 1 second, run risk assessments
            if now - last_eval >= 1.0:
                last_eval = now
                assessments = self.evaluate_risk()

                # Print dashboard table to stdout
                print("\033[H\033[J", end="") # Clean console screen
                print("================== AEGIS REASONING BRAIN ==================")
                print(f"Active Permits: {len(self.permit_store.active_permits)}")
                print("-----------------------------------------------------------")
                print(f"{'ZONE':<8} | {'INCIDENT PROBABILITY':<25} | {'RISK SCORE':<10} | {'URGENCY':<12}")
                print("-----------------------------------------------------------")
                
                for ra in assessments:
                    zone_name = f"ZONE {ra.zone_id}"
                    # Format probability distribution
                    prob_str = f"{ra.max_probability_state} ({ra.max_probability_value*100:.1f}%)"
                    print(f"{zone_name:<8} | {prob_str:<25} | {ra.risk_score:<10.1f} | {ra.recommendation_urgency:<12}")
                print("===========================================================")

            # 3. Every 10 seconds, tick permit store (expire old permits)
            if now - last_permit_tick >= 10.0:
                last_permit_tick = now
                self.permit_store.tick()

            time.sleep(0.01)
