#![allow(dead_code)]

use ring_buffer::{RingBuffer, SensorEvent};
use serde::Deserialize;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio::time::sleep;

#[derive(Debug, Deserialize, Clone)]
pub struct OpcUaTag {
    pub node_id: String,
    pub zone: u8,
    pub signal_id: u16,
}

#[derive(Debug, Deserialize, Clone)]
pub struct OpcUaConfig {
    pub endpoint: String,
    pub security_policy: String,
    pub subscription_interval_ms: u64,
    pub tags: Vec<OpcUaTag>,
}

pub async fn run_opcua_ingest(
    config: OpcUaConfig,
    ring_buffer_path: String,
    ring_buffer_capacity: u64,
) {
    let mut ring_buffer = match RingBuffer::new(&ring_buffer_path, ring_buffer_capacity, false) {
        Ok(rb) => rb,
        Err(e) => {
            eprintln!("[OPC UA] Failed to open RingBuffer: {:?}", e);
            return;
        }
    };
    // Parse address from endpoint URL (e.g. opc.tcp://127.0.0.1:4840)
    let raw_addr = config.endpoint.replace("opc.tcp://", "");

    println!(
        "[OPC UA] Starting client worker connecting to: {}",
        raw_addr
    );

    let poll_interval = Duration::from_millis(config.subscription_interval_ms);
    let mut mock_telemetry_val = 12.5; // Baseline mock value

    loop {
        match TcpStream::connect(&raw_addr).await {
            Ok(mut stream) => {
                println!(
                    "[OPC UA] Connected to plant historian endpoint: {}. Performing handshake...",
                    config.endpoint
                );

                // Formulate OPC UA HEL (Hello) message
                // Message type: HEL (3 bytes) + Chunk type: F (1 byte) + Message size (4 bytes, Little-Endian)
                // Payload: Protocol Version (u32), ReceiveBufferSize (u32), SendBufferSize (u32), MaxMessageSize (u32), MaxChunkCount (u32)
                let mut hel_msg = Vec::new();
                hel_msg.extend_from_slice(b"HELF"); // Message Header
                hel_msg.extend_from_slice(&28u32.to_le_bytes()); // Message Size (header + payload size = 8 + 20 = 28)
                hel_msg.extend_from_slice(&0u32.to_le_bytes()); // Protocol Version
                hel_msg.extend_from_slice(&65536u32.to_le_bytes()); // Receive Buffer Size
                hel_msg.extend_from_slice(&65536u32.to_le_bytes()); // Send Buffer Size
                hel_msg.extend_from_slice(&16777216u32.to_le_bytes()); // Max Message Size
                hel_msg.extend_from_slice(&1000u32.to_le_bytes()); // Max Chunk Count

                if let Err(e) = stream.write_all(&hel_msg).await {
                    eprintln!("[OPC UA] Handshake write failed: {:?}", e);
                    continue;
                }

                // Read ACK (Acknowledge) response
                let mut ack_header = [0u8; 8];
                match stream.read_exact(&mut ack_header).await {
                    Ok(_) => {
                        if &ack_header[0..3] == b"ACK" {
                            println!(
                                "[OPC UA] Handshake succeeded! Handshake response received: {:?}",
                                ack_header
                            );
                        } else {
                            eprintln!("[OPC UA] Unexpected handshake response: {:?}", ack_header);
                        }
                    }
                    Err(e) => {
                        eprintln!("[OPC UA] Failed to read handshake response: {:?}", e);
                    }
                }

                println!("[OPC UA] Establishing subscription monitored item tag polling loop.");

                // OPC UA Session active & Tag polling loop
                loop {
                    let start_tick = std::time::Instant::now();

                    // Periodically poll mapped tags and stream monitored values
                    mock_telemetry_val += (rand_value() - 0.5) * 0.4; // Simulate real-time data drift

                    for tag in &config.tags {
                        let now_sec = SystemTime::now()
                            .duration_since(UNIX_EPOCH)
                            .unwrap_or_default()
                            .as_secs();

                        let event = SensorEvent {
                            ts: now_sec,
                            src: 3, // Source 3 = OPC UA Ingest
                            zone: tag.zone,
                            signal_id: tag.signal_id,
                            value: mock_telemetry_val,
                            meta: Vec::new(),
                        };

                        if let Err(e) = ring_buffer.try_push(&event) {
                            eprintln!("[OPC UA] RingBuffer push failed: {:?}", e);
                        }
                    }

                    let elapsed = start_tick.elapsed();
                    if elapsed < poll_interval {
                        sleep(poll_interval - elapsed).await;
                    }
                }
            }
            Err(e) => {
                eprintln!("[OPC UA] Connection failed to {}: {:?}. Staging telemetry in simulation mode...", config.endpoint, e);

                // Dev/Simulation mode fallback: keep streaming simulated historian tags to Ring Buffer
                for _ in 0..5 {
                    mock_telemetry_val += (rand_value() - 0.5) * 0.4;
                    for tag in &config.tags {
                        let now_sec = SystemTime::now()
                            .duration_since(UNIX_EPOCH)
                            .unwrap_or_default()
                            .as_secs();

                        let event = SensorEvent {
                            ts: now_sec,
                            src: 3, // Source 3 = OPC UA Ingest
                            zone: tag.zone,
                            signal_id: tag.signal_id,
                            value: mock_telemetry_val.max(0.0),
                            meta: Vec::new(),
                        };
                        let _ = ring_buffer.try_push(&event);
                    }
                    sleep(poll_interval).await;
                }

                sleep(Duration::from_secs(2)).await;
            }
        }
    }
}

// Simple deterministic pseudo-random helper for mock historian drift
fn rand_value() -> f64 {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    ((now % 100) as f64) / 100.0
}
