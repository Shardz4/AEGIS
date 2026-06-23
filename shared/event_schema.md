# AEGIS Event Protocol Schema

This document defines the binary message format used in the shared-memory ring buffer for inter-process communication between the Rust Core and the Python Reasoning Brain.

## Event Serialization Format

All events are serialized using **MessagePack** (via `rmp-serde` in Rust and `msgpack-python` in Python) to ensure cross-language compatibility, compact size, and high-performance serialization/deserialization.

Each event consists of a 4-byte little-endian length prefix followed by the MessagePack payload bytes:

```
┌──────────────────────────────┬───────────────────────────────┐
│ Length Prefix (u32, 4 bytes) │ MessagePack Payload (N bytes) │
└──────────────────────────────┴───────────────────────────────┘
```

## SensorEvent Object Structure

The payload deserializes to a dictionary/map containing the following fields:

| Field Name | MsgPack Key | Type | Description |
|---|---|---|---|
| `ts` | `ts` | `u64` | Unix timestamp in microseconds |
| `src` | `src` | `u8` | Source type identifier (see below) |
| `zone` | `zone` | `u8` | Plant zone ID (typically 0-15) |
| `signal_id` | `signal_id` | `u16` | Unique sensor or camera ID |
| `value` | `value` | `f64` | The raw sensor reading or detection confidence |
| `meta` | `meta` | `bytes` | Optional binary metadata (up to 256 bytes) |

### Source Type Identifiers (`src` enum)
- `0`: SCADA telemetry (sensor readings)
- `1`: CCTV video analytics (object tracking, bounding boxes)
- `2`: PERMIT state changes
- `3`: FATIGUE telemetry (operator wearable metrics)
- `4`: PLUME consequence overlays (Gaussian plume simulation results)

---

## Metadata Field Formats (`meta` payloads)

To maintain high throughput on the shared memory buffer, additional structured data is packed into the `meta` field as serialized MsgPack sub-objects based on the `src`.

### 1. SCADA with TTI Annotations (`src = 0`)
When a SCADA sensor is enriched by the Rust TTI engine, the `meta` field contains a serialized `TtiResult`:
```json
{
  "tti_seconds": float or null, // Predicted time to threshold breach in seconds
  "slope": float,               // Current slope of linear trend (units/sec)
  "r_squared": float,           // R² coefficient of linear fit (confidence)
  "urgency": int                // Urgency code: 0=NORMAL, 1=WATCH, 2=WARNING, 3=CRITICAL
}
```

### 2. Plume Simulation Results (`src = 4`)
For plume event notifications, the `meta` field contains a serialized `PlumeResult`:
```json
{
  "hazard_radius_m": float,
  "hazard_polygon": [[float, float], ...], // List of local coordinates forming the polygon
  "max_concentration_ppm": float,
  "affected_zones": [int, ...]
}
```
