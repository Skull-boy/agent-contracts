from pathlib import Path

import pytest
from agent_contracts import validate_contract, SCHEMA_V1_1_PATH


ROOT = Path(__file__).resolve().parent.parent
FIXTURES_V1_1 = ROOT / "tests" / "fixtures" / "v1.1"


def test_v1_1_minimal_valid_contract():
    contract = FIXTURES_V1_1 / "valid-minimal.yaml"
    result = validate_contract(contract)

    assert result.valid is True
    assert result.errors == ()


def test_v1_1_full_valid_contract():
    contract = FIXTURES_V1_1 / "valid-full.yaml"
    result = validate_contract(contract)

    assert result.valid is True
    assert result.errors == ()


def test_v1_1_invalid_enum_fails():
    contract = FIXTURES_V1_1 / "invalid-enum.yaml"
    result = validate_contract(contract)

    assert result.valid is False
    assert len(result.errors) >= 1
    assert any("state.persistence" in err.path or "persistence" in err.message for err in result.errors)


def test_v1_1_missing_identity_fails():
    contract = FIXTURES_V1_1 / "invalid-missing-identity.yaml"
    result = validate_contract(contract)

    assert result.valid is False
    assert len(result.errors) >= 1


def test_unsupported_version_fails():
    contract = FIXTURES_V1_1 / "unsupported-version.yaml"
    result = validate_contract(contract)

    assert result.valid is False
    assert len(result.errors) == 1
    assert result.errors[0].path == "version"
    assert "Unsupported specification version" in result.errors[0].message


def test_v1_1_explicit_schema_path():
    contract = FIXTURES_V1_1 / "valid-minimal.yaml"
    result = validate_contract(contract, schema_path=SCHEMA_V1_1_PATH)

    assert result.valid is True
    assert result.errors == ()


def test_v1_1_system_identity(tmp_path):
    f = tmp_path / "system_contract.yaml"
    f.write_text(
        "version: 1.1\n"
        "system:\n"
        "  name: Test System\n"
        "  purpose: Testing system identity\n"
        "domain: software\n",
        encoding="utf-8",
    )
    result = validate_contract(f)
    assert result.valid is True
    assert result.errors == ()


def test_v1_1_agent_identity_compatibility(tmp_path):
    f = tmp_path / "agent_contract.yaml"
    f.write_text(
        "version: 1.1\n"
        "agent:\n"
        "  name: Test Agent\n"
        "  purpose: Testing agent identity alias\n",
        encoding="utf-8",
    )
    result = validate_contract(f)
    assert result.valid is True
    assert result.errors == ()


def test_v1_1_workflow_identity_compatibility(tmp_path):
    f = tmp_path / "workflow_contract.yaml"
    f.write_text(
        "version: 1.1\n"
        "workflow: Test Workflow\n",
        encoding="utf-8",
    )
    result = validate_contract(f)
    assert result.valid is True
    assert result.errors == ()