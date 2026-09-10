"""
Phase-3 test: the dataset generator produces well-formed, correctly-labelled
network and device logs, and the attacks actually manifest in the data.
"""
from __future__ import annotations

import csv
import os

import pytest

from net.generate_dataset import generate, DEVICE_COLUMNS
from net.transaction import COLUMNS as NET_COLUMNS
from net.config import LABEL_FDI, LABEL_STEALTH, ATTACKER

PORT = 5124  # test-only Modbus port


@pytest.mark.asyncio
async def test_generate_small_dataset(tmp_path):
    out = str(tmp_path / "run")
    await generate(out, scenarios=[LABEL_FDI, LABEL_STEALTH], speedup=0, seed=1,
                   warmup=8, attack=8, gap=6, flood_n=10, port=PORT)

    net_path = os.path.join(out, "network_log.csv")
    dev_path = os.path.join(out, "device_log.csv")
    assert os.path.exists(net_path) and os.path.exists(dev_path)

    net = list(csv.DictReader(open(net_path, encoding="utf-8")))
    dev = list(csv.DictReader(open(dev_path, encoding="utf-8")))

    # schema
    assert list(net[0].keys()) == NET_COLUMNS
    assert list(dev[0].keys()) == DEVICE_COLUMNS

    # duration = warmup + 2*(attack+gap) = 8 + 2*14 = 36 device rows
    assert len(dev) == 36
    assert [r for r in dev if r["label"] == LABEL_FDI]      # FDI window present
    assert [r for r in dev if r["label"] == LABEL_STEALTH]  # stealth window present

    # FDI actually spoofs LIT101 out of band, and the attacker source appears
    fdi_rows = [r for r in dev if r["label"] == LABEL_FDI]
    assert all(float(r["LIT101"]) > 1100 for r in fdi_rows)
    assert any(t["src_ip"] == ATTACKER.ip and t["label"] == LABEL_FDI for t in net)

    # stealth keeps pH in-band (evades a naive band check) but forces the acid pump
    stealth_rows = [r for r in dev if r["label"] == LABEL_STEALTH]
    assert all(6.5 <= float(r["AIT202"]) <= 8.5 for r in stealth_rows)
    assert all(int(r["P203"]) == 1 for r in stealth_rows)
