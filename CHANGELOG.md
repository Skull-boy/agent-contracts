# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-08-30

### Added [STABLE]
- **Runtime Enforcer Engine (`ContractEnforcer`)** [STABLE]:
  - `ContractEnforcer.load(path: str | Path) -> ContractEnforcer`: Loads, validates, and deep-freezes contracts with SHA-256 integrity hash verification.
  - `ContractEnforcer.gate(action_name: str, action_type: Literal["side_effect", "permission"])`: Decorator factory providing default-deny gating for synchronous and asynchronous functions.
  - `ContractEnforcer.get_audit_log() -> list[AuditEntry]`: Returns a tamper-proof deep copy of all session authorization decisions.
  - `ContractEnforcer.verify_integrity() -> bool`: Verifies that the contract file on disk has not been altered since load time.
  - `ContractEnforcer.approve(action_name: str, token: str = "")`: Synchronous approval stub for manual confirmation flows.
  - `ContractEnforcer.assert_gated(fn: Any) -> bool`: Utility to assert that a sensitive integration function is wrapped with an enforcer gate (Threat T4 mitigation).
- **Core Exceptions Hierarchy** [STABLE]:
  - `ContractViolationError(action_name, contract_path, suggestion)`: Raised on undeclared actions (Default-Deny).
  - `ContractTamperError(message)`: Raised on attempted mutations of frozen contract objects or disk file mismatch.
  - `ApprovalPendingError(action_name, approval_config)`: Raised when an action hits an approval requirement.
  - `ContractVersionError(message)`: Raised on version constraint or invariant mismatches.
  - `ContractValidationError(message, errors)`: Raised on schema or security constraint failures.
- **Audit Logging** [STABLE]:
  - `AuditEntry` frozen dataclass with fields: `timestamp`, `action_name`, `action_type`, `decision`, `reason`, `contract_field_reference`.

### Security
- Threat Mitigations implemented:
  - **T4**: Gate bypass detection via `assert_gated(fn)`.
  - **T5**: Runtime contract file replacement defense via SHA-256 hash tracking and immutable object freezing.
  - **T7**: Load-time and schema-level prohibition of wildcard permissions (`*`, `all`, `any`).
  - **T8**: Load-time warning for irreversible side effects without approval boundaries.
  - **T9**: Tamper-proof audit logging with immutable entries and deep-copied log outputs.
  - **T10**: Strict version cross-validation.

---

## [0.3.0] - 2026-08-30

### Added
- **Lifecycle Governance Specification (v1.1)**:
  - Added `lifecycle` object to `WORKFLOW-CONTRACT-SPEC.md` and `schemas/v1.1/contract.schema.json`.
  - Closed lifecycle mode taxonomy: `request-response`, `scheduled`, `persistent`.
  - Mandatory `idle_behavior` description for persistent agents via JSON Schema `if/then` rules.
  - Optional `irreversible: boolean` flag on side effects.
  - `ContractVersion` enum (`V1 = "1"`, `V1_1 = "1.1"`) and explicit version detection in `detect_contract_version()`.
  - `apply_lifecycle_defaults()` applying `{mode: request-response, initiation: human-only, resumability: stateless}` to v1 contracts with a transparency warning.
- **Tier 2 Semantic Linter Additions**:
  - `[AC301]` Vague idle behavior warning for persistent agents (Threat T2).
  - `[AC302]` Irreversible side effect without approval boundary warning (Threat T8).
- **RFC 0002**: Specification RFC for the Lifecycle field and migration path (`rfcs/0002-lifecycle-field.md`).

---

## [0.2.0] - 2026-08-30

### Fixed
- **Canonical Filename Enforcement**:
  - Enforced `contract.yaml` as the canonical filename across all tooling.
  - Introduced `ContractFileNameError` raised when `.yml` is encountered with an actionable message.
- **Repository Integrity Audit**:
  - Audited all directory paths and verified implementation folders.
