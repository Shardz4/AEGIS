import subprocess
import time
import os
import sys
import pytest

# Ensure python_brain/src is in sys.path
src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from aegis.ipc.reader import RingBufferReader
from aegis.config import get_ring_path

def test_throughput():
    ring_path = get_ring_path()
    if os.path.exists(ring_path):
        try:
            os.remove(ring_path)
        except Exception:
            pass

    # Start the Rust producer as a subprocess
    rust_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "rust_core"))
    
    print("Building Rust binary in release mode...")
    # Compile in release mode so it runs at full speed
    subprocess.run(["cargo", "build", "--release", "--bin", "bin"], cwd=rust_dir, check=True)
    
    producer_path = os.path.join(rust_dir, "target", "release", "bin")
    if os.name == 'nt':
        producer_path += ".exe"

    print("Launching producer in unthrottled mode...")
    env = os.environ.copy()
    env["AEGIS_RING_PATH"] = ring_path
    env["AEGIS_UNTHROTTLED"] = "1"
    
    proc = subprocess.Popen([producer_path], env=env)
    
    reader = None
    try:
        # Wait up to 5 seconds for the ring buffer to be created by the Rust process
        start_wait = time.time()
        while not os.path.exists(ring_path):
            if time.time() - start_wait > 5.0:
                raise FileNotFoundError(f"Producer did not create ring buffer file at {ring_path}")
            time.sleep(0.1)
            
        time.sleep(0.5)  # Let it write some events first
        
        reader = RingBufferReader(ring_path, batch_size=2048)
        
        events_received = 0
        latencies = []
        
        start_time = time.time()
        # Read for 3 seconds
        while time.time() - start_time < 3.0:
            t0 = time.time()
            batch = reader.read_batch()
            dt = time.time() - t0
            
            if batch:
                events_received += len(batch)
                latencies.append(dt)
                # Verify structure of a few events
                for ev in batch[:10]:
                    assert "ts" in ev
                    assert "src" in ev
                    assert "zone" in ev
                    assert "signal_id" in ev
                    assert "value" in ev
                    assert "meta" in ev
            else:
                time.sleep(0.001)

        total_time = time.time() - start_time
        throughput = events_received / total_time
        
        print(f"\nThroughput results:")
        print(f"Total events received: {events_received}")
        print(f"Total time: {total_time:.2f} s")
        print(f"Throughput: {throughput:.2f} events/sec")
        if latencies:
            print(f"Average read_batch latency: {sum(latencies)/len(latencies)*1000:.3f} ms")
            print(f"Max read_batch latency: {max(latencies)*1000:.3f} ms")
            
        # Assert throughput >= 20,000 events/sec
        assert throughput >= 20000, f"Expected throughput >= 20000 events/sec, got {throughput:.2f}"
        
    finally:
        if proc:
            proc.terminate()
            proc.wait()
        if reader:
            reader.close()
        
        # Clean up
        if os.path.exists(ring_path):
            try:
                os.remove(ring_path)
            except Exception:
                pass
