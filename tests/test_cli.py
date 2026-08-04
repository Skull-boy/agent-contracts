from pathlib import Path

from agent_contracts.cli import main


ROOT = Path(__file__).resolve().parent.parent


def test_cli_valid_contract_returns_zero(monkeypatch, capsys):
    contract = (
        ROOT
        / "implementations"
        / "n8n"
        / "duplicate-issue-detector"
        / "contract.yaml"
    )

    monkeypatch.setattr(
        "sys.argv",
        ["agent-contracts", "validate", str(contract)],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "PASS" in output


def test_cli_invalid_contract_returns_one(monkeypatch, capsys):
    contract = ROOT / "tests" / "fixtures" / "invalid-version.yaml"

    monkeypatch.setattr(
        "sys.argv",
        ["agent-contracts", "validate", str(contract)],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "FAIL" in output
    assert "version" in output


def test_cli_missing_file_returns_two(monkeypatch, capsys):
    contract = ROOT / "tests" / "fixtures" / "does-not-exist.yaml"

    monkeypatch.setattr(
        "sys.argv",
        ["agent-contracts", "validate", str(contract)],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 2
    assert "ERROR" in output
    assert "file not found" in output