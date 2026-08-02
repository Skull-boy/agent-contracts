# Architecture

**Status:** Draft
**Applies to:** how this repository itself is organized — the structural counterpart to [`workflow-engineering.md`](./workflow-engineering.md)'s reasoning and [`WORKFLOW-CONTRACT-SPEC.md`](../WORKFLOW-CONTRACT-SPEC.md)'s field definitions

---

## Why this document is separate from the other two

`workflow-engineering.md` answers *why this repository exists*. `WORKFLOW-CONTRACT-SPEC.md` answers *what fields a Contract contains*. Neither answers *how the pieces actually fit together* — which folder holds what, how a contribution moves from idea to merged code, where a disagreement gets resolved. That's this document's job.

---

## The three-layer model

```
┌─────────────────────────────────────────────────────────────┐
│  PATTERN                                                      │
│  Framework-agnostic. Describes a reusable shape.               │
│  e.g. detect → judge → approve → act                           │
│  Lives in: patterns/                                           │
└───────────────────────────┬─────────────────────────────────┘
                             │
                             │  one pattern, many possible
                             │  implementations
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  IMPLEMENTATION                                                │
│  Framework-specific. One concrete realization of a pattern.    │
│  e.g. the n8n duplicate-issue-detector workflow                 │
│  Lives in: implementations/<framework>/<name>/                  │
└───────────────────────────┬─────────────────────────────────┘
                             │
                             │  every implementation declares
                             │  its own behavior
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  CONTRACT                                                      │
│  Implementation-specific. What this exact implementation is    │
│  allowed to do — permissions, side effects, approval points.    │
│  Lives in: implementations/<framework>/<name>/contract.yaml     │
└─────────────────────────────────────────────────────────────┘
```

A Pattern can have many Implementations (n8n today, LangGraph or Make tomorrow). Every Implementation has exactly one Contract, because permissions and side effects are specific to how that implementation was actually built — not to the abstract shape it follows. See [`WORKFLOW-CONTRACT-SPEC.md`](../WORKFLOW-CONTRACT-SPEC.md#contracts-vs-patterns--two-different-layers) for why this project deliberately keeps Contract scoped to Implementation rather than Pattern.

---

## Repository layout, mapped to the model

| Folder | Layer | Contains |
|---|---|---|
| `patterns/` | Pattern | Framework-agnostic descriptions of reusable shapes |
| `implementations/<framework>/<name>/` | Implementation + Contract | The actual `workflow.json` (or equivalent), its `README.md`, and its `contract.yaml` |
| `docs/` | Cross-cutting | Reasoning and structural documents that apply above any single Pattern or Implementation — this file included |
| `WORKFLOW-CONTRACT-SPEC.md` | Cross-cutting | The formal field definitions every `contract.yaml` must follow |
| `rfcs/` | Governance | Permanent record of proposed and decided changes to the model itself |

---

## How a contribution actually moves through this

**Adding a new Implementation of an existing Pattern:**
1. Build it in `implementations/<framework>/<name>/`
2. Write its Contract (`contract.yaml` + the README's `## Contract` section)
3. Open a PR — no RFC needed, this doesn't change the model, only adds to it

**Adding a new Pattern:**
1. Open an issue describing the proposed shape
2. It needs at least one worked Implementation before the Pattern doc itself is merged — an abstract shape with nothing real underneath it doesn't get documented as proven (see `patterns/detect-judge-approve-act.md`'s own "Status: Proven" line for what this looks like once satisfied)

**Proposing a change to the model itself** (new Contract fields, a different layer structure, anything that would change this document or the spec):
1. Open an issue tagged `rfc`
2. Discussion happens there
3. Once resolved, the decision is written up as a permanent, numbered file in `rfcs/` — the issue can close, but the reasoning doesn't disappear with it

---

## Where governance sits

The `rfcs/` folder is the permanent record; the GitHub issue is where the actual back-and-forth happens. This split matters: an issue can get buried or closed, but a numbered RFC file stays in git history as a citable answer to "why is it built this way" — the same pattern `WORKFLOW-CONTRACT-SPEC.md`'s own versioning section already commits to (a proposal isn't accepted without a worked example; once accepted, it's written down permanently, not just decided in a thread).

---

## Non-Goals

- **This is not a build system or CI specification.** It describes organizational structure, not tooling.
- **This does not replace the spec's field definitions.** For what goes inside a `contract.yaml`, see `WORKFLOW-CONTRACT-SPEC.md`, not this document.
- **This is not fixed forever.** If the three-layer model turns out to be wrong once a second-framework Implementation actually gets built, this document is what changes — via the RFC process it describes, not silently.
