# Concept: Approval Boundaries

**Part of:** [`WORKFLOW-CONTRACT-SPEC.md`](../../WORKFLOW-CONTRACT-SPEC.md) — the `approval_points` field
**Status:** Draft

---

## What this concept means

An approval boundary is the exact point in a workflow's execution where it stops and requires an explicit human decision before proceeding to anything irreversible. Not a general sense of "a human is involved somewhere" — a specific, named point in the Detect → Judge → Approve → Act shape where the workflow will not advance without that decision.

---

## Why it's declared explicitly, not implied

"Human-in-the-loop" as a phrase is easy to say and easy to leave vague. A workflow can claim it in a README while actually auto-executing three of its five side effects without ever pausing. An approval boundary is the mechanism that makes the claim checkable: it names precisely which action requires sign-off, so "human-in-the-loop" means something specific instead of a general vibe.

---

## An empty list is a real answer, not a missing one

```yaml
approval_points: []
```

This is not an author forgetting to fill in the field. It's a deliberate claim: *this implementation performs no action serious enough to require approval.* The Semantic Duplicate Issue Detector makes exactly this claim — it only ever posts a comment suggesting a possible duplicate, never closes or labels an issue, so there is nothing in its side effects that rises to the level of needing a human gate.

An empty `approval_points` list should always be able to be justified by pointing at the `side_effects` list next to it. If the side effects include anything destructive, irreversible, or costly to undo, an empty approval list is a bug in the Contract, not a valid design choice.

---

## What qualifies as an approval boundary

A boundary is real when all three of these are true:

1. **The workflow actually stops.** Execution pauses — it doesn't proceed speculatively and roll back if rejected.
2. **A specific person or role is the approver**, not "the system decides it's probably fine."
3. **Rejection has a defined outcome.** What happens if the human says no isn't left undefined — the workflow's `recovery_strategy` or an explicit fallback should say what happens next.

A workflow that sends a Slack message saying "I'm about to do X" and proceeds regardless of reply is not an approval boundary. It's a notification.

---

## Worked example

From the Telegram → GitHub → Antigravity pipeline: the boundary sits after a coding agent proposes a fix and before that fix is pushed to a real branch. The human reviews the diff on Telegram; only an explicit approval reply resumes the workflow toward the `git push` side effect. Rejecting it, or simply not responding, means the fix never leaves the local working state.

---

## Relationship to other concepts

An approval boundary only makes sense in relation to [`side-effects.md`](./side-effects.md) — you can't evaluate whether a boundary is placed correctly without knowing exactly what the workflow would otherwise do unchecked. See also [`recovery.md`](./recovery.md) for what happens on the rejection path.
