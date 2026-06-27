import os
import sys
import pytest

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

def test_cusum_drift_detection():
    """Verify that slow persistent sensor drift triggers the DRIFTING state and recalibration resets it."""
    graph = EquipmentGraph()
    permit_store = PermitStore(graph)
    engine = RiskEngine()
    
    # We will test Sensor 5 (Reactor Temp) in Zone 2
    # Sensor 5 is a Temperature type sensor
    # Nominal Temperature baseline = 25.0, std_dev = 1.0
    # K = 0.5 * std_dev = 0.5, H = 4.0 * std_dev = 4.0
    sensor_id = 5
    zone_id = 2
    
    # Feed 10 ticks of nominal data (25.0)
    nominal_events = []
    for _ in range(10):
        nominal_events.append({
            "src": 0,
            "zone": zone_id,
            "signal_id": sensor_id,
            "value": 25.0
        })
        
    reader = MockRingReader(nominal_events)
    processor = BatchProcessor(reader, engine, graph, permit_store)
    
    processor.process_events()
    assert processor.sensor_calibration_state.get(sensor_id, 'NOMINAL') == 'NOMINAL'
    assert processor.cusum_high.get(sensor_id, 0.0) == 0.0
    
    # Now feed ticks of drifting values: 27.0
    # For each tick, high CUSUM = max(0, prev + 27.0 - (25.0 + 0.5)) = max(0, prev + 1.5)
    # After 3 ticks, CUSUM should exceed H = 4.0 (1.5 * 3 = 4.5 > 4.0)
    drift_events = []
    for _ in range(5):
        drift_events.append({
            "src": 0,
            "zone": zone_id,
            "signal_id": sensor_id,
            "value": 27.0
        })
        
    processor.ring_reader.events = drift_events
    processor.process_events()
    
    # Verify drift state is triggered
    assert processor.sensor_calibration_state.get(sensor_id) == 'DRIFTING'
    
    # Recalibrate
    processor.recalibrate_sensor(sensor_id)
    assert processor.sensor_calibration_state.get(sensor_id) == 'CALIBRATING'
    assert processor.cusum_high.get(sensor_id) == 0.0
    
    # Feed one nominal tick (25.0)
    processor.ring_reader.events = [{
        "src": 0,
        "zone": zone_id,
        "signal_id": sensor_id,
        "value": 25.0
    }]
    processor.process_events()
    
    # Should transition back to NOMINAL
    assert processor.sensor_calibration_state.get(sensor_id) == 'NOMINAL'
