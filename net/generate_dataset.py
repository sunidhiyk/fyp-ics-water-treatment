"""
Phase 3 — labelled dataset generator.

Runs the simulated plant with realistic OT traffic and injects a schedule of
attack scenarios, recording the two raw data streams the proposal calls for:

  * network log  (data/<run>/network_log.csv) — every Modbus TCP transaction that
    crossed the (simulated) wire, decoded into src/dst, function code, targeted
    register, and written value. This is what the Phase-4 protocol-aware DPI
    engine consumes.
  * device log   (data/<run>/device_log.csv)  — the per-second historian record of
    every sensor's REPORTED value and every actuator state. This is what the
    Phase-5 LSTM sequence model trains on.

Both streams carry a ground-truth ``label`` column (normal / one of the attack
classes) so detectors can be trained and evaluated with known answers.

Design
------
* We own the physics clock: the plant is stepped one sim-second per tick, and the
  server serves whatever we publish. This makes runs fully reproducible and lets
  us compress wall-time via ``--speedup``.
* Legitimate traffic: an HMI/PLC actor reads the sensor block and writes actuator
  commands over REAL Modbus TCP (band-control logic, the authorised writer).
* Malicious traffic: an attacker actor issues real Modbus requests implementing
  each scenario. Sensor-spoofing scenarios overwrite the reported register AFTER
  the plant publishes but BEFORE the HMI reads, so the HMI (and the historian)
  see the spoofed value — exactly how a false-data-injection behaves.

Usage
-----
    python -m net.generate_dataset --out-dir data/run1 --speedup 30
    python -m net.generate_dataset --scenarios false_data_injection,flooding_dos
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import os
import time
from dataclasses import dataclass

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.server import StartAsyncTcpServer, ServerAsyncStop

from sim.plant import Plant
from sim.modbus_server import build_context
from sim.register_map import SENSORS, ACTUATORS, BY_TAG, REGISTER_COUNT
from .actors import logged_read, logged_write
from .config import (
    HMI, ATTACKER, LABEL_NORMAL, LABEL_FDI, LABEL_CMD_INJECTION,
    LABEL_FLOODING, LABEL_REPLAY, LABEL_STEALTH, ATTACK_LABELS,
)
from .transaction import Transaction, write_csv

HOST = "127.0.0.1"
PORT = 5023   # dataset-generation Modbus port (distinct from the live demo :5020)


# ---------------------------------------------------------------------------
# Attack schedule
# ---------------------------------------------------------------------------
@dataclass
class Window:
    start: int
    end: int          # exclusive
    label: str        # ground-truth attack class (or LABEL_NORMAL)


def build_schedule(scenarios: list[str], warmup: int, attack: int,
                   gap: int) -> tuple[list[Window], int]:
    """Lay out: [warmup normal] then, per scenario, [attack][normal gap]."""
    windows: list[Window] = []
    t = warmup
    for s in scenarios:
        windows.append(Window(t, t + attack, s))
        t += attack + gap
    duration = t
    return windows, duration


def active_label(windows: list[Window], tick: int) -> str:
    for w in windows:
        if w.start <= tick < w.end:
            return w.label
    return LABEL_NORMAL


# ---------------------------------------------------------------------------
# Datastore helpers (in-process access to the served context)
# ---------------------------------------------------------------------------
def _read(ctx, address: int) -> int:
    return ctx[0].getValues(3, address, count=1)[0]


def _write(ctx, address: int, value: int) -> None:
    ctx[0].setValues(3, address, [int(value) & 0xFFFF])


# ---------------------------------------------------------------------------
# Actors
# ---------------------------------------------------------------------------
async def hmi_tick(client, ctx, sink, last_cmd: dict) -> list[int]:
    """HMI reads the sensor block then writes any changed actuator commands."""
    # One block read (SCADA-style poll) — logged as a single read transaction.
    regs = await logged_read(client, HMI, 0, REGISTER_COUNT, sink) or \
        [_read(ctx, a) for a in range(REGISTER_COUNT)]

    def sv(tag: str) -> float:
        p = BY_TAG[tag]
        return p.to_physical(regs[p.address])

    # Band-control logic (the legitimate PLC program).
    cmds = {
        "MV101": 0 if sv("LIT101") > 900 else 1,
        "P101": 1 if sv("LIT101") > 500 else 0,
        "P201": 1 if sv("AIT202") < 6.8 else 0,
        "P203": 1 if sv("AIT202") > 7.8 else 0,
        "MV301": 1 if sv("DPIT301") > 35 else 0,
        "P301": 1 if sv("LIT301") > 400 else 0,
        "P401": 1 if sv("LIT301") > 350 else 0,
        "P501": 1 if sv("LIT401") > 400 else 0,
    }
    for tag, val in cmds.items():
        if last_cmd.get(tag) != val:                      # write only on change
            await logged_write(client, HMI, BY_TAG[tag].address,
                               BY_TAG[tag].to_register(val), sink)
            last_cmd[tag] = val
    return regs


async def attack_pre_read(kind: str, ctx, client, sink, replay_buf: list) -> None:
    """Manipulations that must land BEFORE the HMI reads (sensor spoofing)."""
    if kind == LABEL_FDI:
        # Spoof LIT101 to a high, out-of-band value.
        p = BY_TAG["LIT101"]
        _write(ctx, p.address, p.to_register(1180.0))
        await logged_write(client, ATTACKER, p.address, p.to_register(1180.0),
                           sink, label=LABEL_FDI)
    # Stealth deliberately performs NO sensor-spoofing write here: a write to a
    # sensor register is exactly what the protocol-aware engine flags. Instead the
    # stealth manipulation is delivered post-read as a valid-looking actuator
    # command from a compromised HMI (see attack_post_read), so it evades the DPI
    # layer and is catchable only by the LSTM's temporal model.


async def attack_post_read(kind: str, ctx, client, sink, replay_buf: list,
                           flood_n: int) -> None:
    """Manipulations after the HMI poll (writes, floods, replays)."""
    if kind == LABEL_CMD_INJECTION:
        # Unauthorised actuator write: force the raw-water transfer pump OFF.
        p = BY_TAG["P101"]
        _write(ctx, p.address, 0)
        await logged_write(client, ATTACKER, p.address, 0, sink,
                           label=LABEL_CMD_INJECTION)
    elif kind == LABEL_STEALTH:
        # Compromised-HMI over-dosing: force the HCl pump ON from the AUTHORISED
        # HMI source with a perfectly valid value. Nothing about this single write
        # is protocol-illegal (authorised writer, in-range actuator state), so the
        # DPI engine cannot flag it. The harm is only visible as a temporal
        # anomaly (acid pump held on, driving pH down) — the LSTM's job.
        p = BY_TAG["P203"]
        _write(ctx, p.address, 1)
        await logged_write(client, HMI, p.address, 1, sink, label=LABEL_STEALTH)
    elif kind == LABEL_FLOODING:
        # Burst of read requests to degrade the control loop (volumetric anomaly).
        for _ in range(flood_n):
            await logged_read(client, ATTACKER, BY_TAG["LIT101"].address, 1,
                              sink, label=LABEL_FLOODING)
    elif kind == LABEL_REPLAY:
        # Re-send a previously captured legitimate actuator command, out of order.
        if replay_buf:
            addr, raw = replay_buf[-1]
            _write(ctx, addr, raw)
            await logged_write(client, ATTACKER, addr, raw, sink, label=LABEL_REPLAY)


# ---------------------------------------------------------------------------
# Device-log row
# ---------------------------------------------------------------------------
DEVICE_COLUMNS = (["ts", "tick"] + [s.tag for s in SENSORS] +
                  [a.tag for a in ACTUATORS] + ["label"])


def device_row(ctx, tick: int, label: str) -> dict:
    row = {"ts": round(time.time(), 3), "tick": tick, "label": label}
    for s in SENSORS:
        row[s.tag] = round(s.to_physical(_read(ctx, s.address)), 3)
    for a in ACTUATORS:
        row[a.tag] = _read(ctx, a.address)
    return row


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------
async def generate(out_dir: str, scenarios: list[str], speedup: float, seed: int,
                   warmup: int, attack: int, gap: int, flood_n: int,
                   port: int = PORT) -> None:
    os.makedirs(out_dir, exist_ok=True)
    windows, duration = build_schedule(scenarios, warmup, attack, gap)

    ctx = build_context()
    plant = Plant(seed=seed)
    for a in ACTUATORS:                                   # prime actuator registers
        _write(ctx, a.address, a.to_register(plant.state[a.tag]))

    server = asyncio.create_task(StartAsyncTcpServer(context=ctx, address=(HOST, port)))
    await asyncio.sleep(1.0)                              # let it bind

    hmi = AsyncModbusTcpClient(HOST, port=port)
    attacker = AsyncModbusTcpClient(HOST, port=port)
    await hmi.connect()
    await attacker.connect()

    net_log: list[Transaction] = []
    device_rows: list[dict] = []
    replay_buf: list[tuple[int, int]] = []
    last_cmd: dict[str, int] = {}

    wall = "max speed" if speedup <= 0 else f"~{duration/speedup:.0f}s wall"
    print(f"Generating {duration} sim-seconds "
          f"({', '.join(scenarios)}) at {'unthrottled' if speedup <= 0 else str(speedup)+'x'} -> {wall}")

    try:
        for tick in range(duration):
            label = active_label(windows, tick)

            # 1. plant consumes actuator commands, advances one second
            for a in ACTUATORS:
                plant.state[a.tag] = a.to_physical(_read(ctx, a.address))
            plant.step(1.0)
            # 2. publish reported sensor values
            for s in SENSORS:
                _write(ctx, s.address, s.to_register(plant.sensor_reading(s.tag)))
            # 3. pre-read attacker manipulation (sensor spoofing)
            await attack_pre_read(label, ctx, attacker, net_log, replay_buf)
            # 4. legitimate HMI poll + control
            before = len(net_log)
            await hmi_tick(hmi, ctx, net_log, last_cmd)
            # remember a legit actuator write for later replay
            for t in net_log[before:]:
                if t.is_write and t.src_ip == HMI.ip:
                    replay_buf.append((t.register, t.value_raw))
            # 5. post-read attacker manipulation (writes / floods / replays)
            await attack_post_read(label, ctx, attacker, net_log, replay_buf, flood_n)
            # 6. historian row (reported values + final actuator states)
            device_rows.append(device_row(ctx, tick, label))

            if speedup > 0:
                await asyncio.sleep(1.0 / speedup)
    finally:
        hmi.close()
        attacker.close()
        server.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await server
        with contextlib.suppress(Exception):
            await ServerAsyncStop()

    # ---- write outputs ----
    net_path = os.path.join(out_dir, "network_log.csv")
    dev_path = os.path.join(out_dir, "device_log.csv")
    write_csv(net_path, net_log)
    with open(dev_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=DEVICE_COLUMNS)
        w.writeheader()
        w.writerows(device_rows)

    # ---- summary ----
    from collections import Counter
    net_by_label = Counter(t.label for t in net_log)
    dev_by_label = Counter(r["label"] for r in device_rows)
    print(f"\nnetwork_log.csv : {len(net_log)} transactions -> {net_path}")
    for k, v in net_by_label.most_common():
        print(f"    {k:24} {v}")
    print(f"device_log.csv  : {len(device_rows)} rows -> {dev_path}")
    for k, v in dev_by_label.most_common():
        print(f"    {k:24} {v}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase-3 labelled ICS dataset generator")
    ap.add_argument("--out-dir", default="data/run1")
    ap.add_argument("--scenarios", default=",".join(ATTACK_LABELS),
                    help="comma-separated attack classes to include")
    ap.add_argument("--speedup", type=float, default=30.0,
                    help="wall-time compression (0 = as fast as possible)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--warmup", type=int, default=60, help="normal seconds before first attack")
    ap.add_argument("--attack", type=int, default=45, help="seconds per attack window")
    ap.add_argument("--gap", type=int, default=45, help="normal seconds between attacks")
    ap.add_argument("--flood-n", type=int, default=40, help="requests/tick during flooding")
    args = ap.parse_args()

    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    bad = [s for s in scenarios if s not in ATTACK_LABELS]
    if bad:
        raise SystemExit(f"unknown scenarios: {bad}\nvalid: {ATTACK_LABELS}")

    asyncio.run(generate(args.out_dir, scenarios, args.speedup, args.seed,
                         args.warmup, args.attack, args.gap, args.flood_n))


if __name__ == "__main__":
    main()
