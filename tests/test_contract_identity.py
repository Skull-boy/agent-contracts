"""Contract identity pinning tests (roadmap M1.3, T12/T14).

Covers the roadmap acceptance scenarios:

- a symlink that escapes the addressed directory raises
  ``ContractViolationError`` before the contract is sealed;
- a symlink that stays inside the addressed directory loads and is recorded
  in the frozen identity receipt;
- replacing that symlink after load makes ``verify_integrity()`` fail with
  ``ContractTamperError`` even though the original target is untouched;
- an unregistered contract logs a warning and records it in the typed result;
- registered + matching gets a clean receipt, registered + stale warns;
- a plain ``load(path)`` with no registry argument behaves exactly as before.

The registry cross-check is intentionally path-keyed for file contracts
(``node_id`` is ``None`` for them), and the M1.4 re-seal boundary is pinned
here too: a genuinely divergent regeneration is refused unless the documented
dev flag is set.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import logging
from pathlib import Path

import pytest

from scyvera import (
    ContractEnforcer,
    ContractRegistry,
    ContractTamperError,
    ContractViolationError,
    IDENTITY_DIVERGENT_REGISTRY,
    IDENTITY_MATCHES_REGISTRY,
    IDENTITY_NOT_CHECKED,
    IDENTITY_STALE_REGISTRY,
    IDENTITY_UNREGISTERED,
)


def _write_contract(
    path: Path,
    *,
    name: str = "test-agent",
    purpose: str = "identity fixture",
    permissions: tuple[str, ...] = ("tasks:read",),
) -> Path:
    """Write a minimal schema-valid v1.1 contract and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    permission_lines = "".join(
        f"  - resource: {permission.split(':')[0]}\n"
        f"    actions: [{permission.split(':', 1)[1]}]\n"
        for permission in permissions
    )
    path.write_text(
        "version: 1.1\n"
        "system:\n"
        f"  name: {name}\n"
        f"  purpose: {purpose}\n"
        "lifecycle:\n"
        "  mode: request-response\n"
        "permissions:\n"
        f"{permission_lines}"
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


def _symlink_or_skip(
    link: Path,
    target: Path,
    *,
    target_is_directory: bool = False,
) -> None:
    """Create a symlink or skip with the existing house convention."""
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this platform")


def _registry(tmp_path: Path) -> ContractRegistry:
    return ContractRegistry(path=str(tmp_path / "registry.jsonl"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# T14: symlink refusal and pinning
# ---------------------------------------------------------------------------


def test_symlink_escape_raises_contract_violation(tmp_path: Path) -> None:
    outside = _write_contract(tmp_path / "outside" / "contract.yaml")
    addressed = tmp_path / "addressed"
    addressed.mkdir()
    link = addressed / "contract.yaml"
    _symlink_or_skip(link, outside)

    with pytest.raises(ContractViolationError) as excinfo:
        ContractEnforcer.load(link)

    assert excinfo.value.action_name == "load"
    assert excinfo.value.reason is not None
    assert "T14" in str(excinfo.value)
    assert "outside the addressed directory" in str(excinfo.value)


def test_same_directory_symlink_loads_and_is_recorded(tmp_path: Path) -> None:
    real = _write_contract(tmp_path / "real.yaml")
    link = tmp_path / "contract.yaml"
    _symlink_or_skip(link, real)

    enforcer = ContractEnforcer.load(link)
    identity = enforcer.contract_identity

    assert identity.canonical_path == real.resolve()
    assert identity.requested_path == link.absolute()
    assert identity.resolved_symlink is True
    assert identity.load_hash == _sha256(real)
    assert identity.crosscheck == IDENTITY_NOT_CHECKED
    assert enforcer.contract_path == real.resolve()

    @enforcer.gate("tasks:read", "read")
    def read_task() -> str:
        return "ok"

    assert read_task() == "ok"


def test_post_load_symlink_replacement_fails_verify_integrity(
    tmp_path: Path,
) -> None:
    real = _write_contract(tmp_path / "real.yaml")
    replacement = _write_contract(
        tmp_path / "replacement.yaml",
        name="other-agent",
        purpose="replacement target",
    )
    link = tmp_path / "contract.yaml"
    _symlink_or_skip(link, real)

    enforcer = ContractEnforcer.load(link)
    assert enforcer.verify_integrity() is True

    # Swap the link after load. The original target is byte-identical, so only
    # the pinned requested-path resolution can catch this (T14).
    link.unlink()
    _symlink_or_skip(link, replacement)

    with pytest.raises(ContractTamperError) as excinfo:
        enforcer.verify_integrity()
    assert "resolves to" in str(excinfo.value)
    assert "T14" in str(excinfo.value)

    @enforcer.gate("tasks:read", "read")
    def read_task() -> str:  # pragma: no cover - body must never run
        return "should not run"

    with pytest.raises(ContractTamperError):
        read_task()


# ---------------------------------------------------------------------------
# T12: registry cross-check receipts
# ---------------------------------------------------------------------------


def test_unregistered_contract_warns_and_records_typed_receipt(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    contract = _write_contract(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)

    with caplog.at_level(logging.WARNING, logger="scyvera.enforcer"):
        enforcer = ContractEnforcer.load(contract, registry=registry)

    identity = enforcer.contract_identity
    assert identity.crosscheck == IDENTITY_UNREGISTERED
    assert identity.registry_entry_id is None
    assert len(identity.warnings) == 1
    assert "never been registered" in identity.warnings[0]
    assert "never been registered" in caplog.text

    # Governance still works on first load; the warning is permanent in the
    # identity receipt rather than a quiet log line.
    @enforcer.gate("tasks:read", "read")
    def read_task() -> str:
        return "ok"

    assert read_task() == "ok"


def test_registered_matching_contract_gets_clean_receipt(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    contract = _write_contract(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)
    entry = ContractEnforcer.load(contract).register(registry)

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="scyvera.enforcer"):
        enforcer = ContractEnforcer.load(contract, registry=registry)

    identity = enforcer.contract_identity
    assert identity.crosscheck == IDENTITY_MATCHES_REGISTRY
    assert identity.registry_entry_id == entry.entry_id
    assert identity.registry_version == entry.version
    assert identity.warnings == ()
    assert caplog.text == ""


def test_registered_stale_contract_warns_without_blocking(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    contract = _write_contract(tmp_path / "contract.yaml")
    original_bytes = contract.read_bytes()
    registry = _registry(tmp_path)
    ContractEnforcer.load(contract).register(registry)

    _write_contract(
        contract,
        purpose="revision two",
        permissions=("tasks:read", "tasks:write"),
    )
    ContractEnforcer.load(contract).register(registry)

    # Roll the file back to the first version: it is registered, but stale
    # relative to the latest intent. That is a warning, not a block.
    contract.write_bytes(original_bytes)

    with caplog.at_level(logging.WARNING, logger="scyvera.enforcer"):
        enforcer = ContractEnforcer.load(contract, registry=registry)

    identity = enforcer.contract_identity
    assert identity.crosscheck == IDENTITY_STALE_REGISTRY
    assert identity.is_registered is True
    assert identity.registry_version == 2
    assert len(identity.warnings) == 1
    assert "older registry entry" in identity.warnings[0]
    assert "older registry entry" in caplog.text


def test_registry_path_string_is_accepted(tmp_path: Path) -> None:
    contract = _write_contract(tmp_path / "contract.yaml")
    registry_path = tmp_path / "registry.jsonl"

    enforcer = ContractEnforcer.load(contract, registry=str(registry_path))

    assert enforcer.contract_identity.crosscheck == IDENTITY_UNREGISTERED
    assert registry_path.exists()


# ---------------------------------------------------------------------------
# Regression pin: default load is unchanged, and M1.4 blocks regeneration
# ---------------------------------------------------------------------------


def test_default_load_without_registry_is_unchanged(tmp_path: Path) -> None:
    contract = _write_contract(tmp_path / "contract.yaml")

    enforcer = ContractEnforcer.load(contract)
    identity = enforcer.contract_identity

    assert identity.crosscheck == IDENTITY_NOT_CHECKED
    assert identity.resolved_symlink is False
    assert identity.reseal_authorized is False
    assert identity.warnings == ()
    assert identity.load_hash == _sha256(contract)
    assert enforcer.integrity_hash == identity.load_hash
    assert enforcer.contract_path == contract.resolve()
    assert enforcer.verify_integrity() is True

    @enforcer.gate("tasks:read", "read")
    def read_task() -> str:
        return "ok"

    assert read_task() == "ok"

    with pytest.raises(ContractViolationError):
        @enforcer.gate("tasks:write", "permission")
        def write_task() -> str:  # pragma: no cover
            return "denied"

        write_task()


def test_divergent_regeneration_refused_without_dev_flag(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    contract = _write_contract(tmp_path / "contract.yaml")
    registry = _registry(tmp_path)
    ContractEnforcer.load(contract).register(registry)

    _write_contract(contract, purpose="regenerated outside the ritual")

    with pytest.raises(ContractViolationError) as excinfo:
        ContractEnforcer.load(contract, registry=registry)
    assert "reseal" in str(excinfo.value)
    assert "regeneration" in str(excinfo.value)

    with caplog.at_level(logging.WARNING, logger="scyvera.enforcer"):
        allowed = ContractEnforcer.load(
            contract,
            registry=registry,
            allow_unsealed_reseal=True,
        )

    identity = allowed.contract_identity
    assert identity.crosscheck == IDENTITY_DIVERGENT_REGISTRY
    assert identity.reseal_authorized is True
    assert len(identity.warnings) == 1
    assert "allow_unsealed_reseal=True" in caplog.text


def test_identity_receipt_is_frozen(tmp_path: Path) -> None:
    contract = _write_contract(tmp_path / "contract.yaml")
    identity = ContractEnforcer.load(contract).contract_identity

    with pytest.raises(FrozenInstanceError):
        identity.crosscheck = IDENTITY_MATCHES_REGISTRY  # type: ignore[misc]
