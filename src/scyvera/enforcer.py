"""
Runtime Enforcement Engine for Scyvera Agent Contracts.

DESIGN PRINCIPLES:
==================
1. THE CONTRACT IS THE SOURCE OF TRUTH, NOT THE ENFORCER'S LOGIC.
   The enforcer interprets the contract; it does not override it.
   Any action the enforcer takes must be traceable to a specific field
   in the loaded contract.

2. DEFAULT-DENY.
   If an action is not declared in permissions or side_effects, it is
   DENIED, not warned about. Deny loudly with a ContractViolationError
   that names the undeclared action and the contract field it should
   have been in.

3. THE CONTRACT ITSELF MUST BE IMMUTABLE AT RUNTIME.
   Once ContractEnforcer.load() completes, the loaded contract object
   is frozen. Any attempt to modify it raises ContractTamperError.

4. ENFORCEMENT MUST BE UNFORGEABLE BY THE AGENT.
   An agent cannot call a side effect by wrapping it in a function that
   isn't gated. The gate must be the only path to the declared side
   effect. Document clearly that enforcement is only as strong as the
   integration — scyvera cannot prevent a developer from bypassing
   the gate at the call site.

5. EVERY ENFORCEMENT DECISION IS LOGGED.
   Allowed, denied, and approval-pending actions all produce a
   structured log entry. Silent enforcement is no enforcement.

KNOWN LIMITATIONS:
==================
- T4 (Gate Bypass): Scyvera cannot physically prevent a developer or agent
  from directly calling an ungated function in Python without the @gate
  decorator. Integrators should use `ContractEnforcer.assert_gated(fn)` in
  their integration test suites to ensure all sensitive call sites are wrapped.
- T5 (Pre-Load File Tampering): The SHA-256 integrity check in verify_integrity()
  protects against file replacement AFTER load. It does not protect against a
  tampered contract.yaml being present BEFORE ContractEnforcer.load() is called.
  The deployment environment is responsible for protecting the contract file
  prior to load.
- T6 (Permission String Spoofing): Scyvera enforces that a declared action
  matches a declared contract entry. It cannot introspect arbitrary third-party
  code inside the decorated function to verify that a function decorated with
  'github:issues:write' does not internally make an administrative API call.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import functools
import hashlib
import inspect
import logging
from pathlib import Path
import re
from typing import Any, Callable, Literal
import warnings

from .exceptions import (
    ApprovalPendingError,
    ContractTamperError,
    ContractValidationError,
    ContractVersionError,
    ContractViolationError,
)
from .validator import (
    LIFECYCLE_DEFAULTS,
    ContractVersion,
    detect_contract_version,
    load_contract,
    validate_contract,
)

logger = logging.getLogger("scyvera.enforcer")


# =============================================================================
# Immutability Primitives (Principle 3 & Threat T5 / T9)
# =============================================================================

class _ImmutableDict(dict):
    """Immutable dictionary wrapper that raises ContractTamperError on modification."""

    def __setitem__(self, key: Any, value: Any) -> None:
        raise ContractTamperError(
            f"Cannot modify frozen contract: attempted to set key '{key}'."
        )

    def __delitem__(self, key: Any) -> None:
        raise ContractTamperError(
            f"Cannot modify frozen contract: attempted to delete key '{key}'."
        )

    def pop(self, *args: Any, **kwargs: Any) -> Any:
        raise ContractTamperError("Cannot modify frozen contract: pop() is prohibited.")

    def popitem(self) -> Any:
        raise ContractTamperError("Cannot modify frozen contract: popitem() is prohibited.")

    def clear(self) -> None:
        raise ContractTamperError("Cannot modify frozen contract: clear() is prohibited.")

    def update(self, *args: Any, **kwargs: Any) -> None:
        raise ContractTamperError("Cannot modify frozen contract: update() is prohibited.")

    def setdefault(self, *args: Any, **kwargs: Any) -> Any:
        raise ContractTamperError("Cannot modify frozen contract: setdefault() is prohibited.")


class _ImmutableList(list):
    """Immutable list wrapper that raises ContractTamperError on modification."""

    def __setitem__(self, index: Any, value: Any) -> None:
        raise ContractTamperError(
            f"Cannot modify frozen contract: attempted to modify index {index}."
        )

    def __delitem__(self, index: Any) -> None:
        raise ContractTamperError(
            f"Cannot modify frozen contract: attempted to delete index {index}."
        )

    def append(self, value: Any) -> None:
        raise ContractTamperError("Cannot modify frozen contract: append() is prohibited.")

    def extend(self, values: Any) -> None:
        raise ContractTamperError("Cannot modify frozen contract: extend() is prohibited.")

    def insert(self, index: int, value: Any) -> None:
        raise ContractTamperError("Cannot modify frozen contract: insert() is prohibited.")

    def remove(self, value: Any) -> None:
        raise ContractTamperError("Cannot modify frozen contract: remove() is prohibited.")

    def pop(self, index: int = -1) -> Any:
        raise ContractTamperError("Cannot modify frozen contract: pop() is prohibited.")

    def clear(self) -> None:
        raise ContractTamperError("Cannot modify frozen contract: clear() is prohibited.")


def _deep_freeze(data: Any) -> Any:
    """Recursively freeze dictionaries and lists into immutable equivalents."""
    if isinstance(data, dict):
        frozen = _ImmutableDict()
        for k, v in data.items():
            dict.__setitem__(frozen, k, _deep_freeze(v))
        return frozen
    elif isinstance(data, list):
        frozen = _ImmutableList()
        for item in data:
            list.append(frozen, _deep_freeze(item))
        return frozen
    return data


# =============================================================================
# Audit Log Entry (Principle 5 & Threat T9)
# =============================================================================

@dataclass(frozen=True)
class AuditEntry:
    """Immutable audit record representing an enforcer decision."""
    timestamp: str
    action_name: str
    action_type: str  # "side_effect" or "permission"
    decision: str     # "ALLOWED", "DENIED", "PENDING"
    reason: str
    contract_field_reference: str


# =============================================================================
# Contract Enforcer (Core Runtime Engine)
# =============================================================================

class ContractEnforcer:
    """Runtime enforcement gatekeeper for Scyvera Agent Contracts.

    The enforcer gates operations against the declared capabilities, permissions,
    side effects, and approval boundaries defined in a contract.yaml.
    """

    def __init__(
        self,
        contract_path: Path,
        raw_contract: dict[str, Any],
        integrity_hash: str,
    ) -> None:
        self._contract_path = contract_path
        self._integrity_hash = integrity_hash
        self._raw_contract = raw_contract
        self._frozen_contract: Mapping[str, Any] = _deep_freeze(raw_contract)
        self._audit_log: list[AuditEntry] = []
        self._granted_approvals: set[str] = set()

    @property
    def integrity_hash(self) -> str:
        """The SHA-256 digest of the contract file at load time."""
        return self._integrity_hash

    @property
    def contract(self) -> Mapping[str, Any]:
        """Read-only, immutable representation of the loaded contract."""
        return self._frozen_contract

    @property
    def contract_path(self) -> Path:
        """Path to the loaded contract file."""
        return self._contract_path

    # -------------------------------------------------------------------------
    # Loader and Factory (T5, T7, T8, T10)
    # -------------------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> ContractEnforcer:
        """Load and validate a contract.yaml file, freezing it for runtime enforcement.

        Raises:
            FileNotFoundError: If the contract file does not exist.
            ContractFileNameError: If the file uses .yml instead of .yaml.
            ContractValidationError: If structural/schema validation fails.
            ContractVersionError: If version constraints or invariants are violated.
        """
        contract_path = Path(path)
        if not contract_path.exists():
            raise FileNotFoundError(f"Contract file not found at: {contract_path}")

        # Compute SHA-256 file hash before loading content (T5)
        content_bytes = contract_path.read_bytes()
        integrity_hash = hashlib.sha256(content_bytes).hexdigest()

        # Step 1: Structural load & validation (checks .yaml naming & schema)
        raw_data = load_contract(contract_path)
        if not isinstance(raw_data, dict):
            raise ContractValidationError(
                f"Contract file '{contract_path}' must contain a YAML mapping, got {type(raw_data).__name__}."
            )

        # Step 2: Version and Invariant Check (T10)
        cls._validate_version_invariants(raw_data, contract_path)

        # Step 3: Threat Mitigation Constraints (T7, T8)
        cls._validate_security_constraints(raw_data, contract_path)

        # Step 4: Structural schema validation
        val_result = validate_contract(contract_path)
        if not val_result.valid:
            err_msgs = [f"{e.path}: {e.message}" if e.path else e.message for e in val_result.errors]
            raise ContractValidationError(
                f"Contract validation failed for '{contract_path}': " + "; ".join(err_msgs),
                errors=val_result.errors,
            )
        cls._validate_security_constraints(raw_data, contract_path)

        # Step 4: Apply backward compatibility defaults if omitted
        raw_copy = dict(raw_data)
        if "lifecycle" not in raw_copy:
            raw_copy["lifecycle"] = dict(LIFECYCLE_DEFAULTS)

        return cls(
            contract_path=contract_path,
            raw_contract=raw_copy,
            integrity_hash=integrity_hash,
        )

    @classmethod
    def _validate_version_invariants(cls, contract: dict[str, Any], path: Path) -> None:
        """Validate cross-version consistency and enforce strict version constraints (T10)."""
        cv_explicit = contract.get("contract_version")
        ver_num = contract.get("version")

        # If explicitly claiming 1.1 via contract_version but missing lifecycle in v1.1 strict mode
        if cv_explicit == "1.1" and "lifecycle" not in contract:
            raise ContractVersionError(
                f"Contract at '{path}' explicitly declares contract_version: '1.1' "
                f"but is missing the required 'lifecycle' field. "
                f"Declare a 'lifecycle' block (e.g. {{mode: request-response}})."
            )

        version = detect_contract_version(contract)
        if version is None:
            raise ContractVersionError(
                f"Unsupported or unrecognized contract version in '{path}'. "
                f"Expected '1' or '1.1', found version={ver_num}, contract_version={cv_explicit}."
            )

    @classmethod
    def _validate_security_constraints(cls, contract: dict[str, Any], path: Path) -> None:
        """Enforce threat mitigations T7 (Wildcards) and T8 (Irreversible Actions)."""
        # T7: Check for wildcards in permissions and side_effects
        permissions = contract.get("permissions", [])
        _WILDCARDS = {"*", "all", "any"}
        _SERVICE_SCOPE_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+:[a-zA-Z0-9_\-:]+$")

        for perm in permissions:
            if isinstance(perm, str):
                cleaned = perm.strip()
                if cleaned in _WILDCARDS:
                    raise ContractValidationError(
                        f"Wildcard permission '{cleaned}' is prohibited in '{path}' (Threat T7)."
                    )
                if not _SERVICE_SCOPE_PATTERN.match(cleaned):
                    raise ContractValidationError(
                        f"Permission string '{cleaned}' does not match required service:scope pattern (e.g. 'github:issues:write') in '{path}'."
                    )
            elif isinstance(perm, dict):
                for k, v in perm.items():
                    if k in _WILDCARDS or str(v).strip() in _WILDCARDS:
                        raise ContractValidationError(
                            f"Wildcard entry '{k}: {v}' in permissions is prohibited in '{path}' (Threat T7)."
                        )
                    if isinstance(v, list):
                        for act in v:
                            if str(act).strip() in _WILDCARDS:
                                raise ContractValidationError(
                                    f"Wildcard action '{act}' in permission '{k}' is prohibited in '{path}' (Threat T7)."
                                )

        side_effects = contract.get("side_effects", [])
        for se in side_effects:
            if isinstance(se, str) and se.strip() in _WILDCARDS:
                raise ContractValidationError(
                    f"Wildcard side effect '{se}' is prohibited in '{path}' (Threat T7)."
                )

        # T8: Irreversible action without approval check
        approvals = contract.get("approvals", []) or contract.get("approval_points", [])
        if not approvals:
            for se in side_effects:
                if isinstance(se, dict) and se.get("irreversible") is True:
                    side_effect_name = se.get("type") or se.get("action") or se.get("name") or str(se)
                    logger.warning(
                        "Contract '%s' declares irreversible side effect '%s' "
                        "but approval_points is empty. This action cannot be "
                        "undone and has no human approval gate. (T8)",
                        path,
                        side_effect_name,
                    )

    # -------------------------------------------------------------------------
    # Integrity Verification (Threat T5)
    # -------------------------------------------------------------------------

    def verify_integrity(self) -> bool:
        """Verify that the contract file on disk has not been modified since load time.

        Raises:
            ContractTamperError: If the file content hash has changed or file is missing.
        """
        if not self._contract_path.exists():
            raise ContractTamperError(
                f"Contract file '{self._contract_path}' was removed from disk after load!"
            )

        current_bytes = self._contract_path.read_bytes()
        current_hash = hashlib.sha256(current_bytes).hexdigest()

        if current_hash != self._integrity_hash:
            raise ContractTamperError(
                f"Contract file '{self._contract_path}' has been tampered with on disk! "
                f"Load-time hash: {self._integrity_hash}, Current hash: {current_hash}."
            )

        return True

    # -------------------------------------------------------------------------
    # Runtime Gate Decorator (Principles 1, 2, 4, 5)
    # -------------------------------------------------------------------------

    def gate(
        self,
        action_name: str,
        action_type: Literal["side_effect", "permission"],
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator factory to gate a function call against declared permissions or side effects.

        Args:
            action_name: The identifier of the action (e.g. 'github:issues:write' or 'comment').
            action_type: Either 'side_effect' or 'permission'.

        Returns:
            A decorator that intercepts execution, evaluates the contract, logs the audit
            entry, and either executes or raises a ContractViolationError / ApprovalPendingError.
        """
        if action_type not in ("side_effect", "permission"):
            raise ValueError(
                f"Invalid action_type '{action_type}'. Must be 'side_effect' or 'permission'."
            )

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            if inspect.iscoroutinefunction(fn):
                @functools.wraps(fn)
                async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                    self._check_gate(action_name, action_type)
                    try:
                        result = await fn(*args, **kwargs)
                        self._log_execution(action_name, action_type, success=True)
                        return result
                    except Exception as e:
                        self._log_execution(action_name, action_type, success=False, error=str(e))
                        raise
                wrapper = async_wrapper
            else:
                @functools.wraps(fn)
                def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                    self._check_gate(action_name, action_type)
                    try:
                        result = fn(*args, **kwargs)
                        self._log_execution(action_name, action_type, success=True)
                        return result
                    except Exception as e:
                        self._log_execution(action_name, action_type, success=False, error=str(e))
                        raise
                wrapper = sync_wrapper

            # Mark function as officially gated for assert_gated() (Threat T4 mitigation)
            setattr(wrapper, "__scyvera_gated__", True)
            setattr(wrapper, "__scyvera_action__", (action_name, action_type))
            return wrapper

        return decorator

    def _check_gate(self, action_name: str, action_type: str) -> None:
        """Perform pre-execution contract evaluation."""
        now = datetime.now(timezone.utc).isoformat()

        # Step 1: Check declaration (Default-Deny)
        is_declared, field_ref = self._is_action_declared(action_name, action_type)
        if not is_declared:
            # Principle 2: Default-deny loud violation
            entry = AuditEntry(
                timestamp=now,
                action_name=action_name,
                action_type=action_type,
                decision="DENIED",
                reason=f"Action '{action_name}' is not declared in '{action_type}s'.",
                contract_field_reference=field_ref,
            )
            self._audit_log.append(entry)
            suggestion = "side_effects" if action_type == "side_effect" else "permissions"
            raise ContractViolationError(
                action_name=action_name,
                contract_path=str(self._contract_path),
                suggestion=suggestion,
            )

        # Step 2: Check approval boundary
        requires_approval, approval_config = self._check_approval_required(action_name)
        if requires_approval and action_name not in self._granted_approvals:
            entry = AuditEntry(
                timestamp=now,
                action_name=action_name,
                action_type=action_type,
                decision="PENDING",
                reason="Action requires human confirmation prior to execution.",
                contract_field_reference="approval_points / approvals",
            )
            self._audit_log.append(entry)
            raise ApprovalPendingError(action_name=action_name, approval_config=approval_config)

        # Step 3: Allowed execution
        entry = AuditEntry(
            timestamp=now,
            action_name=action_name,
            action_type=action_type,
            decision="ALLOWED",
            reason=f"Action '{action_name}' matched declared contract specification.",
            contract_field_reference=field_ref,
        )
        self._audit_log.append(entry)

    def _is_action_declared(self, action_name: str, action_type: str) -> tuple[bool, str]:
        """Check if an action is declared in the loaded contract."""
        clean_action = action_name.strip()

        if action_type == "permission":
            field_name = "permissions"
            declared_perms = self._frozen_contract.get("permissions", [])
            for p in declared_perms:
                if isinstance(p, str):
                    if clean_action == p.strip() or clean_action.replace(" ", "") == p.replace(" ", ""):
                        return True, field_name
                elif isinstance(p, dict):
                    # v1 format: {"github": "issues:write"}
                    for k, v in p.items():
                        if k != "resource" and k != "actions":
                            combined = f"{k}:{v}".replace(" ", "")
                            if clean_action.replace(" ", "") in (combined, f"{k}", str(v)):
                                return True, field_name
                    # v1.1 format: {"resource": "github_issues", "actions": ["read", "write"]}
                    res = p.get("resource")
                    acts = p.get("actions", [])
                    if res:
                        if clean_action == res:
                            return True, field_name
                        for act in acts:
                            if clean_action in (f"{res}:{act}", f"{res}: {act}", act):
                                return True, field_name
            return False, field_name

        elif action_type == "side_effect":
            field_name = "side_effects"
            declared_effects = self._frozen_contract.get("side_effects", [])
            for se in declared_effects:
                if isinstance(se, str):
                    if clean_action.lower() in se.lower() or clean_action == se or se.lower() in clean_action.lower():
                        return True, field_name
                elif isinstance(se, dict):
                    se_type = se.get("type", "").lower()
                    se_res = se.get("resource", "").lower()
                    se_desc = se.get("description", "").lower()
                    clean_lower = clean_action.lower()
                    if clean_lower in (se_type, se_res, f"{se_res}:{se_type}"):
                        return True, field_name
                    if se_res and clean_lower.startswith(se_res):
                        remainder = clean_lower[len(se_res):].lstrip(":-_ ")
                        if remainder and (remainder in se_type or se_type in remainder or remainder in se_desc):
                            return True, field_name
                    if clean_lower in se_desc or (se_type and clean_lower in se_type):
                        return True, field_name
            return False, field_name

        return False, "unknown"

    def _check_approval_required(self, action_name: str) -> tuple[bool, dict[str, Any]]:
        """Determine if an action hits an approval requirement."""
        clean_action = action_name.strip()

        # Check v1 approval_points list
        approval_points = self._frozen_contract.get("approval_points", [])
        for ap in approval_points:
            if isinstance(ap, str) and (clean_action == ap.strip() or ap.strip() in clean_action):
                return True, {"channel": "manual", "timeout": "unspecified", "approver": "human"}

        # Check v1.1 approvals list
        approvals = self._frozen_contract.get("approvals", [])
        for ap in approvals:
            if isinstance(ap, str) and (clean_action == ap.strip() or ap.strip() in clean_action):
                return True, {"action": ap, "required": True, "approver": "human"}
            elif isinstance(ap, dict):
                act = ap.get("action", "")
                if ap.get("required", True) and (clean_action == act or act in clean_action or clean_action in act):
                    return True, dict(ap)

        return False, {}

    def _log_execution(self, action_name: str, action_type: str, success: bool, error: str | None = None) -> None:
        """Log execution outcome for observability."""
        status = "COMPLETED" if success else f"FAILED: {error}"
        logger.debug(
            "Contract execution [%s]: action='%s', type='%s', status='%s'",
            self._contract_path.name,
            action_name,
            action_type,
            status,
        )

    # -------------------------------------------------------------------------
    # Approval Flow and Audit Log Management (Threat T9)
    # -------------------------------------------------------------------------

    def approve(self, action_name: str, token: str = "") -> None:
        """Record manual human approval for a pending gated action.

        NOTE: Approval channels (Telegram, email, webhook) are synchronous-stub
        in v1.0. Integrators must catch ApprovalPendingError and implement
        their own approval routing until the async approval runtime ships.
        """
        clean_action = action_name.strip()
        self._granted_approvals.add(clean_action)
        now = datetime.now(timezone.utc).isoformat()
        entry = AuditEntry(
            timestamp=now,
            action_name=clean_action,
            action_type="approval",
            decision="ALLOWED",
            reason=f"Human approval granted manually with token='{token}'.",
            contract_field_reference="approval_points / approvals",
        )
        self._audit_log.append(entry)
        logger.info("Human approval recorded for action '%s'", clean_action)

    def get_audit_log(self) -> list[AuditEntry]:
        """Return a tamper-proof deep copy of all session audit log entries (T9)."""
        return copy.deepcopy(self._audit_log)

    @staticmethod
    def assert_gated(fn: Any) -> bool:
        """Verify that a function is decorated with @enforcer.gate(...) (T4).

        Raises:
            ContractViolationError: If the function is not wrapped by an enforcer gate.
        """
        if not getattr(fn, "__scyvera_gated__", False):
            name = getattr(fn, "__name__", str(fn))
            raise ContractViolationError(
                action_name=name,
                contract_path="<callsite>",
                suggestion="Decorate this function with @enforcer.gate(action_name, action_type).",
            )
        return True
