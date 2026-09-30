"""
Figures for the final report that are not produced by the evaluation scripts.

    python -m report.make_figures

Writes report/figures/architecture.png and report/figures/dataset_timeline.png.
The evaluation plots (eval/results/*.png) and the dashboard screenshots are
produced elsewhere and referenced directly by the report.
"""
from __future__ import annotations

import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = os.path.join("report", "figures")

# light fills + strong edges read well on white paper
C = {
    "plant": ("#e8f1fb", "#2f6db5"), "hmi": ("#e8f1fb", "#2f6db5"),
    "attack": ("#fde8e7", "#c62828"), "log": ("#f1f1f1", "#555555"),
    "dpi": ("#e6f0ff", "#1f5fbf"), "nf": ("#fdf3dc", "#b7791f"),
    "lstm": ("#f1eafc", "#6b3fb0"), "trust": ("#e5f5ef", "#1e7d5a"),
}


def box(ax, x0, y0, x1, y1, title, sub, kind):
    fill, edge = C[kind]
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0,
                                boxstyle="round,pad=0.4,rounding_size=1.2",
                                fc=fill, ec=edge, lw=1.6))
    cx = (x0 + x1) / 2
    ax.text(cx, (y0 + y1) / 2 + (1.1 if sub else 0), title, ha="center",
            va="center", fontsize=10.5, fontweight="bold", color="#1b1b1b")
    if sub:
        ax.text(cx, (y0 + y1) / 2 - 1.6, sub, ha="center", va="center",
                fontsize=8.3, color="#333333")


def arrow(ax, x0, y0, x1, y1, color="#444444", style="-|>", ls="-"):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(arrowstyle=style, color=color, lw=1.5,
                                linestyle=ls, shrinkA=0, shrinkB=0))


def architecture() -> str:
    fig, ax = plt.subplots(figsize=(11, 7.2))
    ax.set_xlim(0, 100); ax.set_ylim(0, 66); ax.axis("off")

    # --- OT segment -------------------------------------------------------
    box(ax, 3, 52, 31, 62, "Plant simulator", "5 stages - 13 sensors, 9 actuators", "plant")
    box(ax, 69, 52, 97, 62, "Soft-PLC / HMI", "authorised writer 10.0.0.5", "hmi")
    ax.plot([31.8, 68.2], [57, 57], color="#2f6db5", lw=3)
    ax.text(50, 58.6, "Modbus TCP (real frames)", ha="center", fontsize=9.5,
            color="#2f6db5", fontweight="bold")
    box(ax, 40, 44, 60, 50.5, "Attacker", "10.0.0.66 - 5 attack types", "attack")
    arrow(ax, 50, 51, 50, 56.4, color="#c62828")

    # --- data streams -----------------------------------------------------
    box(ax, 3, 32, 31, 40, "Device log", "1 Hz sensor/actuator history", "log")
    box(ax, 69, 32, 97, 40, "Network log", "decoded Modbus transactions", "log")
    arrow(ax, 17, 51.4, 17, 40.6)
    arrow(ax, 64, 57, 83, 40.6)
    ax.text(74.5, 49, "request log", fontsize=8.5, color="#555555", style="italic")

    # --- detection layer --------------------------------------------------
    box(ax, 3, 17, 31, 25.5, "LSTM autoencoder", "stealthy / unseen behaviour", "lstm")
    box(ax, 38, 17, 64, 25.5, "DPI rule engine", "who wrote what, where", "dpi")
    box(ax, 71, 17, 97, 25.5, "NetFlow monitor", "request floods (DoS)", "nf")
    arrow(ax, 17, 31.4, 17, 26.1)
    arrow(ax, 76, 31.4, 51, 26.1)
    arrow(ax, 88, 31.4, 84, 26.1)
    ax.text(1.5, 28.5, "detection-in-depth", fontsize=9, color="#666666",
            rotation=90, va="center")

    # --- trust + response -------------------------------------------------
    box(ax, 37, 2, 63, 10, "Correlator", "one time-ordered incident stream", "trust")
    box(ax, 3, 2, 31, 10, "Operator dashboard", "FastAPI + WebSocket", "trust")
    box(ax, 69, 2, 97, 10, "Hash-chain ledger", "SHA-256 links + Ed25519", "trust")
    arrow(ax, 17, 16.4, 44, 10.6)
    arrow(ax, 51, 16.4, 50, 10.6)
    arrow(ax, 84, 16.4, 56, 10.6)
    arrow(ax, 36.4, 6, 31.6, 6)
    arrow(ax, 63.6, 6, 68.4, 6)

    fig.tight_layout()
    p = os.path.join(OUT, "architecture.png")
    fig.savefig(p, dpi=170); plt.close(fig)
    return p


def dataset_timeline(device_log: str = "data/run1/device_log.csv") -> str:
    rows = list(csv.DictReader(open(device_log, newline="", encoding="utf-8")))
    t = [int(r["tick"]) for r in rows]
    lit = [float(r["LIT101"]) for r in rows]
    ph = [float(r["AIT202"]) for r in rows]
    p101 = [int(float(r["P101"])) for r in rows]
    p203 = [int(float(r["P203"])) for r in rows]
    labels = [r["label"] for r in rows]

    # contiguous attack windows
    wins, cur = [], None
    for i, l in enumerate(labels):
        if l != "normal":
            cur = (l, cur[1] if cur and cur[0] == l else i, i)
        elif cur:
            wins.append(cur); cur = None
    if cur:
        wins.append(cur)
    short = {"false_data_injection": "False data\ninjection",
             "command_injection": "Command\ninjection", "flooding_dos": "Flooding\n(DoS)",
             "replay": "Replay", "stealth_manipulation": "Stealth\nmanipulation"}

    fig, axes = plt.subplots(3, 1, figsize=(11, 6.4), sharex=True,
                             gridspec_kw={"height_ratios": [1.2, 1, 0.8]})
    for ax in axes:
        for l, s, e in wins:
            ax.axvspan(s, e + 1, color="#f28b82", alpha=0.25, lw=0)
    for l, s, e in wins:
        axes[0].text((s + e) / 2, 1240, short[l], ha="center", va="bottom",
                     fontsize=8, color="#8e1b1b")

    axes[0].plot(t, lit, color="#1f5fbf", lw=1.2)
    axes[0].axhline(1100, color="#c62828", ls="--", lw=0.9)
    axes[0].set_ylabel("LIT101\ntank level (mm)"); axes[0].set_ylim(0, 1450)
    axes[0].text(3, 1115, "safe limit 1100", fontsize=7.5, color="#c62828")

    axes[1].plot(t, ph, color="#6b3fb0", lw=1.2)
    axes[1].set_ylabel("AIT202\npH")

    axes[2].step(t, p101, where="post", color="#1e7d5a", lw=1.2, label="P101 transfer pump")
    axes[2].step(t, [v + 1.3 for v in p203], where="post", color="#b7791f", lw=1.2,
                 label="P203 acid pump (offset)")
    axes[2].set_yticks([0, 1, 1.3, 2.3]); axes[2].set_yticklabels(["off", "on", "off", "on"])
    axes[2].set_ylabel("pump state"); axes[2].legend(loc="upper left", fontsize=7.5)
    axes[2].set_xlabel("time (s)")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    p = os.path.join(OUT, "dataset_timeline.png")
    fig.savefig(p, dpi=160); plt.close(fig)
    return p


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    for p in (architecture(), dataset_timeline()):
        print("saved", p)


if __name__ == "__main__":
    main()
