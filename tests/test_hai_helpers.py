"""Tests for the HAI-validation helper functions (synthetic data, no download)."""
from __future__ import annotations

import numpy as np

from eval.hai_validate import episodes, threshold_metrics, episode_detection


def test_episodes_from_binary_labels():
    y = np.array([0, 1, 1, 0, 0, 1, 0, 1, 1, 1], dtype=np.int8)
    assert episodes(y) == [(1, 2), (5, 5), (7, 9)]


def test_threshold_metrics_counts():
    scores = np.array([0.1, 0.9, 0.8, 0.2])
    labels = np.array([0, 1, 0, 1])
    m = threshold_metrics(scores, labels, thr=0.5)
    # pred = [F, T, T, F] -> TP=1 (idx1), FP=1 (idx2), FN=1 (idx3), TN=1 (idx0)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 1, 1, 1)
    assert m["precision"] == 0.5 and m["recall"] == 0.5


def test_episode_detection_uses_window_overlap():
    # 12 rows, one attack episode at rows 6-7; window of 3
    y = np.zeros(12, dtype=np.int8); y[6:8] = 1
    scores = np.zeros(10)            # 12 - 3 + 1 windows
    scores[4] = 1.0                  # window 4 ends at row 6 -> overlaps episode
    r = episode_detection(scores, thr=0.5, y=y, window=3)
    assert r["episodes"] == 1 and r["detected"] == 1
    assert r["median_latency_s"] == 0.0
    # nothing fires -> episode missed
    assert episode_detection(np.zeros(10), 0.5, y, 3)["detected"] == 0
