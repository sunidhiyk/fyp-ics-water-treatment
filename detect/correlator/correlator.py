"""
Alert correlator (Phase 6).

Runs all three detection layers over a dataset and merges their alerts into one
chronological incident stream, then records every control command and every alert
into the tamper-evident ledger. This is the join point of the whole system: the
protocol-aware DPI, the NetFlow volume monitor, and the LSTM sequence model each
see different attacks, and together they cover the full threat set.
"""
from __future__ import annotations

from detect.alert import Alert
from detect.dpi.engine import load_network_log, inspect
from detect.netflow.monitor import NetFlowMonitor
from detect.lstm.detect import detect as lstm_detect
from net.config import HMI
from ledger.hashchain import HashChainLedger


def _tick_of(alert: Alert) -> int:
    return int(alert.evidence.get("tick",
               alert.evidence.get("window_end_row", 0)))


def correlate(network_log: str, device_log: str,
              lstm_art_dir: str = "detect/lstm/artifacts") -> list[Alert]:
    """Merge DPI + NetFlow + LSTM alerts into one time-ordered stream."""
    txns = list(load_network_log(network_log))

    alerts: list[Alert] = []

    # DPI — per-transaction protocol-semantic rules
    for t in txns:
        a = inspect(t)
        if a is not None:
            a.evidence["tick"] = t.tick
            alerts.append(a)

    # NetFlow — per-window volume
    mon = NetFlowMonitor().fit(txns)
    alerts.extend(mon.detect(txns))

    # LSTM — per-window sequence anomaly (needs trained artifacts)
    try:
        lstm_alerts, *_ = lstm_detect(device_log, lstm_art_dir)
        alerts.extend(lstm_alerts)
    except FileNotFoundError:
        pass  # model not trained yet; DPI + NetFlow still produce a stream

    alerts.sort(key=lambda a: (_tick_of(a), a.layer))
    return alerts


def record_to_ledger(alerts: list[Alert], network_log: str, path: str,
                     key_path: str) -> HashChainLedger:
    """Append every control command and every alert to a fresh hash-chain ledger."""
    ledger = HashChainLedger(path=path, key_path=key_path)

    # timeline of control commands (legitimate HMI writes) + alerts, in tick order
    timeline: list[tuple[int, dict]] = []
    for t in load_network_log(network_log):
        if t.is_write and t.src_ip == HMI.ip:
            timeline.append((t.tick, {
                "type": "control_command", "ts": t.ts, "tick": t.tick,
                "src": t.src_ip, "tag": t.tag, "value": t.value_phys,
            }))
    for a in alerts:
        rec = a.to_dict()
        rec["type"] = "alert"
        rec["tick"] = _tick_of(a)
        timeline.append((_tick_of(a), rec))

    for _, rec in sorted(timeline, key=lambda x: x[0]):
        ledger.append(rec)
    return ledger
