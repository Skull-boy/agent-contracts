# RFC 0002: Lifecycle Field for Agent Contracts v1.1

- **Status**: Accepted
- **Author**: Scyvera Core Team / Agent Contracts Working Group
- **Created**: 2026-08-30
- **Target Spec**: Agent Contracts v1.1
- **JSON Schema**: `schemas/v1.1/contract.schema.json`

---

## 1. Problem Statement

The initial Agent Contracts specification (v1) implicitly assumed a **request-response** execution model: an agent is triggered by an external event or user prompt, executes a bounded DAG or graph of operations, produces outputs, and terminates.

However, modern autonomous systems and agentic workflows exhibit fundamentally different execution paradigms:
1. **Request-Response Agents**: Ephemeral, prompt/webhook-driven, stateless teardown upon completion.
2. **Scheduled Agents**: Chronologically triggered at fixed intervals or cron schedules (e.g. competitor watchers, periodic batch analyzers).
3. **Persistent / Autonomous Agents**: Long-running or continuously active daemons that self-initiate actions, perform background thinking/monitoring during idle periods, and persist internal state snapshots.

Without declaring the system's execution lifecycle:
- Tooling and human auditors cannot distinguish between acceptable background activity and rogue autonomous actions.
- Runtime enforcers cannot apply appropriate rate limits, initiation checks, or idle boundaries.
- Future governance fields (such as `self_modification`, `context_contract`, and `agent_to_agent` coordination) lack the foundational context of how and when the agent executes.

---

## 2. Proposed Field Definition

The `lifecycle` object is introduced in Agent Contracts v1.1.

### Schema Definition
```json
"lifecycle": {
  "type": "object",
  "required": ["mode"],
  "properties": {
    "mode": {
      "type": "string",
      "enum": ["request-response", "persistent", "scheduled"],
      "description": "Execution model of the system. Closed enum."
    },
    "idle_behavior": {
      "type": "string",
      "maxLength": 500,
      "description": "What the system may do between triggers. Required when mode is persistent."
    },
    "initiation": {
      "type": "string",
      "enum": ["human-only", "schedule", "self", "agent"],
      "description": "Who or what can trigger this system to act."
    },
    "resumability": {
      "type": "string",
      "enum": ["stateless", "context-snapshot", "replay-from-log"],
      "description": "What 'restart' means for this system."
    }
  },
  "additionalProperties": false
}
```

### Conditional Invariant
When `mode == "persistent"`, `idle_behavior` is **strictly required**:
```json
"if": {
  "properties": {
    "lifecycle": {
      "properties": {
        "mode": { "const": "persistent" }
      }
    }
  },
  "required": ["lifecycle"]
},
"then": {
  "properties": {
    "lifecycle": {
      "required": ["mode", "idle_behavior"]
    }
  }
}
```

---

## 3. Migration Path for v1 Contracts (Backward Compatibility)

Backward compatibility is guaranteed:
1. **Schema Layer**: In `schemas/v1.1/contract.schema.json`, `lifecycle` is not in the top-level `required` array. Contracts lacking `lifecycle` continue to pass structural validation.
2. **Loader / Runtime Layer**: When loading a contract without an explicit `lifecycle` declaration, the Scyvera contract loader (`apply_lifecycle_defaults`) automatically injects the canonical v1 default:
   ```yaml
   lifecycle:
     mode: request-response
     initiation: human-only
     resumability: stateless
   ```
3. **Transparency Notice**: When defaults are applied, the loader emits a `logging.warning()` so contract authors are alerted that implicit defaults are being assumed and can make their declarations explicit.

---

## 4. What This Unlocks

1. **Runtime Enforcement**: The `ContractEnforcer` can detect lifecycle downgrade attacks (T1) by validating invocation frequencies against declared lifecycle modes.
2. **Idle State Governance**: Explicit `idle_behavior` declarations prevent persistent agents from executing unmonitored background tasks (T2).
3. **Foundation for Advanced Capabilities**: Provides the architectural predicate for upcoming v1.2+ governance fields (`self_modification`, `context_contract`, `agent_to_agent`).

---

## 5. What This Does NOT Change

- **All v1 Fields**: `inputs`, `outputs`, `permissions`, `side_effects`, `approval_points`, `recovery_strategy`, `replay_semantics`, `dependencies`, `state`, and `observability` retain their full semantics and validation rules.
- **Existing v1 Contracts**: Valid v1 contracts remain valid without any file modification.
- **Scyvera v1 Public API**: `load_contract()`, `validate_contract()`, and existing CLI commands maintain complete API stability.

---

## 6. Open Questions & Resolutions

1. **Q: Should `lifecycle` be required at the JSON Schema level in v1.1?**
   - **Resolution**: No. Making it required at the schema level would invalidate existing v1.1 contracts that omit it. It is optional in schema, and defaults are applied deterministically at the loader layer with transparency warnings.
2. **Q: Should `idle_behavior` be permitted for `request-response` agents?**
   - **Resolution**: For `request-response` and `scheduled` modes, `idle_behavior` is `null` / omitted because there is no persistent process active between invocations.
3. **Q: How are initiation resets tracked for T1 mitigation?**
   - **Resolution**: In the runtime enforcer, invocation timestamps are tracked within a sliding window. User-initiated runs pass an initiation token or context flag to reset the burst window counter.
