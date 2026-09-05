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
    """

    def __init__(self, action_name: str, contract_path: str, suggestion: str) -> None:
        self.action_name = action_name
        self.contract_path = str(contract_path)
        self.suggestion = suggestion
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
