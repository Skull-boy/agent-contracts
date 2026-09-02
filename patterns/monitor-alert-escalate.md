# Pattern: Monitor → Alert → Escalate

**Status:** Proposed / Active
**Category:** Operational / Observability / Safety pattern

---

## Intent

The **Monitor → Alert → Escalate** pattern governs ongoing, non-single-shot workflows and agents that continuously watch external or internal state sources over time, filter routine background activity, alert when defined operational thresholds or anomalies are crossed, and escalate to human decision-makers only when severity or confidence warrants intervention.

---

## When to Use It

- **Continuous tracking:** You are watching a high-volume continuous stream, polling an API, checking uptime, tracking metrics, or monitoring external data (e.g. competitor updates, cloud spend, error rates).
- **Tiered severity handling:** Routine events or minor variations require automated self-healing, caching, or silent logging, whereas medium anomalies require team alerts and critical failures require active human escalation.
- **Asymmetric human attention:** Humans cannot review every single event in real time, but must be in the loop for high-impact or ambiguous edge cases.
- **Cost / Token budget management:** Continually summarizing or filtering signals at low cost, reserving expensive actions or alerts for verified incidents.

---

## When NOT to Use It

- **Single-shot reactive tasks:** If a workflow executes once in response to an explicit user webhook or pull request to perform a direct verification, use [`detect-judge-approve-act`](./detect-judge-approve-act.md) instead.
- **Purely passive cron pipelines:** If a scheduled task just performs an ETL batch transform with deterministic outputs and no stateful thresholding or alerting logic.
- **Fully autonomous destructive loops:** If an agent is expected to execute critical irreversible external modifications without human escalation gates.

---

## Structure

```
                     Continuous Watch
                            │
                            ▼
                     ┌─────────────┐
                     │   MONITOR   │ ◀─── (Poll / Webhook / Stream)
                     └──────┬──────┘
                            │
                   Threshold / Anomaly?
                   ┌────────┴────────┐
                   │                 │
              [No / Below]      [Yes / Match]
                   │                 │
                   ▼                 ▼
             ┌───────────┐     ┌───────────┐
             │ Log/Cache │     │   ALERT   │
             │  (Silent) │     └─────┬─────┘
             └───────────┘           │
                              Severity Level?
                              ┌──────┴──────┐
                              │             │
                         [Medium/Info]  [Critical]
                              │             │
                              ▼             ▼
                        ┌───────────┐ ┌───────────┐
                        │ Broadcast │ │ ESCALATE  │
                        │ (Channel) │ │ (Human-   │
                        └───────────┘ │  in-Loop) │
                                      └───────────┘
```

The pattern is structured across three core stages:

1. **Monitor (Ingest & Filter)** — Ingests updates from the target stream or schedule. Evaluates raw data against baseline conditions, ignoring noise and recording telemetry state silently.
2. **Alert (Format & Notify)** — When an event breaches operational thresholds or matches pattern heuristics, the agent generates structured alerts (e.g. posting digests to a dedicated notification channel, tagging teams, or updating dashboards).
3. **Escalate (Human-in-the-Loop Intervene)** — When severity surpasses automated response boundaries, ambiguity is detected, or irreversible actions are required, the agent triggers an escalation gate, waiting for human confirmation or handing over full incident control.

---

## Contract Requirements

When declaring a `contract.yaml` implementing the Monitor → Alert → Escalate pattern, the following fields are critical:

- `lifecycle.mode`: Typically `scheduled` or `persistent`, reflecting ongoing execution rather than one-off `request-response`.
- `lifecycle.idle_behavior`: Bounded description of polling intervals or background standby logic.
- `permissions`: Granular read scopes for monitored streams and bounded write scopes for alert channels (e.g., `slack:chat:write`, `github:issues:write`).
- `approval_points`: Explicit escalation triggers (actions requiring human intervention before proceeding).
- `side_effects`: Clearly partitioned between low-severity notification emits and high-severity escalation actions.
- `state`: Explicit state persistence configuration (e.g. tracking last-seen timestamp, event hashes, or baseline watermarks).
- `observability`: Set to `audit` or `verbose` to capture telemetry and threshold breach history.

---

## Known Implementations

| Framework | Implementation | Contract |
|---|---|---|
| n8n | [`competitor-feature-parity-watcher`](../implementations/n8n/competitor-feature-parity-watcher) | [contract.yaml](../implementations/n8n/competitor-feature-parity-watcher/contract.yaml) |

*(Additional implementations across LangGraph and custom daemon agents can be proposed through the RFC process.)*
