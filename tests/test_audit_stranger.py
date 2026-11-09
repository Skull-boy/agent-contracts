"""Stranger-test hardening regressions (roadmap R1).

Covers the four cold-run failures the roadmap identified:

* combined imports (``import os, requests``) must be detected;
* agent/ML SDK imports must identify the exact library;
* hardcoded credentials in source files must be reported by AU-SECRET-001;
* governance status must be honest in the human render and the unified
  envelope without moving the published ``--json`` bytes.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest
from jsonschema import Draft202012Validator

from scyvera.audit import (
    governance_report,
    governance_status,
    scan_tree,
    unify_audit_report,
)
from scyvera.audit_rules import RULES
from scyvera.cli import main
from scyvera.report import render_report
from scyvera.unified import load_report_schema


ROOT = Path(__file__).resolve().parent.parent
STRANGER = ROOT / "tests" / "fixtures" / "stranger"

AUDIT_JSON_KEYS = {
    "report_version",
    "target",
    "score",
    "band",
    "stats",
    "findings",
    "draft_available",
    "packs_suggested",
}

# Token literals are assembled at runtime so this test module does not itself
# contain a contiguous credential-like literal (the repository is dogfooded by
# the same rule set).
GITHUB_TOKEN = "ghp_" + "aBcDeFgHiJkLmNoPqRsTuVwXyZ012345"
WANDB_TOKEN = "wb_" + "aBcDeFgHiJkLmNoPqRsTuVwXyZ012345"
OPENAI_TOKEN = "sk-proj-" + "a1b2c3d4e5f6g7h8i9j0k1l2"


def _assignment(name: str, value: str) -> str:
    return f'{name} = "{value}"'


def _rule(rule_id: str):
    return next(rule for rule in RULES if rule.rule_id == rule_id)


def _run_cli(monkeypatch: pytest.MonkeyPatch, capsys, *argv: object):
    monkeypatch.setattr(sys, "argv", ["scyvera", *(str(item) for item in argv)])
    code = main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _validator() -> Draft202012Validator:
    schema = load_report_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


# ---------------------------------------------------------------------------
# Combined-import network detection (failure a)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    ["import os, requests", "import requests, os", "import sys, openai"],
)
def test_combined_import_matches_regardless_of_position(line: str) -> None:
    findings = _rule("AU-NET-002").scan("src/app.py", line + "\n", "app.py")

    assert len(findings) == 1
    assert findings[0].rule_id == "AU-NET-002"
    assert findings[0].line == 1


def test_single_library_import_and_fetch_still_match() -> None:
    import_findings = _rule("AU-NET-002").scan(
        "src/app.py", "from requests import get\n", "app.py"
    )
    fetch_findings = _rule("AU-NET-002").scan(
        "src/app.js", "const r = await " + "fetch" + "(url);\n", "app.js"
    )

    assert len(import_findings) == 1
    assert len(fetch_findings) == 1
    assert "'fetch'" in fetch_findings[0].detail


def test_combined_import_fixture_scores_as_a_finding(tmp_path: Path) -> None:
    (tmp_path / "flask_app.py").write_text(
        "import os, requests\n\nrequests.post('https://api.github.com')\n",
        encoding="utf-8",
    )

    report = scan_tree(tmp_path)

    assert [finding.rule_id for finding in report.findings] == ["AU-NET-002"]
    assert report.findings[0].scored is True
    assert report.score < 100


# ---------------------------------------------------------------------------
# Agent/ML library identity (failure c)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "library", "permission"),
    [
        ("agent_client.py", "openai", "network:egress:api_openai_com"),
        ("hf_client.py", "huggingface_hub", "network:egress:huggingface_co"),
        ("wandb_train.py", "wandb", "network:egress:api_wandb_ai"),
    ],
)
def test_agent_library_is_named_in_the_finding(
    filename: str, library: str, permission: str
) -> None:
    report = scan_tree(STRANGER / filename)
    findings = [
        finding
        for finding in report.findings
        if finding.rule_id == "AU-NET-002"
    ]

    assert len(findings) == 1
    finding = findings[0]
    assert f"'{library}'" in finding.detail
    assert permission in finding.detail
    assert finding.suggestion["permissions"] == [permission]
    assert finding.suggestion["capabilities"][0]["description"].endswith(library)


def test_google_genai_is_detected_without_flagging_google_root() -> None:
    rule = _rule("AU-NET-002")

    assert rule.scan(
        "src/app.py", "from google.genai import types\n", "app.py"
    )
    assert rule.scan(
        "src/app.py", "from google.protobuf import text_format\n", "app.py"
    ) == []


# ---------------------------------------------------------------------------
# AU-SECRET-001 (failure b)
# ---------------------------------------------------------------------------


def test_hardcoded_credentials_are_found_in_four_languages() -> None:
    report = scan_tree(STRANGER)
    secrets = [
        finding
        for finding in report.findings
        if finding.rule_id == "AU-SECRET-001"
    ]

    assert {Path(finding.path).suffix for finding in secrets} >= {
        ".py",
        ".js",
        ".go",
        ".rs",
    }
    assert all(finding.severity == "high" for finding in secrets)
    assert all(finding.scored is False for finding in secrets)
    # Quarantined fixture findings stay out of the score and scored stats, but
    # remain visible in the report and its quarantine count.
    assert report.score == 100
    assert report.stats["findings"]["high"] == 0
    assert "quarantined finding(s) not scored" in render_report(report)


def test_value_is_redacted_in_the_finding() -> None:
    report = scan_tree(STRANGER / "web_client.js")
    (finding,) = [
        item
        for item in report.findings
        if item.rule_id == "AU-SECRET-001"
    ]

    assert GITHUB_TOKEN not in finding.detail
    assert "value redacted" in finding.detail
    assert finding.suggestion["permissions"] == ["secrets:read"]
    assert finding.suggestion["approvals"] == [
        {"action": "secrets:read", "required": True}
    ]


@pytest.mark.parametrize(
    "line",
    [
        _assignment("api_key", "short"),
        _assignment("api_key", "a" * 24),
        _assignment("api_key", "test-super-secret-token"),
        'token = "x" * len(secret)',
        "# " + _assignment("api_key", OPENAI_TOKEN),
        _assignment("payload", "abcdefghijklmnopqrstuvwxyz"),
    ],
)
def test_secret_allowlist_and_value_floor(line: str) -> None:
    findings = _rule("AU-SECRET-001").scan("app.py", line + "\n", "app.py")

    assert findings == []


def test_provider_prefix_is_caught_without_a_credential_name() -> None:
    findings = _rule("AU-SECRET-001").scan(
        "app.py",
        f'wandb.login(key="{WANDB_TOKEN}")\n',
        "app.py",
    )

    assert len(findings) == 1
    assert "'token'" in findings[0].detail


# ---------------------------------------------------------------------------
# Governance status (failure d)
# ---------------------------------------------------------------------------


def _payload(target: Path) -> dict:
    return {
        "target": str(target),
        "score": 100,
        "band": "Shielded",
        "stats": {"files_scanned": 1, "files_skipped": 0, "findings": {}},
        "findings": [],
    }


def test_ungoverned_render_carries_banner_and_hint(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("import json\n", encoding="utf-8")
    report = scan_tree(tmp_path)

    text = render_report(report)

    assert report.governance == "ungoverned"
    assert text.splitlines()[0].endswith("(score 100/100) [ungoverned]")
    assert "no contract.yaml found" in text
    assert "'scyvera init'" in text


def test_ungoverned_warn_render_marks_the_header_without_a_second_hint(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text(
        _assignment("token", GITHUB_TOKEN) + "\n",
        encoding="utf-8",
    )
    report = scan_tree(tmp_path)

    text = render_report(report)

    assert text.splitlines()[0].startswith("WARN  ")
    assert text.splitlines()[0].endswith("[ungoverned]")
    assert "no contract.yaml found" not in text


def test_governed_render_is_unchanged(tmp_path: Path) -> None:
    (tmp_path / "contract.yaml").write_text(
        "contract_version: '1.0'\n", encoding="utf-8"
    )
    (tmp_path / "app.py").write_text("import json\n", encoding="utf-8")
    report = scan_tree(tmp_path)

    text = render_report(report)

    assert report.governance == "governed"
    assert "[ungoverned]" not in text
    assert "no contract.yaml found" not in text


def test_governance_detection_is_name_based_and_depth_bounded(
    tmp_path: Path,
) -> None:
    shallow = tmp_path / "repo"
    contract = shallow / "a" / "b" / "c" / "contract.yaml"
    contract.parent.mkdir(parents=True)
    contract.write_text("contract_version: '1.0'\n", encoding="utf-8")

    payload = _payload(shallow)
    assert governance_status(payload) == "governed"
    assert governance_report(payload) == {
        "status": "governed",
        "contract_path": "a/b/c/contract.yaml",
    }

    nested = tmp_path / "nested"
    too_deep = nested / "a" / "b" / "c" / "d" / "contract.yaml"
    too_deep.parent.mkdir(parents=True)
    too_deep.write_text("contract_version: '1.0'\n", encoding="utf-8")

    assert governance_status(_payload(nested)) == "ungoverned"


def test_governance_detection_honors_skip_dirs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    hidden = repo / ".git" / "contract.yaml"
    hidden.parent.mkdir(parents=True)
    hidden.write_text("contract_version: '1.0'\n", encoding="utf-8")

    assert governance_status(_payload(repo)) == "ungoverned"


def test_unified_summary_carries_governance_additively(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text("import json\n", encoding="utf-8")
    report = scan_tree(tmp_path)
    unified = unify_audit_report(report.to_dict())

    assert unified.summary["governance"] == {
        "status": "ungoverned",
        "contract_path": None,
    }
    _validator().validate(unified.to_dict())

    (tmp_path / "contract.yaml").write_text(
        "contract_version: '1.0'\n", encoding="utf-8"
    )
    governed = unify_audit_report(scan_tree(tmp_path).to_dict())

    assert governed.summary["governance"] == {
        "status": "governed",
        "contract_path": "contract.yaml",
    }
    _validator().validate(governed.to_dict())


def test_audit_json_bytes_exclude_governance(
    monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path
) -> None:
    (tmp_path / "app.py").write_text(
        _assignment("token", GITHUB_TOKEN) + "\n",
        encoding="utf-8",
    )
    report = scan_tree(tmp_path)

    payload = report.to_dict()
    assert set(payload) == AUDIT_JSON_KEYS
    assert "governance" not in payload
    expected = json.dumps(payload, indent=2, ensure_ascii=False)

    code, out, err = _run_cli(
        monkeypatch, capsys, "audit", tmp_path, "--json"
    )

    assert code == 1
    assert err == ""
    assert out == expected + "\n"


# ---------------------------------------------------------------------------
# Exit codes stay constitutional (0 pass/warn, 1 findings, 2 usage)
# ---------------------------------------------------------------------------


def test_ungoverned_with_findings_still_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path
) -> None:
    (tmp_path / "app.py").write_text(
        _assignment("token", GITHUB_TOKEN) + "\n",
        encoding="utf-8",
    )

    code, out, _ = _run_cli(monkeypatch, capsys, "audit", tmp_path)

    assert code == 1
    assert "[ungoverned]" in out


def test_governed_clean_still_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path
) -> None:
    (tmp_path / "contract.yaml").write_text(
        "contract_version: '1.0'\n", encoding="utf-8"
    )
    (tmp_path / "app.py").write_text("import json\n", encoding="utf-8")

    code, out, err = _run_cli(monkeypatch, capsys, "audit", tmp_path)

    assert code == 0
    assert err == ""
    assert "PASS" in out
    assert "[ungoverned]" not in out


# ---------------------------------------------------------------------------
# R1b: BOM handling
# ---------------------------------------------------------------------------

LANGPACK = STRANGER / "langpack"
LANGPACK_WRAPPERS = STRANGER / "langpack_wrappers"


def test_bom_prefixed_combined_import_matches_au_net_002() -> None:
    plain = "import wandb, requests\n"
    rule = _rule("AU-NET-002")

    for text in (plain, "\ufeff" + plain):
        findings = rule.scan("a.py", text, "a.py")
        assert len(findings) == 1
        assert findings[0].line == 1
        assert "'wandb'" in findings[0].detail


def test_trailing_bom_is_stripped_per_line() -> None:
    findings = _rule("AU-NET-002").scan(
        "a.py", "import wandb\ufeff\n", "a.py"
    )

    assert len(findings) == 1
    assert findings[0].line == 1


def test_bom_prefixed_credential_literal_matches_au_secret_001() -> None:
    text = "\ufeff" + _assignment("token", GITHUB_TOKEN) + "\n"

    findings = _rule("AU-SECRET-001").scan("a.py", text, "a.py")

    assert len(findings) == 1
    assert findings[0].line == 1
    assert GITHUB_TOKEN not in findings[0].detail


def test_scan_path_strips_utf8_signature(tmp_path: Path) -> None:
    (tmp_path / "bom.py").write_text(
        "import wandb, requests\n", encoding="utf-8-sig"
    )

    report = scan_tree(tmp_path)

    assert report.stats["files_scanned"] == 1
    assert [finding.rule_id for finding in report.findings] == ["AU-NET-002"]
    assert report.findings[0].scored is True


def test_bom_and_non_bom_findings_are_equivalent() -> None:
    plain = (
        'token = "' + GITHUB_TOKEN + '"\n'
        "import wandb, requests\n"
    )
    rule_ids = ("AU-SECRET-001", "AU-NET-002")
    plain_findings = [
        (finding.rule_id, finding.line, finding.detail)
        for rule_id in rule_ids
        for finding in _rule(rule_id).scan("a.py", plain, "a.py")
    ]
    bom_findings = [
        (finding.rule_id, finding.line, finding.detail)
        for rule_id in rule_ids
        for finding in _rule(rule_id).scan("a.py", "\ufeff" + plain, "a.py")
    ]

    assert bom_findings == plain_findings


def test_utf16_file_is_still_skipped_as_binary(tmp_path: Path) -> None:
    (tmp_path / "utf16.py").write_bytes(
        "import wandb, requests\n".encode("utf-16")
    )

    report = scan_tree(tmp_path)

    assert report.findings == ()
    assert report.stats["files_scanned"] == 0
    assert report.stats["files_skipped"] == 1


# ---------------------------------------------------------------------------
# R1b: multi-language pattern pack
# ---------------------------------------------------------------------------

LANGPACK_EXPECTED = {
    ("Client.cs", 5),
    ("client.c", 5),
    ("client.go", 5),
    ("client.java", 1),
    ("client.js", 1),
    ("client.rs", 2),
}


def test_language_pack_produces_exactly_six_network_findings() -> None:
    report = scan_tree(LANGPACK)

    assert len(report.findings) == 6
    assert {
        (finding.path, finding.line) for finding in report.findings
    } == LANGPACK_EXPECTED
    assert all(
        finding.rule_id == "AU-NET-002"
        and finding.severity == "medium"
        and finding.scored is False
        for finding in report.findings
    )


@pytest.mark.parametrize(
    ("filename", "library"),
    [
        ("client.go", "net/http"),
        ("client.java", "java.net.http"),
        ("client.rs", "reqwest"),
        ("client.c", "popen"),
        ("Client.cs", "HttpClient"),
        ("client.js", "axios"),
    ],
)
def test_language_pack_names_the_client(
    filename: str, library: str
) -> None:
    report = scan_tree(LANGPACK / filename)
    (finding,) = [
        item
        for item in report.findings
        if item.rule_id == "AU-NET-002"
    ]

    assert f"'{library}'" in finding.detail
    assert finding.suggestion["permissions"][0].startswith(
        "network:egress:"
    )
    assert finding.suggestion["capabilities"][0]["name"] == "outbound_network"


def test_wrapper_aware_shell_rules_reach_source_files() -> None:
    findings = scan_tree(LANGPACK_WRAPPERS).findings

    assert {
        (finding.rule_id, finding.path, finding.line)
        for finding in findings
        if finding.rule_id in ("AU-NET-001", "AU-SH-001", "AU-GIT-001")
    } == {
        ("AU-NET-001", "install.c", 4),
        ("AU-SH-001", "delete.py", 3),
        ("AU-GIT-001", "force.js", 3),
    }
    assert all(finding.scored is False for finding in findings)


@pytest.mark.parametrize(
    ("filename", "statement"),
    [
        (
            "app.go",
            _assignment("key", GITHUB_TOKEN).replace(" = ", " := ", 1),
        ),
        (
            "App.java",
            _assignment("String TOKEN", GITHUB_TOKEN) + ";",
        ),
        (
            "app.rs",
            "let " + _assignment("api_key", GITHUB_TOKEN) + ";",
        ),
        (
            "App.cs",
            "var " + _assignment("apiKey", GITHUB_TOKEN) + ";",
        ),
        (
            "app.js",
            "const " + _assignment("TOKEN", GITHUB_TOKEN) + ";",
        ),
        (
            "app.c",
            "char *" + _assignment("token", GITHUB_TOKEN) + ";",
        ),
    ],
)
def test_source_secret_assignments_generalize_across_languages(
    filename: str, statement: str
) -> None:
    findings = _rule("AU-SECRET-001").scan(
        filename, statement + "\n", filename
    )

    assert len(findings) == 1
    assert findings[0].severity == "high"


def test_source_secret_flags_bare_literal_passing() -> None:
    statement = 'setApiKey("' + GITHUB_TOKEN + '")'

    findings = _rule("AU-SECRET-001").scan(
        "app.py", statement + "\n", "app.py"
    )

    assert len(findings) == 1
    assert "'setApiKey'" in findings[0].detail


def test_language_pack_is_deterministic() -> None:
    first = scan_tree(LANGPACK)
    second = scan_tree(LANGPACK)

    assert first.to_dict() == second.to_dict()
    assert first.to_json() == second.to_json()


def test_language_coverage_doc_states_the_honest_limit() -> None:
    text = (ROOT / "docs" / "language-coverage.md").read_text(
        encoding="utf-8"
    )

    assert (
        "pattern-level, review-grade coverage — not AST or conformance-grade"
        in text
    )
