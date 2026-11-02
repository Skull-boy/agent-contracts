"""Tests for RFC 0004 M2.0c contract draft generation (§5, §10.1).

The milestone's hard QA rule lives here: every fixture corpus is copied out of
``tests/fixtures`` (a direct fixture scan is quarantined wholesale by
M2.0a.1), drafted, written, and then re-read from disk and re-validated with
both quality gates. The generator cannot drift from the v1.1 schema without
this sweep failing before users see it.

Nothing is written into the repository tree: scans target ``tmp_path`` copies
and drafts are written under ``tmp_path`` only.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from typing import Any, Mapping

import pytest
import yaml

from scyvera.audit import AuditReport, scan_tree
from scyvera.audit_rules import Finding
from scyvera.cli import main
from scyvera.generate import DraftContract, build_draft, write_draft
from scyvera.linter import lint_contract
from scyvera.validator import validate_contract


ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "fixtures" / "audit"
POSITIVE = CORPUS / "positive"
NEGATIVE = CORPUS / "negative"
CORPUS_CASES = sorted(
    (path for path in CORPUS.iterdir() if path.is_dir()),
    key=lambda path: path.name,
)


def _scored_copy(tmp_path: Path, corpus: Path) -> tuple[Path, AuditReport]:
    """Copy ``corpus`` outside ``tests/fixtures`` so its findings are scored."""
    target = tmp_path / corpus.name
    shutil.copytree(corpus, target)
    return target, scan_tree(target)


def _report(*findings: Finding, target: str = "sample-repo") -> AuditReport:
    """Build a minimal in-memory report around ``findings``."""
    return AuditReport(
        report_version=1,
        target=target,
        score=100,
        band="Shielded",
        stats={},
        findings=tuple(findings),
        draft_available=bool(findings),
        packs_suggested=(),
    )


def _finding(
    severity: str,
    suggestion: Mapping[str, Any],
    *,
    scored: bool = True,
    rule_id: str = "AU-TEST-001",
) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=severity,
        title="test finding",
        detail="synthetic test finding",
        path="src/example.py",
        line=1,
        suggestion=suggestion,
        scored=scored,
    )


def _run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> tuple[int, str, str]:
    """Run the in-process CLI and return ``(exit_code, stdout, stderr)``."""
    monkeypatch.setattr(sys, "argv", ["scyvera", *argv])
    exit_code = main()
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


# ---------------------------------------------------------------------------
# Schema-accuracy dogfood sweep (RFC 0004 §5 hard QA rule, §7 check 5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corpus", CORPUS_CASES, ids=lambda path: path.name)
def test_every_fixture_draft_validates_and_lints_clean(
    tmp_path: Path,
    corpus: Path,
) -> None:
    target, report = _scored_copy(tmp_path, corpus)
    assert target != corpus

    draft_path = tmp_path / "draft.yaml"
    write_draft(build_draft(report), draft_path)

    # Validate the file on disk, not the in-memory mapping: this catches
    # emission bugs that a mapping-only assertion would miss.
    validation = validate_contract(draft_path)
    assert validation.valid, (
        f"{corpus.name} draft failed validation: "
        f"{[(error.path, error.message) for error in validation.errors]}"
    )

    lint = lint_contract(draft_path)
    assert lint.valid_structure, f"{corpus.name} draft failed structural lint"
    assert lint.warnings == (), (
        f"{corpus.name} draft emitted lint warnings: "
        f"{[(warning.rule_id, warning.message) for warning in lint.warnings]}"
    )


def test_negative_corpus_draft_is_empty_but_valid(tmp_path: Path) -> None:
    _, report = _scored_copy(tmp_path, NEGATIVE)
    draft = build_draft(report)

    assert draft["system"]["name"] == "negative"
    assert draft["risk"]["level"] == "low"
    for section in (
        "capabilities",
        "resources",
        "permissions",
        "side_effects",
        "approvals",
    ):
        assert draft[section] == [], section

    draft_path = tmp_path / "draft.yaml"
    write_draft(draft, draft_path)
    assert validate_contract(draft_path).valid
    assert lint_contract(draft_path).warnings == ()


# ---------------------------------------------------------------------------
# Draft content: identity, risk, criticality, merging
# ---------------------------------------------------------------------------


def test_system_name_comes_from_the_scanned_directory(tmp_path: Path) -> None:
    _, report = _scored_copy(tmp_path, POSITIVE)
    assert build_draft(report)["system"]["name"] == "positive"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("My Repo", "my-repo"),
        ("ACME_Inc", "acme-inc"),
        ("UPPER", "upper"),
        ("---Weird Name---", "weird-name"),
        ("!!!", "generated-system"),
        ("", "generated-system"),
    ],
)
def test_repo_name_is_sanitized(raw: str, expected: str) -> None:
    draft = build_draft(_report(), repo_name=raw)
    assert draft["system"]["name"] == expected


def test_domain_defaults_to_software_and_can_be_overridden() -> None:
    assert build_draft(_report())["domain"] == "software"
    assert build_draft(_report(), domain="finance")["domain"] == "finance"


def test_risk_level_tracks_worst_scored_severity(tmp_path: Path) -> None:
    _, report = _scored_copy(tmp_path, POSITIVE)
    assert build_draft(report)["risk"]["level"] == "critical"

    assert build_draft(_report())["risk"]["level"] == "low"
    assert (
        build_draft(_report(_finding("medium", {})))["risk"]["level"]
        == "medium"
    )
    assert (
        build_draft(
            _report(_finding("medium", {}), _finding("high", {}))
        )["risk"]["level"]
        == "high"
    )


def test_critical_findings_graft_irreversible_side_effects(
    tmp_path: Path,
) -> None:
    _, report = _scored_copy(tmp_path, POSITIVE)
    draft = build_draft(report)
    effects = {effect["type"]: effect for effect in draft["side_effects"]}

    # Critical-only effects are grafted (RFC 0004 §10.1).
    assert effects["file_delete"]["irreversible"] is True
    assert effects["remote_execution"]["irreversible"] is True
    # High-severity effects never become irreversible.
    assert "irreversible" not in effects["ci_deploy_write"]
    assert "irreversible" not in effects["host_mount"]
    # Medium-severity effects never become irreversible.
    assert "irreversible" not in effects["external_api_write"]


def test_medium_and_high_findings_drop_a_supplied_irreversible_flag() -> None:
    for severity in ("medium", "high"):
        draft = build_draft(
            _report(
                _finding(
                    severity,
                    {
                        "side_effects": [
                            {
                                "type": "file_delete",
                                "resource": "workspace",
                                "irreversible": True,
                            }
                        ]
                    },
                )
            )
        )
        effect = draft["side_effects"][0]
        assert "irreversible" not in effect, severity


def test_critical_findings_force_irreversible_even_when_omitted() -> None:
    draft = build_draft(
        _report(
            _finding(
                "critical",
                {"side_effects": [{"type": "wipe", "resource": "disk"}]},
            )
        )
    )
    assert draft["side_effects"][0]["irreversible"] is True


def test_critical_duplicate_wins_over_noncritical() -> None:
    suggestion = {
        "side_effects": [
            {"type": "remote_execution", "resource": "network"}
        ]
    }
    draft = build_draft(
        _report(
            _finding("medium", suggestion, rule_id="AU-TEST-002"),
            _finding("critical", suggestion, rule_id="AU-TEST-003"),
        )
    )
    assert len(draft["side_effects"]) == 1
    assert draft["side_effects"][0]["irreversible"] is True


def test_repeated_suggestion_deduplicates_structurally() -> None:
    suggestion = {"permissions": ["secrets:read"]}
    draft = build_draft(
        _report(
            _finding("critical", suggestion, rule_id="AU-TEST-001"),
            _finding("critical", suggestion, rule_id="AU-TEST-002"),
            _finding("critical", suggestion, rule_id="AU-TEST-003"),
        )
    )
    assert draft["permissions"] == ["secrets:read"]


def test_merged_sections_sort_deterministically() -> None:
    draft = build_draft(
        _report(
            _finding("medium", {"permissions": ["registry:publish"]}),
            _finding("medium", {"permissions": ["git_ref:write"]}),
            _finding("medium", {"permissions": ["secrets:read"]}),
        )
    )
    assert draft["permissions"] == [
        "git_ref:write",
        "registry:publish",
        "secrets:read",
    ]


def test_quarantined_findings_contribute_nothing(tmp_path: Path) -> None:
    _, report = _scored_copy(tmp_path, POSITIVE)
    # Every finding in a direct fixture scan is quarantined, so the draft is
    # empty even though the report still lists 12 findings.
    direct = scan_tree(POSITIVE)
    assert direct.findings
    assert all(finding.scored is False for finding in direct.findings)

    draft = build_draft(direct)
    assert draft["system"]["name"] == "positive"
    assert draft["risk"]["level"] == "low"
    assert draft["permissions"] == []
    assert draft["side_effects"] == []


def test_capabilities_and_observability_fragments_are_mapped(
    tmp_path: Path,
) -> None:
    _, report = _scored_copy(tmp_path, POSITIVE)
    draft = build_draft(report)

    assert {"name": "outbound_network"} in [
        {"name": item["name"]} for item in draft["capabilities"]
    ]
    assert draft["observability"] == {
        "level": "audit",
        "sinks": ["dependency_audit"],
    }


def test_unsupported_suggestion_keys_are_listed_in_header(
    tmp_path: Path,
) -> None:
    draft = build_draft(
        _report(_finding("low", {"future_section": [{"name": "x"}]}))
    )
    assert draft["permissions"] == []

    draft_path = tmp_path / "draft.yaml"
    write_draft(draft, draft_path)
    header = draft_path.read_text(encoding="ascii").splitlines()[:6]
    assert any("future_section" in line for line in header)


# ---------------------------------------------------------------------------
# YAML quality: deterministic, ASCII-safe, round-trippable, human header
# ---------------------------------------------------------------------------


def test_write_draft_is_deterministic(tmp_path: Path) -> None:
    _, report = _scored_copy(tmp_path, POSITIVE)
    draft = build_draft(report)

    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    write_draft(draft, first)
    write_draft(draft, second)

    assert first.read_bytes() == second.read_bytes()


def test_written_draft_round_trips_through_safe_load(tmp_path: Path) -> None:
    _, report = _scored_copy(tmp_path, POSITIVE)
    draft = build_draft(report)
    draft_path = tmp_path / "draft.yaml"
    write_draft(draft, draft_path)

    loaded = yaml.safe_load(draft_path.read_text(encoding="ascii"))
    assert loaded == dict(draft)
    assert isinstance(loaded, dict)

    # Round-trip a second time: emitted YAML must itself be emitted stably.
    reloaded_path = tmp_path / "reloaded.yaml"
    write_draft(loaded, reloaded_path)
    assert reloaded_path.read_bytes() == draft_path.read_bytes()


def test_written_draft_is_ascii_only(tmp_path: Path) -> None:
    draft = build_draft(
        _report(
            _finding(
                "low",
                {"capabilities": [{"name": "caf\u00e9"}]},
            )
        ),
        repo_name="r\u00e9sum\u00e9",
    )
    draft_path = tmp_path / "draft.yaml"
    write_draft(draft, draft_path)

    raw = draft_path.read_bytes()
    assert all(byte < 128 for byte in raw)
    loaded = yaml.safe_load(raw.decode("ascii"))
    assert loaded["system"]["name"] == "r-sum"


def test_header_is_short_ascii_and_actionable(tmp_path: Path) -> None:
    _, report = _scored_copy(tmp_path, NEGATIVE)
    draft_path = tmp_path / "draft.yaml"
    write_draft(build_draft(report), draft_path)

    lines = draft_path.read_text(encoding="ascii").splitlines()
    header = [line for line in lines if line.startswith("#")]
    assert 3 <= len(header) <= 6
    assert header[0].startswith("# Contract draft generated by `scyvera audit`")
    joined = "\n".join(header)
    assert "scyvera validate" in joined
    assert "scyvera lint" in joined


def test_write_draft_creates_exactly_one_file(tmp_path: Path) -> None:
    _, report = _scored_copy(tmp_path, POSITIVE)
    draft_path = tmp_path / "contract.yaml"
    before = {path.name for path in tmp_path.iterdir()}

    write_draft(build_draft(report), draft_path)

    after = {path.name for path in tmp_path.iterdir()}
    assert after - before == {"contract.yaml"}
    assert draft_path.is_file()


# ---------------------------------------------------------------------------
# CLI matrix (RFC 0004 §5, §9)
# ---------------------------------------------------------------------------


def test_cli_generate_writes_report_and_one_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target, _ = _scored_copy(tmp_path, POSITIVE)
    draft_path = tmp_path / "contract.yaml"
    before = {path.name for path in tmp_path.iterdir()}

    exit_code, out, err = _run(
        monkeypatch,
        capsys,
        ["audit", str(target), "--generate", str(draft_path)],
    )

    # M2.0b exit contract: scored findings warn and exit 1.
    assert exit_code == 1
    assert err == ""
    assert "Blast Radius:" in out
    assert f"Draft contract written to {draft_path}" in out
    assert draft_path.is_file()
    assert {path.name for path in tmp_path.iterdir()} - before == {
        "contract.yaml"
    }


def test_cli_refuses_to_overwrite_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target, _ = _scored_copy(tmp_path, NEGATIVE)
    draft_path = tmp_path / "contract.yaml"
    draft_path.write_text("sentinel\n", encoding="ascii")

    exit_code, out, err = _run(
        monkeypatch,
        capsys,
        ["audit", str(target), "--generate", str(draft_path)],
    )

    assert exit_code == 2
    assert out == ""
    assert err.strip() == (
        f"scyvera audit: error: {draft_path} exists; "
        "pass --force to overwrite"
    )
    assert draft_path.read_text(encoding="ascii") == "sentinel\n"


def test_cli_force_overwrites_existing_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target, _ = _scored_copy(tmp_path, NEGATIVE)
    draft_path = tmp_path / "contract.yaml"
    draft_path.write_text("sentinel\n", encoding="ascii")

    exit_code, out, err = _run(
        monkeypatch,
        capsys,
        ["audit", str(target), "--generate", str(draft_path), "--force"],
    )

    assert exit_code == 0
    assert err == ""
    assert "Draft contract written to" in out
    assert draft_path.read_text(encoding="ascii").startswith(
        "# Contract draft generated by `scyvera audit`."
    )


def test_cli_json_generate_adds_only_draft_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target, report = _scored_copy(tmp_path, POSITIVE)

    plain_exit, plain_out, plain_err = _run(
        monkeypatch,
        capsys,
        ["audit", str(target), "--json"],
    )
    assert plain_exit == 1
    assert plain_err == ""
    plain = json.loads(plain_out)
    assert "draft_path" not in plain

    draft_path = tmp_path / "contract.yaml"
    gen_exit, gen_out, gen_err = _run(
        monkeypatch,
        capsys,
        ["audit", str(target), "--json", "--generate", str(draft_path)],
    )
    assert gen_exit == 1
    assert gen_err == ""
    generated = json.loads(gen_out)

    assert list(generated) == [*plain, "draft_path"]
    assert generated["draft_path"] == str(draft_path)
    assert {
        key: value for key, value in generated.items() if key != "draft_path"
    } == plain
    assert gen_out == json.dumps(generated, indent=2, ensure_ascii=False) + "\n"


def test_cli_json_without_generate_is_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target, report = _scored_copy(tmp_path, POSITIVE)

    exit_code, out, err = _run(
        monkeypatch,
        capsys,
        ["audit", str(target), "--json"],
    )

    assert exit_code == 1
    assert err == ""
    assert out == report.to_json() + "\n"


def test_cli_badge_remains_the_final_line_with_generate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target, _ = _scored_copy(tmp_path, NEGATIVE)
    draft_path = tmp_path / "contract.yaml"

    exit_code, out, err = _run(
        monkeypatch,
        capsys,
        [
            "audit",
            str(target),
            "--generate",
            str(draft_path),
            "--badge",
        ],
    )

    assert exit_code == 0
    assert err == ""
    lines = [line for line in out.splitlines() if line.strip()]
    assert "Draft contract written to" in lines[-2]
    assert lines[-1].startswith("[![Blast Radius:")


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (
            ["--pack", "github-safe"],
            "scyvera audit: error: policy packs ship in a later release; "
            "--pack is not available yet",
        ),
        (
            ["--force"],
            "scyvera audit: error: --force requires --generate",
        ),
        (
            ["--generate", "draft.yml"],
            None,
        ),
    ],
    ids=["pack", "force-without-generate", "yml-extension"],
)
def test_cli_rejects_unsupported_flag_combinations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    expected: str | None,
) -> None:
    target, _ = _scored_copy(tmp_path, NEGATIVE)
    draft_path = tmp_path / "draft.yml"
    resolved = [
        str(draft_path) if value == "draft.yml" else value for value in argv
    ]

    exit_code, out, err = _run(
        monkeypatch,
        capsys,
        ["audit", str(target), *resolved],
    )

    assert exit_code == 2
    assert out == ""
    assert err.count("\n") == 1
    if expected is not None:
        assert err.strip() == expected
    else:
        assert "must use the .yaml extension" in err


def test_cli_generate_failure_does_not_print_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target, _ = _scored_copy(tmp_path, NEGATIVE)
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory\n", encoding="ascii")
    draft_path = blocker / "contract.yaml"

    exit_code, out, err = _run(
        monkeypatch,
        capsys,
        ["audit", str(target), "--generate", str(draft_path)],
    )

    assert exit_code == 2
    assert out == ""
    assert err.startswith(f"scyvera audit: error: cannot write {draft_path}:")
    assert err.count("\n") == 1


def test_draft_contract_exposes_omitted_keys() -> None:
    draft = build_draft(
        _report(_finding("low", {"unsupported": [], "permissions": []}))
    )
    assert isinstance(draft, DraftContract)
    assert draft.omitted_suggestion_keys == ("unsupported",)
