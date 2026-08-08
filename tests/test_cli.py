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
        ["agent-contract", "validate", str(contract)],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "PASS" in output


def test_cli_invalid_contract_returns_one(monkeypatch, capsys):
    contract = ROOT / "tests" / "fixtures" / "invalid-version.yaml"

    monkeypatch.setattr(
        "sys.argv",
        ["agent-contract", "validate", str(contract)],
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
        ["agent-contract", "validate", str(contract)],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 2
    assert "ERROR" in output
    assert "file not found" in output


def test_cli_v1_1_valid_contract_returns_zero(monkeypatch, capsys):
    contract = ROOT / "tests" / "fixtures" / "v1.1" / "valid-full.yaml"

    monkeypatch.setattr(
        "sys.argv",
        ["agent-contract", "validate", str(contract)],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "PASS" in output


def test_cli_explicit_schema_flag(monkeypatch, capsys):
    contract = ROOT / "tests" / "fixtures" / "v1.1" / "valid-minimal.yaml"
    schema = ROOT / "schemas" / "v1.1" / "contract.schema.json"

    monkeypatch.setattr(
        "sys.argv",
        ["agent-contract", "validate", str(contract), "--schema", str(schema)],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "PASS" in output


def test_cli_init_generates_valid_v1_1_contract(tmp_path, monkeypatch, capsys):
    output_file = tmp_path / "contract.yaml"

    monkeypatch.setattr(
        "sys.argv",
        ["agent-contract", "init", str(output_file), "--name", "Test Tutor"],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "CREATED" in output
    assert output_file.exists()

    # Now validate the generated contract file directly using CLI validate
    monkeypatch.setattr(
        "sys.argv",
        ["agent-contract", "validate", str(output_file)],
    )
    val_exit = main()
    val_out = capsys.readouterr().out

    assert val_exit == 0
    assert "PASS" in val_out