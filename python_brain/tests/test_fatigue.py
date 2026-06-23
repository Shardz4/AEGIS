import os
import sys
import pytest
import time
from datetime import datetime, timedelta

# Ensure python_brain/src is in sys.path
src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from aegis.fatigue.fatigue_monitor import FatigueMonitor, OperatorProfile
from aegis.risk.bayesian_net import RiskEngine
from aegis.risk.batch_processor import BatchProcessor
from aegis.graph.equipment_graph import EquipmentGraph
from aegis.permits.permit_store import PermitStore

def test_operator_fatigued_night_shift():
    """1. Operator at hour 11 of a 12-hour night shift -> fatigue_score > 70"""
    # 2:00 AM represents a night shift hour
    mock_now = datetime(2026, 6, 23, 2, 0, 0)
    monitor = FatigueMonitor(start_time=mock_now)
    
    # Create operator who started 11 hours ago
    operator_id = "TEST_FATIGUED"
    monitor.operators[operator_id] = OperatorProfile(
        operator_id=operator_id,
        name="Test Fatigued Night",
        shift_start=mock_now - timedelta(hours=11),
        shift_duration_hours=12.0,
        role="Field Operator",
        current_zone=1
    )
    
    assessment = monitor.get_fatigue_score(operator_id)
    assert assessment.fatigue_score > 70.0
    assert assessment.risk_level == "high"
    assert assessment.is_night_shift

def test_operator_fresh_day_shift():
    """2. Operator at hour 1 of a day shift -> fatigue_score < 20"""
    # 10:00 AM represents a day shift hour
    mock_now = datetime(2026, 6, 23, 10, 0, 0)
    monitor = FatigueMonitor(start_time=mock_now)
    
    # Create operator who started 1 hour ago
    operator_id = "TEST_FRESH"
    monitor.operators[operator_id] = OperatorProfile(
        operator_id=operator_id,
        name="Test Fresh Day",
        shift_start=mock_now - timedelta(hours=1),
        shift_duration_hours=8.0,
        role="Maintenance",
        current_zone=1
    )
    
    assessment = monitor.get_fatigue_score(operator_id)
    assert assessment.fatigue_score < 20.0
    assert assessment.risk_level == "normal"
    assert not assessment.is_night_shift

def test_bayesian_network_fatigue_impact():
    """3. Bayesian network with FatigueScore=high increases incident probability vs FatigueScore=normal"""
    engine = RiskEngine()
    
    # Case A: normal fatigue
    evidence_normal = {
        "GasLevel": "low",
        "Temperature": "normal",
        "Pressure": "normal",
        "TTI_Urgency": "normal",
        "HotWorkActive": "no",
        "ConfinedSpace": "no",
        "WorkerCount": "none",
        "FatigueScore": "normal"
    }
    res_normal = engine.compute_risk(zone_id=1, timestamp=time.time(), evidence=evidence_normal)
    
    # Case B: high fatigue
    evidence_high = evidence_normal.copy()
    evidence_high["FatigueScore"] = "high"
    res_high = engine.compute_risk(zone_id=1, timestamp=time.time(), evidence=evidence_high)
    
    # Compare incident probability distribution
    assert res_high.risk_score > res_normal.risk_score
    
    p_negligible_normal = res_normal.incident_probability.get("negligible", 0.0)
    p_negligible_high = res_high.incident_probability.get("negligible", 0.0)
    
    assert p_negligible_high < p_negligible_normal  # Probability of negligible incident decreases
    assert res_high.risk_score - res_normal.risk_score > 0.0

def test_zone_level_risk_elevation():
    """4. Zone with fatigued operator: risk_score increases by at least 5-10 points"""
    graph = EquipmentGraph()
    permit_store = PermitStore(graph)
    engine = RiskEngine()
    
    class MockReader:
        def read_batch(self):
            return []

    # Initialize batch processor
    processor = BatchProcessor(
        ring_reader=MockReader(),
        risk_engine=engine,
        equipment_graph=graph,
        permit_store=permit_store
    )
    
    # Let's make sure permit store is empty for zone 1 to avoid permit confounding
    active = permit_store.get_active_for_zone(1)
    for p in list(active):
        permit_store.active_permits.remove(p)
        
    # Evaluate risk when Zone 1 has no fatigued operators (Elena, Rajesh etc. are not in Zone 1)
    assessments_before = processor.evaluate_risk()
    ra_zone1_before = next(ra for ra in assessments_before if ra.zone_id == 1)
    
    # Now, assign a fatigued night shift operator to Zone 1
    mock_now = datetime(2026, 6, 23, 2, 0, 0)
    processor.fatigue_monitor.current_time = mock_now
    processor.fatigue_monitor.operators["OP_FATIGUED_TEST"] = OperatorProfile(
        operator_id="OP_FATIGUED_TEST",
        name="Fatigued Test",
        shift_start=mock_now - timedelta(hours=11),
        shift_duration_hours=12.0,
        role="Field Operator",
        current_zone=1
    )
    
    # Evaluate risk with the fatigued operator in Zone 1
    assessments_after = processor.evaluate_risk()
    ra_zone1_after = next(ra for ra in assessments_after if ra.zone_id == 1)
    
    delta = ra_zone1_after.risk_score - ra_zone1_before.risk_score
    print(f"\n[Zone 1 Fatigue Impact] Risk score before: {ra_zone1_before.risk_score:.2f}%")
    print(f"[Zone 1 Fatigue Impact] Risk score after: {ra_zone1_after.risk_score:.2f}%")
    print(f"[Zone 1 Fatigue Impact] Delta: {delta:.2f}%")
    
    assert delta >= 5.0, f"Expected risk_score to increase by >= 5 points, got {delta:.2f}"
    assert delta <= 15.0, f"Expected risk_score increase to be reasonable, got {delta:.2f}"
