"""Execution trace schema for RFC 0003 §C4 (roadmap M1.2).

RFC 0003 §C4 defines a flat, JSON-serializable trace entry so every runtime
(Python enforcer, n8n webhook, LangGraph run, harness skill, MCP wrapper) can
emit comparable evidence::

    {
      "node_id": "...",
      "action_name": "github:issues:write",
      "action_type": "side_effect",
      "declared": true,
      "result": "allowed" | "pending_approval" | "violation",
      "hash_of_contract": "<sha256 hex>",
      "timestamp": "<ISO-8601>"
    }

The trace generalizes :class:`~scyvera.enforcer.AuditEntry`. Two additional
fields (``reason`` and ``contract_field_reference``) keep the conversion
lossless in both directions, so a ``TraceLog`` can be built from an enforcer
audit log and converted back without dropping evidence.

``declared`` is derived from the audit decision: the enforcer's default-deny
path emits a DENIED entry whose reason contains ``" is not declared in "``.
Every other entry (allowed, pending, or a guardrail/integrity denial) is
treated as declared, because declaration was either satisfied or not
re-evaluated by that decision. The derivation is pinned in
``tests/test_trace.py``.

Everything here is pure: no I/O, no printing, no wall clock. Serialization is
deterministic (sorted keys, compact separators, one canonical JSON object per
line), so identical logs produce byte-identical JSONL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any, Optional

from .enforcer import AuditEntry
from .exceptions import TraceError

__all__ = [
    "TRACE_RESULT_ALLOWED",
    "TRACE_RESULT_PENDING_APPROVAL",
    "TRACE_RESULT_VIOLATION",
    "TRACE_RESULTS",
    "TraceEntry",
    "TraceLog",
    "TraceError",
    "audit_from_trace",
    "trace_from_audit",
]

#: RFC 0003 §C4 literal result values.
TRACE_RESULT_ALLOWED: str = "allowed"
TRACE_RESULT_PENDING_APPROVAL: str = "pending_approval"
TRACE_RESULT_VIOLATION: str = "violation"
TRACE_RESULTS: frozenset[str] = frozenset(
    {TRACE_RESULT_ALLOWED, TRACE_RESULT_PENDING_APPROVAL, TRACE_RESULT_VIOLATION}
)

_RESULT_TO_DECISION: dict[str, str] = {
    TRACE_RESULT_ALLOWED: "ALLOWED",
    TRACE_RESULT_PENDING_APPROVAL: "PENDING",
    TRACE_RESULT_VIOLATION: "DENIED",
}
_DECISION_TO_RESULT: dict[str, str] = {
    decision: result for result, decision in _RESULT_TO_DECISION.items()
}

_TRACE_FIELDS: tuple[str, ...] = (
    "node_id",
    "action_name",
    "action_type",
    "declared",
    "result",
    "hash_of_contract",
    "timestamp",
    "reason",
    "contract_field_reference",
)

_UNDECLARED_MARKER = " is not declared in "


def _is_declared(entry: AuditEntry) -> bool:
    """Return whether ``entry`` represents an action declared in the contract.

    The enforcer's only signal for an undeclared action is its default-deny
    reason (``"Action 'x' is not declared in 'permissions'."``); the frozen
    ``AuditEntry`` carries no separate flag. Guardrail and integrity denials
    keep ``True`` because they occur for actions that already passed (or never
    reached) the declaration step.
    """
    return not (
        entry.decision == "DENIED" and _UNDECLARED_MARKER in entry.reason
    )


def _validate_timestamp(value: Any) -> str:
    """Return ``value`` when it is an ISO-8601 timestamp string, else fail."""
    if not isinstance(value, str) or not value:
        raise TraceError("trace field 'timestamp' must be a non-empty string")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise TraceError(
            f"trace field 'timestamp' is not ISO-8601: {value!r}"
        ) from exc
    return value


def _validate_hash(value: Any) -> str:
    """Return ``value`` when it is a 64-character hexadecimal SHA-256."""
    if not isinstance(value, str) or len(value) != 64:
        raise TraceError(
            "trace field 'hash_of_contract' must be a 64-character "
            "hexadecimal SHA-256 string"
        )
    try:
        int(value, 16)
    except ValueError as exc:
        raise TraceError(
            "trace field 'hash_of_contract' must be hexadecimal"
        ) from exc
    return value


def _validate_str(value: Any, field: str, *, allow_empty: bool = True) -> str:
    """Return ``value`` when it is a string, optionally non-empty."""
    if not isinstance(value, str):
        raise TraceError(f"trace field '{field}' must be a string")
    if not allow_empty and not value:
        raise TraceError(f"trace field '{field}' must be non-empty")
    return value


@dataclass(frozen=True)
class TraceEntry:
    """One RFC 0003 §C4 trace record.

    All fields are required; ``node_id`` is the only nullable one (file
    contracts have no declaration node id). The two extra fields beyond the
    RFC shape (``reason`` and ``contract_field_reference``) are copied from
    :class:`~scyvera.enforcer.AuditEntry` so the conversion is lossless.
    """

    node_id: Optional[str]
    action_name: str
    action_type: str
    declared: bool
    result: str
    hash_of_contract: str
    timestamp: str
    reason: str
    contract_field_reference: str

    def __post_init__(self) -> None:
        if self.node_id is not None:
            _validate_str(self.node_id, "node_id", allow_empty=False)
        _validate_str(self.action_name, "action_name", allow_empty=False)
        _validate_str(self.action_type, "action_type", allow_empty=False)
        if type(self.declared) is not bool:
            raise TraceError("trace field 'declared' must be a boolean")
        if not isinstance(self.result, str) or self.result not in TRACE_RESULTS:
            raise TraceError(
                "trace field 'result' must be one of "
                f"{sorted(TRACE_RESULTS)}, got {self.result!r}"
            )
        _validate_hash(self.hash_of_contract)
        _validate_timestamp(self.timestamp)
        _validate_str(self.reason, "reason")
        _validate_str(
            self.contract_field_reference, "contract_field_reference"
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the exact RFC field set as a JSON-serializable mapping."""
        return {field: getattr(self, field) for field in _TRACE_FIELDS}

    @classmethod
    def from_dict(cls, data: Any) -> "TraceEntry":
        """Build an entry from a mapping, rejecting every malformed shape.

        Raises:
            TraceError: On a non-mapping, missing or unknown fields, wrong
                types, an unknown ``result``, a bad digest, or a
                non-ISO-8601 timestamp.
        """
        if not isinstance(data, dict):
            raise TraceError(
                f"trace entry must be a JSON object, got {type(data).__name__}"
            )
        missing = [field for field in _TRACE_FIELDS if field not in data]
        if missing:
            raise TraceError(
                "trace entry is missing field(s): " + ", ".join(missing)
            )
        unknown = sorted(set(data) - set(_TRACE_FIELDS))
        if unknown:
            raise TraceError(
                "trace entry has unknown field(s): " + ", ".join(unknown)
            )
        return cls(
            node_id=data["node_id"],
            action_name=data["action_name"],
            action_type=data["action_type"],
            declared=data["declared"],
            result=data["result"],
            hash_of_contract=data["hash_of_contract"],
            timestamp=data["timestamp"],
            reason=data["reason"],
            contract_field_reference=data["contract_field_reference"],
        )


@dataclass(frozen=True)
class TraceLog:
    """Ordered, immutable collection of :class:`TraceEntry` values.

    An empty log is valid. JSONL output is canonical: one compact JSON object
    per entry, sorted keys, UTF-8, newline-terminated. Timestamps are preserved
    verbatim; the eval harness normalizes them separately for reproducible
    artifacts.
    """

    entries: tuple[TraceEntry, ...] = ()

    def __post_init__(self) -> None:
        entries = tuple(self.entries)
        for entry in entries:
            if not isinstance(entry, TraceEntry):
                raise TraceError(
                    "trace log entries must be TraceEntry values, got "
                    f"{type(entry).__name__}"
                )
        object.__setattr__(self, "entries", entries)

    def to_jsonl(self) -> str:
        """Serialize to canonical JSONL (empty log -> empty string)."""
        return "".join(
            json.dumps(
                entry.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            + "\n"
            for entry in self.entries
        )

    @classmethod
    def from_jsonl(cls, text: str) -> "TraceLog":
        """Parse JSONL, reporting the 1-based line number on any failure."""
        if not isinstance(text, str):
            raise TraceError(
                f"trace JSONL must be a string, got {type(text).__name__}"
            )
        entries: list[TraceEntry] = []
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                raise TraceError(f"trace JSONL line {number}: empty line")
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TraceError(
                    f"trace JSONL line {number}: invalid JSON "
                    f"({exc.msg} at column {exc.colno})"
                ) from exc
            try:
                entries.append(TraceEntry.from_dict(payload))
            except TraceError as exc:
                raise TraceError(f"trace JSONL line {number}: {exc}") from exc
        return cls(entries=tuple(entries))


def trace_from_audit(
    entry: AuditEntry,
    *,
    node_id: Optional[str],
    contract_hash: str,
) -> TraceEntry:
    """Convert one enforcer audit entry into a trace entry.

    Args:
        entry: The frozen audit record emitted by ``ContractEnforcer``.
        node_id: Contract/declaration node id, or ``None`` for file contracts.
        contract_hash: SHA-256 of the governing contract.

    Returns:
        A frozen :class:`TraceEntry`. ``declared`` is derived from the
        audit reason (see :func:`_is_declared`).

    Raises:
        TraceError: If ``entry`` is not an ``AuditEntry`` or carries a
            decision outside ALLOWED/PENDING/DENIED.
    """
    if not isinstance(entry, AuditEntry):
        raise TraceError(
            f"trace_from_audit expects AuditEntry, got {type(entry).__name__}"
        )
    try:
        result = _DECISION_TO_RESULT[entry.decision]
    except KeyError as exc:
        raise TraceError(
            f"unknown audit decision {entry.decision!r}; expected one of "
            f"{sorted(_DECISION_TO_RESULT)}"
        ) from exc
    return TraceEntry(
        node_id=node_id,
        action_name=entry.action_name,
        action_type=entry.action_type,
        declared=_is_declared(entry),
        result=result,
        hash_of_contract=contract_hash,
        timestamp=entry.timestamp,
        reason=entry.reason,
        contract_field_reference=entry.contract_field_reference,
    )


def audit_from_trace(trace: TraceEntry) -> AuditEntry:
    """Convert a trace entry back into an enforcer audit entry.

    ``node_id`` and ``hash_of_contract`` are trace-only and intentionally
    dropped; every other field round-trips exactly.

    Raises:
        TraceError: If ``trace`` is not a :class:`TraceEntry` or its result is
            outside the RFC literal set.
    """
    if not isinstance(trace, TraceEntry):
        raise TraceError(
            f"audit_from_trace expects TraceEntry, got {type(trace).__name__}"
        )
    try:
        decision = _RESULT_TO_DECISION[trace.result]
    except KeyError as exc:
        raise TraceError(
            f"unknown trace result {trace.result!r}; expected one of "
            f"{sorted(TRACE_RESULTS)}"
        ) from exc
    return AuditEntry(
        timestamp=trace.timestamp,
        action_name=trace.action_name,
        action_type=trace.action_type,
        decision=decision,
        reason=trace.reason,
        contract_field_reference=trace.contract_field_reference,
    )
