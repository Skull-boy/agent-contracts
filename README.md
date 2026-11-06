<div align="center">
<img src="https://raw.githubusercontent.com/Skull-boy/agent-contracts/main/assets/scyvera.png" alt="Scyvera" width="320">

# Scyvera

**Set the boundary once. Get it enforced everywhere. Prove it forever.**

Operational contracts for AI agents: what a system can do, what it can access, and what it must never do — enforced at runtime and provable after the fact.

MCP and A2A standardize how agents communicate with tools and each other. Scyvera defines the layer above: the operational boundary those agents run inside.

[![License](https://img.shields.io/github/license/Skull-boy/agent-contracts)](./LICENSE)
[![Tests](https://github.com/Skull-boy/agent-contracts/actions/workflows/validate-contracts.yml/badge.svg)](https://github.com/Skull-boy/agent-contracts/actions/workflows/validate-contracts.yml)
[![PyPI](https://img.shields.io/pypi/v/scyvera)](https://pypi.org/project/scyvera/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![Security Policy](https://img.shields.io/badge/security-policy-blue)](./SECURITY.md)
[![Blast Radius](https://img.shields.io/badge/blast%20radius-shielded-green)](#-the-2-minute-demo)

<!-- TODO(G1): drop assets/scyvera-audit.gif (terminal capture of a blocked agent action, <2 MB) — recorded by maintainer, see roadmap G2 -->
</div>

---

> **Try it, read nothing first:** `pip install "scyvera @ git+https://github.com/Skull-boy/agent-contracts.git" && scyvera audit .`
>
> The audit funnel is on `main` and ships in the 1.3.0 release. Installs from 1.2.0 and earlier provide validation, linting, and enforcement only.

---

## ⚡ The 2-Minute Demo

**Scyvera in 23 seconds** — the audit, the generated draft, and the block that proves it:

![Scyvera in 23 seconds](assets/scyvera-demo.gif)

And this is `scyvera audit .` run inside the Scyvera repository itself:

```text
WARN  .
      Blast Radius: 92/100 (Shielded)
      Scanned 154 files (5 manifests, 9 workflow files, 44 source files, 6 shell scripts, 2 container files, 1 env file, 36 doc files, 51 other files)

      MEDIUM    [AU-N8N-001] n8n workflow with external writes
                implementations/n8n/competitor-feature-parity-watcher/workflow.json:169 + 3 more
      MEDIUM    [AU-NET-002] outbound network calls in source
                implementations/langgraph/duplicate-issue-detector/backfill.py:23 + 1 more

      With a contract: force-push -> requires approval; .env -> unread;
      npm publish -> forbidden.  Run with --generate to draft one.
```

The scan is read-only. It did not change a file.

**You never have to write a contract. The scan writes your first draft.**

### a. Scan anything

```bash
scyvera audit <path>
```

Bands from RFC 0004 §4:

| Band | Score | Interpretation |
|---|---|---|
| **Shielded** | 90–100 | Few or no scored findings; the scanned boundary is narrow. |
| **Controlled** | 70–89 | Some findings; the boundary is mostly declared, with gaps to review. |
| **Exposed** | 40–69 | Multiple or high-severity findings; the environment can do more than it declares. |
| **Unbounded** | 0–39 | Critical or broad findings; little enforceable boundary is present. |

A band summarizes a scan. It is not a security certification.

### b. Put a badge in your README

```bash
scyvera audit . --badge
```

Alongside the report, it prints the snippet below. This repository's own badge is in the hero row above.

```markdown
[![Blast Radius: Shielded](https://img.shields.io/badge/blast%20radius-Shielded-green)](scyvera)
```

### c. Gate CI

```bash
scyvera audit . --fail-under 90
```

Exit codes: `0` ok, `1` findings or threshold breach, `2` usage or I/O error.

One GitHub Actions step:

```yaml
- run: scyvera audit . --fail-under 90
```

### d. Adopt the boundary it found

```bash
scyvera audit . --generate contract.yaml
```

```text
Draft contract written to contract.yaml (validate with: scyvera validate contract.yaml).
```

The scan writes one schema-valid v1.1 contract. `scyvera validate contract.yaml` and `scyvera lint contract.yaml` both pass with 0 warnings, and a permanent fixture sweep enforces that for every audit corpus. `--force` overwrites an existing file; nothing else is ever written.

That draft is the input to the enforcement layer below: `ContractEnforcer.load("contract.yaml")` turns the scanned boundary into a runtime gate.

### e. Start from a policy, not a blank page

```bash
scyvera audit . --generate contract.yaml --pack github-safe
```

The pack's constraints win over heuristic-derived entries; finding-only extras are appended. Six golden packs ship in `packs/`: `dev-agent`, `github-safe`, `finance-ops`, `research-assistant`, `email-triage`, `devops-safe`. Loading is local-only. A pack is a starting boundary, not an audit result. See [`docs/policy-packs.md`](./docs/policy-packs.md).

---

## 🛡️ Governing for Real

Scanning shows what the environment can do. This section turns that into enforcement: the draft from step 2d is a normal v1.1 contract, so it loads into the enforcer, and the registry makes the boundary provable after the fact.

Scyvera provides four complementary governance layers:

| Layer | Component | Responsibility | Trust Level |
|---|---|---|---|
| **Tier 1 & 2: Static Verification** | `validate_contract()`, `lint_contract()` | Validates that a `contract.yaml` is structurally and semantically well-formed against JSON schemas and semantic rules (ACxxx taxonomy). | Declaration conformance |
| **Runtime Enforcement Engine** | `ContractEnforcer` (`load()`, `from_declaration()`) | Gates Python calls against declared permissions and side effects using **Default-Deny** semantics. Intercepts execution on approval boundaries (`ApprovalPendingError`). Cryptographically seals contracts with SHA-256. | Execution boundary enforcement |
| **Gateway Boundary Isolation** | `BaseGateway`, `GitHubGateway`, `QdrantGateway` | Single enforcement boundary: holds credentials privately and gates every external API call, structurally preventing gate bypass. | Credential & API isolation |
| **Contract Registry** | `ContractRegistry`, `RegistryEntry` | Append-only, versioned, persistent store of all contracts governed by Scyvera. Answers what contract governed which agent at any historical moment (`get_at_time()`). | Cryptographic provenance & audit |

### Contract CLI

Create a starter contract, or inspect one you already have. The CLI detects the specification version (`1` vs `1.1`) and validates against the matching JSON Schema.

```bash
scyvera init contract.yaml --name "Research Assistant" --domain "research"
scyvera validate contract.yaml
scyvera lint contract.yaml
scyvera check contract.yaml
```

```text
CREATED contract.yaml (spec version 1.1)
PASS  contract.yaml
PASS  contract.yaml (0 semantic warnings)
PASS  contract.yaml (tier 0 (structural): 0 schema errors, 0 semantic warnings)
```

`lint` runs the Tier 2 ACxxx rules: unbounded write permissions (AC101), high-risk systems without approvals (AC201), vague idle behavior (AC301), and irreversible actions without an approval boundary (AC302).

`check` (RFC 0003 §C3) runs the Tier 0 conformance check — `validate` + `lint` in one report, with `--tier {0,1,2,auto}` resolving to the highest implemented tier and never degrading silently. Tier 1 (`--tier 1`) now inspects n8n workflows and LangGraph implementations, comparing exercised services and approval gates against `contract.yaml` and reporting T101/T102/T103 findings (roadmap M2.2/M2.3).

### Runtime Enforcer

The `ContractEnforcer` protects your agent's execution boundaries in Python by enforcing **Default-Deny**: any undeclared permission or side effect raises `ContractViolationError`, and any action requiring approval raises `ApprovalPendingError`.

#### File-based contract gating

```python
from pathlib import Path
from scyvera import ContractEnforcer, ContractViolationError, ApprovalPendingError

# 1. Load, validate, and freeze contract.yaml from disk
enforcer = ContractEnforcer.load("implementations/n8n/duplicate-issue-detector/contract.yaml")

# 2. Gate sensitive tools and operations
@enforcer.gate(action_name="github:issues:write", action_type="permission")
def post_github_comment(issue_id: int, comment: str):
    print(f"Posting comment to issue #{issue_id}: {comment}")
    return True

@enforcer.gate(action_name="aws_s3:read", action_type="permission")
def read_s3_bucket():
    return "s3_data"

# 3. Allowed calls execute cleanly and log to the audit trail
post_github_comment(101, "Potential duplicate detected.")

# 4. Undeclared actions are denied immediately (Default-Deny)
try:
    read_s3_bucket()
except ContractViolationError as e:
    print(f"Blocked by Scyvera: {e}")

# 5. Inspect the immutable audit log
for entry in enforcer.get_audit_log():
    print(f"[{entry.timestamp}] {entry.decision} - {entry.action_name} ({entry.reason})")

# 6. Verify file integrity on disk (Threat T5 defense)
enforcer.verify_integrity()  # Raises ContractTamperError if contract.yaml was modified
```

#### Dynamic runtime declarations (no YAML file required)

For agents created dynamically at runtime, Scyvera supports code-declared contracts with the same enforcement guarantees:

```python
from scyvera import ContractEnforcer, DeclarationValidationError

# Declare the contract directly in Python — sealed cryptographically at creation
enforcer = ContractEnforcer.from_declaration({
    "node_id": "researcher-v1",
    "permissions": ["arxiv:read", "database:read"],
    "side_effects": ["database:write"],
    "approval_points": ["database:write"],
    "lifecycle": "request-response",
    "state": "stateless",
})

print(f"Sealed SHA-256 Digest: {enforcer.integrity_hash}")
print(f"Contract Source: {enforcer.contract_source}")  # 'declaration'

# Enforces identical default-deny rules
@enforcer.gate("arxiv:read", "permission")
def fetch_papers(topic: str):
    return ["paper1", "paper2"]

fetch_papers("quantum computing")  # Executes and logs to the audit trail
```

### Gateway Enforcement Architecture

In agent architectures, security boundaries fail if agents can bypass enforcers by importing and calling raw API clients directly. Scyvera solves this with **Gateways** (`BaseGateway`, `GitHubGateway`, `QdrantGateway`):

- **Single Enforcement Boundary**: API credentials and raw SDK clients (e.g. `PyGithub`, `qdrant-client`) are encapsulated privately within the gateway. No outside node holds credentials or raw clients.
- **Structural Gating**: Every public method is decorated per-instance with `@enforcer.gate(...)`. Any undeclared or unapproved action halts execution immediately via `ContractViolationError` or `ApprovalPendingError`.
- **Exception Normalization**: Client exceptions are caught and wrapped into `GatewayError` to ensure deterministic fault isolation.
- **CI Linting**: Scyvera includes a GitHub Actions workflow (`.github/workflows/lint-gateway.yml`) that scans the codebase and fails the build if any raw API client is imported outside `gateway.py`.

Install optional adapters with `pip install "scyvera[github]"`, `pip install "scyvera[qdrant]"`, or `pip install "scyvera[all]"`.

```python
from scyvera import ContractEnforcer, GitHubGateway, GatewayError, ContractViolationError

# 1. Load the contract enforcer
enforcer = ContractEnforcer.load("contract.yaml")

# 2. Instantiate the gateway with an injected enforcer and private credentials
gateway = GitHubGateway(enforcer, token="YOUR_GITHUB_TOKEN")

# 3. Gated read operation (succeeds if declared in the contract)
issue = gateway.read_issue("owner/repo", issue_number=42)

# 4. Gated mutating operation (enforces Default-Deny and approvals)
try:
    gateway.close_issue("owner/repo", issue_number=42)
except ContractViolationError as e:
    print(f"Blocked by Scyvera: {e}")
```

### Contract Registry

The `ContractRegistry` provides a versioned, append-only, persistent record of every contract that has governed any agent in your ecosystem. It answers: *"What contract governed this agent at this exact moment, and has that contract ever changed?"*

```python
from scyvera import ContractEnforcer, ContractRegistry

# 1. Initialize a registry backed by a persistent JSON-lines file
registry = ContractRegistry(".scyvera/registry.jsonl")

# 2. Register an agent enforcer (idempotent on duplicate contract hash)
enforcer = ContractEnforcer.from_declaration({
    "node_id": "triage-agent-v1",
    "permissions": ["github:read"],
    "side_effects": ["github:comment"],
})
entry = enforcer.register(registry)

print(f"Registered Version: {entry.version}")
print(f"Registry Entry ID: {entry.entry_id}")
print(f"Integrity Hash: {entry.contract_hash}")

# 3. Query the latest contract for an agent
latest_entry = registry.get_latest("triage-agent-v1")

# 4. Time-travel audit query: get the contract active at an exact historical timestamp
historical_entry = registry.get_at_time(
    node_id="triage-agent-v1",
    timestamp="2026-10-20T12:00:00+00:00",
)

# 5. Inspect the full version history for a node
history = registry.get_history("triage-agent-v1")
```

### Programmatic Contract Builder

You can construct, inspect, serialize, and validate Agent Contracts in Python without writing YAML by hand:

```python
from scyvera import Contract, validate_contract

# Programmatically construct a v1.1 Contract
contract = (
    Contract(name="Literature Research Assistant", purpose="Analyzes scientific papers")
    .set_domain("research")
    .add_capability("search_documents", description="Queries research repositories")
    .add_resource("paper_db", type="pdf_repository", access="read")
    .add_input("research_topic", type="string", required=True)
    .add_output("summary", type="document")
    .add_permission("paper_db", actions=["read", "search"])
    .set_state("session")
    .set_recovery("retry")
    .set_replay("idempotent")
    .set_observability("basic")
    .set_risk("low", category="misinformation_risk")
)

# Validate directly in code
result = contract.validate()

if result.valid:
    print("Contract is valid")
    contract.save("contract.yaml")
else:
    for err in result.errors:
        print(f"Error at {err.path}: {err.message}")
```

---

## 🧩 What This Actually Is

`Scyvera` provides a machine-readable specification and Python governance layer for defining and enforcing the operational boundary of intelligent or automated systems.

It is **NOT**:
- another agent framework
- an LLM wrapper
- an orchestration library
- a coding-agent framework
- an OS-level sandbox or anti-malware scanner

It **IS**:
A framework-independent and domain-independent governance layer describing and enforcing system identity, capabilities, resources, inputs, outputs, permissions, constraints, side effects, approvals, dependencies, state persistence, failure recovery, replay semantics, observability, and risk.

---

## ⚠️ What Scyvera Does Not Guarantee

Scyvera provides structural verification, runtime gating, gateway isolation, and registry provenance, but security is an end-to-end discipline:

1. **Gate Bypass at Call Sites (Threat T4)**: Scyvera enforces boundaries at the `@enforcer.gate(...)` decorator. To eliminate the risk of ungated bypass, applications should use Scyvera **Gateways** (`BaseGateway`, `GitHubGateway`, `QdrantGateway`), where credentials and raw SDK clients are kept strictly private. If invoking custom functions directly, integrators should use `ContractEnforcer.assert_gated(fn)` in integration test suites.
2. **Internal Third-Party Behavior / String Spoofing (Threat T6)**: Scyvera verifies that a declared intent (e.g. `github:issues:write`) matches an allowed permission in the contract. It does not perform dynamic bytecode analysis or network-packet inspection to guarantee that a third-party library does not execute unauthorized background network calls.
3. **Pre-Load File Tampering (Threat T5)**: The SHA-256 integrity check in `verify_integrity()` protects against file replacement AFTER load. It does not protect against a tampered `contract.yaml` present BEFORE `ContractEnforcer.load()` is called. For dynamic contracts created in-memory, `from_declaration()` seals the dictionary immediately upon construction.

---

## 🌐 Domain-Neutral Example Contracts (v1.1)

See [`examples/v1.1/`](./examples/v1.1) for runnable, validated v1.1 contracts across different domains. `scyvera audit --generate` produces drafts in this same v1.1 schema, so generated and hand-authored contracts share one format.

| Domain | Contract File | Description |
|---|---|---|
| **Education** | [`education-tutor.yaml`](./examples/v1.1/education-tutor.yaml) | Guided study tutor, low risk, session state |
| **Research** | [`research-assistant.yaml`](./examples/v1.1/research-assistant.yaml) | Scientific literature analysis, arXiv API dependency |
| **Finance** | [`financial-operations.yaml`](./examples/v1.1/financial-operations.yaml) | Critical risk, payment caps ($5000 USD limit), controller approval gate |
| **Healthcare** | [`clinical-information-assistant.yaml`](./examples/v1.1/clinical-information-assistant.yaml) | High risk, EHR database access, physician approval gate, model integrity requirements |

---

## 📂 Repository Structure

```text
agent-contracts/
├── README.md                           # This file
├── WORKFLOW-CONTRACT-SPEC.md           # Formal specification (v1 and v1.1)
├── CHANGELOG.md                        # Version history and releases
├── CONTRIBUTING.md                     # Contribution guidelines and testing
├── CONTRIBUTORS.md                     # Project contributors
├── LICENSE                             # MIT License
├── pyproject.toml                      # Build, packaging, and test configuration
├── requirements-dev.txt                # Development dependencies
├── .gitguardian.yaml                   # Scanner exclusion for synthetic audit fixtures
├── .github/workflows/
│   ├── lint-gateway.yml                # Fails on raw API client imports outside gateway.py
│   ├── publish-pypi.yml                # Tag-triggered wheel build and PyPI publish
│   └── validate-contracts.yml          # Build wheel, run tests, verify CLI
├── assets/                             # Logo and image assets
├── docs/
│   ├── contract-model-v1.1.md          # Normative v1.1 Specification Model
│   ├── contract-reference.md           # Contract Field Reference Cheatsheet
│   ├── design-principles.md            # Normative Design Principles
│   ├── threat-model-enforcer.md        # Runtime Threat Model (T4–T10)
│   ├── threat-model-distribution.md    # Distribution Threat Model (T11–T14)
│   ├── threat-model-lifecycle.md       # Lifecycle Governance Threat Model (T1–T3)
│   ├── roadmap.md                      # Implementation Roadmap & Task Sequencing
│   ├── terminology.md                  # Specification Terminology
│   ├── architecture.md                 # Repository Architectural Model
│   ├── policy-packs.md                 # Policy Pack format, packs, and merge rules
│   ├── vision.md                       # Strategic Project Vision
│   ├── workflow-engineering.md         # Engineering Philosophy
│   ├── concepts/                       # Concept deep-dives
│   │   ├── approval-boundaries.md
│   │   ├── permissions.md
│   │   ├── recovery.md
│   │   ├── replay-semantics.md
│   │   └── side-effects.md
│   └── spec/
│       └── contract-v1.1-design.md     # v1.1 design record
├── examples/
│   ├── tamper_demo.py                  # Integrity-check demonstration
│   └── v1.1/                           # Validated v1.1 domain examples
│       ├── business-automation.yaml
│       ├── clinical-information-assistant.yaml
│       ├── education-tutor.yaml
│       ├── financial-operations.yaml
│       ├── research-assistant.yaml
│       └── software-development-agent.yaml
├── patterns/                           # Reusable contract patterns
│   ├── detect-judge-approve-act.md
│   └── monitor-alert-escalate.md
├── packs/                              # Policy Packs (six golden packs, RFC 0004 §6)
│   ├── dev-agent.yaml
│   ├── devops-safe.yaml
│   ├── email-triage.yaml
│   ├── finance-ops.yaml
│   ├── github-safe.yaml
│   └── research-assistant.yaml
├── rfcs/                               # Specification RFCs
│   ├── 0002-lifecycle-field.md         # Lifecycle Field (v1.1, implemented)
│   ├── 0003-harness-distribution-eval-and-integrity.md
│   └── 0004-audit-cli-blast-radius-and-policy-packs.md
├── schemas/                            # Packaged JSON Schemas (v1 and v1.1)
│   ├── v1/contract.schema.json
│   └── v1.1/contract.schema.json
├── scripts/
│   └── validate_contracts.py           # Repository-wide contract validation
├── src/scyvera/                        # Python governance package
│   ├── __init__.py                     # Public API exports
│   ├── audit.py                        # Deterministic audit scan engine
│   ├── audit_rules.py                  # AUxxx rule registry and suggestion fragments
│   ├── builder.py                      # Programmatic Contract Builder API
│   ├── cli.py                          # CLI (audit, validate, lint, init)
│   ├── enforcer.py                     # Runtime enforcer and dynamic declarations
│   ├── exceptions.py                   # Custom exception hierarchy
│   ├── gateway.py                      # Gated gateway layer (base, GitHub, Qdrant)
│   ├── generate.py                     # Schema-valid contract draft generator
│   ├── linter.py                       # Tier 2 semantic linter (ACxxx taxonomy)
│   ├── packs.py                        # Policy Pack loader, validation, and errors
│   ├── packs/                          # Packaged Policy Packs (wheel data)
│   ├── registry.py                     # Versioned append-only contract registry
│   ├── report.py                       # Band-first Blast Radius renderer and badge
│   ├── validator.py                    # Multi-version schema validation engine
│   └── schemas/                        # Bundled schemas (v1 and v1.1)
│       ├── v1/contract.schema.json
│       └── v1.1/contract.schema.json
├── tests/
│   ├── fixtures/                       # Validator fixtures and the audit corpus
│   ├── test_audit.py                   # Rule, report shape, and exit-code tests
│   ├── test_audit_contexts.py          # Executable-context and quarantine tests
│   ├── test_audit_dogfood.py           # Permanent Shielded-band dogfood gate
│   ├── test_audit_generate.py          # Draft schema-accuracy and CLI sweep
│   ├── test_audit_report.py            # Terminal renderer, badge, and CI gate
│   ├── test_builder.py
│   ├── test_cli.py
│   ├── test_declaration.py             # Dynamic declaration and sealing tests
│   ├── test_duplicate_issue_detector_workflow.py
│   ├── test_enforcer.py                # Runtime enforcer tests (T1–T10)
│   ├── test_filename_enforcement.py
│   ├── test_gate_integrity.py
│   ├── test_gateway.py                 # Gateway boundary tests
│   ├── test_lifecycle.py
│   ├── test_linter.py
│   ├── test_packs.py                   # Policy Pack schema/lint sweep and CLI merge tests
│   ├── test_registry.py                # Contract registry tests
│   ├── test_schemas_sync.py
│   ├── test_validator.py
│   └── test_validator_v1_1.py
└── implementations/                    # Multi-framework reference implementations
    ├── n8n/                            # Four reference n8n workflows
    ├── langgraph/                      # LangGraph reference implementation
    └── rfcs/                           # Implementation design records
```

---

## 🗺️ Implementation Status & Roadmap

### Available Now

- **Agent Contracts v1 & v1.1 Specifications**: Machine-readable schemas for system identity, capabilities, permissions, constraints, side effects, approvals, dependencies, lifecycle, recovery, replay, observability, and risk.
- **Audit scan engine (`scyvera audit`)**: AUxxx rule registry, deterministic JSON report (`report_version: 1`), execution-context matching, skip list, size caps, binary sniffing, symlink refusal, and fixture quarantine.
- **Blast Radius Report**: band-first terminal renderer, `--badge` shields.io snippet (band only), and the `--fail-under` CI gate with exit codes `0` / `1` / `2`.
- **Contract draft generation (`--generate`)**: findings-derived v1.1 drafts with deterministic ordering, `--force` overwrite guard, and zero-warning `validate` / `lint` results enforced by a fixture sweep.
- **Policy Packs (`--pack`)**: six golden packs (`dev-agent`, `github-safe`, `finance-ops`, `research-assistant`, `email-triage`, `devops-safe`) loaded locally from `packs/<name>.yaml`, applied to `--generate` drafts, and shipped as wheel package data. Every pack must pass schema validation and zero-warning lint in the `tests/test_packs.py` sweep.
- **Static Validation Engine**: CLI and Python API (`validate_contract`) validating against bundled JSON Schemas.
- **Semantic Linter**: Tier 2 consistency rules (`lint_contract`) detecting unbounded write permissions (AC101), high-risk systems without approval gates (AC201), vague idle behavior (AC301), and irreversible actions (AC302).
- **Runtime Enforcer (`ContractEnforcer`)**: Default-deny execution gating (`@enforcer.gate`), post-load SHA-256 integrity checks, and audit trails.
- **Dynamic Declarations**: Runtime contract synthesis (`ContractEnforcer.from_declaration()`) with cryptographic sealing and strict validation.
- **Gated Gateways**: Isolated external API boundaries (`BaseGateway`, `GitHubGateway`, `QdrantGateway`) and CI lint checks enforcing credential privacy.
- **Contract Registry**: Versioned, append-only, JSONL contract store (`ContractRegistry`) with point-in-time time-travel queries.
- **Cross-Framework Implementations**: Proven parity between n8n and LangGraph reference implementations.
- **Permanent dogfood gate**: the test suite asserts that `scyvera audit .` keeps this repository in the `Shielded` band.

### Roadmap (planned, not yet implemented)

The full task-level plan lives in [`docs/roadmap.md`](./docs/roadmap.md). The next phases as recorded there:

- **Phase 1 — Core Hardening**: hash-chained `ContractRegistry`, trace schema layer, contract identity pinning against symlink escape and substitution, the re-seal ritual, and completed distribution threat-model status.
- **Phase 2 — Conformance & Evals**: tiered `scyvera check` (structural, static, runtime-trace) with n8n and LangGraph adapters, a trace-driven eval harness, report-format unification, and an additive v1.2 `guardrails` schema slice.
- **Phase 3 — Distribution**: the `scyvera-harness` skill, multi-runtime packaging for OpenCode / Claude / Gemini / Codex, Sigstore and SBOM release attestations, `scyvera self-check`, and the documentation surface upgrade.
- **Growth lane**: G2 launch film, G3 showcase gallery and pack curation, G4 contributor ladder. G1 is this README rewrite; the animated GIF of a blocked agent action is still outstanding.
- **Phase 4 — Optional enforcer upgrades**: sliding-window invocation throttling, asynchronous approval channels, and multi-agent contract negotiation.

---

## 🧪 Running Tests

```bash
pytest tests/ -v
```

The suite includes a permanent dogfood gate: it scans this repository and fails if `scyvera audit .` ever leaves the `Shielded` band. Generated contract drafts are likewise re-read from disk and re-validated in every test run.

---

## 🤝 Contributing

Contributions are welcome — new domain profiles, framework reference implementations, specification RFCs, or Python API improvements. See [CONTRIBUTING.md](./CONTRIBUTING.md) for details.

Good first contributions: a Policy Pack — start from the template in [`docs/policy-packs.md`](./docs/policy-packs.md); a domain example; an audit rule with fixtures.

---

## 📄 License

Distributed under the MIT License — see [LICENSE](./LICENSE) for details.

Maintained by [Shinjan Das](https://github.com/Skull-boy) and open-source contributors — see [CONTRIBUTORS.md](./CONTRIBUTORS.md).
