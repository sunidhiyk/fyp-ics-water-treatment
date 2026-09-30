"""
External validation of the LSTM detector on the public HAI dataset.

Our Phase-5 LSTM was trained and tested on data from our own simulator. An
obvious question is whether the approach holds up on data we did not generate.
This script answers it using HAI 22.04 (HIL-based Augmented ICS, National
Security Research Institute) - a real hardware-in-the-loop testbed with boiler,
turbine, water-treatment and HIL processes, sampled at 1 Hz like our device log.

Protocol (unsupervised, same as our detector):
  * train the SAME LSTM autoencoder on HAI's normal-only training file,
  * derive the alarm threshold from normal training scores only,
  * score HAI's test file, which contains real, labelled attacks (~1% of time),
  * report ROC-AUC (threshold-free), precision/recall/F1/FPR at the learned
    threshold, and attack-episode detection + latency.

Both our per-feature standardised score and plain reconstruction MSE are reported
so the scoring choice can be compared on real data.

    python -m eval.hai_validate
"""
from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np
import pandas as pd
import torch
from numpy.lib.stride_tricks import sliding_window_view
from sklearn.metrics import (average_precision_score, precision_recall_curve,
                             roc_auc_score)

from detect.lstm.model import (LSTMAutoencoder, per_feature_errors,
                               standardized_scores)


def load_hai(path: str) -> tuple[np.ndarray, np.ndarray, list[str]]:
    df = pd.read_csv(path)
    y = df["Attack"].to_numpy(dtype=np.int8)
    feats = df.drop(columns=["timestamp", "Attack"])
    return feats.to_numpy(dtype=np.float32), y, list(feats.columns)


def score_windows(model, xs: np.ndarray, window: int, mu, sigma,
                  batch: int = 1024) -> tuple[np.ndarray, np.ndarray]:
    """Score every length-``window`` window of xs without materialising them all.

    Returns (max-standardised score, mean-MSE score), one per window.
    """
    x_t = torch.from_numpy(xs)
    wins = x_t.unfold(0, window, 1)                # (M, F, W) view - no copy
    n = wins.shape[0]
    s_max = np.empty(n, dtype=np.float32)
    s_mean = np.empty(n, dtype=np.float32)
    for i in range(0, n, batch):
        chunk = wins[i:i + batch].permute(0, 2, 1).contiguous()   # (B, W, F)
        pf = per_feature_errors(model, chunk)
        s_max[i:i + batch] = standardized_scores(pf, mu, sigma).numpy()
        s_mean[i:i + batch] = pf.mean(dim=1).numpy()
    return s_max, s_mean


def episodes(y: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous attack runs (start, end inclusive) in a 0/1 label array."""
    eps, start = [], None
    for t, v in enumerate(y):
        if v and start is None:
            start = t
        elif not v and start is not None:
            eps.append((start, t - 1)); start = None
    if start is not None:
        eps.append((start, len(y) - 1))
    return eps


def threshold_metrics(scores: np.ndarray, wlabel: np.ndarray, thr: float) -> dict:
    pred = scores > thr
    tp = int(np.sum(pred & (wlabel == 1)))
    fp = int(np.sum(pred & (wlabel == 0)))
    fn = int(np.sum(~pred & (wlabel == 1)))
    tn = int(np.sum(~pred & (wlabel == 0)))
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": p, "recall": r,
            "f1": 2 * p * r / (p + r) if p + r else 0.0,
            "fpr": fp / (fp + tn) if fp + tn else 0.0,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def episode_detection(scores: np.ndarray, thr: float, y: np.ndarray,
                      window: int) -> dict:
    """An attack episode counts as detected if any window overlapping it fires."""
    fired_end = np.flatnonzero(scores > thr) + window - 1   # window -> end row
    fired_rows = set(fired_end.tolist())
    eps = episodes(y)
    detected, lat = 0, []
    for s, e in eps:
        hits = [t for t in range(s, e + window) if t in fired_rows]
        if hits:
            detected += 1
            lat.append(max(0, min(hits) - s))
    return {"episodes": len(eps), "detected": detected,
            "median_latency_s": float(np.median(lat)) if lat else None,
            "latencies_s": lat}


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate the LSTM on the public HAI dataset")
    ap.add_argument("--train", default="data/public/hai/train1.csv",
                    help="comma-separated normal-only training files")
    ap.add_argument("--calib", default="",
                    help="optional held-out normal file used only to set the threshold")
    ap.add_argument("--test", default="data/public/hai/test1.csv")
    ap.add_argument("--tag", default="", help="suffix for output file names")
    ap.add_argument("--window", type=int, default=10)
    ap.add_argument("--stride", type=int, default=5, help="training-window stride")
    ap.add_argument("--hidden", type=int, default=64)
    ap.add_argument("--latent", type=int, default=32)
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--threshold-pct", type=float, default=99.9)
    ap.add_argument("--clip", type=float, default=5.0,
                    help="clip scaled inputs to +/-clip std (0 disables)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-dir", default="eval/results")
    args = ap.parse_args()

    torch.manual_seed(args.seed); np.random.seed(args.seed)
    t0 = time.time()

    # One or more normal-only training days (comma-separated).
    train_paths = [p.strip() for p in args.train.split(",") if p.strip()]
    days = [load_hai(p) for p in train_paths]
    cols = days[0][2]
    for (x, y, c), p in zip(days, train_paths):
        assert y.sum() == 0, f"{p} should be normal-only"
        assert c == cols, f"{p} has different columns"
    xte, yte, _ = load_hai(args.test)
    xtr = np.concatenate([d[0] for d in days])

    # drop features that never vary in normal operation (no information)
    keep = xtr.std(axis=0) > 1e-6
    feats = [c for c, k in zip(cols, keep) if k]
    mean, std = xtr[:, keep].mean(0), xtr[:, keep].std(0)

    def prep(x: np.ndarray) -> np.ndarray:
        s = ((x[:, keep] - mean) / std).astype(np.float32)
        if args.clip > 0:
            # Robustness guard: a sensor that is near-constant in training (tiny
            # std) turns any small day-to-day drift into an enormous z-score, which
            # then dominates every window's error. Clipping bounds each signal's
            # influence. Chosen a priori, not tuned on test labels.
            s = np.clip(s, -args.clip, args.clip)
        return s

    xte_s = prep(xte)
    print(f"HAI: train {len(train_paths)} day(s), {len(xtr):,}s normal | "
          f"test {len(xte):,}s, {int(yte.sum())} attack s | {len(feats)} "
          f"informative features (dropped {int((~keep).sum())} constant)")

    # ---- train on normal ----
    # windows are built per day so none straddles the gap between two recordings
    train_w = np.concatenate([
        sliding_window_view(prep(d[0]), args.window, axis=0)[::args.stride]
        .transpose(0, 2, 1) for d in days])
    train_w = np.ascontiguousarray(train_w)                      # (M, W, F)
    tx = torch.from_numpy(train_w)
    model = LSTMAutoencoder(len(feats), hidden=args.hidden, latent=args.latent)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = torch.nn.MSELoss()
    print(f"training on {len(tx):,} normal windows ...")
    for ep in range(args.epochs):
        model.train()
        perm = torch.randperm(len(tx))
        total = 0.0
        for i in range(0, len(tx), 256):
            b = tx[perm[i:i + 256]]
            opt.zero_grad()
            loss = loss_fn(model(b), b)
            loss.backward(); opt.step()
            total += loss.item() * len(b)
        print(f"  epoch {ep+1:2}/{args.epochs}  MSE {total/len(tx):.4f}")

    # ---- normal error statistics (training data) ----
    pf_tr = per_feature_errors(model, tx)
    mu, sigma = pf_tr.mean(0), pf_tr.std(0)
    sigma[sigma < 1e-6] = 1e-6

    # ---- alarm threshold ----
    if args.calib:
        # Held-out normal day, never used for training: the threshold then reflects
        # how much normal behaviour varies from one day to the next.
        xc, yc, cc = load_hai(args.calib)
        assert yc.sum() == 0 and cc == cols, "calibration day must be normal-only"
        c_max, c_mean = score_windows(model, prep(xc), args.window, mu, sigma)
        thr_source = f"held-out normal day ({os.path.basename(args.calib)})"
    else:
        c_max = standardized_scores(pf_tr, mu, sigma).numpy()
        c_mean = pf_tr.mean(dim=1).numpy()
        thr_source = "training windows"
    thr_max = float(np.percentile(c_max, args.threshold_pct))
    thr_mean = float(np.percentile(c_mean, args.threshold_pct))
    print(f"threshold: {args.threshold_pct}th percentile of scores on {thr_source}")

    # ---- score the test set ----
    s_max, s_mean = score_windows(model, xte_s, args.window, mu, sigma)
    # contamination-aware window label: attack if any row in the window is attack
    wlabel = sliding_window_view(yte, args.window).max(axis=1)

    results = {"dataset": "HAI 22.04",
               "train_files": [os.path.basename(p) for p in train_paths],
               "calibration": thr_source,
               "test_file": os.path.basename(args.test),
               "train_seconds": int(len(xtr)), "test_seconds": int(len(xte)),
               "attack_seconds": int(yte.sum()), "features": len(feats),
               "window": args.window, "threshold_pct": args.threshold_pct,
               "scores": {}}
    for name, s, thr in (("per-feature std (ours)", s_max, thr_max),
                         ("mean MSE", s_mean, thr_mean)):
        # Oracle upper bound: the best F1 over all thresholds. This USES test labels
        # to choose the threshold, so it is not a deployable result - it shows how
        # well the score separates the classes if the threshold were calibrated.
        prec, rec, thrs = precision_recall_curve(wlabel, s)
        f1s = 2 * prec * rec / np.clip(prec + rec, 1e-12, None)
        best = int(np.nanargmax(f1s[:-1])) if len(thrs) else 0
        oracle_thr = float(thrs[best]) if len(thrs) else thr
        results["scores"][name] = {
            "roc_auc": float(roc_auc_score(wlabel, s)),
            "pr_auc": float(average_precision_score(wlabel, s)),
            "attack_base_rate": float(wlabel.mean()),
            "threshold": thr,
            "at_threshold": threshold_metrics(s, wlabel, thr),
            "episodes": episode_detection(s, thr, yte, args.window),
            "oracle_best": {"threshold": oracle_thr,
                            **threshold_metrics(s, wlabel, oracle_thr),
                            "episodes": episode_detection(s, oracle_thr, yte,
                                                          args.window)},
        }

    # ---- report ----
    print("\n" + "=" * 70)
    print("HAI EXTERNAL VALIDATION  (train on normal, test on real attacks)")
    print("=" * 70)
    for name, r in results["scores"].items():
        m, e, o = r["at_threshold"], r["episodes"], r["oracle_best"]
        print(f"\n[{name}]")
        print(f"  ROC-AUC  {r['roc_auc']:.3f}    PR-AUC {r['pr_auc']:.3f} "
              f"(random = {r['attack_base_rate']:.3f})")
        print(f"  train-derived threshold : P {m['precision']:.3f}  R {m['recall']:.3f}"
              f"  F1 {m['f1']:.3f}  FPR {m['fpr']:.3f}"
              f"  episodes {e['detected']}/{e['episodes']}")
        print(f"  oracle best threshold   : P {o['precision']:.3f}  R {o['recall']:.3f}"
              f"  F1 {o['f1']:.3f}  FPR {o['fpr']:.3f}"
              f"  episodes {o['episodes']['detected']}/{o['episodes']['episodes']}"
              f"  (upper bound - uses test labels)")
    print(f"\n(runtime {time.time()-t0:.0f}s)")

    os.makedirs(args.out_dir, exist_ok=True)
    sfx = f"_{args.tag}" if args.tag else ""
    with open(os.path.join(args.out_dir, f"hai_results{sfx}.json"), "w",
              encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)

    # ---- timeline plot ----
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11, 3.8))
    x = np.arange(len(s_max)) + args.window - 1
    ax.plot(x / 3600, s_max, lw=0.5, color="#58a6ff", label="anomaly score")
    ax.axhline(thr_max, color="#f85149", lw=1, ls="--", label="threshold (from normal)")
    for s, e in episodes(yte):
        ax.axvspan(s / 3600, (e + 1) / 3600, color="#f85149", alpha=0.18)
    ax.set_yscale("log")
    ax.set_xlabel("time in test set (hours)"); ax.set_ylabel("score (log)")
    ax.set_title(f"HAI {os.path.basename(args.test)} - LSTM score vs real attacks "
                 f"(shaded); trained on {len(train_paths)} recording(s)")
    ax.legend(loc="upper right", fontsize=8); fig.tight_layout()
    p = os.path.join(args.out_dir, f"hai_timeline{sfx}.png")
    fig.savefig(p, dpi=130); plt.close(fig)
    print("saved", p, f"and hai_results{sfx}.json")


if __name__ == "__main__":
    main()
