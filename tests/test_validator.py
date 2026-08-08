from pathlib import Path

import pytest
import yaml

from scyvera import validate_contract


ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schemas" / "v1" / "contract.schema.json"


def test_valid_contract_passes():
    contract = (
        ROOT
        / "implementations"
        / "n8n"
        / "duplicate-issue-detector"
        / "contract.yaml"
    )

    result = validate_contract(contract)

    assert result.valid is True
    assert result.errors == ()


def test_wrong_version_fails():
    contract = ROOT / "tests" / "fixtures" / "invalid-version.yaml"

    result = validate_contract(contract, SCHEMA)

    assert result.valid is False
    assert len(result.errors) == 1
    assert result.errors[0].path == "version"


def test_empty_contract_fails():
    contract = ROOT / "tests" / "fixtures" / "empty.yaml"

    result = validate_contract(contract, SCHEMA)

    assert result.valid is False
    assert len(result.errors) == 1
    assert result.errors[0].path == ""
    assert result.errors[0].message == "contract.yaml is empty"


def test_malformed_yaml_raises_yaml_error():
    contract = ROOT / "tests" / "fixtures" / "malformed.yaml"

    with pytest.raises(yaml.YAMLError):
        validate_contract(contract)
