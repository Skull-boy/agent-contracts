"""Tests for the M2.0a audit scan engine (RFC 0004 §2–§4, §7)."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from scyvera.audit import AuditReport, SymlinkTargetError, scan_tree
from scyvera.audit_rules import RULES, SEVERITY_WEIGHTS, Finding
from scyvera.cli import main


ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "fixtures" / "audit"
POSITIVE = CORPUS / "positive"
NEGATIVE = CORPUS / "negative"

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


POSITIVE_CASES = [
    ("AU-ENV-001", "medium", POSITIVE / ".env"),
    ("AU-ENV-002", "critical", POSITIVE / ".env"),
    ("AU-SH-001", "critical", POSITIVE / "scripts" / "clean.sh"),
    ("AU-SH-001", "critical", POSITIVE / "scripts" / "cleanup.ps1"),
    ("AU-GIT-001", "high", POSITIVE / "scripts" / "release.sh"),
    ("AU-NET-001", "critical", POSITIVE / ".github" / "workflows" / "install.yml"),
    ("AU-NET-002", "medium", POSITIVE / "src" / "client.py"),
    ("AU-CI-001", "high", POSITIVE / ".github" / "workflows" / "write-all.yml"),
    ("AU-CI-002", "high", POSITIVE / ".github" / "workflows" / "publish.yml"),
    ("AU-DOC-001", "high", POSITIVE / "Dockerfile"),
    ("AU-N8N-001", "medium", POSITIVE / "automation" / "workflow.json"),
    ("AU-DEP-001", "low", POSITIVE / "requirements.txt"),
]


NEGATIVE_CASES = [
    ("AU-ENV-001", NEGATIVE / "settings.yaml"),
    ("AU-ENV-002", NEGATIVE / "settings.yaml"),
    ("AU-SH-001", NEGATIVE / "scripts" / "clean-safe.sh"),
    ("AU-SH-001", NEGATIVE / "scripts" / "cleanup-safe.ps1"),
    ("AU-GIT-001", NEGATIVE / "scripts" / "release-safe.sh"),
    ("AU-NET-001", NEGATIVE / ".github" / "workflows" / "verify.yml"),
    ("AU-NET-002", NEGATIVE / "src" / "offline.py"),
    ("AU-CI-001", NEGATIVE / ".github" / "workflows" / "read-all.yml"),
    ("AU-CI-002", NEGATIVE / ".github" / "workflows" / "build.yml"),
    ("AU-DOC-001", NEGATIVE / "Dockerfile.safe"),
    ("AU-N8N-001", NEGATIVE / "automation" / "workflow-offline.json"),
    ("AU-DEP-001", NEGATIVE / "requirements-pinned.txt"),
]


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat = path.stat()
            snapshot[path.relative_to(root).as_posix()] = (
                stat.st_size,
                stat.st_mtime_ns,
            )
    return snapshot


def test_finding_is_frozen():
    finding = Finding(
        rule_id="AU-ENV-001",
        severity="medium",
        title="title",
        detail="detail",
        path=".env",
        line=None,
        suggestion={},
    )

    with pytest.raises(FrozenInstanceError):
        finding.severity = "low"  # type: ignore[misc]


def test_severity_weights_match_rfc():
    assert SEVERITY_WEIGHTS == {
        "critical": 15,
        "high": 8,
        "medium": 3,
        "low": 1,
    }


def test_registry_is_flat_and_complete():
    assert [rule.rule_id for rule in RULES] == [
        "AU-ENV-001",
        "AU-ENV-002",
        "AU-SH-001",
        "AU-GIT-001",
        "AU-NET-001",
        "AU-NET-002",
        "AU-CI-001",
        "AU-CI-002",
        "AU-DOC-001",
        "AU-N8N-001",
        "AU-DEP-001",
    ]


def test_rules_are_pure_callables():
    for rule in RULES:
        assert rule("empty.txt", "", "empty.txt") == []


@pytest.mark.parametrize(
    ("rule_id", "severity", "fixture"),
    POSITIVE_CASES,
    ids=[f"{rule_id}-{fixture.name}" for rule_id, _, fixture in POSITIVE_CASES],
)
def test_positive_fixture_reports_rule(rule_id, severity, fixture):
    assert fixture.is_file()

    report = scan_tree(fixture)
    matches = [finding for finding in report.findings if finding.rule_id == rule_id]

    assert matches, [finding.rule_id for finding in report.findings]
    assert all(finding.severity == severity for finding in matches)
    assert all(finding.suggestion for finding in matches)
    assert all("/" in finding.path or "\\" not in finding.path for finding in matches)


@pytest.mark.parametrize(
    ("rule_id", "fixture"),
    NEGATIVE_CASES,
    ids=[f"{rule_id}-{fixture.name}" for rule_id, fixture in NEGATIVE_CASES],
)
def test_negative_fixture_is_clean(rule_id, fixture):
    assert fixture.is_file()

    report = scan_tree(fixture)

    assert report.findings == ()
    assert report.score == 100
    assert report.band == "Shielded"


def test_negative_corpus_is_clean():
    report = scan_tree(NEGATIVE)

    assert report.findings == ()
    assert report.score == 100
    assert report.band == "Shielded"
    assert report.stats["findings"] == {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
    }


def test_corpus_score_counts_and_stats():
    report = scan_tree(CORPUS)

    assert report.report_version == 1
    assert len(report.findings) == 12
    assert all(finding.scored is False for finding in report.findings)
    assert report.score == 100
    assert report.band == "Shielded"
    assert report.stats["files_scanned"] == 22
    assert report.stats["files_skipped"] == 0
    assert report.stats["findings"] == {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
    }


def test_repeated_rule_load_stops_after_third_occurrence(tmp_path):
    three = tmp_path / "three"
    three.mkdir()
    for index in range(3):
        (three / f"client_{index}.py").write_text(
            "import " + "requests\n",
            encoding="utf-8",
        )

    five = tmp_path / "five"
    five.mkdir()
    for index in range(5):
        (five / f"client_{index}.py").write_text(
            "import " + "requests\n",
            encoding="utf-8",
        )

    three_report = scan_tree(three)
    five_report = scan_tree(five)

    assert [finding.rule_id for finding in three_report.findings] == [
        "AU-NET-002",
        "AU-NET-002",
        "AU-NET-002",
    ]
    assert len(five_report.findings) == 5
    assert all(finding.scored for finding in five_report.findings)
    # base 3 * (1.00 + 0.25 + 0.10) = 4.05 -> ceil 5 -> score 95.
    assert three_report.score == 95
    assert five_report.score == 95


def test_findings_are_ordered_deterministically():
    report = scan_tree(CORPUS)

    ordered_keys = [
        (SEVERITY_RANK[finding.severity], finding.rule_id, finding.path)
        for finding in report.findings
    ]
    assert ordered_keys == sorted(ordered_keys)

    assert [finding.rule_id for finding in report.findings] == [
        "AU-ENV-002",
        "AU-NET-001",
        "AU-SH-001",
        "AU-SH-001",
        "AU-CI-001",
        "AU-CI-002",
        "AU-DOC-001",
        "AU-GIT-001",
        "AU-ENV-001",
        "AU-N8N-001",
        "AU-NET-002",
        "AU-DEP-001",
    ]


def test_report_shape_matches_rfc_0004():
    report = scan_tree(CORPUS)
    data = report.to_dict()

    assert list(data) == [
        "report_version",
        "target",
        "score",
        "band",
        "stats",
        "findings",
        "draft_available",
        "packs_suggested",
    ]
    assert list(data["stats"]) == ["files_scanned", "files_skipped", "findings"]
    assert list(data["findings"][0]) == [
        "rule_id",
        "severity",
        "title",
        "detail",
        "path",
        "line",
        "suggestion",
        "scored",
    ]
    assert "generated_at" not in data
    assert data["target"] == CORPUS.as_posix()
    # Every finding in the corpus is a quarantined fixture, so nothing is
    # actionable: no contract draft and no policy pack are suggested.
    assert data["draft_available"] is False
    assert data["packs_suggested"] == []


def test_scan_is_byte_identical_across_runs():
    first = scan_tree(CORPUS).to_json()
    second = scan_tree(CORPUS).to_json()

    assert first == second


def test_scan_does_not_write_to_target():
    before = _snapshot(CORPUS)

    scan_tree(CORPUS)
    scan_tree(CORPUS)

    assert _snapshot(CORPUS) == before


def test_git_status_unchanged_after_scan():
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not available")

    def status() -> str:
        result = subprocess.run(
            [
                git,
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                "tests/fixtures/audit",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    before = status()
    scan_tree(CORPUS)
    after = status()

    assert after == before


def test_paths_are_normalized_to_forward_slashes():
    report = scan_tree(CORPUS)

    assert report.findings
    assert all("\\" not in finding.path for finding in report.findings)


def test_skip_list_size_cap_and_binary_sniff(tmp_path):
    target = tmp_path / "repo"
    target.mkdir()

    (target / "app.py").write_text("import " + "requests\n", encoding="utf-8")

    skip_dir = target / ".git"
    skip_dir.mkdir()
    (skip_dir / "leak.py").write_text("import " + "requests\n", encoding="utf-8")

    (target / "binary.bin").write_bytes(b"\x00import requests\n")
    (target / "huge.py").write_text(
        "import " + "requests\n" + "#" * (1024 * 1024),
        encoding="utf-8",
    )

    report = scan_tree(target)

    assert report.stats["files_scanned"] == 1
    assert report.stats["files_skipped"] == 2
    assert [finding.path for finding in report.findings] == ["app.py"]
    assert [finding.rule_id for finding in report.findings] == ["AU-NET-002"]


def test_symlinked_target_is_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "app.py").write_text("import " + "requests\n", encoding="utf-8")

    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this platform")

    with pytest.raises(SymlinkTargetError):
        scan_tree(link)


def test_symlinked_target_is_refused_before_traversal(monkeypatch, tmp_path):
    target = tmp_path / "repo"
    target.mkdir()

    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda self: self == target,
    )

    with pytest.raises(SymlinkTargetError):
        scan_tree(target)


def test_cli_audit_json_is_deterministic(monkeypatch, capsys):
    outputs: list[str] = []
    exit_codes: list[int] = []

    for _ in range(2):
        monkeypatch.setattr(
            "sys.argv",
            ["scyvera", "audit", str(CORPUS), "--json"],
        )
        exit_codes.append(main())
        outputs.append(capsys.readouterr().out)

    # Fixture-only findings are quarantined, so the scan is a PASS.
    assert exit_codes == [0, 0]
    assert outputs[0] == outputs[1]

    data = json.loads(outputs[0])
    assert data["report_version"] == 1
    assert data["score"] == 100
    assert data["band"] == "Shielded"
    assert len(data["findings"]) == 12
    assert all(finding["scored"] is False for finding in data["findings"])


def test_cli_audit_quarantined_only_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        ["scyvera", "audit", str(POSITIVE)],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "PASS" in output
    assert "12 quarantined finding(s) not scored" in output
    assert "score 100/100" in output


def test_cli_audit_scored_finding_warns_and_exits_one(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "client.py").write_text(
        "import " + "requests\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "sys.argv",
        ["scyvera", "audit", str(tmp_path)],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "WARN" in output
    assert "Blast Radius: 97/100 (Shielded)" in output
    assert "[AU-NET-002]" in output
    assert "quarantined" not in output


def test_cli_audit_clean_path_returns_zero(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        ["scyvera", "audit", str(NEGATIVE)],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "PASS" in output
    assert "score 100/100" in output


def test_cli_audit_missing_path_returns_two(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        ["scyvera", "audit", str(CORPUS / "does-not-exist")],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 2
    assert "ERROR" in output
    assert "file not found" in output


def test_cli_audit_symlink_target_returns_two(tmp_path, monkeypatch, capsys):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this platform")

    monkeypatch.setattr(
        "sys.argv",
        ["scyvera", "audit", str(link)],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 2
    assert "ERROR" in output
    assert "symlink" in output.lower()


def test_audit_report_is_read_only_dataclass():
    report = scan_tree(NEGATIVE)

    assert isinstance(report, AuditReport)
    assert isinstance(report.findings, tuple)
    assert report.findings == ()
