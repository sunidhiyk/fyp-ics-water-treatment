"""
Run the trained LSTM autoencoder over a device log and report detections.

    python -m detect.lstm.detect --device-log data/run1/device_log.csv

Emits an Alert for every window whose reconstruction error exceeds the learned
threshold, then prints per-attack-class detection and the false-positive rate.
The critical result: the stealth manipulation — invisible to the DPI layer — is
caught here.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict

import numpy as np
import torch

from detect.alert import Alert
from net.config import LABEL_NORMAL
from .dataset import FEATURES, load_device_log, make_windows, Scaler
from .model import LSTMAutoencoder, per_feature_errors, standardized_scores

ARTIFACT_DIR = "detect/lstm/artifacts"


def load_model(art_dir: str) -> tuple[LSTMAutoencoder, dict]:
    with open(os.path.join(art_dir, "meta.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    model = LSTMAutoencoder(len(meta["features"]), hidden=meta["hidden"],
                            latent=meta["latent"])
    model.load_state_dict(torch.load(os.path.join(art_dir, "model.pt")))
    model.eval()
    return model, meta


def detect(device_log: str, art_dir: str) -> list[Alert]:
    model, meta = load_model(art_dir)
    scaler = Scaler.from_dict(meta["scaler"])
    window, threshold = meta["window"], meta["threshold"]

    mu = torch.tensor(meta["err_mu"])
    sigma = torch.tensor(meta["err_sigma"])

    x, labels = load_device_log(device_log)
    xs = scaler.transform(x)
    win, wlabels = make_windows(xs, labels, window)
    pf = per_feature_errors(model, torch.tensor(win))
    errs = standardized_scores(pf, mu, sigma).numpy()
    worst_feat = (pf - mu).div(sigma).argmax(dim=1).numpy()

    alerts: list[Alert] = []
    for i, (e, lbl) in enumerate(zip(errs, wlabels)):
        if e > threshold:
            culprit = FEATURES[worst_feat[i]]
            alerts.append(Alert(
                ts=0.0, layer="lstm", rule="sequence_anomaly", severity="high",
                message=(f"Process behaviour over the last {window}s does not match "
                         f"learned normal operation (anomaly score {e:.2f} > "
                         f"{threshold:.2f}); most abnormal signal: {culprit} - "
                         f"possible stealthy or previously-unseen manipulation."),
                intent="stealthy / unseen process manipulation",
                tag=culprit,
                evidence={"window_end_row": i + window - 1, "score": round(float(e), 3),
                          "threshold": round(threshold, 3), "culprit": culprit},
                true_label=lbl,
            ))
    return alerts, errs, wlabels, threshold


def main() -> None:
    ap = argparse.ArgumentParser(description="LSTM sequence anomaly detector")
    ap.add_argument("--device-log", default="data/run1/device_log.csv")
    ap.add_argument("--art-dir", default=ARTIFACT_DIR)
    args = ap.parse_args()

    alerts, errs, wlabels, threshold = detect(args.device_log, args.art_dir)

    total = Counter(wlabels)
    flagged = Counter(a.true_label for a in alerts)

    print(f"threshold = {threshold:.5f}\n")
    print("DETECTION BY ATTACK CLASS  (window level)")
    print(f"{'label':24} {'windows':>8} {'flagged':>8} {'rate':>7}")
    for lbl in sorted(total):
        tot, fl = total[lbl], flagged[lbl]
        rate = f"{100*fl/tot:5.1f}%" if tot else "   n/a"
        print(f"{lbl:24} {tot:>8} {fl:>8} {rate:>7}")

    fp = flagged[LABEL_NORMAL]
    print(f"\nFalse positives on normal windows: {fp}/{total[LABEL_NORMAL]} "
          f"({100*fp/total[LABEL_NORMAL]:.2f}%)")

    attack = [l for l in total if l != LABEL_NORMAL]
    caught = [l for l in attack if flagged[l] > 0]
    missed = [l for l in attack if flagged[l] == 0]
    print("\nLSTM detected :", ", ".join(sorted(caught)) or "none")
    print("LSTM missed   :", ", ".join(sorted(missed)) or "none")


if __name__ == "__main__":
    main()
