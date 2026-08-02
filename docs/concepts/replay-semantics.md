# Concept: Replay Semantics

**Part of:** [`WORKFLOW-CONTRACT-SPEC.md`](../../WORKFLOW-CONTRACT-SPEC.md) — the `replay_semantics` field
**Status:** Draft

---

## What this concept means

Replay semantics answer one question: if this workflow runs again on the same input — because it was manually re-triggered, because a scheduler double-fired, because someone retried a failed execution — what happens? Does it produce the same result harmlessly, does it pile up duplicate side effects, or does it actively do something wrong the second time?

---

## Why this needs stating even when a workflow "shouldn't" run twice

Workflows re-run for reasons outside their own design. A webhook fires twice because the sender retried. A scheduled trigger overlaps with a manual test run. Someone clicks "Execute workflow" a second time while debugging, forgetting the first run already completed. None of these are misuse — they're the normal operating conditions of anything long-lived. A Contract that doesn't state what happens on a second run is making an unstated assumption that re-runs never happen, which is never actually true.

---

## The three states, precisely

**Idempotent.** Running twice on the same input produces the same end state as running once. Not "produces the same output" — the same *state*, including everything the workflow wrote anywhere. This is the strongest and most desirable guarantee, but it has to be engineered, not assumed.

**Append-only.** Running twice adds a second record alongside the first, rather than overwriting or erroring. Safe in the sense that nothing gets corrupted, but not free — a second run means duplicate entries somewhere, and anything downstream reading that data needs to already expect duplicates.

**Unsafe-to-repeat.** Running twice does something actively wrong — a second comment where only one was intended, a second charge, a state transition that doesn't make sense to apply twice. A workflow in this category should say so explicitly, and ideally should have a guard elsewhere in its Contract (an approval boundary, a pre-check) that prevents an accidental second run from ever reaching the unsafe step.

---

## How idempotency is actually achieved, not just claimed

Writing `replay_semantics: idempotent` in a Contract is a claim. It's only true if something concrete backs it — almost always a stable identifier used as the key for any write, so a second write with the same key overwrites rather than duplicates.

```yaml
replay_semantics: >
  Idempotent per issue — re-running on the same issue re-embeds and
  re-checks, but the Qdrant upsert uses the issue number as point ID,
  so it overwrites rather than duplicates.
```

The mechanism is named, not just the outcome. "Idempotent" alone is an assertion; "idempotent because the issue number is the point ID" is something a reviewer can actually verify by reading the implementation.

---

## Worked example: an implementation that is deliberately not idempotent

Not every workflow should claim idempotency it doesn't have. The GitHub Debugger Agent's commit step, once it pushes a fix, is not safe to blindly re-run on the same trigger — a second run against an already-fixed file could produce a redundant or conflicting commit. Its Contract should say so plainly, rather than default to claiming idempotency because that sounds like the more impressive answer:

```yaml
replay_semantics: >
  Unsafe to repeat past the commit step. Re-running after a fix has
  already been pushed may produce a conflicting or redundant commit.
  The approval boundary before push is the safeguard — a human
  reviewing the diff a second time is expected to notice and decline.
```

An honest "unsafe-to-repeat, mitigated by an approval boundary" is a stronger Contract than an unearned "idempotent."

---

## Relationship to other concepts

Replay semantics and [`recovery.md`](./recovery.md) interact directly: a retry-based recovery strategy is only safe to actually retry if the replayed step is idempotent or append-only. A `recovery_strategy` that retries an `unsafe-to-repeat` step is a contradiction inside the same Contract — the two fields should never disagree with each other.
