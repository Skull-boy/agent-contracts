# Google ADK adoption kit (issue #85)

This kit bundles the Google ADK governance surface an adopter needs: a valid
v1.1 contract template for an ADK support-triage agent, an illustrative
ADK + Scyvera wiring file, the Tier 0 verification path, and the canonical
finding/exit-code tables. It is declarative. It calls the installed `scyvera`
engines and does not ship, fork, or modify them.

**Reference target:** [`reference/adk_agent.py`](./reference/adk_agent.py) — an
ADK `LlmAgent` with three Python tools (read, comment, close) where the close is
an irreversible action behind a human approval gate.

**Tier honesty:** there is no Google ADK Tier-1 adapter in this release. The
kit verifies Tier 0 structure plus the audit blast-radius scan. `scyvera check
--tier 1` on an ADK directory exits `2`; the kit never claims otherwise.

## Three-step adopter path

### 1. Install scyvera

```bash
python -m pip install scyvera
scyvera --version
```

Exit `0` and a version such as `scyvera 1.4.0` means the CLI is on `PATH`. The
kit scripts do not install anything, do not use the network, and do not need
credentials.

### 2. Run the kit check

From the repository root:

```bash
sh docs/kits/google-adk/verify.sh          # POSIX
pwsh docs/kits/google-adk/verify.ps1       # PowerShell
```

Both scripts are idempotent and preserve the engine's exit code. Expected
output for the read-only fixture:

```text
verify.sh: scyvera 1.4.0
PASS  docs/kits/google-adk/contract.template.yaml
PASS  docs/kits/google-adk/contract.template.yaml (0 semantic warnings)
PASS  docs/kits/google-adk/contract.template.yaml (tier 0 (structural): 0 schema errors, 0 semantic warnings)
PASS  docs/kits/google-adk - exploit risk none (score 100/100) [ungoverned]
verify.sh: expected: PASS tier 0, 0 schema errors, 0 semantic warnings, audit 100/100 (exit 0)
verify.sh: tier 1 is not claimed: no Google ADK adapter exists yet
verify.sh: google-adk kit verified (exit 0)
```

`[ungoverned]` is the honest status of a template that has not been copied to
`contract.yaml` yet. After step 3, `scyvera audit .` reports the adopter target
as `[governed]` (or `[provisional]` for a draft).

The audit renderer may print an em dash where this page shows a hyphen; the
band and score are the machine-relevant parts.

### 3. Ship the contract into your repo

1. Copy [`contract.template.yaml`](./contract.template.yaml) to `contract.yaml`
   beside your ADK agent. Keep the canonical name; `.yml` is rejected.
2. Replace every field marked `# EDIT` — agent name, domain, resources,
   permissions, side effects, approvals, dependencies, state, recovery, replay,
   observability, and risk.
3. Wire the gate as [`reference/adk_agent.py`](./reference/adk_agent.py) shows:
   load the contract once, gate every externally reaching tool, and refuse to
   build the agent if any tool is ungated.
4. Run the same checks the kit runs:

```bash
scyvera validate contract.yaml
scyvera lint contract.yaml
scyvera check contract.yaml --tier 0
```

A schema or lint error exits `1`; fix the contract or the code, never silence
the finding. An unknown tier or missing adapter exits `2`; that is a signal,
not a pass.

## How an ADK agent loads and references a Scyvera contract

The contract lives on disk beside the agent. It is loaded once at process
start, before the ADK agent is constructed:

```python
from scyvera.enforcer import ContractEnforcer

enforcer = ContractEnforcer.load("contract.yaml", registry="registry.jsonl")
```

That call validates the YAML, pins the canonical path, hashes the contract, and
builds the default-deny gate. It does **not** run the agent and it does **not**
infer authority from the model.

Each tool is wrapped at definition time:

```python
@enforcer.gate("support:read", "read")
def read_issue(issue_number: int) -> dict:
    ...

@enforcer.gate("support:close", "side_effect")
def close_issue(issue_number: int) -> None:
    ...
```

The action name must match the contract: `support:read` matches
`permissions[].resource: support` + `actions: [read]`; `support:close` matches
the `side_effects` declaration and its `approvals` entry. An action the contract
does not declare is denied; a declared irreversible action without an approval
is `PENDING`.

Before constructing `LlmAgent`, assert the invariant:

```python
for tool in tools:
    ContractEnforcer.assert_gated(tool)
```

An ADK tool registered outside the gate is invisible to Scyvera. The assertion
turns that into a startup failure instead of a silent governance hole.

## What `provisional` / draft means for an ADK agent

A provisional contract is a contract **file on disk** with
`provisional: true` (v1.1/v1.2 only; v1 rejects the key even as `false`). It is
not an in-memory hint and it is not automatic authority.

- Full mode (`ContractEnforcer.load("contract.yaml")`) refuses it with
  `ProvisionalContractError` and names the promotion ritual.
- Draft mode (`ContractEnforcer.load("contract.yaml", mode="draft")`) accepts
  only a provisional contract. Declared reversible actions run; undeclared
  actions are denied; irreversible actions still default-deny behind an
  approval gate even when `approvals` is empty; guardrails, identity pinning,
  integrity checks, and symlink refusal stay active.
- Every draft-mode audit entry and trace entry carries `provisional: true`, so
  an operator can never mistake a draft for a promoted contract.
- Promotion is human-only: `scyvera promote` plus the re-seal ritual, with a
  reviewer, an intent, and diff-hash confirmation. No time-based, event-based,
  or agent-executed promotion.
- Keeping an ADK agent in draft forever is threat T15: it buys no destructive
  authority and it stays visibly provisional.

The full boundary is in [`reference/boundary.md`](./reference/boundary.md).

## Honest Tier 0 scope for Google ADK

Tier 0 is structural: JSON Schema validation plus the ACxxx semantic lint. It
checks that the contract is well-formed and internally consistent. It does not
inspect the ADK source tree and cannot compare declared capabilities with tool
bodies, because no ADK Tier-1 adapter exists.

Consequences:

- No `T101` (undeclared action), `T102` (ungated write), or `T103` (unused
  declaration) findings are produced for ADK.
- A clean Tier 0 result is not a claim that every ADK tool is gated, that a
  model cannot be prompt-injected, or that the contract matches reality.
- The audit scanner is pattern-level and review-grade; a missing finding is not
  evidence of absence. See
  [`docs/language-coverage.md`](../../language-coverage.md).

What the kit does prove, honestly: the contract fixture is schema-valid, lints
with zero warnings, passes the Tier 0 check, and adds no blast-radius findings.

## Reference tables

[`reference/finding-codes.md`](./reference/finding-codes.md) and
[`reference/exit-codes.md`](./reference/exit-codes.md) are byte-identical to the
M3.1 skill's tables under `skills/scyvera-governance/reference/`. Do not edit
the copies; update the skill and re-copy, or the two vocabularies will drift.

## Why this kit is under `docs/kits/`

The shipped kits at `kits/n8n/` and `kits/langgraph/` are pinned by
`tests/test_m32_kits.py`: the test asserts the exact top-level contents of
`kits/` and the exact file set of each kit. Registering a new `kits/<target>/`
therefore requires editing that test. Issue #85 is scoped to `kits/` and `docs/`
with no test changes, so this reference kit lives at `docs/kits/google-adk/`
and is linked from [`kits/README.md`](../../../kits/README.md). The authoring
guide records how to promote it once a pin update is allowed.
