# Finding codes

Compact reference for every rule ID the engines can emit. Severity values are
the engine's own: **critical**, **high**, **medium**, **low** for audit;
**error** / **warning** for conformance. Never re-rank them.

`tests/test_m31_skill.py` pins this table against `RULES` in
`src/scyvera/audit_rules.py` and the AC/T1 taxonomy, so an added rule fails the
suite until this reference is updated.

## Audit rules (`scyvera audit`)

| Rule | Severity | Meaning |
|---|---|---|
| `AU-ENV-001` | medium | A dotenv secrets file is present in the scanned tree. |
| `AU-ENV-002` | critical | A secret-looking value is committed inside an env file. |
| `AU-SH-001` | critical | A shell script performs a recursive-force delete. |
| `AU-GIT-001` | high | A destructive git operation (for example force-push or hard reset) appears in a script or workflow. |
| `AU-NET-001` | critical | A remote install script is piped into a shell. |
| `AU-NET-002` | medium | Source code makes outbound network calls through a known client or SDK. |
| `AU-CI-001` | high | A CI workflow grants write-all or exposes secrets inside a `run` block. |
| `AU-CI-002` | high | A CI job deploys or publishes an artifact. |
| `AU-DOC-001` | high | A container runs privileged or mounts a risky host path. |
| `AU-N8N-001` | medium | An n8n workflow writes to an external system. |
| `AU-DEP-001` | low | A dependency manifest leaves versions unpinned. |
| `AU-SECRET-001` | high | Source contains a hardcoded credential-like literal; the value is redacted. |

## Conformance rules (`scyvera validate` / `scyvera lint` / `scyvera check`)

| Rule | Severity | Meaning |
|---|---|---|
| `AC000` | error | Structural validation failed; semantic linting did not run. |
| `AC101` | warning | A write permission is granted but no side effect is declared. |
| `AC103` | warning | A capability name duplicates an operational permission verb. |
| `AC201` | warning | Risk level is high or critical but no approval boundary exists. |
| `AC301` | warning | `idle_behavior` uses an unbounded term such as "anything". |
| `AC302` | warning | An irreversible side effect has no approval boundary. |
| `AC401` | warning | A required dependency has no recovery strategy. |
| `AC601` | warning | Side effects are declared but observability is `none`. |
| `AC701` | warning | A pre-v1.2 contract carries a `guardrails` block that its version ignores. |
| `T101` | error | Tier 1 found an external action the contract does not declare. |
| `T102` | error | Tier 1 found an externally-reaching write reachable without a declared gate. |
| `T103` | warning | Tier 1 found a declared permission the implementation never exercises. |

`AUDIT` findings carry a path and usually a line. `T101`/`T102`/`T103` carry
the implementing file; `ACxxx` findings carry the contract. Report the rule ID,
severity, and location exactly as printed.
