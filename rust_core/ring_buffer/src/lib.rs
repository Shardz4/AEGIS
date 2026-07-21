use memmap2::MmapMut;
use std::fs::OpenOptions;
use std::io::{Error, ErrorKind, Result};
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::thread;
use std::time::Duration;

pub mod protocol;
pub use protocol::SensorEvent;

const HEADER_SIZE: u64 = 64;
const OFFSET_WRITE_POS: usize = 0;
const OFFSET_READ_POS: usize = 8;
const OFFSET_CAPACITY: usize = 16;
const OFFSET_EVENT_COUNT: usize = 24;

pub struct RingBuffer {
    mmap: MmapMut,
    data_capacity: u64,
    drop_oldest: bool,
}

impl RingBuffer {
    /// Opens an existing ring buffer file or creates a new one at the specified path.
    /// `capacity` is the total size of the file in bytes (minimum 1024).
    pub fn new<P: AsRef<Path>>(path: P, capacity: u64, drop_oldest: bool) -> Result<Self> {
        if capacity < HEADER_SIZE + 128 {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                format!("Capacity must be at least {} bytes", HEADER_SIZE + 128),
            ));
        }

        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .open(&path)?;

        let metadata = file.metadata()?;
        let size = metadata.len();

        let mmap = if size == 0 {
            file.set_len(capacity)?;
            let mut mmap = unsafe { MmapMut::map_mut(&file)? };
            // Initialize header
            let data_cap = capacity - HEADER_SIZE;
            unsafe {
                let write_ptr = mmap.as_mut_ptr().add(OFFSET_WRITE_POS) as *mut u64;
                let read_ptr = mmap.as_mut_ptr().add(OFFSET_READ_POS) as *mut u64;
                let cap_ptr = mmap.as_mut_ptr().add(OFFSET_CAPACITY) as *mut u64;
                let count_ptr = mmap.as_mut_ptr().add(OFFSET_EVENT_COUNT) as *mut u64;

                std::ptr::write_volatile(write_ptr, 0);
                std::ptr::write_volatile(read_ptr, 0);
                std::ptr::write_volatile(cap_ptr, data_cap);
                std::ptr::write_volatile(count_ptr, 0);
            }
            mmap
        } else {
            unsafe { MmapMut::map_mut(&file)? }
        };

        // Read data capacity from header
        let data_capacity = unsafe {
            let cap_ptr = mmap.as_ptr().add(OFFSET_CAPACITY) as *const u64;
            std::ptr::read_volatile(cap_ptr)
        };

        if data_capacity == 0 || data_capacity > capacity {
            return Err(Error::new(
                ErrorKind::InvalidData,
                "Invalid data capacity in ring buffer header",
            ));
        }

        Ok(Self {
            mmap,
            data_capacity,
            drop_oldest,
        })
    }

    fn write_pos_ref(&self) -> &AtomicU64 {
        unsafe { &*(self.mmap.as_ptr().add(OFFSET_WRITE_POS) as *const AtomicU64) }
    }

    fn read_pos_ref(&self) -> &AtomicU64 {
        unsafe { &*(self.mmap.as_ptr().add(OFFSET_READ_POS) as *const AtomicU64) }
    }

    fn event_count_ref(&self) -> &AtomicU64 {
        unsafe { &*(self.mmap.as_ptr().add(OFFSET_EVENT_COUNT) as *const AtomicU64) }
    }

    /// Read a u32 from the data area at the logical position `pos`.
    fn read_u32_at(&self, pos: u64) -> u32 {
        let offset = HEADER_SIZE + (pos % self.data_capacity);
        let ptr = self.mmap.as_ptr();
        if offset + 4 <= HEADER_SIZE + self.data_capacity {
            unsafe {
                let val_ptr = ptr.add(offset as usize) as *const u32;
                std::ptr::read_unaligned(val_ptr)
            }
        } else {
            // Split read (wrap-around for length prefix itself)
            let mut buf = [0u8; 4];
            let first_part = (self.data_capacity - (pos % self.data_capacity)) as usize;
            unsafe {
                std::ptr::copy_nonoverlapping(
                    ptr.add(offset as usize),
                    buf.as_mut_ptr(),
                    first_part,
                );
                std::ptr::copy_nonoverlapping(
                    ptr.add(HEADER_SIZE as usize),
                    buf.as_mut_ptr().add(first_part),
                    4 - first_part,
                );
            }
            u32::from_ne_bytes(buf)
        }
    }

    /// Try to push an event into the ring buffer. Non-blocking.
    /// Returns Ok(true) if successful, Ok(false) if full, or Err on serialization/system errors.
    pub fn try_push(&mut self, event: &SensorEvent) -> Result<bool> {
        let payload = rmp_serde::to_vec(event)
            .map_err(|e| Error::new(ErrorKind::InvalidData, e.to_string()))?;
        let event_len = payload.len() as u32;
        let total_len = 4 + event_len as u64;

        if total_len > self.data_capacity {
            return Err(Error::new(
                ErrorKind::InvalidInput,
                format!(
                    "Event size ({} bytes) exceeds total data capacity ({} bytes)",
                    total_len, self.data_capacity
                ),
            ));
        }

        loop {
            let w = self.write_pos_ref().load(Ordering::SeqCst);
            let r = self.read_pos_ref().load(Ordering::SeqCst);

            if w + total_len - r > self.data_capacity {
                if self.drop_oldest {
                    // Drop oldest event by advancing read_pos
                    let len_at_r = self.read_u32_at(r);
                    let step = 4 + len_at_r as u64;
                    let _ = self.read_pos_ref().compare_exchange(
                        r,
                        r + step,
                        Ordering::SeqCst,
                        Ordering::SeqCst,
                    );
                    // Loop again to check space
                    continue;
                } else {
                    return Ok(false);
                }
            }

            // Copy data to buffer starting at w % data_capacity
            let offset = (w % self.data_capacity) as usize;
            let mmap_ptr = self.mmap.as_mut_ptr();

            if offset + total_len as usize <= self.data_capacity as usize {
                // Contiguous copy
                unsafe {
                    let len_ptr = mmap_ptr.add(HEADER_SIZE as usize + offset) as *mut u32;
                    std::ptr::write_unaligned(len_ptr, event_len);
                    std::ptr::copy_nonoverlapping(
                        payload.as_ptr(),
                        mmap_ptr.add(HEADER_SIZE as usize + offset + 4),
                        payload.len(),
                    );
                }
            } else {
                // Split copy (wrap-around)
                let mut temp_buf = Vec::with_capacity(total_len as usize);
                temp_buf.extend_from_slice(&event_len.to_ne_bytes());
                temp_buf.extend_from_slice(&payload);

                let first_part = (self.data_capacity as usize) - offset;
                unsafe {
                    std::ptr::copy_nonoverlapping(
                        temp_buf.as_ptr(),
                        mmap_ptr.add(HEADER_SIZE as usize + offset),
                        first_part,
                    );
                    std::ptr::copy_nonoverlapping(
                        temp_buf.as_ptr().add(first_part),
                        mmap_ptr.add(HEADER_SIZE as usize),
                        total_len as usize - first_part,
                    );
                }
            }

            // Advance write_pos and event_count
            self.write_pos_ref().store(w + total_len, Ordering::SeqCst);
            self.event_count_ref().fetch_add(1, Ordering::SeqCst);
            return Ok(true);
        }
    }

    /// Push an event, blocking until space is available if drop_oldest is false.
    pub fn push(&mut self, event: &SensorEvent) -> Result<()> {
        while !self.try_push(event)? {
            thread::sleep(Duration::from_millis(1));
        }
        Ok(())
    }

    /// Helper for testing: read a single event from the buffer.
    pub fn pop(&mut self) -> Result<Option<SensorEvent>> {
        let w = self.write_pos_ref().load(Ordering::SeqCst);
        let r = self.read_pos_ref().load(Ordering::SeqCst);

        if r == w {
            return Ok(None);
        }

        let event_len = self.read_u32_at(r);
        let total_len = 4 + event_len as u64;

        if r + total_len > w {
            // Data not fully written yet
            return Ok(None);
        }

        let offset = ((r + 4) % self.data_capacity) as usize;
        let mut payload = vec![0u8; event_len as usize];
        let ptr = self.mmap.as_ptr();

        if offset + event_len as usize <= self.data_capacity as usize {
            unsafe {
                std::ptr::copy_nonoverlapping(
                    ptr.add(HEADER_SIZE as usize + offset),
                    payload.as_mut_ptr(),
                    event_len as usize,
                );
            }
        } else {
            let first_part = (self.data_capacity as usize) - offset;
            unsafe {
                std::ptr::copy_nonoverlapping(
                    ptr.add(HEADER_SIZE as usize + offset),
                    payload.as_mut_ptr(),
                    first_part,
                );
                std::ptr::copy_nonoverlapping(
                    ptr.add(HEADER_SIZE as usize),
                    payload.as_mut_ptr().add(first_part),
                    event_len as usize - first_part,
                );
            }
        }

        // Deserialization
        let event: SensorEvent = rmp_serde::from_slice(&payload)
            .map_err(|e| Error::new(ErrorKind::InvalidData, e.to_string()))?;

        // Advance read_pos
        self.read_pos_ref().store(r + total_len, Ordering::SeqCst);

        Ok(Some(event))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_file_path() -> String {
        format!(
            "temp_ring_buffer_{}.bin",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        )
    }

    #[test]
    fn test_basic_push_pop() {
        let path = temp_file_path();
        // File must fit at least header (64) + data space. Let's allocate 2048 bytes
        let mut rb = RingBuffer::new(&path, 2048, false).unwrap();

        let event = SensorEvent {
            ts: 123456,
            src: 1,
            zone: 2,
            signal_id: 10,
            value: 42.5,
            meta: vec![1, 2, 3, 4],
        };

        rb.push(&event).unwrap();

        let popped = rb.pop().unwrap().unwrap();
        assert_eq!(popped, event);

        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn test_wrap_around() {
        let path = temp_file_path();
        // Create small buffer: 64 header + 256 data = 320 bytes
        let mut rb = RingBuffer::new(&path, 320, false).unwrap();

        // Write events until we wrap around
        let event = SensorEvent {
            ts: 11111,
            src: 0,
            zone: 1,
            signal_id: 5,
            value: 12.3,
            meta: vec![0; 20], // msgpack size will be ~40-50 bytes
        };

        // We should be able to push and pop in a loop without hitting capacity issues
        for i in 0..10 {
            let mut ev = event.clone();
            ev.ts = i;
            rb.push(&ev).unwrap();
            let popped = rb.pop().unwrap().unwrap();
            assert_eq!(popped.ts, i);
        }

        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn test_drop_oldest() {
        let path = temp_file_path();
        // Create small buffer: 64 header + 128 data = 192 bytes
        // Each event takes ~40 bytes. Pushing 5 events without popping should drop the oldest.
        let mut rb = RingBuffer::new(&path, 192, true).unwrap();

        for i in 0..6 {
            let ev = SensorEvent {
                ts: i,
                src: 0,
                zone: 0,
                signal_id: i as u16,
                value: i as f64,
                meta: vec![0; 5],
            };
            rb.push(&ev).unwrap();
        }

        // We pushed 6 events. Since data capacity is 128 bytes, and each event is ~33 bytes,
        // it can hold at most 3 events at a time. The first 3 events should have been dropped.
        let mut popped_vals = Vec::new();
        while let Some(ev) = rb.pop().unwrap() {
            popped_vals.push(ev.ts);
        }

        assert!(!popped_vals.is_empty());
        // Verify that the retrieved events have the latest timestamps
        assert_eq!(*popped_vals.last().unwrap(), 5);
        assert!(*popped_vals.first().unwrap() > 0); // Event 0 should definitely be dropped

        let _ = std::fs::remove_file(&path);
    }
}
