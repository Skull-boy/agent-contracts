"""Hash-chain mechanics for the contract registry (RFC 0003 §C1, roadmap M1.1).

RFC 0003 §C1 extends every appended ``RegistryEntry`` with a ``prev_hash``
field: the SHA-256 of the immediately preceding serialized entry, or
:data:`GENESIS_HASH` for the first entry. The chain is recomputable from the
registry file alone, and verification must fail closed on any break, splice,
reorder, or fabricated insertion — this is the T13 mitigation.

This module is pure mechanics: no I/O, no printing, no mutable global state.
It is the single source of truth for the byte serialization that is both
persisted and hashed, so stored bytes and hashed bytes can never diverge.

Historical caveat (also documented on ``ContractRegistry.upgrade_chain``):
backfilling a pre-chain registry proves integrity from the upgrade moment
forward. Tampering that happened before the snapshot sidecar was taken is
outside C1's guarantee; the sidecar and warning exist to make that boundary
explicit.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import TYPE_CHECKING, Sequence

from .exceptions import RegistryError

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for type checkers only
    from .registry import RegistryEntry

__all__ = [
    "ChainInterval",
    "GENESIS_HASH",
    "canonical_entry_bytes",
    "compute_chain_intervals",
    "next_prev_hash",
    "verify_chain_entries",
]

#: RFC 0003 §C1 verbatim: the fixed prev_hash of the first registry entry.
GENESIS_HASH: str = "0" * 64


def canonical_entry_bytes(entry: RegistryEntry) -> bytes:
    """Return the exact UTF-8 bytes persisted for ``entry`` (no newline).

    ``_append_to_file`` writes these bytes and ``verify_chain`` hashes these
    same bytes, so the on-disk record and the hashed record are identical by
    construction. Field order comes from the dataclass, keeping the encoding
    deterministic across processes and Python versions.
    """
    return json.dumps(asdict(entry), separators=(",", ":")).encode("utf-8")


def next_prev_hash(previous: RegistryEntry) -> str:
    """Return the ``prev_hash`` the entry after ``previous`` must carry."""
    return hashlib.sha256(canonical_entry_bytes(previous)).hexdigest()


@dataclass(frozen=True)
class ChainInterval:
    """One expected link in a registry chain.

    ``index`` is the zero-based position of the entry whose ``prev_hash`` is
    being checked. ``expected_prev_hash`` is what the chain requires
    (genesis for the first entry, otherwise the SHA-256 of the previous
    canonical entry). ``actual_prev_hash`` is the stored value; ``None`` means
    a pre-chain entry.
    """

    index: int
    expected_prev_hash: str
    actual_prev_hash: str | None

    @property
    def valid(self) -> bool:
        """Whether this link matches the chain requirement."""
        return self.actual_prev_hash == self.expected_prev_hash


def compute_chain_intervals(
    entries: Sequence[RegistryEntry],
) -> tuple[ChainInterval, ...]:
    """Return the expected-vs-stored link for every entry, in order."""
    intervals: list[ChainInterval] = []
    for index, entry in enumerate(entries):
        expected = (
            GENESIS_HASH
            if index == 0
            else next_prev_hash(entries[index - 1])
        )
        intervals.append(
            ChainInterval(
                index=index,
                expected_prev_hash=expected,
                actual_prev_hash=entry.prev_hash,
            )
        )
    return tuple(intervals)


def verify_chain_entries(entries: Sequence[RegistryEntry]) -> bool:
    """Verify a sequence of entries, raising ``RegistryError`` on any break.

    Fail-closed by design: a missing ``prev_hash`` (pre-chain or spliced
    line), a reordered line, an edited line, and a fabricated insertion at a
    non-genesis position all raise. An empty sequence is trivially valid and
    returns ``True``; callers decide whether "empty" is meaningful.
    """
    for interval in compute_chain_intervals(entries):
        if interval.valid:
            continue
        if interval.actual_prev_hash is None:
            reason = (
                f"entry {interval.index + 1} has no prev_hash; registry is "
                "pre-chain or mixed-format — call upgrade_chain() explicitly"
            )
        else:
            reason = (
                f"chain break at entry {interval.index + 1}: expected "
                f"prev_hash {interval.expected_prev_hash}, found "
                f"{interval.actual_prev_hash}"
            )
        raise RegistryError("verify_chain", reason)
    return True
