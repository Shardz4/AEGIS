import os
import json
import pytest
import numpy as np
from aegis.risk.bayesian_net import build_bayesian_network, RiskEngine
from aegis.risk.batch_processor import BatchProcessor
from aegis.risk.permit_store import PermitStore
from ring_buffer_py import RingBufferPy

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
    base_prob = res_base.incident_probability["critical"]
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
    # Setup dummy ring buffer file
    rb_path = "test_cctv_ring.dat"
    if os.path.exists(rb_path):
        os.remove(rb_path)
        
    try:
        # Create a tiny ring buffer
        rb = RingBufferPy(rb_path, 4096)
        
        # Initialize BatchProcessor
        bp = BatchProcessor(rb_path)
        
        # 1. Push a PPE Breach event (src=1, signal_id=1001, val=1.0)
        import msgpack
        meta_payload = msgpack.packb({"camera_id": "CAM-C-301", "confidence": 0.94, "violator_role": "Contractor"})
        
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
            bp.process_events()
            
            # Verify that the CCTV event is no longer active
            assert bp.latest_cctv_events[2]["PPEBreach"]["active"] is False
            
            # Verify evaluate_risk evidence reflects the resolution
            assessments_after = bp.evaluate_risk()
            zone_c_assessment_after = next(a for a in assessments_after if a.zone_id == 2)
            assert zone_c_assessment_after.raw_evidence["PPEBreachActive"] == "no"
            
        finally:
            if os.path.exists(override_file):
                os.remove(override_file)
                
    finally:
        if os.path.exists(rb_path):
            os.remove(rb_path)
