use ring_buffer::RingBuffer;
use scada_sim::{ScadaSimulator, SimConfig, SensorType, Scenario};
use tti_engine::{TtiEngine, TtiResult, Urgency};
use plume_sim::{PlumeEngine, PlumeParams, ZoneBoundary};
use ring_buffer::SensorEvent;
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
    let _ = std::fs::remove_file("control_override.json");

    // Initialize shared-memory ring buffer (64MB)
    let mut rb = RingBuffer::new(&path, 64 * 1024 * 1024, false)?;

    // Define 8 plant zones (center_x, center_y, radius_m)
    let zone_boundaries = vec![
        ZoneBoundary { zone_id: 0, center_x: 100.0, center_y: 100.0, radius_m: 50.0 },
        ZoneBoundary { zone_id: 1, center_x: 250.0, center_y: 100.0, radius_m: 40.0 },
        ZoneBoundary { zone_id: 2, center_x: 400.0, center_y: 100.0, radius_m: 60.0 },
        ZoneBoundary { zone_id: 3, center_x: 100.0, center_y: 250.0, radius_m: 45.0 },
        ZoneBoundary { zone_id: 4, center_x: 250.0, center_y: 250.0, radius_m: 50.0 },
        ZoneBoundary { zone_id: 5, center_x: 400.0, center_y: 250.0, radius_m: 55.0 },
        ZoneBoundary { zone_id: 6, center_x: 100.0, center_y: 400.0, radius_m: 60.0 },
        ZoneBoundary { zone_id: 7, center_x: 400.0, center_y: 400.0, radius_m: 50.0 },
    ];

    // Initialize SCADA simulator (200 sensors, 8 zones, 10Hz tick rate)
    let sim_config = SimConfig::default();
    let mut sim = ScadaSimulator::new(sim_config);
    println!("Initialized ScadaSimulator with {} sensors across {} zones", 
             sim.sensors.len(), sim.config.num_zones);

    // Initialize TTI Engine with window size of 30 ticks (~3 seconds)
    let mut tti_engine = TtiEngine::new(30);

    // Initialize Plume Engine
    let plume_engine = PlumeEngine::new();
    let mut last_plume_calc: std::collections::HashMap<u16, Instant> = std::collections::HashMap::new();

    // Keep track of latest results for the console dashboard
    let mut latest_results: Vec<(String, String, TtiResult)> = Vec::new();
    // Keep track of latest computed plume details for display
    let mut active_plumes: Vec<(u8, f64)> = Vec::new();

    let mut active_wind_speed = 3.2;
    let mut active_wind_direction = 225.0;

    let start_time = Instant::now();
    let duration = Duration::from_secs(600);
    let tick_duration = Duration::from_millis(100); // 10Hz

    let mut last_dashboard_print = Instant::now();
    let mut ticks = 0;

    println!("Pipeline running. Simulating for 60 seconds...");
    println!("--------------------------------------------------");

    while start_time.elapsed() < duration {
        let tick_start = Instant::now();

        // Every 10 ticks (1 second), check for control overrides
        if ticks % 10 == 0 {
            if let Ok(content) = std::fs::read_to_string("control_override.json") {
                if let Ok(val) = serde_json::from_str::<serde_json::Value>(&content) {
                    // 1. Process isolation command
                    if let Some(isolated_zones) = val.get("isolated_zones").and_then(|z| z.as_array()) {
                        for zone_val in isolated_zones {
                            if let Some(zone_id) = zone_val.as_u64() {
                                let zone_id = zone_id as u8;
                                for sensor in &mut sim.sensors {
                                    if sensor.zone == zone_id && sensor.scenario != Scenario::Normal {
                                        println!("Closed-loop: Process isolation command received. Resetting Zone {} sensor #{} to Normal.", zone_id, sensor.id);
                                        sensor.scenario = Scenario::Normal;
                                        sensor.ticks_in_scenario = 0;
                                        sensor.drift = 0.0;
                                    }
                                }
                            }
                        }
                    }

                    // 2. Sensor recalibration command
                    if let Some(recalibrated) = val.get("recalibrated_sensors").and_then(|r| r.as_array()) {
                        for sensor_val in recalibrated {
                            if let Some(sensor_id) = sensor_val.as_u64() {
                                let sensor_id = sensor_id as u16;
                                if let Some(sensor) = sim.sensors.iter_mut().find(|s| s.id == sensor_id) {
                                    println!("Closed-loop: Recalibration command received. Resetting sensor #{} drift.", sensor_id);
                                    sensor.drift = 0.0;
                                    sensor.scenario = Scenario::Normal;
                                    sensor.ticks_in_scenario = 0;
                                }
                            }
                        }
                    }
                }
            }
        }

        // 1. Tick SCADA Simulator
        let raw_events = sim.tick();
        ticks += 1;

        latest_results.clear();

        // 2. Process events through TTI Engine
        for mut event in raw_events {
            if event.zone == 255 {
                // Capture wind parameters
                if event.signal_id == 900 {
                    active_wind_speed = event.value;
                } else if event.signal_id == 901 {
                    active_wind_direction = event.value;
                }
                // Push directly to ring buffer so Python can read it
                if let Err(e) = rb.try_push(&event) {
                    eprintln!("Ring buffer full, wind event dropped: {:?}", e);
                }
                continue;
            }

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
            let meta_bytes = rmp_serde::to_vec_named(&tti_result)?;
            event.meta = meta_bytes;

            // Save for dashboard rendering
            let name = format!("{} Sensor #{}", sensor_name(sensor.sensor_type), sensor.id);
            let zone_str = format!("ZONE {}", sensor.zone);
            latest_results.push((zone_str, name, tti_result.clone()));

            // Write enriched SCADA event to shared memory ring buffer
            if let Err(e) = rb.try_push(&event) {
                eprintln!("Ring buffer full, event dropped: {:?}", e);
            }

            // 3. If Gas Concentration sensor enters Warning/Critical, trigger Plume Dispersion model
            if sensor.sensor_type == SensorType::GasConcentration 
                && (tti_result.urgency == Urgency::Warning || tti_result.urgency == Urgency::Critical)
            {
                let now_inst = Instant::now();
                let should_compute = match last_plume_calc.get(&event.signal_id) {
                    None => true,
                    Some(&last) => now_inst.duration_since(last) >= Duration::from_secs(5),
                };

                if should_compute {
                    last_plume_calc.insert(event.signal_id, now_inst);

                    // Estimate emission rate Q (leak_rate = slope * calibration_factor)
                    // Ensure positive emission rate of at least 0.01 kg/s
                    let slope = tti_result.slope.max(0.01);
                    let emission_rate = slope * 0.05;

                    // Place source at the center of the zone it belongs to
                    let source_zone = sensor.zone as usize;
                    let source_x = zone_boundaries[source_zone].center_x;
                    let source_y = zone_boundaries[source_zone].center_y;

                    let plume_params = PlumeParams {
                        source_x,
                        source_y,
                        emission_rate_kg_s: emission_rate,
                        wind_speed_m_s: active_wind_speed,
                        wind_direction_deg: active_wind_direction,
                        stability_class: 'D',      // stability D (neutral)
                        gas_name: "H2S".to_string(),
                        threshold_ppm: 50.0,       // IDLH for H2S
                        molecular_weight: 34.08,   // MW
                    };

                    let plume_res = plume_engine.compute(&plume_params, &zone_boundaries);

                    // Save plume details for console dashboard
                    if let Some(pos) = active_plumes.iter().position(|p| p.0 == sensor.zone) {
                        active_plumes[pos] = (sensor.zone, plume_res.hazard_radius_m);
                    } else {
                        active_plumes.push((sensor.zone, plume_res.hazard_radius_m));
                    }

                    // Serialize PlumeResult into MsgPack bytes
                    let plume_meta = rmp_serde::to_vec_named(&plume_res)?;

                    // Create PLUME event (src = 4)
                    let plume_event = SensorEvent {
                        ts: event.ts,
                        src: 4, // PLUME
                        zone: sensor.zone,
                        signal_id: sensor.id,
                        value: plume_res.hazard_radius_m,
                        meta: plume_meta,
                    };

                    if let Err(e) = rb.try_push(&plume_event) {
                        eprintln!("Ring buffer full, plume event dropped: {:?}", e);
                    }
                }
            } else if sensor.sensor_type == SensorType::GasConcentration {
                // Remove plume if gas sensor drops below warning
                if let Some(pos) = active_plumes.iter().position(|p| p.0 == sensor.zone) {
                    active_plumes.remove(pos);
                }
            }
        }

        // 4. Print Console Dashboard every 1 second
        if !std::env::var("AEGIS_UNTHROTTLED").is_ok() && last_dashboard_print.elapsed() >= Duration::from_secs(1) {
            last_dashboard_print = Instant::now();

            // Sort results: Critical first, then Warning, then Watch, then Normal
            // Within the same urgency, sort by TTI ascending
            latest_results.sort_by(|a, b| {
                let urgency_ord = b.2.urgency.cmp(&a.2.urgency);
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

            if !active_plumes.is_empty() {
                println!("---------------------------------------------------------------------");
                println!("ACTIVE PLUME DISPERSION MODELS:");
                for (zone_id, radius) in &active_plumes {
                    println!("ZONE {} | Consequence Hazard Radius: {:.1}m (IDLH threshold 50ppm)", zone_id, radius);
                }
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
