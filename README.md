<div align="center">
<img src="https://raw.githubusercontent.com/Skull-boy/agent-contracts/main/assets/scyvera.png" alt="Scyvera" width="320">

# Scyvera

**Machine-readable, domain-independent, and framework-independent operational contracts for AI agents and automated systems.**

MCP and A2A standardize how agents communicate with tools and each other. `Scyvera` defines the layer above: what an intelligent system can do, what resources it can access, what authority it requires, what constraints apply, what side effects it produces, and how it is governed.

![License](https://img.shields.io/github/license/Skull-boy/agent-contracts)
![Stars](https://img.shields.io/github/stars/Skull-boy/agent-contracts)
![Issues](https://img.shields.io/github/issues/Skull-boy/agent-contracts)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)

</div>


---

## 🧩 What This Actually Is

`Scyvera` provides a machine-readable specification and Python tooling layer for defining the operational boundary of intelligent or automated systems.

It is **NOT**:
- another agent framework
- an LLM wrapper
- an orchestration library
- a coding-agent framework
- a security sandbox or malware scanner

It **IS**:
A framework-independent and domain-independent specification layer describing system identity, capabilities, resources, inputs, outputs, permissions, constraints, side effects, approvals, dependencies, state persistence, failure recovery, replay semantics, observability, artifact trust declarations, and risk.

---

## ⚡ Quickstart

### 1. Installation

Install locally or in your project virtualenv:

```bash
pip install scyvera
# Or for local development:
pip install -e .
```

### 2. Command-Line Interface (CLI)

#### Create a starter Contract template (v1.1)
```bash
scyvera init contract.yaml --name "Research Assistant"
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

Override with a custom JSON Schema file:
```bash
scyvera validate contract.yaml --schema path/to/custom.schema.json
```

---

## 🐍 Python API & Programmatic Contract Builder

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
    # Save to file
    contract.save("contract.yaml")
else:
    for err in result.errors:
        print(f"Error at {err.path}: {err.message}")
```

Validate an existing YAML file programmatically:
```python
from scyvera import validate_contract

result = validate_contract("contract.yaml")
print(f"Valid: {result.valid}")
```

---

## 📋 Every Implementation Documents a Contract

Instead of prose documentation alone, systems in this repository specify:

- **Identity & Purpose** — system identity, operational scope, and system version
- **Capabilities** — semantic ability claims
- **Resources** — data stores, APIs, entities, or systems accessed
- **Inputs & Outputs** — data entering and produced by the system
- **Permissions** — exact authorized `{resource, actions[]}` combinations
- **Constraints** — quantitative limits (e.g. rate limits, transaction caps)
- **Side Effects** — externally observable mutations
- **Approvals** — explicit human or expert approval gates
- **Dependencies** — required external services, models, APIs
- **State, Recovery, Replay, Observability** — persistence, failure strategy, idempotency, and audit evidence
- **Artifact Security & Risk** — model/data artifact trust requirements and risk level classification

---

## 📂 Repository Structure

```text
agent-contracts/
├── README.md
├── WORKFLOW-CONTRACT-SPEC.md
├── CONTRIBUTING.md
├── CONTRIBUTORS.md
├── LICENSE
├── pyproject.toml
├── docs/
│   ├── contract-model-v1.1.md          # Normative v1.1 Specification
│   ├── vision.md                       # Strategic Project Vision
│   ├── design-principles.md            # Normative Design Principles
│   └── terminology.md                  # Specification Terminology
├── schemas/
│   ├── v1/                             # Contract v1 JSON Schema
│   │   └── contract.schema.json
│   └── v1.1/                           # Contract v1.1 JSON Schema
│       └── contract.schema.json
├── examples/
│   └── v1.1/                           # Domain-Neutral Examples (v1.1)
│       ├── education-tutor.yaml
│       ├── research-assistant.yaml
│       ├── financial-operations.yaml
│       └── clinical-information-assistant.yaml
├── src/
│   └── scyvera/                # Python Package
│       ├── __init__.py
│       ├── builder.py                  # Programmatic Contract Builder API
│       ├── validator.py                # Multi-Version Validator Engine
│       ├── cli.py                      # CLI Application (validate, init)
│       └── schemas/                    # Bundled Package Schemas
├── tests/
│   ├── fixtures/                       # Test Fixture Files
│   ├── test_validator.py              # v1 Validator Unit Tests
│   ├── test_validator_v1_1.py         # v1.1 Validator Unit Tests
│   ├── test_builder.py                # Programmatic Builder Unit Tests
│   └── test_cli.py                    # CLI Unit Tests
└── implementations/                    # Multi-Framework Reference Implementations
    ├── n8n/
    └── langgraph/
```

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

## 🔐 Security & Governance Boundary Notice

> [!IMPORTANT]
> **Contract Declaration ≠ Security Verification ≠ Runtime Enforcement.**
> An Agent Contract describes declared operational boundaries. It is not a sandbox, anti-malware scanner, or runtime enforcement proxy. Contract declarations provide structured input upon which external policy engines, verification scanners, and runtime isolation systems operate.

---

## 🗺️ Where the Spec Is Headed (v1.1)

Contract v1 was designed and proven against coding/developer agents. That's now understood to be a starting substrate, not the ceiling — v1.1 is a deliberate audit-and-redesign effort to make the spec:

- **Domain-independent** — usable for research, education, finance, business-workflow, and healthcare-workflow agents, not just coding agents
- **Framework-independent** — already true in principle (n8n + LangGraph prove it), being stress-tested further
- **Accessible to non-technical authors** — YAML/JSON is a representation format, not meant to be the only way to create a contract

This is genuinely in the design/audit phase — classifying existing Contract v1 fields, testing them against non-coding agent archetypes, and only then extending the schema. Nothing in this section describes a shipped feature. Follow progress in [`implementations/rfcs/`](./implementations/rfcs) and open issues tagged `v1.1`.

---

## 🤝 Contributing

Contributions are welcome — new domain profiles, framework reference implementations, specification RFCs, or Python API improvements. See [CONTRIBUTING.md](./CONTRIBUTING.md) for details.

---

## 📄 License

Distributed under the MIT License — see [LICENSE](./LICENSE) for details.

Built and maintained by [Shinjan Das](https://github.com/Skull-boy) and open-source contributors — see [CONTRIBUTORS.md](./CONTRIBUTORS.md).
