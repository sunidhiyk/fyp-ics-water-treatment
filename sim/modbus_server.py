"""
Modbus TCP front-end for the plant simulator.

Runs an async Modbus TCP server (pymodbus) whose holding registers ARE the
plant's live state. Three coroutines cooperate on a shared ModbusServerContext:

  * physics loop   -> steps Plant, writes sensor registers
  * control loop   -> the built-in "soft PLC": reads sensors, writes actuator
                      registers to keep the process in band (level/pH/DP interlocks)
  * modbus server  -> serves the registers over TCP so external masters
                      (OpenPLC, HMI, attack scripts, the DPI tap) speak real Modbus

The built-in control loop lets the whole testbed run with a single command while
OpenPLC integration (plc/) is being brought up. When OpenPLC drives the actuators
instead, start with ``--no-control`` and the plant follows OpenPLC's commands.

Register model: a single unit/slave, holding registers 0..REGISTER_COUNT-1,
addressed exactly as register_map.py defines.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from pymodbus.datastore import ModbusServerContext, ModbusDeviceContext, ModbusSequentialDataBlock
from pymodbus.server import StartAsyncTcpServer

from .plant import Plant
from .register_map import BY_TAG, SENSORS, ACTUATORS, REGISTER_COUNT, Kind

log = logging.getLogger("sim.modbus")

# pymodbus data blocks are 1-based on the wire; the library offsets internally.
# We keep our register_map addresses 0-based and let the datablock start at 0.


def build_context() -> ModbusServerContext:
    # pymodbus 3.11: addresses are 0-based by default; one holding-register block
    # is shared as both hr and ir so masters can read sensors via fc=3 or fc=4.
    block = ModbusSequentialDataBlock(0, [0] * (REGISTER_COUNT + 1))
    device = ModbusDeviceContext(hr=block, ir=block)
    return ModbusServerContext(devices=device, single=True)


def _write_reg(ctx: ModbusServerContext, address: int, value: int) -> None:
    # fc=3 -> holding registers; single slave context.
    ctx[0].setValues(3, address, [int(value) & 0xFFFF])


def _read_reg(ctx: ModbusServerContext, address: int) -> int:
    return ctx[0].getValues(3, address, count=1)[0]


async def physics_loop(plant: Plant, ctx: ModbusServerContext, dt: float) -> None:
    """Step the plant and publish sensor values into the datastore."""
    while True:
        # Pull actuator commands that external masters wrote into the registers.
        for a in ACTUATORS:
            plant.state[a.tag] = a.to_physical(_read_reg(ctx, a.address))
        plant.step(dt)
        # Publish noisy sensor readings.
        for spt in SENSORS:
            raw = spt.to_register(plant.sensor_reading(spt.tag))
            _write_reg(ctx, spt.address, raw)
        await asyncio.sleep(dt)


async def control_loop(ctx: ModbusServerContext, dt: float) -> None:
    """Built-in soft-PLC: simple band interlocks written back as actuator commands."""
    def sensor(tag: str) -> float:
        p = BY_TAG[tag]
        return p.to_physical(_read_reg(ctx, p.address))

    def command(tag: str, value: int) -> None:
        _write_reg(ctx, BY_TAG[tag].address, value)

    while True:
        # P1: keep raw tank between 500 and 900 mm.
        lit101 = sensor("LIT101")
        if lit101 < 500:
            command("MV101", 1); command("P101", 0)
        elif lit101 > 900:
            command("MV101", 0); command("P101", 1)
        else:
            command("MV101", 1); command("P101", 1)

        # P2: hold pH in 6.8..7.8 via dosing pumps.
        ph = sensor("AIT202")
        command("P201", 1 if ph < 6.8 else 0)   # raise pH
        command("P203", 1 if ph > 7.8 else 0)   # lower pH

        # P3: backwash UF when differential pressure too high.
        command("MV301", 1 if sensor("DPIT301") > 35 else 0)
        command("P301", 1 if sensor("LIT301") > 400 else 0)

        # P4/P5: run feed + RO pump while feed tank has water.
        lit401 = sensor("LIT401")
        command("P401", 1 if sensor("LIT301") > 350 else 0)
        command("P501", 1 if lit401 > 400 else 0)
        command("MV501", 1)

        await asyncio.sleep(dt)


async def serve(host: str, port: int, dt: float, control: bool, seed: int | None) -> None:
    plant = Plant(seed=seed)
    ctx = build_context()
    # Prime actuator registers from the plant's initial state.
    for a in ACTUATORS:
        _write_reg(ctx, a.address, a.to_register(plant.state[a.tag]))

    tasks = [asyncio.create_task(physics_loop(plant, ctx, dt))]
    if control:
        tasks.append(asyncio.create_task(control_loop(ctx, dt)))

    log.info("Modbus TCP server on %s:%d (dt=%.2fs, control=%s)", host, port, dt, control)
    await StartAsyncTcpServer(context=ctx, address=(host, port))


def main() -> None:
    ap = argparse.ArgumentParser(description="Water-treatment plant Modbus TCP simulator")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5020)
    ap.add_argument("--dt", type=float, default=1.0, help="sim step / publish interval (s)")
    ap.add_argument("--no-control", action="store_true",
                    help="disable the built-in soft-PLC (drive actuators via OpenPLC instead)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(serve(args.host, args.port, args.dt, not args.no_control, args.seed))


if __name__ == "__main__":
    main()
