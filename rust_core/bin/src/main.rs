use ring_buffer::{RingBuffer, SensorEvent};
use std::time::{SystemTime, UNIX_EPOCH, Instant, Duration};
use std::thread;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = std::env::var("AEGIS_RING_PATH").unwrap_or_else(|_| "aegis_ring.bin".to_string());
    println!("Starting AEGIS Smoke-Test Producer writing to: {}", path);

    // 64MB buffer
    let mut rb = RingBuffer::new(&path, 64 * 1024 * 1024, false)?;

    let running = std::sync::atomic::AtomicBool::new(true);
    let running = std::sync::Arc::new(running);
    let running_clone = running.clone();

    let handle = thread::spawn(move || {
        let mut signal_id = 0;
        let start_time = Instant::now();
        let target_rate = 10000; // events/sec
        let tick_duration = Duration::from_nanos(1_000_000_000 / target_rate);
        let mut count = 0;

        let mut next_tick = Instant::now();

        while running_clone.load(std::sync::atomic::Ordering::Relaxed) {
            let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_micros() as u64;
            let event = SensorEvent {
                ts: now,
                src: 0, // SCADA
                zone: (signal_id % 8) as u8,
                signal_id,
                value: (signal_id % 100) as f64,
                meta: vec![],
            };

            if let Err(e) = rb.push(&event) {
                eprintln!("Error pushing event: {:?}", e);
                break;
            }

            count += 1;
            signal_id = signal_id.wrapping_add(1);

            next_tick += tick_duration;
            let now_inst = Instant::now();
            if next_tick > now_inst {
                thread::sleep(next_tick - now_inst);
            } else if now_inst - next_tick > Duration::from_millis(100) {
                // Reset to now if we fall behind
                next_tick = now_inst;
            }
        }

        let elapsed = start_time.elapsed().as_secs_f64();
        println!("Producer finished. Wrote {} events in {:.2} seconds ({:.2} events/sec)", 
                 count, elapsed, count as f64 / elapsed);
    });

    thread::sleep(Duration::from_secs(5));
    running.store(false, std::sync::atomic::Ordering::Relaxed);
    let _ = handle.join();

    Ok(())
}
