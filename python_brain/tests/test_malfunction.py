import os
import sys
import pytest
import numpy as np

# Ensure python_brain/src is in sys.path
src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from aegis.graph.equipment_graph import EquipmentGraph
from aegis.permits.permit_store import PermitStore
from aegis.risk.bayesian_net import RiskEngine
from aegis.risk.batch_processor import BatchProcessor

class MockRingReader:
    def __init__(self, events=None):
        self.events = events or []

    def read_batch(self):
        return self.events

def test_sensor_malfunction_outlier_mad():
    """Verify that a single outlying sensor in a zone is flagged as malfunctioning (spatial voting <= 2)."""
    graph = EquipmentGraph()
    permit_store = PermitStore(graph)
    engine = RiskEngine()
    
    # 25 sensors in Zone 2 have IDs: 2, 10, 18, 26, 34, ..., 194 (2 + 8 * idx)
    zone_id = 2
    sensor_ids = [2 + 8 * i for i in range(25)]
    
    events = []
    # 24 sensors are nominal (2.4 bar)
    for s_id in sensor_ids[:-1]:
        events.append({
            "src": 0,
            "zone": zone_id,
            "signal_id": s_id,
            "value": 2.4
        })
    # 1 sensor is an extreme outlier (15.0 bar)
    outlier_sensor_id = sensor_ids[-1]
    events.append({
        "src": 0,
        "zone": zone_id,
        "signal_id": outlier_sensor_id,
        "value": 15.0
    })
    
    reader = MockRingReader(events)
    processor = BatchProcessor(reader, engine, graph, permit_store)
    
    # Process events to trigger malfunction detection
    processor.process_events()
    
    # Check that outlier sensor is identified as malfunctioning
    assert outlier_sensor_id in processor.malfunctioning_sensors
    # Check that nominal sensors are not malfunctioning
    for s_id in sensor_ids[:-1]:
        assert s_id not in processor.malfunctioning_sensors

    # Evaluate risk and verify the outlier sensor is excluded from representative value calculation
    assessments = processor.evaluate_risk()
    # Zone 2 is index 2
    assert processor.latest_signals[zone_id]["Pressure"] == pytest.approx(2.4)


def test_sensor_process_anomaly():
    """Verify that if > 2 sensors are outliers, it is voted as a PROCESS_ANOMALY (not malfunctioning)."""
    graph = EquipmentGraph()
    permit_store = PermitStore(graph)
    engine = RiskEngine()
    
    zone_id = 2
    sensor_ids = [2 + 8 * i for i in range(25)]
    
    events = []
    # 22 sensors are nominal (2.4 bar)
    for s_id in sensor_ids[:-3]:
        events.append({
            "src": 0,
            "zone": zone_id,
            "signal_id": s_id,
            "value": 2.4
        })
    # 3 sensors are outliers (15.0 bar)
    outlier_ids = sensor_ids[-3:]
    for s_id in outlier_ids:
        events.append({
            "src": 0,
            "zone": zone_id,
            "signal_id": s_id,
            "value": 15.0
        })
        
    reader = MockRingReader(events)
    processor = BatchProcessor(reader, engine, graph, permit_store)
    
    # Process events to trigger malfunction detection
    processor.process_events()
    
    # Since there are 3 outliers (> 2), they should NOT be flagged as malfunctioning
    # (they are classified as a genuine process anomaly)
    assert len(processor.malfunctioning_sensors) == 0
