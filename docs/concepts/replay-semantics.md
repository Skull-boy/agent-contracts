# Concept: Replay Semantics

**Part of:** [`WORKFLOW-CONTRACT-SPEC.md`](../../WORKFLOW-CONTRACT-SPEC.md) — `replay_semantics` (v1) and `replay` (v1.1)  
**Status:** Active

---

## What this concept means

Replay semantics answer one question: if this workflow runs again on the same input — because it was manually re-triggered, because a scheduler double-fired, because someone retried a failed execution — what happens? Does it produce the same result harmlessly, does it pile up duplicate side effects, or does it actively do something wrong the second time?

---

## Why this needs stating even when a workflow "shouldn't" run twice

Workflows re-run for reasons outside their own design. A webhook fires twice because the sender retried. A scheduled trigger overlaps with a manual test run. Someone clicks "Execute workflow" a second time while debugging, forgetting the first run already completed. None of these are misuse — they're the normal operating conditions of anything long-lived. A Contract that doesn't state what happens on a second run is making an unstated assumption that re-runs never happen, which is never actually true.

---

## The four replay modes in v1.1

In the v1.1 specification (`contract-model-v1.1.md`), `replay.mode` is a closed enum:

- **`idempotent`**: Running twice on the same input produces the exact same end state as running once. Not "produces the same output" — the same *state*, including everything the workflow wrote anywhere. This is the strongest and most desirable guarantee, but it must be engineered, not assumed.
- **`non_idempotent`**: Running twice adds side effects (e.g. append-only logs, duplicate records, multiple counter increments) rather than overwriting. Safe in the sense that existing state is not destroyed, but downstream consumers must expect duplicates.
- **`conditional`**: Safe to re-run only if specific pre-conditions are satisfied (e.g., entity is still in a draft state, or idempotency keys have not expired).
- **`prohibited`**: Running twice executes an unsafe, destructive, or conflicting operation (e.g. a second financial transaction, duplicate git push, or invalid state transition). Blind replay is strictly prohibited.

---

## How idempotency is actually achieved, not just claimed

Writing `mode: idempotent` in a Contract is a claim. It's only true if something concrete backs it — almost always a stable identifier used as the key for any write, so a second write with the same key overwrites rather than duplicates.

In v1.1 (preferred structured format):
```yaml
replay:
  mode: idempotent
  details: >
    Idempotent per issue — re-running on the same issue re-embeds and
    re-checks, but the Qdrant upsert uses the issue number as point ID,
    so it overwrites rather than duplicates.
```

In v1 (legacy string format):
```yaml
replay_semantics: >
  Idempotent per issue — re-running on the same issue re-embeds and
  re-checks, but the Qdrant upsert uses the issue number as point ID,
  so it overwrites rather than duplicates.
```

The mechanism is named, not just the outcome. "Idempotent" alone is an assertion; "idempotent because the issue number is the point ID" is something a reviewer can actually verify by reading the implementation.

---

## Worked example: an implementation with prohibited replay

Not every workflow should claim idempotency it doesn't have. The GitHub Debugger Agent's commit step, once it pushes a fix, is not safe to blindly re-run on the same trigger — a second run against an already-fixed file could produce a redundant or conflicting commit. Its Contract states this clearly:

```yaml
replay:
  mode: prohibited
  details: >
    Prohibited past the commit step. Re-running after a fix has
    already been pushed may produce a conflicting or redundant commit.
    The approval boundary before push is the safeguard — a human
    reviewing the diff a second time is expected to notice and decline.
```

An honest "prohibited, mitigated by an approval boundary" is a stronger Contract than an unearned "idempotent."

---

## Relationship to other concepts

Replay semantics and [`recovery.md`](./recovery.md) interact directly: a retry-based recovery strategy is only safe to actually retry if the replayed step is `idempotent` or `non_idempotent`. A `recovery` strategy that automatically retries an action marked `prohibited` without human approval is a severe flaw — the two fields must never contradict each other. See [`approval-boundaries.md`](./approval-boundaries.md) for gating non-idempotent or prohibited actions.
