"""
The structured Modbus transaction record — one row of the network log.

This holds exactly the fields a protocol-aware DPI decoder extracts from a Modbus
TCP frame (source/destination, function code, targeted register, written value),
plus the physical interpretation via the register map and a ground-truth label
for supervised evaluation. It is the shared contract between the dataset
generator (Phase 3) and the DPI rule engine (Phase 4).

Whether the record is produced by an application-layer logger (works everywhere)
or by parsing a real pcap captured with tshark (WSL/Linux), the schema is
identical — so downstream code does not care which source produced it.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, asdict, fields

from sim.register_map import BY_ADDRESS

# Modbus function codes we model.
FUNC_NAMES = {
    3: "read_holding_registers",
    4: "read_input_registers",
    6: "write_single_register",
    16: "write_multiple_registers",
}
WRITE_FUNCS = {6, 16}


@dataclass
class Transaction:
    ts: float             # epoch seconds
    src_ip: str
    src_port: int
    dst_ip: str
    dst_port: int
    unit_id: int
    func_code: int
    register: int         # first register address touched
    value_raw: int        # raw register value (writes; 0 for reads)
    count: int = 1        # number of registers in the request
    label: str = "normal"  # ground truth for training/eval

    # -- derived (not stored as separate columns unless materialised) -------
    @property
    def func_name(self) -> str:
        return FUNC_NAMES.get(self.func_code, f"fc{self.func_code}")

    @property
    def is_write(self) -> bool:
        return self.func_code in WRITE_FUNCS

    @property
    def tag(self) -> str:
        p = BY_ADDRESS.get(self.register)
        return p.tag if p else ""

    @property
    def value_phys(self) -> float | None:
        p = BY_ADDRESS.get(self.register)
        return p.to_physical(self.value_raw) if p else None

    def to_row(self) -> dict:
        d = asdict(self)
        d.update(func_name=self.func_name, is_write=int(self.is_write),
                 tag=self.tag, value_phys=self.value_phys)
        return d


COLUMNS = [f.name for f in fields(Transaction)] + \
          ["func_name", "is_write", "tag", "value_phys"]


def write_csv(path: str, txns: list[Transaction]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for t in txns:
            w.writerow(t.to_row())
