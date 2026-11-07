"""Tests for the RFC 0003 §C4 trace schema (roadmap M1.2).

The trace generalizes ``AuditEntry`` without losing evidence: every entry the
enforcer can emit round-trips through ``trace_from_audit`` /
``audit_from_trace``. Parsing is fail-closed (missing/unknown fields, wrong
types, unknown results, bad timestamps, malformed JSONL lines), and JSONL is
canonical and deterministic.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from scyvera import (
    AuditEntry,
    TraceEntry,
    TraceError,
    TraceLog,
    audit_from_trace,
    trace_from_audit,
)


TIMESTAMP = "2026-01-01T12:00:00+00:00"
HASH_A = "a" * 64
HASH_B = "b" * 64


def _audit(
    decision: str = "ALLOWED",
    *,
    action_name: str = "db:write",
    action_type: str = "side_effect",
    reason: str = "Action matched the contract.",
    field: str = "side_effects",
) -> AuditEntry:
    return AuditEntry(
        timestamp=TIMESTAMP,
        action_name=action_name,
        action_type=action_type,
        decision=decision,
        reason=reason,
        contract_field_reference=field,
    )


def _trace(**overrides: object) -> TraceEntry:
    values: dict[str, object] = {
        "node_id": "agent-v1",
        "action_name": "db:write",
        "action_type": "side_effect",
        "declared": True,
        "result": "allowed",
        "hash_of_contract": HASH_A,
        "timestamp": TIMESTAMP,
        "reason": "Action matched the contract.",
        "contract_field_reference": "side_effects",
    }
    values.update(overrides)
    return TraceEntry(**values)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Lossless AuditEntry round-trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("decision", "result"),
    [
        ("ALLOWED", "allowed"),
        ("PENDING", "pending_approval"),
        ("DENIED", "violation"),
    ],
)
def test_audit_round_trip_for_all_decisions(decision: str, result: str) -> None:
    audit = _audit(decision)

    trace = trace_from_audit(audit, node_id="agent-v1", contract_hash=HASH_A)

    assert trace.node_id == "agent-v1"
    assert trace.result == result
    assert trace.hash_of_contract == HASH_A
    assert trace.timestamp == audit.timestamp
    assert trace.reason == audit.reason
    assert trace.contract_field_reference == audit.contract_field_reference
    assert audit_from_trace(trace) == audit


def test_undeclared_denial_sets_declared_false() -> None:
    audit = _audit(
        "DENIED",
        action_name="admin:delete",
        action_type="permission",
        reason="Action 'admin:delete' is not declared in 'permissions'.",
        field="permissions",
    )

    trace = trace_from_audit(audit, node_id=None, contract_hash=HASH_B)

    assert trace.declared is False
    assert trace.result == "violation"
    assert audit_from_trace(trace) == audit


def test_guardrail_denial_stays_declared() -> None:
    audit = _audit(
        "DENIED",
        reason=(
            "Guardrail 'budgets' denied action 'db:write': "
            "side_effects_per_window=2 reached within window '1h'."
        ),
        field="guardrails.budgets",
    )

    trace = trace_from_audit(audit, node_id=None, contract_hash=HASH_B)

    assert trace.declared is True
    assert trace.result == "violation"
    assert audit_from_trace(trace) == audit


def test_trace_from_audit_rejects_non_audit_entry() -> None:
    with pytest.raises(TraceError):
        trace_from_audit({"decision": "ALLOWED"}, node_id=None, contract_hash=HASH_A)  # type: ignore[arg-type]


def test_trace_from_audit_rejects_unknown_decision() -> None:
    audit = _audit("MAYBE")
    with pytest.raises(TraceError):
        trace_from_audit(audit, node_id=None, contract_hash=HASH_A)


def test_audit_from_trace_rejects_unknown_result() -> None:
    trace = _trace()
    object.__setattr__(trace, "result", "maybe")
    with pytest.raises(TraceError):
        audit_from_trace(trace)


def test_audit_from_trace_rejects_non_trace_entry() -> None:
    with pytest.raises(TraceError):
        audit_from_trace("not-a-trace")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# to_dict / from_dict
# ---------------------------------------------------------------------------


def test_to_dict_has_the_exact_field_set() -> None:
    payload = _trace().to_dict()
    assert set(payload) == {
        "node_id",
        "action_name",
        "action_type",
        "declared",
        "result",
        "hash_of_contract",
        "timestamp",
        "reason",
        "contract_field_reference",
    }


def test_from_dict_round_trips() -> None:
    trace = _trace()
    assert TraceEntry.from_dict(trace.to_dict()) == trace


@pytest.mark.parametrize("missing", sorted(_trace().to_dict()))
def test_from_dict_rejects_missing_field(missing: str) -> None:
    payload = _trace().to_dict()
    del payload[missing]
    with pytest.raises(TraceError, match="missing field"):
        TraceEntry.from_dict(payload)


def test_from_dict_rejects_unknown_field() -> None:
    payload = _trace().to_dict()
    payload["extra"] = "nope"
    with pytest.raises(TraceError, match="unknown field"):
        TraceEntry.from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("node_id", 7),
        ("action_name", None),
        ("action_type", []),
        ("declared", "yes"),
        ("declared", 1),
        ("result", "maybe"),
        ("hash_of_contract", "abc"),
        ("hash_of_contract", "z" * 64),
        ("timestamp", "not-a-timestamp"),
        ("timestamp", None),
        ("reason", 5),
        ("contract_field_reference", None),
    ],
)
def test_from_dict_rejects_wrong_types_and_values(
    field: str, value: object
) -> None:
    payload = _trace().to_dict()
    payload[field] = value
    with pytest.raises(TraceError):
        TraceEntry.from_dict(payload)


def test_from_dict_accepts_null_node_id() -> None:
    payload = _trace(node_id=None).to_dict()
    assert TraceEntry.from_dict(payload).node_id is None


def test_from_dict_rejects_non_mapping() -> None:
    with pytest.raises(TraceError, match="JSON object"):
        TraceEntry.from_dict(["not", "an", "object"])


def test_from_dict_accepts_trailing_z_timestamp() -> None:
    payload = _trace(timestamp="2026-01-01T12:00:00Z").to_dict()
    assert TraceEntry.from_dict(payload).timestamp == "2026-01-01T12:00:00Z"


def test_trace_entry_is_frozen() -> None:
    trace = _trace()
    with pytest.raises(dataclasses.FrozenInstanceError):
        trace.result = "violation"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TraceLog JSONL
# ---------------------------------------------------------------------------


def test_empty_trace_log_is_valid() -> None:
    log = TraceLog()
    assert log.entries == ()
    assert log.to_jsonl() == ""
    assert TraceLog.from_jsonl("") == log


def test_trace_log_jsonl_is_canonical_and_deterministic() -> None:
    first = trace_from_audit(_audit("ALLOWED"), node_id="a-v1", contract_hash=HASH_A)
    second = trace_from_audit(
        _audit("PENDING", reason="Approval required.", field="approvals"),
        node_id="a-v1",
        contract_hash=HASH_A,
    )
    log = TraceLog(entries=(first, second))

    output = log.to_jsonl()
    assert output == log.to_jsonl()
    lines = output.splitlines()
    assert len(lines) == 2
    for line in lines:
        payload = json.loads(line)
        assert line == json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
    assert output.endswith("\n")


def test_trace_log_round_trips() -> None:
    log = TraceLog(
        entries=(
            trace_from_audit(_audit("ALLOWED"), node_id=None, contract_hash=HASH_A),
            trace_from_audit(
                _audit(
                    "DENIED",
                    action_name="admin:delete",
                    action_type="permission",
                    reason="Action 'admin:delete' is not declared in 'permissions'.",
                    field="permissions",
                ),
                node_id=None,
                contract_hash=HASH_B,
            ),
        )
    )
    assert TraceLog.from_jsonl(log.to_jsonl()) == log


def test_from_jsonl_reports_the_bad_line_number() -> None:
    good = json.dumps(
        trace_from_audit(
            _audit("ALLOWED"), node_id=None, contract_hash=HASH_A
        ).to_dict(),
        sort_keys=True,
        separators=(",", ":"),
    )
    text = good + "\n" + "{not json\n"

    with pytest.raises(TraceError, match="line 2"):
        TraceLog.from_jsonl(text)


def test_from_jsonl_reports_structural_errors_with_line_number() -> None:
    payload = _trace().to_dict()
    del payload["result"]
    text = json.dumps(payload)

    with pytest.raises(TraceError, match="line 1"):
        TraceLog.from_jsonl(text)


def test_from_jsonl_rejects_blank_lines() -> None:
    with pytest.raises(TraceError, match="line 1"):
        TraceLog.from_jsonl("\n")


def test_trace_log_rejects_non_entry_values() -> None:
    with pytest.raises(TraceError):
        TraceLog(entries=("not-an-entry",))  # type: ignore[arg-type]


def test_trace_log_is_frozen() -> None:
    log = TraceLog()
    with pytest.raises(dataclasses.FrozenInstanceError):
        log.entries = ()  # type: ignore[misc]
