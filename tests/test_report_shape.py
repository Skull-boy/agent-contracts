"""Shape and status tests for the unified report envelope (roadmap M2.5).

Coverage targets:

- every mode (audit, tier 0, tier 1, eval) validates against
  ``schemas/report/v1/unified-report.schema.json``;
- all modes emit the exact same eight top-level keys;
- unified serialization is byte-identical across repeated calls;
- every status-mapping row is pinned, including the schema-only tier 2 mode
  and the CLI's loud tier 2 refusal;
- ACxxx / T1xx / AUxxx / eval findings normalize to one record shape with
  deterministic ordering;
- the published audit ``--json``, ``check`` render, and ``EvalResult.to_json``
  bytes remain pinned (snapshot assertions).
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest
import yaml
from jsonschema import Draft202012Validator

from scyvera.audit import AuditReport, scan_tree, unify_audit_report
from scyvera.audit_rules import Finding
from scyvera.cli import main
from scyvera.conformance import (
    CheckReport,
    CheckTier,
    TierNotImplementedError,
    check_contract,
    render_check,
    resolve_tier,
)
from scyvera.evals import run_eval_file
from scyvera.linter import LintWarning
from scyvera.unified import (
    MODES,
    UnifiedFinding,
    UnifiedReport,
    audit_status,
    check_status,
    eval_status,
    from_audit_report,
    from_eval_result,
    load_report_schema,
)


ROOT = Path(__file__).resolve().parent.parent
VALID = ROOT / "tests" / "fixtures" / "v1.1" / "valid-minimal.yaml"
VALID_REL = Path("tests/fixtures/v1.1/valid-minimal.yaml")
INVALID = ROOT / "tests" / "fixtures" / "v1.1" / "invalid-enum.yaml"
AUDIT_CLEAN = ROOT / "tests" / "fixtures" / "audit" / "negative"
AUDIT_CLEAN_REL = Path("tests/fixtures/audit/negative")
AUDIT_QUARANTINED = ROOT / "tests" / "fixtures" / "audit" / "positive"
N8N_CONFORMANT = ROOT / "implementations" / "n8n" / "competitor-feature-parity-watcher"
N8N_FAILING = ROOT / "implementations" / "n8n" / "duplicate-issue-detector"
LANGGRAPH_REF = (
    ROOT / "implementations" / "langgraph" / "duplicate-issue-detector"
)
GOLDEN_EVAL = LANGGRAPH_REF / "evals" / "refund-agent.eval.yaml"

EXPECTED_KEYS = {
    "report_version",
    "tool",
    "mode",
    "status",
    "subject",
    "summary",
    "findings",
    "data",
}

# Pinned pre-change serializer bytes (snapshot assertions, Task C-6).
AUDIT_JSON_SHA256 = "0f5b13338b6d26f4f77b5cd363ed81c007b17d93891c75658119922d386254bc"
EVAL_JSON_SHA256 = "c7915e57846e59b21bdd37eb9b3faab6f1d1f8a98c4b0555cdc9162772f60947"
CHECK_RENDER = (
    f"PASS  {VALID_REL} "
    "(tier 0 (structural): 0 schema errors, 0 semantic warnings)\n"
)


def _load_adapter(path: Path, class_name: str, name: str) -> type:
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return getattr(module, class_name)


N8N_TIER1 = _load_adapter(
    ROOT / "implementations" / "n8n" / "tier1.py", "N8nTier1Adapter", "unified_n8n"
)
LANGGRAPH_TIER1 = _load_adapter(
    ROOT / "implementations" / "langgraph" / "tier1.py",
    "LangGraphTier1Adapter",
    "unified_langgraph",
)


def _tier0(path: Path) -> UnifiedReport:
    return check_contract(path, tier="0").unified()


def _tier1(target: Path, adapter_class: type) -> UnifiedReport:
    return check_contract(
        target / "contract.yaml",
        tier="1",
        target=target,
        adapter=adapter_class(),
    ).unified()


def _audit(path: Path) -> UnifiedReport:
    report = scan_tree(path)
    return unify_audit_report(report.to_dict())


def _eval() -> UnifiedReport:
    return from_eval_result(run_eval_file(GOLDEN_EVAL))


CASES = {
    "audit-clean": lambda: _audit(AUDIT_CLEAN),
    "audit-quarantined": lambda: _audit(AUDIT_QUARANTINED),
    "check-tier0-pass": lambda: _tier0(VALID),
    "check-tier0-fail": lambda: _tier0(INVALID),
    "check-tier1-pass": lambda: _tier1(N8N_CONFORMANT, N8N_TIER1),
    "check-tier1-warn": lambda: _tier1(LANGGRAPH_REF, LANGGRAPH_TIER1),
    "eval": _eval,
}

EXPECTED_MODES = {
    "audit-clean": "audit",
    "audit-quarantined": "audit",
    "check-tier0-pass": "check-tier0",
    "check-tier0-fail": "check-tier0",
    "check-tier1-pass": "check-tier1",
    "check-tier1-warn": "check-tier1",
    "eval": "eval",
}


def _validator() -> Draft202012Validator:
    schema = load_report_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _run_cli(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *argv: object,
) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["scyvera", *(str(item) for item in argv)])
    code = main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _synthetic_audit_report() -> AuditReport:
    finding = Finding(
        rule_id="AU-NET-002",
        severity="medium",
        title="outbound network calls in source",
        detail="synthetic detail",
        path="src/foo/client.py",
        line=None,
        suggestion={},
        scored=True,
    )
    return AuditReport(
        report_version=1,
        target=".",
        score=99,
        band="Shielded",
        stats={
            "files_scanned": 3,
            "files_skipped": 0,
            "findings": {"critical": 0, "high": 0, "medium": 1, "low": 0},
        },
        findings=(finding,),
        draft_available=True,
        packs_suggested=("github-safe",),
    )


# ---------------------------------------------------------------------------
# Schema conformance and shape equality (Task C-1/C-2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(CASES))
def test_unified_mode_validates_against_schema(name: str) -> None:
    unified = CASES[name]()
    assert unified.mode == EXPECTED_MODES[name]
    _validator().validate(unified.to_dict())


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_mode_has_the_same_top_level_keys(name: str) -> None:
    payload = CASES[name]().to_dict()
    assert set(payload) == EXPECTED_KEYS
    assert payload["report_version"] == 1
    assert payload["tool"] == "scyvera"


def test_schema_represents_every_mode_including_tier2() -> None:
    schema = load_report_schema()
    assert schema["properties"]["mode"]["enum"] == list(MODES)
    assert "check-tier2" in MODES


# ---------------------------------------------------------------------------
# Determinism (Task C-3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(CASES))
def test_unified_bytes_are_identical_across_calls(name: str) -> None:
    first = CASES[name]()
    second = CASES[name]()
    assert first.to_dict() == second.to_dict()
    assert first.to_json() == second.to_json()


def test_unified_json_contains_no_timestamp_or_hostname() -> None:
    unified = CASES["eval"]()
    summary = json.dumps(dict(unified.summary), sort_keys=True).lower()
    for marker in ("timestamp", "hostname", "generated_at"):
        assert marker not in summary
    payload = unified.to_dict()
    for marker in ("timestamp", "hostname", "generated_at"):
        assert marker not in payload


# ---------------------------------------------------------------------------
# Status mapping pins (Task C-4)
# ---------------------------------------------------------------------------


def test_audit_status_mapping() -> None:
    clean = scan_tree(AUDIT_CLEAN).to_dict()
    quarantined = scan_tree(AUDIT_QUARANTINED).to_dict()

    assert audit_status(clean) == "PASS"
    assert audit_status(quarantined) == "WARN"
    assert audit_status({"score": 50, "findings": [{}]}, 90) == "FAIL"
    assert audit_status({"score": 95, "findings": [{}]}, 90) == "WARN"
    assert audit_status({"score": 100, "findings": []}, 90) == "PASS"


def test_check_tier0_status_mapping() -> None:
    assert check_status(check_contract(VALID, tier="0")) == "PASS"
    assert check_status(check_contract(INVALID, tier="0")) == "FAIL"

    soft = CheckReport(
        contract_path="contract.yaml",
        tier=CheckTier.STRUCTURAL,
        tier_note=None,
        valid=True,
        validation_errors=(),
        warnings=(
            LintWarning(
                rule_id="AC101",
                title="soft warning",
                message="informational",
                severity="warning",
            ),
        ),
    )
    assert check_status(soft) == "WARN"


def test_check_tier1_status_mapping() -> None:
    passing = check_contract(
        N8N_CONFORMANT / "contract.yaml",
        tier="1",
        target=N8N_CONFORMANT,
        adapter=N8N_TIER1(),
    )
    warning = check_contract(
        LANGGRAPH_REF / "contract.yaml",
        tier="1",
        target=LANGGRAPH_REF,
        adapter=LANGGRAPH_TIER1(),
    )
    failing = check_contract(
        N8N_FAILING / "contract.yaml",
        tier="1",
        target=N8N_FAILING,
        adapter=N8N_TIER1(),
    )

    assert check_status(passing) == "PASS"
    assert check_status(warning) == "WARN"
    assert check_status(failing) == "FAIL"


def test_check_tier2_is_schema_only_and_cli_refuses_loudly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(TierNotImplementedError):
        resolve_tier("2")

    report = UnifiedReport(
        mode="check-tier2",
        status="PASS",
        subject="contract.yaml",
        summary={"tier": 2},
        findings=(),
        data={"tier": 2},
    )
    _validator().validate(report.to_dict())

    code, out, err = _run_cli(
        monkeypatch, capsys, "check", VALID, "--tier", "2", "--unified"
    )
    assert code == 2
    assert out == ""
    assert "not implemented" in err


def test_eval_status_mapping() -> None:
    result = run_eval_file(GOLDEN_EVAL)
    assert eval_status(result) == "WARN"
    assert eval_status(dataclasses.replace(result, expected_ok=False)) == "FAIL"


# ---------------------------------------------------------------------------
# Finding normalization and ordering (Task C-5)
# ---------------------------------------------------------------------------


def test_audit_findings_normalize_to_the_shared_record() -> None:
    payload = _synthetic_audit_report().to_dict()
    unified = from_audit_report(payload, subject=".", status="WARN")

    (finding,) = unified.findings
    assert finding.to_dict() == {
        "id": "AU-NET-002",
        "severity": "medium",
        "title": "outbound network calls in source",
        "message": "synthetic detail",
        "path": "src/foo/client.py",
        "node_id": "",
    }


def test_unknown_audit_severity_normalizes_to_info() -> None:
    payload = {
        "target": ".",
        "score": 99,
        "band": "Shielded",
        "stats": {"files_scanned": 1, "files_skipped": 0, "findings": {}},
        "findings": [
            {
                "rule_id": "AU-X-001",
                "severity": "weird",
                "title": "odd",
                "detail": "",
                "path": "x.py",
                "scored": True,
            }
        ],
        "draft_available": True,
        "packs_suggested": [],
    }
    (finding,) = from_audit_report(payload, subject=".", status="WARN").findings
    assert finding.severity == "info"


def test_acxxx_findings_normalize_to_high_and_low() -> None:
    unified = _tier0(INVALID)

    assert unified.status == "FAIL"
    schema_errors = [f for f in unified.findings if f.id == "AC000"]
    assert schema_errors
    assert {f.severity for f in schema_errors} == {"high"}
    assert schema_errors[0].title == "Contract schema error"
    assert schema_errors[0].path == str(INVALID)


def test_t1xx_findings_normalize_with_node_ids() -> None:
    warning = _tier1(LANGGRAPH_REF, LANGGRAPH_TIER1)
    assert {f.id for f in warning.findings} == {"T103"}
    assert {f.severity for f in warning.findings} == {"low"}

    failing = _tier1(N8N_FAILING, N8N_TIER1)
    assert {f.id for f in failing.findings} == {"T101"}
    assert {f.severity for f in failing.findings} == {"high"}
    assert any(f.node_id for f in failing.findings)


def test_eval_warnings_normalize_to_info() -> None:
    result = dataclasses.replace(
        run_eval_file(GOLDEN_EVAL),
        warnings=("step 1 'db:write': non-scyvera exception (RuntimeError)",),
    )
    unified = from_eval_result(result)

    (finding,) = unified.findings
    assert finding.id == "EVAL"
    assert finding.severity == "info"
    assert finding.title == "Eval warning"
    assert "RuntimeError" in finding.message


def test_findings_are_ordered_by_severity_id_and_path() -> None:
    unified = UnifiedReport(
        mode="audit",
        status="WARN",
        subject=".",
        summary={},
        findings=(
            UnifiedFinding("Z", "low", "t", "m", "z.py"),
            UnifiedFinding("B", "high", "t", "m", "b.py"),
            UnifiedFinding("A", "high", "t", "m", "a.py"),
            UnifiedFinding("A", "critical", "t", "m", "c.py"),
        ),
        data={},
    )
    assert [(f.severity, f.id, f.path) for f in unified.findings] == [
        ("critical", "A", "c.py"),
        ("high", "A", "a.py"),
        ("high", "B", "b.py"),
        ("low", "Z", "z.py"),
    ]


# ---------------------------------------------------------------------------
# Byte identity of the published serializers (Task C-6)
# ---------------------------------------------------------------------------


def test_audit_json_bytes_are_pinned() -> None:
    report = _synthetic_audit_report()
    assert hashlib.sha256(report.to_json().encode("utf-8")).hexdigest() == (
        AUDIT_JSON_SHA256
    )
    assert set(report.to_dict()) == {
        "report_version",
        "target",
        "score",
        "band",
        "stats",
        "findings",
        "draft_available",
        "packs_suggested",
    }


def test_check_render_bytes_are_pinned() -> None:
    assert render_check(check_contract(VALID_REL, tier="0")) == CHECK_RENDER


def test_eval_result_json_bytes_are_pinned() -> None:
    result = run_eval_file(GOLDEN_EVAL)
    assert hashlib.sha256(result.to_json().encode("utf-8")).hexdigest() == (
        EVAL_JSON_SHA256
    )
    assert set(result.to_dict()) == {
        "version",
        "name",
        "total",
        "axes",
        "expected_ok",
        "warnings",
        "trace",
    }


def test_audit_cli_json_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = scan_tree(AUDIT_CLEAN_REL)
    code, out, err = _run_cli(
        monkeypatch, capsys, "audit", AUDIT_CLEAN_REL, "--json"
    )
    assert code == 0
    assert err == ""
    assert out == report.to_json() + "\n"


# ---------------------------------------------------------------------------
# CLI matrix (Task C-7)
# ---------------------------------------------------------------------------


def test_cli_eval_human_output_and_exit_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _run_cli(monkeypatch, capsys, "eval", GOLDEN_EVAL)

    assert code == 0
    assert err == ""
    assert "WARN  refund-agent" in out
    assert "total: 75.0/100" in out
    assert "constraints: 0.0" in out
    assert "approval: 1.0" in out
    assert "recovery: 1.0" in out
    assert "replay: 1.0" in out
    assert "trace: 4 entries" in out


def test_cli_eval_json_validates_against_the_schema(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _run_cli(
        monkeypatch, capsys, "eval", GOLDEN_EVAL, "--json"
    )

    assert code == 0
    assert err == ""
    payload = json.loads(out)
    _validator().validate(payload)
    assert payload["mode"] == "eval"
    assert payload["status"] == "WARN"
    assert payload["summary"]["total"] == 75.0
    assert payload["summary"]["axes"] == {
        "constraints": 0.0,
        "approval": 1.0,
        "recovery": 1.0,
        "replay": 1.0,
    }


def test_cli_eval_failure_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    for name in ("contract.yaml", "agent_eval_fixture.py"):
        shutil.copy(GOLDEN_EVAL.parent / name, tmp_path / name)
    payload = yaml.safe_load(GOLDEN_EVAL.read_text(encoding="utf-8"))
    payload["expected_trace"]["decisions"] = ["ALLOWED", "ALLOWED", "ALLOWED", "ALLOWED"]
    case = tmp_path / "mismatch.eval.yaml"
    case.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    code, out, _ = _run_cli(monkeypatch, capsys, "eval", case)
    assert code == 1
    assert "FAIL  refund-agent" in out


def test_cli_eval_missing_case_exits_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, out, err = _run_cli(
        monkeypatch, capsys, "eval", tmp_path / "missing.eval.yaml"
    )
    assert code == 2
    assert out == ""
    assert "cannot read eval case" in err


def test_cli_check_unified_is_schema_valid(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _run_cli(
        monkeypatch, capsys, "check", VALID, "--tier", "0", "--unified"
    )
    assert code == 0
    assert err == ""
    payload = json.loads(out)
    _validator().validate(payload)
    assert payload["mode"] == "check-tier0"
    assert payload["status"] == "PASS"

    code, out, _ = _run_cli(
        monkeypatch, capsys, "check", INVALID, "--tier", "0", "--unified"
    )
    assert code == 1
    payload = json.loads(out)
    _validator().validate(payload)
    assert payload["status"] == "FAIL"


def test_cli_audit_unified_is_schema_valid(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _run_cli(
        monkeypatch, capsys, "audit", AUDIT_CLEAN_REL, "--unified"
    )
    assert code == 0
    assert err == ""
    payload = json.loads(out)
    _validator().validate(payload)
    assert payload["mode"] == "audit"
    assert payload["status"] == "PASS"
    assert payload["data"]["report_version"] == 1


def test_cli_audit_rejects_json_and_unified_together(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _run_cli(
        monkeypatch, capsys, "audit", AUDIT_CLEAN_REL, "--json", "--unified"
    )
    assert code == 2
    assert out == ""
    assert "mutually exclusive" in err
