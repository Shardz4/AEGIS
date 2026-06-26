import os
import sys
import json
import time
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
    def read_batch(self):
        return []

def test_permit_store_graph_propagation():
    """Verify that adding and revoking a permit propagates correctly to the EquipmentGraph."""
    graph = EquipmentGraph()
    permit_store = PermitStore(graph)
    
    # PermitStore starts with 3 prepopulated permits
    assert len(permit_store.active_permits) == 3
    
    # Add permit
    permit_store.add_permit("PTW-8022", 2, "HotWork", 4.0, 3)
    assert "PTW-8022" in permit_store.active_permits
    assert permit_store.active_permits["PTW-8022"].status == "ACTIVE"
    
    ctx = graph.get_zone_context(2)
    assert any(p["permit_id"] == "PTW-8022" for p in ctx["permits"])
    
    # Revoke permit
    permit_store.revoke_permit("PTW-8022")
    assert permit_store.active_permits["PTW-8022"].status == "EXPIRED"
    
    ctx2 = graph.get_zone_context(2)
    assert not any(p["permit_id"] == "PTW-8022" for p in ctx2["permits"])

def test_batch_processor_control_override_processing():
    """Verify that BatchProcessor reads control_override.json and revokes permits."""
    # Ensure any previous control_override.json is deleted
    if os.path.exists("control_override.json"):
        os.remove("control_override.json")
        
    graph = EquipmentGraph()
    permit_store = PermitStore(graph)
    engine = RiskEngine()
    reader = MockRingReader()
    
    # Populate permit store
    permit_store.add_permit("PTW-8022", 2, "HotWork", 4.0, 3)
    assert "PTW-8022" in permit_store.active_permits
    assert permit_store.active_permits["PTW-8022"].status == "ACTIVE"
    
    processor = BatchProcessor(
        ring_reader=reader,
        risk_engine=engine,
        equipment_graph=graph,
        permit_store=permit_store
    )
    
    # Write control override file cancelling PTW-8022
    override_data = {
        "isolated_zones": [],
        "cancelled_permits": ["PTW-8022"]
    }
    with open("control_override.json", "w", encoding="utf-8") as f:
        json.dump(override_data, f)
        
    try:
        # Run processor for a short time (e.g. 0.05 seconds) to trigger the control override loop
        processor.run(duration_seconds=0.05)
        
        # Verify that permit status is set to EXPIRED
        assert permit_store.active_permits["PTW-8022"].status == "EXPIRED"
        
        ctx = graph.get_zone_context(2)
        assert not any(p["permit_id"] == "PTW-8022" for p in ctx["permits"])
    finally:
        # Clean up override file
        if os.path.exists("control_override.json"):
            os.remove("control_override.json")
