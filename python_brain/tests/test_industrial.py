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

from aegis.risk.bayesian_net import RiskEngine
from aegis.risk.batch_processor import BatchProcessor
from aegis.permits.permit_store import PermitStore
from aegis.graph.equipment_graph import EquipmentGraph
from aegis.ipc.reader import RingBufferReader
import msgpack

class MockRingBuffer:
    def __init__(self, path, capacity=4096):
        self.path = os.path.abspath(path)
        self.capacity = capacity
        # Initialize file with 64-byte header: write_pos(0), read_pos(0), capacity(data_cap), event_count(0)
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


def test_batch_processor_industrial_ingestion():
    """Verify that BatchProcessor treats Modbus (src=2) and OPC UA (src=3) telemetry correctly."""
    rb_path = "test_industrial_ring.dat"
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
        
        # 1. Push a Modbus event (src=2, zone=2, signal=6, value=2.5)
        # We need to construct TtiResult meta payload
        tti_meta = msgpack.packb({
            "tti_seconds": 120.0,
            "slope": 0.05,
            "urgency": 2  # Warning
        })
        
        rb.push_event(
            ts=1000,
            src=2, # Modbus
            zone=2, # Zone C
            signal_id=6, # Pressure sensor
            value=2.5,
            meta=tti_meta
        )
        
        # Process the batch
        bp.process_events()
        
        # Verify that the value is parsed
        assert bp.zone_sensor_values[2][6] == 2.5
        assert bp.sensor_tti[6][0] == 120.0
        assert bp.sensor_tti[6][2] == "warning"
        
        # 2. Push an OPC UA event (src=3, zone=2, signal=5, value=28.4)
        tti_meta_opc = msgpack.packb({
            "tti_seconds": None,
            "slope": 0.0,
            "urgency": 0  # Normal
        })
        
        rb.push_event(
            ts=1010,
            src=3, # OPC UA
            zone=2, # Zone C
            signal_id=5, # Temp sensor
            value=28.4,
            meta=tti_meta_opc
        )
        
        bp.process_events()
        
        # Verify that the value is parsed
        assert bp.zone_sensor_values[2][5] == 28.4
        assert bp.sensor_tti[5][0] is None
        assert bp.sensor_tti[5][2] == "normal"
        
        # Close the reader so we can delete the file cleanly
        reader.close()
                
    finally:
        if os.path.exists(rb_path):
            try:
                os.remove(rb_path)
            except Exception:
                pass
