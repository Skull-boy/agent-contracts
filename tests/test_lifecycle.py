"""
Tests for Lifecycle Governance (v1.1) and related threat mitigations (T1, T2, T3, T8).
"""
import logging
from pathlib import Path

import pytest

from scyvera import (
    ContractVersion,
    apply_lifecycle_defaults,
    detect_contract_version,
    lint_contract,
    validate_contract,
)
from scyvera.validator import load_contract


ROOT = Path(__file__).resolve().parent.parent
FIXTURES_V1_1 = ROOT / "tests" / "fixtures" / "v1.1"
SCHEMA_V1_1 = ROOT / "schemas" / "v1.1" / "contract.schema.json"


def test_worked_example_request_response_validates():
    """Worked example 1: Request-response agent validates cleanly."""
    contract_path = FIXTURES_V1_1 / "lifecycle-request-response.yaml"
    result = validate_contract(contract_path, schema_path=SCHEMA_V1_1)
    assert result.valid is True
    assert result.errors == ()


def test_worked_example_scheduled_validates():
    """Worked example 2: Scheduled agent validates cleanly."""
    contract_path = FIXTURES_V1_1 / "lifecycle-scheduled.yaml"
    result = validate_contract(contract_path, schema_path=SCHEMA_V1_1)
    assert result.valid is True
    assert result.errors == ()


def test_worked_example_persistent_validates():
    """Worked example 3: Persistent agent with idle_behavior validates cleanly."""
    contract_path = FIXTURES_V1_1 / "lifecycle-persistent.yaml"
    result = validate_contract(contract_path, schema_path=SCHEMA_V1_1)
    assert result.valid is True
    assert result.errors == ()


def test_persistent_mode_without_idle_behavior_fails_validation():
    """A persistent agent with no idle_behavior MUST fail validation (T2 constraint)."""
    contract_path = FIXTURES_V1_1 / "lifecycle-persistent-no-idle.yaml"
    result = validate_contract(contract_path, schema_path=SCHEMA_V1_1)
    assert result.valid is False
    assert len(result.errors) > 0
    # Error should indicate idle_behavior or schema condition failure
    assert any("idle_behavior" in e.message or "lifecycle" in e.path for e in result.errors)


def test_v1_contract_validates_and_defaults_applied(caplog):
    """A v1 contract without lifecycle passes validation, and loader defaults are applied with a warning."""
    v1_contract_path = (
        ROOT
        / "implementations"
        / "n8n"
        / "duplicate-issue-detector"
        / "contract.yaml"
    )
    result = validate_contract(v1_contract_path)
    assert result.valid is True

    # Test apply_lifecycle_defaults on a v1.1 contract missing lifecycle
    raw_v1_1 = {
        "version": 1.1,
        "system": {"name": "test-agent"},
        "inputs": [],
        "outputs": [],
        "permissions": [],
        "side_effects": [],
        "approvals": [],
        "dependencies": [],
        "state": {"persistence": "none"},
        "recovery": {"strategy": "retry"},
        "replay": {"mode": "idempotent"},
        "observability": {"level": "basic"},
        "risk": {"level": "low"},
    }
    with caplog.at_level(logging.WARNING):
        augmented = apply_lifecycle_defaults(raw_v1_1)

    assert "lifecycle" in augmented
    assert augmented["lifecycle"]["mode"] == "request-response"
    assert augmented["lifecycle"]["initiation"] == "human-only"
    assert augmented["lifecycle"]["resumability"] == "stateless"
    assert "Applying defaults" in caplog.text


def test_detect_contract_version():
    """Contract version detector accurately parses contract_version and version fields."""
    assert detect_contract_version({"contract_version": "1.1"}) == ContractVersion.V1_1
    assert detect_contract_version({"contract_version": "1"}) == ContractVersion.V1
    assert detect_contract_version({"version": 1.1}) == ContractVersion.V1_1
    assert detect_contract_version({"version": "1.1"}) == ContractVersion.V1_1
    assert detect_contract_version({"version": 1}) == ContractVersion.V1
    assert detect_contract_version({}) == ContractVersion.V1


def test_linter_ac301_vague_idle_behavior_warning(tmp_path):
    """Linter flags vague terms in idle_behavior (T2 mitigation)."""
    contract_file = tmp_path / "contract.yaml"
    contract_file.write_text(
        """version: 1.1
system:
  name: vague-agent
lifecycle:
  mode: persistent
  idle_behavior: "assists users with whatever and anything they ask"
inputs: []
outputs: []
permissions: []
side_effects: []
approvals: []
dependencies: []
state:
  persistence: none
recovery:
  strategy: retry
replay:
  mode: idempotent
observability:
  level: basic
risk:
  level: low
""",
        encoding="utf-8",
    )

    res = lint_contract(contract_file)
    assert res.valid_structure is True
    rule_ids = [w.rule_id for w in res.warnings]
    assert "AC301" in rule_ids
    ac301 = next(w for w in res.warnings if w.rule_id == "AC301")
    assert "vague term" in ac301.message.lower()


def test_linter_ac302_irreversible_side_effect_without_approval(tmp_path):
    """Linter flags irreversible side effects when approvals is empty (T8 mitigation)."""
    contract_file = tmp_path / "contract.yaml"
    contract_file.write_text(
        """version: 1.1
system:
  name: irreversible-agent
lifecycle:
  mode: request-response
inputs: []
outputs: []
permissions: []
side_effects:
  - type: database_wipe
    resource: production_db
    irreversible: true
approvals: []
dependencies: []
state:
  persistence: none
recovery:
  strategy: retry
replay:
  mode: idempotent
observability:
  level: basic
risk:
  level: high
""",
        encoding="utf-8",
    )

    res = lint_contract(contract_file)
    assert res.valid_structure is True
    rule_ids = [w.rule_id for w in res.warnings]
    assert "AC302" in rule_ids
