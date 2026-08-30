# Workflow Contract Specification — v1

**Status:** Draft
**Applies to:** every workflow in this repository, across every implementation (n8n, LangGraph, or otherwise)

---

## Why this exists

Documentation describes. Contracts commit.

A README can say a workflow "only comments on GitHub issues." That's a claim — true until someone edits the workflow and forgets to update the prose next to it. A Contract is different: it's a fixed-shape declaration of what a workflow is allowed to do, written so a human *or a tool* can check whether the actual implementation matches what it claims.

This spec defines that fixed shape.

---

## Format

Every workflow ships a Contract in two forms:

1. **Human-readable** — a `## Contract` section in the workflow's `README.md`, using the fields below
2. **Machine-readable** — a `contract.yaml` file in the same folder, same fields, structured for tooling to eventually validate against the actual `workflow.json`

The Markdown version is for people. The YAML version is what makes "contracts commit" true instead of aspirational — a future linter can check a workflow's actual HTTP/credential nodes against its declared `permissions` and flag a mismatch, the same way a type checker catches a lie in a function signature.

Until that linter exists, the YAML file is still worth writing — it's the difference between a promise and a promise written down in a form that *could* be checked.

---

## Required Fields

| Field | Type | Description |
|---|---|---|
| `lifecycle` | object | Execution model and trigger semantics. Required (default: `{mode: request-response}` for backward compatibility). |
| `inputs` | list | What data enters the workflow, and from where (trigger payload, uploaded file, API response) |
| `outputs` | list | What the workflow produces or returns, if anything |
| `permissions` | list | Every external system accessed, and the exact scope (e.g. `github: issues:write`, never a bare `github: full-access`) |
| `side_effects` | list | Every action the workflow can take in the world — comments posted, files written, messages sent, records updated. If it's not listed here, the workflow shouldn't do it. |
| `approval_points` | list | Where a human must explicitly approve before the workflow proceeds. An empty list is a real, intentional claim — it means nothing here requires approval, not that the author forgot to fill it in. |
| `recovery_strategy` | string | What happens when a dependency fails mid-run: retry, fail loudly, fail silently and log, partial-completion behavior |
| `replay_semantics` | string | Is it safe to run this workflow again on the same input? Idempotent, append-only, or unsafe-to-repeat — state explicitly |
| `dependencies` | list | External services/APIs/credentials required to run at all |
| `state` | string | What persists between runs, and where (a Google Sheet, a vector store, nothing) |
| `observability` | list | What the workflow surfaces about its own execution — logs, digest messages, dashboards |

### Lifecycle Field Specification

Field: `lifecycle`
Type: `object`
Required: `yes` (in v1.1; default: `{mode: request-response, initiation: human-only, resumability: stateless}` for backward compatibility — existing contracts without this field are treated as request-response)

Sub-fields:
- `mode`: `request-response` | `persistent` | `scheduled`
  - Defines the execution model of the agent. Closed enum — new modes require a spec RFC.
- `idle_behavior`: `null` (for request-response/scheduled) | string description of what the agent may do between triggers (required when `mode: persistent`, max 500 chars). Must be bounded and specific.
- `initiation`: `human-only` | `schedule` | `self` | `agent`
  - Who/what can trigger this agent to act.
- `resumability`: `stateless` | `context-snapshot` | `replay-from-log`
  - What "restart" means for this agent.

---

## Worked Examples

### Example 1: Request-Response Agent (Duplicate Issue Detector)

```yaml
# contract.yaml
version: 1.1
contract_version: "1.1"
system:
  name: duplicate-issue-detector
  purpose: Detect semantically duplicate GitHub issues
  version: "1.0.0"

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
    description: Posts one comment on the triggering issue, if similarity >= threshold
  - type: vector_upsert
    resource: qdrant_collection
    description: Writes one vector to the Qdrant collection

approval_points: []   # intentionally empty — comments only, no approval gate required

recovery:
  strategy: retry
  details: If Qdrant is unreachable, fails loudly and visibly in execution log.

replay:
  mode: idempotent
  details: Re-running on same issue re-embeds and overwrites vector by issue number.

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

### Example 2: Scheduled Agent (Competitor Feature Watcher)

```yaml
# contract.yaml
version: 1.1
contract_version: "1.1"
system:
  name: competitor-feature-watcher
  purpose: Periodically checks competitor product pages for feature changes
  version: "1.0.0"

lifecycle:
  mode: scheduled
  initiation: schedule
  resumability: stateless

inputs:
  - name: competitor_urls
    type: configuration
    required: true

outputs:
  - name: feature_diff_report
    type: document

permissions:
  - resource: competitor_websites
    actions: [read]
  - resource: internal_dashboard
    actions: [write]

side_effects:
  - type: notification
    resource: internal_dashboard
    description: Updates internal dashboard with newly detected competitor features

approval_points: []

recovery:
  strategy: retry

replay:
  mode: idempotent

dependencies:
  - name: HTTP client
    type: library
    required: true

state:
  persistence: persistent
  storage: database

observability:
  level: basic

risk:
  level: low
```

### Example 3: Persistent Autonomous Agent (Headlong-style)

```yaml
# contract.yaml
version: 1.1
contract_version: "1.1"
system:
  name: headlong-persistent-agent
  purpose: Autonomous agent that continuously monitors and responds to environment changes
  version: "1.0.0"

lifecycle:
  mode: persistent
  idle_behavior: Monitors GitHub notifications for mentions of the repository and queues responses for review
  initiation: self
  resumability: context-snapshot

inputs:
  - name: environment_events
    type: stream
    required: true

outputs:
  - name: research_report
    type: document

permissions:
  - resource: github_api
    actions: [read, write]
  - resource: web_search
    actions: [read]

side_effects:
  - type: comment
    resource: github_api
    description: Posts research findings as GitHub issue comments
    irreversible: false

approvals:
  - action: publish_report
    required: true
    approver: human
    condition: Before any external publication

recovery:
  strategy: human_escalation

replay:
  mode: non_idempotent

dependencies:
  - name: GitHub API
    type: api
    required: true
  - name: Search Engine API
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

## Contracts vs. Patterns — two different layers

A **Contract** describes one specific implementation's behavior. A **Pattern** (see `patterns/`) describes the reusable shape underneath it — `detect → judge → approve → act`, for example — independent of any framework.

A pattern can have many Contracts implementing it (an n8n version, a LangGraph version), each with its own permissions and side effects, because the same abstract shape can be wired up differently. Don't conflate the two: a Contract is concrete and framework-specific; a Pattern is abstract and framework-agnostic.

---

## Versioning & Change Process

This is v1. Fields may be added in v2, but existing v1 fields will not be silently redefined — a field's meaning, once shipped, is stable.

To propose a change:
1. Open an issue tagged `contract-rfc`
2. Include at least one worked example showing the proposed field/change applied to a real workflow in this repo
3. A change is only accepted once at least one existing workflow's Contract has been updated to demonstrate it works in practice — a proposal with no worked example doesn't get merged, no matter how reasonable it sounds in the abstract

This mirrors the project's own founding lesson: several independent people converged on the same missing pieces through real discussion, not one person designing in isolation. The RFC process is that lesson turned into a mechanism.

---

## Migration Note

Workflows documented before this spec existed (the original four in this repository) currently have a Contract-shaped section in their README using an earlier, five-field informal version (`Inputs / Permissions Required / Side Effects / Approval Points / Recovery Behavior`). These are not wrong — they're a subset of v1. Each should be upgraded to the full v1 field set (and given a `contract.yaml`) as a small, individually-trackable issue rather than one large rewrite.

---

## Non-Goals for v1

- **No enforcement tooling yet.** A linter that validates `contract.yaml` against the actual `workflow.json` is a real future goal, not part of this version. v1 is the schema the linter will eventually check against.
- **No cross-framework contract translation.** A LangGraph implementation of the same pattern writes its own Contract; this spec doesn't attempt to auto-translate one framework's contract into another's.
