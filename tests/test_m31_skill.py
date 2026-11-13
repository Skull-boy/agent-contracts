"""Convention pins for the M3.1 harness skill package.

These are executable contracts, in the style of ``tests/test_pd7_mcp.py``:
the skill text, the hash lock, the finding table, and the exit-code table are
pinned so an edit cannot drift them silently. Every test fails closed.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

import pytest

from scyvera.audit_rules import RULES
from scyvera.cli import build_parser

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # the wheel workflow runs pytest from another cwd
    sys.path.insert(0, str(ROOT))

from tools.lock_skill import (  # noqa: E402  (path setup must run first)
    SKILL_DIR,
    build_registry,
    render_registry,
    verify_registry,
)

SKILL_MD = SKILL_DIR / "SKILL.md"
FINDING_CODES = SKILL_DIR / "reference" / "finding-codes.md"
EXIT_CODES = SKILL_DIR / "reference" / "exit-codes.md"
REGISTRY = ROOT / "skills-registry.json"

NEVERS = (
    "NEVER fabricate findings",
    "NEVER lower a finding's severity",
    "NEVER declare PASS without running the command",
)

AUDIT_RULE_IDS = {rule.rule_id for rule in RULES}
CONFORMANCE_RULE_IDS = {
    "AC000",
    "AC101",
    "AC103",
    "AC201",
    "AC301",
    "AC302",
    "AC401",
    "AC601",
    "AC701",
    "T101",
    "T102",
    "T103",
}
EXPECTED_COMMANDS = {
    "validate",
    "lint",
    "check",
    "self-check",
    "audit",
    "eval",
    "init",
    "serve-mcp",
}


def test_skill_md_contains_the_three_nevers_verbatim() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    for never in NEVERS:
        assert never in text, f"missing NEVER: {never}"


def test_skill_md_states_the_design_principle() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "knowledge, not powers" in text
    assert "does not give you\ngovernance authority" in text


def test_skill_md_stays_under_120_lines() -> None:
    assert len(SKILL_MD.read_text(encoding="utf-8").splitlines()) < 120


def test_every_locked_file_hash_recomputes() -> None:
    assert verify_registry() == []


def test_registry_is_deterministic_and_matches_disk() -> None:
    first = render_registry(build_registry())
    second = render_registry(build_registry())
    assert first == second
    assert first == REGISTRY.read_text(encoding="utf-8")


def test_registry_keeps_the_ecosystem_lock_shape() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert registry["version"] == 1
    entry = registry["skills"]["scyvera-governance"]
    assert entry["sourceType"] == "github"
    assert entry["skillPath"] == "skills/scyvera-governance/SKILL.md"
    assert entry["computedHash"] == entry["files"][entry["skillPath"]]
    assert entry["files"] == dict(sorted(entry["files"].items()))
    assert "locked_at_version" in entry and "version" in entry


def test_finding_codes_table_covers_every_registry_rule_id() -> None:
    text = FINDING_CODES.read_text(encoding="utf-8")
    documented = set(
        re.findall(r"`((?:AU-[A-Z0-9]+-\d+)|(?:AC\d{3})|(?:T1\d{2}))`", text)
    )
    expected = AUDIT_RULE_IDS | CONFORMANCE_RULE_IDS
    assert documented == expected


def test_exit_codes_table_documents_every_registered_command(capsys) -> None:
    text = EXIT_CODES.read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| `([a-z-]+)` \|", text, flags=re.MULTILINE))
    assert documented == EXPECTED_COMMANDS

    parser = build_parser()
    for command in sorted(documented):
        with pytest.raises(SystemExit) as raised:
            parser.parse_args([command, "--help"])
        assert raised.value.code == 0, command
    capsys.readouterr()


def test_scripts_are_offline_and_unprivileged() -> None:
    for name in ("audit.sh", "audit.ps1"):
        text = (SKILL_DIR / "scripts" / name).read_text(encoding="utf-8")
        for forbidden in ("curl", "wget", "ssh ", "sudo", "Invoke-WebRequest"):
            assert forbidden not in text, f"{name} contains {forbidden}"
        assert "scyvera audit" in text
        assert "$LASTEXITCODE" in text or "code=$?" in text
