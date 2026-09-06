"""
Live plant monitor: connects to the running Modbus server as a client and
prints the current sensor/actuator values as a refreshing table.

This doubles as a demo of the *client* side of the OT protocol (the same role
the HMI, and later the attack scripts and DPI tap, play).

    python -m sim.monitor --host 127.0.0.1 --port 5020
"""
from __future__ import annotations

import argparse
import asyncio
import os

from pymodbus.client import AsyncModbusTcpClient

from .register_map import SENSORS, ACTUATORS, REGISTER_COUNT

ACT_LABEL = {0: "OFF/CLOSED", 1: "ON/OPEN", 2: "TRANS"}


def _clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _band_flag(value: float, lo: float, hi: float) -> str:
    return "  " if lo <= value <= hi else "!!"


async def run(host: str, port: int, interval: float) -> None:
    client = AsyncModbusTcpClient(host, port=port)
    await client.connect()
    if not client.connected:
        raise SystemExit(f"could not connect to Modbus server at {host}:{port}")

    try:
        while True:
            rr = await client.read_holding_registers(0, count=REGISTER_COUNT, device_id=1)
            if rr.isError():
                print("read error:", rr)
                await asyncio.sleep(interval)
                continue
            regs = rr.registers

            _clear()
            print(f"Water-Treatment Plant  —  live @ {host}:{port}")
            print("=" * 58)
            print("SENSORS")
            print(f"  {'tag':8} {'value':>10} {'unit':8} {'band':>16}")
            for p in SENSORS:
                val = p.to_physical(regs[p.address])
                flag = _band_flag(val, p.lo, p.hi)
                print(f"{flag}{p.tag:8} {val:>10.2f} {p.unit:8} "
                      f"[{p.lo:g}..{p.hi:g}]")
            print("\nACTUATORS")
            for p in ACTUATORS:
                raw = int(regs[p.address])
                print(f"  {p.tag:8} {ACT_LABEL.get(raw, raw):>10}   {p.description}")
            print("\n(ctrl-c to quit)")
            await asyncio.sleep(interval)
    finally:
        client.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Live plant monitor (Modbus client)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5020)
    ap.add_argument("--interval", type=float, default=1.0)
    args = ap.parse_args()
    try:
        asyncio.run(run(args.host, args.port, args.interval))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
