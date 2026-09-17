"""Phase-5 test: the NetFlow monitor flags a request flood and nothing else."""
from __future__ import annotations

from net.transaction import Transaction
from net.config import HMI, ATTACKER, LABEL_NORMAL, LABEL_FLOODING
from detect.netflow.monitor import NetFlowMonitor


def _read(src_ip, tick, label=LABEL_NORMAL):
    return Transaction(ts=float(tick), src_ip=src_ip, src_port=1, dst_ip="10.0.0.2",
                       dst_port=502, unit_id=1, func_code=3, register=0,
                       value_raw=0, count=1, label=label, tick=tick)


def _dataset():
    txns = []
    # 40 normal ticks: HMI issues ~2 requests each
    for t in range(40):
        txns += [_read(HMI.ip, t), _read(HMI.ip, t)]
    # 5 flooding ticks: attacker issues 40 requests each
    for t in range(40, 45):
        for _ in range(40):
            txns.append(_read(ATTACKER.ip, t, LABEL_FLOODING))
        txns.append(_read(HMI.ip, t))  # HMI keeps polling underneath
    return txns


def test_monitor_learns_normal_and_flags_flood():
    txns = _dataset()
    mon = NetFlowMonitor().fit(txns)
    assert mon.normal_max <= 2          # learned normal ceiling is small
    alerts = mon.detect(txns)
    # every flood tick flagged, attributed to the attacker, none on normal
    assert len(alerts) == 5
    assert all(a.true_label == LABEL_FLOODING for a in alerts)
    assert all(a.src_ip == ATTACKER.ip for a in alerts)


def test_no_false_positive_when_only_normal():
    txns = [_read(HMI.ip, t) for t in range(50)]
    mon = NetFlowMonitor().fit(txns)
    assert mon.detect(txns) == []
