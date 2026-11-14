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
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Literal, Mapping, Optional, Union

from .enforcer import (
    ContractEnforcer,
    IDENTITY_MATCHES_REGISTRY,
)
from .exceptions import PromotionIntentError, RegistryError, ResealError
from .linter import LintWarning, lint_contract
from .registry import ContractRegistry, RegistryEntry
from .validator import load_contract, validate_contract

__all__ = [
    "PromotionIntent",
    "PromotionReceipt",
    "RESEAL_AUDIT_NOTE",
    "ResealRecord",
    "ResealResult",
    "diff_sha256",
    "promotion_diff",
    "reseal",
    "verify_promotion_confirmation",
]

logger = logging.getLogger("scyvera.reseal")

_OP_ORDER: Mapping[str, int] = {"add": 0, "remove": 1, "replace": 2}


@dataclass(frozen=True)
class PromotionIntent:
    """Explicit human intent required for a draft -> full promotion.

    RFC 0005 §5.1: no default reviewer, no default intent, and no environment,
    CI, prompt, or model-derived fallback. Both strings must be non-empty after
    stripping surrounding whitespace.
    """

    reviewer: str
    intent: str
    reference: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reviewer, str) or not self.reviewer.strip():
            raise PromotionIntentError(
                "reviewer", "reviewer must be a non-empty string"
            )
        if not isinstance(self.intent, str) or not self.intent.strip():
            raise PromotionIntentError(
                "intent", "intent must be a non-empty string"
            )
        if self.reference is not None and not isinstance(self.reference, str):
            raise PromotionIntentError(
                "reference", "reference must be a string or null"
            )
        object.__setattr__(self, "reviewer", self.reviewer.strip())
        object.__setattr__(self, "intent", self.intent.strip())
        if self.reference is not None:
            stripped = self.reference.strip()
            object.__setattr__(
                self, "reference", stripped if stripped else None
            )


@dataclass(frozen=True)
class PromotionReceipt:
    """Complete RFC 0005 §5.4 evidence for one draft -> full promotion."""

    receipt_version: int
    reviewer: str
    intent: str
    reference: str | None
    from_entry_id: str
    to_entry_id: str
    from_version: int
    to_version: int
    from_contract_hash: str
    to_contract_hash: str
    diff: tuple[dict[str, Any], ...]
    diff_sha256: str

    def to_dict(self) -> dict[str, Any]:
        """Return the RFC 0005 §5.4 JSON shape (diff as a JSON array)."""
        return {
            "receipt_version": self.receipt_version,
            "reviewer": self.reviewer,
            "intent": self.intent,
            "reference": self.reference,
            "from_entry_id": self.from_entry_id,
            "to_entry_id": self.to_entry_id,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "from_contract_hash": self.from_contract_hash,
            "to_contract_hash": self.to_contract_hash,
            "diff": [dict(change) for change in self.diff],
            "diff_sha256": self.diff_sha256,
        }


def _pointer_token(value: Any) -> str:
    """Escape one RFC 6901 JSON Pointer reference token."""
    return str(value).replace("~", "~0").replace("/", "~1")


def _json_equal(left: Any, right: Any) -> bool:
    """Compare two JSON values without Python's ``True == 1`` coercion."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is bool and type(right) is bool and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if type(left) is not type(right):
        return False
    return left == right


def _diff_values(
    before: Any,
    after: Any,
    path: str,
    changes: list[dict[str, Any]],
) -> None:
    """Recursively append RFC 0005 §5.2 change records."""
    if isinstance(before, dict) and isinstance(after, dict):
        for key in before:
            if key not in after:
                changes.append(
                    {
                        "op": "remove",
                        "path": f"{path}/{_pointer_token(key)}",
                        "before": before[key],
                    }
                )
        for key in after:
            child_path = f"{path}/{_pointer_token(key)}"
            if key not in before:
                changes.append(
                    {"op": "add", "path": child_path, "after": after[key]}
                )
            else:
                _diff_values(before[key], after[key], child_path, changes)
        return

    if isinstance(before, list) and isinstance(after, list):
        shared = min(len(before), len(after))
        for index in range(shared):
            _diff_values(
                before[index],
                after[index],
                f"{path}/{index}",
                changes,
            )
        for index in range(shared, len(after)):
            changes.append(
                {
                    "op": "add",
                    "path": f"{path}/{index}",
                    "after": after[index],
                }
            )
        for index in range(len(before) - 1, shared - 1, -1):
            changes.append(
                {
                    "op": "remove",
                    "path": f"{path}/{index}",
                    "before": before[index],
                }
            )
        return

    if not _json_equal(before, after):
        changes.append(
            {"op": "replace", "path": path, "before": before, "after": after}
        )


def _canonical_record(record: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(record),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def promotion_diff(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return the deterministic RFC 0005 §5.2 diff between two contents."""
    changes: list[dict[str, Any]] = []
    _diff_values(dict(before), dict(after), "", changes)
    changes.sort(
        key=lambda record: (
            record["path"],
            _OP_ORDER[record["op"]],
            _canonical_record(record),
        )
    )
    return changes


def diff_sha256(changes: list[Mapping[str, Any]]) -> str:
    """Return the SHA-256 of the canonical RFC 0005 §5.2 diff bytes."""
    payload = json.dumps(
        [dict(change) for change in changes],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_promotion_confirmation(
    expected_sha256: str,
    confirmation: str | None,
) -> None:
    """Check the operator's ``--confirm`` prefix against the diff hash.

    RFC 0005 §5.1/§5.5: confirmation must be at least the first 12 hex
    characters of ``diff_sha256``. A bare ``--yes``, an empty value, or a
    mismatched prefix fails closed with ``ResealError("promotion", ...)`` so
    the CLI cannot weaken the gate.
    """
    if confirmation is None or not confirmation.strip():
        raise ResealError(
            "promotion",
            "confirmation is required: pass --confirm <first 12+ hex of "
            "diff_sha256>; bare --yes/--force is not accepted",
        )
    prefix = confirmation.strip().lower()
    if len(prefix) < 12:
        raise ResealError(
            "promotion",
            f"confirmation prefix is too short ({len(prefix)} chars); "
            "supply at least 12 hex characters of diff_sha256",
        )
    if any(character not in "0123456789abcdef" for character in prefix):
        raise ResealError(
            "promotion",
            "confirmation must be hex characters from diff_sha256",
        )
    if not expected_sha256.startswith(prefix):
        raise ResealError(
            "promotion",
            f"confirmation prefix '{prefix}' does not match diff_sha256 "
            f"'{expected_sha256}'",
        )


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
    # RFC 0005 §5.3 additive fields at the end so keyword constructions keep
    # working. `promotion` mirrors the compact registry block when present.
    draft: bool = False
    promotion: dict | None = None


@dataclass(frozen=True)
class ResealResult:
    """Result of :func:`reseal`: the record plus the freshly sealed enforcer.

    The enforcer is built only after registration succeeds and carries a
    ``matches-registry`` identity receipt. The frozen record proves what the
    ritual did and is suitable for an audit log.
    """

    enforcer: ContractEnforcer
    record: ResealRecord
    promotion_receipt: PromotionReceipt | None = None


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
    *,
    promotion: PromotionIntent | None = None,
) -> ResealResult:
    """Run the re-seal ritual and return a governable enforcer.

    Implements roadmap M1.4 (T12) and RFC 0005 §5.3 (promotion). Steps, each
    fail-closed:

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

    Promotion (RFC 0005 §5.3) is expressed by passing ``promotion`` when the
    latest registry entry is a draft and the new file is full. The transition
    table is enforced before any append, the §5.2 diff is computed from the
    registry entry's recorded content (never the mutable file), and the
    compact promotion block is stored on the new full entry. A provisional
    contract can never be promoted, and a full contract can never be demoted.

    Args:
        new_contract_path: The regenerated ``contract.yaml`` to seal.
        registry: A :class:`~scyvera.registry.ContractRegistry` or its path.
        promotion: Explicit human :class:`PromotionIntent` for
            ``draft -> full``. Required for that transition and rejected for
            every other one.

    Returns:
        :class:`ResealResult` with the new enforcer and the audit record, plus
        the :class:`PromotionReceipt` for a promotion.

    Raises:
        ResealError: If any step fails, including skipped registration,
            a legacy/non-chain registry, an invalid promotion transition, or
            an unexpected version transition.
        PromotionIntentError: If ``promotion`` is malformed.
        TypeError: If ``registry`` is neither a registry nor a path.
    """
    path = Path(new_contract_path)

    # (0) Read the new content before validation so the transition can be
    # classified without guessing from filenames.
    try:
        parsed = load_contract(path)
    except Exception as exc:
        raise ResealError(
            "validate",
            f"contract '{path}' could not be read: {exc}",
        ) from exc
    new_is_provisional = (
        isinstance(parsed, dict) and parsed.get("provisional") is True
    )

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

    # (d) Seal the candidate in the mode its own content requires. Draft mode
    # is only for provisional files; full mode only for promoted ones. Draft
    # mode relaxes nothing else (RFC 0005 §4.6).
    candidate_mode: Literal["full", "draft"] = (
        "draft" if new_is_provisional else "full"
    )
    try:
        candidate = ContractEnforcer.load(
            path,
            mode=candidate_mode,
            allow_unsealed_reseal=True,
        )
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

    # (e) RFC 0005 §5.3 transition table, enforced before any append.
    if promotion is not None and new_is_provisional:
        raise ResealError(
            "promotion",
            "cannot promote a contract that is still provisional; removed "
            "`provisional` before requesting promotion",
        )

    if previous is None:
        if promotion is not None:
            raise ResealError(
                "promotion",
                f"not a promotion: no previous registry entry exists for "
                f"'{canonical_path}'",
            )
    elif previous.draft:
        if not new_is_provisional and promotion is None:
            raise ResealError(
                "promotion",
                "draft -> full requires an explicit PromotionIntent naming "
                "the human reviewer and the reason. Removing `provisional` "
                "and re-sealing is not a promotion (RFC 0005 §5.3).",
            )
    else:
        if new_is_provisional:
            raise ResealError(
                "promotion",
                "a full contract cannot be demoted to provisional by re-seal",
            )
        if promotion is not None:
            raise ResealError(
                "promotion",
                f"not a promotion: the latest entry for '{canonical_path}' "
                "is not a draft",
            )

    # (f) Compute the §5.2 diff against the registry's recorded draft content
    # before registering, so an empty or ordinary re-seal never appends.
    promotion_changes: list[dict[str, Any]] = []
    promotion_hash: str | None = None
    promotion_block: dict[str, Any] | None = None
    if promotion is not None:
        # The transition table guarantees a draft predecessor here. `parsed`
        # is exactly what registration re-reads, not the enforcer's normalized
        # copy, so the committed diff cannot disagree over injected defaults.
        assert previous is not None
        candidate_content = dict(parsed)
        promotion_changes = promotion_diff(previous.content, candidate_content)
        if not promotion_changes:
            raise ResealError(
                "promotion",
                "no changes: a promotion that changes nothing is not a "
                "promotion",
            )
        if not any(
            change["op"] == "remove" and change["path"] == "/provisional"
            for change in promotion_changes
        ):
            raise ResealError(
                "promotion",
                "diff does not record removal of `/provisional`; the "
                "promoted file must omit the flag",
            )
        promotion_hash = diff_sha256(promotion_changes)
        promotion_block = {
            "reviewer": promotion.reviewer,
            "intent": promotion.intent,
            "reference": promotion.reference,
            "from_entry_id": previous.entry_id,
            "from_version": previous.version,
            "from_contract_hash": previous.contract_hash,
            "diff_sha256": promotion_hash,
        }

    # CAS-style re-check: the entry the human reviewed must still be latest.
    latest_now = registry_obj.get_latest_by_path(canonical_path)
    latest_entry_id = latest_now.entry_id if latest_now is not None else None
    expected_entry_id = previous.entry_id if previous is not None else None
    if latest_entry_id != expected_entry_id:
        raise ResealError(
            "register",
            "registry changed while the re-seal was running; the reviewed "
            f"entry {expected_entry_id} is no longer latest "
            f"({latest_entry_id})",
        )

    try:
        if promotion_block is None:
            # Keep compatibility with registries that implement the pre-RFC
            # single-argument `register(enforcer)` signature.
            entry = registry_obj.register(candidate)
        else:
            entry = registry_obj.register(candidate, promotion=promotion_block)
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
    if promotion is not None and reused:
        raise ResealError(
            "promotion",
            "promotion must append a new version; the registry reused the "
            "existing entry",
        )
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

    # (g) Verify the committed entry reproduces the reviewed diff exactly.
    promotion_receipt: PromotionReceipt | None = None
    if promotion is not None:
        assert previous is not None
        assert promotion_hash is not None
        assert promotion_block is not None
        committed_changes = promotion_diff(previous.content, entry.content)
        committed_hash = diff_sha256(committed_changes)
        if committed_changes != promotion_changes or committed_hash != promotion_hash:
            raise ResealError(
                "promotion",
                "registered content does not reproduce the reviewed diff; "
                "the promotion is not trustworthy",
            )
        promotion_receipt = PromotionReceipt(
            receipt_version=1,
            reviewer=promotion.reviewer,
            intent=promotion.intent,
            reference=promotion.reference,
            from_entry_id=previous.entry_id,
            to_entry_id=entry.entry_id,
            from_version=previous.version,
            to_version=entry.version,
            from_contract_hash=previous.contract_hash,
            to_contract_hash=entry.contract_hash,
            diff=tuple(promotion_changes),
            diff_sha256=promotion_hash,
        )

    # (h) Frozen warning-audit record (timestamp-free by design).
    record = ResealRecord(
        canonical_path=canonical_path,
        contract_hash=entry.contract_hash,
        entry_id=entry.entry_id,
        version=entry.version,
        node_id=entry.node_id,
        contract_source=entry.contract_source,
        lint_warnings=tuple(lint_result.warnings),
        reused_existing_entry=reused,
        draft=new_is_provisional,
        promotion=promotion_block,
    )

    # (i) Only after registration succeeds is a fresh enforcer built/returned.
    try:
        fresh = ContractEnforcer.load(
            path,
            mode=candidate_mode,
            registry=registry_obj,
        )
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
        "Re-seal complete for '%s': version %s, entry %s (%s%s).",
        canonical_path,
        record.version,
        record.entry_id,
        "reused existing entry" if reused else "new entry",
        ", promotion" if promotion is not None else "",
    )
    return ResealResult(
        enforcer=fresh,
        record=record,
        promotion_receipt=promotion_receipt,
    )
