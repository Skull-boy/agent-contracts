# Concept: Permissions

**Part of:** [`WORKFLOW-CONTRACT-SPEC.md`](../../WORKFLOW-CONTRACT-SPEC.md) — the `permissions` field  
**Status:** Active

---

## What this concept means

Permissions are the exact, scoped list of every external system an implementation is allowed to touch, and what it's allowed to do to each one. Not "this workflow uses GitHub" — which GitHub scope, on which resource, read or write.

---

## Why "uses GitHub" isn't a permission

A workflow that says it "uses GitHub" could mean anything from reading one issue's title to force-pushing to `main`. That gap — between what a workflow plausibly needs and what it's actually been granted — is where damage happens. Not because anyone intended it, but because a broad credential sitting unused is still a broad credential, and the day someone extends the workflow's logic without revisiting its access, the blast radius of a mistake is defined by the permission that was already there, not the one the new code actually needed.

A permission entry has to be specific enough that granting it and reading it back tells you exactly the same thing.

---

## The shape of a permission entry

In v1.1 (preferred structured format):
```yaml
permissions:
  - resource: github_issues
    actions: [read, write]
    scope: repository
  - resource: openai_embeddings
    actions: [read]
  - resource: qdrant_collection
    actions: [read, write]
```

In v1 (legacy format):
```yaml
permissions:
  - github: issues:write   # comment only — never close, label, or edit
  - openai: embeddings:read
  - qdrant: read+write on one collection
```

Three things every entry should make clear:

1. **The resource** — which external entity or dataset is targeted
2. **The actions** — the narrowest action verbs (e.g. `read`, `write`, `delete`, `query`) that actually satisfy the declared `side_effects`
3. **The scope** — optional operational boundary (e.g. `repository`, `session`, `tenant`)

---

## The test: permission should be derivable from side effects, not the other way around

Write `side_effects` first. Every permission listed should exist because something in that list requires it — never the reverse, where a permission is granted because it might be convenient later. If you can't point to a specific side effect that needs a given scope, that scope doesn't belong in the Contract yet, regardless of how likely it is you'll want it eventually.

**Bad:** `github: full-access` — because it was the default option and everything worked.
**Correct:** `github: issues:write` — because the only declared side effect is posting one comment.

---

## Never a bare platform default (Threat T7 Prohibition)

Never write `github: full-access`, `openai: all`, or wildcards like `*`, `all`, or `any` as a permission entry.

In Scyvera:
- **Schema Validation**: The JSON Schema rejects wildcards via regex pattern matching (`^[a-zA-Z0-9_\-]+:[a-zA-Z0-9_\-:]+$`).
- **Load-Time Check (Threat T7)**: `ContractEnforcer.load()` and `ContractEnforcer.from_declaration()` actively inspect all permission items and raise `ContractValidationError` or `DeclarationValidationError` if `*`, `all`, or `any` is supplied.
- **Semantic Linter (Rule AC101)**: `lint_contract()` raises a warning if a write permission (e.g. `actions: [write]`) is declared without any corresponding declared side effect.

---

## Runtime Enforcement: Default-Deny

At runtime in Python, `ContractEnforcer` gates every decorated call:
```python
@enforcer.gate("github_issues:write", "permission")
def post_comment(...):
    ...
```
If `github_issues:write` is not declared in the loaded contract, `ContractViolationError` is raised immediately. Scyvera denies unauthorized actions loudly by default rather than warning or silently skipping.

---

## Worked example

From the Semantic Duplicate Issue Detector (v1.1 format):

```yaml
permissions:
  - resource: github_issues
    actions: [read, write]
  - resource: openai_embeddings
    actions: [read]
  - resource: qdrant_collection
    actions: [read, write]
```

Each entry traces to a specific side effect: the GitHub permission exists because it posts a comment; the OpenAI permission exists because it embeds issue text; the Qdrant permission exists because it reads and writes vectors to exactly one collection.

---

## Relationship to other concepts

Permissions and [`side-effects.md`](./side-effects.md) are two sides of the same fact — permissions are what's *granted*, side effects are what's *done* with it. A Contract where these two lists don't obviously map to each other is a Contract that hasn't actually been checked, only written.
