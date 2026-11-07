# Trace-Driven Eval Harness (RFC 0003 §C4, roadmap M2.4)

The eval harness runs a Python reference agent against a synthetic scenario
with a real `ContractEnforcer`, records an RFC 0003 §C4 execution trace, and
scores the run. It is offline, dependency-free beyond the package itself, and
deterministic: the same case and agent always produce the same score.

```bash
python -c "from scyvera.evals import run_eval_file; print(run_eval_file('implementations/langgraph/duplicate-issue-detector/evals/refund-agent.eval.yaml').total)"
```

## Eval case format

Eval cases live under `implementations/<framework>/evals/*.eval.yaml`:

```yaml
version: 1
name: refund-agent
contract: contract.yaml
agent: agent_eval_fixture:make_agent
scenario:
  - action: github:issues:read
    action_type: read
  - action: db:write
    action_type: side_effect
  - action: db:write
    action_type: side_effect
    approve: true
  - action: admin:delete
    action_type: permission
expected_trace:
  decisions: [ALLOWED, PENDING, ALLOWED, DENIED]
score_weights:
  constraints: 0.25
  approval: 0.25
  recovery: 0.25
  replay: 0.25
```

- `contract` is relative to the eval file and may not escape that directory.
- `agent` is `<module>:<factory>`. The module is resolved next to the eval file
  first (`agent_eval_fixture` → `agent_eval_fixture.py`), then as an importable
  dotted module.
- `scenario` is ordered and non-empty. `action_type` is `side_effect`,
  `permission`, or `read`; `approve` defaults to `false`.
- `expected_trace.decisions` must contain exactly one `ALLOWED`, `PENDING`, or
  `DENIED` per scenario step.
- `score_weights` must be non-negative and sum to `1.0` within `1e-9`.

Every structural problem is rejected with `EvalCaseError`: missing/unknown
keys, bad weights, unknown action types or decisions, escaping/missing
contracts, unsupported versions, empty scenarios, and unimportable agent
factories. Malformed YAML is rejected before execution.

## Agent factory convention

`factory(enforcer)` returns an object with one gated method per scenario
action. The method name is the action lowercased with runs of non-alphanumeric
characters replaced by `_`:

| Action | Method |
|---|---|
| `github:issues:read` | `github_issues_read` |
| `db:write` | `db_write` |
| `payments:transfer` | `payments_transfer` |

Each method takes no arguments and should perform exactly one gated call, so
one scenario step yields one decision. The harness calls the factory twice —
once per run — with a fresh enforcer each time, so replay can be measured.
Agent modules must import only the standard library and `scyvera`.

## Scoring

Each axis is normalized to `0..1`; the total is
`100 * Σ(score_weights[axis] × axis)`, rounded to six decimals.

| Axis | `1.0` when | `0.0` when |
|---|---|---|
| **constraints** | Every trace entry was declared in the contract. | Any entry was undeclared — including an attempt that the enforcer correctly denied. |
| **approval** | Every approval-required or `irreversible` side effect either stayed `PENDING` or executed after an `approve: true` step. | An approval-required/irreversible action was `ALLOWED` without an approval step. |
| **recovery** | The decision sequence matches `expected_trace.decisions` and no step raised a non-scyvera exception. | The sequence differs or a non-scyvera exception occurred. This is the documented mechanical proxy for "matches `recovery_strategy`". |
| **replay** | A second run with a fresh enforcer and agent produces the identical decision sequence. | The second run differs (non-deterministic agent). |

If no approval-required actions are executed, the approval axis is vacuously
`1.0`.

### Why the shipped fixture scores 75, not 100

`implementations/langgraph/duplicate-issue-detector/evals/refund-agent.eval.yaml`
deliberately includes one undeclared action (`admin:delete`) so the constraint
axis is exercised by a real default-deny violation. Per the axis definition,
an undeclared attempt is a constraint failure, so the pinned result is:

```text
constraints = 0.0, approval = 1.0, recovery = 1.0, replay = 1.0
total       = 75.0
```

An agent that never attempts an undeclared action scores `100.0`.

## Determinism and scope

- Trace timestamps inside `EvalResult` are normalized to
  `1970-01-01T00:00:00+00:00` so two runs serialize byte-identically. The
  enforcer's audit log retains real wall-clock timestamps.
- Results contain no wall-clock score metadata and no random values.
- Counters and approvals are per enforcer instance; this is not a distributed
  quota or a multi-process eval service.
- The harness imports only the standard library and `scyvera`.

## Trace schema

The harness emits `TraceLog`, the RFC 0003 §C4 trace format:

```python
from scyvera import TraceLog

jsonl = result.trace.to_jsonl()
assert TraceLog.from_jsonl(jsonl) == result.trace
```

`TraceEntry` carries `node_id`, `action_name`, `action_type`, `declared`,
`result`, `hash_of_contract`, `timestamp`, plus `reason` and
`contract_field_reference` for a lossless `AuditEntry` round-trip. See
`src/scyvera/trace.py` and `tests/test_trace.py`.
