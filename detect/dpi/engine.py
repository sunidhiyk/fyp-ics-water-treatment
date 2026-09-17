"""
Protocol-aware deep-packet-inspection rule engine (Phase 4).

This is the interpretable, low-latency detection layer, modelled on PA-NIDS. It
inspects each decoded Modbus transaction and applies a small set of
protocol-semantic rules. Unlike a statistical detector, every alert names exactly
what happened: which device was targeted, what action was requested, what value
was injected, and who sent it - the information an operator needs to respond.

Rules
-----
R1  unauthorized_writer  - a WRITE from a source not in the authorised-writer
    policy. Catches command injection and any spoofing write from a rogue host.
R2  sensor_write         - a WRITE targeting a SENSOR register. Sensors are plant
    outputs; nothing should ever write them over Modbus. Catches sensor spoofing
    / false-data-injection.
R3  out_of_band_setpoint - a WRITE to an actuator/set-point with a value outside
    its safe band or not a legal discrete state. Defence-in-depth: catches a bad
    set-point even from an otherwise-authorised source.

By design the engine does NOT flag reads (so a request flood looks like ordinary
reads - that is the NetFlow monitor's job) and does NOT flag a valid-looking
command from an authorised source (a compromised-HMI stealth manipulation - that
is the LSTM's job). Those deliberate blind spots are exactly why the system needs
all three layers.
"""
from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator

from sim.register_map import BY_ADDRESS, Kind
from net.config import AUTHORIZED_WRITERS
from net.transaction import Transaction, WRITE_FUNCS
from detect.alert import Alert


def _mk(t: Transaction, rule: str, severity: str, intent: str, message: str) -> Alert:
    return Alert(
        ts=t.ts, layer="dpi", rule=rule, severity=severity, message=message,
        tag=t.tag, src_ip=t.src_ip, dst_ip=t.dst_ip, intent=intent,
        evidence={"func": t.func_name, "register": t.register,
                  "value_raw": t.value_raw, "value_phys": t.value_phys},
        true_label=t.label,
    )


def inspect(t: Transaction) -> Alert | None:
    """Apply the DPI rules to one transaction; return an Alert or None.

    Rules are checked in priority order and the first match wins, so each flagged
    transaction yields a single, most-relevant alert.
    """
    if t.func_code not in WRITE_FUNCS:
        return None  # reads are not inspected by the protocol-semantic rules

    point = BY_ADDRESS.get(t.register)
    tag = point.tag if point else f"reg{t.register}"
    desc = point.description if point else "unknown register"
    val = t.value_phys if t.value_phys is not None else t.value_raw
    unit = point.unit if point else ""

    # R2 - write to a sensor register (spoofing). Checked before R1 so the alert
    # names the more specific intent when both apply.
    if point is not None and point.kind is Kind.SENSOR:
        authorised = t.src_ip in AUTHORIZED_WRITERS
        extra = "" if authorised else f" from unauthorised source {t.src_ip}"
        return _mk(t, "sensor_write", "high", "sensor spoofing / false data injection",
                   f"Sensor register {tag} ({desc}) was WRITTEN{extra} with "
                   f"value {val} {unit} - sensors must never be written; likely "
                   f"false-data-injection to mask the true process value.")

    # R1 - write from an unauthorised source.
    if t.src_ip not in AUTHORIZED_WRITERS:
        return _mk(t, "unauthorized_writer", "high", "unauthorised command injection",
                   f"Unauthorised source {t.src_ip} issued a WRITE to {tag} "
                   f"({desc}) = {val} {unit}, targeting {t.dst_ip}. No such source "
                   f"is permitted to command actuators - likely command injection.")

    # R3 - authorised source, but the commanded value is illegal / out of band.
    if point is not None:
        legal = point.discrete_states
        if legal is not None and int(round(val)) not in legal:
            return _mk(t, "out_of_band_setpoint", "medium", "invalid actuator state",
                       f"Actuator {tag} ({desc}) commanded to illegal state "
                       f"{int(round(val))} (allowed: {list(legal)}).")
        if not (point.lo <= val <= point.hi):
            return _mk(t, "out_of_band_setpoint", "medium", "set-point manipulation",
                       f"Set-point {tag} ({desc}) commanded to {val} {unit}, "
                       f"outside safe band [{point.lo:g}..{point.hi:g}].")
    return None


def run(transactions: Iterable[Transaction]) -> Iterator[Alert]:
    """Stream alerts for a sequence of transactions."""
    for t in transactions:
        alert = inspect(t)
        if alert is not None:
            yield alert


# ---------------------------------------------------------------------------
# CSV loading (network_log.csv -> Transaction stream)
# ---------------------------------------------------------------------------
def load_network_log(path: str) -> Iterator[Transaction]:
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            yield Transaction(
                ts=float(row["ts"]), src_ip=row["src_ip"],
                src_port=int(row["src_port"]), dst_ip=row["dst_ip"],
                dst_port=int(row["dst_port"]), unit_id=int(row["unit_id"]),
                func_code=int(row["func_code"]), register=int(row["register"]),
                value_raw=int(row["value_raw"]), count=int(row["count"]),
                label=row["label"], tick=int(row.get("tick", -1)),
            )
