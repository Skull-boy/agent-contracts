# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Contract Registry (`ContractRegistry`, `RegistryEntry`, `RegistryError`) (Phase 2)**:
  - Versioned, append-only, JSON-lines persistent store for registered contracts (`.scyvera/registry.jsonl`).
  - Idempotent registration on duplicate SHA-256 hash.
  - Automatic version incrementing per `node_id`.
  - Query APIs: `get_latest(node_id)`, `get_by_hash(contract_hash)`, `get_history(node_id)`, `get_at_time(node_id, timestamp)`, `list_nodes()`, `size()`, `has_hash(contract_hash)`.
  - Atomic writes using temporary file pattern to guarantee durability.
  - Fail-closed error handling raising `RegistryError` on corrupt or unreadable files.
- **Dynamic Contract Declarations (`ContractEnforcer.from_declaration()`) (Phase 1)**:
  - Create fully governed `ContractEnforcer` instances from in-memory Python dictionaries without requiring a `contract.yaml` file on disk.
  - Deep copy and cryptographic sealing with SHA-256 integrity hash at creation time.
  - Strict declaration validation (`DeclarationValidationError`) rejecting unknown fields, invalid `node_id` formatting, empty permissions, and wildcard injection (Threat T7).
  - Full feature parity with file-based enforcers: `@enforcer.gate(...)`, `verify_integrity()`, audit logs, and `approve()` work identically.
- **Enforcer Registration Integration**:
  - `ContractEnforcer.register(registry)` method to register an enforcer's contract directly into a registry and store `registry_entry_id`.
  - Added `node_id`, `contract_source`, and `registry_entry_id` properties to `ContractEnforcer`.
- **Expanded Test Suite**:
  - Added comprehensive test suites: `tests/test_declaration.py` (Phase 1) and `tests/test_registry.py` (Phase 2), bringing total tests to 128 passing tests.

---

## [1.1.3] — 2026-09-05

### Added
- **Gateway Enforcement Layer (`BaseGateway`, `GitHubGateway`, `QdrantGateway`)**:
  - Single enforcement boundary for external API operations and credential management.
  - Per-instance `@enforcer.gate` wrapping with default-deny semantics.
  - Optional dependency handling for `PyGithub` and `qdrant-client` to keep core package dependency-light.
- **Gateway Exception Wrapping**:
  - Introduced `GatewayError` to encapsulate third-party API client exceptions.
- Added GitHub Actions workflow for gateway linting (`.github/workflows/lint-gateway.yml`).

### Changed
- `ContractEnforcer.gate()` now supports `"read"` as an action type alias for permission gating.

---

## [1.1.2] — 2026-08-30

### Changed
- Version bump with packaging corrections
- pip install scyvera resolves to this release as latest stable
- T8 warning now correctly emitted via logging module 
  (scyvera.enforcer logger) instead of warnings.warn
- T7 wildcard rejection enforced at JSON schema level in addition 
  to Python load-time check — validate_contract() now catches 
  wildcards independently of ContractEnforcer

---

## [1.0.0] — 2026-08-30

### Added — Runtime Enforcer (Step 3)
- `ContractEnforcer` class: load, freeze, gate, audit, integrity verification
- `ContractEnforcer.gate(action_name, action_type)` decorator — default-deny enforcement of declared side_effects and permissions
- `ContractEnforcer.verify_integrity()` — SHA-256 check detects contract file replacement after load (T5)
- `ContractEnforcer.get_audit_log()` — returns deep-copy frozen AuditEntry list (T9)
- `ContractVersionError` — raised on schema version mismatch (T10)
- `ContractTamperError` — raised on frozen object mutation or disk file replacement (T5, T9)
- `ApprovalPendingError` — raised when action hits an approval_point; approval channel routing is caller's responsibility (stub, documented)
- `assert_gated(fn)` utility for integration test suites (T4)
- T7: wildcard permissions rejected at schema level AND Python load time
- T8: irreversible side effect + empty approval_points emits logging.WARNING via scyvera.enforcer logger
- 59-test suite covering all threat models T1–T10

### Stable Public API (semver-protected from v1.0.0)
- ContractEnforcer.load / gate / get_audit_log / verify_integrity / assert_gated
- ContractViolationError, ContractTamperError, ApprovalPendingError, ContractVersionError, AuditEntry

### What scyvera does NOT guarantee (documented in README)
- Cannot prevent gate bypass if integrator calls ungated function directly (T4 — known limitation)
- Cannot verify that gated function's internal behavior matches its declared permission string (T6 — known limitation)
- Integrity check protects AFTER load only, not before (T5)

---

## [0.3.0] — 2026-08-30

### Added — Contract v1.1 Spec + lifecycle field (Step 2)
- `lifecycle` field added to contract spec (optional, backward compatible)
- v1.1 JSON schema at schemas/v1.1/contract.schema.json
- Default applied by loader when lifecycle absent: {mode: request-response, initiation: human-only, resumability: stateless}
- loader emits logging.WARNING when defaults are applied
- `irreversible` boolean field on side_effects entries
- RFC 0002 (lifecycle field) added to rfcs/
- Three worked examples in spec: request-response, scheduled, persistent
- T1/T2/T3 threat mitigations documented

### Migration
- All v1 contracts (no lifecycle field) remain valid
- No breaking changes to validate_contract() or CLI

---

## [0.2.0] — 2026-08-30

### Fixed — Repository Cleanup (Step 1)
- Canonical filename is now contract.yaml everywhere; contract.yml references removed
- Loader raises actionable error on contract.yml: "Found contract.yml — rename to contract.yaml"
- Backslash folder issue resolved (if it existed)

### Migration
- Rename any contract.yml files to contract.yaml
