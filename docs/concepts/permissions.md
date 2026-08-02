# Concept: Permissions

**Part of:** [`WORKFLOW-CONTRACT-SPEC.md`](../../WORKFLOW-CONTRACT-SPEC.md) — the `permissions` field
**Status:** Draft

---

## What this concept means

Permissions are the exact, scoped list of every external system an implementation is allowed to touch, and what it's allowed to do to each one. Not "this workflow uses GitHub" — which GitHub scope, on which resource, read or write.

---

## Why "uses GitHub" isn't a permission

A workflow that says it "uses GitHub" could mean anything from reading one issue's title to force-pushing to `main`. That gap — between what a workflow plausibly needs and what it's actually been granted — is where damage happens. Not because anyone intended it, but because a broad credential sitting unused is still a broad credential, and the day someone extends the workflow's logic without revisiting its access, the blast radius of a mistake is defined by the permission that was already there, not the one the new code actually needed.

A permission entry has to be specific enough that granting it and reading it back tells you exactly the same thing.

---

## The shape of a permission entry

```yaml
permissions:
  - github: issues:write   # comment only — never close, label, or edit
  - openai: embeddings:read
  - qdrant: read+write on one collection
```

Three things every entry should make clear:

1. **The system** — which external service
2. **The scope** — the narrowest access level that actually satisfies the workflow's declared `side_effects`, not the broadest one the platform happens to offer
3. **What's explicitly excluded**, when the scope name alone doesn't make it obvious — `github: issues:write` is ambiguous on its own about whether it can close an issue; the comment resolves it

---

## The test: permission should be derivable from side effects, not the other way around

Write `side_effects` first. Every permission listed should exist because something in that list requires it — never the reverse, where a permission is granted because it might be convenient later. If you can't point to a specific side effect that needs a given scope, that scope doesn't belong in the Contract yet, regardless of how likely it is you'll want it eventually.

**Bad:** `github: full-access` — because it was the default option and everything worked.
**Correct:** `github: issues:write` — because the only declared side effect is posting one comment.

---

## Never a bare platform default

Never write `github: full-access`, `openai: all`, or an equivalent catch-all as a permission entry. If a workflow genuinely needs broad access across many resource types, that's a signal to look harder at whether it's actually one workflow or several bundled together — not a reason to write a vague permission and move on.

---

## Worked example

From the Semantic Duplicate Issue Detector:

```yaml
permissions:
  - github: issues:write   # comment only — never close, label, or edit
  - openai: embeddings:read
  - qdrant: read+write on one collection
```

Each line traces to a specific side effect: the GitHub scope exists because it posts a comment (and nothing else — the parenthetical exists precisely to rule out the broader things `issues:write` could otherwise be read to allow); the OpenAI scope exists because it embeds issue text; the Qdrant scope exists because it reads and writes vectors to exactly one collection, not the whole instance.

---

## Relationship to other concepts

Permissions and [`side-effects.md`](./side-effects.md) are two sides of the same fact — permissions are what's *granted*, side effects are what's *done* with it. A Contract where these two lists don't obviously map to each other is a Contract that hasn't actually been checked, only written.
