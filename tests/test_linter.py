from pathlib import Path

from agent_contracts import lint_contract, Contract
from agent_contracts.cli import main


ROOT = Path(__file__).resolve().parent.parent


def test_linter_clean_contract():
    contract = (
        Contract(name="Clean Tutor")
        .add_capability("explain")
        .set_risk("low")
        .set_observability("basic")
    )
    # Validate and lint
    val_res = contract.validate()
    assert val_res.valid is True

    lint_res = lint_contract(ROOT / "examples" / "v1.1" / "education-tutor.yaml")
    assert lint_res.valid_structure is True
    assert lint_res.warnings == ()


def test_linter_ac101_unbounded_write():
    c = Contract(name="Unbounded Writer Agent")
    c.add_permission("database", actions=["write"])
    # Note: no side_effects declared!

    # Save to temp file
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as tmp:
        c.save(tmp.name)
        lint_res = lint_contract(tmp.name)

    assert lint_res.valid_structure is True
    assert len(lint_res.warnings) >= 1
    assert any(w.rule_id == "AC101" for w in lint_res.warnings)


def test_linter_ac201_unprotected_high_risk():
    c = Contract(name="High Risk Agent")
    c.set_risk("critical")
    # Note: no approvals declared!

    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as tmp:
        c.save(tmp.name)
        lint_res = lint_contract(tmp.name)

    assert lint_res.valid_structure is True
    assert len(lint_res.warnings) >= 1
    assert any(w.rule_id == "AC201" for w in lint_res.warnings)


def test_linter_ac103_capability_duplicating_permission(tmp_path):
    c = Contract(name="Duplicate Verb System")
    c.add_capability("read_patient_records")  # Duplicates permission verb!

    f = tmp_path / "ac103.yaml"
    c.save(f)
    lint_res = lint_contract(f)

    assert lint_res.valid_structure is True
    assert any(w.rule_id == "AC103" for w in lint_res.warnings)


def test_cli_lint_command(monkeypatch, capsys):
    contract = ROOT / "examples" / "v1.1" / "research-assistant.yaml"

    monkeypatch.setattr(
        "sys.argv",
        ["agent-contract", "lint", str(contract)],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "PASS" in output
