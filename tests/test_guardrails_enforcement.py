"""Runtime enforcement tests for RFC 0003 §C5 guardrails (roadmap M2.6).

The guardrails object is enforced inside ``ContractEnforcer._check_gate`` —
the same layer every gateway method goes through — after the existing
integrity / declaration / approval steps:

- ``rate_limit.max_calls_per_minute`` counts every gated attempt (allowed,
  denied, and pending alike) in a sliding 60-second window;
- ``budgets.side_effects_per_window`` counts only admitted side-effect
  executions in the declared window;
- ``fail_closed`` decides whether guardrail-evaluation failures deny or permit.

Counters are per enforcer instance. Tests inject a clock so window expiry is
proven with zero sleeps.
"""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scyvera import (
    ApprovalPendingError,
    ContractEnforcer,
    ContractViolationError,
    DeclarationValidationError,
    GuardrailViolationError,
    Guardrails,
)


START = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    """Deterministic guardrail clock; advance() never sleeps."""

    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now = self.now + timedelta(**kwargs)


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "contract.yaml"
    path.write_text(body, encoding="utf-8")
    return path


_BASE = """version: 1.2
system:
  name: Guardrail Demo
permissions:
  - github:issues:read
side_effects:
  - db:write
"""

_BUDGET = """guardrails:
  budgets:
    side_effects_per_window: 2
    window: "1h"
"""

_RATE = """guardrails:
  rate_limit:
    max_calls_per_minute: 2
"""


def _load(tmp_path: Path, guardrails: str, clock: FakeClock) -> ContractEnforcer:
    return ContractEnforcer.load(
        _write(tmp_path, _BASE + guardrails),
        clock=clock,
    )


def _decisions(enforcer: ContractEnforcer) -> list[tuple[str, str, str]]:
    return [
        (entry.action_name, entry.decision, entry.contract_field_reference)
        for entry in enforcer.get_audit_log()
    ]


# ---------------------------------------------------------------------------
# Budgets: N allowed, N+1 denied, window expiry re-admits
# ---------------------------------------------------------------------------


def test_budget_allows_n_then_denies_n_plus_one(tmp_path: Path) -> None:
    clock = FakeClock()
    enforcer = _load(tmp_path, _BUDGET, clock)
    calls = []

    @enforcer.gate("db:write", "side_effect")
    def write() -> str:
        calls.append("write")
        return "ok"

    assert write() == "ok"
    assert write() == "ok"

    with pytest.raises(GuardrailViolationError) as excinfo:
        write()

    error = excinfo.value
    assert error.guardrail == "budgets"
    assert error.limit == 2
    assert error.window == "1h"
    assert error.action_name == "db:write"
    assert "side_effects_per_window=2" in str(error)
    assert calls == ["write", "write"]

    last = enforcer.get_audit_log()[-1]
    assert last.decision == "DENIED"
    assert last.contract_field_reference == "guardrails.budgets"


def test_budget_window_expiry_readmits(tmp_path: Path) -> None:
    clock = FakeClock()
    enforcer = _load(tmp_path, _BUDGET, clock)

    @enforcer.gate("db:write", "side_effect")
    def write() -> str:
        return "ok"

    assert write() == "ok"
    assert write() == "ok"
    with pytest.raises(GuardrailViolationError):
        write()

    clock.advance(hours=1, seconds=1)
    assert write() == "ok"
    assert enforcer.get_audit_log()[-1].decision == "ALLOWED"


def test_permission_calls_never_consume_side_effect_budget(tmp_path: Path) -> None:
    clock = FakeClock()
    enforcer = _load(
        tmp_path,
        """guardrails:
  budgets:
    side_effects_per_window: 1
    window: "1h"
""",
        clock,
    )

    @enforcer.gate("github:issues:read", "read")
    def read() -> str:
        return "read"

    @enforcer.gate("db:write", "side_effect")
    def write() -> str:
        return "write"

    for _ in range(5):
        assert read() == "read"

    assert write() == "write"
    with pytest.raises(GuardrailViolationError):
        write()


def test_pending_approval_never_consumes_budget(tmp_path: Path) -> None:
    clock = FakeClock()
    path = _write(
        tmp_path,
        """version: 1.2
system:
  name: Approval Demo
permissions:
  - github:issues:read
side_effects:
  - payments:transfer
approvals:
  - action: payments:transfer
    required: true
guardrails:
  budgets:
    side_effects_per_window: 1
    window: "1h"
""",
    )
    enforcer = ContractEnforcer.load(path, clock=clock)

    @enforcer.gate("payments:transfer", "side_effect")
    def transfer() -> str:
        return "sent"

    for _ in range(3):
        with pytest.raises(ApprovalPendingError):
            transfer()

    assert all(
        entry.decision == "PENDING"
        for entry in enforcer.get_audit_log()
        if entry.action_name == "payments:transfer"
    )

    enforcer.approve("payments:transfer")
    assert transfer() == "sent"
    with pytest.raises(GuardrailViolationError):
        transfer()


# ---------------------------------------------------------------------------
# Rate limit: every attempt counts; window expiry re-admits
# ---------------------------------------------------------------------------


def test_rate_limit_denies_the_attempt_after_the_maximum(tmp_path: Path) -> None:
    clock = FakeClock()
    enforcer = _load(tmp_path, _RATE, clock)

    @enforcer.gate("github:issues:read", "read")
    def read() -> str:
        return "ok"

    assert read() == "ok"
    assert read() == "ok"
    with pytest.raises(GuardrailViolationError) as excinfo:
        read()

    error = excinfo.value
    assert error.guardrail == "rate_limit"
    assert error.limit == 2
    assert error.window == "60s"
    assert "max_calls_per_minute=2" in str(error)
    assert enforcer.get_audit_log()[-1].contract_field_reference == (
        "guardrails.rate_limit"
    )


def test_rate_limit_counts_denied_attempts(tmp_path: Path) -> None:
    clock = FakeClock()
    enforcer = _load(tmp_path, _RATE, clock)

    @enforcer.gate("github:issues:read", "read")
    def read() -> str:
        return "ok"

    # Attempt 1 is denied as undeclared, but still consumes rate capacity.
    with pytest.raises(ContractViolationError):
        enforcer.gate("aws:s3:read", "read")(lambda: "nope")()

    assert read() == "ok"  # attempt 2
    with pytest.raises(GuardrailViolationError):  # attempt 3 > max 2
        read()


def test_rate_limit_counts_pending_attempts(tmp_path: Path) -> None:
    clock = FakeClock()
    enforcer = _load(
        tmp_path,
        """approvals:
  - action: db:write
    required: true
guardrails:
  rate_limit:
    max_calls_per_minute: 2
""",
        clock,
    )

    @enforcer.gate("db:write", "side_effect")
    def write() -> str:
        return "ok"

    with pytest.raises(ApprovalPendingError):
        write()
    with pytest.raises(ApprovalPendingError):
        write()

    enforcer.approve("db:write")
    with pytest.raises(GuardrailViolationError):  # attempt 3 > max 2
        write()

    clock.advance(seconds=61)
    assert write() == "ok"


def test_rate_limit_window_expiry_readmits(tmp_path: Path) -> None:
    clock = FakeClock()
    enforcer = _load(
        tmp_path,
        """guardrails:
  rate_limit:
    max_calls_per_minute: 1
""",
        clock,
    )

    @enforcer.gate("github:issues:read", "read")
    def read() -> str:
        return "ok"

    assert read() == "ok"
    with pytest.raises(GuardrailViolationError):
        read()

    clock.advance(seconds=60)
    with pytest.raises(GuardrailViolationError):
        read()  # exactly 60s old is still inside the inclusive boundary

    clock.advance(seconds=61)
    assert read() == "ok"


# ---------------------------------------------------------------------------
# fail_closed semantics
# ---------------------------------------------------------------------------


def _broken_clock() -> datetime:
    raise RuntimeError("clock unavailable")


def test_fail_closed_denies_when_guardrail_evaluation_raises(
    tmp_path: Path,
) -> None:
    enforcer = ContractEnforcer.load(
        _write(
            tmp_path,
            _BASE
            + """guardrails:
  fail_closed: true
  rate_limit:
    max_calls_per_minute: 10
""",
        ),
        clock=_broken_clock,
    )

    @enforcer.gate("github:issues:read", "read")
    def read() -> str:
        return "ok"

    with pytest.raises(GuardrailViolationError) as excinfo:
        read()

    error = excinfo.value
    assert error.guardrail == "fail_closed"
    assert "fail_closed is true" in str(error)
    last = enforcer.get_audit_log()[-1]
    assert last.decision == "DENIED"
    assert last.contract_field_reference == "guardrails.fail_closed"


def test_explicit_fail_open_permits_when_guardrail_evaluation_raises(
    tmp_path: Path,
) -> None:
    enforcer = ContractEnforcer.load(
        _write(
            tmp_path,
            _BASE
            + """guardrails:
  fail_closed: false
  rate_limit:
    max_calls_per_minute: 10
""",
        ),
        clock=_broken_clock,
    )

    @enforcer.gate("github:issues:read", "read")
    def read() -> str:
        return "ok"

    assert read() == "ok"
    assert enforcer.get_audit_log()[-1].decision == "ALLOWED"


# ---------------------------------------------------------------------------
# No guardrails / empty guardrails keep today's behavior exactly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("guardrail_block", ["", "guardrails: {}\n"])
def test_absent_or_empty_guardrails_do_not_change_decisions(
    tmp_path: Path, guardrail_block: str
) -> None:
    clock = FakeClock()
    enforcer = ContractEnforcer.load(
        _write(tmp_path, _BASE + guardrail_block),
        clock=clock,
    )
    assert enforcer.guardrails in (None, Guardrails())
    if guardrail_block == "":
        assert enforcer.guardrails is None

    @enforcer.gate("github:issues:read", "read")
    def read() -> str:
        return "ok"

    @enforcer.gate("db:write", "side_effect")
    def write() -> str:
        return "ok"

    assert read() == "ok"
    assert write() == "ok"
    with pytest.raises(ContractViolationError):
        enforcer.gate("ssh:exec", "read")(lambda: "nope")()

    assert _decisions(enforcer) == [
        ("github:issues:read", "ALLOWED", "permissions"),
        ("db:write", "ALLOWED", "side_effects"),
        ("ssh:exec", "DENIED", "permissions"),
    ]


def test_guardrails_record_is_frozen(tmp_path: Path) -> None:
    clock = FakeClock()
    enforcer = _load(tmp_path, _BUDGET, clock)
    assert enforcer.guardrails is not None
    with pytest.raises(FrozenInstanceError):
        enforcer.guardrails.fail_closed = True  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        enforcer.guardrails.budgets.side_effects_per_window = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Async gate path and declarations
# ---------------------------------------------------------------------------


def test_async_gate_enforces_rate_limit_identically(tmp_path: Path) -> None:
    clock = FakeClock()
    enforcer = _load(
        tmp_path,
        """guardrails:
  rate_limit:
    max_calls_per_minute: 1
""",
        clock,
    )

    @enforcer.gate("github:issues:read", "read")
    async def read() -> str:
        return "ok"

    async def scenario() -> tuple[str, str]:
        first = await read()
        with pytest.raises(GuardrailViolationError):
            await read()
        return first, enforcer.get_audit_log()[-1].contract_field_reference

    first, field_reference = asyncio.run(scenario())
    assert first == "ok"
    assert field_reference == "guardrails.rate_limit"


def test_declaration_guardrails_are_enforced(tmp_path: Path) -> None:
    clock = FakeClock()
    enforcer = ContractEnforcer.from_declaration(
        {
            "node_id": "guard-test-v1",
            "permissions": ["github:issues:read"],
            "side_effects": ["db:write"],
            "guardrails": {
                "budgets": {
                    "side_effects_per_window": 1,
                    "window": "1h",
                }
            },
        },
        clock=clock,
    )

    @enforcer.gate("db:write", "side_effect")
    def write() -> str:
        return "ok"

    assert write() == "ok"
    with pytest.raises(GuardrailViolationError):
        write()


def test_malformed_declaration_guardrails_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(DeclarationValidationError) as excinfo:
        ContractEnforcer.from_declaration(
            {
                "node_id": "guard-test-v1",
                "permissions": ["github:issues:read"],
                "guardrails": {
                    "budgets": {
                        "side_effects_per_window": 0,
                        "window": "1h",
                    }
                },
            }
        )
    assert excinfo.value.field == "guardrails"


def test_non_callable_clock_is_rejected(tmp_path: Path) -> None:
    contract = _write(tmp_path, _BASE)
    with pytest.raises(TypeError):
        ContractEnforcer.load(contract, clock=42)  # type: ignore[arg-type]


def test_guardrail_error_is_a_contract_violation() -> None:
    error = GuardrailViolationError(
        "budgets",
        "db:write",
        reason="limit reached",
        limit=2,
        window="1h",
    )
    assert isinstance(error, ContractViolationError)
    assert error.guardrail == "budgets"
    assert error.limit == 2
    assert error.window == "1h"
