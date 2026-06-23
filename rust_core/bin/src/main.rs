use ring_buffer::RingBuffer;
use scada_sim::{ScadaSimulator, SimConfig, SensorType};
use tti_engine::{TtiEngine, TtiResult, Urgency};
use std::time::{Instant, Duration};
use std::thread;

fn format_tti(tti: Option<f64>) -> String {
    match tti {
        None => "Flat/Drifting".to_string(),
        Some(t) if t == 0.0 => "BREACHED".to_string(),
        Some(t) => {
            if t < 60.0 {
                format!("{:.1}s", t)
            } else if t < 3600.0 {
                let m = (t / 60.0).floor();
                let s = (t % 60.0).round();
                format!("{}m {}s", m, s)
            } else {
                let h = (t / 3600.0).floor();
                let m = ((t % 3600.0) / 60.0).round();
                format!("{}h {}m", h, m)
            }
        }
    }
}

fn sensor_name(sensor_type: SensorType) -> &'static str {
    match sensor_type {
        SensorType::GasConcentration => "GasConc",
        SensorType::Temperature => "Temp",
        SensorType::Pressure => "Pressure",
        SensorType::FlowRate => "FlowRate",
        SensorType::Vibration => "Vibration",
        SensorType::PH => "pH",
        SensorType::Level => "Level",
        SensorType::Humidity => "Humidity",
    }
}

fn urgency_label(urgency: Urgency) -> &'static str {
    match urgency {
        Urgency::Normal => "  NORMAL",
        Urgency::Watch => "ℹ WATCH",
        Urgency::Warning => "⚠ WARNING",
        Urgency::Critical => "🚨 CRITICAL",
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = std::env::var("AEGIS_RING_PATH").unwrap_or_else(|_| "aegis_ring.bin".to_string());
    println!("Starting AEGIS Pipeline Daemon");
    println!("Ring buffer: {}", path);

    // Initialize shared-memory ring buffer (64MB)
    let mut rb = RingBuffer::new(&path, 64 * 1024 * 1024, false)?;

    // Initialize SCADA simulator (200 sensors, 8 zones, 10Hz tick rate)
    let sim_config = SimConfig::default();
    let mut sim = ScadaSimulator::new(sim_config);
    println!("Initialized ScadaSimulator with {} sensors across {} zones", 
             sim.sensors.len(), sim.config.num_zones);

    // Initialize TTI Engine with window size of 30 ticks (~3 seconds)
    let mut tti_engine = TtiEngine::new(30);

    // Keep track of latest results for the console dashboard
    let mut latest_results: Vec<(String, String, TtiResult)> = Vec::new();

    let start_time = Instant::now();
    let duration = Duration::from_secs(60);
    let tick_duration = Duration::from_millis(100); // 10Hz

    let mut last_dashboard_print = Instant::now();
    let mut ticks = 0;

    println!("Pipeline running. Simulating for 60 seconds...");
    println!("--------------------------------------------------");

    while start_time.elapsed() < duration {
        let tick_start = Instant::now();

        // 1. Tick SCADA Simulator
        let raw_events = sim.tick();
        ticks += 1;

        latest_results.clear();

        // 2. Process events through TTI Engine
        for mut event in raw_events {
            // Find corresponding sensor to get threshold and type
            let sensor = &sim.sensors[event.signal_id as usize];
            let threshold = sensor.threshold_critical;
            
            // Update TTI Engine
            let tti_result = tti_engine.update(
                event.signal_id,
                event.ts,
                event.value,
                threshold,
            );

            // Serialize TtiResult into MsgPack bytes for the meta field
            let meta_bytes = rmp_serde::to_vec(&tti_result)?;
            event.meta = meta_bytes;

            // Save for dashboard rendering
            let name = format!("{} Sensor #{}", sensor_name(sensor.sensor_type), sensor.id);
            let zone_str = format!("ZONE {}", sensor.zone);
            latest_results.push((zone_str, name, tti_result));

            // Write enriched event to shared memory ring buffer
            if let Err(e) = rb.try_push(&event) {
                // If the buffer is full and we aren't dropping oldest, log warning
                eprintln!("Ring buffer full, event dropped: {:?}", e);
            }
        }

        // 3. Print Console Dashboard every 1 second
        if !std::env::var("AEGIS_UNTHROTTLED").is_ok() && last_dashboard_print.elapsed() >= Duration::from_secs(1) {
            last_dashboard_print = Instant::now();

            // Sort results: Critical first, then Warning, then Watch, then Normal
            // Within the same urgency, sort by TTI ascending
            latest_results.sort_by(|a, b| {
                let urgency_ord = b.2.urgency.cmp(&a.2.urgency); // descending urgency
                if urgency_ord == std::cmp::Ordering::Equal {
                    match (a.2.tti_seconds, b.2.tti_seconds) {
                        (Some(t1), Some(t2)) => t1.partial_cmp(&t2).unwrap_or(std::cmp::Ordering::Equal),
                        (Some(_), None) => std::cmp::Ordering::Less,
                        (None, Some(_)) => std::cmp::Ordering::Greater,
                        (None, None) => std::cmp::Ordering::Equal,
                    }
                } else {
                    urgency_ord
                }
            });

            print!("\x1B[2J\x1B[1H"); // Clear screen and move cursor to top
            println!("================== AEGIS LIVE SCADA & TTI PIPELINE ==================");
            println!("Elapsed: {:.1}s | Ticks: {} | Buffer: {}", 
                     start_time.elapsed().as_secs_f64(), ticks, path);
            println!("---------------------------------------------------------------------");
            println!("{:<8} | {:<18} | {:<12} | {:<12} | {:<10} | {}", 
                     "ZONE", "SENSOR", "VALUE", "TTI", "CONFIDENCE", "URGENCY");
            println!("---------------------------------------------------------------------");

            for (zone, name, res) in latest_results.iter().take(5) {
                let val_str = format!("{:.2}", res.current_value);
                let tti_str = format_tti(res.tti_seconds);
                let conf_str = format!("{:.2}", res.r_squared);
                println!("{:<8} | {:<18} | {:<12} | {:<12} | {:<10} | {}",
                         zone, name, val_str, tti_str, conf_str, urgency_label(res.urgency));
            }
            println!("=====================================================================");
        }

        // Sleep to throttle tick rate to 10Hz
        if !std::env::var("AEGIS_UNTHROTTLED").is_ok() {
            let elapsed = tick_start.elapsed();
            if elapsed < tick_duration {
                thread::sleep(tick_duration - elapsed);
            }
        }
    }

    println!("\nSimulation complete. Stopped pipeline daemon.");
    Ok(())
}
