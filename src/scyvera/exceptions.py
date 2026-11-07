"""
Custom exception types for scyvera.

These exceptions represent specific, actionable error conditions in
contract loading, validation, and runtime enforcement.
"""
from typing import Any


class ContractFileNameError(Exception):
    """Raised when a contract file uses .yml instead of the canonical .yaml extension.

    The Agent Contract specification (WORKFLOW-CONTRACT-SPEC.md) mandates
    contract.yaml as the canonical filename. Files using .yml are rejected
    with an actionable error message directing the author to rename.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(
            f"Found contract.yml — rename to contract.yaml "
            f"(see WORKFLOW-CONTRACT-SPEC.md): {path}"
        )


class ContractViolationError(Exception):
    """Raised when an undeclared action (permission or side effect) is attempted at runtime.

    Scyvera operates on default-deny: any operation not declared in the contract
    is denied immediately and loudly.

    ``reason`` is an additive keyword for load-time violations that are not
    undeclared actions (for example, an M1.3/T14 symlink escape). When it is
    supplied, it replaces the default "action not declared" message; existing
    three-argument call sites keep their exact message and attributes.
    """

    def __init__(
        self,
        action_name: str,
        contract_path: str,
        suggestion: str,
        *,
        reason: str | None = None,
    ) -> None:
        self.action_name = action_name
        self.contract_path = str(contract_path)
        self.suggestion = suggestion
        self.reason = reason
        if reason is not None:
            super().__init__(reason)
            return
        super().__init__(
            f"Contract violation: Action '{action_name}' is not declared in '{self.contract_path}'. "
            f"Suggestion: Declare this action in the '{suggestion}' field of your contract."
        )


class ContractTamperError(Exception):
    """Raised when an attempt to mutate the loaded contract or its source file is detected.

    The contract must remain strictly immutable after load.
    """

    def __init__(self, message: str = "Attempted mutation of frozen contract object or file hash mismatch.") -> None:
        super().__init__(message)


class GuardrailViolationError(ContractViolationError):
    """Raised when an optional v1.2 guardrail denies an otherwise-gated call.

    Implements RFC 0003 §C5. This is a :class:`ContractViolationError`
    subclass, so existing ``except ContractViolationError`` blocks keep
    catching it unchanged. The extra attributes identify which guardrail
    fired and the limit/window that was exceeded.

    ``guardrail`` is one of ``"rate_limit"``, ``"budgets"``, or
    ``"fail_closed"``. ``limit`` and ``window`` are populated where the
    guardrail has them (``None`` for ``fail_closed``). Messages contain no
    wall-clock value, so repeated denials serialize deterministically.
    """

    def __init__(
        self,
        guardrail: str,
        action_name: str,
        *,
        reason: str,
        limit: int | None = None,
        window: str | None = None,
        contract_path: str = "contract",
    ) -> None:
        self.guardrail = guardrail
        self.limit = limit
        self.window = window
        super().__init__(
            action_name=action_name,
            contract_path=contract_path,
            suggestion=(
                f"Adjust 'guardrails.{guardrail}' in contract.yaml, wait for "
                f"the window to pass, or remove the guardrail block."
            ),
            reason=reason,
        )


class ApprovalPendingError(Exception):
    """Raised when an action matches an approval boundary and requires human confirmation.

    In the v1.0 enforcer, this error halts execution and exposes the approval configuration
    (channel, timeout, fallback behavior) to the integrating application.
    """

    def __init__(self, action_name: str, approval_config: dict[str, Any] | Any) -> None:
        self.action_name = action_name
        self.approval_config = approval_config
        super().__init__(
            f"Action '{action_name}' requires human approval before execution. "
            f"Approval config: {approval_config}"
        )


class ContractVersionError(Exception):
    """Raised when a contract version is invalid, mismatched, or violates version constraints."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ContractValidationError(Exception):
    """Raised when contract structural or schema validation fails during enforcer load."""

    def __init__(self, message: str, errors: tuple[Any, ...] = ()) -> None:
        self.errors = errors
        super().__init__(message)


class GatewayError(Exception):
    """Raised when an underlying gateway client operation fails.

    Wraps the original third-party exception to prevent raw client
    exceptions (PyGithub, Qdrant) from leaking outside the gateway
    boundary. The gateway is the sole owner of credentials and clients.
    """

    def __init__(self, action: str, original_exception: Exception) -> None:
        self.action: str = action
        self.original_exception: Exception = original_exception
        self.original: Exception = original_exception
        super().__init__(
            f"Gateway error for action '{action}': {original_exception}"
        )


class DeclarationValidationError(Exception):
    """Raised when a runtime contract declaration is invalid.

    This is a creation-time error — raised when from_declaration()
    receives a dict that fails validation. Distinct from
    ContractViolationError which is a runtime enforcement error.
    """

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        super().__init__(
            f"Invalid contract declaration — field '{field}': {reason}"
        )


class RegistryError(Exception):
    """Raised when a contract registry operation fails.

    Covers: corrupt registry file, duplicate hash registration,
    registry path not writable, malformed registry entry on read.
    """

    def __init__(self, operation: str, reason: str) -> None:
        self.operation = operation
        self.reason = reason
        super().__init__(
            f"Registry error during '{operation}': {reason}"
        )


class ResealError(Exception):
    """Raised when the M1.4 re-seal ritual cannot complete.

    The ritual is the only sanctioned regeneration path (T12): validate,
    lint with zero errors, register the sealed contract, then hand back a
    governable enforcer. Any skipped or partial step raises this error so a
    caller can never receive an enforcer from a half-completed reseal.
    """

    def __init__(self, step: str, reason: str) -> None:
        self.step = step
        self.reason = reason
        super().__init__(
            f"Re-seal ritual failed at '{step}': {reason}"
        )


class PackError(Exception):
    """Raised when a Policy Pack cannot be loaded or is malformed.

    Implements the local-only pack contract in RFC 0004 §6: a pack is a
    facts-only YAML artifact, so any structural problem is reported before a
    draft is generated rather than silently ignored.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


class TraceError(ValueError):
    """Raised when a trace entry or trace log is structurally invalid.

    RFC 0003 §C4 traces are a fail-closed interchange format: missing or
    unknown fields, wrong types, unknown result values, non-ISO-8601
    timestamps, and malformed JSONL lines are rejected rather than coerced.
    ``ValueError`` is the house base for parse/validation failures (for
    example :class:`GuardrailConfigError`), so callers can catch invalid input
    without depending on the trace module.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)

