# AEGIS — Adaptive Engine for Graded Industrial Safety

AEGIS is a high-performance, predictive process-safety intelligence system designed for industrial facilities. It fuses SCADA telemetry, CCTV video analytics, permit-to-work data, operator fatigue metrics, and regulatory standards to provide safety officers with actionable, citation-backed incident warnings *before* traditional threshold alarms fire.

---

## 🏗️ System Architecture Overview
The system is divided into three primary processing layers linked by high-performance protocols:

1. **Rust Core**: A high-performance, low-latency engine responsible for SCADA ingestion, CCTV frame grabs, Time-To-Incident (TTI) trend estimation, and Gaussian plume consequence simulations. Runs on a `<50ms` tick path.
2. **Shared-Memory Ring Buffer IPC**: A lock-free shared-memory ring buffer connecting Rust and Python, enabling high-throughput data transfer.
3. **Python Reasoning Brain**: A probabilistic intelligence layer that uses a Bayesian risk network (`pgmpy`) and a dynamic equipment-permit graph (`networkx`) to assess safety risks, and a retrieval-augmented generation (RAG) narrator to generate operator alerts with regulatory citations.
4. **Dashboard Web Console**: An interactive, high-contrast, minimalist operator console built with custom styling, real-time WebSocket telemetry, interactive map rendering, voice announcements, and closed-loop mitigation control inputs.

---

## 🚀 Advanced Implemented Features

### 1. Safe Evacuation Routing & Dynamic Site-Map Loader (Plan 1)
* **Dynamic Site-Map Loader**: Allows loading custom plant topologies dynamically from a JSON configuration, resetting zone nodes, Euclidean coordinates, and adjacencies, while maintaining linked equipment and sensors.
* **Risk Slashing Pathfinder**: Uses Dijkstra's algorithm to calculate the safest path from any zone to the Safe Haven (Zone E - Control Room). It applies a dynamic cost calculation:
  * Blocks impassable zones (active gas plumes or critical risk $\ge 70\%$) with near-infinite cost.
  * Penalizes ("slashes") zones with active permits (e.g. Hot Work, Confined Space) or minor anomalies (elevated temperature/pressure) to route personnel away from potential hazards.

### 2. Dynamic Wind Vector Ingestion & Real-Time Plume Rotation (Plan 2)
* **SCADA Wind Drift**: SCADA simulates dynamic wind speed and direction changes (drifts) using Gaussian noise, emitting global telemetry events on Zone 255 (Signals 900 and 901).
* **Plume Dispersion & Rotation**: The Rust core pipeline consumes wind telemetry to calculate the angle and spread of the gas leak plume. The dashboard maps this to rotate the canvas wind rose needle and align the plume overlay dynamically.

### 3. Voice-Synthesized Control Room Announcements (Plan 3)
* **Audio Alerts**: Leverages the Web Speech Synthesis API to announce critical safety alerts over control room loudspeakers.
* **Operator Toggle**: Features a high-contrast `VOICE ON` / `VOICE OFF` button in the dashboard console header. When active, it automatically reads the location, risk score, urgency statement, and first prioritized action item of incoming alarms.

### 4. Interactive Closed-Loop Mitigation Controls (Plan 4)
* **Permit Cancellation & Zone Isolation**: Alert cards display actionable buttons allowing safety officers to intervene:
  * **Cancel Permit**: revokes high-risk conflicting permits (e.g., Hot Work during gas leak), which propagates to the Python `PermitStore` and reduces the zone's risk score.
  * **Isolate Feed**: writes an isolation command to `control_override.json` in the workspace root. The Rust SCADA pipeline reads this override and resets all sensor scenarios in the isolated zone to normal, eliminating the hazard.

### 5. Sensor Malfunction Detection with Spatial Voting (Plan 6)
* **MAD Outlier Checks**: Compares the 25 spatial sensors of the same type within each zone. Applies a Median Absolute Deviation (MAD) statistical outlier test with a threshold floor (`0.1 * baseline`) to identify malfunctioning equipment in low-noise conditions.
* **Spatial Voting**:
  * **$\le 2$ sensors deviate**: Classified as a `SENSOR_MALFUNCTION`. The sensor is flagged as faulty, shows `[FAULT]` / `FAULTY SENSOR` on the dashboard, and is excluded from Bayesian risk and TTI urgency calculations to prevent false alarms.
  * **$> 2$ sensors deviate**: Voted as a `PROCESS_ANOMALY` (real hazard), and the risk assessment escalates normally.

---

## 📂 Repository Directory Layout
* `rust_core/`: Rust workspace containing the SCADA simulation and pipeline processor.
  * `bin/src/main.rs`: The pipeline daemon processing telemetry, TTI, and plumes.
  * `scada_sim/`: SCADA simulation generating drift telemetry.
  * `ring_buffer/`: Lock-free shared-memory ring buffer.
* `python_brain/`: Python package housing the Bayesian network, permit graph, and RAG narrator.
  * `src/aegis/risk/batch_processor.py`: The core telemetry and risk evaluation processor.
  * `tests/`: Automated test suite (`test_ipc.py`, `test_routing.py`, `test_mitigation.py`, `test_malfunction.py`).
* `dashboard/`: Web app dashboard resources (HTML, CSS, JS, server).
  * `server.py`: Python web server serving dashboard and managing WebSocket broadcasts.
  * `js/app.js`: Main frontend coordinator.
  * `js/charts.js`: Manager drawing sparklines and handling malfunction canvas states.
* `shared/`: Event schema and protocol documentation.

---

## 🛠️ Installation & Setup

### Prerequisites
* Rust (Cargo)
* Python 3.10+
* Playwright/Browser (for UI automation)

### Rust Build
```bash
cd rust_core
cargo build --release
```

### Python Dependencies
```bash
pip install -e python_brain/
```

---

## 🧪 Running the Verification Test Suites

To execute the automated unit tests, run the following commands from the workspace root:

### 1. IPC Integration Tests
```bash
python -m pytest python_brain/tests/test_ipc.py
```

### 2. Evacuation Routing & Risk Slashing Tests
```bash
python -m pytest python_brain/tests/test_routing.py
```

### 3. Closed-Loop Mitigation Tests
```bash
python -m pytest python_brain/tests/test_mitigation.py
```

### 4. Sensor Malfunction Detection & Outlier Tests
```bash
python -m pytest python_brain/tests/test_malfunction.py
```

---

## 💻 Running the Live Console Dashboard

1. **Start the Web Dashboard Server**:
   ```bash
   python dashboard/server.py
   ```
   The dashboard will be available at `http://localhost:8080/`.

2. **Trigger the Demo Scenario**:
   * Open `http://localhost:8080/` in your browser.
   * Click **RUN DEMO** in the header.
   * Watch the timeline milestones:
     * **t=10s**: Gas leak starts in Zone C.
     * **t=20s**: Simulated sensor malfunction is injected on pressure sensor `SEN-18` (value: 95.0, urgency: critical). Observe the dashed gray line in the sparklines, `[FAULT]` display, and `1 SEN` fault badge in Reactor Area details, while Reactor Area risk remains normal.
     * **t=30s**: Hot Work permit starts in Zone C.
     * **t=60s**: Plume model visualizes gas spread.
     * **t=90s**: Malfunction clears, real alarm AL-02-0001 is triggered, and safe evacuation path shifts dynamically.
