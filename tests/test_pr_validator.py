from pathlib import Path
import sys

from scripts.validate_pr_contracts import validate_files, AGENT_CONTRACT_PATH

def test_contract_validator_agent_contract_is_valid():
    passed, failed, report = validate_files([AGENT_CONTRACT_PATH])
    assert failed == 0
    assert passed == 1
    assert "Contract Governance Report (PASS)" in report
    assert "contract-validator" in report

def test_validate_pr_contracts_handles_mixed_files(tmp_path):
    valid_contract = tmp_path / "valid_contract.yaml"
    valid_contract.write_text(
        """version: 1.1\nsystem:\n  name: test-agent\nlifecycle:\n  mode: request-response\n"""
    )
    invalid_contract = tmp_path / "invalid_contract.yaml"
    invalid_contract.write_text(
        """version: 99\nsystem:\n  name: test-agent\n"""
    )

    passed, failed, report = validate_files([valid_contract, invalid_contract])
    assert passed == 1
    assert failed == 1
    assert "Contract Governance Report (WARNING)" in report
    assert "FAIL" in report
