"""Re-seal ritual for contract regeneration (roadmap M1.4, T12).

Threat T12 (contract substitution via prompt injection) treats regeneration as
a *status change event*, not an ordinary file write. This module is the single
sanctioned path: a regenerated contract must be validated, linted with zero
errors, registered as a new registry version, and only then handed back as a
governable enforcer. The frozen :class:`ResealRecord` is the warning-audit
record for that transition; it is deliberately timestamp-free because the
provenance datetime already lives in the registry entry.

Invariant (roadmap M1.4): **no path rebuilds an enforcer without going through
:func:`reseal` or explicitly disabling the ritual via the documented dev flag**
(:meth:`scyvera.enforcer.ContractEnforcer.load` /
:meth:`~scyvera.enforcer.ContractEnforcer.from_declaration`
``allow_unsealed_reseal=True``, default ``False``). A contract that was already
registered and now hashes differently is a regeneration; ``load()`` refuses it
unless that flag is set, so production flows cannot silently bypass this
ritual.

The ritual is pure orchestration: no printing, no wall-clock values, no
mutable module state. Lint warnings are logged and preserved in the record.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Optional, Union

from .enforcer import (
    ContractEnforcer,
    IDENTITY_MATCHES_REGISTRY,
)
from .exceptions import RegistryError, ResealError
from .linter import LintWarning, lint_contract
from .registry import ContractRegistry, RegistryEntry
from .validator import validate_contract

__all__ = [
    "RESEAL_AUDIT_NOTE",
    "ResealRecord",
    "ResealResult",
    "reseal",
]

logger = logging.getLogger("scyvera.reseal")

#: Module-level audit note for reviewers and integrators.
RESEAL_AUDIT_NOTE = (
    "A contract regeneration is a status change event (T12). The only "
    "governance-valid rebuild path is reseal(): validate -> lint with zero "
    "errors -> register a new version -> fresh enforcer. Direct loaders may "
    "only bypass it with the documented allow_unsealed_reseal=True dev flag."
)


@dataclass(frozen=True)
class ResealRecord:
    """Frozen warning-audit record for one completed re-seal ritual.

    No wall-clock field is included: the registry entry's ``registered_at``
    already records provenance. ``lint_warnings`` preserves every ACxxx warning
    seen during step (b), whether or not it blocked the ritual (only
    ``severity == "error"`` blocks). ``reused_existing_entry`` is true when the
    contract content was byte-identical to an already-registered entry, which
    is the idempotent re-seal case.
    """

    canonical_path: Path
    contract_hash: str
    entry_id: str
    version: int
    node_id: Optional[str]
    contract_source: str
    lint_warnings: tuple[LintWarning, ...]
    reused_existing_entry: bool


@dataclass(frozen=True)
class ResealResult:
    """Result of :func:`reseal`: the record plus the freshly sealed enforcer.

    The enforcer is built only after registration succeeds and carries a
    ``matches-registry`` identity receipt. The frozen record proves what the
    ritual did and is suitable for an audit log.
    """

    enforcer: ContractEnforcer
    record: ResealRecord


def _as_registry(
    registry: Union[ContractRegistry, str, Path],
) -> ContractRegistry:
    """Normalize a registry instance or path for the ritual."""
    if isinstance(registry, ContractRegistry):
        return registry
    if isinstance(registry, (str, Path)):
        return ContractRegistry(path=str(registry))
    raise TypeError(
        "registry must be a ContractRegistry or a str/Path; "
        f"got {type(registry).__name__}"
    )


def reseal(
    new_contract_path: str | Path,
    registry: Union[ContractRegistry, str, Path],
) -> ResealResult:
    """Run the M1.4 re-seal ritual and return a governable enforcer.

    Steps, each fail-closed:

    1. ``validate_contract`` must pass (step ``validate``).
    2. ``lint_contract`` must report zero error-severity warnings; ordinary
       warnings are logged and recorded (step ``lint``).
    3. The registry chain is verified, the contract is sealed and hashed, and
       ``ContractRegistry.register`` runs idempotently. Identical content
       reuses the existing entry; changed content must produce the next
       version for the same canonical path (step ``register``). A skipped or
       partial registration raises instead of returning an enforcer.
    4. A frozen, timestamp-free :class:`ResealRecord` is produced (step
       ``record``).
    5. A fresh enforcer is loaded against the registry and must report
       ``matches-registry`` before it is returned (step ``identity``).

    Args:
        new_contract_path: The regenerated ``contract.yaml`` to seal.
        registry: A :class:`~scyvera.registry.ContractRegistry` or its path.

    Returns:
        :class:`ResealResult` with the new enforcer and the audit record.

    Raises:
        ResealError: If any step fails, including skipped registration,
            a legacy/non-chain registry, or an unexpected version transition.
        TypeError: If ``registry`` is neither a registry nor a path.
    """
    path = Path(new_contract_path)

    # (a) Structural validation before anything is registered (T12).
    try:
        validation = validate_contract(path)
    except Exception as exc:
        raise ResealError(
            "validate",
            f"contract '{path}' could not be validated: {exc}",
        ) from exc
    if not validation.valid:
        details = "; ".join(
            f"{error.path}: {error.message}" if error.path else error.message
            for error in validation.errors
        )
        raise ResealError(
            "validate",
            f"contract '{path}' failed validation and was not registered: {details}",
        )

    # (b) Lint must be error-free; warnings are allowed and recorded.
    try:
        lint_result = lint_contract(path)
    except Exception as exc:
        raise ResealError(
            "lint",
            f"contract '{path}' could not be linted: {exc}",
        ) from exc
    lint_errors = tuple(
        warning
        for warning in lint_result.warnings
        if warning.severity == "error"
    )
    if not lint_result.valid_structure or lint_errors:
        details = "; ".join(
            f"{warning.rule_id}: {warning.message}" for warning in lint_errors
        ) or "structural validation failed during lint"
        raise ResealError(
            "lint",
            f"contract '{path}' has lint errors and was not registered: {details}",
        )
    for warning in lint_result.warnings:
        logger.warning(
            "Re-seal lint %s (%s): %s",
            warning.rule_id,
            warning.title,
            warning.message,
        )

    # (c) Register the sealed contract on a chain-intact registry.
    registry_obj = _as_registry(registry)
    try:
        registry_obj.verify_chain()
    except RegistryError as exc:
        raise ResealError(
            "register",
            f"registry chain is not intact, refusing to append: {exc}",
        ) from exc

    try:
        candidate = ContractEnforcer.load(path, allow_unsealed_reseal=True)
    except Exception as exc:
        raise ResealError(
            "seal",
            f"contract '{path}' could not be sealed: {exc}",
        ) from exc

    canonical_path = candidate.contract_identity.canonical_path
    if canonical_path is None:  # pragma: no cover - load() always pins a path
        raise ResealError("seal", "sealed contract has no canonical path")

    previous: Optional[RegistryEntry] = registry_obj.get_latest_by_path(
        canonical_path
    )
    try:
        entry = registry_obj.register(candidate)
    except Exception as exc:
        raise ResealError(
            "register",
            f"registry refused the re-seal of '{canonical_path}': {exc}",
        ) from exc

    if entry is None or entry.contract_hash != candidate.integrity_hash:
        raise ResealError(
            "register",
            "registry did not return a sealed entry for this contract; "
            "the registration step was skipped",
        )
    if not registry_obj.has_hash(candidate.integrity_hash):
        raise ResealError(
            "register",
            "registry did not persist this contract; "
            "the registration step was partial",
        )

    reused = previous is not None and entry.entry_id == previous.entry_id
    if previous is not None:
        expected_version = previous.version if reused else previous.version + 1
        if entry.version != expected_version:
            raise ResealError(
                "register",
                f"expected registry version {expected_version}, got "
                f"{entry.version}; registration was partial",
            )
    elif entry.version != 1:
        raise ResealError(
            "register",
            f"first registration must be version 1, got {entry.version}",
        )

    # (d) Frozen warning-audit record (timestamp-free by design).
    record = ResealRecord(
        canonical_path=canonical_path,
        contract_hash=entry.contract_hash,
        entry_id=entry.entry_id,
        version=entry.version,
        node_id=entry.node_id,
        contract_source=entry.contract_source,
        lint_warnings=tuple(lint_result.warnings),
        reused_existing_entry=reused,
    )

    # (e) Only after registration succeeds is a fresh enforcer built/returned.
    try:
        fresh = ContractEnforcer.load(path, registry=registry_obj)
    except Exception as exc:
        raise ResealError(
            "identity",
            f"fresh enforcer could not confirm the registered identity: {exc}",
        ) from exc
    if fresh.contract_identity.crosscheck != IDENTITY_MATCHES_REGISTRY:
        raise ResealError(
            "identity",
            "fresh enforcer did not match the registry entry; "
            "registration was skipped or raced",
        )
    fresh._registry_entry_id = entry.entry_id

    logger.info(
        "Re-seal complete for '%s': version %s, entry %s (%s).",
        canonical_path,
        record.version,
        record.entry_id,
        "reused existing entry" if reused else "new entry",
    )
    return ResealResult(enforcer=fresh, record=record)
