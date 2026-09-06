"""
Actors on the OT segment. Each helper performs a REAL Modbus TCP request via a
pymodbus client and records it as a Transaction tagged with the source actor's
logical identity and a ground-truth label.

Keeping the send-and-log together here means the dataset's network log is an
exact account of the frames that actually crossed the (simulated) wire.
"""
from __future__ import annotations

import time

from pymodbus.client import AsyncModbusTcpClient

from .config import Actor, PLC_IP, PLC_PORT, LABEL_NORMAL
from .transaction import Transaction


async def logged_read(client: AsyncModbusTcpClient, actor: Actor, address: int,
                      count: int, sink: list[Transaction], label: str = LABEL_NORMAL,
                      unit_id: int = 1) -> list[int] | None:
    """Read holding registers over TCP and log the transaction."""
    rr = await client.read_holding_registers(address, count=count, device_id=unit_id)
    sink.append(Transaction(
        ts=time.time(), src_ip=actor.ip, src_port=actor.port,
        dst_ip=PLC_IP, dst_port=PLC_PORT, unit_id=unit_id,
        func_code=3, register=address, value_raw=0, count=count, label=label,
    ))
    return None if rr.isError() else rr.registers


async def logged_write(client: AsyncModbusTcpClient, actor: Actor, address: int,
                       value_raw: int, sink: list[Transaction],
                       label: str = LABEL_NORMAL, unit_id: int = 1) -> None:
    """Write a single holding register over TCP and log the transaction."""
    await client.write_register(address, int(value_raw) & 0xFFFF, device_id=unit_id)
    sink.append(Transaction(
        ts=time.time(), src_ip=actor.ip, src_port=actor.port,
        dst_ip=PLC_IP, dst_port=PLC_PORT, unit_id=unit_id,
        func_code=6, register=address, value_raw=int(value_raw) & 0xFFFF,
        count=1, label=label,
    ))
