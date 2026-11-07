"""Tests for the RFC 0003 §C4 trace-driven eval harness (roadmap M2.4).

Coverage:

- the shipped golden fixture scores exactly 75.0 with pinned per-axis values
  and is byte-identical across two runs;
- malformed eval cases are rejected with :class:`EvalCaseError` (missing and
  unknown keys, bad weights, unknown action types, path escape, unimportable
  factory, empty scenario, bad versions/decisions);
- each axis can fail independently, and the weighted total follows the
  documented formula;
- the harness trace round-trips through canonical JSONL.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import yaml

from scyvera import TraceLog
from scyvera.evals import (
    EvalAxes,
    EvalCaseError,
    load_eval_case,
    run_eval,
    run_eval_file,
)


ROOT = Path(__file__).resolve().parent.parent
GOLDEN = (
    ROOT
    / "implementations"
    / "langgraph"
    / "duplicate-issue-detector"
    / "evals"
    / "refund-agent.eval.yaml"
)

_AGENT_SOURCE = '''\
from scyvera import ContractEnforcer


class FixtureAgent:
    def __init__(self, enforcer: ContractEnforcer) -> None:
        self.github_issues_read = enforcer.gate(
            "github:issues:read", "read"
        )(self._read)
        self.db_write = enforcer.gate(
            "db:write", "side_effect"
        )(self._write)
        self.payments_transfer = enforcer.gate(
            "payments:transfer", "side_effect"
        )(self._transfer)
        self.admin_delete = enforcer.gate(
            "admin:delete", "permission"
        )(self._delete)

    def _read(self) -> str:
        return "read"

    def _write(self) -> str:
        return "write"

    def _transfer(self) -> str:
        return "transfer"

    def _delete(self) -> str:
        return "delete"


def make_agent(enforcer: ContractEnforcer) -> FixtureAgent:
    return FixtureAgent(enforcer)
'''

_BASE_CONTRACT = """\
version: 1.1
system:
  name: eval-fixture
permissions:
  - github:issues:read
side_effects:
  - db:write
approvals:
  - action: db:write
    required: true
"""

_EQUAL_WEIGHTS = {
    "constraints": 0.25,
    "approval": 0.25,
    "recovery": 0.25,
    "replay": 0.25,
}


def _base_payload() -> dict:
    return {
        "version": 1,
        "name": "fixture",
        "contract": "contract.yaml",
        "agent": "agent_fixture:make_agent",
        "scenario": [
            {"action": "github:issues:read", "action_type": "read"},
            {
                "action": "db:write",
                "action_type": "side_effect",
                "approve": True,
            },
        ],
        "expected_trace": {"decisions": ["ALLOWED", "ALLOWED"]},
        "score_weights": dict(_EQUAL_WEIGHTS),
    }


def _write_assets(tmp_path: Path, agent_source: str = _AGENT_SOURCE) -> None:
    (tmp_path / "contract.yaml").write_text(_BASE_CONTRACT, encoding="utf-8")
    (tmp_path / "agent_fixture.py").write_text(agent_source, encoding="utf-8")


def _write_case(
    tmp_path: Path,
    *,
    contract: str = _BASE_CONTRACT,
    scenario: list[dict] | None = None,
    decisions: list[str] | None = None,
    weights: dict | None = None,
    agent_source: str = _AGENT_SOURCE,
    payload: dict | None = None,
) -> Path:
    (tmp_path / "contract.yaml").write_text(contract, encoding="utf-8")
    (tmp_path / "agent_fixture.py").write_text(agent_source, encoding="utf-8")
    data = _base_payload() if payload is None else payload
    if scenario is not None:
        data["scenario"] = scenario
    if decisions is not None:
        data["expected_trace"] = {"decisions": decisions}
    if weights is not None:
        data["score_weights"] = weights
    path = tmp_path / "case.eval.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _malformed(tmp_path: Path, mutate) -> Path:
    _write_assets(tmp_path)
    payload = _base_payload()
    mutate(payload)
    path = tmp_path / "case.eval.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Golden fixture
# ---------------------------------------------------------------------------


def test_golden_fixture_scores_exactly_75() -> None:
    result = run_eval_file(GOLDEN)

    assert result.total == 75.0
    assert result.axes == EvalAxes(
        constraints=0.0,
        approval=1.0,
        recovery=1.0,
        replay=1.0,
    )
    assert result.expected_ok is True
    assert result.warnings == ()
    assert [
        (entry.action_name, entry.result, entry.declared)
        for entry in result.trace.entries
    ] == [
        ("github:issues:read", "allowed", True),
        ("db:write", "pending_approval", True),
        ("db:write", "allowed", True),
        ("admin:delete", "violation", False),
    ]


def test_golden_fixture_is_byte_identical_across_runs() -> None:
    first = run_eval_file(GOLDEN)
    second = run_eval_file(GOLDEN)

    assert first.to_dict() == second.to_dict()
    assert first.to_json() == second.to_json()
    assert first.total == second.total
    assert first.axes == second.axes
    assert first.warnings == second.warnings


def test_golden_fixture_trace_round_trips_through_jsonl() -> None:
    result = run_eval_file(GOLDEN)
    assert TraceLog.from_jsonl(result.trace.to_jsonl()) == result.trace


def test_eval_result_is_frozen() -> None:
    result = run_eval_file(GOLDEN)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.total = 0.0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.axes.constraints = 1.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Malformed eval cases
# ---------------------------------------------------------------------------


def test_rejects_missing_key(tmp_path: Path) -> None:
    path = _malformed(tmp_path, lambda payload: payload.pop("name"))
    with pytest.raises(EvalCaseError, match="missing"):
        load_eval_case(path)


def test_rejects_unknown_key(tmp_path: Path) -> None:
    def mutate(payload: dict) -> None:
        payload["extra"] = True

    with pytest.raises(EvalCaseError, match="unknown key"):
        load_eval_case(_malformed(tmp_path, mutate))


def test_rejects_negative_weight(tmp_path: Path) -> None:
    def mutate(payload: dict) -> None:
        payload["score_weights"]["constraints"] = -0.1
        payload["score_weights"]["approval"] = 0.35

    with pytest.raises(EvalCaseError, match="non-negative"):
        load_eval_case(_malformed(tmp_path, mutate))


def test_rejects_weights_not_summing_to_one(tmp_path: Path) -> None:
    def mutate(payload: dict) -> None:
        payload["score_weights"]["constraints"] = 0.5

    with pytest.raises(EvalCaseError, match="sum to 1.0"):
        load_eval_case(_malformed(tmp_path, mutate))


def test_rejects_unknown_action_type(tmp_path: Path) -> None:
    def mutate(payload: dict) -> None:
        payload["scenario"][0]["action_type"] = "write"

    with pytest.raises(EvalCaseError, match="action_type"):
        load_eval_case(_malformed(tmp_path, mutate))


def test_rejects_contract_path_escape(tmp_path: Path) -> None:
    def mutate(payload: dict) -> None:
        payload["contract"] = "../outside.yaml"

    with pytest.raises(EvalCaseError, match="escapes"):
        load_eval_case(_malformed(tmp_path, mutate))


def test_rejects_unimportable_agent_factory(tmp_path: Path) -> None:
    def mutate(payload: dict) -> None:
        payload["agent"] = "definitely_not_a_module_xyz:make_agent"

    with pytest.raises(EvalCaseError, match="cannot import agent module"):
        load_eval_case(_malformed(tmp_path, mutate))


def test_rejects_missing_agent_factory_attribute(tmp_path: Path) -> None:
    def mutate(payload: dict) -> None:
        payload["agent"] = "agent_fixture:not_a_factory"

    with pytest.raises(EvalCaseError, match="not found"):
        load_eval_case(_malformed(tmp_path, mutate))


def test_rejects_empty_scenario(tmp_path: Path) -> None:
    def mutate(payload: dict) -> None:
        payload["scenario"] = []
        payload["expected_trace"] = {"decisions": []}

    with pytest.raises(EvalCaseError, match="non-empty"):
        load_eval_case(_malformed(tmp_path, mutate))


def test_rejects_unsupported_version(tmp_path: Path) -> None:
    def mutate(payload: dict) -> None:
        payload["version"] = 2

    with pytest.raises(EvalCaseError, match="version"):
        load_eval_case(_malformed(tmp_path, mutate))


def test_rejects_decision_count_mismatch(tmp_path: Path) -> None:
    def mutate(payload: dict) -> None:
        payload["expected_trace"] = {"decisions": ["ALLOWED"]}

    with pytest.raises(EvalCaseError, match="one decision per scenario step"):
        load_eval_case(_malformed(tmp_path, mutate))


def test_rejects_unknown_expected_decision(tmp_path: Path) -> None:
    def mutate(payload: dict) -> None:
        payload["expected_trace"] = {
            "decisions": ["ALLOWED", "MAYBE"]
        }

    with pytest.raises(EvalCaseError, match="decisions\\[1\\]"):
        load_eval_case(_malformed(tmp_path, mutate))


def test_rejects_unknown_weight_axis(tmp_path: Path) -> None:
    def mutate(payload: dict) -> None:
        payload["score_weights"]["speed"] = 0.0

    with pytest.raises(EvalCaseError, match="unknown key"):
        load_eval_case(_malformed(tmp_path, mutate))


def test_rejects_missing_weight_axis(tmp_path: Path) -> None:
    def mutate(payload: dict) -> None:
        del payload["score_weights"]["replay"]

    with pytest.raises(EvalCaseError, match="missing axis"):
        load_eval_case(_malformed(tmp_path, mutate))


def test_rejects_non_boolean_approve(tmp_path: Path) -> None:
    def mutate(payload: dict) -> None:
        payload["scenario"][0]["approve"] = "yes"

    with pytest.raises(EvalCaseError, match="approve"):
        load_eval_case(_malformed(tmp_path, mutate))


def test_rejects_unknown_step_key(tmp_path: Path) -> None:
    def mutate(payload: dict) -> None:
        payload["scenario"][0]["retry"] = True

    with pytest.raises(EvalCaseError, match="unknown key"):
        load_eval_case(_malformed(tmp_path, mutate))


def test_rejects_absolute_contract_path(tmp_path: Path) -> None:
    def mutate(payload: dict) -> None:
        payload["contract"] = str(tmp_path / "contract.yaml")

    with pytest.raises(EvalCaseError, match="relative"):
        load_eval_case(_malformed(tmp_path, mutate))


def test_rejects_missing_contract(tmp_path: Path) -> None:
    def mutate(payload: dict) -> None:
        payload["contract"] = "missing.yaml"

    with pytest.raises(EvalCaseError, match="not found"):
        load_eval_case(_malformed(tmp_path, mutate))


def test_rejects_invalid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "case.eval.yaml"
    path.write_text("{not: valid: yaml", encoding="utf-8")
    with pytest.raises(EvalCaseError, match="invalid YAML"):
        load_eval_case(path)


# ---------------------------------------------------------------------------
# Per-axis failures and the weighted total
# ---------------------------------------------------------------------------


def test_constraints_only_failure_scores_zero_and_matches_formula(
    tmp_path: Path,
) -> None:
    path = _write_case(
        tmp_path,
        scenario=[
            {"action": "github:issues:read", "action_type": "read"},
            {"action": "admin:delete", "action_type": "permission"},
        ],
        decisions=["ALLOWED", "DENIED"],
        weights={
            "constraints": 0.7,
            "approval": 0.1,
            "recovery": 0.1,
            "replay": 0.1,
        },
    )
    result = run_eval(load_eval_case(path))

    assert result.axes.constraints == 0.0
    assert result.axes.approval == 1.0
    assert result.axes.recovery == 1.0
    assert result.axes.replay == 1.0
    assert result.total == 30.0
    assert result.total == round(
        100.0
        * (
            0.7 * result.axes.constraints
            + 0.1 * result.axes.approval
            + 0.1 * result.axes.recovery
            + 0.1 * result.axes.replay
        ),
        6,
    )


def test_approval_only_failure_scores_zero(tmp_path: Path) -> None:
    contract = """\
version: 1.1
system:
  name: approval-fixture
side_effects:
  - type: payments:transfer
    irreversible: true
"""
    path = _write_case(
        tmp_path,
        contract=contract,
        scenario=[
            {"action": "payments:transfer", "action_type": "side_effect"}
        ],
        decisions=["ALLOWED"],
    )
    result = run_eval(load_eval_case(path))

    assert result.axes.constraints == 1.0
    assert result.axes.approval == 0.0
    assert result.axes.recovery == 1.0
    assert result.axes.replay == 1.0
    assert result.total == 75.0


def test_replay_failure_scores_zero(tmp_path: Path) -> None:
    non_deterministic = '''\
_calls = 0


class FixtureAgent:
    def __init__(self, enforcer):
        self.db_write = enforcer.gate(
            "db:write", "side_effect"
        )(self._write)

    def _write(self):
        return "write"


def make_agent(enforcer):
    global _calls
    _calls += 1
    if _calls % 2 == 0:
        return object()
    return FixtureAgent(enforcer)
'''
    contract = """\
version: 1.1
system:
  name: replay-fixture
side_effects:
  - db:write
"""
    path = _write_case(
        tmp_path,
        contract=contract,
        scenario=[{"action": "db:write", "action_type": "side_effect"}],
        decisions=["ALLOWED"],
        agent_source=non_deterministic,
    )
    result = run_eval(load_eval_case(path))

    assert result.axes.constraints == 1.0
    assert result.axes.approval == 1.0
    assert result.axes.recovery == 1.0
    assert result.axes.replay == 0.0
    assert result.total == 75.0


def test_recovery_failure_scores_zero(tmp_path: Path) -> None:
    path = _write_case(
        tmp_path,
        scenario=[{"action": "db:write", "action_type": "side_effect"}],
        decisions=["ALLOWED"],  # actual is PENDING (approval required)
    )
    result = run_eval(load_eval_case(path))

    assert result.axes.constraints == 1.0
    assert result.axes.approval == 1.0
    assert result.axes.recovery == 0.0
    assert result.axes.replay == 1.0
    assert result.total == 75.0
    assert result.expected_ok is False


def test_valid_case_scores_100(tmp_path: Path) -> None:
    path = _write_case(tmp_path)
    result = run_eval(load_eval_case(path))

    assert result.axes == EvalAxes(1.0, 1.0, 1.0, 1.0)
    assert result.total == 100.0
    assert result.expected_ok is True
    assert result.warnings == ()
