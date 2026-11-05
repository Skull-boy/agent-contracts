"""Tests for the n8n Tier 1 static adapter (RFC 0003 §C3, roadmap M2.2).

Coverage targets:

- Every committed n8n reference workflow has an exact expected finding set
  (code + node id): ``duplicate-issue-detector`` reports its two undeclared
  Ollama endpoints, the other three are fully conformant.
- Detection is proven on mutated ``tmp_path`` copies (an undeclared host and a
  write that bypasses its approval gate), while the committed ``workflow.json``
  and ``contract.yaml`` files stay byte-identical.
- The adapter is fail-closed: an invalid contract raises
  :class:`Tier1ContractError` and ``check_contract`` never scans it.
- The adapter is read-only and deterministic (mtime + bytes snapshots).
- CLI ``--tier 1`` follows the 0/1/2 exit-code matrix; ``--tier 2`` still
  fails loudly with the unchanged not-implemented message.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

from scyvera.cli import main
from scyvera.conformance import (
    CheckTier,
    ConformanceError,
    Tier1ContractError,
    check_contract,
    render_check,
)

ROOT = Path(__file__).resolve().parent.parent
IMPLEMENTATIONS = ROOT / "implementations" / "n8n"
ADAPTER_PATH = IMPLEMENTATIONS / "tier1.py"
INVALID_ENUM = ROOT / "tests" / "fixtures" / "v1.1" / "invalid-enum.yaml"
VALID = ROOT / "tests" / "fixtures" / "v1.1" / "valid-full.yaml"


def _load_adapter_class() -> type:
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(
            "n8n_tier1_under_test", ADAPTER_PATH
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module.N8nTier1Adapter


N8nTier1Adapter = _load_adapter_class()

WORKFLOWS = {
    directory.name: directory
    for directory in sorted(IMPLEMENTATIONS.iterdir())
    if (directory / "workflow.json").is_file()
}

EXPECTED: dict[str, set[tuple[str, str]]] = {
    "competitor-feature-parity-watcher": set(),
    "duplicate-issue-detector": {
        ("T101", "Embed New Issue (Ollama)"),
        ("T101", "Embed Issue (Ollama)"),
    },
    "github-debugger-agent": set(),
    "telegram-github-antigravity-pipeline": set(),
}


def _scan(directory: Path):
    return N8nTier1Adapter().scan(directory, directory / "contract.yaml")


def _pairs(findings) -> set[tuple[str, str]]:
    return {(finding.code, finding.node_id) for finding in findings}


def _copy_workflow(
    tmp_path: Path,
    name: str,
    mutate: Callable[[dict[str, Any]], None] | None = None,
    contract_edit: Callable[[str], str] | None = None,
) -> Path:
    source = WORKFLOWS[name]
    target = tmp_path / name
    target.mkdir()
    shutil.copy2(source / "workflow.json", target / "workflow.json")
    contract_text = (source / "contract.yaml").read_text(encoding="utf-8")
    if contract_edit is not None:
        contract_text = contract_edit(contract_text)
    (target / "contract.yaml").write_text(contract_text, encoding="utf-8")
    if mutate is not None:
        payload = json.loads((source / "workflow.json").read_text(encoding="utf-8"))
        mutate(payload)
        (target / "workflow.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    return target


def _snapshot(directory: Path) -> dict[str, tuple[int, bytes]]:
    return {
        path.name: (path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(directory.iterdir())
        if path.is_file()
    }


@pytest.fixture(scope="session", autouse=True)
def _guard_committed_workflows():
    """Fail the session if any committed reference file changed bytes/mtime."""
    before = {name: _snapshot(directory) for name, directory in WORKFLOWS.items()}
    yield
    after = {name: _snapshot(directory) for name, directory in WORKFLOWS.items()}
    assert after == before, "committed n8n fixtures must stay byte-identical"


# ---------------------------------------------------------------------------
# Expected findings per committed reference workflow
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_reference_workflow_exact_findings(name: str) -> None:
    findings = _scan(WORKFLOWS[name])
    assert _pairs(findings) == EXPECTED[name]
    assert all(finding.node_id for finding in findings)
    assert all(finding.path.endswith("workflow.json") for finding in findings)


def test_reference_corpus_covers_both_verdicts() -> None:
    nonconformant = {name for name in EXPECTED if _scan(WORKFLOWS[name])}
    conformant = {name for name in EXPECTED if not _scan(WORKFLOWS[name])}
    assert nonconformant == {"duplicate-issue-detector"}
    assert conformant == {
        "competitor-feature-parity-watcher",
        "github-debugger-agent",
        "telegram-github-antigravity-pipeline",
    }


def test_t101_findings_are_errors() -> None:
    findings = _scan(WORKFLOWS["duplicate-issue-detector"])
    assert findings
    assert {finding.code for finding in findings} == {"T101"}
    assert {finding.severity for finding in findings} == {"error"}
    assert all("local-llm" in finding.message for finding in findings)


def test_scan_is_deterministic() -> None:
    for name in EXPECTED:
        assert _scan(WORKFLOWS[name]) == _scan(WORKFLOWS[name])


# ---------------------------------------------------------------------------
# Mutation detection (tmp_path copies; committed files stay untouched)
# ---------------------------------------------------------------------------


def _mutate_undeclared_host(workflow: dict[str, Any]) -> None:
    for node in workflow["nodes"]:
        if node.get("name") == "Fetch Changelog Page":
            node["parameters"]["url"] = "https://api.stripe.com/v1/charges"
            return
    raise AssertionError("fixture node not found")


def _bypass_approval_gate(workflow: dict[str, Any]) -> None:
    for edge in workflow["connections"]["Send to Discord"]["main"][0]:
        if edge.get("node") == "Wait for Approval":
            edge["node"] = "Commit Fixes"
            return
    raise AssertionError("approval edge not found")


def test_mutation_detects_undeclared_host(tmp_path: Path) -> None:
    target = _copy_workflow(
        tmp_path, "competitor-feature-parity-watcher", _mutate_undeclared_host
    )
    findings = _scan(target)
    assert _pairs(findings) == {("T101", "Fetch Changelog Page")}
    assert findings[0].severity == "error"


def test_mutation_detects_ungated_write(tmp_path: Path) -> None:
    target = _copy_workflow(tmp_path, "github-debugger-agent", _bypass_approval_gate)
    findings = _scan(target)
    assert _pairs(findings) == {("T102", "Commit Fixes")}
    assert findings[0].severity == "error"


def test_mutation_detects_unused_declaration(tmp_path: Path) -> None:
    def add_slack(contract: str) -> str:
        return contract.replace(
            "permissions:\n", "permissions:\n  - slack: read\n", 1
        )

    target = _copy_workflow(tmp_path, "github-debugger-agent", contract_edit=add_slack)
    findings = _scan(target)
    assert _pairs(findings) == {("T103", "")}
    assert findings[0].severity == "warning"
    assert findings[0].path.endswith("contract.yaml")


def test_unknown_external_node_is_not_silently_skipped(tmp_path: Path) -> None:
    def add_postgres(workflow: dict[str, Any]) -> None:
        workflow["nodes"].append(
            {
                "name": "Write Findings",
                "type": "n8n-nodes-base.postgres",
                "typeVersion": 1,
                "parameters": {"operation": "insert"},
                "position": [0, 0],
            }
        )

    target = _copy_workflow(tmp_path, "github-debugger-agent", add_postgres)
    assert ("T101", "Write Findings") in _pairs(_scan(target))


def test_committed_files_are_never_modified() -> None:
    before = {name: _snapshot(directory) for name, directory in WORKFLOWS.items()}
    for directory in WORKFLOWS.values():
        _scan(directory)
    after = {name: _snapshot(directory) for name, directory in WORKFLOWS.items()}
    assert after == before, "tier 1 scanning must be read-only"


def test_adapter_is_read_only(tmp_path: Path) -> None:
    target = _copy_workflow(tmp_path, "github-debugger-agent")
    before = _snapshot(target)
    _scan(target)
    assert _snapshot(target) == before


# ---------------------------------------------------------------------------
# Fail-closed contract handling and report shape
# ---------------------------------------------------------------------------


def test_adapter_refuses_invalid_contract() -> None:
    with pytest.raises(Tier1ContractError) as excinfo:
        N8nTier1Adapter().scan(
            WORKFLOWS["github-debugger-agent"],
            INVALID_ENUM,
        )
    assert issubclass(Tier1ContractError, ConformanceError)
    assert "refusing to scan" in str(excinfo.value)


def test_check_contract_tier1_invalid_contract_never_scans() -> None:
    report = check_contract(
        INVALID_ENUM,
        tier="1",
        target=WORKFLOWS["github-debugger-agent"],
        adapter=N8nTier1Adapter(),
    )
    assert report.valid is False
    assert report.tier1_findings == ()
    assert report.tier1_failed is False


def test_check_contract_tier1_reports_findings() -> None:
    directory = WORKFLOWS["duplicate-issue-detector"]
    report = check_contract(
        directory / "contract.yaml",
        tier="1",
        target=directory,
        adapter=N8nTier1Adapter(),
    )
    assert report.tier is CheckTier.STATIC
    assert report.valid is True
    assert report.tier1_failed is True
    text = render_check(report)
    assert "      [T101] undeclared action: node 'Embed New Issue (Ollama)'" in text
    assert text.isascii()
    assert text.startswith("FAIL ")


def test_tier0_report_has_empty_tier1_findings() -> None:
    report = check_contract(VALID, tier="0")
    assert report.tier1_findings == ()
    assert report.tier1_failed is False


# ---------------------------------------------------------------------------
# CLI 0/1/2 matrix
# ---------------------------------------------------------------------------


def _run_cli(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    target: Path,
    tier: str,
) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["scyvera", "check", str(target), "--tier", tier])
    exit_code = main()
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


@pytest.mark.parametrize(
    "name",
    [
        "competitor-feature-parity-watcher",
        "github-debugger-agent",
        "telegram-github-antigravity-pipeline",
    ],
)
def test_cli_tier1_conformant_exit_zero(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code, output, error = _run_cli(
        monkeypatch, capsys, WORKFLOWS[name], "1"
    )
    assert exit_code == 0
    assert error == ""
    assert "PASS" in output
    assert "tier 1 (static)" in output
    assert "[T10" not in output


def test_cli_tier1_findings_exit_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code, output, error = _run_cli(
        monkeypatch, capsys, WORKFLOWS["duplicate-issue-detector"], "1"
    )
    assert exit_code == 1
    assert error == ""
    assert "FAIL" in output
    assert "[T101] undeclared action:" in output
    assert "Embed New Issue (Ollama)" in output
    assert "Embed Issue (Ollama)" in output


def test_cli_tier1_warn_only_exit_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def add_slack(contract: str) -> str:
        return contract.replace(
            "permissions:\n", "permissions:\n  - slack: read\n", 1
        )

    target = _copy_workflow(tmp_path, "github-debugger-agent", contract_edit=add_slack)
    monkeypatch.setattr(
        "scyvera.cli._discover_tier1_adapter", lambda _target: N8nTier1Adapter()
    )
    exit_code, output, error = _run_cli(monkeypatch, capsys, target, "1")
    assert exit_code == 0, "T103 warnings are informational"
    assert error == ""
    assert "WARN" in output
    assert "[T103] unused declaration:" in output


def test_cli_tier1_without_adapter_exit_two(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code, output, error = _run_cli(monkeypatch, capsys, VALID, "1")
    assert exit_code == 2
    assert output == ""
    assert "no tier 1 adapter" in error
    assert "Traceback" not in error


def test_cli_tier2_still_exit_two(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code, output, error = _run_cli(monkeypatch, capsys, VALID, "2")
    assert exit_code == 2
    assert output == ""
    assert "tier 2 (runtime-trace) is not implemented yet" in error
    assert "Traceback" not in error


def test_cli_tier0_output_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code, output, error = _run_cli(monkeypatch, capsys, VALID, "0")
    assert exit_code == 0
    assert error == ""
    assert output.startswith(f"PASS  {VALID}")
    assert "tier 0 (structural)" in output
    assert "[T10" not in output
