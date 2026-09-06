"""
OT-segment network model: who is on the network and what they are allowed to do.

This is a *simulated* OT segment. Each actor has a logical source identity
(IP/port) that appears in the network log exactly as it would on the wire, so the
Phase-4 DPI engine can reason about "who sent this write" from policy alone —
without being told the ground-truth attacker/normal label.

The authorization policy (AUTHORIZED_WRITERS) is the single source of truth for
"which source is allowed to write actuator/set-point registers." The dataset
generator uses it to craft realistic legit vs. malicious traffic; the DPI rule
engine uses the *same* policy to decide whether a write is unauthorized.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
    role: str          # ground-truth role label (HMI / SCADA / ATTACKER)
    ip: str            # logical source IP on the OT segment
    port: int          # logical source port


# The PLC/HMI that legitimately controls the plant.
HMI = Actor(role="HMI", ip="10.0.0.5", port=50201)
# A supervisory station that legitimately reads (and may issue sanctioned writes).
SCADA = Actor(role="SCADA", ip="10.0.0.10", port=50210)
# The malicious host used in attack scenarios.
ATTACKER = Actor(role="ATTACKER", ip="10.0.0.66", port=44444)

# The PLC/plant endpoint that serves Modbus.
PLC_IP = "10.0.0.2"
PLC_PORT = 502

# Sources permitted to WRITE actuator / set-point registers. Anything else that
# issues a write is, by policy, an unauthorized command injection.
AUTHORIZED_WRITERS: set[str] = {HMI.ip}

# Ground-truth attack-class labels used across the dataset + evaluation.
LABEL_NORMAL = "normal"
LABEL_FDI = "false_data_injection"     # spoofed sensor value
LABEL_CMD_INJECTION = "command_injection"  # unauthorized actuator write
LABEL_FLOODING = "flooding_dos"        # request flood
LABEL_REPLAY = "replay"                # replayed legitimate frames
LABEL_STEALTH = "stealth_manipulation"  # in-band spoof + forced actuator

ATTACK_LABELS = [
    LABEL_FDI, LABEL_CMD_INJECTION, LABEL_FLOODING, LABEL_REPLAY, LABEL_STEALTH,
]
