"""Eval-case ingestion for the RFC 0003 §C4 harness (roadmap M2.4).

An eval case is a YAML fixture::

    version: 1
    name: refund-agent
    contract: contract.yaml
    agent: agent_eval_fixture:make_agent
    scenario:
      - action: github:issues:read
        action_type: read
      - action: db:write
        action_type: side_effect
        approve: true
    expected_trace:
      decisions: [ALLOWED, ALLOWED]
    score_weights:
      constraints: 0.25
      approval: 0.25
      recovery: 0.25
      replay: 0.25

Paths are resolved relative to the eval file's directory and may not escape
it. The agent reference is ``<module>:<factory>`` where the module is either a
single-file module next to the eval file (``agent_eval_fixture`` ->
``agent_eval_fixture.py``) or an importable dotted module.

Validation is fail-closed: every structural problem raises
:class:`EvalCaseError` with an actionable message. Nothing is coerced.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

__all__ = [
    "EVAL_AXES",
    "EvalAxes",
    "EvalCase",
    "EvalCaseError",
    "EvalStep",
    "load_eval_case",
]

#: The four RFC 0003 §C4 scoring axes, in canonical order.
EVAL_AXES: tuple[str, ...] = ("constraints", "approval", "recovery", "replay")

_ALLOWED_ACTION_TYPES = frozenset({"side_effect", "permission", "read"})
_ALLOWED_DECISIONS = frozenset({"ALLOWED", "PENDING", "DENIED"})
_CASE_KEYS = frozenset(
    {
        "version",
        "name",
        "contract",
        "agent",
        "scenario",
        "expected_trace",
        "score_weights",
    }
)
_STEP_KEYS = frozenset({"action", "action_type", "approve"})
_WEIGHT_TOLERANCE = 1e-9


class EvalCaseError(ValueError):
    """Raised when an eval case cannot be loaded or is structurally invalid."""


@dataclass(frozen=True)
class EvalStep:
    """One ordered scenario step: a gated action and optional approval."""

    action: str
    action_type: str
    approve: bool = False


@dataclass(frozen=True)
class EvalAxes:
    """Normalized 0..1 scores for the four RFC 0003 §C4 axes."""

    constraints: float
    approval: float
    recovery: float
    replay: float

    def as_dict(self) -> dict[str, float]:
        """Return the axes in canonical order."""
        return {
            "constraints": self.constraints,
            "approval": self.approval,
            "recovery": self.recovery,
            "replay": self.replay,
        }


@dataclass(frozen=True)
class EvalCase:
    """A validated, immutable eval case.

    ``base_dir`` and ``source_path`` are loader metadata (not YAML fields) used
    to resolve the contract and the agent module.
    """

    version: int
    name: str
    contract_path: Path
    agent_module: str
    agent_factory: str
    scenario: tuple[EvalStep, ...]
    expected_decisions: tuple[str, ...]
    score_weights: Mapping[str, float]
    base_dir: Path
    source_path: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "scenario", tuple(self.scenario))
        object.__setattr__(
            self, "expected_decisions", tuple(self.expected_decisions)
        )
        object.__setattr__(
            self, "score_weights", MappingProxyType(dict(self.score_weights))
        )


def _reject_unknown(data: Mapping[str, Any], allowed: frozenset[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise EvalCaseError(
            f"{where} has unknown key(s): {', '.join(unknown)}"
        )


def _require_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise EvalCaseError(
            f"{where} must be a mapping, got {type(value).__name__}"
        )
    return value


def _require_non_empty_str(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvalCaseError(f"{where} must be a non-empty string")
    return value


def _parse_scenario(raw: Any) -> tuple[EvalStep, ...]:
    if not isinstance(raw, list) or not raw:
        raise EvalCaseError("scenario must be a non-empty list of steps")
    steps: list[EvalStep] = []
    for index, item in enumerate(raw):
        where = f"scenario[{index}]"
        step = _require_mapping(item, where)
        _reject_unknown(step, _STEP_KEYS, where)
        for required in ("action", "action_type"):
            if required not in step:
                raise EvalCaseError(f"{where} is missing '{required}'")
        action = _require_non_empty_str(step["action"], f"{where}.action")
        action_type = step["action_type"]
        if action_type not in _ALLOWED_ACTION_TYPES:
            raise EvalCaseError(
                f"{where}.action_type must be one of "
                f"{sorted(_ALLOWED_ACTION_TYPES)}, got {action_type!r}"
            )
        approve = step.get("approve", False)
        if type(approve) is not bool:
            raise EvalCaseError(
                f"{where}.approve must be a boolean, got "
                f"{type(approve).__name__}"
            )
        steps.append(
            EvalStep(action=action, action_type=action_type, approve=approve)
        )
    return tuple(steps)


def _parse_expected_trace(
    raw: Any, *, step_count: int
) -> tuple[str, ...]:
    expected = _require_mapping(raw, "expected_trace")
    _reject_unknown(expected, frozenset({"decisions"}), "expected_trace")
    if "decisions" not in expected:
        raise EvalCaseError("expected_trace is missing 'decisions'")
    decisions = expected["decisions"]
    if not isinstance(decisions, list):
        raise EvalCaseError("expected_trace.decisions must be a list")
    if len(decisions) != step_count:
        raise EvalCaseError(
            "expected_trace.decisions must have one decision per scenario "
            f"step ({step_count}), got {len(decisions)}"
        )
    for index, decision in enumerate(decisions):
        if decision not in _ALLOWED_DECISIONS:
            raise EvalCaseError(
                f"expected_trace.decisions[{index}] must be one of "
                f"{sorted(_ALLOWED_DECISIONS)}, got {decision!r}"
            )
    return tuple(decisions)


def _parse_weights(raw: Any) -> Mapping[str, float]:
    weights = _require_mapping(raw, "score_weights")
    _reject_unknown(weights, frozenset(EVAL_AXES), "score_weights")
    missing = [axis for axis in EVAL_AXES if axis not in weights]
    if missing:
        raise EvalCaseError(
            "score_weights is missing axis/axes: " + ", ".join(missing)
        )
    parsed: dict[str, float] = {}
    for axis in EVAL_AXES:
        value = weights[axis]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EvalCaseError(
                f"score_weights.{axis} must be a number, got "
                f"{type(value).__name__}"
            )
        number = float(value)
        if not math.isfinite(number):
            raise EvalCaseError(
                f"score_weights.{axis} must be finite, got {value!r}"
            )
        if number < 0:
            raise EvalCaseError(
                f"score_weights.{axis} must be non-negative, got {value!r}"
            )
        parsed[axis] = number
    total = sum(parsed.values())
    if abs(total - 1.0) > _WEIGHT_TOLERANCE:
        raise EvalCaseError(
            f"score_weights must sum to 1.0 (tolerance {_WEIGHT_TOLERANCE}), "
            f"got {total!r}"
        )
    return parsed


def _parse_agent(raw: Any) -> tuple[str, str]:
    reference = _require_non_empty_str(raw, "agent")
    module, separator, factory = reference.partition(":")
    if not separator or not module or not factory or ":" in factory:
        raise EvalCaseError(
            "agent must be '<module>:<factory>' (for example "
            "'agent_eval_fixture:make_agent')"
        )
    return module, factory


def _resolve_contract(raw: Any, base_dir: Path) -> Path:
    value = _require_non_empty_str(raw, "contract")
    candidate = Path(value)
    if candidate.is_absolute():
        raise EvalCaseError(
            "contract must be a path relative to the eval file's directory"
        )
    resolved = (base_dir / candidate).resolve()
    try:
        resolved.relative_to(base_dir.resolve())
    except ValueError as exc:
        raise EvalCaseError(
            "contract path escapes the eval file's directory: "
            f"{value!r}"
        ) from exc
    if resolved.suffix != ".yaml":
        raise EvalCaseError(
            "contract must use the canonical .yaml extension: "
            f"{value!r}"
        )
    if not resolved.is_file():
        raise EvalCaseError(f"contract file not found: '{resolved}'")
    return resolved


def load_eval_case(path: str | Path) -> EvalCase:
    """Load and validate one eval-case YAML file.

    Args:
        path: Path to a ``*.eval.yaml`` fixture.

    Returns:
        A validated, frozen :class:`EvalCase`.

    Raises:
        EvalCaseError: On unreadable/invalid YAML, missing or unknown keys,
            bad weights, unknown action types, unsupported versions, an
            escaping/missing contract, a malformed agent reference, or an
            empty scenario.
    """
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvalCaseError(f"cannot read eval case '{source}': {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise EvalCaseError(f"invalid YAML in '{source}': {exc}") from exc

    data = _require_mapping(raw, "eval case")
    _reject_unknown(data, _CASE_KEYS, "eval case")
    missing = [key for key in sorted(_CASE_KEYS) if key not in data]
    if missing:
        raise EvalCaseError(
            "eval case is missing key(s): " + ", ".join(missing)
        )

    version = data["version"]
    if type(version) is not int or version != 1:
        raise EvalCaseError(
            f"version must be the integer 1, got {version!r}"
        )

    name = _require_non_empty_str(data["name"], "name")
    base_dir = source.resolve().parent
    contract_path = _resolve_contract(data["contract"], base_dir)
    agent_module, agent_factory = _parse_agent(data["agent"])
    scenario = _parse_scenario(data["scenario"])
    expected = _parse_expected_trace(
        data["expected_trace"], step_count=len(scenario)
    )
    weights = _parse_weights(data["score_weights"])

    # Validate the agent reference eagerly so a typo is a case error rather
    # than a mid-run failure. Local import avoids the case <-> agent cycle.
    from .agent import load_factory

    load_factory(agent_module, agent_factory, base_dir)

    return EvalCase(
        version=version,
        name=name,
        contract_path=contract_path,
        agent_module=agent_module,
        agent_factory=agent_factory,
        scenario=scenario,
        expected_decisions=expected,
        score_weights=weights,
        base_dir=base_dir,
        source_path=source.resolve(),
    )
