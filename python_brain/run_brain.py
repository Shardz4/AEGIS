import os
import sys
import time

# Ensure python_brain/src is in sys.path
src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "src"))
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from aegis.ipc.reader import RingBufferReader
from aegis.graph.equipment_graph import EquipmentGraph
from aegis.permits.permit_store import PermitStore
from aegis.risk.bayesian_net import RiskEngine
from aegis.risk.batch_processor import BatchProcessor

def main():
    ring_path = os.environ.get("AEGIS_RING_PATH", "aegis_ring.bin")
    
    print(f"Connecting to shared-memory ring buffer: {ring_path}")
    print("Ensure Rust Core daemon is running and has initialized the ring buffer.")
    
    # Wait for the ring buffer to be created by Rust
    while not os.path.exists(ring_path):
        print("Waiting for Rust Core to initialize the ring buffer file...")
        time.sleep(2)
        
    try:
        # Initialize IPC reader (64MB shared memory block)
        reader = RingBufferReader(ring_path, 64 * 1024 * 1024)
        
        # Initialize engine modules
        engine = RiskEngine()
        graph = EquipmentGraph()
        permit_store = PermitStore()
        
        # Populate active permits in permit store to match the demo baseline
        # In the demo scenario:
        # Zone 2 (Reactor Area): HotWork permit (worker count: 3)
        # Zone 0 (Tank Farm): ConfinedSpace permit (worker count: 2)
        permit_store.add_permit("PTW-8022", 2, "HotWork", 4.0, 3)
        permit_store.add_permit("PTW-8023", 0, "ConfinedSpace", 8.0, 2)
        
        # Sync permits to equipment graph
        graph.activate_permit("PTW-8022", 2, "HotWork", 4.0, 3)
        graph.activate_permit("PTW-8023", 0, "ConfinedSpace", 8.0, 2)
        
        # Instantiate and run batch processor
        processor = BatchProcessor(
            ring_reader=reader,
            risk_engine=engine,
            equipment_graph=graph,
            permit_store=permit_store
        )
        
        # Run indefinitely (e.g. 24 hours or until interrupted)
        processor.run(duration_seconds=86400.0)
        
    except KeyboardInterrupt:
        print("\nStopping AEGIS Reasoning Brain.")
    except Exception as e:
        print(f"\nError running AEGIS Reasoning Brain: {e}")

if __name__ == "__main__":
    main()
