# Threat Model: Agent Lifecycle Governance (v1.1)

This document formalizes the security and governance threat model for the `lifecycle` field introduced in Agent Contracts v1.1.

---

## Threat T1: Lifecycle Downgrade Attack

### Description
An agent author or malicious agent implementation declares `mode: request-response`, claiming a narrow, stateless, human-triggered operational profile, but executes continuously in a persistent loop or is invoked repeatedly by automated triggers. The contract presents a false sense of minimal governance exposure to human reviewers or downstream security tooling.

### Impact
- Side effects that should only occur with explicit human initiation are executed in high volume.
- Rate limits, budget ceilings, and audit review cycles designed for intermittent invocation are overwhelmed.
- Downstream systems assume stateless teardown between runs while in-memory state or persistence leaks across executions.

### Mitigation Strategy

#### Available Now
- **Schema & Invariant Enforcement**: The loader and validator require explicit lifecycle declarations for v1.1 contracts and enforce strict mode constraints (e.g. `idle_behavior` required for persistent mode).
- **Default-Deny Gating**: Actions outside the declared permissions and side effects are blocked regardless of invocation rate.

#### Roadmap (Planned, not yet implemented)
- **Invocation Frequency Tracking (Runtime Enforcer)**: Planned enhancement for `ContractEnforcer` to track invocation frequency using a sliding time window (e.g. 60 seconds). If an agent declaring `mode: request-response` and `initiation: human-only` is invoked repeatedly (e.g. >20 times) within the window without external reset, the enforcer will emit a high-severity `LIFECYCLE_DOWNGRADE_WARNING` log entry.
- **Cadence Audit Logging**: Future integration to record invocation cadence metrics directly in `AuditEntry`.

---

## Threat T2: Idle Behavior Claim Inflation

### Description
An agent with `mode: persistent` provides a vague, unbounded `idle_behavior` description such as `"thinks about things"`, `"does any task"`, `"assists users with whatever is needed"`, or `"monitors all data"`. By using vague phrasing, the agent author effectively claims carte-blanche authority to execute arbitrary background compute, poll arbitrary endpoints, or consume background tokens without explicit boundary declarations.

### Impact
- Background resource drain and uncontrolled API consumption.
- Covert exfiltration or side effects executed under the guise of ambiguous "idle processing".
- Contract review failure: human auditors cannot determine if observed background behavior is permitted or anomalous.

### Mitigation Strategy
1. **Schema Constraints**: The JSON Schema enforces that `idle_behavior` is a bounded string with a maximum length of 500 characters (`maxLength: 500`).
2. **Conditional Requirement**: Schema `if/then` rules mandate `idle_behavior` whenever `mode: persistent`. It is not allowed to be omitted or empty.
3. **Semantic Linter (Rule AC301)**: Scyvera's semantic linter (`lint_contract`) actively inspects `idle_behavior` for vague wildcard keywords: `"anything"`, `"whatever"`, `"all"`, `"unlimited"`, `"any task"`. Any occurrence triggers a lint warning `[AC301] Vague Idle Behavior`.
4. **Specification Standard**: The specification dictates that `idle_behavior` must be concrete, specific, and audit-verifiable (e.g. `"monitors GitHub notifications for repository mentions"`).

---

## Threat T3: Mode Enum Expansion Attack

### Description
A fork, third-party contributor, or extension proposes ambiguous intermediate lifecycle modes (such as `"semi-persistent"`, `"hybrid"`, `"background"`, or `"event-driven-autonomous"`) that blur the distinct governance obligations separating bounded request-response executions from unprompted continuous agents.

### Impact
- Enforcer ambiguity: tooling cannot determine whether `idle_behavior` must be enforced or whether human initiation is required.
- Inconsistent security boundaries across different framework implementations.
- Downgrade of governance rigor into weakly-typed execution categories.

### Mitigation Strategy
1. **Closed Enum in JSON Schema**: The `mode` property in `schemas/v1.1/contract.schema.json` is strictly closed:
   ```json
   "enum": ["request-response", "persistent", "scheduled"]
   ```
2. **No Fallback Modes**: Sub-field schemas set `"additionalProperties": false` on the `lifecycle` object to prevent arbitrary modifier pollution.
3. **Formal RFC Process**: Any addition to the lifecycle mode taxonomy requires a formal Specification RFC with reference implementations and threat models before schema adoption.
