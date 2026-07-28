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

---

## Worked Example

Using the Semantic Duplicate Issue Detector as the reference implementation:

```yaml
# contract.yaml
version: 1
workflow: duplicate-issue-detector

inputs:
  - GitHub issue title + body (from webhook trigger)

outputs:
  - One comment on the triggering issue, only if a duplicate is found

permissions:
  - github: issues:write   # comment only — never close, label, or edit
  - openai: embeddings:read
  - qdrant: read+write on one collection

side_effects:
  - Posts one comment on the triggering issue, if similarity >= threshold
  - Writes one vector to the Qdrant collection

approval_points: []   # intentionally empty — this workflow only ever comments,
                       # never closes or merges, so no approval gate is required

recovery_strategy: >
  If Qdrant is unreachable, the run fails loudly and visibly in n8n's
  execution log. It does not silently skip the duplicate check.

replay_semantics: >
  Idempotent per issue — re-running on the same issue re-embeds and
  re-checks, but the Qdrant upsert uses the issue number as point ID,
  so it overwrites rather than duplicates.

dependencies:
  - GitHub API
  - OpenAI Embeddings API
  - Qdrant instance

state: >
  Persisted in a Qdrant collection — one vector per previously-seen issue.

observability:
  - GitHub comment itself is the only execution signal (no separate log/digest)
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
