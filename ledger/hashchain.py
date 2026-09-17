"""
Signed hash-chain ledger — a tamper-evident audit trail.

Each entry links to the previous one by hash (like a blockchain) and is signed
with an Ed25519 key:

    entry_hash = SHA256( index | prev_hash | payload_hash | timestamp )
    signature  = Ed25519_sign( entry_hash )

Two independent protections:
  * the hash chain — altering any entry changes its hash, which breaks every
    subsequent link, so a single edit is detectable and localisable;
  * the signature — an attacker who recomputes the whole chain to hide an edit
    still cannot forge the signatures without the private key.

``verify()`` walks the chain, recomputing hashes and checking signatures, and
reports the first broken entry. This delivers the tamper-evidence property the
proposal assigns to blockchain logging; the same interface (LedgerBackend) can be
re-backed by Hyperledger Fabric later without changing callers.
"""
from __future__ import annotations

import hashlib
import json
import os

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey)

from .backend import LedgerBackend, VerifyResult

GENESIS_PREV = "0" * 64


def _canonical(payload: dict) -> str:
    # deterministic serialisation so the hash is stable across runs/machines
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _sha256(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
    return h.hexdigest()


class HashChainLedger(LedgerBackend):
    def __init__(self, path: str | None = None, key_path: str | None = None) -> None:
        self.path = path
        self._entries: list[dict] = []
        self._priv = self._load_or_make_key(key_path)
        self._pub: Ed25519PublicKey = self._priv.public_key()
        if path and os.path.exists(path):
            self._load()

    # -- key management ----------------------------------------------------
    def _load_or_make_key(self, key_path: str | None) -> Ed25519PrivateKey:
        if key_path and os.path.exists(key_path):
            with open(key_path, "rb") as fh:
                return serialization.load_pem_private_key(fh.read(), password=None)
        key = Ed25519PrivateKey.generate()
        if key_path:
            os.makedirs(os.path.dirname(key_path) or ".", exist_ok=True)
            with open(key_path, "wb") as fh:
                fh.write(key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption()))
        return key

    def public_key_hex(self) -> str:
        return self._pub.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()

    # -- persistence -------------------------------------------------------
    def _load(self) -> None:
        with open(self.path, encoding="utf-8") as fh:
            self._entries = [json.loads(line) for line in fh if line.strip()]

    def _persist(self, entry: dict) -> None:
        if self.path:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")

    # -- core --------------------------------------------------------------
    def _hash_entry(self, index: int, prev_hash: str, payload_hash: str,
                    ts: float) -> str:
        return _sha256(str(index), prev_hash, payload_hash, repr(ts))

    def append(self, record: dict) -> dict:
        index = len(self._entries)
        prev_hash = self._entries[-1]["entry_hash"] if self._entries else GENESIS_PREV
        ts = float(record.get("ts", 0.0))
        payload_hash = _sha256(_canonical(record))
        entry_hash = self._hash_entry(index, prev_hash, payload_hash, ts)
        signature = self._priv.sign(bytes.fromhex(entry_hash)).hex()
        entry = {
            "index": index, "ts": ts, "prev_hash": prev_hash,
            "payload": record, "payload_hash": payload_hash,
            "entry_hash": entry_hash, "signature": signature,
        }
        self._entries.append(entry)
        self._persist(entry)
        return entry

    def entries(self) -> list[dict]:
        return list(self._entries)

    def verify(self) -> VerifyResult:
        prev = GENESIS_PREV
        for i, e in enumerate(self._entries):
            # 1. index + linkage
            if e["index"] != i:
                return VerifyResult(False, len(self._entries), i, "index mismatch")
            if e["prev_hash"] != prev:
                return VerifyResult(False, len(self._entries), i,
                                    "previous-hash link broken")
            # 2. payload integrity
            if _sha256(_canonical(e["payload"])) != e["payload_hash"]:
                return VerifyResult(False, len(self._entries), i,
                                    "payload altered (hash mismatch)")
            # 3. entry hash integrity
            recomputed = self._hash_entry(e["index"], e["prev_hash"],
                                          e["payload_hash"], e["ts"])
            if recomputed != e["entry_hash"]:
                return VerifyResult(False, len(self._entries), i,
                                    "entry hash mismatch")
            # 4. signature
            try:
                self._pub.verify(bytes.fromhex(e["signature"]),
                                 bytes.fromhex(e["entry_hash"]))
            except InvalidSignature:
                return VerifyResult(False, len(self._entries), i,
                                    "invalid signature")
            prev = e["entry_hash"]
        return VerifyResult(True, len(self._entries))
