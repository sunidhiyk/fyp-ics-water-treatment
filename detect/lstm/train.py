"""
Train the LSTM autoencoder on NORMAL plant behaviour and derive an anomaly
threshold. Saves the model weights and a sidecar JSON (scaler, threshold, config)
so the detector can run without retraining.

    python -m detect.lstm.train --device-log data/run1/device_log.csv
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
import torch
from torch import nn

from .dataset import (FEATURES, load_device_log, fit_scaler,
                      make_windows, training_windows)
from .model import (LSTMAutoencoder, per_feature_errors, standardized_scores)

ARTIFACT_DIR = "detect/lstm/artifacts"


def set_seed(seed: int) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)


def train(device_log: str, window: int, hidden: int, latent: int, epochs: int,
          lr: float, seed: int, threshold_pct: float, out_dir: str) -> None:
    set_seed(seed)
    os.makedirs(out_dir, exist_ok=True)

    x, labels = load_device_log(device_log)
    scaler = fit_scaler(x, labels)
    xs = scaler.transform(x)

    train_x = training_windows(xs, labels, window)
    if len(train_x) == 0:
        raise SystemExit("no attack-free training windows found")
    all_w, all_y = make_windows(xs, labels, window)

    print(f"features={len(FEATURES)}  window={window}  "
          f"train_windows={len(train_x)}  all_windows={len(all_w)}")

    model = LSTMAutoencoder(len(FEATURES), hidden=hidden, latent=latent)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()

    # small dataset -> full-batch / few mini-batches is fine
    tx = torch.tensor(train_x)
    n = len(tx)
    bs = min(64, n)
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(n)
        total = 0.0
        for i in range(0, n, bs):
            idx = perm[i:i + bs]
            batch = tx[idx]
            opt.zero_grad()
            recon = model(batch)
            loss = loss_fn(recon, batch)
            loss.backward()
            opt.step()
            total += loss.item() * len(idx)
        if (ep + 1) % max(1, epochs // 10) == 0 or ep == 0:
            print(f"  epoch {ep+1:3}/{epochs}  train MSE {total/n:.5f}")

    # per-feature normal error statistics -> standardised anomaly score
    pf = per_feature_errors(model, tx)
    mu = pf.mean(dim=0)
    sigma = pf.std(dim=0)
    sigma[sigma < 1e-6] = 1e-6
    train_scores = standardized_scores(pf, mu, sigma).numpy()
    threshold = float(np.percentile(train_scores, threshold_pct))
    threshold = max(threshold, float(train_scores.max()) * 1.05)  # margin over normal
    print(f"normal std-score: mean={train_scores.mean():.3f} "
          f"max={train_scores.max():.3f}  -> threshold={threshold:.3f}")

    torch.save(model.state_dict(), os.path.join(out_dir, "model.pt"))
    meta = {
        "features": FEATURES, "window": window, "hidden": hidden,
        "latent": latent, "threshold": threshold, "scaler": scaler.to_dict(),
        "err_mu": mu.tolist(), "err_sigma": sigma.tolist(),
    }
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    print(f"saved model + meta to {out_dir}/")


def main() -> None:
    ap = argparse.ArgumentParser(description="Train LSTM autoencoder on normal data")
    ap.add_argument("--device-log", default="data/run1/device_log.csv")
    ap.add_argument("--window", type=int, default=10)
    ap.add_argument("--hidden", type=int, default=32)
    ap.add_argument("--latent", type=int, default=16)
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--threshold-pct", type=float, default=99.5,
                    help="percentile of normal error used as the alarm threshold")
    ap.add_argument("--out-dir", default=ARTIFACT_DIR)
    args = ap.parse_args()
    train(args.device_log, args.window, args.hidden, args.latent, args.epochs,
          args.lr, args.seed, args.threshold_pct, args.out_dir)


if __name__ == "__main__":
    main()
