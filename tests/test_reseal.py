"""Re-seal ritual tests (roadmap M1.4, T12).

Pins the roadmap acceptance cases:

- a valid regeneration passes the full ritual and yields a new registered
  version plus a working enforcer;
- skipped or partial registration is rejected instead of returning a
  governable enforcer;
- an invalid/tampered contract is rejected in step (a), before anything is
  registered;
- re-sealing byte-identical content is idempotent (no duplicate append);
- the documented ``allow_unsealed_reseal`` dev flag is the only way to load a
  divergent contract outside ``reseal()``.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from scyvera import (
    ContractEnforcer,
    ContractRegistry,
    ContractViolationError,
    IDENTITY_MATCHES_REGISTRY,
    LintResult,
    LintWarning,
    ResealError,
    reseal,
)


def _write_contract(
    path: Path,
    *,
    name: str = "reseal-agent",
    purpose: str = "reseal fixture",
    permissions: tuple[str, ...] = ("tasks:read",),
    side_effects: tuple[str, ...] = (),
) -> Path:
    """Write a minimal schema-valid v1.1 contract and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    permission_lines = "".join(
        f"  - resource: {permission.split(':')[0]}\n"
        f"    actions: [{permission.split(':', 1)[1]}]\n"
        for permission in permissions
    )
    side_effect_lines = "".join(
        f"  - type: {effect}\n    resource: {name}\n"
        for effect in side_effects
    )
    side_effect_block = side_effect_lines or "  []\n"
    path.write_text(
        "version: 1.1\n"
        "system:\n"
        f"  name: {name}\n"
        f"  purpose: {purpose}\n"
        "lifecycle:\n"
        "  mode: request-response\n"
        "permissions:\n"
        f"{permission_lines}"
        f"side_effects:\n{side_effect_block}"
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
    return ContractRegistry(path=str(tmp_path / "registry.jsonl"))


def _rows(registry_path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in registry_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ---------------------------------------------------------------------------
# Happy path: valid regeneration creates version N+1
# ---------------------------------------------------------------------------


def test_valid_regeneration_registers_new_version_and_working_enforcer(
    tmp_path: Path,
) -> None:
    contract = _write_contract(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)
    original = ContractEnforcer.load(contract)
    first_entry = original.register(registry)
    assert first_entry.version == 1

    _write_contract(contract, purpose="regenerated under the ritual")

    result = reseal(contract, registry)
    record = result.record
    enforcer = result.enforcer

    assert record.canonical_path == contract.resolve()
    assert record.version == first_entry.version + 1
    assert record.reused_existing_entry is False
    assert record.contract_hash == enforcer.integrity_hash
    assert record.entry_id == enforcer.registry_entry_id
    assert record.contract_source == "file"
    assert record.lint_warnings == ()

    history = registry.get_history_by_path(contract)
    assert [entry.version for entry in history] == [1, 2]
    assert registry.get_latest_by_path(contract).contract_hash == record.contract_hash
    assert registry.verify_chain() is True

    assert enforcer.contract_identity.crosscheck == IDENTITY_MATCHES_REGISTRY
    assert enforcer.contract_identity.registry_entry_id == record.entry_id

    @enforcer.gate("tasks:read", "read")
    def read_task() -> str:
        return "governed"

    assert read_task() == "governed"


def test_lint_warnings_are_recorded_but_do_not_block(tmp_path: Path) -> None:
    contract = _write_contract(
        tmp_path / "contract.yaml",
        permissions=("tasks:write",),
    )
    registry = _registry(tmp_path)

    result = reseal(contract, registry)

    assert result.record.version == 1
    assert result.record.lint_warnings
    assert all(
        warning.severity == "warning"
        for warning in result.record.lint_warnings
    )
    assert any(warning.rule_id == "AC101" for warning in result.record.lint_warnings)


# ---------------------------------------------------------------------------
# Fail-closed paths
# ---------------------------------------------------------------------------


def test_skipped_registration_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _write_contract(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)
    monkeypatch.setattr(registry, "register", lambda enforcer: None)

    with pytest.raises(ResealError) as excinfo:
        reseal(contract, registry)

    assert excinfo.value.step == "register"
    assert "skipped" in excinfo.value.reason
    assert registry.size() == 0


def test_partial_registration_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _write_contract(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)
    real_register = registry.register
    calls: list[str] = []

    def register_without_persisting(enforcer):
        calls.append("called")
        return real_register(enforcer)

    monkeypatch.setattr(registry, "has_hash", lambda contract_hash: False)
    monkeypatch.setattr(registry, "register", register_without_persisting)

    with pytest.raises(ResealError) as excinfo:
        reseal(contract, registry)

    assert excinfo.value.step == "register"
    assert "partial" in excinfo.value.reason
    assert calls == ["called"]


def test_invalid_contract_is_rejected_before_registration(tmp_path: Path) -> None:
    contract = tmp_path / "contract.yaml"
    contract.write_text(
        "version: 1.1\n"
        "system:\n"
        "  name: broken-agent\n"
        "permissions: not-a-list\n",
        encoding="utf-8",
    )
    registry = _registry(tmp_path)

    with pytest.raises(ResealError) as excinfo:
        reseal(contract, registry)

    assert excinfo.value.step == "validate"
    assert registry.size() == 0
    assert not (tmp_path / "registry.jsonl").read_text(encoding="utf-8").strip()


def test_lint_error_is_rejected_before_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _write_contract(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)

    def lint_with_error(path):
        return LintResult(
            valid_structure=True,
            warnings=(
                LintWarning(
                    rule_id="AC999",
                    title="Synthetic lint error",
                    message="deliberately injected for the fail-closed test",
                    severity="error",
                ),
            ),
        )

    monkeypatch.setattr(
        importlib.import_module("scyvera.reseal"),
        "lint_contract",
        lint_with_error,
    )

    with pytest.raises(ResealError) as excinfo:
        reseal(contract, registry)

    assert excinfo.value.step == "lint"
    assert registry.size() == 0


def test_legacy_registry_refuses_to_reseal(tmp_path: Path) -> None:
    contract = _write_contract(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)
    ContractEnforcer.load(contract).register(registry)

    registry_path = tmp_path / "registry.jsonl"
    rows = _rows(registry_path)
    for row in rows:
        row.pop("prev_hash", None)
    registry_path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    legacy = ContractRegistry(path=str(registry_path))

    with pytest.raises(ResealError) as excinfo:
        reseal(contract, legacy)

    assert excinfo.value.step == "register"
    assert "chain is not intact" in excinfo.value.reason


# ---------------------------------------------------------------------------
# Idempotency and the documented dev flag
# ---------------------------------------------------------------------------


def test_resealing_same_content_is_idempotent(tmp_path: Path) -> None:
    contract = _write_contract(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)
    registry_path = tmp_path / "registry.jsonl"

    first = reseal(contract, registry)
    before_bytes = registry_path.read_bytes()

    second = reseal(contract, registry)

    assert second.record.reused_existing_entry is True
    assert second.record.entry_id == first.record.entry_id
    assert second.record.version == first.record.version
    assert registry.size() == 1
    assert registry_path.read_bytes() == before_bytes
    assert registry.verify_chain() is True


def test_dev_flag_is_the_only_way_to_load_a_divergent_contract(
    tmp_path: Path,
) -> None:
    contract = _write_contract(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)
    ContractEnforcer.load(contract).register(registry)

    _write_contract(contract, purpose="regenerated outside the ritual")

    with pytest.raises(ContractViolationError) as excinfo:
        ContractEnforcer.load(contract, registry=registry)
    assert "reseal" in str(excinfo.value)

    allowed = ContractEnforcer.load(
        contract,
        registry=registry,
        allow_unsealed_reseal=True,
    )
    assert allowed.contract_identity.reseal_authorized is True

    # Declarations expose the same documented marker without changing the
    # default path.
    default_decl = ContractEnforcer.from_declaration(
        {"node_id": "dev-flag-v1", "permissions": ["github.read"]}
    )
    dev_decl = ContractEnforcer.from_declaration(
        {"node_id": "dev-flag-v1", "permissions": ["github.read"]},
        allow_unsealed_reseal=True,
    )
    assert default_decl.contract_identity.reseal_authorized is False
    assert dev_decl.contract_identity.reseal_authorized is True
