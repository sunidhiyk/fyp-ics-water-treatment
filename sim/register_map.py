"""
Modbus register map for the simulated water-treatment plant.

This is the single source of truth shared by:
  - the plant simulator (sim/plant.py)          -> writes sensor values, reads actuator commands
  - the OpenPLC / control logic                 -> reads sensors, writes actuator commands
  - the protocol-aware DPI rule engine (detect) -> decodes writes against these definitions

Naming follows the SWaT convention used in the reference papers so the mapping
table in the proposal (LIT101, MV101, P101, AIT202, ...) is directly recognisable.

Value encoding
--------------
Modbus registers are 16-bit unsigned integers. Physical (float) values are
scaled by ``scale`` before being written to a register and divided back on read.
e.g. a pH of 7.35 with scale=100 is stored as 735.

    raw_register = round(physical_value * scale)
    physical_value = raw_register / scale
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Kind(str, Enum):
    SENSOR = "sensor"      # written by the plant, read by the PLC (input-like)
    ACTUATOR = "actuator"  # written by the PLC/HMI, read by the plant (command)


class Stage(str, Enum):
    INTAKE = "P1_intake"
    DOSING = "P2_chemical_dosing"
    ULTRAFILTRATION = "P3_ultrafiltration"
    DECHLORINATION = "P4_dechlorination"
    REVERSE_OSMOSIS = "P5_reverse_osmosis"


@dataclass(frozen=True)
class Point:
    tag: str            # SWaT-style tag, e.g. "LIT101"
    address: int        # Modbus holding-register address (0-based)
    kind: Kind
    stage: Stage
    unit: str           # engineering unit, e.g. "mm", "pH", "m3/h"
    scale: int          # physical -> register multiplier
    lo: float           # safe operating lower bound (physical units)
    hi: float           # safe operating upper bound (physical units)
    description: str = ""
    # For actuators: the legal discrete states (e.g. valve/pump 0=OFF,1=ON,2=TRANS)
    discrete_states: tuple[int, ...] | None = None

    def to_register(self, physical: float) -> int:
        return max(0, min(0xFFFF, round(physical * self.scale)))

    def to_physical(self, raw: int) -> float:
        return raw / self.scale


# ---------------------------------------------------------------------------
# Point definitions. Addresses are grouped by stage in blocks of 10.
# ---------------------------------------------------------------------------
POINTS: list[Point] = [
    # --- P1 raw water intake -------------------------------------------------
    Point("LIT101", 0, Kind.SENSOR, Stage.INTAKE, "mm", 1, 250, 1100,
          "Raw water tank level"),
    Point("FIT101", 1, Kind.SENSOR, Stage.INTAKE, "m3/h", 100, 0.0, 3.0,
          "Raw water inflow rate"),
    Point("MV101", 5, Kind.ACTUATOR, Stage.INTAKE, "state", 1, 0, 2,
          "Motorised inlet valve", discrete_states=(0, 1, 2)),
    Point("P101", 6, Kind.ACTUATOR, Stage.INTAKE, "state", 1, 0, 1,
          "Raw water transfer pump", discrete_states=(0, 1)),

    # --- P2 chemical dosing --------------------------------------------------
    Point("AIT201", 10, Kind.SENSOR, Stage.DOSING, "uS/cm", 10, 100, 300,
          "Conductivity after dosing"),
    Point("AIT202", 11, Kind.SENSOR, Stage.DOSING, "pH", 100, 6.5, 8.5,
          "pH after chemical dosing"),
    Point("FIT201", 12, Kind.SENSOR, Stage.DOSING, "m3/h", 100, 0.0, 3.0,
          "Dosing stage flow"),
    Point("P201", 15, Kind.ACTUATOR, Stage.DOSING, "state", 1, 0, 1,
          "NaOCl dosing pump", discrete_states=(0, 1)),
    Point("P203", 16, Kind.ACTUATOR, Stage.DOSING, "state", 1, 0, 1,
          "HCl dosing pump", discrete_states=(0, 1)),

    # --- P3 ultrafiltration --------------------------------------------------
    Point("DPIT301", 20, Kind.SENSOR, Stage.ULTRAFILTRATION, "kPa", 10, 0.0, 40.0,
          "UF differential pressure"),
    Point("LIT301", 21, Kind.SENSOR, Stage.ULTRAFILTRATION, "mm", 1, 250, 1100,
          "UF feed tank level"),
    Point("FIT301", 22, Kind.SENSOR, Stage.ULTRAFILTRATION, "m3/h", 100, 0.0, 3.0,
          "UF permeate flow"),
    Point("MV301", 25, Kind.ACTUATOR, Stage.ULTRAFILTRATION, "state", 1, 0, 2,
          "UF backwash valve", discrete_states=(0, 1, 2)),
    Point("P301", 26, Kind.ACTUATOR, Stage.ULTRAFILTRATION, "state", 1, 0, 1,
          "UF feed pump", discrete_states=(0, 1)),

    # --- P4 dechlorination (UV) ---------------------------------------------
    Point("AIT401", 30, Kind.SENSOR, Stage.DECHLORINATION, "ppm", 100, 0.0, 1.0,
          "Residual chlorine"),
    Point("LIT401", 31, Kind.SENSOR, Stage.DECHLORINATION, "mm", 1, 250, 1100,
          "RO feed tank level"),
    Point("P401", 35, Kind.ACTUATOR, Stage.DECHLORINATION, "state", 1, 0, 1,
          "UV dechlorinator / feed pump", discrete_states=(0, 1)),

    # --- P5 reverse osmosis --------------------------------------------------
    Point("PIT501", 40, Kind.SENSOR, Stage.REVERSE_OSMOSIS, "kPa", 1, 0, 300,
          "RO feed pressure"),
    Point("FIT501", 41, Kind.SENSOR, Stage.REVERSE_OSMOSIS, "m3/h", 100, 0.0, 2.0,
          "RO permeate flow"),
    Point("AIT501", 42, Kind.SENSOR, Stage.REVERSE_OSMOSIS, "uS/cm", 10, 5, 100,
          "RO permeate conductivity"),
    Point("P501", 45, Kind.ACTUATOR, Stage.REVERSE_OSMOSIS, "state", 1, 0, 1,
          "RO high-pressure pump", discrete_states=(0, 1)),
    Point("MV501", 46, Kind.ACTUATOR, Stage.REVERSE_OSMOSIS, "state", 1, 0, 2,
          "RO permeate valve", discrete_states=(0, 1, 2)),
]

# Fast lookups -------------------------------------------------------------
BY_TAG: dict[str, Point] = {p.tag: p for p in POINTS}
BY_ADDRESS: dict[int, Point] = {p.address: p for p in POINTS}

SENSORS: list[Point] = [p for p in POINTS if p.kind is Kind.SENSOR]
ACTUATORS: list[Point] = [p for p in POINTS if p.kind is Kind.ACTUATOR]

# Highest address we must allocate in the Modbus datastore (+1 for count).
MAX_ADDRESS: int = max(p.address for p in POINTS)
REGISTER_COUNT: int = MAX_ADDRESS + 1


def get(tag: str) -> Point:
    return BY_TAG[tag]
