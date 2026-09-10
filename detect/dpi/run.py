"""
Run the DPI engine over a generated network log and report what it caught.

    python -m detect.dpi.run --network-log data/run1/network_log.csv

Prints a sample of the interpretable alerts, then a per-attack-class detection
breakdown and the false-positive rate on normal traffic. The blind spots
(flooding, stealth) are expected — they belong to the NetFlow and LSTM layers.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict

from net.config import LABEL_NORMAL
from .engine import load_network_log, inspect


def main() -> None:
    ap = argparse.ArgumentParser(description="Protocol-aware DPI rule engine")
    ap.add_argument("--network-log", default="data/run1/network_log.csv")
    ap.add_argument("--show", type=int, default=8, help="sample alerts to print")
    args = ap.parse_args()

    total = Counter()          # transactions per label
    flagged = Counter()        # flagged transactions per label
    rule_hits = Counter()      # alerts per rule
    sample = []

    for t in load_network_log(args.network_log):
        total[t.label] += 1
        alert = inspect(t)
        if alert is not None:
            flagged[t.label] += 1
            rule_hits[alert.rule] += 1
            if len(sample) < args.show:
                sample.append(alert)

    # ---- sample alerts ----
    print("=" * 78)
    print("SAMPLE INTERPRETABLE ALERTS")
    print("=" * 78)
    for a in sample:
        print(f"\n* {a.rule}  [{a.severity}]  intent: {a.intent}")
        print(f"  {a.message}")

    # ---- per-class detection ----
    print("\n" + "=" * 78)
    print("DETECTION BY ATTACK CLASS  (transaction level)")
    print("=" * 78)
    print(f"{'label':24} {'total':>7} {'flagged':>8} {'rate':>7}")
    for label in sorted(total):
        tot, fl = total[label], flagged[label]
        rate = f"{100*fl/tot:5.1f}%" if tot else "   n/a"
        print(f"{label:24} {tot:>7} {fl:>8} {rate:>7}")

    # ---- false positives on normal ----
    fp = flagged[LABEL_NORMAL]
    n_norm = total[LABEL_NORMAL]
    print("\n" + "-" * 78)
    print(f"False positives on normal traffic: {fp}/{n_norm} "
          f"({100*fp/n_norm:.2f}% FPR)" if n_norm else "no normal traffic")
    print("Rule hits:", dict(rule_hits))

    # ---- which attack classes were detected at all ----
    attack_labels = [l for l in total if l != LABEL_NORMAL]
    caught = [l for l in attack_labels if flagged[l] > 0]
    missed = [l for l in attack_labels if flagged[l] == 0]
    print("\nDPI detected :", ", ".join(sorted(caught)) or "none")
    print("DPI missed   :", ", ".join(sorted(missed)) or "none",
          "  <- handled by NetFlow (flooding) / LSTM (stealth) layers")


if __name__ == "__main__":
    main()
