"""Tests for contract filename enforcement.

The Agent Contract specification mandates contract.yaml as the canonical
filename. Files using .yml must be rejected with a clear, actionable error.
"""
from pathlib import Path

import pytest

from scyvera import validate_contract
from scyvera.exceptions import ContractFileNameError
from scyvera.validator import load_contract


ROOT = Path(__file__).resolve().parent.parent


def test_yml_extension_raises_contract_filename_error(tmp_path):
    """Loading a file named contract.yml raises ContractFileNameError."""
    yml_file = tmp_path / "contract.yml"
    yml_file.write_text("version: 1\nworkflow: test\n", encoding="utf-8")

    with pytest.raises(ContractFileNameError) as exc_info:
        load_contract(yml_file)

    assert "Found contract.yml" in str(exc_info.value)
    assert "rename to contract.yaml" in str(exc_info.value)
    assert "WORKFLOW-CONTRACT-SPEC.md" in str(exc_info.value)


def test_yml_extension_rejected_via_validate_contract(tmp_path):
    """validate_contract also rejects .yml files (it calls load_contract internally)."""
    yml_file = tmp_path / "my-agent.yml"
    yml_file.write_text("version: 1\nworkflow: test\n", encoding="utf-8")

    with pytest.raises(ContractFileNameError):
        validate_contract(yml_file)


def test_yaml_extension_accepted(tmp_path):
    """Loading a file named contract.yaml works normally."""
    yaml_file = tmp_path / "contract.yaml"
    yaml_file.write_text(
        "version: 1\nworkflow: test\ninputs: []\noutputs: []\n"
        "permissions: []\nside_effects: []\napproval_points: []\n"
        "recovery_strategy: retry\nreplay_semantics: idempotent\n"
        "dependencies: []\nstate: none\nobservability: []\n",
        encoding="utf-8",
    )

    # Should not raise
    data = load_contract(yaml_file)
    assert data["workflow"] == "test"


def test_non_yml_yaml_extension_accepted(tmp_path):
    """Loading .yaml files with non-standard names (e.g. my-system.yaml) works."""
    custom_file = tmp_path / "my-system.yaml"
    custom_file.write_text("version: 1\nworkflow: test\n", encoding="utf-8")

    data = load_contract(custom_file)
    assert data["workflow"] == "test"


def test_all_implementation_contracts_validate():
    """Every contract.yaml in implementations/ validates successfully."""
    contracts = list(ROOT.glob("implementations/**/contract.yaml"))
    assert len(contracts) > 0, "Expected at least one implementation contract.yaml"

    for contract_path in contracts:
        result = validate_contract(contract_path)
        assert result.valid, (
            f"{contract_path.relative_to(ROOT)} failed validation: "
            + "; ".join(f"{e.path}: {e.message}" for e in result.errors)
        )
