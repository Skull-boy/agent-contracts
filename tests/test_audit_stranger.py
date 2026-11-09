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
