# Orchestration vs. enforcement for Google ADK

Google ADK is an **orchestration** framework: it decides which tool the model
wants to call, in what order, and with which arguments. Scyvera is the
**authority** layer: it decides whether a declared action may execute. The two
layers meet at the tool wrapper, not in the model prompt.

```text
user request
    |
    v
ADK Runner / LlmAgent ................ orchestration (model chooses a tool)
    |
    v
tool function decorated with @enforcer.gate("support:read", "read")
    |
    +--> verify_integrity() ......... contract bytes are unchanged
    +--> declared? ................... no  -> DENIED  (ContractViolationError)
    +--> approval? ................... yes -> PENDING (ApprovalPendingError)
    +--> guardrails .................. budget/rate check
    |
    v
ALLOWED -> the tool body performs the external effect
```

## What each artifact is responsible for

| Artifact | Responsibility | What it cannot do |
|---|---|---|
| `contract.template.yaml` (copied to `contract.yaml`) | Declares authority: resources, permissions, side effects, approvals, recovery, replay, risk. | Enforce anything by itself. A declaration no gate consults changes nothing. |
| `reference/adk_agent.py` | Shows where the gate sits relative to ADK tools. | Cover a tool registered outside `@enforcer.gate`. Such a tool is invisible to Scyvera. |
| `scyvera` enforcer | Default-deny gate, identity/integrity pinning, approval boundary, audit log, draft mode. | Inspect model reasoning or stop an arbitrary ADK tool that bypasses the wrapper. |
| Google ADK | Tool selection and execution order. | Supply governance. ADK has no Scyvera authority and must not be described as having any. |

## Provisional contracts and draft mode

`provisional: true` is **not** inferred authority living in memory. It is a
contract written to disk, marked as a draft, and loaded explicitly:

```python
enforcer = ContractEnforcer.load("contract.yaml", mode="draft", registry="registry.jsonl")
```

* Full-mode load of a provisional contract raises `ProvisionalContractError`
  and names the promotion ritual.
* Draft mode allows declared actions, denies undeclared actions, keeps
  integrity/identity/guardrail checks, and still default-denies irreversible
  actions behind an approval gate even when `approvals` is empty.
* Every draft-mode audit entry and trace entry is marked `provisional`.
* Promotion is human-only: `scyvera promote` plus the re-seal ritual. There is
  no time-based, event-based, or agent-executed promotion.
* A permanent draft buys no destructive authority (RFC 0005 §7.2, threat T15).

## The sentence to keep honest

> The kit is orchestration, not enforcement. Without a provisional contract
> on disk, there is no inference-time enforcement; and without a gate around
> the tool, there is no enforcement at all.
