"""Tests for the ``scyvera check`` conformance CLI (RFC 0003 §C3, M2.1).

Coverage targets:

- Tier 0 is a **superset** of ``scyvera validate`` + ``scyvera lint``:
  a failing fixture reports the schema error *and* the AC000 structural
  finding in one report, with exit code 1; a passing fixture exits 0.
- ``--tier auto`` resolves to the highest implemented tier with an explicit
  note, never silently (roadmap M2.1 acceptance criterion).
- Explicit unimplemented tiers (1, 2) fail loudly with exit code 2 and a
  clean one-line stderr message (no traceback), per the fail-closed
  philosophy and RFC 0003 §C3 "never silently".
- The library layer (:mod:`scyvera.conformance`) is pure: no printing, no
  filesystem writes, deterministic reports, and immutable-result objects.
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scyvera.cli import main
from scyvera.conformance import (
    CheckReport,
    CheckTier,
    Tier1UnavailableError,
    TierNotImplementedError,
    check_contract,
    render_check,
    resolve_tier,
)

ROOT = Path(__file__).resolve().parent.parent
VALID = ROOT / "tests" / "fixtures" / "v1.1" / "valid-full.yaml"
VALID_MINIMAL = ROOT / "tests" / "fixtures" / "v1.1" / "valid-minimal.yaml"
INVALID_VERSION = ROOT / "tests" / "fixtures" / "invalid-version.yaml"
INVALID_ENUM = ROOT / "tests" / "fixtures" / "v1.1" / "invalid-enum.yaml"
MISSING = ROOT / "tests" / "fixtures" / "does-not-exist.yaml"


# ---------------------------------------------------------------------------
# Resolution policy (resolve_tier)
# ---------------------------------------------------------------------------


def test_resolve_tier_auto_carries_note() -> None:
    tier, note = resolve_tier("auto")
    assert tier is CheckTier.STRUCTURAL
    assert note is not None
    assert "tier 0" in note


def test_resolve_tier_none_behaves_like_auto() -> None:
    tier, note = resolve_tier(None)
    assert tier is CheckTier.STRUCTURAL
    assert note is not None


def test_resolve_tier_zero_is_explicit_and_silent() -> None:
    tier, note = resolve_tier("0")
    assert tier is CheckTier.STRUCTURAL
    assert note is None


def test_resolve_tier_static_resolves() -> None:
    tier, note = resolve_tier("1")
    assert tier is CheckTier.STATIC
    assert note is None
    tier, note = resolve_tier(CheckTier.STATIC)
    assert tier is CheckTier.STATIC
    assert note is None


def test_resolve_tier_trace_raises() -> None:
    with pytest.raises(TierNotImplementedError):
        resolve_tier("2")
    with pytest.raises(TierNotImplementedError):
        resolve_tier(CheckTier.TRACE)


def test_resolve_tier_unknown_value_raises_value_error() -> None:
    with pytest.raises(ValueError):
        resolve_tier("nine")


# ---------------------------------------------------------------------------
# Library layer: check_contract / CheckReport
# ---------------------------------------------------------------------------


def test_check_contract_tier0_passes_valid_contract() -> None:
    report = check_contract(VALID, tier="0")
    assert isinstance(report, CheckReport)
    assert report.tier is CheckTier.STRUCTURAL
    assert report.valid is True
    assert report.tier_note is None
    assert report.validation_errors == ()
    assert report.warnings == ()


def test_check_contract_minimal_passes() -> None:
    assert check_contract(VALID_MINIMAL, tier="0").valid is True


def test_check_contract_fails_invalid_version() -> None:
    report = check_contract(INVALID_VERSION, tier="0")
    assert report.valid is False
    assert any(
        "Unsupported specification version" in error.message
        for error in report.validation_errors
    )
    assert any(w.rule_id == "AC000" for w in report.warnings), (
        "tier 0 must surface the lint layer's AC000 alongside schema errors"
    )


def test_check_report_is_immutable() -> None:
    report = check_contract(VALID, tier="0")
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.valid = True  # type: ignore[misc]


def test_check_contract_is_deterministic() -> None:
    first = check_contract(INVALID_VERSION, tier="0")
    second = check_contract(INVALID_VERSION, tier="0")
    assert first == second
    assert render_check(first) == render_check(second)


def test_check_contract_tier_auto_resolves_with_note() -> None:
    report = check_contract(VALID, tier="auto")
    assert report.tier is CheckTier.STRUCTURAL
    assert report.tier_note is not None
    assert "tier 0" in report.tier_note


def test_check_contract_tier1_requires_adapter() -> None:
    with pytest.raises(Tier1UnavailableError):
        check_contract(VALID, tier="1")
    with pytest.raises(TierNotImplementedError):
        check_contract(VALID, tier="2")


def test_conformance_library_never_prints_or_writes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _fixture_state() -> frozenset[tuple[str, int]]:
        return frozenset(
            (p.name, p.stat().st_mtime_ns if p.is_file() else -1)
            for p in (ROOT / "tests" / "fixtures").iterdir()
        )

    before = _fixture_state()
    check_contract(VALID, tier="auto")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert _fixture_state() == before, "check must never touch the filesystem"


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def test_render_check_pass_has_no_note_line() -> None:
    report = check_contract(VALID, tier="0")
    text = render_check(report)
    assert text.startswith(f"PASS  {report.contract_path}")
    assert "note:" not in text
    assert text.endswith("\n")


def test_render_check_fail_lists_both_layers() -> None:
    text = render_check(check_contract(INVALID_VERSION, tier="0"))
    assert text.startswith("FAIL")
    assert "Unsupported specification version" in text  # validator layer
    assert "[AC000]" in text  # linter layer


def test_render_check_is_ascii_safe() -> None:
    text = render_check(check_contract(INVALID_ENUM, tier="0"))
    assert text.isascii(), "narrow codepages must survive check output"


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def test_cli_tier0_pass(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["scyvera", "check", str(VALID), "--tier", "0"])
    exit_code = main()
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "PASS" in output
    assert "note:" not in output


def test_cli_default_auto_resolves_with_notice(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["scyvera", "check", str(VALID)])
    exit_code = main()
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "note: --tier auto resolved to tier 0" in output


def test_cli_check_fail_exit_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["scyvera", "check", str(INVALID_VERSION), "--tier", "0"])
    exit_code = main()
    output = capsys.readouterr().out
    assert exit_code == 1
    assert "FAIL" in output
    assert "Unsupported specification version" in output
    assert "[AC000]" in output


def test_cli_check_invalid_enum_fail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["scyvera", "check", str(INVALID_ENUM), "--tier", "0"])
    exit_code = main()
    output = capsys.readouterr().out
    assert exit_code == 1
    assert "FAIL" in output


def test_cli_check_missing_file_exit_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["scyvera", "check", str(MISSING)])
    exit_code = main()
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "ERROR" in captured.out
    assert "file not found" in captured.out


def test_cli_check_unimplemented_tier_exit_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["scyvera", "check", str(VALID), "--tier", "2"])
    exit_code = main()
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "not implemented" in captured.err
    assert "Traceback" not in captured.err, "unimplemented tiers fail with a clean message"


def test_cli_check_tier1_without_adapter_exit_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["scyvera", "check", str(VALID), "--tier", "1"])
    exit_code = main()
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "no tier 1 adapter" in captured.err
    assert "Traceback" not in captured.err, "missing adapters fail with a clean message"


def test_cli_superset_of_validate_and_lint_on_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The check exit code never approves what validate or lint would fail."""
    for fixture in (INVALID_VERSION, INVALID_ENUM):
        monkeypatch.setattr(sys, "argv", ["scyvera", "validate", str(fixture)])
        validate_exit = main()
        monkeypatch.setattr(sys, "argv", ["scyvera", "lint", str(fixture)])
        lint_exit = main()
        monkeypatch.setattr(sys, "argv", ["scyvera", "check", str(fixture), "--tier", "0"])
        check_exit = main()
        capsys.readouterr()
        assert check_exit == 1, f"{fixture.name}: check must fail alongside sources"
        assert check_exit >= validate_exit and check_exit >= lint_exit, (
            f"{fixture.name}: check must be a superset of validate + lint"
        )


def test_cli_narrow_codepage_does_not_crash() -> None:
    code = (
        "import sys; "
        "from scyvera.cli import main; "
        f"sys.argv = ['scyvera', 'check', {str(VALID)!r}, '--tier', '0']; "
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
    assert "UnicodeEncodeError" not in result.stderr
