use serde::{Serialize, Deserialize};

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct SensorEvent {
    pub ts: u64,
    pub src: u8,
    pub zone: u8,
    pub signal_id: u16,
    pub value: f64,
    #[serde(with = "serde_bytes")]
    pub meta: Vec<u8>,
}
