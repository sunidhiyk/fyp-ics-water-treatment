"""
Phase-5 test: the LSTM autoencoder + standardised per-feature scoring flags a
stealth-style anomaly (one 'actuator' feature forced on) above every normal
window. Uses a tiny synthetic series and few epochs so it runs fast.
"""
from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from detect.lstm.model import (LSTMAutoencoder, per_feature_errors,
                               standardized_scores)


def _normal_series(n=240):
    t = np.arange(n)
    f0 = np.sin(t / 7.0)                 # a smoothly varying "sensor"
    f1 = np.cos(t / 11.0)               # another "sensor"
    f2 = np.zeros(n)                    # an "actuator" that is normally OFF
    f3 = np.ones(n)                    # an "actuator" that is normally ON
    x = np.stack([f0, f1, f2, f3], axis=1).astype(np.float32)
    return x


def _windows(x, w=10):
    return np.stack([x[i:i + w] for i in range(len(x) - w + 1)]).astype(np.float32)


def test_forced_actuator_anomaly_scores_above_normal():
    torch.manual_seed(0)
    np.random.seed(0)
    x = _normal_series()
    mean, std = x.mean(0), x.std(0)
    std[std < 1e-6] = 1.0
    xs = (x - mean) / std
    win = torch.tensor(_windows(xs))

    model = LSTMAutoencoder(n_features=4, hidden=8, latent=4)
    opt = torch.optim.Adam(model.parameters(), lr=1e-2)
    loss_fn = torch.nn.MSELoss()
    for _ in range(40):
        opt.zero_grad()
        loss = loss_fn(model(win), win)
        loss.backward()
        opt.step()

    pf = per_feature_errors(model, win)
    mu, sigma = pf.mean(0), pf.std(0)
    sigma[sigma < 1e-6] = 1e-6
    normal_scores = standardized_scores(pf, mu, sigma)
    thr = float(normal_scores.max())

    # stealth-style: force the normally-OFF actuator (feature 2) ON for a window
    anom = xs[:10].copy()
    anom[:, 2] = (1.0 - mean[2]) / std[2]        # actuator forced ON, scaled
    anom_t = torch.tensor(anom[None, :, :])
    pf_a = per_feature_errors(model, anom_t)
    score = float(standardized_scores(pf_a, mu, sigma)[0])

    assert score > thr, f"anomaly score {score:.2f} should exceed normal max {thr:.2f}"
