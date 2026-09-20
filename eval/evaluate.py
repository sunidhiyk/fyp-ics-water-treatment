"""
Phase 7 - quantitative evaluation and ablation.

Scores each detection layer (DPI rule engine, NetFlow monitor, LSTM autoencoder)
and the combined detection-in-depth system against the labelled dataset, following
the methodology of the reference papers: precision, recall, false-positive rate,
F1, per-attack-class recall, and detection latency. The ablation shows that no
single layer covers every attack, but the combined system does - the core claim
of the project.

Evaluation unit: one second (tick). Ground truth per tick comes from the device
log's label; a tick is "attack" if its label is not normal. Each layer's alerts
are attributed to the tick they fire on (the transaction tick for DPI/NetFlow, the
window-end tick for the LSTM).

    python -m eval.evaluate
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import dataclass, asdict

from net.config import LABEL_NORMAL, ATTACK_LABELS
from detect.correlator.correlator import correlate, _tick_of


@dataclass
class Metrics:
    layer: str
    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def fpr(self) -> float:
        return self.fp / (self.fp + self.tn) if (self.fp + self.tn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def load_labels(device_log: str) -> list[str]:
    with open(device_log, newline="", encoding="utf-8") as fh:
        return [row["label"] for row in csv.DictReader(fh)]


def alerted_ticks_by_layer(alerts) -> dict[str, set[int]]:
    layers: dict[str, set[int]] = {"dpi": set(), "netflow": set(), "lstm": set()}
    for a in alerts:
        layers.setdefault(a.layer, set()).add(_tick_of(a))
    return layers


def confusion(alerted: set[int], labels: list[str]) -> Metrics:
    tp = fp = fn = tn = 0
    for tick, lbl in enumerate(labels):
        is_attack = lbl != LABEL_NORMAL
        fired = tick in alerted
        if is_attack and fired:
            tp += 1
        elif is_attack and not fired:
            fn += 1
        elif not is_attack and fired:
            fp += 1
        else:
            tn += 1
    return Metrics("", tp, fp, fn, tn)


def per_class_recall(alerted: set[int], labels: list[str]) -> dict[str, float]:
    out = {}
    for cls in ATTACK_LABELS:
        ticks = [t for t, l in enumerate(labels) if l == cls]
        if ticks:
            hit = sum(1 for t in ticks if t in alerted)
            out[cls] = hit / len(ticks)
    return out


def episodes(labels: list[str]) -> list[tuple[str, int, int]]:
    """Contiguous attack runs as (label, start_tick, end_tick_inclusive)."""
    eps, cur = [], None
    for t, l in enumerate(labels):
        if l != LABEL_NORMAL:
            if cur and cur[0] == l:
                cur = (l, cur[1], t)
            else:
                if cur:
                    eps.append(cur)
                cur = (l, t, t)
        else:
            if cur:
                eps.append(cur); cur = None
    if cur:
        eps.append(cur)
    return eps


def detection_latency(alerted: set[int], eps) -> dict[str, float | None]:
    """Seconds from each episode's start to the first alert within it (None=missed)."""
    out = {}
    for lbl, start, end in eps:
        fired = [t for t in range(start, end + 1) if t in alerted]
        out[lbl] = (min(fired) - start) if fired else None
    return out


def evaluate(network_log: str, device_log: str, art_dir: str) -> dict:
    labels = load_labels(device_log)
    alerts = correlate(network_log, device_log, art_dir)
    by_layer = alerted_ticks_by_layer(alerts)

    combos = {
        "DPI (rule)": by_layer["dpi"],
        "NetFlow": by_layer["netflow"],
        "LSTM": by_layer["lstm"],
        "Combined": by_layer["dpi"] | by_layer["netflow"] | by_layer["lstm"],
    }
    eps = episodes(labels)

    results = {"layers": {}, "per_class_recall": {}, "latency": {}, "episodes": eps}
    for name, ticks in combos.items():
        m = confusion(ticks, labels)
        m.layer = name
        results["layers"][name] = {
            "precision": m.precision, "recall": m.recall, "fpr": m.fpr,
            "f1": m.f1, "tp": m.tp, "fp": m.fp, "fn": m.fn, "tn": m.tn,
        }
        results["per_class_recall"][name] = per_class_recall(ticks, labels)
        results["latency"][name] = detection_latency(ticks, eps)
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def print_report(r: dict) -> None:
    print("=" * 74)
    print("ABLATION  -  per-second precision / recall / FPR / F1")
    print("=" * 74)
    print(f"{'layer':14} {'precision':>10} {'recall':>8} {'FPR':>8} {'F1':>8}")
    for name, m in r["layers"].items():
        print(f"{name:14} {m['precision']:>10.3f} {m['recall']:>8.3f} "
              f"{m['fpr']:>8.3f} {m['f1']:>8.3f}")

    print("\n" + "=" * 74)
    print("PER-ATTACK-CLASS RECALL")
    print("=" * 74)
    classes = ATTACK_LABELS
    print(f"{'layer':14} " + " ".join(f"{c[:11]:>12}" for c in classes))
    for name in r["layers"]:
        row = r["per_class_recall"][name]
        print(f"{name:14} " + " ".join(f"{row.get(c,0)*100:>11.0f}%" for c in classes))

    print("\n" + "=" * 74)
    print("DETECTION LATENCY (seconds to first alert; X = missed)")
    print("=" * 74)
    print(f"{'layer':14} " + " ".join(f"{c[:11]:>12}" for c in classes))
    for name in r["layers"]:
        lat = r["latency"][name]
        cells = []
        for c in classes:
            v = lat.get(c)
            cells.append("X" if v is None else str(v))
        print(f"{name:14} " + " ".join(f"{x:>12}" for x in cells))


def make_plots(r: dict, out_dir: str) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(out_dir, exist_ok=True)
    paths = []

    # 1) ablation bars: recall / precision / FPR per layer
    names = list(r["layers"].keys())
    recall = [r["layers"][n]["recall"] for n in names]
    prec = [r["layers"][n]["precision"] for n in names]
    fpr = [r["layers"][n]["fpr"] for n in names]
    x = range(len(names))
    w = 0.25
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar([i - w for i in x], recall, w, label="Recall", color="#3fb950")
    ax.bar(list(x), prec, w, label="Precision", color="#58a6ff")
    ax.bar([i + w for i in x], fpr, w, label="False-positive rate", color="#f85149")
    ax.set_xticks(list(x)); ax.set_xticklabels(names)
    ax.set_ylim(0, 1.05); ax.set_ylabel("score")
    ax.set_title("Detection-in-depth ablation (per-second)")
    ax.legend(); fig.tight_layout()
    p1 = os.path.join(out_dir, "ablation.png")
    fig.savefig(p1, dpi=130); plt.close(fig); paths.append(p1)

    # 2) per-class recall heatmap-style grouped bars
    classes = [c for c in ATTACK_LABELS]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    nlayers = len(names)
    bw = 0.8 / nlayers
    colors = {"DPI (rule)": "#58a6ff", "NetFlow": "#d29922",
              "LSTM": "#bc8cff", "Combined": "#3fb950"}
    for j, name in enumerate(names):
        vals = [r["per_class_recall"][name].get(c, 0) for c in classes]
        ax.bar([i + j * bw for i in range(len(classes))], vals, bw,
               label=name, color=colors.get(name))
    ax.set_xticks([i + 0.4 - bw / 2 for i in range(len(classes))])
    ax.set_xticklabels([c.replace("_", "\n") for c in classes], fontsize=8)
    ax.set_ylim(0, 1.05); ax.set_ylabel("recall")
    ax.set_title("Per-attack-class recall by layer")
    ax.legend(fontsize=8); fig.tight_layout()
    p2 = os.path.join(out_dir, "per_class_recall.png")
    fig.savefig(p2, dpi=130); plt.close(fig); paths.append(p2)
    return paths


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase-7 evaluation and ablation")
    ap.add_argument("--network-log", default="data/run1/network_log.csv")
    ap.add_argument("--device-log", default="data/run1/device_log.csv")
    ap.add_argument("--lstm-art", default="detect/lstm/artifacts")
    ap.add_argument("--out-dir", default="eval/results")
    ap.add_argument("--no-plots", action="store_true")
    args = ap.parse_args()

    r = evaluate(args.network_log, args.device_log, args.lstm_art)
    print_report(r)

    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "results.json"), "w", encoding="utf-8") as fh:
        json.dump({k: v for k, v in r.items() if k != "episodes"}, fh, indent=2)
    if not args.no_plots:
        paths = make_plots(r, args.out_dir)
        print("\nsaved:", ", ".join(paths), "and results.json")


if __name__ == "__main__":
    main()
