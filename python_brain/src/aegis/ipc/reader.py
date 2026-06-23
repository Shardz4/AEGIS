import mmap
import os
import struct
import time
import msgpack
from aegis.config import (
    HEADER_SIZE,
    OFFSET_WRITE_POS,
    OFFSET_READ_POS,
    OFFSET_CAPACITY,
    OFFSET_EVENT_COUNT,
)

class RingBufferReader:
    def __init__(self, path: str, batch_size: int = 64):
        self.path = os.path.abspath(path)
        self.batch_size = batch_size
        self.file_obj = None
        self.mem = None
        self.data_capacity = 0
        
        # Wait up to 5 seconds for the file to exist (if started before producer)
        start_wait = time.time()
        while not os.path.exists(self.path):
            if time.time() - start_wait > 5.0:
                raise FileNotFoundError(f"Ring buffer file not found at {self.path}")
            time.sleep(0.1)

        self.file_obj = open(self.path, "r+b")
        self.mem = mmap.mmap(self.file_obj.fileno(), 0, access=mmap.ACCESS_WRITE)
        
        # Read data capacity from header
        self.data_capacity = struct.unpack_from("<Q", self.mem, OFFSET_CAPACITY)[0]
        if self.data_capacity == 0:
            raise ValueError("Ring buffer capacity in header is 0")

    def close(self):
        if self.mem:
            self.mem.close()
            self.mem = None
        if self.file_obj:
            self.file_obj.close()
            self.file_obj = None

    def read_u32_at(self, pos: int) -> int:
        offset = pos % self.data_capacity
        phys_offset = HEADER_SIZE + offset
        if phys_offset + 4 <= HEADER_SIZE + self.data_capacity:
            return struct.unpack_from("<I", self.mem, phys_offset)[0]
        else:
            # Wrap around length prefix
            first_part_len = self.data_capacity - offset
            first_part = self.mem[phys_offset : phys_offset + first_part_len]
            second_part = self.mem[HEADER_SIZE : HEADER_SIZE + 4 - first_part_len]
            return struct.unpack("<I", first_part + second_part)[0]

    def read_batch(self) -> list[dict]:
        if not self.mem:
            raise ValueError("Reader is closed")
            
        write_pos = struct.unpack_from("<Q", self.mem, OFFSET_WRITE_POS)[0]
        read_pos = struct.unpack_from("<Q", self.mem, OFFSET_READ_POS)[0]

        if read_pos == write_pos:
            return []

        batch = []
        count = 0
        
        while read_pos < write_pos and count < self.batch_size:
            # 1. Read event length
            event_len = self.read_u32_at(read_pos)
            total_len = 4 + event_len

            # Check if this entire event has been fully written by producer
            if read_pos + total_len > write_pos:
                break

            # 2. Read serialized payload
            payload_pos = (read_pos + 4) % self.data_capacity
            phys_payload_pos = HEADER_SIZE + payload_pos
            
            if phys_payload_pos + event_len <= HEADER_SIZE + self.data_capacity:
                # Contiguous read
                payload = self.mem[phys_payload_pos : phys_payload_pos + event_len]
            else:
                # Split read (wrap around)
                first_part_len = self.data_capacity - payload_pos
                first_part = self.mem[phys_payload_pos : phys_payload_pos + first_part_len]
                second_part = self.mem[HEADER_SIZE : HEADER_SIZE + event_len - first_part_len]
                payload = first_part + second_part

            # 3. Deserialize using msgpack
            try:
                raw_ev = msgpack.unpackb(payload, raw=False)
                if isinstance(raw_ev, (list, tuple)) and len(raw_ev) >= 6:
                    event = {
                        "ts": raw_ev[0],
                        "src": raw_ev[1],
                        "zone": raw_ev[2],
                        "signal_id": raw_ev[3],
                        "value": raw_ev[4],
                        "meta": raw_ev[5],
                    }
                else:
                    event = raw_ev
                batch.append(event)
            except Exception as e:
                # If there's a corruption, print and break/skip
                print(f"Error unpacking event at pos {read_pos}: {e}")
                break

            read_pos += total_len
            count += 1

        # Write updated read position back to header
        struct.pack_into("<Q", self.mem, OFFSET_READ_POS, read_pos)
        
        return batch
