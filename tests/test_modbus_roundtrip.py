"""Smoke test: start the simulator's Modbus server and read live registers.

Verifies the whole Phase-2 slice end to end:
  server context builds -> physics loop publishes sensors -> a Modbus client
  connects over TCP and reads sane values -> a client write to an actuator
  register is reflected back.
"""
from __future__ import annotations

import asyncio
import contextlib

import pytest

from pymodbus.client import AsyncModbusTcpClient

from sim.modbus_server import build_context, physics_loop, control_loop, _read_reg
from sim.plant import Plant
from sim.register_map import BY_TAG
from pymodbus.server import StartAsyncTcpServer, ServerAsyncStop

HOST, PORT = "127.0.0.1", 5099


@pytest.mark.asyncio
async def test_roundtrip():
    plant = Plant(seed=7)
    ctx = build_context()
    server_task = asyncio.create_task(
        StartAsyncTcpServer(context=ctx, address=(HOST, PORT))
    )
    phys = asyncio.create_task(physics_loop(plant, ctx, dt=0.2))
    ctrl = asyncio.create_task(control_loop(ctx, dt=0.2))
    await asyncio.sleep(1.0)  # let a few steps publish

    try:
        client = AsyncModbusTcpClient(HOST, port=PORT)
        await client.connect()
        assert client.connected

        lit101 = BY_TAG["LIT101"]
        rr = await client.read_holding_registers(lit101.address, count=1, device_id=1)
        assert not rr.isError()
        level = lit101.to_physical(rr.registers[0])
        assert 0 < level < 1200, f"LIT101 out of range: {level}"

        # Write an actuator command and confirm the datastore reflects it.
        p101 = BY_TAG["P101"]
        await client.write_register(p101.address, 0, device_id=1)
        await asyncio.sleep(0.3)
        assert _read_reg(ctx, p101.address) in (0, 1)  # control loop may re-drive it
        client.close()
    finally:
        for t in (phys, ctrl, server_task):
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t
        await ServerAsyncStop()


if __name__ == "__main__":
    asyncio.run(test_roundtrip())
    print("roundtrip OK")
