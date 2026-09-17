"""
Operator dashboard (demo slice of Phase 6).

A single-process demo that exercises the *real* OT path:

  startup ->  launch the plant's Modbus TCP server in-process (port 5020)
          ->  a poller connects as a Modbus CLIENT and reads all registers /s
          ->  latest snapshot is broadcast to browser clients over WebSocket
          ->  the page renders sensor cards (green in-band / red out-of-band)
              and actuator states, refreshing live

An "Inject attack" button writes an out-of-band value to LIT101 via the same
Modbus client — the field-level analogue of a spoofing write — so you can watch
the affected sensor flip red in the browser. This previews what the DPI and LSTM
detection layers will flag automatically in later phases.

Run:
    python -m app.dashboard          # then open http://127.0.0.1:8000
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.server import StartAsyncTcpServer, ServerAsyncStop

import time

from sim.plant import Plant
from sim.modbus_server import build_context, physics_loop, control_loop
from sim.register_map import SENSORS, ACTUATORS, BY_TAG, REGISTER_COUNT
from ledger.hashchain import HashChainLedger

MODBUS_HOST, MODBUS_PORT = "127.0.0.1", 5020

app = FastAPI(title="Water-Treatment ICS Dashboard")

# shared runtime state
_clients: set[WebSocket] = set()
_latest: dict = {"sensors": [], "actuators": [], "alerts": [], "attack": False,
                 "ledger": {"count": 0, "intact": True, "broken_index": None}}
_client: AsyncModbusTcpClient | None = None
_tasks: list[asyncio.Task] = []
_attack_active = False
_spoof_task: asyncio.Task | None = None

# tamper-evident audit trail (in-memory: resets each run)
_ledger = HashChainLedger()
_alerted_tags: set[str] = set()   # tags currently in an alerted state (edge-detect)


def _ledger_summary() -> dict:
    r = _ledger.verify()
    return {"count": len(_ledger), "intact": r.ok, "broken_index": r.broken_index}


def _meta() -> dict:
    return {
        "sensors": [{"tag": p.tag, "unit": p.unit, "lo": p.lo, "hi": p.hi,
                     "stage": p.stage.value, "desc": p.description} for p in SENSORS],
        "actuators": [{"tag": p.tag, "desc": p.description} for p in ACTUATORS],
    }


async def _poller() -> None:
    """Read the plant over Modbus and broadcast snapshots to browsers."""
    global _client
    _client = AsyncModbusTcpClient(MODBUS_HOST, port=MODBUS_PORT)
    await _client.connect()
    while True:
        try:
            rr = await _client.read_holding_registers(0, count=REGISTER_COUNT, device_id=1)
            if not rr.isError():
                regs = rr.registers
                sensors, alerts = [], []
                for p in SENSORS:
                    v = p.to_physical(regs[p.address])
                    ok = p.lo <= v <= p.hi
                    sensors.append({"tag": p.tag, "value": round(v, 2), "ok": ok})
                    if not ok:
                        alerts.append({
                            "tag": p.tag,
                            "msg": f"{p.tag} ({p.description}) = {v:.2f} {p.unit} "
                                   f"outside safe band [{p.lo:g}..{p.hi:g}]",
                        })
                actuators = [{"tag": p.tag,
                              "state": int(round(BY_TAG[p.tag].to_physical(regs[p.address])))}
                             for p in ACTUATORS]
                # append each NEWLY-alerting sensor to the tamper-evident ledger
                current = {a["tag"] for a in alerts}
                for a in alerts:
                    if a["tag"] not in _alerted_tags:
                        _ledger.append({"type": "alert", "ts": time.time(),
                                        "tag": a["tag"], "message": a["msg"]})
                _alerted_tags.clear()
                _alerted_tags.update(current)
                _latest.update(sensors=sensors, actuators=actuators,
                               alerts=alerts, attack=_attack_active,
                               ledger=_ledger_summary())
                await _broadcast(_latest)
        except Exception:  # keep the demo alive across transient client hiccups
            pass
        await asyncio.sleep(1.0)


async def _broadcast(payload: dict) -> None:
    dead = []
    msg = json.dumps(payload)
    for ws in _clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.discard(ws)


@app.on_event("startup")
async def _startup() -> None:
    plant = Plant(seed=42)
    ctx = build_context()
    for a in ACTUATORS:
        ctx[0].setValues(3, a.address, [a.to_register(plant.state[a.tag])])
    _tasks.append(asyncio.create_task(
        StartAsyncTcpServer(context=ctx, address=(MODBUS_HOST, MODBUS_PORT))))
    _tasks.append(asyncio.create_task(physics_loop(plant, ctx, dt=1.0)))
    _tasks.append(asyncio.create_task(control_loop(ctx, dt=1.0)))
    await asyncio.sleep(1.5)          # let the server bind + publish a few steps
    _tasks.append(asyncio.create_task(_poller()))


@app.on_event("shutdown")
async def _shutdown() -> None:
    for t in _tasks:
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t
    with contextlib.suppress(Exception):
        await ServerAsyncStop()


async def _hold_spoof(tag: str, physical: float) -> None:
    """Continuously overwrite a sensor register — a sustained false-data-injection.

    The plant's physics loop republishes the true value every second; an attacker
    holds the spoof by writing faster than that, so the register the operator/HMI
    reads stays fixed at the injected value. This is exactly the manipulation the
    DPI and LSTM layers are built to detect.
    """
    p = BY_TAG[tag]
    # Dedicated attacker connection: a separate TCP client (a separate "host" on
    # the OT segment) avoids sharing a pymodbus transaction context with the
    # dashboard poller, and is closer to how a real injection host behaves.
    attacker = AsyncModbusTcpClient(MODBUS_HOST, port=MODBUS_PORT)
    await attacker.connect()
    try:
        while True:
            with contextlib.suppress(Exception):
                await attacker.write_register(p.address, p.to_register(physical), device_id=1)
            await asyncio.sleep(0.1)
    finally:
        attacker.close()


@app.post("/api/attack")
async def inject_attack() -> dict:
    """Spoof LIT101 out of band via sustained Modbus writes (data-manipulation attack)."""
    global _attack_active, _spoof_task
    if _client is not None and _spoof_task is None:
        _spoof_task = asyncio.create_task(_hold_spoof("LIT101", 1180.0))
        _attack_active = True
        _ledger.append({"type": "control_command", "ts": time.time(),
                        "src": "10.0.0.66", "tag": "LIT101", "value": 1180.0,
                        "note": "operator-triggered demo: spoof write to LIT101"})
    return {"ok": True}


@app.post("/api/clear")
async def clear_attack() -> dict:
    global _attack_active, _spoof_task
    if _spoof_task is not None:
        _spoof_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _spoof_task
        _spoof_task = None
    _attack_active = False
    return {"ok": True}


@app.get("/api/meta")
async def meta() -> dict:
    return _meta()


@app.get("/api/ledger")
async def get_ledger() -> dict:
    """Return recent ledger entries and the current integrity status."""
    r = _ledger.verify()
    entries = _ledger.entries()[-12:]     # last few for display
    view = [{"index": e["index"], "type": e["payload"].get("type", "?"),
             "summary": e["payload"].get("message") or e["payload"].get("note")
             or f'{e["payload"].get("tag","")}={e["payload"].get("value","")}',
             "entry_hash": e["entry_hash"][:12]} for e in entries]
    return {"integrity": {"intact": r.ok, "broken_index": r.broken_index,
                          "reason": r.reason, "count": r.length},
            "entries": view}


@app.post("/api/tamper")
async def tamper() -> dict:
    """Demo: forge a stored ledger entry so integrity verification fails."""
    if len(_ledger) == 0:
        return {"ok": False, "reason": "ledger empty"}
    victim = min(1, len(_ledger) - 1)
    _ledger._entries[victim]["payload"]["value"] = 0.0
    _ledger._entries[victim]["payload"]["note"] = "record silently altered by attacker"
    return {"ok": True, "tampered_index": victim}


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    await websocket.accept()
    _clients.add(websocket)
    with contextlib.suppress(Exception):
        await websocket.send_text(json.dumps(_latest))
    try:
        while True:
            await websocket.receive_text()   # keepalive; page doesn't send commands
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (Path(__file__).parent / "frontend" / "index.html").read_text(encoding="utf-8")


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
