use ring_buffer::{RingBuffer, SensorEvent};
use serde::Deserialize;
use std::net::SocketAddr;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::sync::mpsc;
use tokio::time::sleep;
use tokio_modbus::prelude::*;

#[derive(Debug, Deserialize, Clone)]
pub struct RegisterInput {
    pub register_address: u16,
    pub register_type: String, // "input" or "holding"
    pub zone: u8,
    pub signal_id: u16,
    pub scale: f64,
}

#[derive(Debug, Deserialize, Clone)]
pub struct CoilOutput {
    pub mitigation_type: String,
    pub zone: u8,
    pub coil_address: u16,
}

#[derive(Debug, Deserialize, Clone)]
pub struct ModbusConfig {
    pub plc_ip: String,
    pub plc_port: u16,
    pub poll_interval_ms: u64,
    pub inputs: Vec<RegisterInput>,
    pub outputs: Vec<CoilOutput>,
}

pub struct ModbusActuationCommand {
    pub zone: u8,
    pub action: String,
}

pub async fn run_modbus_ingest(
    config: ModbusConfig,
    ring_buffer_path: String,
    ring_buffer_capacity: u64,
    mut rx_actuation: mpsc::Receiver<ModbusActuationCommand>,
) {
    let mut ring_buffer = match RingBuffer::new(&ring_buffer_path, ring_buffer_capacity, false) {
        Ok(rb) => rb,
        Err(e) => {
            eprintln!("[Modbus] Failed to open RingBuffer: {:?}", e);
            return;
        }
    };
    let plc_addr = format!("{}:{}", config.plc_ip, config.plc_port);
    let socket_addr: SocketAddr = match plc_addr.parse() {
        Ok(addr) => addr,
        Err(e) => {
            eprintln!(
                "[Modbus] Invalid IP/port config: {}, error: {:?}",
                plc_addr, e
            );
            return;
        }
    };

    println!(
        "[Modbus] Starting client worker connecting to: {}",
        socket_addr
    );

    // Actuation task that listens for incoming operator commands
    let outputs_cfg = config.outputs.clone();
    tokio::spawn(async move {
        while let Some(cmd) = rx_actuation.recv().await {
            if let Some(target_coil) = outputs_cfg
                .iter()
                .find(|o| o.zone == cmd.zone && o.mitigation_type == cmd.action)
            {
                println!(
                    "[Modbus] Actuating coil address {} for Zone {} mitigation command '{}'",
                    target_coil.coil_address, cmd.zone, cmd.action
                );

                // Establish connection for command writing
                match tcp::connect(socket_addr).await {
                    Ok(mut client) => {
                        match client
                            .write_single_coil(target_coil.coil_address, true)
                            .await
                        {
                            Ok(_) => println!("[Modbus] Coil actuation write succeeded!"),
                            Err(e) => eprintln!("[Modbus] Failed to write coil: {:?}", e),
                        }
                    }
                    Err(e) => eprintln!("[Modbus] Failed to connect for actuation: {:?}", e),
                }
            }
        }
    });

    // Telemetry polling loop
    let inputs = config.inputs.clone();
    let poll_interval = Duration::from_millis(config.poll_interval_ms);

    loop {
        match tcp::connect(socket_addr).await {
            Ok(mut client) => {
                println!("[Modbus] Connected to PLC. Starting register polling.");
                loop {
                    let start_tick = std::time::Instant::now();

                    for input in &inputs {
                        let result = match input.register_type.as_str() {
                            "holding" => {
                                client
                                    .read_holding_registers(input.register_address, 1)
                                    .await
                            }
                            _ => client.read_input_registers(input.register_address, 1).await,
                        };

                        match result {
                            Ok(vals) => {
                                if let Some(&raw_val) = vals.first() {
                                    let scaled_val = raw_val as f64 * input.scale;
                                    let now_sec = SystemTime::now()
                                        .duration_since(unch_epoch())
                                        .unwrap_or_default()
                                        .as_secs();

                                    let event = SensorEvent {
                                        ts: now_sec,
                                        src: 2, // Source 2 = Modbus Ingest
                                        zone: input.zone,
                                        signal_id: input.signal_id,
                                        value: scaled_val,
                                        meta: Vec::new(),
                                    };

                                    if let Err(e) = ring_buffer.try_push(&event) {
                                        eprintln!("[Modbus] RingBuffer push failed: {:?}", e);
                                    }
                                }
                            }
                            Err(e) => {
                                eprintln!(
                                    "[Modbus] Polling error on address {}: {:?}",
                                    input.register_address, e
                                );
                            }
                        }
                    }

                    let elapsed = start_tick.elapsed();
                    if elapsed < poll_interval {
                        sleep(poll_interval - elapsed).await;
                    }
                }
            }
            Err(e) => {
                eprintln!(
                    "[Modbus] Connection failed to {}: {:?}. Retrying in 5 seconds...",
                    socket_addr, e
                );
                sleep(Duration::from_secs(5)).await;
            }
        }
    }
}

// Helper to represent UNIX_EPOCH securely
fn unch_epoch() -> SystemTime {
    UNIX_EPOCH
}
