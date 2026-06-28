import os
import sys
import json
import struct
import pytest
import numpy as np

# Ensure python_brain/src is in sys.path
src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from aegis.risk.bayesian_net import build_bayesian_network, RiskEngine
from aegis.risk.batch_processor import BatchProcessor
from aegis.permits.permit_store import PermitStore
from aegis.graph.equipment_graph import EquipmentGraph
from aegis.ipc.reader import RingBufferReader
import msgpack

class MockRingBuffer:
    def __init__(self, path, capacity=4096):
        self.path = os.path.abspath(path)
        self.capacity = capacity
        # Initialize file with SCADA Ring Buffer Header
        # 64-byte header: write_pos(0), read_pos(0), capacity(data_cap), event_count(0)
        data_cap = capacity - 64
        with open(self.path, "wb") as f:
            header = struct.pack("<QQQQ", 0, 0, data_cap, 0) + b"\x00" * 32
            f.write(header + b"\x00" * data_cap)
            
    def push_event(self, ts, src, zone, signal_id, value, meta=b""):
        payload = msgpack.packb([ts, src, zone, signal_id, value, meta])
        length = len(payload)
        
        with open(self.path, "r+b") as f:
            header = f.read(64)
            write_pos, read_pos, data_cap, event_count = struct.unpack("<QQQQ", header[:32])
            
            len_bytes = struct.pack("<I", length)
            
            curr_pos = write_pos
            for byte in len_bytes + payload:
                offset = curr_pos % data_cap
                f.seek(64 + offset)
                f.write(bytes([byte]))
                curr_pos += 1
                
            # Update header
            f.seek(0)
            f.write(struct.pack("<QQQQ", curr_pos, read_pos, data_cap, event_count + 1) + b"\x00" * 32)


def test_bayesian_network_cctv_nodes():
    """Verify that the BN compiles and propagates CCTV risk factors correctly."""
    engine = RiskEngine()
    
    # 1. Base case: normal SCADA parameters, no CCTV breach
    evidence_base = {
        "GasLevel": "low",
        "Temperature": "normal",
        "Pressure": "normal",
        "TTI_Urgency": "normal",
        "EquipAge": "new",
        "HotWorkActive": "no",
        "ConfinedSpace": "no",
        "WorkerCount": "none",
        "FatigueScore": "normal",
        "PPEBreachActive": "no",
        "VisualSmoke": "no"
    }
    res_base = engine.compute_risk(zone_id=2, timestamp=100.0, evidence=evidence_base)
    base_score = res_base.risk_score
    
    # 2. Case with PPE Breach active
    evidence_ppe = evidence_base.copy()
    evidence_ppe["PPEBreachActive"] = "yes"
    res_ppe = engine.compute_risk(zone_id=2, timestamp=100.0, evidence=evidence_ppe)
    ppe_score = res_ppe.risk_score
    
    # 3. Case with Visual Smoke active
    evidence_smoke = evidence_base.copy()
    evidence_smoke["VisualSmoke"] = "yes"
    res_smoke = engine.compute_risk(zone_id=2, timestamp=100.0, evidence=evidence_smoke)
    smoke_score = res_smoke.risk_score

    # Check risk score propagation: active breaches should significantly elevate risk scores
    assert ppe_score > base_score, "PPE breach should elevate risk score"
    assert smoke_score > base_score, "Visual smoke detection should elevate risk score"
    assert smoke_score > ppe_score, "Visual smoke represents a higher direct process threat than PPE breach"


def test_batch_processor_cctv_ingestion():
    """Verify that BatchProcessor processes CCTV telemetry events and triggers overrides."""
    rb_path = "test_cctv_ring.dat"
    if os.path.exists(rb_path):
        try:
            os.remove(rb_path)
        except Exception:
            pass
        
    try:
        # Create mock ring buffer
        rb = MockRingBuffer(rb_path, 4096)
        
        # Initialize BatchProcessor
        graph = EquipmentGraph()
        permit_store = PermitStore(graph)
        engine = RiskEngine()
        reader = RingBufferReader(rb_path)
        
        bp = BatchProcessor(
            ring_reader=reader,
            risk_engine=engine,
            equipment_graph=graph,
            permit_store=permit_store
        )
        
        # 1. Push a PPE Breach event
        meta_payload = json.dumps({"camera_id": "CAM-C-301", "confidence": 0.94, "violator_role": "Contractor"}).encode('utf-8')
        rb.push_event(
            ts=1000,
            src=1, # CCTV
            zone=2, # Zone C
            signal_id=1001, # PPE Breach
            value=1.0,
            meta=meta_payload
        )
        
        # Process the batch
        bp.process_events()
        
        # Verify that CCTV breach is cached as active
        cctv_events = bp.latest_cctv_events.get(2, {})
        assert cctv_events.get("PPEBreach", {}).get("active") is True
        assert cctv_events["PPEBreach"]["camera_id"] == "CAM-C-301"
        assert cctv_events["PPEBreach"]["violator_role"] == "Contractor"
        
        # 2. Verify that evaluate_risk propagates the PPE Breach to the evidence dict
        assessments = bp.evaluate_risk()
        zone_c_assessment = next(a for a in assessments if a.zone_id == 2)
        assert zone_c_assessment.raw_evidence["PPEBreachActive"] == "yes"
        
        # 3. Simulate resolving the event via control_override.json
        override_file = "control_override.json"
        with open(override_file, "w", encoding="utf-8") as f:
            json.dump({"acked_cctv_events": ["2:1001"]}, f)
            
        try:
            # Run one process loop tick
            bp.run(duration_seconds=0.05)
            
            # Verify that the CCTV event is no longer active
            assert bp.latest_cctv_events[2]["PPEBreach"]["active"] is False
            
            # Verify evaluate_risk evidence reflects the resolution
            assessments_after = bp.evaluate_risk()
            zone_c_assessment_after = next(a for a in assessments_after if a.zone_id == 2)
            assert zone_c_assessment_after.raw_evidence["PPEBreachActive"] == "no"
            
        finally:
            if os.path.exists(override_file):
                os.remove(override_file)
                
            # Close the reader so we can delete the file cleanly
            reader.close()
                
    finally:
        if os.path.exists(rb_path):
            try:
                os.remove(rb_path)
            except Exception:
                pass
