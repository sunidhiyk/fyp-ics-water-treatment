"""
Ledger backend interface.

Every control command and every detection alert is appended to a tamper-evident
ledger so that, after an incident, an operator can trust the record has not been
altered. Keeping this behind an interface means the hash-chain implementation used
now can later be swapped for Hyperledger Fabric without touching the callers
(correlator, dashboard) — the blockchain becomes a drop-in backend.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class VerifyResult:
    ok: bool
    length: int
    broken_index: int | None = None   # first tampered/broken entry, if any
    reason: str = ""

    def __str__(self) -> str:
        if self.ok:
            return f"INTACT - {self.length} entries, chain + signatures verified"
        return (f"COMPROMISED - break at entry {self.broken_index}: {self.reason} "
                f"({self.length} entries total)")


class LedgerBackend(ABC):
    """Append-only, tamper-evident log of records."""

    @abstractmethod
    def append(self, record: dict) -> dict:
        """Append a record; return the created ledger entry."""

    @abstractmethod
    def entries(self) -> list[dict]:
        """Return all ledger entries in order."""

    @abstractmethod
    def verify(self) -> VerifyResult:
        """Check the whole ledger's integrity."""

    def __len__(self) -> int:
        return len(self.entries())
