# Pattern: Detect → Judge → Approve → Act

**Status:** Proven — two full implementations exist (n8n + LangGraph)
**Category:** Reasoning / Safety pattern

---

## The shape

```
  Input arrives
       │
       ▼
  ┌─────────┐     ┌─────────┐     ┌──────────┐     ┌────────┐
  │ DETECT  │────▶│  JUDGE  │────▶│ APPROVE  │────▶│  ACT   │
  └─────────┘     └─────────┘     └──────────┘     └────────┘
  Something         Score/         Human gate       Take the
  worth              classify      (may be a        one
  looking at         relevance     no-op if the      declared
                      or risk      Contract says     side effect
                                   none is needed)
```

Four stages, in order, each with a distinct job:

1. **Detect** — notice something happened worth evaluating. A new GitHub issue, a competitor's changelog update, a job posting that changed status.
2. **Judge** — assess it against a standard. Is this a duplicate? Is this relevant to us? Is this actually closed?
3. **Approve** — the point where a human either explicitly signs off, or the Contract has already declared that no approval is needed for this specific action (see `approval_points` in [`WORKFLOW-CONTRACT-SPEC.md`](../WORKFLOW-CONTRACT-SPEC.md) — an empty approval list is a real, intentional claim, not a skipped step).
4. **Act** — the one declared, bounded side effect. Comment. Alert. Flag. Never more than what the Contract says it does.

---

## Why this pattern recurs

Every workflow in this repository that isn't a pure notification bot follows this shape, because it's the minimum structure needed to let an AI system exercise judgment *without* silently taking irreversible action on that judgment. Skip Judge, and you're just forwarding raw noise. Skip Approve, and a bad Detect+Judge call becomes a bad Act with no human ever in the loop.

---

## Known Implementations

| Framework | Implementation | Contract |
|---|---|---|
| n8n | [`duplicate-issue-detector`](../implementations/n8n/duplicate-issue-detector) | [contract.yaml](../implementations/n8n/duplicate-issue-detector/contract.yaml) |
| LangGraph | [`duplicate-issue-detector`](../implementations/langgraph/duplicate-issue-detector) | [contract.yaml](../implementations/langgraph/duplicate-issue-detector/contract.yaml) |

**The second-framework implementation now exists.** The LangGraph implementation was built from the same pattern and contract shape as the n8n version — same four stages, same declared permissions, same `approval_points: []` claim, same idempotency mechanism. See [`docs/workflow-engineering.md`](../docs/workflow-engineering.md#why-do-patterns-outlive-frameworks) for the hypothesis this implements.

**Other workflows in this repository may also instantiate this pattern** — several look like plausible fits on inspection — but per this project's own governance process, a pattern classification isn't asserted here without a worked-through Contract confirming it. If you believe a workflow belongs in this table, open the discussion under [`rfcs/`](../rfcs) with the Contract that supports it, rather than a one-line addition to this table.

---

## What varies by implementation, and what must not

**Allowed to vary:** the specific Detect trigger (webhook vs. schedule vs. manual), the specific Judge mechanism (embeddings vs. keyword rules vs. an LLM call), the specific Act (a comment vs. a Slack message vs. a database write).

**Must not vary:** the presence of a declared Contract, and the principle that Act only ever executes the specific, bounded side effects that Contract lists — regardless of framework.
