<div align="center">
<img src="https://raw.githubusercontent.com/Skull-boy/agent-contracts/main/assets/scyvera.png" alt="Scyvera" width="320">
    
# Scyvera

**Machine-readable, domain-independent, and framework-independent operational contracts for AI agents and automated systems.**

MCP and A2A standardize how agents communicate with tools and each other. `Scyvera` defines the layer above: what an intelligent system can do, what resources it can access, what authority it requires, what constraints apply, what side effects it produces, and how it is governed.

[![License](https://img.shields.io/github/license/Skull-boy/agent-contracts)](./LICENSE)
[![Tests](https://img.shields.io/badge/tests-141%20passed-brightgreen)](#-running-tests)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](./CONTRIBUTING.md)

</div>

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

## 🛡️ Governance & Enforcement Architecture

Scyvera provides four complementary governance layers:

| Layer | Component | Responsibility | Trust Level |
|---|---|---|---|
| **Tier 1 & 2: Static Verification** | `validate_contract()`, `lint_contract()` | Validates that a `contract.yaml` is structurally and semantically well-formed against JSON schemas and semantic rules (ACxxx taxonomy). | Declaration conformance |
| **Runtime Enforcement Engine** | `ContractEnforcer` (`load()`, `from_declaration()`) | Gates Python calls against declared permissions and side effects using **Default-Deny** semantics. Intercepts execution on approval boundaries (`ApprovalPendingError`). Cryptographically seals contracts with SHA-256. | Execution boundary enforcement |
| **Gateway Boundary Isolation** | `BaseGateway`, `GitHubGateway`, `QdrantGateway` | Single enforcement boundary: holds credentials privately and gates every external API call, structurally preventing gate bypass. | Credential & API isolation |
| **Contract Registry** | `ContractRegistry`, `RegistryEntry` | Append-only, versioned, persistent store of all contracts governed by Scyvera. Answers what contract governed which agent at any historical moment (`get_at_time()`). | Cryptographic provenance & audit |

---

## ⚡ Quickstart

### 1. Installation

Install the core package from PyPI:

```bash
pip install scyvera
```

Or install with optional gateway adapters:

```bash
# With PyGithub for GitHubGateway
pip install "scyvera[github]"

# With qdrant-client for QdrantGateway
pip install "scyvera[qdrant]"

# With all gateway adapters
pip install "scyvera[all]"

# For local development:
pip install -e ".[dev]"
```

### 2. Command-Line Interface (CLI)

#### Create a starter Contract template (v1.1)
```bash
scyvera init contract.yaml --name "Research Assistant" --domain "research"
```

Interactive wizard mode:
```bash
scyvera init contract.yaml -i
```

#### Validate an Agent Contract
The CLI automatically detects the specification version (`1` vs `1.1`) and validates against the corresponding JSON Schema:
```bash
scyvera validate contract.yaml
```

Output:
```text
PASS  contract.yaml
```

#### Semantic Linting (Tier 2 consistency)
```bash
scyvera lint contract.yaml
```

---

## 🔒 Runtime Enforcer

The `ContractEnforcer` protects your agent's execution boundaries in Python by enforcing **Default-Deny**: any undeclared permission or side effect raises `ContractViolationError`, and any action requiring approval raises `ApprovalPendingError`.

### File-Based Contract Gating

```python
from pathlib import Path
from scyvera import ContractEnforcer, ContractViolationError, ApprovalPendingError

# 1. Load, validate, and freeze contract.yaml from disk
enforcer = ContractEnforcer.load("implementations/n8n/duplicate-issue-detector/contract.yaml")

# 2. Gate sensitive tools and operations
@enforcer.gate(action_name="github_issues:write", action_type="permission")
def post_github_comment(issue_id: int, comment: str):
    print(f"Posting comment to issue #{issue_id}: {comment}")
    return True

@enforcer.gate(action_name="aws_s3:read", action_type="permission")
def read_s3_bucket():
    return "s3_data"

# 3. Allowed calls execute cleanly and log to audit trail
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

### Dynamic Runtime Declarations (No YAML File Required)

For agents created dynamically at runtime, Scyvera supports code-declared contracts with the exact same enforcement guarantees:

```python
from scyvera import ContractEnforcer, DeclarationValidationError

# Declare contract directly in Python — sealed cryptographically at creation
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

fetch_papers("quantum computing")  # Executes and logs to audit trail
```

---

## 🚪 Gateway Enforcement Architecture

In agent architectures, security boundaries fail if agents can bypass enforcers by importing and calling raw API clients directly. Scyvera solves this with **Gateways** (`BaseGateway`, `GitHubGateway`, `QdrantGateway`):

- **Single Enforcement Boundary**: API credentials and raw SDK clients (e.g. `PyGithub`, `qdrant-client`) are encapsulated privately within the gateway. No outside node holds credentials or raw clients.
- **Structural Gating**: Every public method is decorated per-instance with `@enforcer.gate(...)`. Any undeclared or unapproved action halts execution immediately via `ContractViolationError` or `ApprovalPendingError`.
- **Exception Normalization**: Client exceptions are caught and wrapped into `GatewayError` to ensure deterministic fault isolation.
- **CI Linting**: Scyvera includes a GitHub Actions workflow (`.github/workflows/lint-gateway.yml`) that scans the codebase and fails the build if any raw API client is imported outside `gateway.py`.

```python
from scyvera import ContractEnforcer, GitHubGateway, GatewayError, ContractViolationError

# 1. Load the contract enforcer
enforcer = ContractEnforcer.load("contract.yaml")

# 2. Instantiate gateway with injected enforcer and private credentials
gateway = GitHubGateway(enforcer, token="ghp_...")

# 3. Gated read operation (succeeds if declared in contract)
issue = gateway.read_issue("owner/repo", issue_number=42)

# 4. Gated mutating operation (enforces Default-Deny & approvals)
try:
    gateway.close_issue("owner/repo", issue_number=42)
except ContractViolationError as e:
    print(f"Blocked by Scyvera: {e}")
```

---

## 🏛️ Contract Registry

The `ContractRegistry` provides a versioned, append-only, persistent record of every contract that has governed any agent in your ecosystem. It answers: *"What contract governed this agent at this exact moment, and has that contract ever changed?"*

```python
from scyvera import ContractEnforcer, ContractRegistry

# 1. Initialize registry backed by persistent JSON-lines file
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

# 4. Time-travel audit query: get contract active at an exact historical timestamp
historical_entry = registry.get_at_time(
    node_id="triage-agent-v1",
    timestamp="2026-10-20T12:00:00+00:00",
)

# 5. Inspect full version history for a node
history = registry.get_history("triage-agent-v1")
```

---

## 🛠️ Programmatic Contract Builder

You can programmatically construct, inspect, serialize, and validate Agent Contracts in Python without manually writing YAML:

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
    print("Contract is valid!")
    contract.save("contract.yaml")
else:
    for err in result.errors:
        print(f"Error at {err.path}: {err.message}")
```

---

## ⚠️ What Scyvera Does Not Guarantee

Scyvera provides structural verification, runtime gating, gateway isolation, and registry provenance, but security is an end-to-end discipline:

1. **Gate Bypass at Call Sites (Threat T4)**: Scyvera enforces boundaries at the `@enforcer.gate(...)` decorator. To eliminate the risk of ungated bypass, applications should use Scyvera **Gateways** (`BaseGateway`, `GitHubGateway`, `QdrantGateway`), where credentials and raw SDK clients are kept strictly private. If invoking custom functions directly, integrators should use `ContractEnforcer.assert_gated(fn)` in integration test suites.
2. **Internal Third-Party Behavior / String Spoofing (Threat T6)**: Scyvera verifies that a declared intent (e.g. `github:issues:write`) matches an allowed permission in the contract. It does not perform dynamic bytecode analysis or network-packet inspection to guarantee that a third-party library does not execute unauthorized background network calls.
3. **Pre-Load File Tampering (Threat T5)**: The SHA-256 integrity check in `verify_integrity()` protects against file replacement AFTER load. It does not protect against a tampered `contract.yaml` present BEFORE `ContractEnforcer.load()` is called. For dynamic contracts created in-memory, `from_declaration()` seals the dictionary immediately upon construction.

---

## 🌐 Domain-Neutral Example Contracts (v1.1)

See [`examples/v1.1/`](./examples/v1.1) for runnable, validated v1.1 contracts across different domains:

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
├── README.md                           # Main project documentation
├── WORKFLOW-CONTRACT-SPEC.md           # Formal specification (v1 and v1.1)
├── CHANGELOG.md                        # Version history and releases
├── CONTRIBUTING.md                     # Contribution guidelines and testing
├── CONTRIBUTORS.md                     # Project contributors
├── LICENSE                             # MIT License
├── pyproject.toml                      # Build and packaging configuration
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
│   ├── vision.md                       # Strategic Project Vision
│   ├── workflow-engineering.md         # Engineering Philosophy
│   └── concepts/                       # Concept deep-dives
│       ├── approval-boundaries.md
│       ├── permissions.md
│       ├── recovery.md
│       ├── replay-semantics.md
│       └── side-effects.md
├── examples/v1.1/                      # Validated v1.1 Domain Examples
│   ├── business-automation.yaml
│   ├── clinical-information-assistant.yaml
│   ├── education-tutor.yaml
│   ├── financial-operations.yaml
│   ├── research-assistant.yaml
│   └── software-development-agent.yaml
├── patterns/                           # Reusable Contract Patterns
│   ├── detect-judge-approve-act.md
│   └── monitor-alert-escalate.md
├── rfcs/                               # Specification RFCs
│   ├── 0002-lifecycle-field.md         # Lifecycle Field (v1.1, Implemented)
│   └── 0003-harness-distribution-eval-and-integrity.md   # Distribution & Integrity Layer (Proposed)
├── src/scyvera/                        # Python Governance Package
│   ├── __init__.py                     # Public API exports
│   ├── builder.py                      # Programmatic Contract Builder API
│   ├── cli.py                          # CLI Application (validate, init, lint)
│   ├── enforcer.py                     # Runtime Contract Enforcer & Dynamic Declarations
│   ├── exceptions.py                   # Custom Exception Hierarchy
│   ├── gateway.py                      # Gated Gateway Layer (Base, GitHub, Qdrant)
│   ├── linter.py                       # Tier 2 Semantic Linter (ACxxx taxonomy)
│   ├── registry.py                     # Versioned Append-Only Contract Registry
│   ├── validator.py                    # Multi-Version Schema Validation Engine
│   └── schemas/                        # Bundled JSON Schemas (v1 and v1.1)
│       ├── v1/contract.schema.json
│       └── v1.1/contract.schema.json
├── tests/                              # Pytest test suite (128 passing tests)
│   ├── fixtures/                       # Test fixture files
│   ├── test_builder.py
│   ├── test_cli.py
│   ├── test_declaration.py            # Dynamic Declaration & Sealing Tests
│   ├── test_duplicate_issue_detector_workflow.py
│   ├── test_enforcer.py               # Runtime Enforcer Tests (T1–T10)
│   ├── test_filename_enforcement.py
│   ├── test_gateway.py                # Gateway Boundary Tests
│   ├── test_lifecycle.py
│   ├── test_linter.py
│   ├── test_registry.py               # Contract Registry Tests
│   ├── test_schemas_sync.py
│   ├── test_validator.py
│   └── test_validator_v1_1.py
└── implementations/                    # Multi-Framework Implementations
    ├── n8n/                            # Reference n8n workflows
    └── langgraph/                      # LangGraph reference implementation
```

---

## 🗺️ Implementation Status & Roadmap

### Available Now
- **Agent Contracts v1 & v1.1 Specifications**: Machine-readable schemas for system identity, capabilities, permissions, constraints, side effects, approvals, dependencies, lifecycle, recovery, replay, observability, and risk.
- **Static Validation Engine**: CLI and Python API (`validate_contract`) validating against bundled JSON Schemas.
- **Semantic Linter**: Tier 2 consistency rules (`lint_contract`) detecting unbounded write permissions (AC101), high-risk systems without approval gates (AC201), vague idle behavior (AC301), and irreversible actions (AC302).
- **Runtime Enforcer (`ContractEnforcer`)**: Default-deny execution gating (`@enforcer.gate`), post-load SHA-256 integrity checks, and tamper-proof audit trails.
- **Dynamic Declarations**: Runtime contract synthesis (`ContractEnforcer.from_declaration()`) with cryptographic sealing and strict validation.
- **Gated Gateways**: Isolated external API boundaries (`BaseGateway`, `GitHubGateway`, `QdrantGateway`) and CI lint checks enforcing credential privacy.
- **Contract Registry**: Versioned, append-only, JSONL contract store (`ContractRegistry`) with point-in-time time-travel queries.
- **Cross-Framework Implementations**: Proven parity between n8n and LangGraph reference implementations.

### Roadmap (Planned, not yet implemented)
The full task-level plan lives in [`docs/roadmap.md`](./docs/roadmap.md); the next development wave is formalized in [RFC 0003 — Harness Distribution, Conformance Evaluation & Integrity Layer](./rfcs/0003-harness-distribution-eval-and-integrity.md). Headlines:

- **Phase 1 — Core Hardening**: hash-chained `ContractRegistry` (tamper-evident provenance, T13), contract identity pinning against symlink escape and prompt-injection substitution (T12/T14), package self-integrity attestation (T11).
- **Phase 2 — Conformance & Evals**: tiered `scyvera check` (structural → static → runtime-trace) with adapters for n8n and LangGraph, a runtime-trace eval harness, and an additive optional `guardrails` schema slice (fail-closed, budgets, rate limits).
- **Phase 3 — Distribution**: `scyvera-harness` skill for OpenCode / Claude / Codex / Gemini, attested releases (Sigstore signature + SBOM), and `scyvera self-check` against signed manifests.

Existing known-future capabilities (async approval channels, AST capability inference, multi-agent negotiation, sliding-window invocation throttling) are tracked as Phase 4 tasks in the roadmap.

---

## 🧪 Running Tests

Run the full 141-test test suite:

```bash
pytest tests/ -v
```

---

## 🤝 Contributing

Contributions are welcome — new domain profiles, framework reference implementations, specification RFCs, or Python API improvements. See [CONTRIBUTING.md](./CONTRIBUTING.md) for details.

---

## 📄 License

Distributed under the MIT License — see [LICENSE](./LICENSE) for details.

Maintained by [Shinjan Das](https://github.com/Skull-boy) and open-source contributors — see [CONTRIBUTORS.md](./CONTRIBUTORS.md).
