"""
Shared Alert type emitted by every detection layer (DPI, LSTM, NetFlow).

Modelled on the interpretable alert format from the PA-NIDS paper: an alert does
not merely say "anomaly" — it names the targeted component, the action, the
source and destination, and the likely attacker intent, so an operator can
understand and act on it. The correlator, ledger, and dashboard all consume this
one type regardless of which layer produced it.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field


@dataclass
class Alert:
    ts: float                 # epoch seconds of the triggering event
    layer: str                # "dpi" | "lstm" | "netflow"
    rule: str                 # short rule/detector id, e.g. "unauthorized_writer"
    severity: str             # "high" | "medium" | "low"
    message: str              # full human-readable, PA-NIDS-style sentence
    tag: str = ""             # targeted component (e.g. "LIT101"), if known
    src_ip: str = ""          # attacker/source address, if known
    dst_ip: str = ""          # targeted device address, if known
    intent: str = ""          # suspected attacker intent
    evidence: dict = field(default_factory=dict)  # raw fields that triggered it
    true_label: str = ""      # ground truth (for evaluation only; not for display)

    def to_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        return f"[{self.severity.upper():6}] {self.layer}:{self.rule} — {self.message}"
