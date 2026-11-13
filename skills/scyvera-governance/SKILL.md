---
name: scyvera-governance
description: Run Scyvera's deterministic governance tools on a repository or contract. Use when asked to audit a codebase, validate or lint a contract, check conformance, prove an install is intact, score an eval case, or scaffold a contract. Teaches tool use and exit-code reading; never substitutes agent judgment for an engine verdict.
---

# Scyvera governance

Scyvera is a deterministic governance CLI. This skill teaches you when to run
it, which command to run, and how to read what comes back. It does not give you
governance authority.

## Design principle: knowledge, not powers

A skill must never give an agent governance POWERS, only governance
KNOWLEDGE. You run Scyvera's tools; you do not become the judge. The engines
decide PASS/FAIL from schemas, rules, and adapters. Your job is to invoke the
right command, preserve its output, and report its exit code. Do not execute
scanned code, do not edit a finding to change its meaning, and do not overrule
an engine verdict with your own opinion.

## When to invoke

- Asked to audit, scan, or assess blast radius: run `scyvera audit`.
- Asked whether a contract is valid or semantically sane: run `scyvera validate`, then `scyvera lint`.
- Asked whether an implementation conforms, or to check before a consequential action: run `scyvera check`.
- Asked to prove an installed Scyvera is intact: run `scyvera self-check`.
- Asked to score a trace-driven case: run `scyvera eval`.
- Asked for a starting contract: run `scyvera init`, then validate.

## The three NEVERs

- **NEVER fabricate findings.** Report only what the command printed. If it failed, report the failure.
- **NEVER lower a finding's severity.** Copy the engine's severity and rule ID unchanged. Do not re-rank, suppress, or explain away a finding.
- **NEVER declare PASS without running the command.** "It looks fine" is not a verdict. A PASS claim requires a real run and exit code 0.

## Command map

Exit codes are the contract: `0` success/pass (warnings may still print), `1` a
finding or verdict failure, `2` usage, IO, or unverifiable input. Never treat
stderr as a pass.

### `scyvera init [output]` — scaffold
Writes the starter contract (default `contract.yaml`). Exit `0` created, `1` target exists or cancelled.
```
$ scyvera init contract.yaml --name "Demo Agent"
CREATED contract.yaml (spec version 1.1)                       # exit 0
```

### `scyvera validate <contract>` — schema only
Exit `0` valid, `1` invalid, `2` IO error.
```
$ scyvera validate tests/fixtures/v1.1/valid-minimal.yaml
PASS  tests/fixtures/v1.1/valid-minimal.yaml                   # exit 0
```

### `scyvera lint <contract>` — Tier 2 semantics
Runs the ACxxx semantic rules. Warnings still exit `0`; structural failure exits `1`; IO exits `2`.
```
$ scyvera lint tests/fixtures/v1.1/valid-minimal.yaml
PASS  tests/fixtures/v1.1/valid-minimal.yaml (0 semantic warnings)  # exit 0
```

### `scyvera check <target> [--tier 0|1|auto]` — conformance
Tier 0 is schema + lint; Tier 1 runs the static adapter. Exit `0` pass/warn, `1` fail (`T101` or error `T102`), `2` usage/IO or an explicit tier 2 refusal.
```
$ scyvera check tests/fixtures/v1.1/valid-minimal.yaml --tier 0
PASS  tests/fixtures/v1.1/valid-minimal.yaml (tier 0 (structural): 0 schema errors, 0 semantic warnings)  # exit 0
```

### `scyvera self-check [--json]` — install integrity
Verifies installed files against the packaged manifest. Exit `0` clean, `1` deviation, `2` unverifiable.
```
$ scyvera self-check
PASS  self-check  scyvera 1.4.0
      manifest: 1
      verified: 36 files                                       # exit 0
```

### `scyvera audit [path] [--fail-under N]` — blast radius
Read-only scan. Exit `0` clean or threshold met, `1` scored findings or threshold breach, `2` usage/IO.
```
$ scyvera audit . --fail-under 92
WARN  .
      Blast Radius: 92/100 (Shielded)                          # exit 0
```

### `scyvera eval <case.eval.yaml> [--json]` — four-axis score
Runs the reference agent and scores constraints, approval, recovery, replay. Exit `0` pass/warn, `1` fail, `2` usage/IO.
```
$ scyvera eval implementations/langgraph/duplicate-issue-detector/evals/refund-agent.eval.yaml
WARN  refund-agent
      total: 75.0/100                                          # exit 0
```

## MCP path (prefer when the host is MCP-native)

Run `scyvera serve-mcp` as a stdio JSON-RPC 2.0 server and prefer its five
tools over shelling out: `scyvera_audit` (`path`), `scyvera_validate`
(`contract_path`), `scyvera_check` (`target`, `tier?`), `scyvera_self_check`,
and `scyvera_packages`. Results are the same payloads and verdicts as the CLI.
A tool error is a JSON-RPC error, never a silent pass. See `docs/mcp.md`.

## Working rules

1. **init → contract.** Start from `scyvera init`, then `validate`, then `lint`. Do not hand-write a contract to make a check pass.
2. **Check before consequential actions.** Before a write, deploy, publish, or destructive command, run `scyvera check` and `scyvera audit --fail-under`. Report the exact exit code.
3. **Re-seal ritual.** If a contract changes, re-run validate → lint → check, then use the engine's registry re-seal path. Never hand-edit `registry.jsonl` and never re-register to hide a deviation.
4. **Keep the command's own text.** Quote findings and exit codes; do not paraphrase them into a stronger or weaker claim.

Reference: `reference/exit-codes.md`, `reference/finding-codes.md`,
`scripts/audit.sh`, `scripts/audit.ps1`.
