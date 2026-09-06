"""
Discrete-time physics model of the multi-stage water-treatment plant.

The model is intentionally simple but *coupled*: each stage feeds the next, and
sensor values depend on upstream actuator states. That coupling is what makes an
LSTM able to learn cross-sensor temporal correlations (level -> valve -> pump),
and what a stealthy attack has to violate to be caught.

State is a plain dict of physical values keyed by SWaT tag. One ``step(dt)``
advances the simulation by ``dt`` seconds. Actuator commands are read from the
same state dict (the PLC/HMI writes them via Modbus; see modbus_server.py).

Units follow register_map.py. Levels in mm, flows in m3/h, pH dimensionless.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .register_map import BY_TAG, SENSORS, ACTUATORS, Kind

# Tank cross-sectional areas (m^2) used to convert flow (m3/h) into level change.
TANK_AREA = {
    "LIT101": 1.5,   # raw water tank
    "LIT301": 1.2,   # UF feed tank
    "LIT401": 1.0,   # RO feed tank
}

# Nominal pump flow when running (m3/h).
PUMP_FLOW = {
    "P101": 2.0,
    "P301": 1.8,
    "P401": 1.6,
    "P501": 1.2,
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass
class Plant:
    """Coupled water-treatment process simulation."""

    noise: float = 0.01          # fractional sensor noise (gaussian sigma)
    seed: int | None = None
    state: dict[str, float] = field(default_factory=dict)
    t: float = 0.0               # elapsed sim seconds

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        if not self.state:
            self.reset()

    # -- lifecycle ---------------------------------------------------------
    def reset(self) -> None:
        self.t = 0.0
        self.state = {}
        # Sensors start mid-band, actuators start in a safe idle configuration.
        for p in SENSORS:
            self.state[p.tag] = (p.lo + p.hi) / 2.0
        for p in ACTUATORS:
            self.state[p.tag] = 0  # everything OFF/closed at start
        # A sensible running baseline so the process is "alive" immediately.
        self.state["LIT101"] = 700.0
        self.state["LIT301"] = 650.0
        self.state["LIT401"] = 600.0
        self.state["AIT202"] = 7.3
        self.state["MV101"] = 1     # inlet valve open
        self.state["P101"] = 1      # transfer pump running
        self.state["P301"] = 1
        self.state["P401"] = 1
        self.state["P501"] = 1

    # -- helpers -----------------------------------------------------------
    def _on(self, tag: str) -> bool:
        return int(round(self.state.get(tag, 0))) == 1

    def _valve_open(self, tag: str) -> bool:
        # 0=closed, 1=open, 2=transition (treat as half-open)
        return int(round(self.state.get(tag, 0))) >= 1

    def _noisy(self, tag: str, value: float) -> float:
        p = BY_TAG[tag]
        sigma = abs(value) * self.noise
        return _clamp(value + self._rng.gauss(0, sigma), 0.0, p.hi * 1.5)

    # -- dynamics ----------------------------------------------------------
    def step(self, dt: float = 1.0) -> dict[str, float]:
        """Advance the plant by ``dt`` seconds and return a copy of state."""
        h = dt / 3600.0  # seconds -> hours (flows are per hour)
        s = self.state

        # --- P1 intake: tank fills through MV101, drains via P101 ----------
        inflow = 2.5 if self._valve_open("MV101") else 0.0
        outflow_101 = PUMP_FLOW["P101"] if self._on("P101") else 0.0
        s["FIT101"] = inflow
        dl = (inflow - outflow_101) * h / TANK_AREA["LIT101"] * 1000.0  # m -> mm
        s["LIT101"] = _clamp(s["LIT101"] + dl, 0, 1200)

        # --- P2 dosing: pH pulled by NaOCl (up) / HCl (down) pumps ----------
        ph = s["AIT202"]
        if self._on("P201"):
            ph += 0.03 * dt        # NaOCl raises pH
        if self._on("P203"):
            ph -= 0.03 * dt        # HCl lowers pH
        # natural relaxation toward neutral feed water
        ph += (7.3 - ph) * 0.01 * dt
        s["AIT202"] = _clamp(ph, 5.5, 9.5)
        s["AIT201"] = 180 + (ph - 7.0) * 20   # conductivity tracks dosing
        s["FIT201"] = outflow_101

        # --- P3 ultrafiltration: feed tank + differential pressure ---------
        in_301 = outflow_101
        out_301 = PUMP_FLOW["P301"] if self._on("P301") else 0.0
        dl3 = (in_301 - out_301) * h / TANK_AREA["LIT301"] * 1000.0
        s["LIT301"] = _clamp(s["LIT301"] + dl3, 0, 1200)
        s["FIT301"] = out_301
        # DP rises with throughput, drops on backwash (MV301 open)
        dp = s["DPIT301"] + (out_301 * 2.0 - 3.0) * dt * 0.1
        if self._valve_open("MV301"):
            dp -= 5.0 * dt
        s["DPIT301"] = _clamp(dp, 0, 60)

        # --- P4 dechlorination: residual chlorine + RO feed tank -----------
        in_401 = out_301
        out_401 = PUMP_FLOW["P401"] if self._on("P401") else 0.0
        dl4 = (in_401 - out_401) * h / TANK_AREA["LIT401"] * 1000.0
        s["LIT401"] = _clamp(s["LIT401"] + dl4, 0, 1200)
        # UV/dechlor drives residual chlorine down when P401 runs
        cl = s["AIT401"] - (0.02 * dt if self._on("P401") else -0.01 * dt)
        s["AIT401"] = _clamp(cl, 0.0, 1.5)

        # --- P5 reverse osmosis: pressure + permeate -----------------------
        if self._on("P501"):
            s["PIT501"] = _clamp(s["PIT501"] + 20 * dt, 0, 280)
            s["FIT501"] = PUMP_FLOW["P501"]
            s["AIT501"] = 30 + (ph - 7.0) * 5
        else:
            s["PIT501"] = _clamp(s["PIT501"] - 30 * dt, 0, 280)
            s["FIT501"] = 0.0
            s["AIT501"] = 60.0

        self.t += dt
        return dict(s)

    # -- observation -------------------------------------------------------
    def sensor_reading(self, tag: str) -> float:
        """Sensor value with measurement noise applied (what the PLC 'sees')."""
        return self._noisy(tag, self.state[tag])

    def snapshot(self) -> dict[str, float]:
        """Noise-free ground-truth snapshot (for labelling/datasets)."""
        return dict(self.state)
