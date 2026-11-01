"""Report-level tests for RFC 0004 M2.0b (§2 layout, §4 badge, §7 checks).

Covers the band-first terminal renderer, the band-only shields.io badge, the
``--fail-under`` CI gate, encoding fallback, and the determinism/no-write
guarantees. Nothing here writes into the repository tree: every scan targets
a fixture corpus or a ``tmp_path`` repository.
"""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Mapping

import pytest

from scyvera.audit import AuditReport, scan_tree
from scyvera.audit_rules import Finding
from scyvera.cli import main
from scyvera.report import BAND_COLORS, render_badge, render_report


ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "fixtures" / "audit"
POSITIVE = CORPUS / "positive"
NEGATIVE = CORPUS / "negative"

EM_DASH = "\u2014"


def _finding(
    rule_id: str,
    severity: str,
    title: str,
    path: str,
    line: int | None = None,
    *,
    scored: bool = True,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=severity,
        title=title,
        detail="synthetic detail",
        path=path,
        line=line,
        suggestion={},
        scored=scored,
    )


def _report(
    findings: tuple[Finding, ...] = (),
    *,
    target: str = ".",
    score: int = 100,
    band: str = "Shielded",
    files_scanned: int = 3,
    file_kinds: Mapping[str, int] | None = None,
) -> AuditReport:
    scored = [finding for finding in findings if finding.scored]
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for finding in scored:
        severity_counts[finding.severity] += 1

    return AuditReport(
        report_version=1,
        target=target,
        score=score,
        band=band,
        stats={
            "files_scanned": files_scanned,
            "files_skipped": 0,
            "findings": severity_counts,
        },
        findings=findings,
        draft_available=bool(scored),
        packs_suggested=("github-safe",) if scored else (),
        file_kinds=file_kinds or {},
    )


def _layout_report() -> AuditReport:
    findings = (
        _finding(
            "AU-NET-002",
            "medium",
            "outbound network calls in source",
            "src/foo/client.py",
        ),
        _finding(
            "AU-SH-001",
            "high",
            "recursive delete in shell script",
            "scripts/clean.sh",
            8,
        ),
        _finding(
            "AU-NET-001",
            "critical",
            "install-script execution",
            ".github/workflows/release.yml",
            52,
        ),
        _finding(
            "AU-NET-001",
            "critical",
            "install-script execution",
            "scripts/install.sh",
            3,
        ),
        _finding(
            "AU-ENV-002",
            "critical",
            "secret committed in env file",
            "tests/fixtures/audit/positive/.env",
            1,
            scored=False,
        ),
    )
    return _report(
        findings,
        target=".",
        score=71,
        band="Exposed",
        files_scanned=214,
        file_kinds={"manifests": 2, "workflows": 3, "source": 41},
    )


def _run_cli(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
) -> tuple[int, str, str]:
    monkeypatch.setattr("sys.argv", ["scyvera", *argv])
    exit_code = main()
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


@pytest.fixture
def findings_repo(tmp_path: Path) -> Path:
    """A repository outside ``tests/fixtures`` with one scored medium finding."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("import " + "requests\n", encoding="utf-8")
    return repo


@pytest.fixture
def clean_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "clean"
    repo.mkdir()
    (repo / "app.py").write_text("print('hello')\n", encoding="utf-8")
    return repo


# --- Terminal renderer (RFC 0004 §2) ---------------------------------------


def test_render_report_is_deterministic() -> None:
    report = _layout_report()

    first = render_report(report)
    second = render_report(report)

    assert first == second, "rendering the same report twice must be identical"


def test_render_report_ignores_input_order() -> None:
    report = _layout_report()
    reversed_report = replace(report, findings=tuple(reversed(report.findings)))

    assert render_report(report) == render_report(reversed_report), (
        "rendered order must come from severity/rule/path, not input order"
    )


def test_render_report_is_band_first_and_aligned() -> None:
    lines = render_report(_layout_report()).splitlines()

    assert lines[0] == "FAIL  .", f"expected FAIL header, got {lines[0]!r}"
    assert lines[1] == "      Blast Radius: 71/100 (Exposed)", (
        f"band line must come second, got {lines[1]!r}"
    )
    assert lines[2] == (
        "      Scanned 214 files "
        "(2 manifests, 3 workflow files, 41 source files)"
    ), f"unexpected scanned line: {lines[2]!r}"

    bracket_columns = {line.index("[AU-") for line in lines if "[AU-" in line}
    assert bracket_columns == {16}, (
        f"rule ids must share one column, got {sorted(bracket_columns)}"
    )


def test_render_report_orders_and_groups_severities() -> None:
    text = render_report(_layout_report())
    lines = text.splitlines()

    critical = next(
        index for index, line in enumerate(lines) if "AU-NET-001" in line
    )
    high = next(index for index, line in enumerate(lines) if "AU-SH-001" in line)
    medium = next(
        index for index, line in enumerate(lines) if "AU-NET-002" in line
    )

    assert critical < high < medium, "findings must be grouped severity-descending"
    assert (
        ".github/workflows/release.yml:52 + 1 more" in text
    ), "identical rule/title findings must collapse with a count"


def test_render_report_omits_quarantined_findings() -> None:
    text = render_report(_layout_report())

    assert "AU-ENV-002" not in text, "quarantined findings must not be rendered"
    assert "tests/fixtures/" not in text, "fixture paths must not leak into output"


def test_render_report_clean_pass_line() -> None:
    rendered = render_report(_report(target="."))

    assert rendered == (
        f"PASS  . {EM_DASH} exploit risk none (score 100/100)"
    ), f"unexpected clean layout: {rendered!r}"


def test_render_report_warns_without_critical_findings() -> None:
    report = _report(
        (_finding("AU-NET-002", "medium", "outbound calls", "src/a.py"),),
        target=".",
        score=97,
    )

    assert render_report(report).startswith("WARN  .")


def test_render_report_never_emits_ansi_escapes() -> None:
    text = render_report(_layout_report())

    assert "\x1b[" not in text, "v1 report output must not contain ANSI escapes"


# --- Encoding fallback (RFC 0004 §2 em dash) --------------------------------


def test_render_report_ascii_fallback_is_encodable() -> None:
    text = render_report(_report(target="."), encoding="ascii")

    assert text == "PASS  . -> exploit risk none (score 100/100)", (
        f"expected ASCII dash fallback, got {text!r}"
    )
    assert text.encode("ascii"), "fallback output must be ASCII-encodable"


def test_render_report_cp437_fallback_is_encodable() -> None:
    text = render_report(_layout_report(), encoding="cp437")

    text.encode("cp437")  # must not raise UnicodeEncodeError


def test_render_report_replaces_unencodable_finding_text() -> None:
    report = _report(
        (_finding("AU-X-001", "low", "arrow \u2192 title", "src/x.py"),),
        target=".",
        score=99,
    )

    text = render_report(report, encoding="ascii")

    text.encode("ascii")  # must not raise UnicodeEncodeError
    assert "arrow ? title" in text, f"expected replacement, got {text!r}"


# --- Badge (RFC 0004 §4) ----------------------------------------------------


@pytest.mark.parametrize(
    ("band", "color"),
    [
        ("Shielded", "green"),
        ("Controlled", "yellow"),
        ("Exposed", "orange"),
        ("Unbounded", "red"),
    ],
)
def test_render_badge_exact_snippet(band: str, color: str) -> None:
    badge = render_badge(_report(band=band, score=73))

    expected = (
        f"[![Blast Radius: {band}]"
        f"(https://img.shields.io/badge/blast%20radius-{band}-{color})]"
        "(scyvera)"
    )
    assert badge == expected, f"unexpected badge for {band}: {badge!r}"
    assert "73" not in badge, "badge must be band-only, never carry the score"


def test_band_colors_match_rfc() -> None:
    assert dict(BAND_COLORS) == {
        "Shielded": "green",
        "Controlled": "yellow",
        "Exposed": "orange",
        "Unbounded": "red",
    }


def test_render_badge_rejects_unknown_band() -> None:
    with pytest.raises(ValueError, match="unknown Blast Radius band"):
        render_badge(_report(band="Mystery"))


# --- CLI exit-code matrix (RFC 0004 §7 check 7) ----------------------------


def test_cli_clean_repo_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_repo: Path,
) -> None:
    code, out, _ = _run_cli(monkeypatch, capsys, "audit", str(clean_repo))

    assert code == 0, f"expected exit 0, got {code}: {out}"
    assert out.startswith("PASS  "), f"expected PASS report, got {out!r}"
    assert "exploit risk none" in out


def test_cli_clean_fixture_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, _ = _run_cli(monkeypatch, capsys, "audit", str(NEGATIVE))

    assert code == 0, f"expected exit 0, got {code}: {out}"
    assert "score 100/100" in out, f"unexpected report: {out!r}"


def test_cli_findings_without_threshold_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    findings_repo: Path,
) -> None:
    code, out, _ = _run_cli(monkeypatch, capsys, "audit", str(findings_repo))

    assert code == 1, f"expected exit 1, got {code}: {out}"
    assert out.startswith("WARN  "), f"expected WARN report, got {out!r}"
    assert "Blast Radius: 97/100 (Shielded)" in out


@pytest.mark.parametrize(
    ("threshold", "expected"),
    [
        ("99", 1),
        ("100", 1),
        ("97", 0),
        ("90", 0),
        ("0", 0),
    ],
)
def test_cli_fail_under_matrix(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    findings_repo: Path,
    threshold: str,
    expected: int,
) -> None:
    code, out, _ = _run_cli(
        monkeypatch,
        capsys,
        "audit",
        str(findings_repo),
        "--fail-under",
        threshold,
    )

    assert code == expected, (
        f"--fail-under {threshold} on score 97 must exit {expected}, "
        f"got {code}: {out}"
    )


def test_cli_missing_path_exits_two(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, _ = _run_cli(
        monkeypatch,
        capsys,
        "audit",
        str(CORPUS / "does-not-exist"),
    )

    assert code == 2, f"expected exit 2, got {code}: {out}"
    assert "file not found" in out


@pytest.mark.parametrize("raw", ["abc", "145", "-1", "1_0", "90.5", ""])
def test_cli_invalid_threshold_exits_two(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    raw: str,
) -> None:
    code, out, err = _run_cli(
        monkeypatch,
        capsys,
        "audit",
        str(CORPUS),
        "--fail-under",
        raw,
    )

    assert code == 2, f"expected exit 2 for {raw!r}, got {code}: {out}{err}"
    assert err.strip() == (
        "scyvera audit: error: --fail-under must be an integer "
        "between 0 and 100"
    ), f"unexpected threshold error: {err!r}"
    assert "usage" not in err.lower(), "threshold errors must not print usage"
    assert "Traceback" not in err, "threshold errors must not print a traceback"


# --- Badge CLI wiring -------------------------------------------------------


def test_cli_badge_is_the_final_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, _ = _run_cli(monkeypatch, capsys, "audit", str(NEGATIVE), "--badge")

    assert code == 0, f"expected exit 0, got {code}: {out}"
    lines = out.rstrip("\n").splitlines()
    assert lines[-1] == render_badge(scan_tree(NEGATIVE)), (
        f"badge must be the final line, got {lines[-1]!r}"
    )
    assert "Shielded-green" in lines[-1]


def test_cli_json_badge_is_additive(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, plain_out, _ = _run_cli(monkeypatch, capsys, "audit", str(NEGATIVE), "--json")
    _, badge_out, _ = _run_cli(
        monkeypatch,
        capsys,
        "audit",
        str(NEGATIVE),
        "--json",
        "--badge",
    )

    plain = json.loads(plain_out)
    badged = json.loads(badge_out)

    assert "badge" not in plain, "--badge must be the only way to add the key"
    assert list(badged) == [*plain, "badge"], "badge must be appended last"
    assert badged["badge"] == render_badge(scan_tree(NEGATIVE))
    for key, value in plain.items():
        assert badged[key] == value, f"--badge changed existing key {key!r}"


def test_cli_json_without_badge_is_byte_identical(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, out, _ = _run_cli(monkeypatch, capsys, "audit", str(NEGATIVE), "--json")

    assert out.rstrip("\n") == scan_tree(NEGATIVE).to_json(), (
        "plain --json must serialize exactly like AuditReport.to_json()"
    )


def test_cli_help_documents_flags_and_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["scyvera", "audit", "--help"])

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 0, "audit --help must exit 0"
    out = capsys.readouterr().out
    assert (
        "exit codes: 0 ok, 1 findings or threshold breach, 2 usage/IO error"
        in out
    ), "pinned exit-code sentence must be in the help output"
    for flag in ("--json", "--badge", "--fail-under"):
        assert flag in out, f"{flag} must be documented in audit --help"


# --- Dogfood and determinism guards (RFC 0004 §7) ---------------------------


def test_dogfood_gate_is_shielded(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, _ = _run_cli(
        monkeypatch,
        capsys,
        "audit",
        str(ROOT),
        "--fail-under",
        "90",
    )

    assert code == 0, f"expected exit 0 under --fail-under 90, got {code}"
    assert "Blast Radius: 92/100 (Shielded)" in out, (
        f"dogfood report drifted: {out!r}"
    )


def test_repository_double_scan_is_dict_equal() -> None:
    first = scan_tree(ROOT).to_dict()
    second = scan_tree(ROOT).to_dict()

    assert first == second, (
        "scanning the repository root twice must produce dict-equal reports "
        "(guards the M2.0a observer-effect bug)"
    )


def test_quarantined_findings_do_not_move_score_band_or_stats(
    findings_repo: Path,
) -> None:
    base = scan_tree(findings_repo)
    quarantined = _finding(
        "AU-ENV-002",
        "critical",
        "secret committed in env file",
        "tests/fixtures/audit/positive/.env",
        1,
        scored=False,
    )
    enriched = replace(base, findings=base.findings + (quarantined,))

    assert enriched.score == base.score == 97
    assert enriched.band == base.band == "Shielded"
    assert enriched.stats == base.stats, "quarantined findings must not add stats"
    assert render_report(enriched) == render_report(base), (
        "quarantined findings must not change the rendered report"
    )


# --- No-write and narrow-codepage guarantees --------------------------------


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_render_and_badge_write_no_files() -> None:
    before = _snapshot(CORPUS)
    report = scan_tree(CORPUS)

    render_report(report)
    render_badge(report)
    json.loads(report.to_json())

    assert _snapshot(CORPUS) == before, "audit rendering must never modify the tree"


def test_cli_ascii_stdout_cannot_crash() -> None:
    code = (
        "import sys; "
        "from scyvera.cli import main; "
        f"sys.argv = ['scyvera', 'audit', {str(NEGATIVE)!r}]; "
        "raise SystemExit(main())"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={**os.environ, "PYTHONIOENCODING": "ascii"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"ASCII stdout must not crash, got {result.returncode}: {result.stderr}"
    )
    assert result.stderr == "", f"unexpected stderr: {result.stderr!r}"
    assert "->" in result.stdout, "narrow codepages must use the ASCII dash"
    assert EM_DASH not in result.stdout
    assert "UnicodeEncodeError" not in result.stderr


def test_positive_fixture_render_has_no_scored_rows() -> None:
    report = scan_tree(POSITIVE)
    text = render_report(report)

    assert report.score == 100
    assert all(finding.scored is False for finding in report.findings)
    assert text.startswith("PASS  ")
    assert "12 quarantined finding(s) not scored" in text
