from .builder import AgentIdentity, Contract, SystemIdentity
from .enforcer import AuditEntry, ContractEnforcer
from .exceptions import (
    ApprovalPendingError,
    ContractFileNameError,
    ContractTamperError,
    ContractValidationError,
    ContractVersionError,
    ContractViolationError,
    GatewayError,
)
from .gateway import BaseGateway, GitHubGateway, QdrantGateway
from .linter import LintResult, LintWarning, lint_contract
from .validator import (
    LIFECYCLE_DEFAULTS,
    SCHEMA_V1_PATH,
    SCHEMA_V1_1_PATH,
    ContractVersion,
    ValidationError,
    ValidationResult,
    apply_lifecycle_defaults,
    detect_contract_version,
    validate_contract,
)

__version__ = "1.1.3"

__all__ = [
    "__version__",
    "AgentIdentity",
    "ApprovalPendingError",
    "AuditEntry",
    "BaseGateway",
    "Contract",
    "ContractEnforcer",
    "ContractFileNameError",
    "ContractTamperError",
    "ContractValidationError",
    "ContractVersion",
    "ContractVersionError",
    "ContractViolationError",
    "GatewayError",
    "GitHubGateway",
    "LIFECYCLE_DEFAULTS",
    "LintResult",
    "LintWarning",
    "QdrantGateway",
    "SCHEMA_V1_PATH",
    "SCHEMA_V1_1_PATH",
    "SystemIdentity",
    "ValidationError",
    "ValidationResult",
    "apply_lifecycle_defaults",
    "detect_contract_version",
    "lint_contract",
    "validate_contract",
]
