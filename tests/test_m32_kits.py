"""Convention pins for the M3.2 per-target adoption kits.

The kits are declarative: they reuse the shipped contracts, adapters, and eval
fixtures, and they carry no engine code. These tests pin the format, the
byte-locked reference tables, the offline verify scripts, the PowerShell parse,
and deterministic engine output across two runs.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

from scyvera.cli import main

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # the wheel workflow runs pytest from another cwd
    sys.path.insert(0, str(ROOT))

KITS = ROOT / "kits"
SKILL_REFERENCE = ROOT / "skills" / "scyvera-governance" / "reference"
REFERENCE_TABLES = ("finding-codes.md", "exit-codes.md")

TARGETS = {
    "n8n": ROOT / "implementations" / "n8n" / "competitor-feature-parity-watcher",
    "langgraph": ROOT / "implementations" / "langgraph" / "duplicate-issue-detector",
}

REQUIRED_FILES = {
    "KIT.md",
    "contract.template.yaml",
    "verify.sh",
    "verify.ps1",
    "reference/finding-codes.md",
    "reference/exit-codes.md",
}

EXPECTED_SUMMARIES = {
    "n8n": "0 tier-1 findings",
    "langgraph": "6 tier-1 finding(s)",
}

GOLDEN_EVAL_REL = (
    "implementations/langgraph/duplicate-issue-detector/evals/refund-agent.eval.yaml"
)
PINNED_EVAL_SCORE = "75.0/100"


def _posix_shell() -> str | None:
    """Return a POSIX shell, preferring Git Bash on Windows."""

    candidates: list[str] = []
    if os.name == "nt":
        candidates.extend(
            [
                r"C:\Program Files\Git\bin\bash.exe",
                r"C:\Program Files\Git\usr\bin\sh.exe",
            ]
        )
    for name in ("sh", "bash"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    return None


def _powershell() -> str | None:
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


def test_kits_match_the_shipped_targets() -> None:
    assert (KITS / "README.md").is_file()
    top_level = {path.name for path in KITS.iterdir()}
    assert top_level == {"README.md", *TARGETS}


def test_each_kit_has_exactly_the_required_files() -> None:
    for target in TARGETS:
        kit = KITS / target
        assert kit.is_dir(), target
        relative = {
            path.relative_to(kit).as_posix()
            for path in kit.rglob("*")
            if path.is_file()
        }
        assert relative == REQUIRED_FILES, target


def test_reference_tables_stay_byte_identical_to_the_skill() -> None:
    for table in REFERENCE_TABLES:
        expected = (SKILL_REFERENCE / table).read_bytes()
        for target in TARGETS:
            copied = (KITS / target / "reference" / table).read_bytes()
            assert copied == expected, f"{target}/reference/{table} drifted"


def test_kit_md_documents_the_three_step_path_and_scope() -> None:
    required_steps = (
        "### 1. Install scyvera",
        "### 2. Run the kit check",
        "### 3. Ship the contract into your repo",
    )
    for target in TARGETS:
        text = (KITS / target / "KIT.md").read_text(encoding="utf-8")
        for step in required_steps:
            assert step in text, f"{target} KIT.md missing {step!r}"
        assert "Honest Tier 1 scope" in text, target
        assert "docs/language-coverage.md" in text, target
        assert "contract.template.yaml" in text, target


def test_contract_templates_validate_and_mark_edit_fields(
    monkeypatch, capsys
) -> None:
    for target in TARGETS:
        template = KITS / target / "contract.template.yaml"
        text = template.read_text(encoding="utf-8")
        assert text.count("# EDIT") >= 5, target
        assert "workflow:" in text, target

        for command in ("validate", "lint"):
            monkeypatch.setattr(
                sys, "argv", ["scyvera", command, str(template)]
            )
            assert main() == 0, f"{target} {command}"
            capsys.readouterr()


def test_verify_scripts_are_offline_and_capture_the_exit_code() -> None:
    forbidden = (
        "curl",
        "wget",
        "ssh ",
        "sudo",
        "Invoke-WebRequest",
        "http://",
        "https://",
        "token",
    )
    for target in TARGETS:
        kit = KITS / target
        sh_text = (kit / "verify.sh").read_text(encoding="utf-8")
        ps_text = (kit / "verify.ps1").read_text(encoding="utf-8")

        for name, text in (("verify.sh", sh_text), ("verify.ps1", ps_text)):
            for word in forbidden:
                assert word not in text, f"{target}/{name} contains {word!r}"
            assert "scyvera --version" in text, f"{target}/{name}"
            assert "scyvera check" in text, f"{target}/{name}"
            assert "expected:" in text, f"{target}/{name}"

        assert "code=$?" in sh_text, target
        assert "$LASTEXITCODE" in ps_text, target


def test_posix_verify_scripts_run_green() -> None:
    shell = _posix_shell()
    if shell is None:
        pytest.skip("no POSIX shell is available on this runner")

    for target in TARGETS:
        script = KITS / target / "verify.sh"
        result = subprocess.run(
            [shell, str(script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"{target}/verify.sh exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "expected:" in result.stdout, target
        assert "verified (exit 0)" in result.stdout, target


def test_kit_output_is_deterministic_across_two_runs() -> None:
    shell = _posix_shell()
    if shell is None:
        pytest.skip("no POSIX shell is available on this runner")

    for target in TARGETS:
        script = KITS / target / "verify.sh"
        first = subprocess.run(
            [shell, str(script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        second = subprocess.run(
            [shell, str(script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert first.returncode == second.returncode == 0, target
        assert first.stdout == second.stdout, target


def test_powershell_verify_scripts_parse() -> None:
    if os.name != "nt":
        pytest.skip("PowerShell parse check is a Windows-only pin")
    powershell = _powershell()
    if powershell is None:
        pytest.skip("PowerShell is not available on this runner")

    for target in TARGETS:
        script = KITS / target / "verify.ps1"
        command = (
            "$tokens = $null; $errors = $null; "
            f"[void][System.Management.Automation.Language.Parser]::ParseFile("
            f"'{script}', [ref]$tokens, [ref]$errors); "
            "if ($errors.Count -gt 0) { "
            "$errors | ForEach-Object { Write-Error $_ }; exit 1 }"
        )
        result = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"{target}/verify.ps1 did not parse\n{result.stderr}"
        )


def test_kit_expected_summaries_match_the_engine(monkeypatch, capsys) -> None:
    for target, reference in TARGETS.items():
        monkeypatch.setattr(
            sys, "argv", ["scyvera", "check", str(reference), "--tier", "1"]
        )
        assert main() == 0, target
        stdout = capsys.readouterr().out
        assert EXPECTED_SUMMARIES[target] in stdout, target
        assert EXPECTED_SUMMARIES[target] in (
            KITS / target / "KIT.md"
        ).read_text(encoding="utf-8"), target


def test_langgraph_kit_pins_the_golden_eval(monkeypatch, capsys) -> None:
    kit_text = (KITS / "langgraph" / "KIT.md").read_text(encoding="utf-8")
    assert GOLDEN_EVAL_REL in kit_text

    pinned = re.search(r"Pinned score: `([^`]+)`", kit_text)
    assert pinned is not None, "KIT.md must pin the eval score"
    assert pinned.group(1) == PINNED_EVAL_SCORE

    eval_path = ROOT / GOLDEN_EVAL_REL
    assert eval_path.is_file()

    monkeypatch.setattr(sys, "argv", ["scyvera", "eval", str(eval_path)])
    assert main() == 0
    stdout = capsys.readouterr().out
    assert f"total: {pinned.group(1)}" in stdout


def test_kits_readme_documents_the_format_and_lockstep() -> None:
    text = (KITS / "README.md").read_text(encoding="utf-8")
    for token in (
        "KIT.md",
        "contract.template.yaml",
        "verify.sh",
        "verify.ps1",
        "reference/",
        "Lockstep rule",
        "Add a kit",
    ):
        assert token in text, token
