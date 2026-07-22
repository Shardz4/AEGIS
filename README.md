# 🛡️ AEGIS — Adaptive Engine for Graded Industrial Safety

**AEGIS** is a high-performance, predictive process-safety intelligence platform designed for high-consequence industrial facilities (petroleum refineries, chemical processing plants, and nuclear installations). By fusing real-time SCADA telemetry, CCTV computer vision analytics, active permit-to-work data, operator fatigue metrics, and regulatory standards, AEGIS provides plant operators with actionable, citation-backed safety warnings and automated risk mitigation **well before** traditional static threshold alarms fire.

---

## 🏗️ System Architecture & Multi-Engine Topology

AEGIS utilizes a high-throughput, dual-engine hybrid architecture joined by zero-copy inter-process communication:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           INDUSTRIAL DATA SOURCES                       │
│    [SCADA Sensors]       [OPC UA Historian]        [Modbus TCP PLCs]    │
└───────────┬──────────────────────┬────────────────────────┬─────────────┘
            │                      │                        │
            ▼                      ▼                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          RUST HIGH-SPEED CORE                           │
│  • Signal Drift (CUSUM)      • MAD Spatial Outlier Voting               │
│  • Time-To-Incident (TTI)    • Pasquill-Gifford Plume Dispersion Model  │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │ Shared-Memory Ring Buffer   │  <50ms Lock-Free IPC
                    └──────────────┬──────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       PYTHON REASONING BRAIN                            │
│  • Bayesian Risk Net (pgmpy) • Dynamic Dijkstra Evacuation Pathfinder   │
│  • Permit Store (NetworkX)   • RAG Regulatory Narrator (OSHA & OISD)    │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
                                   ▼ WebSockets (JSON API)
┌─────────────────────────────────────────────────────────────────────────┐
│                        OPERATOR WEB CONSOLE                             │
│  • Interactive Canvas Map    • Real-time Plume & Wind Vector Display    │
│  • Web Speech Audio Alerts   • Closed-Loop Mitigation Control Override  │
│  • Live OSHA Audit Table     • Sparkline Telemetry & Fault Badges       │
└─────────────────────────────────────────────────────────────────────────┘
```

1. **Rust Core Engine (`rust_core/`)**: Low-latency daemon operating on a `<50ms` processing loop. Ingests SCADA feeds, evaluates CUSUM trend drift, executes MAD spatial outlier voting, runs Pasquill-Gifford gas dispersion equations, and interfaces natively with Modbus TCP PLCs and OPC UA historians.
2. **Shared-Memory Ring Buffer IPC (`shared/`)**: A lock-free, zero-copy shared memory data structure enabling ultra-fast data transfer between the Rust core and Python brain.
3. **Python Reasoning Brain (`python_brain/`)**: Probabilistic intelligence layer using Bayesian Belief Networks (`pgmpy`) and equipment-permit graph structures (`networkx`) for multi-hazard risk assessment, alongside a vector-embedded RAG engine (`chromadb`) for generating regulatory citation-backed alerts.
4. **Dashboard Web Console (`dashboard/`)**: A sleek, dark-mode glassmorphism web console rendering real-time 2D schematic plant maps, dynamic evacuation vectors, sparkline charts, speech-synthesized audio warnings, and closed-loop control actuation inputs.

---

## 🚀 Complete Feature Breakdown

### 1. SCADA Telemetry Ingestion & Time-To-Incident (TTI) Forecasting
* **Continuous Trend Analysis**: Evaluates high-frequency signal streams across all 8 plant zones.
* **CUSUM Statistical Drift Detection**: Applies Cumulative Sum (CUSUM) control charts to identify subtle, gradual sensor calibration decay before value limits are breached.
* **Linear Regression TTI Estimator**: Computes continuous linear regressions over rolling sensor windows to forecast the exact **Time-To-Incident (TTI)** in seconds, giving operators vital lead time to intervene prior to emergency shutdowns.

### 2. Spatial Sensor Malfunction Isolation (MAD Spatial Voting)
* **Median Absolute Deviation (MAD) Outlier Test**: Evaluates groups of 25 spatial sensors per zone against a dynamic baseline floor (`0.1 * baseline`) to detect faulty equipment under low-noise conditions.
* **Spatial Voting Decision Logic**:
  * **$\le 2$ sensors deviate**: Flagged as a `SENSOR_MALFUNCTION`. The reading is marked as `[FAULT]`, rendered as a dashed gray line on UI sparklines, and excluded from Bayesian risk modeling to eliminate alarm fatigue.
  * **$> 2$ sensors deviate**: Voted as a `PROCESS_ANOMALY` (validated physical hazard), triggering risk escalation and emergency protocol dispatch.

### 3. Multi-Modal CCTV AI Vision & RAG Citation Engine
* **Computer Vision Analytics**: Ingests camera feeds (e.g. `CAM-C-301`) to detect Personal Protective Equipment (PPE) non-compliance (missing safety eyewear/helmets) and visual smoke/fire with high confidence scores (e.g., 94–98%).
* **Context-Rich RAG Alert Generation**: Queries a vector store of regulatory standards using semantic embedding search.
* **Automated Citation Matching**: Automatically attaches relevant OSHA (1910.132, 1910.119) and OISD-STD-116 clause excerpts and similarity relevance scores directly onto operator alert cards.
* **RAG Abstention Guardrails**: Includes automated abstention flags when condition metrics exceed known regulatory bounds or lack specific statutory mandates.

### 4. Dynamic Site Evacuation Pathfinder (Risk-Slashed Dijkstra)
* **Configurable Site Map Topology**: Loads customized plant layout JSON configurations defining 2D coordinates, adjacencies, linked equipment, and spatial sensor nodes.
* **Dynamic Dijkstra Evacuation Routing**: Continuously computes the lowest-risk evacuation route from any hazardous zone to designated safe havens (Control Room - Zone E).
* **Risk Slashing Cost Function**: Assigns near-infinite cost weights to blocked or active hazard zones ($\ge 70\%$ risk score or active gas plume), while applying dynamic cost penalties for active permits (Hot Work, Confined Space) to steer evacuating personnel safely around evolving hazards.

### 5. Pasquill-Gifford Gas Plume Dispersion & Wind Vector Modeling
* **Gaussian Consequence Modeling**: Calculates atmospheric dispersion footprints based on gas molecular weight, leak release rate (kg/s), and Pasquill-Gifford atmospheric stability classes.
* **SCADA Wind Drift Telemetry**: Ingests real-time global wind speed and direction telemetry (0°–360°).
* **Interactive Canvas Overlay**: Rotates the UI compass wind rose needle in real time and projects an animated, semi-transparent gas plume footprint matching active wind direction and hazard boundaries.

### 6. Voice-Synthesized Control Room Announcements
* **Speech Synthesis Integration**: Leverages the Web Speech Synthesis API to broadcast clear, automated safety instructions over control room loudspeakers.
* **Operator Console Controls**: Includes a header `VOICE ON` / `VOICE OFF` toggle. When active, it automatically reads out the incident location, risk severity score, urgency statement, and first prioritized action item.

### 7. Closed-Loop Mitigation & Control Override Pipeline
* **Interactive Action Cards**: Provides direct execution controls on UI alert cards:
  * **Cancel Permit**: Revokes conflicting permits (e.g., Hot Work PTW-8022 during a gas release), updating the Python `PermitStore` and recalculating zone risk scores.
  * **Isolate Feed**: Writes an isolation payload to `control_override.json`. The Rust SCADA engine reads the override, triggers simulated valve closure, stops the leak, and clears the gas plume.
  * **Acknowledge & Clear**: Dismisses verified CCTV PPE alerts and restores camera status to nominal.

### 8. Native Industrial Protocol Ingestion (OPC UA & Modbus TCP)
* **Pure-Rust OPC UA TCP Client**: Establishes raw TCP sockets with plant historians using custom Hello/Acknowledge (`HEL`/`ACK`) handshakes, Chunk Header parsing, and monitored tag subscriptions.
* **Modbus TCP PLC Client**: Connects asynchronously to Edge PLCs via `tokio-modbus` to poll Input Registers and Holding Registers mapped to AEGIS signals.
* **Closed-Loop PLC Coil Actuation**: Translates dashboard mitigation inputs into digital output coil writes (Function Codes `0x05`/`0x0F`) to physically close edge valves or activate deluge pumps.
* **Dynamic Industrial Tag Mapping**: Configurable `industrial_config.json` schema mapping NodeIds and Register offsets directly to internal AEGIS signal structures.

### 9. Regulatory Auditing & OSHA PSM / ISO 45001 Compliance Tracking
* **Live Compliance Dashboard Table**: Audits plant operating conditions in real time against key regulatory clauses.
* **OSHA 1910.119(f) — Emergency Operating Procedures**: Tracks Emergency Shutdown (ESD) readiness and active evacuation path availability.
* **OSHA 1910.119(j) — Mechanical Integrity**: Audits testing schedules for safety-critical systems (e.g., deluge pumps). Features an interactive **Run Test** button to execute on-demand compliance verification and set status to `COMPLIANT`.
* **OISD-STD-116 Sec 5.3 — Hot Work LEL Limits**: Automatically flags unsafe Hot Work permits active in zones where combustible gas exceeds 10% LEL, offering one-click permit revocation.

### 10. Step-by-Step Interactive & Automated Pitch Demo Runner
* **Orchestration Script (`run_automated_demo.py`)**: Executes a complete 10-slide feature walkthrough. Automatically boots the web server, opens the browser, and steps through scenarios (SCADA TTI, CCTV RAG, Evacuation Pathfinder, Plume rotation, Permit conflicts, MAD voting, Closed-loop isolation, Industrial protocols, and Compliance tracking).
* **Flexible Execution Modes**: Supports manual step-through (pressing **ENTER**) or direct dashboard button interaction.

---

## 📂 Repository Layout

```
et_hack/
├── .gitignore                      # Git exclusion rules (build artifacts, overrides, scripts)
├── README.md                       # Complete system documentation
├── run_automated_demo.py           # Pitch & live demonstration orchestrator script
├── control_override.json           # Shared control override trigger file (generated at runtime)
│
├── rust_core/                      # High-Performance Rust Engine
│   ├── Cargo.toml                  # Workspace Cargo dependencies
│   ├── bin/
│   │   ├── industrial_config.json  # OPC UA NodeId and Modbus Register address mappings
│   │   └── src/
│   │       ├── main.rs             # SCADA processing daemon & ring buffer writer
│   │       ├── modbus_client.rs    # Tokio Modbus TCP polling & coil write client
│   │       └── opcua_client.rs     # OPC UA TCP subscription & handshake client
│   ├── scada_sim/                  # SCADA telemetry simulation library
│   ├── ring_buffer/                # Shared-memory lock-free IPC implementation
│   └── plume_sim/                  # Pasquill-Gifford atmospheric plume dispersion model
│
├── python_brain/                   # Probabilistic & AI Intelligence Engine
│   ├── pyproject.toml              # Python package metadata & dependencies
│   ├── src/aegis/
│   │   ├── ipc/reader.py           # Shared-memory ring buffer reader interface
│   │   ├── rag/
│   │   │   ├── corpus.py           # Regulatory document corpus (OSHA / OISD standards)
│   │   │   └── retriever.py        # ChromaDB vector retrieval & RAG narrator
│   │   └── risk/
│   │       ├── batch_processor.py  # Telemetry stream & multi-hazard risk engine
│   │       ├── bayesian_net.py     # pgmpy Bayesian belief network model
│   │       └── permit_store.py     # NetworkX active permit & equipment graph
│   └── tests/                      # Automated Test Suite
│       ├── test_cctv.py            # Vision analytics & alert tests
│       ├── test_drift.py           # CUSUM drift detection tests
│       ├── test_industrial.py      # OPC UA & Modbus protocol ingestion tests
│       ├── test_ipc.py             # Shared memory IPC ring buffer integration tests
│       ├── test_malfunction.py     # MAD spatial sensor voting tests
│       ├── test_mitigation.py      # Closed-loop override & isolation tests
│       ├── test_narrator.py        # RAG regulatory citation & narrator tests
│       └── test_routing.py         # Dijkstra risk-slashed evacuation routing tests
│
├── dashboard/                      # Web Dashboard Console
│   ├── server.py                   # Async HTTP & WebSocket broadcast server
│   ├── index.html                  # Dashboard HTML layout
│   ├── css/                        # Custom CSS (styling, glassmorphism, animations)
│   └── js/                         # Frontend JS Modules
│       ├── alerts.js               # Alert card rendering & RAG citation formatting
│       ├── app.js                  # Main dashboard state & WebSocket controller
│       ├── charts.js               # Sparkline chart manager & fault badge renderer
│       ├── map.js                  # Canvas schematic plant map & plume renderer
│       └── voice.js                # Web Speech synthesis controller
│
└── shared/                         # Cross-language Schema Documentation
    └── event_schema.md             # Telemetry & alert IPC packet definitions
```

---

## 🛠️ Prerequisites & Installation

### Prerequisites
* **Rust**: `1.70+` (Cargo)
* **Python**: `3.10+`
* **Web Browser**: Modern browser (Chrome / Edge / Firefox) with JavaScript enabled

### 1. Build Rust Core Engine
```powershell
cd rust_core
cargo build --release
cd ..
```

### 2. Install Python Reasoning Brain Package
```powershell
pip install -e python_brain/
```

---

## 🧪 Running the Verification Test Suite

Run the full pytest suite from the root directory to verify all subsystem components:

```powershell
# Run all unit and integration tests
pytest python_brain/tests/

# Or run individual test modules:
python -m pytest python_brain/tests/test_ipc.py         # Ring Buffer IPC
python -m pytest python_brain/tests/test_routing.py     # Evacuation Pathfinder
python -m pytest python_brain/tests/test_mitigation.py  # Closed-Loop Isolation
python -m pytest python_brain/tests/test_malfunction.py # MAD Outlier Voting
python -m pytest python_brain/tests/test_cctv.py        # CCTV Vision Analytics
python -m pytest python_brain/tests/test_industrial.py  # OPC UA / Modbus Protocols
python -m pytest python_brain/tests/test_drift.py       # CUSUM Sensor Drift
python -m pytest python_brain/tests/test_narrator.py    # RAG Citation Engine
```

---

## 💻 Operating the System & Running Demos

### Option A: Launch Interactive Pitch & Feature Demo
To run the automated 10-slide feature showcase:
```powershell
python run_automated_demo.py
```
This command automatically starts `dashboard/server.py`, opens your web browser at `http://localhost:8080/`, and steps through each pitch slide. Press **ENTER** in the terminal to advance through slides or interact directly with the dashboard UI controls.

### Option B: Standalone Web Console Execution
1. Start the Dashboard Server:
   ```powershell
   python dashboard/server.py
   ```
2. Open `http://localhost:8080/` in your browser.
3. Click **RUN DEMO** in the dashboard header to initiate real-time telemetry simulation and alert triggers.

### Option C: Live Industrial Ingest Mode (OPC UA & Modbus TCP)
To connect the Rust Core daemon directly to physical PLCs and plant historians:
```powershell
# Set environment variable for industrial protocol ingestion
$env:AEGIS_INGEST_MODE="OPC_MODBUS"

# Execute Rust daemon
./rust_core/target/release/bin
```
Telemetry ingested via OPC UA monitored items and Modbus TCP registers will automatically stream through the shared-memory ring buffer into the Python risk engine and render live on the dashboard console.
