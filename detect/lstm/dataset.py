"""
Turn the device log into sliding windows for the LSTM sequence model.

The historian record (device_log.csv) is a multivariate time series: one row per
second, columns for every sensor value and actuator state. The LSTM learns the
*normal temporal shape* of this series, so we present it as overlapping fixed-
length windows.

Scaling is fit on NORMAL rows only (the model must not "see" attacks during
training). A window's label is taken from its last row — the moment being judged.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass

import numpy as np

from sim.register_map import SENSORS, ACTUATORS
from net.config import LABEL_NORMAL

# Feature columns: every sensor reading + every actuator state (the full process).
FEATURES = [s.tag for s in SENSORS] + [a.tag for a in ACTUATORS]


@dataclass
class Scaler:
    mean: np.ndarray
    std: np.ndarray

    def transform(self, x: np.ndarray) -> np.ndarray:
        return (x - self.mean) / self.std

    def to_dict(self) -> dict:
        return {"mean": self.mean.tolist(), "std": self.std.tolist()}

    @staticmethod
    def from_dict(d: dict) -> "Scaler":
        return Scaler(np.array(d["mean"], dtype=np.float32),
                      np.array(d["std"], dtype=np.float32))


def load_device_log(path: str) -> tuple[np.ndarray, list[str]]:
    """Return (values [N,F] float32, labels [N])."""
    rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
    x = np.array([[float(r[c]) for c in FEATURES] for r in rows], dtype=np.float32)
    labels = [r["label"] for r in rows]
    return x, labels


def fit_scaler(x: np.ndarray, labels: list[str]) -> Scaler:
    normal = x[np.array([l == LABEL_NORMAL for l in labels])]
    mean = normal.mean(axis=0)
    std = normal.std(axis=0)
    std[std < 1e-6] = 1.0                      # guard constant features
    return Scaler(mean.astype(np.float32), std.astype(np.float32))


def make_windows(x: np.ndarray, labels: list[str], window: int,
                 ) -> tuple[np.ndarray, list[str]]:
    """Sliding windows [M, window, F] for detection/evaluation.

    Labelling is contamination-aware: a window is attributed to an attack class if
    ANY row within it belongs to that attack (using the most recent attack row's
    label), and is "normal" only when every row is normal. This avoids counting a
    boundary window that still overlaps an attack as a normal false positive.
    """
    xs, ys = [], []
    for i in range(len(x) - window + 1):
        seg = labels[i:i + window]
        attack = [l for l in seg if l != LABEL_NORMAL]
        xs.append(x[i:i + window])
        ys.append(attack[-1] if attack else LABEL_NORMAL)
    return np.asarray(xs, dtype=np.float32), ys


def training_windows(x: np.ndarray, labels: list[str], window: int) -> np.ndarray:
    """Windows whose EVERY row is normal — the clean, attack-free training set."""
    xs = []
    for i in range(len(x) - window + 1):
        if all(labels[j] == LABEL_NORMAL for j in range(i, i + window)):
            xs.append(x[i:i + window])
    return np.asarray(xs, dtype=np.float32)
