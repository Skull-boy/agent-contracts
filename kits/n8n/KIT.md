# n8n adoption kit (M3.2)

This kit bundles the n8n conformance surface an adopter needs: the reference
contract shape, the Tier 1 check that pairs it with a workflow JSON, and the
finding/exit-code tables. It is declarative. It calls the installed `scyvera`
engines and does not ship or fork them.

**Reference target:** [`implementations/n8n/competitor-feature-parity-watcher/`](../../implementations/n8n/competitor-feature-parity-watcher/)
— a workflow that declares every service it reaches, so the reference check
passes at Tier 1.

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
sh kits/n8n/verify.sh          # POSIX
pwsh kits/n8n/verify.ps1       # PowerShell
```

Both scripts are idempotent and preserve the engine's exit code. Expected
output for the pinned reference target:

```text
verify.sh: scyvera 1.4.0
PASS  implementations/n8n/competitor-feature-parity-watcher/contract.yaml (tier 1 (static): 0 tier-1 findings)
verify.sh: expected: PASS, 0 tier-1 findings (exit 0)
verify.sh: n8n kit verified (exit 0)
```

### 3. Ship the contract into your repo

1. Copy [`contract.template.yaml`](./contract.template.yaml) to `contract.yaml`
   next to your `workflow.json`.
2. Replace every field marked `# EDIT` — workflow name, permissions, side
   effects, approval points, recovery, replay, state, and observability.
3. Run the same checks the kit runs:

```bash
scyvera validate contract.yaml
scyvera lint contract.yaml
scyvera check . --tier 1
```

A `T101` or error `T102` fails the check (exit `1`); `T103` warns and keeps
exit `0`. Fix the workflow or the declaration — never silence the finding.

## Honest Tier 1 scope for n8n

The n8n adapter is static inspection of `workflow.json`, not a runtime test.
It catches:

- `T101` — a node reaches a service the contract does not declare. Disabled
  nodes still count: a disabled `httpRequest` is one toggle from acting.
- `T102` — a write-capable node is reachable from a trigger without traversing a
  declared gate (`wait` with `resume: webhook`, Telegram `sendAndWait`).
- `T103` — the contract declares a permission the workflow never exercises
  (warning only).

It cannot resolve values assembled at runtime, prove that a URL expression
points at the host you think it does, emulate n8n's expression language, or
certify that the workflow behaves as described when it runs. Unknown node types
are treated as externally reaching and therefore produce a finding rather than
being skipped. For the audit scanner's pattern-level limits (a different
surface from Tier 1), see
[`docs/language-coverage.md`](../../docs/language-coverage.md) — absence of a
finding is not evidence of absence.

## Reference tables

[`reference/finding-codes.md`](./reference/finding-codes.md) and
[`reference/exit-codes.md`](./reference/exit-codes.md) are byte-identical to the
M3.1 skill's tables under `skills/scyvera-governance/reference/`. Do not edit
the copies; update the skill and re-copy, or `tests/test_m32_kits.py` will fail
the lockstep pin.
