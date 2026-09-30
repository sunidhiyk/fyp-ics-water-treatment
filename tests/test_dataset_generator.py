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
from net.config import LABEL_FDI, LABEL_STEALTH, LABEL_CMD_INJECTION, ATTACKER

PORT = 5124  # test-only Modbus port
PORT_RESTORE = 5125


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


@pytest.mark.asyncio
async def test_actuators_restored_after_attack_windows(tmp_path):
    """An attacker's actuator override must not outlive its attack window.

    The legitimate controller re-asserts its outputs each cycle, so once the
    attack stops, the next cycle puts the pump back. Otherwise seconds labelled
    'normal' after an attack would still carry the attack's effect.
    """
    out = str(tmp_path / "run")
    # ticks: 0-7 normal | 8-15 command injection | 16-21 normal
    #        22-29 stealth | 30-35 normal
    await generate(out, scenarios=[LABEL_CMD_INJECTION, LABEL_STEALTH], speedup=0,
                   seed=1, warmup=8, attack=8, gap=6, flood_n=10, port=PORT_RESTORE)
    dev = list(csv.DictReader(open(os.path.join(out, "device_log.csv"), encoding="utf-8")))
    state = lambda tag, lo, hi: [int(dev[t][tag]) for t in range(lo, hi + 1)]

    assert state("P101", 8, 15) == [0] * 8     # attack holds the transfer pump off...
    assert state("P101", 16, 21) == [1] * 6    # ...and it is back on once the attack ends
    assert state("P203", 22, 29) == [1] * 8    # stealth holds the acid pump on...
    assert state("P203", 30, 35) == [0] * 6    # ...and it is off again afterwards
