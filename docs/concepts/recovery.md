# Concept: Recovery Strategy

**Part of:** [`WORKFLOW-CONTRACT-SPEC.md`](../../WORKFLOW-CONTRACT-SPEC.md) — the `recovery_strategy` field
**Status:** Draft

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

```yaml
recovery_strategy: >
  If Qdrant is unreachable, the run fails loudly and visibly in n8n's
  execution log. It does not silently skip the duplicate check.
```

This passes the test — it names the specific dependency, the specific failure mode, and the specific visible outcome. A recovery strategy that just says "handles errors gracefully" fails the test; it gives a future maintainer nothing to check against when something actually breaks at 2am.

---

## Worked example: threshold-based degradation

From the Job Application Silent-Rejection Detector — a dependency (a job board's page) that's expected to sometimes block automated fetches entirely, for reasons unrelated to the workflow's own correctness:

```yaml
recovery_strategy: >
  Tracks consecutive fetch failures per posting. Retries silently for
  the first two failures. On the third consecutive failure, stops
  retrying that specific posting and sends one notification marking
  it "cannot monitor — check manually," rather than retrying forever
  or failing without ever telling anyone.
```

This is the fail-loudly-once-then-degrade shape: the user finds out exactly once, not zero times and not every single run.

---

## Relationship to other concepts

Recovery strategy is what runs on the failure path of whatever [`side-effects.md`](./side-effects.md) describes on the success path, and it's the natural next stop from [`approval-boundaries.md`](./approval-boundaries.md)'s rejection path — both are about what a workflow does when the expected path doesn't happen.
