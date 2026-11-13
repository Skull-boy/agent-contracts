# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — harness skill package (M3.1)
- **`skills/scyvera-governance/`** packages the governance workflow as an installable harness skill: `SKILL.md` teaches the seven CLI commands and the five MCP tools, pins the three NEVERs, and states the knowledge-not-powers principle; `reference/` documents every finding code and exit code; `scripts/` wraps `scyvera audit` with explicit exit capture. The skill ships its own `contract.yaml` (Tier 0 PASS) and is hash-locked by `tools/lock_skill.py` into `skills-registry.json` with deterministic per-file SHA-256 hashes. No engine files changed.

### Added — per-target adoption kits (M3.2)
- **`kits/n8n/` and `kits/langgraph/`** package each shipped conformance target as a declarative adoption kit: `KIT.md` documents the three-step path and the honest Tier 1 scope, `contract.template.yaml` is the target's reference contract with `# EDIT` markers, `verify.sh`/`verify.ps1` check the pinned reference target with explicit exit capture, and `reference/` carries the M3.1 finding/exit-code tables byte-locked to `skills/scyvera-governance/reference/`. `kits/README.md` specifies the format and lockstep rule; `tests/test_m32_kits.py` pins format, reference lockstep, POSIX execution, PowerShell parse, the LangGraph golden eval score, and deterministic output. No engine files changed.

## [1.4.0] — 2026-11-09

### Added — Conformance CLI and Tier 1 adapters (M2.1–M2.3)
- **`scyvera check`** runs Tier 0 structural conformance (schema plus ACxxx semantics) and discovers the static Tier 1 adapter for n8n workflow JSON and LangGraph source; `--tier auto` selects the highest implemented tier, `T101` or an error-severity `T102` fails, `T103` warns, and an unclaimed target exits `2` with one actionable line. The adapters parse JSON/AST and never import or execute the target.

### Added — Self-check and release attestation (M3.3/M3.4)
- **`scyvera self-check [--json]`** verifies every installed runtime file against the packaged `_self_manifest.json` through `importlib.resources`, failing closed on modified, missing, or unlisted files; exit codes are `0` clean, `1` deviation, and `2` unverifiable. The release workflow downloads the completed publish run's `dist` artifact, regenerates the manifest in a clean venv, gates on `self-check`, emits a CycloneDX 1.5 SBOM, and signs the wheel, SBOM, and release manifest with Sigstore provenance.

### Added — Registry integrity: hash chain, identity pinning, re-seal (M1.1/M1.3/M1.4)
- **Hash-chained `registry.jsonl`** links each entry to the SHA-256 of the previous canonical bytes and verifies eagerly on load, with an explicit one-time `upgrade_chain()` migration; **`ContractEnforcer.load()`** pins the canonical path and hash in a frozen identity receipt, refuses symlink escapes and unregistered re-seal paths, and **`reseal()`** enforces validate → lint with zero errors → chain-verified register → fresh enforcer so production regeneration cannot bypass provenance.

### Added — Guardrails DSL v1.2 (M2.6)
- **Optional top-level `guardrails`** in the v1.2 schema adds `fail_closed`, `budgets` (side-effect count per `s|m|h|d` window), and `rate_limit`; the enforcer counts every gated attempt in a sliding minute and only admitted side effects against budgets, denies with `GuardrailViolationError`, and audits `guardrails.rate_limit` / `guardrails.budgets` / `guardrails.fail_closed`. v1/v1.1 contracts are unchanged, AC701 warns when older contracts carry the block, and counters are per-enforcer/per-process rather than distributed quotas.

### Added — Trace schema and eval harness (M1.2/M2.4)
- **`scyvera.trace`** round-trips every `AuditEntry` decision through canonical JSONL with fail-closed parsing; **`scyvera.evals`** scores recorded traces on the four RFC 0003 §C4 axes (constraints, approval, recovery, replay), executes the golden refund-agent case to a deterministic `75.0`, and normalizes trace timestamps so results serialize byte-identically.

### Added — Unified report and eval CLI (M2.5)
- **`scyvera.unified`** projects audit, check-tier0/1, and eval payloads into one additive eight-key envelope with sorted findings and no timestamps; `scyvera eval <case>` renders the four axes and emits the envelope with `--json`, while `check --unified` and `audit --unified` share the same shape. The producers' published bytes (`audit --json`, `render_check()`, `EvalResult.to_json()`) remain unchanged.

### Added — GitHub Action (PD-6)
- **`scyvera-gate`** is a composite Action (`.github/actions/scyvera-gate/action.yml`) that installs `scyvera>=1.3,<2` from PyPI (or the local workspace), runs audit or conformance tiers, honors `--fail-under` and `--badge`, writes the unified JSON output, and dogfoods the action on push and pull request; its install string accepts 1.4.0.

### Added — MCP server mode (PD-7)
- **`scyvera serve-mcp`** exposes the existing engines over stdio JSON-RPC 2.0 as `scyvera_audit`, `scyvera_validate`, `scyvera_check`, `scyvera_self_check`, and `scyvera_packages`; tool results are the CLI's own payloads (the audit result includes the M2.5 unified envelope), internal failures are JSON-RPC errors, and stdout carries protocol frames only. The roadmap row keeps its `scyvera mcp` wording with a shipped-name note.

### Fixed — Stranger-test hardening (R1)
- **AU-NET-002** now parses comma-separated imports (`import os, requests`) and agent/ML SDKs; new **AU-SECRET-001** (high) reports hardcoded credential-like source literals with the value redacted; **governance status** is detected by a bounded, name-based `contract.yaml` search and surfaced as `[ungoverned]` plus one next step in the terminal and additively as `summary.governance` in `--unified`, while `audit --json` stays byte-identical.

### Added — Multi-language audit pattern pack and BOM fix (R1b)
- **`utf-8-sig` decoding** plus a shared per-line U+FEFF strip make BOM-prefixed files match like plain UTF-8 while UTF-16 still skips as binary; documented AU-NET-002 tables add Go, Java/Kotlin, Rust, C/C++, C#, PHP, and JS/TS clients, wrapper-aware payload extraction extends AU-NET-001/AU-SH-001/AU-GIT-001 into source contexts, and AU-SECRET-001 covers their assignment styles and credential-like callees. Coverage is pattern-level, review-grade — not AST or conformance-grade (see `docs/language-coverage.md`).

### Added — Version flag and install troubleshooting
- **`scyvera --version`** prints exactly `scyvera <installed version>` (or `scyvera unknown` without distribution metadata); `--help` points at it, and the README documents stale-wheel reinstalls and duplicate launchers on `PATH`.

### Added — Trust surface (PD-1–PD-4)
- **`SECURITY.md`** documents supported versions and coordinated disclosure; workflows pin every action by full commit SHA with least-privilege permissions; the suite runs Python 3.10–3.14 across Linux/Windows/macOS; and a static plus runtime pin rejects unsafe `yaml.load` paths.

## [1.3.0] — 2026-11-04

### Added — Policy Packs (M2.7)
- **New `--pack <name>` flag**: `scyvera audit . --generate contract.yaml --pack github-safe` applies a local Policy Pack to the generated v1.1 draft (RFC 0004 §6). The pack supplies the draft's `domain`, forces `irreversibly_forbidden` effects to `irreversible: true` while removing their approval entries, and forces `requires_approval` actions to `required: true`. Pack constraints win over heuristic-derived entries; finding-only extras are appended. `--pack` without `--generate` exits `2` with one actionable stderr line.
- **Six golden packs**: `dev-agent`, `github-safe`, `finance-ops`, `research-assistant`, `email-triage`, and `devops-safe` ship under `packs/` and as wheel package data under `src/scyvera/packs/`. Loading is filesystem-only with no network fetch; pack names cannot escape the packs directory, and symlinked packs are refused (T14).
- **Pack QA sweep**: `tests/test_packs.py` loads every golden pack, applies it to every fixture corpus, writes the draft, and requires Tier 0 schema validation plus Tier 2 lint with zero warnings. It also pins the repository and packaged copies byte-for-byte.
- **Cap placement**: `cap_side_effects_per_window` is accepted under `derive` (the RFC 0004 §6 template) or under `construction` (the section's prose), but not both, so either literal reading of the RFC validates while the pack can never carry two conflicting caps.
- **Docs**: new [`docs/policy-packs.md`](./docs/policy-packs.md) documents the format, merge semantics, and the add-a-pack workflow.

### Changed — Documentation (Growth lane G1)
- **README rewritten around the no-contract funnel**: the hero now states the positioning sentence and leads with `scyvera audit` → report → badge → CI gate → generated draft, with hand-written contract authoring moved to the second path. The runtime enforcer, gateways, registry, builder, honesty sections, and domain examples remain.
- **Badges made non-stale**: the hardcoded test count is replaced by the `validate-contracts.yml` GitHub Actions badge; the row now adds PyPI, Python 3.10+, and this repository's own Shielded Blast Radius badge.
- **2-Minute Demo**: the README embeds `assets/scyvera-demo.gif`, a terminal capture of the audit, the generated draft, and the blocked action.
- **Roadmap refreshed**: `docs/roadmap.md` marks G1 as shipped and links each M2.0x/M2.7 row to its shipped note, so the plan and the changelog stay in step.

### Added — Auto-contract drafts (M2.0c)
- **New `--generate <contract.yaml>` flag**: `scyvera audit` now turns a scan into a ready-to-review v1.1 contract draft. Scored findings merge into `resources`, `permissions`, `side_effects`, and `approvals`; `system.name` comes from the scanned repository directory, `domain` is `software`, and `risk.level` tracks the worst scored severity. Critical findings mark matching side effects `irreversible`; medium and high findings never do (RFC 0004 §10.1). The report still prints exactly as before, followed by one line naming the written draft.
- **New `--force` overwrite guard**: `--generate` refuses to replace an existing file unless `--force` is passed, exiting `2` with a single actionable stderr line. `--force` without `--generate` is rejected the same way.
- **Additive JSON `draft_path`**: with `--json --generate`, the report gains one top-level `"draft_path"` key. Without `--generate`, `--json` output stays byte-identical.
- **Schema-accuracy guarantee**: every fixture corpus is drafted, written, re-read from disk, and validated in tests, so a draft that would fail `scyvera validate` or `scyvera lint` cannot ship.

### Added — Blast Radius Report (M2.0b)
- **Band-first terminal report**: `scyvera audit` now renders the Blast Radius report the way RFC 0004 §2 pins it — status and target first, then the score and band, a `Scanned N files (...)` breakdown, scored findings grouped by severity, and the contract suggestion footer. Quarantined fixture findings stay in `--json` but are never rendered.
- **New `--badge` flag**: emits a shields.io badge pinned to the Blast Radius band (never the numeric score, so published badges do not flap when scoring internals evolve). With `--json`, the report gains one additive top-level `"badge"` key; without `--badge`, `--json` output is byte-identical to before.
- **New `--fail-under <score>` CI gate**: exits `1` when the Blast Radius score is below the threshold and `0` otherwise, independent of whether findings exist. Thresholds are validated as integers from 0 to 100; invalid input exits `2` with a single actionable stderr line and no usage wall or traceback.
- **Windows-safe output**: the renderer falls back from the pinned em dash to `->` when the attached stdout encoding cannot represent it, so narrow console codepages (cp437/cp850) can never crash an audit run.

### Added — Audit Scan Engine (M2.0a)
- **New `scyvera audit [path]` command**: a bounded, read-only walk over a target tree scores it against the 11-rule AUxxx registry (`src/scyvera/audit_rules.py`) and emits a deterministic report — findings ordered by severity, rule id, and path, with no timestamp. `--json` prints that report as `report_version: 1` and nothing else.
- **Hardened scanning**: vendored and tooling directories (`.git`, `.venv`, `node_modules`, `dist`, `build`, `.agents`, and others) are skipped, files larger than 1 MiB are not read, binary content is sniffed and ignored, and symlinks are refused rather than followed (T14-consistent).
- **Diminishing per-rule loads (M2.0a.1)**: the first three occurrences of a rule contribute `1.00`, `0.25`, and `0.10` of its base weight, so one rule can add at most `1.35 x base`; the score is `max(0, 100 - ceil(total_load))`.
- **Fixture quarantine (M2.0a.1)**: findings under `tests/fixtures/`, or from a scan whose target is itself a fixture, stay visible in the report but contribute nothing to score, band, exit code, `draft_available`, `packs_suggested`, or `stats.findings`; a fixtures-only scan reports PASS and exits `0`.
- **Executable-context allowlist (M2.0a.1)**: `AU-SH-001`, `AU-GIT-001`, and `AU-NET-001` fire only in executable contexts — shell, PowerShell, batch, `Dockerfile*`, Makefile/justfile, and workflow `run:` blocks — never in prose, arbitrary YAML/JSON, or documentation.
- **Production hardening (PR #44)**: one typed executable-line parser now backs every context dialect, workflow `run:` blocks no longer leak indentation into a following `env:` block (fixing an AU-CI-001 false positive), and quarantine semantics are consistent end to end.
- **Dogfood gate**: `tests/test_audit_dogfood.py` runs `scyvera audit .` against this repository in CI and pins the Shielded band, so drift fails loudly instead of silently.
- **Docs**: RFC 0004 defines the report contract, scoring formula, and exit-code semantics; `CONTRIBUTING.md` and `.gitguardian.yaml` document the synthetic-fixture policy (scanner configuration excludes the path — tests are never weakened).

---

## [1.2.0] — 2026-10-31

### Added — Contract Registry, Dynamic Declarations & Gate Integrity (unreleased → released)
- **Contract Registry (`ContractRegistry`, `RegistryEntry`, `RegistryError`) (Phase 2)**:
  - Versioned, append-only, JSON-lines persistent store for registered contracts (`.scyvera/registry.jsonl`).
  - Idempotent registration on duplicate SHA-256 hash.
  - Automatic version incrementing per `node_id`.
  - Query APIs: `get_latest(node_id)`, `get_by_hash(contract_hash)`, `get_history(node_id)`, `get_at_time(node_id, timestamp)`, `list_nodes()`, `size()`, `has_hash(contract_hash)`.
  - Atomic writes using temporary file pattern to guarantee durability.
  - Fail-closed error handling raising `RegistryError` on corrupt or unreadable files.
- **Fail-Closed Gate Integrity (Threat T5 hardening)**:
  - `ContractEnforcer.gate()` now runs `verify_integrity()` before declaration checks; tampered or replaced contracts deny the action with an audited `DENIED` audit entry and raise `ContractTamperError` with recovery guidance instead of executing.
- **Governance Documentation & Distribution Roadmap (RFC 0003)**:
  - `docs/roadmap.md` — phased, task-gated implementation plan (P0–P4) with a locked glossary.
  - `rfcs/0003-harness-distribution-eval-and-integrity.md` — hash-chained registry, self-check, tiered conformance checking, trace-based eval harness, guardrail DSL, attested distribution artifacts.
  - `docs/threat-model-distribution.md` — distribution-layer threats T11–T14 (dependency confusion, contract substitution, registry history rewrite, symlink abuse).
  - `docs/architecture.md` renamed from the misspelled `achitecture.md`; README documentation tree refreshed.
- **Dynamic Contract Declarations (`ContractEnforcer.from_declaration()`) (Phase 1)**:
  - Create fully governed `ContractEnforcer` instances from in-memory Python dictionaries without requiring a `contract.yaml` file on disk.
  - Deep copy and cryptographic sealing with SHA-256 integrity hash at creation time.
  - Strict declaration validation (`DeclarationValidationError`) rejecting unknown fields, invalid `node_id` formatting, empty permissions, and wildcard injection (Threat T7).
  - Full feature parity with file-based enforcers: `@enforcer.gate(...)`, `verify_integrity()`, audit logs, and `approve()` work identically.
- **Enforcer Registration Integration**:
  - `ContractEnforcer.register(registry)` method to register an enforcer's contract directly into a registry and store `registry_entry_id`.
  - Added `node_id`, `contract_source`, and `registry_entry_id` properties to `ContractEnforcer`.
- **Expanded Test Suite**:
  - Added comprehensive test suites: `tests/test_declaration.py` (Phase 1) and `tests/test_registry.py` (Phase 2), bringing total tests to 141 passing tests.

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
