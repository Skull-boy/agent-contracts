# Repository Architecture

**Status:** Active  
**Applies to:** Repository organization, architectural layers, and governance mechanisms across `agent-contracts` and the `scyvera` Python package.

---

## 1. Architectural Layers

The repository is organized into four complementary layers:

```text
┌─────────────────────────────────────────────────────────────────────────┐
│  1. PATTERN LAYER (patterns/)                                           │
│  Framework-agnostic, reusable architectural shapes.                      │
│  e.g. detect → judge → approve → act, monitor → alert → escalate        │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     │  reusable pattern realized in
                                     │  multiple runtimes
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  2. IMPLEMENTATION LAYER (implementations/)                             │
│  Concrete agent realizations in specific frameworks.                    │
│  e.g. implementations/n8n/, implementations/langgraph/                  │
│  Each implementation contains source code, workflow, and a contract.   │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     │  every implementation declares
                                     │  an operational contract
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  3. CONTRACT SPECIFICATION & SCHEMAS (schemas/, WORKFLOW-CONTRACT-SPEC) │
│  Normative JSON schemas and field definitions (v1 and v1.1).            │
│  Defines what fields, enums, and invariants constitute a valid contract.│
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     │  contracts are validated and
                                     │  enforced by tooling
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  4. GOVERNANCE & RUNTIME ENGINE (src/scyvera/)                          │
│  Python governance package:                                             │
│  - Static Schema Validator & Tier 2 Semantic Linter                     │
│  - Runtime Enforcer (ContractEnforcer: load, from_declaration, gate)    │
│  - Gated Gateways (BaseGateway, GitHubGateway, QdrantGateway)           │
│  - Contract Registry (ContractRegistry: versioned append-only store)    │
│  - CLI application (scyvera validate, lint, init)                       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Repository Layout

| Directory / File | Layer | Contents |
|---|---|---|
| `patterns/` | Pattern | Reusable, framework-independent architectural designs |
| `implementations/<framework>/<name>/` | Implementation | Concrete implementations (code, workflow JSON, `contract.yaml`, README) |
| `schemas/v1/` & `schemas/v1.1/` | Specification | JSON Schema Draft 2020-12 definitions for Agent Contracts |
| `examples/v1.1/` | Reference | Runnable, schema-validated contracts across domains (education, finance, healthcare, research) |
| `src/scyvera/` | Governance Engine | Source code for the `scyvera` Python package |
| `tests/` | Verification | Pytest test suite covering validation, linter, enforcer, gateways, declarations, and registry |
| `docs/` | Documentation | Normative contract models, design principles, concepts, threat models, and terminology |
| `rfcs/` | Governance | Permanent numbered records of specification and architecture decisions |
| `WORKFLOW-CONTRACT-SPEC.md` | Specification | Formal field reference for v1 and v1.1 contracts |

---

## 3. Contribution & Evolution Workflow

### Adding a New Implementation
1. Identify the pattern implemented (or define a new one).
2. Create `implementations/<framework>/<name>/`.
3. Provide the runnable source/workflow, documentation, and a valid `contract.yaml`.
4. Validate the contract using `scyvera validate implementations/<framework>/<name>/contract.yaml`.

### Proposing a Specification Change
Changes to core contract fields or schema definitions require a formal RFC:
1. Open an issue tagged `rfc`.
2. Author a numbered proposal in `rfcs/` following the established RFC template.
3. Include at least one worked contract example demonstrating the proposed field in practice.
4. Update schemas in `src/scyvera/schemas/` and corresponding validator/linter logic once accepted.

---

## 4. Governance & Verification Guarantees

The architecture enforces a strict separation of concerns:
- **Contract Declaration**: What an autonomous system declares it can or will do.
- **Structural Validation**: Automated checking against formal JSON Schemas (`validate_contract`).
- **Semantic Consistency**: Tier 2 linting rules ensuring operational coherence (`lint_contract`).
- **Runtime Enforcement**: Interception of function calls via `@enforcer.gate` ensuring default-deny.
- **Gateway Boundary Isolation**: Encapsulation of third-party clients and credentials in `gateway.py` to prevent gate bypass.
- **Cryptographic Provenance**: Permanent append-only tracking in `ContractRegistry`.
