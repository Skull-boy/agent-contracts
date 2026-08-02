# Concept: Side Effects

**Part of:** [`WORKFLOW-CONTRACT-SPEC.md`](../../WORKFLOW-CONTRACT-SPEC.md) — the `side_effects` field
**Status:** Draft

---

## What this concept means

A side effect is anything a workflow does that changes the state of the world outside itself — a comment posted, a file written, a message sent, a record updated, a commit pushed. If an implementation can do it, and it's not purely internal computation, it's a side effect, and it belongs on this list.

This is the field the other four concepts all orbit. Permissions exist to make a side effect possible. Approval boundaries exist to gate a side effect before it happens. Recovery strategy exists to define what happens when a side effect fails partway. Replay semantics exist to define what happens if a side effect runs twice. None of those four concepts can be evaluated without first knowing, precisely, what the side effect actually is.

---

## The rule this field enforces

If it's not listed here, the workflow shouldn't do it.

This is stated as a constraint on the implementation, not just a description of it. A `side_effects` list isn't a summary written after the fact — it's the boundary the implementation is expected to stay inside. An implementation that does something not listed in its own Contract has a Contract that's wrong, and wrong in the specific direction that matters most: understating what the workflow actually does.

---

## Specific enough to be falsifiable

"Posts to GitHub" is not a side effect entry — it's a category. A real entry names the exact action and the exact condition under which it happens:

```yaml
side_effects:
  - Posts one comment on the triggering issue, if similarity >= threshold
  - Writes one vector to the Qdrant collection
```

Read this and you know: at most one comment, only conditionally, and exactly one database write, unconditionally. Nothing else. A reviewer — human or, eventually, a linter checking this against the real `workflow.json` — can verify each line against the actual implementation node by node.

---

## Bounding "at most," not just "what kind"

Precise side effects state quantity and condition, not just type. "Sends notifications" is unbounded — how many, how often, under what trigger? "Sends one digest message per scheduled run, listing only newly-flagged items" is bounded. The difference matters most for anything that could compound: a workflow that could theoretically post a hundred comments in a bad run because the list wasn't actually bounded is a very different risk than one that's structurally limited to one.

---

## Every entry earns a place in the other four fields

A side effect that requires no permission wasn't actually a side effect (it didn't touch anything external). One that needs no approval boundary is a deliberate claim that it's not risky enough to warrant one — see [`approval-boundaries.md`](./approval-boundaries.md). One with no stated recovery behavior is missing a field it needs — see [`recovery.md`](./recovery.md). And whether it's safe to trigger twice is exactly what [`replay-semantics.md`](./replay-semantics.md) exists to answer. If a listed side effect doesn't connect to at least a permission and an implicit-or-explicit approval decision, the Contract is incomplete, not just terse.

---

## Worked example

From the Semantic Duplicate Issue Detector, the full picture these other docs have referenced piecemeal:

```yaml
side_effects:
  - Posts one comment on the triggering issue, if similarity >= threshold
  - Writes one vector to the Qdrant collection

permissions:
  - github: issues:write   # comment only — never close, label, or edit
  - qdrant: read+write on one collection

approval_points: []   # justified: neither side effect is destructive or
                       # irreversible — a comment can be deleted, a vector
                       # write is idempotent and harmless to redo

replay_semantics: >
  Idempotent per issue — the Qdrant upsert uses the issue number as
  point ID, so a second run overwrites rather than duplicates.
```

Every other field in this Contract exists to answer a question this one raises. That's the test for whether a `side_effects` list is doing its job: does it generate the rest of the Contract, or did the rest of the Contract get written independently and happen to agree with it?

---

## Relationship to other concepts

This is the anchor field. [`permissions.md`](./permissions.md), [`approval-boundaries.md`](./approval-boundaries.md), [`recovery.md`](./recovery.md), and [`replay-semantics.md`](./replay-semantics.md) are each, in a real sense, a different question asked about this same list.
