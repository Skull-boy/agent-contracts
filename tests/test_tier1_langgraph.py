"""Tests for the LangGraph Tier 1 static adapter (RFC 0003 §C3, M2.3).

Coverage targets:

- The committed reference implementation has an exact expected finding set:
  no T101/T102, and six T103 warnings for declarations the code never
  exercises (``github.close`` / ``github.label`` / ``github.merge`` /
  ``qdrant.delete`` plus the two free-text side-effect sentences).
- Detection is proven on mutated ``tmp_path`` copies (an undeclared HTTP host,
  an approval declaration with an ungated write, and a gated graph), while
  every committed reference file stays byte-identical.
- Discovery claims the target only while the contract says
  ``framework: langgraph`` (or the repository parent chain exposes the
  adapter); removing the key produces the clean unclaimed-target exit 2.
- The adapter is fail-closed on invalid contracts and unparseable source, and
  read-only/deterministic (mtime + byte snapshots).
- CLI ``--tier 1`` follows the 0/1/2 exit-code matrix, and the M2.2 n8n
  commands keep their pinned output.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

from scyvera.cli import _discover_tier1_adapter, main
from scyvera.conformance import (
    CheckTier,
    ConformanceError,
    Tier1ContractError,
    check_contract,
    render_check,
)

ROOT = Path(__file__).resolve().parent.parent
ADAPTER_PATH = ROOT / "implementations" / "langgraph" / "tier1.py"
TARGET = ROOT / "implementations" / "langgraph" / "duplicate-issue-detector"
N8N_TARGET = ROOT / "implementations" / "n8n" / "duplicate-issue-detector"
N8N_CONFORMANT = ROOT / "implementations" / "n8n" / "github-debugger-agent"
INVALID_ENUM = ROOT / "tests" / "fixtures" / "v1.1" / "invalid-enum.yaml"
VALID = ROOT / "tests" / "fixtures" / "v1.1" / "valid-full.yaml"


def _load_adapter_module():
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(
            "langgraph_tier1_under_test", ADAPTER_PATH
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


_MODULE = _load_adapter_module()
LangGraphTier1Adapter = _MODULE.LangGraphTier1Adapter

EXPECTED_MESSAGES = {
    "github.close": (
        "contract declares a permission for 'github.close' but the "
        "implementation never exercises it"
    ),
    "github.label": (
        "contract declares a permission for 'github.label' but the "
        "implementation never exercises it"
    ),
    "github.merge": (
        "contract declares a permission for 'github.merge' but the "
        "implementation never exercises it"
    ),
    "posts": (
        "contract declares a permission for "
        "'posts-one-comment-on-the-triggering-issue,-if-similarity->=-threshold' "
        "but the implementation never exercises it"
    ),
    "qdrant.delete": (
        "contract declares a permission for 'qdrant.delete' but the "
        "implementation never exercises it"
    ),
    "writes": (
        "contract declares a permission for "
        "'writes-one-vector-to-the-qdrant-collection-(always,-regardless-of-duplicate-result)' "
        "but the implementation never exercises it"
    ),
}


def _scan(directory: Path):
    return LangGraphTier1Adapter().scan(directory, directory / "contract.yaml")


def _pairs(findings) -> set[tuple[str, str]]:
    return {(finding.code, finding.node_id) for finding in findings}


def _snapshot(directory: Path) -> dict[str, tuple[int, bytes]]:
    return {
        str(path.relative_to(directory)): (path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(directory.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def _copy_target(tmp_path: Path, name: str = "duplicate-issue-detector") -> Path:
    target = tmp_path / name
    shutil.copytree(
        TARGET,
        target,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    return target


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"mutation anchor not found in {path}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


@pytest.fixture(scope="session", autouse=True)
def _guard_committed_reference() -> None:
    """Fail the session if any committed LangGraph reference file changed."""
    before = _snapshot(TARGET)
    yield
    after = _snapshot(TARGET)
    assert after == before, "committed LangGraph fixtures must stay byte-identical"


# ---------------------------------------------------------------------------
# Exact findings for the committed reference implementation
# ---------------------------------------------------------------------------


def test_reference_exact_findings() -> None:
    findings = _scan(TARGET)
    assert [finding.code for finding in findings] == ["T103"] * 6
    assert _pairs(findings) == {("T103", "")}
    assert all(finding.severity == "warning" for finding in findings)
    assert all(Path(finding.path).name == "contract.yaml" for finding in findings)
    assert {finding.message for finding in findings} == set(
        EXPECTED_MESSAGES.values()
    )


def test_reference_has_no_undeclared_or_ungated_findings() -> None:
    findings = _scan(TARGET)
    assert not {finding.code for finding in findings} & {"T101", "T102"}


def test_reference_is_warn_only_in_check_report() -> None:
    report = check_contract(
        TARGET / "contract.yaml",
        tier="1",
        target=TARGET,
        adapter=LangGraphTier1Adapter(),
    )
    assert report.tier is CheckTier.STATIC
    assert report.valid is True
    assert report.tier1_failed is False
    text = render_check(report)
    assert text.startswith("WARN ")
    assert "[T103] unused declaration:" in text
    assert text.isascii()


def test_scan_is_deterministic() -> None:
    assert _scan(TARGET) == _scan(TARGET)


def test_create_adapter_factory() -> None:
    adapter = _MODULE.create_adapter()
    assert isinstance(adapter, LangGraphTier1Adapter)


# ---------------------------------------------------------------------------
# Mutation detection (tmp_path copies; committed files stay untouched)
# ---------------------------------------------------------------------------


def test_mutation_detects_undeclared_http_host(tmp_path: Path) -> None:
    target = _copy_target(tmp_path)
    _replace(
        target / "duplicate_issue_detector" / "nodes.py",
        "    results = [",
        '    httpx.get("https://api.stripe.com/v1/charges")\n    results = [',
    )
    findings = _scan(target)
    assert ("T101", "judge") in _pairs(findings)
    finding = next(item for item in findings if item.code == "T101")
    assert finding.severity == "error"
    assert "stripe" in finding.message
    assert finding.path.endswith("nodes.py")


def test_mutation_detects_ungated_write(tmp_path: Path) -> None:
    target = _copy_target(tmp_path)
    _replace(
        target / "contract.yaml",
        "approval_points: []",
        "approval_points:\n  - qdrant.write",
    )
    findings = _scan(target)
    assert ("T102", "index") in _pairs(findings)
    finding = next(item for item in findings if item.code == "T102")
    assert finding.severity == "error"
    assert "without traversing an approval gate" in finding.message


def test_gate_on_every_write_path_suppresses_t102(tmp_path: Path) -> None:
    target = _copy_target(tmp_path)
    _replace(
        target / "contract.yaml",
        "approval_points: []",
        "approval_points:\n  - qdrant.write",
    )
    graph = target / "duplicate_issue_detector" / "graph.py"
    _replace(
        target / "duplicate_issue_detector" / "nodes.py",
        "def detect(state: State) -> dict[str, Any]:",
        (
            "def approval_gate(state: State) -> dict[str, Any]:\n"
            "    from langgraph.types import interrupt\n"
            '    interrupt("approve qdrant write")\n'
            "    return {}\n\n\n"
            "def detect(state: State) -> dict[str, Any]:"
        ),
    )
    _replace(
        graph,
        '    g.add_node("index", index)',
        '    g.add_node("index", index)\n    g.add_node("approval", approval_gate)',
    )
    _replace(
        graph,
        '{"act": "act", "index": "index"}',
        '{"act": "act", "index": "approval"}',
    )
    _replace(graph, '    g.add_edge("act", "index")', '    g.add_edge("act", "approval")')
    _replace(
        graph,
        '    g.add_edge("index", END)',
        '    g.add_edge("approval", "index")\n    g.add_edge("index", END)',
    )

    findings = _scan(target)
    assert not any(finding.code == "T102" for finding in findings)


def test_unparseable_source_fails_closed(tmp_path: Path) -> None:
    target = _copy_target(tmp_path)
    (target / "duplicate_issue_detector" / "broken.py").write_text(
        "def broken(:\n", encoding="utf-8"
    )
    findings = _scan(target)
    assert ("T101", "<module>") in _pairs(findings)
    assert all(
        finding.severity == "error"
        for finding in findings
        if finding.code == "T101"
    )


def test_committed_files_are_never_modified() -> None:
    before = _snapshot(TARGET)
    _scan(TARGET)
    assert _snapshot(TARGET) == before


def test_adapter_is_read_only(tmp_path: Path) -> None:
    target = _copy_target(tmp_path)
    before = _snapshot(target)
    _scan(target)
    assert _snapshot(target) == before


# ---------------------------------------------------------------------------
# Fail-closed contract handling and discovery
# ---------------------------------------------------------------------------


def test_adapter_refuses_invalid_contract() -> None:
    with pytest.raises(Tier1ContractError) as excinfo:
        LangGraphTier1Adapter().scan(TARGET, INVALID_ENUM)
    assert issubclass(Tier1ContractError, ConformanceError)
    assert "refusing to scan" in str(excinfo.value)


def test_check_contract_tier1_invalid_contract_never_scans() -> None:
    report = check_contract(
        INVALID_ENUM,
        tier="1",
        target=TARGET,
        adapter=LangGraphTier1Adapter(),
    )
    assert report.valid is False
    assert report.tier1_findings == ()
    assert report.tier1_failed is False


def test_discovery_claims_langgraph_reference() -> None:
    adapter = _discover_tier1_adapter(TARGET)
    assert adapter is not None
    assert type(adapter).__name__ == "LangGraphTier1Adapter"


def test_discovery_keeps_n8n_branch() -> None:
    adapter = _discover_tier1_adapter(N8N_TARGET)
    assert adapter is not None
    assert type(adapter).__name__ == "N8nTier1Adapter"


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


def test_cli_langgraph_warn_only_exit_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code, output, error = _run_cli(monkeypatch, capsys, TARGET, "1")
    assert exit_code == 0
    assert error == ""
    assert "WARN" in output
    assert "tier 1 (static)" in output
    assert "[T103] unused declaration:" in output
    assert "[T101]" not in output
    assert "[T102]" not in output


def test_cli_langgraph_unclaimed_target_exit_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _copy_target(tmp_path)
    contract = target / "contract.yaml"
    text = contract.read_text(encoding="utf-8")
    contract.write_text(text.replace("framework: langgraph\n", "", 1), encoding="utf-8")

    exit_code, output, error = _run_cli(monkeypatch, capsys, target, "1")
    assert exit_code == 2
    assert output == ""
    assert "no tier 1 adapter" in error
    assert "Traceback" not in error


def test_cli_random_directory_exit_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "empty"
    target.mkdir()
    exit_code, output, error = _run_cli(monkeypatch, capsys, target, "1")
    assert exit_code == 2
    assert output == ""
    assert "no tier 1 adapter" in error


def test_cli_n8n_findings_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code, output, error = _run_cli(monkeypatch, capsys, N8N_TARGET, "1")
    assert exit_code == 1
    assert error == ""
    assert "[T101] undeclared action:" in output
    assert "Embed New Issue (Ollama)" in output
    assert "Embed Issue (Ollama)" in output


def test_cli_n8n_conformant_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code, output, error = _run_cli(monkeypatch, capsys, N8N_CONFORMANT, "1")
    assert exit_code == 0
    assert error == ""
    assert "PASS" in output


def test_cli_tier0_untouched(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code, output, error = _run_cli(monkeypatch, capsys, VALID, "0")
    assert exit_code == 0
    assert error == ""
    assert output.startswith(f"PASS  {VALID}")
    assert "tier 0 (structural)" in output
    assert "[T10" not in output
