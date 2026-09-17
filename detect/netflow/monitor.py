"""
NetFlow / DoS volume monitor (Phase 5, AFAD-inspired layer).

The protocol-aware DPI engine inspects the *content* of writes and ignores reads,
so a request flood — which is just a torrent of ordinary-looking reads — sails
straight through it. This monitor is the complementary volumetric layer: it looks
only at *how much* traffic each source generates per time window, learns what
normal looks like, and flags any source whose request rate spikes far beyond it.

It is unsupervised: ``fit`` sees only normal traffic and derives a threshold; it
never sees an attack during training (mirroring AFAD's unsupervised design). The
per-tick request count is the flow feature — during a flood the attacking host
issues tens of requests per second where a normal station issues a handful.

    python -m detect.netflow.monitor --network-log data/run1/network_log.csv
"""
from __future__ import annotations

import argparse
import statistics
from collections import defaultdict

from detect.alert import Alert
from detect.dpi.engine import load_network_log
from net.config import LABEL_NORMAL


def per_tick_source_counts(transactions) -> dict[tuple[int, str], int]:
    """Count requests grouped by (tick, source IP)."""
    counts: dict[tuple[int, str], int] = defaultdict(int)
    for t in transactions:
        counts[(t.tick, t.src_ip)] += 1
    return counts


class NetFlowMonitor:
    """Learns a normal per-window request-rate ceiling and flags floods above it."""

    def __init__(self, k: float = 8.0, margin: float = 1.5) -> None:
        self.k = k                # std-dev multiplier for the statistical bound
        self.margin = margin      # multiplicative safety margin over observed max
        self.threshold: float = float("inf")
        self.normal_mean = 0.0
        self.normal_max = 0

    def fit(self, transactions) -> "NetFlowMonitor":
        counts = per_tick_source_counts(t for t in transactions
                                        if t.label == LABEL_NORMAL)
        vals = list(counts.values())
        if not vals:
            return self
        self.normal_mean = statistics.mean(vals)
        self.normal_max = max(vals)
        std = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        # threshold above BOTH a statistical bound and the observed normal ceiling,
        # so training normal never trips it and generalisation stays conservative.
        self.threshold = max(self.normal_mean + self.k * std,
                             self.normal_max * self.margin)
        return self

    def detect(self, transactions) -> list[Alert]:
        txns = list(transactions)
        counts = per_tick_source_counts(txns)
        # a representative timestamp per tick for the alert
        ts_of_tick = {}
        label_of_tick_src = {}
        for t in txns:
            ts_of_tick.setdefault(t.tick, t.ts)
            label_of_tick_src[(t.tick, t.src_ip)] = t.label

        alerts: list[Alert] = []
        for (tick, src), n in sorted(counts.items()):
            if n > self.threshold:
                alerts.append(Alert(
                    ts=ts_of_tick.get(tick, 0.0), layer="netflow",
                    rule="request_flood", severity="high",
                    message=(f"Source {src} issued {n} requests in one window "
                             f"(normal <= {self.normal_max}; threshold "
                             f"{self.threshold:.0f}) - request flood / DoS on the "
                             f"OT network degrading the control loop."),
                    src_ip=src, intent="denial of service / control-loop disruption",
                    evidence={"tick": tick, "requests": n,
                              "threshold": round(self.threshold, 1)},
                    true_label=label_of_tick_src.get((tick, src), ""),
                ))
        return alerts


def main() -> None:
    ap = argparse.ArgumentParser(description="NetFlow / DoS volume monitor")
    ap.add_argument("--network-log", default="data/run1/network_log.csv")
    args = ap.parse_args()

    txns = list(load_network_log(args.network_log))
    mon = NetFlowMonitor().fit(txns)
    alerts = mon.detect(txns)

    print(f"Learned normal request ceiling: max={mon.normal_max}/window, "
          f"mean={mon.normal_mean:.2f}; flood threshold={mon.threshold:.0f}\n")

    # per-window detection vs ground truth
    from collections import Counter
    flagged_by_label = Counter(a.true_label for a in alerts)
    print(f"Flood windows detected: {len(alerts)}")
    for lbl, n in flagged_by_label.most_common():
        print(f"    {lbl:24} {n}")
    fp = sum(1 for a in alerts if a.true_label == LABEL_NORMAL)
    print(f"\nFalse positives on normal windows: {fp}")
    if alerts:
        print("\nExample alert:\n  " + alerts[0].message)


if __name__ == "__main__":
    main()
