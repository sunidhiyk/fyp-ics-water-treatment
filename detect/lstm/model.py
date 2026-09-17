"""
LSTM autoencoder for multivariate sequence anomaly detection.

An encoder LSTM compresses a window of plant behaviour into a latent vector; a
decoder LSTM reconstructs the window from it. Trained only on normal sequences,
the network reconstructs normal windows well (low error) but reconstructs
anomalous windows — where the temporal relationships between sensors and
actuators are violated — poorly. The per-window reconstruction error is therefore
the anomaly score, and a threshold learned from normal errors separates the two.

This catches attacks the protocol rules cannot: a compromised-HMI stealth
manipulation issues protocol-valid commands, but the resulting behaviour (e.g. an
acid dosing pump held on while pH is otherwise fine) does not match anything the
model saw during normal operation.
"""
from __future__ import annotations

import torch
from torch import nn


class LSTMAutoencoder(nn.Module):
    def __init__(self, n_features: int, hidden: int = 32, latent: int = 16,
                 num_layers: int = 1) -> None:
        super().__init__()
        self.n_features = n_features
        self.hidden = hidden
        self.latent = latent
        self.encoder = nn.LSTM(n_features, hidden, num_layers, batch_first=True)
        self.to_latent = nn.Linear(hidden, latent)
        self.from_latent = nn.Linear(latent, hidden)
        self.decoder = nn.LSTM(hidden, hidden, num_layers, batch_first=True)
        self.output = nn.Linear(hidden, n_features)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: [B, W, F]
        b, w, _ = x.shape
        _, (h, _) = self.encoder(x)                 # h: [layers, B, hidden]
        z = self.to_latent(h[-1])                   # [B, latent]
        dec_in = self.from_latent(z).unsqueeze(1).repeat(1, w, 1)  # [B, W, hidden]
        dec_out, _ = self.decoder(dec_in)           # [B, W, hidden]
        return self.output(dec_out)                 # [B, W, F]


def window_errors(model: LSTMAutoencoder, x: torch.Tensor,
                  batch: int = 256) -> torch.Tensor:
    """Per-window mean-squared reconstruction error. x: [M, W, F] -> [M]."""
    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(x), batch):
            chunk = x[i:i + batch]
            recon = model(chunk)
            err = ((recon - chunk) ** 2).mean(dim=(1, 2))
            out.append(err)
    return torch.cat(out) if out else torch.empty(0)


def per_feature_errors(model: LSTMAutoencoder, x: torch.Tensor,
                       batch: int = 256) -> torch.Tensor:
    """Per-window, per-feature MSE (mean over the time axis). x:[M,W,F] -> [M,F].

    Keeping the error resolved per feature lets the detector standardise each
    signal against its own normal reconstruction level, so a single strongly
    anomalous signal (e.g. one pump held on) is not diluted by the other,
    well-reconstructed features.
    """
    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(x), batch):
            chunk = x[i:i + batch]
            recon = model(chunk)
            err = ((recon - chunk) ** 2).mean(dim=1)   # mean over time -> [B, F]
            out.append(err)
    return torch.cat(out) if out else torch.empty(0)


def standardized_scores(pf_err: torch.Tensor, mu: torch.Tensor,
                        sigma: torch.Tensor) -> torch.Tensor:
    """Window anomaly score = worst per-feature error, standardised by the
    feature's own normal error distribution. pf_err:[M,F] -> [M]."""
    z = (pf_err - mu) / sigma
    return z.max(dim=1).values
