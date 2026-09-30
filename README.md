# Real-Time Cyber-Attack Detection for a Water-Treatment ICS

Software-only implementation of a **detection-in-depth** security framework for a
simulated multi-stage water-treatment plant. Combines three cooperating layers:

1. **Protocol-aware rule-based DPI** — decodes Modbus writes and raises
   interpretable, PA-NIDS-style alerts (which device, what action, what value).
2. **LSTM sequence anomaly detection** — learns normal temporal correlations
   across sensors/flows to catch stealthy or unseen attacks the rules miss.
3. **Tamper-evident ledger** — a signed hash-chain (Hyperledger Fabric optional)
   giving a forensic, tamper-evident audit trail of every command and alert.

Plus an operator dashboard (FastAPI + WebSocket) and a quantitative evaluation
(precision / recall / FPR / detection latency) against single-layer baselines.

> **No physical hardware.** The plant is a Python physics model that exchanges
> real **Modbus TCP** traffic with a Python controller and an attacker over local
> TCP connections. The DPI layer inspects a log of those requests, written by the
> traffic generator with the fields a packet decoder would extract (a `tshark`
> packet capture was not implemented). See `docs/` for the protocol-substitution
> rationale (Modbus in place of ENIP/CIP).

## Architecture

```
[ Python plant simulator ] <--- Modbus TCP ---> [ Python controller (HMI) ]
                                   ^
                                   |  [ attacker ]
        device log (1 Hz)          |  network log (every request, decoded)
               |                   |          |
       [ LSTM detector ]    [ Rule DPI ]   [ NetFlow/DoS monitor ]
               \                   |          /
                +------> [ correlator ] <----+
                         |              |
          [ hash-chain ledger ]   [ FastAPI + WebSocket dashboard ]
```

## Status

| Phase | Component | State |
|------|-----------|-------|
| 0 | Repo scaffold, venv, docker-compose | **done** |
| 2 | Plant physics + Modbus TCP server + soft-PLC | **done** |
| 3 | Traffic generation + labelled dataset | **done** |
| 4 | Protocol-aware DPI rule engine | **done** |
| 5 | LSTM detector + NetFlow/DoS monitor | **done** |
| 6 | Hash-chain ledger + correlator + dashboard | **done** |
| 7 | Attack suite + evaluation + ablation | **done** |

## Tamper-evident ledger + correlator (Phase 6)

**Correlator** ([`detect/correlator/`](detect/correlator/correlator.py)) merges the
three detectors into one incident stream and writes every control command and
alert to the ledger. Run the whole pipeline (coverage table + ledger + tamper
demo):

```bash
python -m detect.correlator.run
```

**Hash-chain ledger** ([`ledger/hashchain.py`](ledger/hashchain.py)) — an
append-only, signed audit trail behind a [`LedgerBackend`](ledger/backend.py)
interface (so Hyperledger Fabric can drop in later). Each entry chains to the
previous by SHA-256 and is signed with Ed25519; `verify()` detects and localises
any edit, deletion, reordering, or forged signature. The live dashboard shows the
ledger with an INTACT/COMPROMISED badge and a **Tamper with log** button that
demonstrates detection in the browser.

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
[`data/README.md`](data/README.md). The network log is written by the generator
itself, which records each Modbus request it sends with the fields a packet
decoder would extract. Capturing the frames with `tshark` and decoding the pcap
would give the same schema but was not implemented.

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

## LSTM anomaly detector + NetFlow monitor (Phase 5)

The two layers that cover what the DPI rules cannot.

**NetFlow/DoS monitor** — unsupervised volume detector. Learns the normal
per-window request rate and flags any source that floods above it:

```bash
python -m detect.netflow.monitor --network-log data/run1/network_log.csv
```
Catches all flooding windows with 0 false positives.

**LSTM autoencoder** — learns normal temporal patterns of the whole process from
`device_log.csv`; a per-feature standardised reconstruction error flags windows
that don't match normal behaviour. Crucially it catches the **stealth
manipulation** (a compromised-HMI command that is protocol-valid, so the DPI layer
cannot see it), and names the most abnormal signal:

```bash
python -m detect.lstm.train  --device-log data/run1/device_log.csv   # train on normal
python -m detect.lstm.detect --device-log data/run1/device_log.csv   # score + report
```
On `data/run1` it catches false data injection, command injection and stealth in
every window, with no false positives on windows of normal operation. It cannot
see flooding or replay, which leave the process unchanged. Model in
[`detect/lstm/model.py`](detect/lstm/model.py).

### Detection-in-depth coverage

| Attack | DPI (Phase 4) | NetFlow (Phase 5) | LSTM (Phase 5) |
|---|---|---|---|
| false data injection | ✅ | | ✅ |
| command injection | ✅ | | ✅ |
| replay | ✅ | | |
| flooding / DoS | | ✅ | |
| stealth manipulation | | | ✅ |

Every attack is covered by at least one layer — the point of the layered design.

## Evaluation & ablation (Phase 7)

Scores each layer and the combined system (precision / recall / FPR / F1,
per-class recall, detection latency) and writes plots + JSON:

```bash
python -m eval.evaluate     # -> eval/results/{ablation.png, per_class_recall.png, results.json}
```

Headline result on `data/run1` (our simulator): no single layer flags more than
60% of attack seconds, while the **combined** system flags **every attack second
(recall 1.00) at 0.89 precision** and alerts in the first second of every attack.
All of its false positives are LSTM alerts in the 9 seconds after an attack ends,
where its 10-second window still overlaps the attack. Full numbers and methodology in [`docs/results.md`](docs/results.md).
These are simulator results; see the external validation below for how the LSTM
layer holds up on real data.

## External validation on the public HAI dataset

To test generalisation beyond our own data, the LSTM detector was trained and
tested on **HAI 22.04**, a real hardware-in-the-loop ICS testbed with labelled
attacks (~1% of the time):

```bash
python -m eval.hai_validate     # needs data/public/hai/{train1,test1}.csv
```

The approach does **not** generalise well. Trained on one day, the score ranks
attacks above normal (ROC-AUC **0.74**) but its threshold flags ~94% of the test
day. Trained on three recordings (117 h) with the threshold set on a separate
held-out normal recording, false alarms fall to ~0.1%, but the best deployable
detector (plain MSE) catches only **2 of 7** attack episodes. The cause is that
HAI's test day runs in operating modes absent from every training recording, which the model mistakes for attacks. The
simulator results should therefore be read as optimistic. Full results,
diagnosis, and future work in [`docs/hai_validation.md`](docs/hai_validation.md).

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

## Docker (prepared, not used by the experiments)

`docker-compose.yml` defines the plant service plus optional OpenPLC and
PostgreSQL services that were set up for future work. None of the experiments
use them: control is done by the Python controller, the ledger is kept in memory
or a JSON-lines file, and no OpenPLC program has been written yet (`plc/` is
empty). The plant's `--no-control` flag is there so an external PLC can take
over the actuators later.

## Layout

```
sim/       plant physics (plant.py), register map (register_map.py), Modbus server
net/       actors, attack scenarios, transaction schema, dataset generator
detect/    dpi/ (rule engine)  lstm/ (sequence model)  netflow/  correlator/
ledger/    LedgerBackend interface and HashChainLedger
app/       FastAPI backend + WebSocket dashboard
eval/      metrics, ablation, HAI validation, plots
report/    figure generator and figures for the final report
demo/      demo GIF / video generators
data/      generated datasets (gitignored); public datasets under data/public
docs/      protocol-substitution rationale, results, HAI validation
tests/     pytest suite
```

## Register map (SWaT-style tags)

Sensors and actuators use the SWaT naming from the reference papers (LIT101,
MV101, P101, AIT202, ...) so the proposal's attack→layer mapping table applies
directly. Full definitions with addresses, units, and safe bands live in
[`sim/register_map.py`](sim/register_map.py).
