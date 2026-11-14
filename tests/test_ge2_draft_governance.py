"""RFC 0005 draft governance tests (GEP GE-2).

Pins the published lifecycle end to end:

* ``provisional`` is an additive v1.1/v1.2 field and is rejected on v1.
* A provisional contract loads only in draft mode, and draft mode accepts
  only a provisional contract that already exists on disk.
* Draft mode keeps the full default-deny gate pipeline and additionally
  default-denies irreversible actions behind a human approval gate.
* Promotion is human-only, goes through ``reseal()``, requires an explicit
  ``PromotionIntent``, and records deterministic diff evidence.
* Audit, trace, and governance surfaces mark provisional state additively
  without changing ``audit --json`` bytes or full-mode behavior.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scyvera import (
    ApprovalPendingError,
    ContractEnforcer,
    ContractRegistry,
    ContractTamperError,
    ContractValidationError,
    ContractViolationError,
    PromotionIntent,
    PromotionIntentError,
    ProvisionalContractError,
    RegistryError,
    ResealError,
    TraceEntry,
    TraceError,
    audit_from_trace,
    diff_sha256,
    promotion_diff,
    reseal,
    trace_from_audit,
    validate_contract,
    verify_promotion_confirmation,
)
from scyvera.audit import (
    governance_report,
    governance_status,
    scan_tree,
    unify_audit_report,
)
from scyvera.chain import canonical_entry_bytes
from scyvera.cli import run_init, run_promote
from scyvera.generate import build_provisional_contract, write_provisional_contract
from scyvera.linter import lint_contract
from scyvera.registry import RegistryEntry
from scyvera.report import render_report


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _contract(
    path: Path,
    *,
    provisional: bool | None = None,
    version: str = "1.1",
    permissions: tuple[str, ...] = ("github:issues:read",),
    side_effects: tuple[dict, ...] = (),
    approvals: tuple[dict, ...] = (),
    lifecycle_mode: str = "request-response",
) -> Path:
    """Write a minimal schema-valid v1.1/v1.2 contract."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"version: {version}"]
    if provisional is not None:
        lines.append(f"provisional: {'true' if provisional else 'false'}")
    lines.extend(
        [
            "system:",
            "  name: ge2-agent",
            "lifecycle:",
            f"  mode: {lifecycle_mode}",
            "  initiation: human-only",
            "permissions:",
            *[f"  - {permission}" for permission in permissions],
            "side_effects:",
        ]
    )
    if side_effects:
        for effect in side_effects:
            lines.append(f"  - {json.dumps(effect)}")
    else:
        lines[-1] = "side_effects: []"
    if approvals:
        lines.append("approvals:")
        for approval in approvals:
            lines.append(f"  - {json.dumps(approval)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _v1_contract(path: Path, *, provisional: bool = False) -> Path:
    path.write_text(
        "version: 1\n"
        "workflow: ge2\n"
        f"provisional: {'true' if provisional else 'false'}\n"
        "inputs: []\n"
        "outputs: []\n"
        "permissions: []\n"
        "side_effects: []\n"
        "approval_points: []\n"
        "recovery_strategy: retry\n"
        "replay_semantics: idempotent\n"
        "dependencies: []\n"
        "state: none\n"
        "observability: []\n",
        encoding="utf-8",
    )
    return path


def _registry(tmp_path: Path) -> ContractRegistry:
    return ContractRegistry(str(tmp_path / "registry.jsonl"))


def _rows(registry_path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in registry_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _draft_fixture(
    path: Path,
    *,
    irreversible: bool = True,
    approvals: tuple[dict, ...] = (),
    side_effects: tuple[dict, ...] | None = None,
) -> Path:
    if side_effects is None:
        side_effects = (
            {
                "type": "file_delete",
                "resource": "workspace",
                "irreversible": irreversible,
            },
        )
    return _contract(
        path,
        provisional=True,
        side_effects=side_effects,
        approvals=approvals,
    )


def _promote(
    draft_path: Path,
    registry: ContractRegistry,
    *,
    reviewer: str = "alice",
    intent: str = "Reviewed the inferred boundary against the runbook.",
) -> tuple[Path, object]:
    """Register a draft, remove the flag, and promote it through reseal()."""
    ContractEnforcer.load(draft_path, mode="draft").register(registry)
    draft_path.write_text(
        draft_path.read_text(encoding="utf-8").replace(
            "provisional: true\n", ""
        ),
        encoding="utf-8",
    )
    result = reseal(
        draft_path,
        registry,
        promotion=PromotionIntent(reviewer=reviewer, intent=intent),
    )
    return draft_path, result


# ---------------------------------------------------------------------------
# RFC 0005 §3.1/§3.2: the field and validation
# ---------------------------------------------------------------------------


def test_provisional_is_accepted_on_v11_and_v12(tmp_path: Path) -> None:
    v11 = _contract(tmp_path / "v11.yaml", provisional=True)
    v12 = _contract(tmp_path / "v12.yaml", provisional=True, version="1.2")

    assert validate_contract(v11).valid
    assert validate_contract(v12).valid


@pytest.mark.parametrize("provisional", [True, False])
def test_v1_rejects_the_provisional_key(
    tmp_path: Path, provisional: bool
) -> None:
    contract = _v1_contract(tmp_path / "v1.yaml", provisional=provisional)
    result = validate_contract(contract)

    assert not result.valid
    messages = " ".join(error.message for error in result.errors)
    assert "contract_version 1.1 or later" in messages


def test_provisional_field_is_preserved_verbatim_and_read_only(
    tmp_path: Path,
) -> None:
    path = _draft_fixture(tmp_path / "contract.yaml")
    enforcer = ContractEnforcer.load(path, mode="draft")

    assert enforcer.is_provisional is True
    assert enforcer.contract["provisional"] is True
    with pytest.raises(ContractTamperError):
        enforcer.contract["provisional"] = False  # type: ignore[index]


def test_absent_provisional_is_not_provisional(tmp_path: Path) -> None:
    path = _contract(tmp_path / "contract.yaml", provisional=None)

    assert validate_contract(path).valid
    assert ContractEnforcer.load(path).is_provisional is False


def test_explicit_false_warns_but_still_validates(tmp_path: Path) -> None:
    path = _contract(tmp_path / "contract.yaml", provisional=False)

    assert validate_contract(path).valid
    lint = lint_contract(path)
    assert lint.valid_structure
    assert any(warning.rule_id == "AC801" for warning in lint.warnings)


def test_provisional_must_be_a_boolean(tmp_path: Path) -> None:
    path = _contract(tmp_path / "contract.yaml", provisional=True)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "provisional: true", "provisional: 'true'"
        ),
        encoding="utf-8",
    )

    assert not validate_contract(path).valid


# ---------------------------------------------------------------------------
# RFC 0005 §4.1: load modes and typed refusal
# ---------------------------------------------------------------------------


def test_full_mode_refuses_provisional_with_typed_error(tmp_path: Path) -> None:
    path = _draft_fixture(tmp_path / "contract.yaml")

    with pytest.raises(ProvisionalContractError) as excinfo:
        ContractEnforcer.load(path)

    assert issubclass(ProvisionalContractError, ContractViolationError)
    message = str(excinfo.value)
    assert "provisional" in message
    assert "reseal" in message
    assert "PromotionIntent" in message


def test_draft_mode_refuses_a_non_provisional_contract(tmp_path: Path) -> None:
    path = _contract(tmp_path / "contract.yaml")

    with pytest.raises(ContractValidationError, match="not provisional"):
        ContractEnforcer.load(path, mode="draft")


def test_draft_mode_rejects_an_unknown_mode(tmp_path: Path) -> None:
    path = _draft_fixture(tmp_path / "contract.yaml")

    with pytest.raises(ValueError, match="Invalid enforcer mode"):
        ContractEnforcer.load(path, mode="relaxed")  # type: ignore[arg-type]


def test_removing_the_flag_cannot_bypass_draft_registry_history(
    tmp_path: Path,
) -> None:
    path = _draft_fixture(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)
    ContractEnforcer.load(path, mode="draft").register(registry)

    # The T12-style bypass: delete the flag by hand and load in full mode
    # against the registry that still records a draft entry.
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "provisional: true\n", ""
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProvisionalContractError, match="draft entry"):
        ContractEnforcer.load(path, registry=registry)

    with pytest.raises(ProvisionalContractError, match="draft entry"):
        ContractEnforcer.load(path, registry=registry, allow_unsealed_reseal=True)


def test_inference_time_enforcement_requires_a_file_on_disk() -> None:
    """A1: no runtime may enforce inferred authority without a draft file."""
    declaration = ContractEnforcer.from_declaration(
        {
            "node_id": "inferred-agent-v1",
            "permissions": ["tasks:read"],
        }
    )

    assert declaration.contract_source == "declaration"
    assert declaration.is_provisional is False
    assert declaration.mode == "full"


# ---------------------------------------------------------------------------
# RFC 0005 §4.2/§4.3: gate semantics and irreversibility
# ---------------------------------------------------------------------------


def test_draft_mode_keeps_default_deny(tmp_path: Path) -> None:
    path = _draft_fixture(tmp_path / "contract.yaml")
    enforcer = ContractEnforcer.load(path, mode="draft")

    @enforcer.gate("github:issues:write", "permission")
    def write_issue() -> str:
        return "written"

    with pytest.raises(ContractViolationError, match="not declared"):
        write_issue()

    denial = enforcer.get_audit_log()[-1]
    assert denial.decision == "DENIED"
    assert denial.provisional is True


def test_irreversible_action_is_pending_even_with_empty_approvals(
    tmp_path: Path,
) -> None:
    path = _draft_fixture(tmp_path / "contract.yaml")
    enforcer = ContractEnforcer.load(path, mode="draft")

    @enforcer.gate("file_delete", "side_effect")
    def delete_file() -> str:
        return "deleted"

    with pytest.raises(ApprovalPendingError) as excinfo:
        delete_file()

    config = excinfo.value.approval_config
    assert config["required"] is True
    assert config["approver"] == "human"
    assert config["source"] == "implicit-irreversible"
    assert enforcer.get_audit_log()[-1].provisional is True

    enforcer.approve("file_delete")
    assert delete_file() == "deleted"
    assert enforcer.get_audit_log()[-1].decision == "ALLOWED"


def test_closed_verb_set_is_matched_as_a_whole_token_phrase(
    tmp_path: Path,
) -> None:
    path = _draft_fixture(
        tmp_path / "contract.yaml",
        irreversible=False,
        side_effects=(
            {"type": "file_undelete", "resource": "workspace"},
        ),
    )
    enforcer = ContractEnforcer.load(path, mode="draft")

    @enforcer.gate("file_undelete", "side_effect")
    def undelete_file() -> str:
        return "restored"

    # "undelete" is not the closed-set token "delete", so no implicit gate.
    assert undelete_file() == "restored"


def test_reversible_declared_side_effect_is_not_implicitly_gated(
    tmp_path: Path,
) -> None:
    path = _draft_fixture(
        tmp_path / "contract.yaml",
        side_effects=(
            {"type": "cache_write", "resource": "cache"},
        ),
    )
    enforcer = ContractEnforcer.load(path, mode="draft")

    @enforcer.gate("cache_write", "side_effect")
    def write_cache() -> str:
        return "cached"

    assert write_cache() == "cached"


def test_draft_mode_does_not_relax_lifecycle_validation(
    tmp_path: Path,
) -> None:
    path = _draft_fixture(tmp_path / "contract.yaml")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "mode: request-response", "mode: free-for-all"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ContractValidationError):
        ContractEnforcer.load(path, mode="draft")


# ---------------------------------------------------------------------------
# RFC 0005 §3.3: registry draft entries and chain compatibility
# ---------------------------------------------------------------------------


def test_draft_entry_preserves_content_and_sets_the_flag(
    tmp_path: Path,
) -> None:
    path = _draft_fixture(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)
    enforcer = ContractEnforcer.load(path, mode="draft")

    entry = enforcer.register(registry)

    assert entry.draft is True
    assert entry.content["provisional"] is True
    assert entry.promotion is None


def test_full_entry_serializes_without_the_new_fields(
    tmp_path: Path,
) -> None:
    path = _contract(tmp_path / "contract.yaml")
    registry_path = tmp_path / "registry.jsonl"
    ContractEnforcer.load(path).register(ContractRegistry(registry_path))

    line = registry_path.read_text(encoding="utf-8").strip()

    assert '"draft"' not in line
    assert '"promotion"' not in line


def test_unpromoted_entry_canonical_bytes_are_unchanged() -> None:
    entry = RegistryEntry(
        entry_id="00000000-0000-0000-0000-000000000000",
        node_id=None,
        contract_hash="a" * 64,
        contract_source="file",
        registered_at="2026-01-01T00:00:00+00:00",
        version=1,
        content={"version": 1.1},
        path="C:/repo/contract.yaml",
        prev_hash="b" * 64,
    )

    payload = json.loads(canonical_entry_bytes(entry))

    assert "draft" not in payload
    assert "promotion" not in payload


def test_registry_load_fails_closed_on_a_draft_flag_mismatch(
    tmp_path: Path,
) -> None:
    path = _draft_fixture(tmp_path / "contract.yaml")
    registry_path = tmp_path / "registry.jsonl"
    ContractEnforcer.load(path, mode="draft").register(
        ContractRegistry(registry_path)
    )

    tampered = registry_path.read_text(encoding="utf-8").replace(
        '"draft":true', '"draft":false'
    )
    registry_path.write_text(tampered, encoding="utf-8")

    with pytest.raises(RegistryError, match="disagrees"):
        ContractRegistry(registry_path)


# ---------------------------------------------------------------------------
# RFC 0005 §4.4/§4.5: audit, trace, and governance marking
# ---------------------------------------------------------------------------


def test_trace_carries_provisional_only_when_true(tmp_path: Path) -> None:
    draft_path = _draft_fixture(tmp_path / "draft.yaml")
    draft = ContractEnforcer.load(draft_path, mode="draft")

    @draft.gate("github:issues:read", "permission")
    def read_issue() -> str:
        return "ok"

    read_issue()
    trace = trace_from_audit(
        draft.get_audit_log()[-1],
        node_id=None,
        contract_hash="a" * 64,
    )

    assert trace.provisional is True
    assert trace.to_dict()["provisional"] is True
    assert trace_from_audit(
        draft.get_audit_log()[0],
        node_id=None,
        contract_hash="a" * 64,
    ).provisional is True
    assert audit_from_trace(trace).provisional is True

    full_path = _contract(tmp_path / "full.yaml")
    full = ContractEnforcer.load(full_path)

    @full.gate("github:issues:read", "permission")
    def read_full() -> str:
        return "ok"

    read_full()
    full_trace = trace_from_audit(
        full.get_audit_log()[-1],
        node_id=None,
        contract_hash="b" * 64,
    )

    assert full_trace.provisional is None
    assert "provisional" not in full_trace.to_dict()


def test_trace_rejects_non_boolean_provisional() -> None:
    payload = TraceEntry(
        node_id=None,
        action_name="a",
        action_type="permission",
        declared=True,
        result="allowed",
        hash_of_contract="a" * 64,
        timestamp="2026-01-01T00:00:00+00:00",
        reason="r",
        contract_field_reference="p",
    ).to_dict()
    payload["provisional"] = None

    with pytest.raises(TraceError, match="provisional"):
        TraceEntry.from_dict(payload)


def test_governance_reports_provisional_and_renders_the_marker(
    tmp_path: Path,
) -> None:
    _draft_fixture(tmp_path / "contract.yaml")
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")

    report = scan_tree(tmp_path)
    text = render_report(report, encoding="utf-8")

    assert report.governance == "provisional"
    assert text.splitlines()[0].endswith("(score 100/100) [provisional]")
    assert "human review and promotion" in text
    assert "governance" not in report.to_dict()

    payload = report.to_dict()
    assert governance_status(payload) == "provisional"
    assert governance_report(payload)["contract_path"] == "contract.yaml"
    unified = unify_audit_report(payload)
    assert unified.summary["governance"]["status"] == "provisional"


def test_governance_warn_render_marks_provisional(tmp_path: Path) -> None:
    _draft_fixture(tmp_path / "contract.yaml")
    (tmp_path / "cleanup.sh").write_text("rm -rf /\n", encoding="utf-8")

    report = scan_tree(tmp_path)
    text = render_report(report, encoding="utf-8")

    assert report.governance == "provisional"
    header = text.splitlines()[0]
    assert header.startswith(("WARN  ", "FAIL  "))
    assert header.endswith("[provisional]")


def test_malformed_contract_fails_closed_to_ungoverned(tmp_path: Path) -> None:
    (tmp_path / "contract.yaml").write_text(
        "provisional: [unterminated\n", encoding="utf-8"
    )
    report = scan_tree(tmp_path)

    assert report.governance == "ungoverned"


# ---------------------------------------------------------------------------
# RFC 0005 §5.2: deterministic diff and confirmation
# ---------------------------------------------------------------------------


def test_promotion_diff_is_deterministic_and_pointer_based() -> None:
    changes = promotion_diff(
        {"version": 1.1, "provisional": True, "system": {"name": "x", "z": 1}},
        {"version": 1.1, "system": {"name": "x"}, "a/b": 2},
    )

    assert changes == [
        {"op": "add", "path": "/a~1b", "after": 2},
        {"op": "remove", "path": "/provisional", "before": True},
        {"op": "remove", "path": "/system/z", "before": 1},
    ]
    assert promotion_diff({"a": 1}, {"a": 1}) == []
    assert promotion_diff({"a": 1}, {"a": True}) != []
    assert diff_sha256(changes) == diff_sha256(list(changes))


def test_confirmation_requires_a_real_hex_prefix() -> None:
    digest = "a" * 64

    verify_promotion_confirmation(digest, "a" * 12)
    verify_promotion_confirmation(digest, ("A" * 12))

    for bad in (None, "", "yes", "a" * 11, "z" * 12, "b" * 12):
        with pytest.raises(ResealError) as excinfo:
            verify_promotion_confirmation(digest, bad)
        assert excinfo.value.step == "promotion"


# ---------------------------------------------------------------------------
# RFC 0005 §5.1/§5.3: human intent and transition table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reviewer,intent",
    [("", "why"), ("   ", "why"), ("alice", ""), ("alice", "   ")],
)
def test_promotion_intent_requires_non_empty_strings(
    reviewer: str, intent: str
) -> None:
    with pytest.raises(PromotionIntentError):
        PromotionIntent(reviewer=reviewer, intent=intent)


def test_draft_to_full_without_intent_is_refused(tmp_path: Path) -> None:
    path = _draft_fixture(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)
    ContractEnforcer.load(path, mode="draft").register(registry)
    path.write_text(
        path.read_text(encoding="utf-8").replace("provisional: true\n", ""),
        encoding="utf-8",
    )

    with pytest.raises(ResealError) as excinfo:
        reseal(path, registry)

    assert excinfo.value.step == "promotion"
    assert "PromotionIntent" in excinfo.value.reason
    assert len(_rows(tmp_path / "registry.jsonl")) == 1


def test_promotion_is_never_silent_or_automatic(tmp_path: Path) -> None:
    path = _draft_fixture(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)

    with pytest.raises(ResealError, match="still provisional"):
        reseal(
            path,
            registry,
            promotion=PromotionIntent(reviewer="alice", intent="why"),
        )


def test_intent_cannot_promote_a_still_provisional_contract(
    tmp_path: Path,
) -> None:
    path = _draft_fixture(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)
    ContractEnforcer.load(path, mode="draft").register(registry)

    with pytest.raises(ResealError, match="still provisional"):
        reseal(
            path,
            registry,
            promotion=PromotionIntent(reviewer="alice", intent="why"),
        )


def test_next_draft_version_needs_no_intent(tmp_path: Path) -> None:
    path = _draft_fixture(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)
    ContractEnforcer.load(path, mode="draft").register(registry)

    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "name: ge2-agent", "name: ge2-agent-v2"
        ),
        encoding="utf-8",
    )
    result = reseal(path, registry)

    assert result.record.version == 2
    assert result.record.draft is True
    assert result.record.promotion is None


def test_full_to_provisional_demotion_is_refused(tmp_path: Path) -> None:
    path = _contract(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)
    reseal(path, registry)

    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "version: 1.1", "version: 1.1\nprovisional: true"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ResealError, match="demoted"):
        reseal(path, registry, promotion=None)


def test_intent_on_an_ordinary_reseal_is_refused(tmp_path: Path) -> None:
    path = _contract(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)
    reseal(path, registry)

    with pytest.raises(ResealError, match="not a promotion"):
        reseal(
            path,
            registry,
            promotion=PromotionIntent(reviewer="alice", intent="why"),
        )


# ---------------------------------------------------------------------------
# RFC 0005 §5.3/§5.4: promotion receipt and registry evidence
# ---------------------------------------------------------------------------


def test_promotion_records_receipt_and_compact_block(tmp_path: Path) -> None:
    draft = _draft_fixture(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)
    draft_entry = ContractEnforcer.load(draft, mode="draft").register(registry)
    draft.write_text(
        draft.read_text(encoding="utf-8").replace("provisional: true\n", ""),
        encoding="utf-8",
    )

    result = reseal(
        draft,
        registry,
        promotion=PromotionIntent(
            reviewer="alice",
            intent="Reviewed inferred boundary.",
            reference="https://example.test/pr/1",
        ),
    )
    receipt = result.promotion_receipt
    promoted_entry = registry.get_latest_by_path(draft.resolve())

    assert receipt is not None
    assert result.record.promotion == promoted_entry.promotion
    assert receipt.from_entry_id == draft_entry.entry_id
    assert receipt.to_entry_id == promoted_entry.entry_id
    assert receipt.from_version == 1
    assert receipt.to_version == 2
    assert receipt.from_contract_hash == draft_entry.contract_hash
    assert receipt.to_contract_hash == promoted_entry.contract_hash
    assert receipt.diff == (
        {"op": "remove", "path": "/provisional", "before": True},
    )
    assert receipt.diff_sha256 == diff_sha256(list(receipt.diff))

    block = promoted_entry.promotion
    assert set(block) == {
        "reviewer",
        "intent",
        "reference",
        "from_entry_id",
        "from_version",
        "from_contract_hash",
        "diff_sha256",
    }
    assert block["reviewer"] == "alice"
    assert block["diff_sha256"] == receipt.diff_sha256
    assert promoted_entry.draft is False

    # A verifier reconstructs the same diff from the two registry entries.
    assert diff_sha256(
        promotion_diff(draft_entry.content, promoted_entry.content)
    ) == receipt.diff_sha256
    assert ContractEnforcer.load(draft, registry=registry).is_provisional is False


def test_promotion_receipt_is_frozen(tmp_path: Path) -> None:
    path = _draft_fixture(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)
    _, result = _promote(path, registry)

    with pytest.raises(Exception):
        result.promotion_receipt.reviewer = "mallory"  # type: ignore[misc]


def test_registry_refuses_a_fabricated_promotion_block(
    tmp_path: Path,
) -> None:
    path = _draft_fixture(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)
    ContractEnforcer.load(path, mode="draft").register(registry)
    draft_entry = registry.get_latest_by_path(path.resolve())
    path.write_text(
        path.read_text(encoding="utf-8").replace("provisional: true\n", ""),
        encoding="utf-8",
    )

    block = {
        "reviewer": "mallory",
        "intent": "fabricated",
        "reference": None,
        "from_entry_id": draft_entry.entry_id,
        "from_version": draft_entry.version,
        "from_contract_hash": draft_entry.contract_hash,
        "diff_sha256": "0" * 64,
    }
    wrong = dict(block, from_entry_id="not-the-draft")
    enforcer = ContractEnforcer.load(path)

    with pytest.raises(RegistryError, match="from_entry_id"):
        registry.register(enforcer, promotion=wrong)
    with pytest.raises(RegistryError, match="from_contract_hash"):
        registry.register(
            enforcer,
            promotion=dict(block, from_contract_hash="c" * 64),
        )

    # A full entry with no draft predecessor cannot claim a promotion either.
    other_registry = _registry(tmp_path / "other")
    with pytest.raises(RegistryError, match="latest entry to be a draft"):
        other_registry.register(
            ContractEnforcer.load(_contract(tmp_path / "full2.yaml")),
            promotion=block,
        )


# ---------------------------------------------------------------------------
# CLI: init --infer and promote
# ---------------------------------------------------------------------------


def test_init_infer_writes_a_provisional_contract_without_executing(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "cleanup.sh").write_text(
        f"touch {tmp_path / 'executed'}\nrm -rf /\n", encoding="utf-8"
    )
    (target / "boom.py").write_text(
        "raise SystemExit('must not import target code')\n", encoding="utf-8"
    )
    output = tmp_path / "contract.yaml"

    assert run_init(output, infer=target) == 0

    text = output.read_text(encoding="utf-8")
    assert "provisional: true" in text
    assert not (tmp_path / "executed").exists()
    assert validate_contract(output).valid

    draft = ContractEnforcer.load(output, mode="draft")
    assert draft.is_provisional is True
    with pytest.raises(ProvisionalContractError):
        ContractEnforcer.load(output)


def test_promote_command_refuses_a_provisional_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _draft_fixture(tmp_path / "contract.yaml")

    assert (
        run_promote(
            path,
            tmp_path / "registry.jsonl",
            reviewer="alice",
            intent="why",
            confirm="a" * 12,
        )
        == 1
    )
    assert "still provisional" in capsys.readouterr().err


def test_promote_command_requires_an_existing_registry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _contract(tmp_path / "contract.yaml")

    assert (
        run_promote(
            path,
            tmp_path / "missing.jsonl",
            reviewer="alice",
            intent="why",
            confirm="a" * 12,
        )
        == 2
    )
    assert "registry not found" in capsys.readouterr().err


def test_promote_command_prints_diff_and_enforces_confirmation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _draft_fixture(tmp_path / "contract.yaml")
    registry_path = tmp_path / "registry.jsonl"
    registry = ContractRegistry(registry_path)
    ContractEnforcer.load(path, mode="draft").register(registry)
    path.write_text(
        path.read_text(encoding="utf-8").replace("provisional: true\n", ""),
        encoding="utf-8",
    )

    assert (
        run_promote(
            path,
            registry_path,
            reviewer="alice",
            intent="why",
            confirm="deadbeefdead",
        )
        == 2
    )
    captured = capsys.readouterr()
    assert "Promotion diff" in captured.out
    assert "diff_sha256:" in captured.out
    assert "does not match" in captured.err
    assert len(_rows(registry_path)) == 1

    first = run_promote(
        path,
        registry_path,
        reviewer="alice",
        intent="why",
        confirm="0" * 12,
    )
    assert first == 2
    printed = capsys.readouterr().out
    prefix = printed.split("diff_sha256: ")[1].splitlines()[0][:12]

    assert (
        run_promote(
            path,
            registry_path,
            reviewer="alice",
            intent="Reviewed inferred boundary.",
            reference="https://example.test/pr/1",
            confirm=prefix,
        )
        == 0
    )
    success = capsys.readouterr().out
    assert "Promotion receipt" in success
    assert "PROMOTED" in success

    rows = _rows(registry_path)
    assert "draft" not in rows[-1]
    assert rows[-1]["promotion"]["reviewer"] == "alice"

    assert (
        run_promote(
            path,
            registry_path,
            reviewer="alice",
            intent="again",
            confirm=prefix,
        )
        == 1
    )


def test_promote_cli_requires_confirm_argument() -> None:
    from scyvera.cli import build_parser

    with pytest.raises(SystemExit) as excinfo:
        build_parser().parse_args(
            ["promote", "contract.yaml", "--registry", "r.jsonl",
             "--reviewer", "alice", "--intent", "why"]
        )
    assert excinfo.value.code == 2
