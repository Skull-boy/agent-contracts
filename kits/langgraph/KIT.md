# LangGraph adoption kit (M3.2)

This kit bundles the LangGraph conformance surface an adopter needs: the
reference contract shape, the Tier 1 AST check that pairs it with Python source,
the golden eval fixture, and the finding/exit-code tables. It is declarative.
It calls the installed `scyvera` engines and does not ship or fork them.

**Reference target:** [`implementations/langgraph/duplicate-issue-detector/`](../../implementations/langgraph/duplicate-issue-detector/)
— a graph that exercises its declared GitHub and Qdrant capabilities and ships a
golden eval case.

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
sh kits/langgraph/verify.sh          # POSIX
pwsh kits/langgraph/verify.ps1       # PowerShell
```

Both scripts are idempotent and preserve the engine's exit code. Expected
output for the pinned reference target:

```text
verify.sh: scyvera 1.4.0
WARN  implementations/langgraph/duplicate-issue-detector/contract.yaml (tier 1 (static): 6 tier-1 finding(s))
      [T103] unused declaration: contract declares a permission for 'github.close' but the implementation never exercises it
      ...
verify.sh: expected: WARN, 6 T103 unused declarations (exit 0)
verify.sh: langgraph kit verified (exit 0)
```

The six `T103` warnings are honest: the reference contract declares
operational verbs (`github.close`, `github.label`, `github.merge`,
`qdrant.delete`) and two free-text entries that the source never exercises.
Prune them when you copy the template, or implement them and keep the warning
at zero.

### 3. Ship the contract into your repo

1. Copy [`contract.template.yaml`](./contract.template.yaml) to `contract.yaml`
   at the root of your implementation directory.
2. Replace every field marked `# EDIT` — workflow name, permissions, side
   effects, approval points, recovery, replay, state, and observability.
3. Run the same checks the kit runs:

```bash
scyvera validate contract.yaml
scyvera lint contract.yaml
scyvera check . --tier 1
```

A `T101` or error `T102` fails the check (exit `1`); `T103` warns and keeps
exit `0`. Fix the source or the declaration — never silence the finding.

## Golden eval

The reference target ships a trace-driven eval case. The kit links it rather
than copying it, so the fixture stays single-sourced:

```bash
scyvera eval implementations/langgraph/duplicate-issue-detector/evals/refund-agent.eval.yaml
```

Expected output:

```text
WARN  refund-agent
      total: 75.0/100
      constraints: 0.0
      approval: 1.0
      recovery: 1.0
      replay: 1.0
      trace: 4 entries
```

**Pinned score: `75.0/100`.** Exit `0` means the case ran and reported `WARN`;
the pinned string is checked by `tests/test_m32_kits.py` against the real
runner output, so a silent scoring change fails the suite.

## Honest Tier 1 scope for LangGraph

The LangGraph adapter parses every `.py` file under the target with `ast`; it
never imports or executes the graph, and it never opens a socket. It catches:

- `T101` — a gateway method, direct HTTP call, or known SDK instantiation
  reaches a service the contract does not declare. Unknown gateway methods and
  unparseable source produce findings rather than being skipped.
- `T102` — a write-capable graph node is reachable from the graph entry without
  traversing a declared gate. Gateway calls count as gated; direct HTTP and SDK
  calls do not.
- `T103` — the contract declares a permission the implementation never
  exercises (warning only).

It cannot resolve dynamic dispatch, reflection, aliases, capabilities populated
from configuration at runtime, or a URL assembled from variables. It also does
not prove that a graph edge is reachable at runtime. For the audit scanner's
pattern-level limits (a different surface from Tier 1), see
[`docs/language-coverage.md`](../../docs/language-coverage.md) — absence of a
finding is not evidence of absence.

## Reference tables

[`reference/finding-codes.md`](./reference/finding-codes.md) and
[`reference/exit-codes.md`](./reference/exit-codes.md) are byte-identical to the
M3.1 skill's tables under `skills/scyvera-governance/reference/`. Do not edit
the copies; update the skill and re-copy, or `tests/test_m32_kits.py` will fail
the lockstep pin.
