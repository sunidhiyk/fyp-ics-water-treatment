"""Phase-6 test: the hash-chain ledger detects every kind of tampering."""
from __future__ import annotations

import copy

from ledger.hashchain import HashChainLedger


def _ledger(tmp_path, n=5):
    led = HashChainLedger(path=str(tmp_path / "l.jsonl"),
                          key_path=str(tmp_path / "k.pem"))
    for i in range(n):
        led.append({"type": "alert", "ts": float(i), "msg": f"event {i}"})
    return led


def test_intact_chain_verifies(tmp_path):
    led = _ledger(tmp_path)
    r = led.verify()
    assert r.ok and r.length == 5 and r.broken_index is None


def test_edited_payload_is_detected(tmp_path):
    led = _ledger(tmp_path)
    led._entries[2]["payload"]["msg"] = "forged"
    r = led.verify()
    assert not r.ok and r.broken_index == 2


def test_deleted_entry_breaks_chain(tmp_path):
    led = _ledger(tmp_path)
    del led._entries[3]                     # removing an entry breaks linkage
    r = led.verify()
    assert not r.ok


def test_reordered_entries_detected(tmp_path):
    led = _ledger(tmp_path)
    led._entries[1], led._entries[2] = led._entries[2], led._entries[1]
    assert not led.verify().ok


def test_persistence_roundtrip(tmp_path):
    led = _ledger(tmp_path)
    reloaded = HashChainLedger(path=str(tmp_path / "l.jsonl"),
                               key_path=str(tmp_path / "k.pem"))
    assert len(reloaded) == 5
    assert reloaded.verify().ok


def test_forged_entry_without_key_fails_signature(tmp_path):
    # Recompute hashes to fake the chain, but sign with a different key -> caught.
    led = _ledger(tmp_path)
    other = HashChainLedger(key_path=str(tmp_path / "other.pem"))
    e = led._entries[2]
    e["payload"]["msg"] = "forged"
    # recompute payload + entry hash so the hash checks would pass...
    from ledger.hashchain import _sha256, _canonical
    e["payload_hash"] = _sha256(_canonical(e["payload"]))
    e["entry_hash"] = led._hash_entry(e["index"], e["prev_hash"],
                                      e["payload_hash"], e["ts"])
    # ...but sign with the wrong key
    e["signature"] = other._priv.sign(bytes.fromhex(e["entry_hash"])).hex()
    r = led.verify()
    # linkage to entry 3 now also breaks; either way it must be flagged
    assert not r.ok
