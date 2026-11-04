"""Tests for RFC 0004 M2.7 Policy Packs (§6, §8).

The milestone's QA bar lives here: every golden pack is loaded, applied to a
draft built from every fixture corpus, written to disk, and re-validated with
Tier 0 (schema) and Tier 2 (semantic lint). A pack that would produce a
contract failing either gate cannot ship.

Nothing is written into the repository tree: corpora are copied under
``tmp_path`` and drafts are written under ``tmp_path`` only.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
import json
import shutil
import sys
from typing import Any

import pytest
import yaml

from scyvera.audit import AuditReport, scan_tree
from scyvera.audit_rules import Finding
from scyvera.cli import main
from scyvera.generate import build_draft, write_draft
from scyvera.linter import lint_contract
from scyvera.packs import (
    PACKS_DIR,
    PackError,
    PolicyPack,
    available_packs,
    load_pack,
    pack_from_mapping,
)
from scyvera.validator import validate_contract


ROOT = Path(__file__).resolve().parent.parent
REPO_PACKS = ROOT / "packs"
PACKAGE_PACKS = ROOT / "src" / "scyvera" / "packs"
CORPUS = ROOT / "tests" / "fixtures" / "audit"
CORPUS_CASES = sorted(
    (path for path in CORPUS.iterdir() if path.is_dir()),
    key=lambda path: path.name,
)

#: RFC 0004 §8, verbatim. Sorted for deterministic parametrization.
GOLDEN_PACK_NAMES: tuple[str, ...] = (
    "dev-agent",
    "devops-safe",
    "email-triage",
    "finance-ops",
    "github-safe",
    "research-assistant",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scored_copy(tmp_path: Path, corpus: Path) -> tuple[Path, AuditReport]:
    """Copy ``corpus`` outside ``tests/fixtures`` so its findings are scored."""
    target = tmp_path / corpus.name
    shutil.copytree(corpus, target)
    return target, scan_tree(target)


def _report(
    *findings: Finding,
    target: str = "sample-repo",
) -> AuditReport:
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
        scored=True,
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


def _valid_payload() -> dict[str, Any]:
    """Return a mutable copy of the canonical github-safe pack."""
    payload = yaml.safe_load(
        (REPO_PACKS / "github-safe.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(payload, dict)
    return payload


def _without_derive(payload: dict[str, Any]) -> None:
    del payload["derive"]


def _unknown_derive_key(payload: dict[str, Any]) -> None:
    payload["derive"]["future_constraint"] = []


def _unsupported_contract_version(payload: dict[str, Any]) -> None:
    payload["construction"]["contract_version"] = "1.0"


def _zero_cap(payload: dict[str, Any]) -> None:
    payload["derive"]["cap_side_effects_per_window"] = 0


def _scalar_instead_of_list(payload: dict[str, Any]) -> None:
    payload["derive"]["irreversibly_forbidden"] = "file_delete"


def _invalid_pack_name(payload: dict[str, Any]) -> None:
    payload["pack"] = "GitHub Safe"


def _unknown_top_level_key(payload: dict[str, Any]) -> None:
    payload["logic"] = {"if": "anything"}


def _empty_entry(payload: dict[str, Any]) -> None:
    payload["derive"]["requires_approval"] = [""]


def _overlapping_constraint(payload: dict[str, Any]) -> None:
    payload["derive"]["requires_approval"] = ["file_delete"]


# ---------------------------------------------------------------------------
# Golden pack inventory and packaging (RFC 0004 §6, §8)
# ---------------------------------------------------------------------------


def test_golden_pack_names_match_the_rfc() -> None:
    assert available_packs(packs_dir=REPO_PACKS) == GOLDEN_PACK_NAMES
    assert available_packs() == GOLDEN_PACK_NAMES


def test_loader_defaults_to_the_packaged_copy() -> None:
    assert PACKS_DIR == PACKAGE_PACKS


@pytest.mark.parametrize("name", GOLDEN_PACK_NAMES)
def test_pack_copies_are_byte_identical(name: str) -> None:
    root = REPO_PACKS / f"{name}.yaml"
    packaged = PACKAGE_PACKS / f"{name}.yaml"
    assert root.is_file(), f"missing repository pack: {root}"
    assert packaged.is_file(), f"missing packaged pack: {packaged}"
    assert root.read_bytes() == packaged.read_bytes()


def test_pyproject_ships_pack_package_data() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"packs/*.yaml"' in text


# ---------------------------------------------------------------------------
# Loading and validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", GOLDEN_PACK_NAMES)
def test_every_golden_pack_loads_with_required_facts(name: str) -> None:
    pack = load_pack(name)
    assert isinstance(pack, PolicyPack)
    assert pack.name == name
    assert pack.version == "1.0.0"
    assert pack.domain
    assert pack.description
    assert pack.contract_version == "1.1"
    assert pack.irreversibly_forbidden
    assert pack.requires_approval
    assert pack.cap_side_effects_per_window is not None


def test_policy_pack_is_immutable() -> None:
    pack = load_pack("github-safe")
    with pytest.raises((AttributeError, TypeError)):
        pack.domain = "finance"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (_without_derive, "missing required key"),
        (_unknown_derive_key, "unknown key"),
        (_unsupported_contract_version, "unsupported construction"),
        (_zero_cap, "positive integer"),
        (_scalar_instead_of_list, "must be a list"),
        (_invalid_pack_name, "lowercase words"),
        (_unknown_top_level_key, "unknown key"),
        (_empty_entry, "non-empty strings"),
        (_overlapping_constraint, "both forbidden and approval-gated"),
    ],
)
def test_pack_validation_rejects_malformed_documents(
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    payload = _valid_payload()
    mutate(payload)
    with pytest.raises(PackError, match=message):
        pack_from_mapping(payload, name="github-safe")


def test_cap_is_optional_and_absent_constraints_stay_absent() -> None:
    payload = _valid_payload()
    del payload["derive"]["cap_side_effects_per_window"]
    pack = pack_from_mapping(payload, name="github-safe")

    assert pack.cap_side_effects_per_window is None
    draft = build_draft(_report(), pack=pack)
    assert "constraints" not in draft


def test_load_pack_rejects_path_traversal() -> None:
    with pytest.raises(PackError, match="invalid policy pack name"):
        load_pack("../contract")


def test_load_pack_reports_available_names() -> None:
    with pytest.raises(PackError) as excinfo:
        load_pack("does-not-exist")
    message = str(excinfo.value)
    assert "unknown policy pack 'does-not-exist'" in message
    assert "github-safe" in message


def test_load_pack_reads_only_the_given_local_directory(tmp_path: Path) -> None:
    shutil.copy(REPO_PACKS / "github-safe.yaml", tmp_path / "github-safe.yaml")
    pack = load_pack("github-safe", packs_dir=tmp_path)
    assert pack.name == "github-safe"


def test_load_pack_refuses_a_symlinked_pack(tmp_path: Path) -> None:
    link = tmp_path / "github-safe.yaml"
    try:
        link.symlink_to(REPO_PACKS / "github-safe.yaml")
    except OSError:
        pytest.skip("symlink creation is unavailable on this host")

    with pytest.raises(PackError, match="symlink"):
        load_pack("github-safe", packs_dir=tmp_path)


# ---------------------------------------------------------------------------
# Merge semantics (RFC 0004 §6: pack wins, finding-only extras appended)
# ---------------------------------------------------------------------------


def test_pack_wins_on_conflicts_and_keeps_finding_only_extras() -> None:
    report = _report(
        _finding(
            "high",
            {
                "side_effects": [
                    {"type": "file_delete", "resource": "workspace"},
                    {"type": "host_mount", "resource": "host"},
                ],
                "approvals": [
                    {"action": "file_delete", "required": False},
                    {"action": "host_mount", "required": False},
                ],
            },
        )
    )

    draft = build_draft(report, pack=load_pack("github-safe"))
    effects = {effect["type"]: effect for effect in draft["side_effects"]}
    approvals = {
        entry["action"]: entry
        for entry in draft["approvals"]
        if isinstance(entry, Mapping)
    }

    # Pack wins: a forbidden effect becomes irreversible and offers no approval.
    assert effects["file_delete"]["irreversible"] is True
    assert "file_delete" not in approvals

    # Pack wins: a required action is forced to required even if it existed.
    assert approvals["git_ref_write"]["required"] is True
    assert approvals["ci_deploy_write"]["required"] is True

    # Finding-only extras the pack does not mention are appended unchanged.
    assert "irreversible" not in effects["host_mount"]
    assert approvals["host_mount"]["required"] is False


def test_pack_supplies_domain_and_side_effect_cap() -> None:
    draft = build_draft(_report(), pack=load_pack("finance-ops"))

    assert draft["domain"] == "finance"
    assert draft["constraints"] == [
        {"type": "side_effects_per_window", "maximum": 5}
    ]


def test_pack_forbidden_types_are_synthesized_when_absent() -> None:
    draft = build_draft(_report(), pack=load_pack("dev-agent"))
    effects = {effect["type"]: effect for effect in draft["side_effects"]}

    assert effects["file_delete"]["irreversible"] is True
    assert effects["remote_execution"]["irreversible"] is True


# ---------------------------------------------------------------------------
# Full sweep: every golden pack × every fixture corpus (RFC 0004 §6 QA bar)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", GOLDEN_PACK_NAMES)
@pytest.mark.parametrize("corpus", CORPUS_CASES, ids=lambda path: path.name)
def test_every_pack_applied_draft_validates_and_lints_clean(
    tmp_path: Path,
    name: str,
    corpus: Path,
) -> None:
    target, report = _scored_copy(tmp_path, corpus)
    assert target != corpus

    pack = load_pack(name)
    draft_path = tmp_path / f"{name}-{corpus.name}.yaml"
    write_draft(build_draft(report, pack=pack), draft_path)

    validation = validate_contract(draft_path)
    assert validation.valid, (
        f"{name} on {corpus.name} failed validation: "
        f"{[(error.path, error.message) for error in validation.errors]}"
    )

    lint = lint_contract(draft_path)
    assert lint.valid_structure, (
        f"{name} on {corpus.name} failed structural lint"
    )
    assert lint.warnings == (), (
        f"{name} on {corpus.name} emitted lint warnings: "
        f"{[(warning.rule_id, warning.message) for warning in lint.warnings]}"
    )

    loaded = yaml.safe_load(draft_path.read_text(encoding="ascii"))
    assert loaded["domain"] == pack.domain
    constraints = {
        entry["type"]: entry
        for entry in loaded.get("constraints", [])
        if isinstance(entry, Mapping)
    }
    assert constraints["side_effects_per_window"]["maximum"] == (
        pack.cap_side_effects_per_window
    )


# ---------------------------------------------------------------------------
# CLI wiring (RFC 0004 §2: --pack applies a pack to the --generate draft)
# ---------------------------------------------------------------------------


def test_cli_pack_requires_generate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "repo"
    target.mkdir()

    exit_code, out, err = _run(
        monkeypatch,
        capsys,
        ["audit", str(target), "--pack", "github-safe"],
    )

    assert exit_code == 2
    assert out == ""
    assert err.strip() == (
        "scyvera audit: error: --pack requires --generate <contract>"
    )


def test_cli_unknown_pack_is_a_usage_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    draft_path = tmp_path / "contract.yaml"

    exit_code, out, err = _run(
        monkeypatch,
        capsys,
        [
            "audit",
            str(target),
            "--generate",
            str(draft_path),
            "--pack",
            "does-not-exist",
        ],
    )

    assert exit_code == 2
    assert out == ""
    assert err.startswith(
        "scyvera audit: error: unknown policy pack 'does-not-exist'"
    )
    assert "github-safe" in err
    assert err.count("\n") == 1
    assert not draft_path.exists()


def test_cli_applies_pack_to_generated_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target, _ = _scored_copy(tmp_path, CORPUS / "positive")
    draft_path = tmp_path / "contract.yaml"

    exit_code, out, err = _run(
        monkeypatch,
        capsys,
        [
            "audit",
            str(target),
            "--generate",
            str(draft_path),
            "--pack",
            "github-safe",
        ],
    )

    assert exit_code == 1
    assert err == ""
    assert f"Draft contract written to {draft_path}" in out

    loaded = yaml.safe_load(draft_path.read_text(encoding="ascii"))
    assert loaded["domain"] == "software"
    assert loaded["constraints"] == [
        {"type": "side_effects_per_window", "maximum": 10}
    ]

    effects = {effect["type"]: effect for effect in loaded["side_effects"]}
    assert effects["file_delete"]["irreversible"] is True
    assert effects["remote_execution"]["irreversible"] is True

    approval_actions = {
        entry["action"]
        for entry in loaded["approvals"]
        if isinstance(entry, Mapping)
    }
    assert "file_delete" not in approval_actions
    assert "remote_execution" not in approval_actions
    assert "git_ref_write" in approval_actions
    assert "ci_deploy_write" in approval_actions

    assert validate_contract(draft_path).valid
    assert lint_contract(draft_path).warnings == ()


def test_cli_json_with_pack_adds_only_draft_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target, _ = _scored_copy(tmp_path, CORPUS / "negative")
    draft_path = tmp_path / "contract.yaml"

    _, plain_out, _ = _run(
        monkeypatch,
        capsys,
        ["audit", str(target), "--json"],
    )
    _, packed_out, _ = _run(
        monkeypatch,
        capsys,
        [
            "audit",
            str(target),
            "--json",
            "--generate",
            str(draft_path),
            "--pack",
            "github-safe",
        ],
    )

    plain = json.loads(plain_out)
    packed = json.loads(packed_out)
    assert list(packed) == [*plain, "draft_path"]
    assert packed["draft_path"] == str(draft_path)
