# Workflow & Agent Contract Specification

**Status:** Active  
**Versions:** v1 (Legacy) / v1.1 (Current)  
**Applies to:** Every workflow and agent implementation in this repository, across all frameworks (n8n, LangGraph, Python, or otherwise).

---

## 1. Why Contracts Exist

Documentation describes. Contracts commit.

A README can say an agent "only comments on GitHub issues." That is an informal prose claim — true until someone edits the code and forgets to update the text. An **Agent Contract** is different: it is a fixed-shape, machine-readable declaration of what a system is authorized to do, what external resources it accesses, what authority it requires, what constraints apply, and what side effects it produces.

The specification provides a structured format that humans, policy engines, and runtime enforcement tools can evaluate against actual behavior.

---

## 2. Specification Versions & Formats

### Canonical Filename
The canonical contract filename is **`contract.yaml`**. Contract files using the `.yml` extension are actively rejected by the loader and validator (`ContractFileNameError`) to enforce ecosystem consistency.

### Representation Formats
1. **Machine-readable YAML** — `contract.yaml` residing alongside the implementation or in standalone contract repositories.
2. **Dynamic Runtime Declarations** — Python dictionary declarations passed to `ContractEnforcer.from_declaration()`, sealed cryptographically with SHA-256 at creation time.
3. **Human-readable Documentation** — A `## Contract` table in each implementation's `README.md`.

### Versioning History
- **Contract v1**: Established the foundational operational fields for developer/workflow automation (inputs, outputs, permissions, side effects, approval points, recovery strategy, replay semantics, dependencies, state, observability).
- **Agent Contract v1.1**: Expanded to full domain independence (research, education, finance, healthcare, software), introduced structured `system` identity, formal `lifecycle` execution modes, structured `recovery`, `replay`, `approvals`, `constraints`, `risk`, `domain`, and artifact trust declarations.

---

## 3. Specification Fields

### Core Specification Fields (v1 & v1.1)

| Field | Version | Type | Description |
|---|---|---|---|
| `version` / `contract_version` | v1 / v1.1 | string / number | Specification version discriminator (`"1"` or `"1.1"`). |
| `system` | v1.1 | object | System identity: `name` (required), `purpose`, and `version`. (Legacy aliases: `agent`, `workflow`). |
| `domain` | v1.1 | string | Operational application domain (e.g. `software`, `research`, `education`, `finance`, `healthcare`). |
| `lifecycle` | v1.1 | object | Execution model and trigger semantics (`mode: request-response \| persistent \| scheduled`, `initiation`, `resumability`, `idle_behavior`). |
| `capabilities` | v1.1 | list | High-level semantic ability claims (e.g. `search_documents`, `analyze_code`). |
| `inputs` | v1 / v1.1 | list | Data payloads, event streams, or parameters entering the system. |
| `outputs` | v1 / v1.1 | list | Data payloads, structured artifacts, or return objects produced by the system. |
| `permissions` | v1 / v1.1 | list | Granular external resource scopes and action authorizations (e.g. `{resource: "github_issues", actions: ["read", "write"]}`). Prohibits wildcards (`*`, `all`, `any`). |
| `constraints` | v1.1 | list | Quantitative limits placed on authorized behavior (rate limits, transaction caps, allowed ranges). |
| `side_effects` | v1 / v1.1 | list | Externally observable changes caused by system operations (comments posted, database records modified, emails sent). Supports `irreversible: true`. |
| `approval_points` / `approvals` | v1 / v1.1 | list | Checkpoints where human confirmation is required prior to execution. An empty list (`[]`) is an explicit claim that no human approval is required. |
| `recovery` / `recovery_strategy` | v1 / v1.1 | object / string | Failure recovery behavior (`retry`, `stop`, `rollback`, `human_escalation`, `fallback`). |
| `replay` / `replay_semantics` | v1 / v1.1 | object / string | Execution safety when re-run on identical inputs (`idempotent`, `non_idempotent`, `conditional`, `prohibited`). |
| `dependencies` | v1 / v1.1 | list | External APIs, models, databases, or services required for execution. |
| `state` | v1 / v1.1 | object / string | Persistence tier (`none`, `session`, `persistent`, `ephemeral`), storage mechanism, and scope. |
| `observability` | v1 / v1.1 | object / list | Logging level (`none`, `basic`, `audit`, `verbose`) and notification sinks. |
| `risk` | v1.1 | object | Risk level assessment (`low`, `medium`, `high`, `critical`) and hazard category. |
| `artifacts` | v1.1 | list | External artifacts (models, datasets) with declared integrity and provenance requirements. |

---

## 4. Lifecycle Field Specification (v1.1)

The `lifecycle` block formalizes how an agent or workflow executes:

```yaml
lifecycle:
  mode: request-response     # request-response | persistent | scheduled
  initiation: human-only     # human-only | schedule | self | agent
  resumability: stateless   # stateless | context-snapshot | replay-from-log
  idle_behavior: null        # string (required when mode is persistent, max 500 chars)
```

- **`mode`**: Closed enum defining the execution model.
  - `request-response`: Bounded run triggered by an event, prompt, or webhook; tears down after execution.
  - `scheduled`: Triggered periodically by a clock or cron schedule.
  - `persistent`: Continuously active daemon or agent that maintains background monitoring or self-directed tasks. Requires an explicit, bounded `idle_behavior` description (enforced by schema and Rule AC301).
- **Backward Compatibility**: If a v1.1 contract omits `lifecycle`, the loader applies defaults (`{mode: "request-response", initiation: "human-only", resumability: "stateless"}`) and emits a warning advising the author to make lifecycle explicit.

---

## 5. Tooling and Enforcement Ecosystem

Unlike early drafts of this specification, comprehensive tooling is implemented in the `scyvera` package:

1. **Static Schema Validation (`validate_contract`)**: Validates contracts against JSON Schema Draft 2020-12 definitions (`schemas/v1/contract.schema.json` and `schemas/v1.1/contract.schema.json`).
2. **Semantic Linter (`lint_contract`)**: Tier 2 consistency analyzer evaluating rules:
   - `AC101`: Unbounded write permissions without declared side effects.
   - `AC103`: Capabilities duplicating operational permission verbs.
   - `AC201`: High-risk systems without approval gates.
   - `AC301`: Vague or unbounded `idle_behavior` strings.
   - `AC302`: Irreversible side effects without approval boundaries.
   - `AC401`: Required dependencies without recovery strategies.
   - `AC601`: Unobserved side effects.
3. **Runtime Enforcement Engine (`ContractEnforcer`)**:
   - `ContractEnforcer.load(path)`: Loads and freezes contract files, computing a SHA-256 hash.
   - `ContractEnforcer.from_declaration(dict)`: Dynamically compiles and cryptographically seals in-memory contract declarations.
   - `@enforcer.gate(action_name, action_type)`: Default-deny execution decorator for Python functions.
   - `enforcer.verify_integrity()`: Validates that the contract source has not been modified after load/seal.
   - `enforcer.get_audit_log()`: Produces tamper-proof, deep-copied audit entries.
4. **Gateway Boundary Layer (`BaseGateway`, `GitHubGateway`, `QdrantGateway`)**: Encapsulates third-party clients and credentials behind gated methods, structurally preventing gate bypass.
5. **Contract Registry (`ContractRegistry`)**: Versioned, append-only, JSONL persistent record of all registered contracts supporting point-in-time audit queries (`get_at_time`).

---

## 6. Worked Examples

### Example 1: Minimal Request-Response System (v1.1)

```yaml
version: "1.1"
contract_version: "1.1"

system:
  name: duplicate-issue-detector
  purpose: Detects semantically duplicate GitHub issues
  version: "1.0.0"

domain: software

lifecycle:
  mode: request-response
  initiation: human-only
  resumability: stateless

inputs:
  - name: github_issue
    type: webhook_payload
    required: true

outputs:
  - name: duplicate_comment
    type: github_comment

permissions:
  - resource: github_issues
    actions: [read, write]
  - resource: openai_embeddings
    actions: [read]
  - resource: qdrant_collection
    actions: [read, write]

side_effects:
  - type: comment
    resource: github_issues
    description: Posts one comment on the triggering issue if similarity exceeds threshold
    irreversible: false
  - type: vector_upsert
    resource: qdrant_collection
    description: Upserts issue embedding vector into Qdrant

approval_points: []   # Intentionally empty — comment-only, non-destructive

recovery:
  strategy: retry
  details: If Qdrant is unreachable, fails loudly and visibly in execution log

replay:
  mode: idempotent
  details: Re-running on same issue re-embeds and overwrites vector by issue number

dependencies:
  - name: GitHub API
    type: api
    required: true
  - name: OpenAI Embeddings API
    type: api
    required: true
  - name: Qdrant instance
    type: service
    required: true

state:
  persistence: persistent
  storage: qdrant_collection

observability:
  level: basic
  sinks: [github_comment]

risk:
  level: low
```

### Example 2: Persistent Autonomous Agent (v1.1)

```yaml
version: "1.1"
contract_version: "1.1"

system:
  name: repository-sentinel
  purpose: Autonomous agent that continuously monitors repository activity and queues security digests
  version: "1.0.0"

domain: software

lifecycle:
  mode: persistent
  idle_behavior: Monitors GitHub notifications for repository mentions and security advisories
  initiation: self
  resumability: context-snapshot

inputs:
  - name: notification_stream
    type: event_stream
    required: true

outputs:
  - name: security_digest
    type: document

permissions:
  - resource: github_api
    actions: [read, write]

side_effects:
  - type: comment
    resource: github_api
    description: Posts security review digest to internal tracking issue
    irreversible: false

approvals:
  - action: publish_digest
    required: true
    approver: human
    condition: Before publishing alerts externally

recovery:
  strategy: human_escalation

replay:
  mode: non_idempotent

dependencies:
  - name: GitHub API
    type: api
    required: true

state:
  persistence: persistent
  storage: local_context_snapshot

observability:
  level: audit

risk:
  level: medium
```

---

## 7. Contracts vs. Patterns

- **Pattern** (see `patterns/`): Framework-agnostic description of an abstract workflow shape (e.g. `detect → judge → approve → act` or `monitor → alert → escalate`).
- **Contract** (`contract.yaml`): Concrete declaration of one specific implementation's operational boundaries (exact permissions, credentials, resources, and side effects).

A single Pattern can have multiple independent implementations across different frameworks (such as n8n and LangGraph), each governed by its own Contract.
