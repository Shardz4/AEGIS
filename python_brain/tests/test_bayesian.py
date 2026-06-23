import os
import sys
import pytest
import numpy as np
import msgpack
import time

# Ensure python_brain/src is in sys.path
src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from aegis.graph.equipment_graph import EquipmentGraph
from aegis.permits.permit_store import PermitStore
from aegis.risk.bayesian_net import RiskEngine
from aegis.risk.batch_processor import BatchProcessor

def test_bayesian_network_cpts_valid():
    """1. Verify that all CPTs are valid and sum to 1 per parent configuration."""
    engine = RiskEngine()
    model = engine.model
    
    # Check that pgmpy's internal structure validation passes
    assert model.check_model(), "pgmpy model structure validation failed"

    # Assert all columns sum to 1.0
    for cpd in model.get_cpds():
        # Values shape: (states_card, parent_card_1 * parent_card_2 * ...)
        # We sum along axis=0 (states)
        col_sums = cpd.values.sum(axis=0)
        assert np.allclose(col_sums, 1.0), f"CPD for variable {cpd.variable} does not sum to 1.0 in all columns"

def test_risk_engine_critical_conditions():
    """2. Verify that GasLevel=critical + HotWorkActive=yes -> risk_score > 75."""
    engine = RiskEngine()
    evidence = {
        "GasLevel": "critical",
        "HotWorkActive": "yes"
    }
    assessment = engine.compute_risk(zone_id=2, timestamp=time.time(), evidence=evidence)
    
    print(f"\n[Critical Case] Risk Score: {assessment.risk_score:.2f}%")
    print(f"[Critical Case] Probabilities: {assessment.incident_probability}")
    
    assert assessment.risk_score > 75.0, f"Expected risk_score > 75 under critical gas + hot work, got {assessment.risk_score:.2f}"
    assert assessment.recommendation_urgency == "IMMEDIATE_ACTION"

def test_risk_engine_all_normal():
    """3. Verify that all normal evidence -> risk_score < 20."""
    engine = RiskEngine()
    evidence = {
        "GasLevel": "low",
        "Temperature": "normal",
        "Pressure": "normal",
        "TTI_Urgency": "normal",
        "HotWorkActive": "no",
        "ConfinedSpace": "no",
        "WorkerCount": "none",
        "FatigueScore": "normal"
    }
    assessment = engine.compute_risk(zone_id=2, timestamp=time.time(), evidence=evidence)
    
    print(f"\n[Normal Case] Risk Score: {assessment.risk_score:.2f}%")
    print(f"[Normal Case] Probabilities: {assessment.incident_probability}")
    
    assert assessment.risk_score < 20.0, f"Expected risk_score < 20 under all normal conditions, got {assessment.risk_score:.2f}"
    assert assessment.recommendation_urgency == "MONITOR"

def test_equipment_graph_context():
    """4. Verify that equipment graph zone context returns correct equipment and sensors."""
    graph = EquipmentGraph()
    
    # Query Zone 2 context
    ctx = graph.get_zone_context(2)
    
    assert ctx["zone_id"] == 2
    assert ctx["zone_name"] == "Zone C - Reactor Area"
    
    # Zone 2 should contain 5 equipment pieces (EQ_10 to EQ_14)
    equipment = ctx["equipment"]
    assert len(equipment) == 5
    for eq in equipment:
        assert eq["equip_id"] in range(10, 15)
        assert "equip_type" in eq
        assert eq["status"] == "OPERATIONAL"

    # Zone 2 should contain sensors mapped to Zone 2
    sensors = ctx["sensors"]
    assert len(sensors) > 0
    for s in sensors:
        assert s["sensor_id"] % 8 == 2
        assert s["sensor_type"] == "Pressure"

class MockRingReader:
    def __init__(self):
        # We simulate SCADA telemetry events
        # Sensor 10 is Pressure sensor in Zone 2
        self.batches = [
            # Batch 1: normal SCADA events
            [
                {
                    "ts": time.time(),
                    "src": 0, # SCADA
                    "zone": 2,
                    "signal_id": 10,
                    "value": 1.5, # normal pressure
                    "meta": msgpack.packb({
                        "tti_seconds": 999.0,
                        "slope": 0.0,
                        "urgency": 0 # normal
                    })
                }
            ],
            # Batch 2: critical SCADA event in Zone 2
            [
                {
                    "ts": time.time(),
                    "src": 0, # SCADA
                    "zone": 2,
                    "signal_id": 10,
                    "value": 9.5, # critical pressure
                    "meta": msgpack.packb({
                        "tti_seconds": 15.0,
                        "slope": 0.8,
                        "urgency": 3 # critical
                    })
                }
            ]
        ]
        self.call_count = 0

    def read_batch(self):
        if self.call_count < len(self.batches):
            batch = self.batches[self.call_count]
            self.call_count += 1
            return batch
        return []

def test_batch_processor_loop():
    """5. Verify that BatchProcessor processes events, computes risks periodically, and produces alerts."""
    graph = EquipmentGraph()
    permit_store = PermitStore(graph)
    engine = RiskEngine()
    
    # We prepopulate Zone 2 with a HotWork permit, which is already done by PermitStore constructor
    active_permits = permit_store.get_active_for_zone(2)
    assert len(active_permits) > 0
    assert any(p.permit_type == "HotWork" for p in active_permits)

    mock_reader = MockRingReader()
    processor = BatchProcessor(
        ring_reader=mock_reader,
        risk_engine=engine,
        equipment_graph=graph,
        permit_store=permit_store
    )

    # Process events and run the loop for a short duration
    # Since mock_reader returns 2 batches, we can step through them manually or call processor.run()
    # Let's step manually first to check exact states
    
    # 1. Process normal batch
    processor.process_events()
    assert 2 in processor.latest_signals
    assert processor.latest_signals[2]["Pressure"] == 1.5
    assert processor.latest_tti[2]["Pressure"][2] == "normal"

    # Evaluate normal risk
    assessments_normal = processor.evaluate_risk()
    ra_zone2_normal = next(r for r in assessments_normal if r.zone_id == 2)
    print(f"\n[Batch Proc Normal Zone 2] Risk score: {ra_zone2_normal.risk_score:.2f}%")
    # Should not trigger alert
    assert len(processor.alert_queue) == 0

    # 2. Process critical batch
    processor.process_events()
    assert processor.latest_signals[2]["Pressure"] == 9.5
    assert processor.latest_tti[2]["Pressure"][2] == "critical"

    # Evaluate critical risk
    assessments_critical = processor.evaluate_risk()
    ra_zone2_crit = next(r for r in assessments_critical if r.zone_id == 2)
    print(f"[Batch Proc Critical Zone 2] Risk score: {ra_zone2_crit.risk_score:.2f}%")
    # Should be elevated due to critical pressure + active hot work
    assert ra_zone2_crit.risk_score > 60.0
    # Should have triggered at least one alert in the queue
    assert len(processor.alert_queue) > 0
    assert processor.alert_queue[-1].zone_id == 2
    assert processor.alert_queue[-1].recommendation_urgency == "IMMEDIATE_ACTION"

    # Now verify the .run() method behaves correctly when simulating a time-bounded loop
    mock_reader.call_count = 0  # reset call count
    processor.alert_queue.clear()
    
    # Run for 1.2 seconds (so it ticks evaluate_risk once)
    processor.run(duration_seconds=1.2)
    assert len(processor.alert_queue) > 0
