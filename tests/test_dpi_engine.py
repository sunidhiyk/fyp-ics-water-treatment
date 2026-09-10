"""
Phase-4 test: the DPI rule engine flags the right transactions and, crucially,
leaves the right ones alone (no false positives on legitimate traffic, and the
deliberate blind spots for flooding/stealth).
"""
from __future__ import annotations

from net.transaction import Transaction
from net.config import HMI, ATTACKER, LABEL_NORMAL
from sim.register_map import BY_TAG
from detect.dpi.engine import inspect


def _txn(src_ip, register, value_raw, func_code=6, label=LABEL_NORMAL):
    return Transaction(ts=0.0, src_ip=src_ip, src_port=1, dst_ip="10.0.0.2",
                       dst_port=502, unit_id=1, func_code=func_code,
                       register=register, value_raw=value_raw, count=1, label=label)


def test_flags_unauthorized_actuator_write():
    # attacker writes the transfer pump OFF -> command injection
    a = inspect(_txn(ATTACKER.ip, BY_TAG["P101"].address, 0))
    assert a is not None and a.rule == "unauthorized_writer" and a.severity == "high"
    assert "P101" == a.tag


def test_flags_sensor_write_as_spoofing():
    # anyone writing a sensor register -> false data injection
    a = inspect(_txn(ATTACKER.ip, BY_TAG["LIT101"].address, 1180))
    assert a is not None and a.rule == "sensor_write"
    assert "false-data-injection" in a.message


def test_flags_out_of_band_setpoint_from_authorized_source():
    # authorised HMI, but commands an illegal actuator state (P101 accepts 0/1)
    a = inspect(_txn(HMI.ip, BY_TAG["P101"].address, 5))
    assert a is not None and a.rule == "out_of_band_setpoint"


def test_legitimate_hmi_actuator_write_is_clean():
    # HMI turns a pump ON with a valid value -> no alert
    assert inspect(_txn(HMI.ip, BY_TAG["P101"].address, 1)) is None


def test_reads_are_never_flagged():
    # a flood of reads (even from the attacker) is not the DPI layer's job
    assert inspect(_txn(ATTACKER.ip, BY_TAG["LIT101"].address, 0, func_code=3)) is None


def test_compromised_hmi_valid_command_is_a_blind_spot():
    # stealth: authorised source, valid actuator, in-range value -> DPI must NOT flag
    assert inspect(_txn(HMI.ip, BY_TAG["P203"].address, 1)) is None
