"""Phase-7 test: the evaluation metric functions are correct on known inputs."""
from __future__ import annotations

from eval.evaluate import (confusion, per_class_recall, episodes,
                           detection_latency)
from net.config import LABEL_NORMAL, LABEL_FDI, LABEL_FLOODING


def test_confusion_counts_and_rates():
    # ticks:      0 N   1 A   2 A   3 N
    labels = [LABEL_NORMAL, LABEL_FDI, LABEL_FDI, LABEL_NORMAL]
    alerted = {1, 3}                 # 1 = TP, 3 = FP, 2 = FN, 0 = TN
    m = confusion(alerted, labels)
    assert (m.tp, m.fp, m.fn, m.tn) == (1, 1, 1, 1)
    assert m.precision == 0.5 and m.recall == 0.5 and m.fpr == 0.5


def test_per_class_recall():
    labels = [LABEL_FDI, LABEL_FDI, LABEL_FLOODING, LABEL_NORMAL]
    alerted = {0, 2}                 # 1 of 2 FDI ticks, 1 of 1 flooding tick
    r = per_class_recall(alerted, labels)
    assert r[LABEL_FDI] == 0.5
    assert r[LABEL_FLOODING] == 1.0


def test_episode_extraction_and_latency():
    labels = ([LABEL_NORMAL] * 3 + [LABEL_FDI] * 4 + [LABEL_NORMAL] * 2
              + [LABEL_FLOODING] * 3)
    eps = episodes(labels)
    assert eps == [(LABEL_FDI, 3, 6), (LABEL_FLOODING, 9, 11)]
    # first FDI alert at tick 5 -> latency 2; flooding alert at 9 -> latency 0
    lat = detection_latency({5, 9}, eps)
    assert lat[LABEL_FDI] == 2 and lat[LABEL_FLOODING] == 0
    # a missed episode reports None
    assert detection_latency({9}, eps)[LABEL_FDI] is None
