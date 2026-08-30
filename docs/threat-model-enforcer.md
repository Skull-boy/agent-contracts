# Threat Model: Scyvera Runtime Enforcer (T4 – T10)

This document formalizes the runtime threat model, security invariants, architectural boundaries, and known limitations for the `ContractEnforcer` engine.

---

## Summary of Threats & Mitigations

| Threat ID | Threat Name | Layer | Mitigation Mechanism | Status |
|---|---|---|---|---|
| **T4** | Gate Bypass | Integration / Call-site | `ContractEnforcer.assert_gated(fn)` + Explicit Documentation | Known Limitation & CI Tooling |
| **T5** | Contract File Replacement at Runtime | File System / Memory | In-memory Object Freezing + SHA-256 Hash + `verify_integrity()` | Fully Enforced |
| **T6** | Permission String Spoofing | Implementation / Runtime | Declaration Binding + Spec RFC Audit Requirement | Known Limitation & Spec Requirement |
| **T7** | Wildcard Injection in Permissions | Schema & Loader | Closed Pattern Matching + Explicit Load-time Prohibitions | Fully Enforced |
| **T8** | Empty Approval Points Bypass | Policy & Schema | `irreversible: true` metadata flag + Load-time Warnings | Fully Enforced (Audit Warning) |
| **T9** | Audit Log Tampering | Enforcer Memory | Private `_audit_log` + Deep Copy Returns + Frozen Dataclasses | Fully Enforced |
| **T10** | Schema Version Confusion | Loader & Parser | Version Discriminator Cross-validation + `ContractVersionError` | Fully Enforced |

---

## Detailed Threat Analysis

### Threat T4: Gate Bypass
- **Description**: A developer or compromised agent imports and calls an underlying execution function directly without routing through the `@enforcer.gate(...)` decorator.
- **Mitigation & Invariant**:
  - Python's dynamic runtime cannot physically seal function call sites across modules.
  - **Tooling**: Scyvera provides `ContractEnforcer.assert_gated(fn)`, which checks the presence of runtime gating metadata (`__scyvera_gated__`). If an unwrapped function is detected, it raises `ContractViolationError`.
  - **Integration Guidance**: CI test suites should run `assert_gated(fn)` across all external integration endpoints.

### Threat T5: Contract File Replacement at Runtime
- **Description**: An agent with local file system write access modifies `contract.yaml` on disk after startup to inject broad permissions, then triggers a reload.
- **Mitigation & Invariant**:
  - At load time, `ContractEnforcer.load()` immediately computes and stores a SHA-256 digest (`integrity_hash`).
  - The in-memory contract is deep-frozen into immutable dictionary/list wrappers (`_deep_freeze`), making in-memory mutation raise `ContractTamperError`.
  - Calling `enforcer.verify_integrity()` re-computes the file hash on disk and raises `ContractTamperError` if any byte on disk has changed.

### Threat T6: Permission String Spoofing
- **Description**: An action is decorated as `@enforcer.gate("github:issues:write", "permission")`, but the function body secretly executes `github:repo:admin` or deletes repositories.
- **Mitigation & Invariant**:
  - Scyvera gates that the **declared intent** matches a **declared permission**. It does not perform dynamic runtime bytecode disassembly of third-party SDK calls.
  - This boundary is explicitly documented: contract validity is guaranteed by the contract author and verified through peer review.

### Threat T7: Wildcard Injection in Permissions
- **Description**: A contract author supplies `permissions: ["*"]` or `side_effects: ["*"]` or `"all"` / `"any"` to bypass granular permissions.
- **Mitigation & Invariant**:
  - Schema patterns enforce `^[a-zA-Z0-9_\-]+:[a-zA-Z0-9_\-:]+$` for permission strings.
  - `ContractEnforcer.load()` actively parses all permission entries and side effects, immediately rejecting `*`, `all`, or `any` with `ContractValidationError`.

### Threat T8: Empty Approval Points Bypass
- **Description**: A workflow contains high-risk or irreversible side effects (e.g. database wipe, financial transaction) but declares `approval_points: []`.
- **Mitigation & Invariant**:
  - The v1.1 schema introduces `irreversible: true` as an optional boolean on side effect declarations.
  - When `irreversible: true` is present and `approval_points` / `approvals` is empty, `ContractEnforcer.load()` emits a high-priority warning alerting developers and CI scanners to the unapproved destructive capability.

### Threat T9: Audit Log Tampering
- **Description**: An agent inspects `enforcer.get_audit_log()` and attempts `.clear()` or pops items to conceal unauthorized actions.
- **Mitigation & Invariant**:
  - `AuditEntry` is a frozen dataclass (`@dataclass(frozen=True)`).
  - `enforcer.get_audit_log()` creates a `copy.deepcopy` of the log list. Mutating the returned array has zero effect on the enforcer's internal log.

### Threat T10: Schema Version Confusion
- **Description**: A contract claims `contract_version: "1.1"` but is structured as a v1 contract or vice versa, causing schema mismatch.
- **Mitigation & Invariant**:
  - `ContractEnforcer.load()` verifies version consistency at load time. If `contract_version: "1.1"` is explicitly declared but required v1.1 fields like `lifecycle` are omitted, `ContractVersionError` is raised immediately.
