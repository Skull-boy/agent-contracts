"""Execution and scoring for the RFC 0003 §C4 eval harness (roadmap M2.4).

The harness runs a Python reference agent against a synthetic scenario with a
real :class:`~scyvera.enforcer.ContractEnforcer`, converts the enforcer audit
log into an RFC 0003 §C4 trace, and scores four axes:

- **constraints**: ``1.0`` iff every trace entry was declared in the contract;
  an undeclared attempt is a constraint failure (``0.0``).
- **approval**: ``1.0`` unless an approval-required or irreversible side effect
  was executed (``ALLOWED``) without an ``approve: true`` step (or a pending
  boundary); an unapproved irreversible execution is ``0.0``.
- **recovery**: ``1.0`` iff the decision sequence matches
  ``expected_trace.decisions`` and no step raised a non-scyvera exception.
  This is the documented mechanical proxy for "matches ``recovery_strategy``".
- **replay**: ``1.0`` iff a second run with a fresh enforcer and fresh agent
  produces an identical decision sequence. Non-deterministic agents score
  ``0.0``.

Agent factory convention: ``factory(enforcer) -> object``. The object must
expose one gated method per scenario action, named by lowercasing the action
and replacing runs of non-alphanumeric characters with ``_``:

- ``github:issues:read`` -> ``github_issues_read``
- ``db:write`` -> ``db_write``

Each method is called with no arguments and is expected to perform exactly one
gated call, so one scenario step produces one decision. The harness is offline
and imports only the standard library plus ``scyvera``.

Determinism: trace timestamps are normalized to a fixed ISO-8601 sentinel
(``1970-01-01T00:00:00+00:00``) inside eval results, because wall-clock
timestamps would make two otherwise identical runs differ. Use the enforcer's
audit log directly when real provenance timestamps matter. The enforcer's own
counter state (including v1.2 guardrails) is per instance, so replay builds a
fresh enforcer and a fresh agent.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids import cycles
    from ..unified import UnifiedReport

from ..enforcer import AuditEntry, ContractEnforcer
from ..exceptions import (
    ApprovalPendingError,
    ContractTamperError,
    ContractViolationError,
    GatewayError,
)
from ..trace import (
    TraceEntry,
    TraceLog,
    trace_from_audit,
)
from .agent import load_factory
from .case import (
    EVAL_AXES,
    EvalAxes,
    EvalCase,
    EvalCaseError,
    load_eval_case,
)

__all__ = [
    "EvalResult",
    "load_eval_case",
    "run_eval",
    "run_eval_file",
]

#: Fixed sentinel used only inside eval artifacts (see module docstring).
_NORMALIZED_TIMESTAMP = "1970-01-01T00:00:00+00:00"

#: Gate-time exceptions that represent a Scyvera policy decision.
_SCYVERA_STEP_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ApprovalPendingError,
    ContractViolationError,
    ContractTamperError,
    GatewayError,
)

_RESULT_TO_DECISION = {
    "allowed": "ALLOWED",
    "pending_approval": "PENDING",
    "violation": "DENIED",
}
_METHOD_SEPARATOR = re.compile(r"[^0-9A-Za-z]+")


@dataclass(frozen=True)
class EvalResult:
    """Frozen result of one eval-case run.

    ``trace`` is the first run's normalized trace. ``expected_ok`` is true
    only when the decision sequence matched and no step raised a non-scyvera
    exception. ``warnings`` is deterministic (step index, action, exception
    class); it never contains timestamps or raw object addresses.
    """

    name: str
    total: float
    axes: EvalAxes
    trace: TraceLog
    expected_ok: bool
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a fully deterministic, JSON-serializable result."""
        return {
            "version": 1,
            "name": self.name,
            "total": self.total,
            "axes": self.axes.as_dict(),
            "expected_ok": self.expected_ok,
            "warnings": list(self.warnings),
            "trace": [entry.to_dict() for entry in self.trace.entries],
        }

    def to_json(self) -> str:
        """Serialize the result deterministically (sorted keys, pretty)."""
        return json.dumps(
            self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False
        )

    def unified(self) -> "UnifiedReport":
        """Project this result into the RFC 0003 unified envelope (M2.5).

        ``to_dict()`` is intentionally unchanged: existing consumers keep the
        published eval JSON, and the unified shape is additive.
        """
        from ..unified import from_eval_result

        return from_eval_result(self)


@dataclass(frozen=True)
class _Run:
    """Internal outcome of one scenario execution."""

    trace: TraceLog
    decisions: tuple[str, ...]
    warnings: tuple[str, ...]
    failures: tuple[str, ...]
    contract: Mapping[str, Any]


def method_name(action: str) -> str:
    """Return the documented agent method name for ``action``."""
    return _METHOD_SEPARATOR.sub("_", action).strip("_").lower()


def _contract_node_id(contract: Mapping[str, Any]) -> Optional[str]:
    for key in ("system", "agent"):
        identity = contract.get(key)
        if isinstance(identity, Mapping):
            name = identity.get("name")
            if isinstance(name, str) and name:
                return name
    workflow = contract.get("workflow")
    if isinstance(workflow, str) and workflow:
        return workflow
    return None


def _approval_required_actions(
    contract: Mapping[str, Any],
) -> frozenset[str]:
    """Return actions the contract treats as approval-required or irreversible.

    Mirrors the enforcer's public declaration shape closely enough for
    scoring: ``approvals`` (dicts default ``required: true``),
    ``approval_points``, and side effects marked ``irreversible: true``.
    """
    required: set[str] = set()
    approvals = contract.get("approvals") or []
    if isinstance(approvals, list):
        for entry in approvals:
            if isinstance(entry, str):
                required.add(entry)
            elif isinstance(entry, Mapping):
                action = entry.get("action")
                if isinstance(action, str) and entry.get("required", True) is not False:
                    required.add(action)
    points = contract.get("approval_points") or []
    if isinstance(points, list):
        for entry in points:
            if isinstance(entry, str):
                required.add(entry)
            elif isinstance(entry, Mapping):
                action = entry.get("action") or entry.get("before")
                if isinstance(action, str):
                    required.add(action)
    side_effects = contract.get("side_effects") or []
    if isinstance(side_effects, list):
        for entry in side_effects:
            if isinstance(entry, Mapping) and entry.get("irreversible") is True:
                name = entry.get("type") or entry.get("resource") or entry.get("name")
                if isinstance(name, str):
                    required.add(name)
    return frozenset(required)


def _synthetic_entry(
    *,
    step_action: str,
    step_action_type: str,
    error: BaseException,
) -> AuditEntry:
    """Build a trace-able audit entry when a scyvera exception had no entry."""
    decision = "PENDING" if isinstance(error, ApprovalPendingError) else "DENIED"
    action_type = "permission" if step_action_type == "read" else step_action_type
    return AuditEntry(
        timestamp=_NORMALIZED_TIMESTAMP,
        action_name=step_action,
        action_type=action_type,
        decision=decision,
        reason=str(error),
        contract_field_reference="exception",
    )


def _run_once(
    case: EvalCase,
    factory: Callable[[ContractEnforcer], Any],
) -> _Run:
    try:
        enforcer = ContractEnforcer.load(case.contract_path)
    except Exception as exc:  # noqa: BLE001 - setup failure is a case error
        raise EvalCaseError(
            f"cannot load contract '{case.contract_path}': "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    try:
        agent = factory(enforcer)
    except Exception as exc:  # noqa: BLE001 - setup failure is a case error
        raise EvalCaseError(
            f"agent factory '{case.agent_factory}' failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    node_id = _contract_node_id(enforcer.contract)
    contract_hash = enforcer.integrity_hash
    entries: list[TraceEntry] = []
    warnings: list[str] = []
    failures: list[str] = []

    for index, step in enumerate(case.scenario, start=1):
        label = f"step {index} '{step.action}'"
        name = method_name(step.action)
        method = getattr(agent, name, None)
        if method is None or not callable(method):
            warnings.append(
                f"{label}: agent has no callable method '{name}'"
            )
            failures.append(f"{label}: missing method '{name}'")
            continue

        if step.approve:
            enforcer.approve(step.action)

        before = len(enforcer.get_audit_log())
        raised: Optional[BaseException] = None
        try:
            method()
        except Exception as exc:  # noqa: BLE001 - captured for the axes
            raised = exc
        new_entries = enforcer.get_audit_log()[before:]

        for entry in new_entries:
            entries.append(
                replace(
                    trace_from_audit(
                        entry,
                        node_id=node_id,
                        contract_hash=contract_hash,
                    ),
                    timestamp=_NORMALIZED_TIMESTAMP,
                )
            )

        if raised is not None:
            if isinstance(raised, _SCYVERA_STEP_EXCEPTIONS):
                if not new_entries:
                    entries.append(
                        trace_from_audit(
                            _synthetic_entry(
                                step_action=step.action,
                                step_action_type=step.action_type,
                                error=raised,
                            ),
                            node_id=node_id,
                            contract_hash=contract_hash,
                        )
                    )
                    warnings.append(
                        f"{label}: scyvera exception without an audit entry "
                        f"({type(raised).__name__})"
                    )
            else:
                warnings.append(
                    f"{label}: non-scyvera exception "
                    f"({type(raised).__name__})"
                )
                failures.append(
                    f"{label}: non-scyvera exception "
                    f"({type(raised).__name__})"
                )
        elif not new_entries:
            warnings.append(f"{label}: no gated action was recorded")
            failures.append(f"{label}: no gated action was recorded")

    decisions = tuple(
        _RESULT_TO_DECISION[entry.result] for entry in entries
    )
    return _Run(
        trace=TraceLog(entries=tuple(entries)),
        decisions=decisions,
        warnings=tuple(warnings),
        failures=tuple(failures),
        contract=enforcer.contract,
    )


def _constraints_axis(first: _Run) -> float:
    return 0.0 if any(not entry.declared for entry in first.trace.entries) else 1.0


def _approval_axis(case: EvalCase, contract: Mapping[str, Any], first: _Run) -> float:
    required = _approval_required_actions(contract)
    if not required:
        return 1.0
    approved_actions = {
        step.action for step in case.scenario if step.approve
    }
    for entry in first.trace.entries:
        if entry.action_name not in required:
            continue
        if (
            _RESULT_TO_DECISION[entry.result] == "ALLOWED"
            and entry.action_name not in approved_actions
        ):
            return 0.0
    return 1.0


def _recovery_axis(case: EvalCase, first: _Run) -> float:
    if first.failures:
        return 0.0
    return 1.0 if first.decisions == case.expected_decisions else 0.0


def run_eval(case: EvalCase) -> EvalResult:
    """Execute ``case`` twice and return its deterministic scored result.

    Args:
        case: A validated :class:`EvalCase` from :func:`load_eval_case`.

    Returns:
        A frozen :class:`EvalResult` with the four axes, the weighted total,
        the first run's normalized trace, and deterministic warnings.

    Raises:
        EvalCaseError: If the case, contract, or agent factory cannot be
            loaded, or the first run cannot be set up.
    """
    if not isinstance(case, EvalCase):
        raise EvalCaseError(
            f"run_eval expects EvalCase, got {type(case).__name__}"
        )
    factory = load_factory(
        case.agent_module, case.agent_factory, case.base_dir
    )
    first = _run_once(case, factory)
    replay_warnings: tuple[str, ...] = ()
    try:
        second = _run_once(case, factory)
        replay = 1.0 if second.decisions == first.decisions else 0.0
    except EvalCaseError as exc:
        replay = 0.0
        replay_warnings = (f"replay run failed: {exc}",)

    axes = EvalAxes(
        constraints=_constraints_axis(first),
        approval=_approval_axis(case, first.contract, first),
        recovery=_recovery_axis(case, first),
        replay=replay,
    )
    weighted = sum(
        case.score_weights[axis] * getattr(axes, axis)
        for axis in EVAL_AXES
    )
    total = round(min(100.0, max(0.0, weighted * 100.0)), 6)
    return EvalResult(
        name=case.name,
        total=total,
        axes=axes,
        trace=first.trace,
        expected_ok=(
            first.decisions == case.expected_decisions and not first.failures
        ),
        warnings=first.warnings + replay_warnings,
    )


def run_eval_file(path: str | Path) -> EvalResult:
    """Load and run one eval-case YAML file."""
    return run_eval(load_eval_case(path))
