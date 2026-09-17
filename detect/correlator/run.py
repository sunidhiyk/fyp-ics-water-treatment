"""
Run the full detection-in-depth pipeline and the tamper-evident ledger.

    python -m detect.correlator.run

Steps:
  1. correlate DPI + NetFlow + LSTM alerts over the dataset,
  2. print which layer(s) detect each attack class (episode level),
  3. write all control commands + alerts to a signed hash-chain ledger and verify,
  4. demonstrate tamper detection by editing one ledger entry.
"""
from __future__ import annotations

import argparse
import copy
from collections import defaultdict

from net.config import ATTACK_LABELS, LABEL_NORMAL
from ledger.hashchain import HashChainLedger
from .correlator import correlate, record_to_ledger


def main() -> None:
    ap = argparse.ArgumentParser(description="Detection-in-depth correlator + ledger")
    ap.add_argument("--network-log", default="data/run1/network_log.csv")
    ap.add_argument("--device-log", default="data/run1/device_log.csv")
    ap.add_argument("--lstm-art", default="detect/lstm/artifacts")
    ap.add_argument("--ledger", default="data/run1/ledger.jsonl")
    ap.add_argument("--key", default="data/run1/ledger_key.pem")
    args = ap.parse_args()

    alerts = correlate(args.network_log, args.device_log, args.lstm_art)

    # ---- which layers caught which attack (episode level) ----
    layers_by_label: dict[str, set[str]] = defaultdict(set)
    count_by_label_layer: dict[tuple[str, str], int] = defaultdict(int)
    for a in alerts:
        if a.true_label and a.true_label != LABEL_NORMAL:
            layers_by_label[a.true_label].add(a.layer)
        count_by_label_layer[(a.true_label, a.layer)] += 1

    print("=" * 70)
    print("DETECTION-IN-DEPTH COVERAGE  (which layer catches each attack)")
    print("=" * 70)
    print(f"{'attack class':24} {'DPI':>5} {'NetFlow':>8} {'LSTM':>6}   detected")
    for lbl in ATTACK_LABELS:
        d = "yes" if "dpi" in layers_by_label[lbl] else "-"
        n = "yes" if "netflow" in layers_by_label[lbl] else "-"
        l = "yes" if "lstm" in layers_by_label[lbl] else "-"
        ok = "COVERED" if layers_by_label[lbl] else "MISSED"
        print(f"{lbl:24} {d:>5} {n:>8} {l:>6}   {ok}")

    fp = count_by_label_layer.get((LABEL_NORMAL, "dpi"), 0) + \
        count_by_label_layer.get((LABEL_NORMAL, "netflow"), 0) + \
        count_by_label_layer.get((LABEL_NORMAL, "lstm"), 0)
    print(f"\nTotal alerts: {len(alerts)}   False positives on normal: {fp}")

    # ---- ledger ----
    import os
    for p in (args.ledger, args.key):                # fresh ledger each run
        if os.path.exists(p):
            os.remove(p)
    ledger = record_to_ledger(alerts, args.network_log, args.ledger, args.key)
    print("\n" + "=" * 70)
    print("TAMPER-EVIDENT LEDGER")
    print("=" * 70)
    print(f"Appended {len(ledger)} records (control commands + alerts)")
    print("Integrity check:", ledger.verify())

    # ---- tamper demonstration ----
    reloaded = HashChainLedger(path=args.ledger, key_path=args.key)
    victim = min(5, len(reloaded) - 1)
    # simulate an attacker editing a stored record to hide an action
    reloaded._entries[victim]["payload"]["value"] = 999.0
    print(f"\nSimulating tamper: edited payload of entry {victim} ...")
    print("Integrity check:", reloaded.verify())


if __name__ == "__main__":
    main()
