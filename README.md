# Real-Time Cyber-Attack Detection for a Water-Treatment ICS

Software-only implementation of a **detection-in-depth** security framework for a
simulated multi-stage water-treatment plant. Combines three cooperating layers:

1. **Protocol-aware rule-based DPI** — decodes Modbus writes and raises
   interpretable, PA-NIDS-style alerts (which device, what action, what value).
2. **LSTM sequence anomaly detection** — learns normal temporal correlations
   across sensors/flows to catch stealthy or unseen attacks the rules miss.
3. **Tamper-evident ledger** — a signed hash-chain (Hyperledger Fabric optional)
   giving a forensic, tamper-evident audit trail of every command and alert.

Plus an operator dashboard (FastAPI + PostgreSQL) and a quantitative evaluation
(precision / recall / FPR / detection latency) against single-layer baselines.

> **No physical hardware.** The plant is a Python physics model driving a real
> **Modbus TCP** network on a Docker bridge, so the packets the DPI layer
> inspects are genuine. See `docs/` for the protocol-substitution rationale
> (Modbus in place of ENIP/CIP) and the full plan.

## Architecture

```
[ Python physics sim ] <--registers--> [ soft-PLC / OpenPLC control logic ]
        |                                          |
        +------------ Modbus TCP (Docker bridge, SPAN tap = tshark) ---------+
             |                    |                      |
      [ Rule DPI ]        [ LSTM detector ]      [ NetFlow/DoS monitor ]
             \                    |                      /
              +--------> [ correlator / alert bus ] <---+
                                  |
                       [ hash-chain ledger ] --(optional)--> [ Fabric ]
                                  |
                    [ FastAPI + PostgreSQL + WebSocket dashboard ]
```

## Status

| Phase | Component | State |
|------|-----------|-------|
| 0 | Repo scaffold, venv, docker-compose | **done** |
| 2 | Plant physics + Modbus TCP server + soft-PLC | **done** |
| 3 | Traffic generation + labelled dataset | **done** |
| 4 | Protocol-aware DPI rule engine | **done** |
| 5 | LSTM detector + NetFlow/DoS monitor | next |
| 6 | Hash-chain ledger + dashboard | ledger pending; **live dashboard demo done** |
| 7 | Attack suite + evaluation | pending |

## Dataset generation (Phase 3)

Generates a labelled dataset by running the plant with real HMI + attacker Modbus
traffic and a schedule of five attack scenarios (false-data-injection, command
injection, flooding/DoS, replay, stealth manipulation):

```bash
python -m net.generate_dataset --out-dir data/run1 --speedup 0
```

Produces `network_log.csv` (decoded Modbus transactions, for the DPI engine) and
`device_log.csv` (per-second historian record, for the LSTM). Both carry a
ground-truth `label` column. Schema and attack-class details in
[`data/README.md`](data/README.md). The network log is captured at the
application layer (equivalent to decoding a pcap); a real `tshark` pcap capture on
the Docker bridge is an optional WSL/Linux path yielding the same schema.

## Protocol-aware DPI rule engine (Phase 4)

The first real detector. It decodes each Modbus write and applies protocol-semantic
rules, emitting interpretable PA-NIDS-style alerts (targeted device, action,
value, source):

```bash
python -m detect.dpi.run --network-log data/run1/network_log.csv
```

Rules: unauthorised writer (command injection), sensor-register write (false data
injection), and out-of-band/illegal set-point. On the generated dataset it catches
false-data-injection, command-injection and replay at 100% with **0 false
positives**, and deliberately passes flooding (→ NetFlow layer) and stealth (→
LSTM layer) through — the detection-in-depth split. Engine in
[`detect/dpi/engine.py`](detect/dpi/engine.py); shared alert type in
[`detect/alert.py`](detect/alert.py).

## Web dashboard demo

A browser dashboard (a demo slice of Phase 6) runs the plant over real Modbus,
streams live values over WebSocket, and includes an **Inject attack** button that
performs a sustained false-data-injection on LIT101 so you can watch the sensor
go red and an alert fire — then **Clear** to recover.

```bash
.venv\Scripts\python -m app.dashboard      # open http://127.0.0.1:8000
```

There is also a terminal demo GIF generator for reports/slides:

```bash
.venv\Scripts\python -m demo.make_gif --out demo/plant_demo.gif
```

## Quick start (local, no Docker)

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt      # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # WSL/Linux

# Run the plant simulator (serves Modbus TCP on :5020, built-in soft-PLC on)
.venv\Scripts\python -m sim.modbus_server --port 5020 --dt 1.0

# In another shell: read live registers with any Modbus client, or run tests
.venv\Scripts\python -m pytest -q
```

## Run the testbed with Docker

```bash
docker compose up plant postgres          # plant on :5020, Postgres on :5432
docker compose --profile plc up           # add OpenPLC (drive plant with --no-control)
```

To hand actuator control to OpenPLC instead of the built-in soft-PLC, start the
plant with `--no-control` and upload the Structured Text program from `plc/`.

## Layout

```
sim/       plant physics (plant.py), register map (register_map.py), Modbus server
plc/       OpenPLC Structured Text control programs
net/       tshark capture + Scapy attack scripts (replay / FDI / flood)
detect/    dpi/ (rule engine)  lstm/ (sequence model)  netflow/  correlator/
ledger/    LedgerBackend interface, HashChainLedger, FabricLedger (stretch)
app/       FastAPI backend + WebSocket dashboard
data/      generated datasets + pcaps (gitignored) ; public datasets under data/public
eval/      metrics, ablation, plots
docs/      architecture + protocol-substitution rationale + results
tests/     pytest suite
```

## Register map (SWaT-style tags)

Sensors and actuators use the SWaT naming from the reference papers (LIT101,
MV101, P101, AIT202, ...) so the proposal's attack→layer mapping table applies
directly. Full definitions with addresses, units, and safe bands live in
[`sim/register_map.py`](sim/register_map.py).
