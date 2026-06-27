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
    
    # We will test Sensor 10 (Pressure) in Zone 2
    # Sensor 10 is in Zone 2, type Pressure (10 % 8 = 2)
    # Nominal Pressure baseline = 1.5, std_dev = 0.1
    # K = 0.5 * std_dev = 0.05, H = 4.0 * std_dev = 0.4
    sensor_id = 10
    zone_id = 2
    
    # Initialize BatchProcessor with empty events
    reader = MockRingReader([])
    processor = BatchProcessor(reader, engine, graph, permit_store)
    
    # Feed 10 ticks of nominal data (1.5) one by one
    for _ in range(10):
        processor.ring_reader.events = [{
            "src": 0,
            "zone": zone_id,
            "signal_id": sensor_id,
            "value": 1.5
        }]
        processor.process_events()
        
    assert processor.sensor_calibration_state.get(sensor_id, 'NOMINAL') == 'NOMINAL'
    assert processor.cusum_high.get(sensor_id, 0.0) == 0.0
    
    # Now feed ticks of drifting values: 1.7 one by one
    # For each tick, high CUSUM = max(0, prev + 1.7 - (1.5 + 0.05)) = max(0, prev + 0.15)
    # After 3 ticks, CUSUM should exceed H = 0.4 (0.15 * 3 = 0.45 > 0.4)
    for _ in range(5):
        processor.ring_reader.events = [{
            "src": 0,
            "zone": zone_id,
            "signal_id": sensor_id,
            "value": 1.7
        }]
        processor.process_events()
    
    # Verify drift state is triggered
    assert processor.sensor_calibration_state.get(sensor_id) == 'DRIFTING'
    
    # Recalibrate
    processor.recalibrate_sensor(sensor_id)
    assert processor.sensor_calibration_state.get(sensor_id) == 'CALIBRATING'
    assert processor.cusum_high.get(sensor_id) == 0.0
    
    # Feed one nominal tick (1.5)
    processor.ring_reader.events = [{
        "src": 0,
        "zone": zone_id,
        "signal_id": sensor_id,
        "value": 1.5
    }]
    processor.process_events()
    
    # Should transition back to NOMINAL
    assert processor.sensor_calibration_state.get(sensor_id) == 'NOMINAL'
