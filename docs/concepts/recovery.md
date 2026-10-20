# Concept: Recovery Strategy

**Part of:** [`WORKFLOW-CONTRACT-SPEC.md`](../../WORKFLOW-CONTRACT-SPEC.md) — `recovery_strategy` (v1) and `recovery` (v1.1)  
**Status:** Active

---

## What this concept means

Recovery strategy is what an implementation does the moment something it depends on fails mid-run — a dependency is unreachable, an API times out, a parse fails. Not whether the workflow *can* fail (everything can), but what happens in the exact moment it does.

---

## Why "it might fail" isn't a recovery strategy

Every workflow can fail. Saying so in a README carries no information — it's true of literally everything that calls an external service. What actually matters, and what most workflow documentation skips entirely, is the answer to one specific question: **when the failure happens, does anyone find out, and does the system do the right thing in the meantime?**

A workflow that silently swallows an error and continues as if nothing happened is not more resilient than one that crashes loudly — it's worse, because a crash gets noticed and a silent skip doesn't.

---

## Three recovery shapes, and when each is correct

**Fail loudly.** The run stops, the error is visible in the execution log, nothing downstream pretends the step succeeded. Correct when silently continuing would mean acting on missing or unverified information — the Semantic Duplicate Issue Detector does this when Qdrant is unreachable, because skipping the check silently would mean letting a real duplicate through without anyone knowing the check never ran.

**Retry, then fail loudly.** Correct for transient failures — a rate limit, a momentary timeout — where a second attempt is likely to succeed and a human doesn't need to be paged for a blip. The retry count should be bounded and stated, not open-ended.

**Fail loudly once, then degrade gracefully.** Correct when a dependency is expected to be occasionally and persistently unreachable for reasons outside the workflow's control — the Job Application Silent-Rejection Detector tracks consecutive failures per posting, and only after crossing a threshold does it stop retrying that specific target and surface a single "can't monitor this one, check manually" notice, rather than either retrying forever or silently going quiet.

What's never correct: catching an error and continuing the run as if the failed step succeeded.

---

## The test: could someone debug a real incident from this sentence alone?

In v1.1 (preferred structured format):
```yaml
recovery:
  strategy: stop
  details: >
    If Qdrant is unreachable, the run fails loudly and visibly in execution
    logs. It does not silently skip the duplicate check.
```

In v1 (legacy string format):
```yaml
recovery_strategy: >
  If Qdrant is unreachable, the run fails loudly and visibly in n8n's
  execution log. It does not silently skip the duplicate check.
```

In v1.1, `recovery.strategy` must be one of the closed enum values:
- `stop`: Halt execution immediately and fail loudly.
- `retry`: Attempt bounded retries before failing loudly.
- `rollback`: Revert partially completed state modifications.
- `human_escalation`: Halt and notify a designated operator for manual intervention.
- `fallback`: Degrade to an explicit secondary mechanism.

This passes the test — it names the specific dependency, the specific failure mode, and the specific visible outcome. A recovery strategy that just says "handles errors gracefully" fails the test; it gives a future maintainer nothing to check against when something actually breaks at 2am.

---

## Static Linter Enforcement: Rule AC401

In Scyvera, recovery strategies are statically verified against declared dependencies:
- **Rule AC401 (`Missing Recovery Strategy for Required Dependency`)**: When a contract lists required dependencies (`required: true`) but specifies no recovery strategy (`recovery: none`, `strategy: none`, or omitted), `scyvera.lint_contract()` emits a warning.
- Silent swallowing of errors is prohibited: an agent cannot depend on external services without explicitly defining its failure posture.

---

## Worked example: threshold-based degradation

From the Job Application Silent-Rejection Detector — a dependency (a job board's page) that is expected to sometimes block automated fetches entirely, for reasons unrelated to the workflow's own correctness:

```yaml
recovery:
  strategy: fallback
  details: >
    Tracks consecutive fetch failures per posting. Retries silently for
    the first two failures. On the third consecutive failure, stops
    retrying that specific posting and sends one notification marking
    it "cannot monitor — check manually," rather than retrying forever
    or failing without ever telling anyone.
```

This is the fail-loudly-once-then-degrade shape: the user finds out exactly once, not zero times and not every single run.

---

## Relationship to other concepts

Recovery strategy is what runs on the failure path of whatever [`side-effects.md`](./side-effects.md) describes on the success path, and it's the natural next stop from [`approval-boundaries.md`](./approval-boundaries.md)'s rejection path — both are about what a workflow does when the expected path doesn't happen. See also [`replay-semantics.md`](./replay-semantics.md) to ensure retry strategies are paired only with idempotent or append-only actions.
