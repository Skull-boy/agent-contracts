# Scyvera gate (composite action)

Runs `scyvera audit` or `scyvera check` in CI and fails on findings, installing
`scyvera>=1.3,<2` from PyPI rather than running repo code.

```yaml
- uses: Skull-boy/agent-contracts/.github/actions/scyvera-gate@main
  with:
    mode: audit
    target: .
```

> Production use: pin to a full commit SHA, not `@main`; `@main` tracks the
> development branch and can change without notice.

## Inputs
| Input | Default | Meaning |
|---|---|---|
| `mode` | `audit` | `audit` (Blast Radius) or `check` (conformance tiers). |
| `target` | required | Path to scan, or a contract / implementation directory. |
| `tier` | `auto` | `check` tier: `0`, `1`, or `auto`. |
| `report-format` | `text` | `text` or `unified` (M2.5 envelope JSON). |
| `badge` | `""` | File for the Blast Radius badge; empty disables it. |
| `exit-on-finding` | `true` | `false` downgrades exit 1 to a warning. |
| `source` | `pypi` | `pypi`, or `local` for the checked-out workspace. |
| `python-version` | `3.12` | Python version; the project floor is 3.10. |

Outputs: `score` (audit only), `status` (`PASS`/`WARN`/`FAIL`), `findings`
(count), `exit-code`, and `unified-json` (compact single-line JSON).

## Examples
```yaml
# Audit with a badge
- uses: Skull-boy/agent-contracts/.github/actions/scyvera-gate@main
  with:
    mode: audit
    target: .
    badge: .github/badges/blast-radius.md
```
```yaml
# Tier 1 check on an implementation directory (source: local dogfoods the repo)
- uses: Skull-boy/agent-contracts/.github/actions/scyvera-gate@main
  with:
    mode: check
    target: implementations/langgraph/duplicate-issue-detector
    tier: "1"
    source: local
```

Exit codes: `0` clean, `1` findings (fatal only with `exit-on-finding: true`), `2` action error.
