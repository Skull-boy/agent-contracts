from .builder import AgentIdentity, Contract, SystemIdentity
from .audit import AuditReport, AuditError, SymlinkTargetError, scan_tree
from .audit_rules import RULES, SEVERITY_WEIGHTS, AuditRule, Finding
from .enforcer import AuditEntry, ContractEnforcer
from .generate import DraftContract, build_draft, write_draft
from .packs import PACKS_DIR, PolicyPack, available_packs, load_pack
from .report import BAND_COLORS, render_badge, render_report
from .exceptions import (
    ApprovalPendingError,
    ContractFileNameError,
    ContractTamperError,
    ContractValidationError,
    ContractVersionError,
    ContractViolationError,
    DeclarationValidationError,
    GatewayError,
    PackError,
    RegistryError,
)
from .gateway import BaseGateway, GitHubGateway, QdrantGateway
from .registry import ContractRegistry, RegistryEntry
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
    "AuditError",
    "AuditReport",
    "AuditRule",
    "BAND_COLORS",
    "BaseGateway",
    "Contract",
    "ContractEnforcer",
    "ContractFileNameError",
    "ContractRegistry",
    "ContractTamperError",
    "ContractValidationError",
    "ContractVersion",
    "ContractVersionError",
    "ContractViolationError",
    "DeclarationValidationError",
    "DraftContract",
    "Finding",
    "GatewayError",
    "GitHubGateway",
    "LIFECYCLE_DEFAULTS",
    "LintResult",
    "LintWarning",
    "PACKS_DIR",
    "PackError",
    "PolicyPack",
    "QdrantGateway",
    "RULES",
    "RegistryEntry",
    "RegistryError",
    "SCHEMA_V1_PATH",
    "SCHEMA_V1_1_PATH",
    "SEVERITY_WEIGHTS",
    "SymlinkTargetError",
    "SystemIdentity",
    "ValidationError",
    "ValidationResult",
    "apply_lifecycle_defaults",
    "available_packs",
    "build_draft",
    "detect_contract_version",
    "lint_contract",
    "load_pack",
    "render_badge",
    "render_report",
    "scan_tree",
    "validate_contract",
    "write_draft",
]
