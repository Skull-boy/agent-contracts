# Exit codes

The house convention is `0` / `1` / `2`, and every command keeps it. Warnings
may print on exit `0`; they are not failures. JSON output (`--json`,
`--unified`) never changes the exit code.

| Command | 0 | 1 | 2 |
|---|---|---|---|
| `validate` | Contract is valid. | Schema validation failed. | File not found, permission denied, or unreadable schema. |
| `lint` | Zero semantic warnings, or warnings only. | Structural validation failed before linting. | File not found or permission denied. |
| `check` | Pass, or warn-only (`T103` / soft warnings). | Fail: `T101` or error-severity `T102`, or schema failure. | Usage/IO error, explicit tier 2 refusal, or no Tier 1 adapter claims the target. |
| `self-check` | Installed files match the packaged manifest. | A verifiable manifest disagrees: modified, missing, unlisted, or version mismatch. | Unverifiable: missing, malformed, or unsupported manifest, or an IO problem. |
| `audit` | Clean, or `--fail-under` threshold met. | Scored findings, or the score is below `--fail-under`. | Usage or IO error (`--json` with `--unified`, bad threshold, missing path). |
| `eval` | Case passes, or reports `WARN`. | Case fails (`expected_ok` is false). | Malformed case, missing contract, or bad agent factory. |
| `init` | Contract written. | Target exists without `--force`, or the prompt was cancelled. | Not used. |
| `serve-mcp` | Clean shutdown after host EOF. | Not used. | Startup failure (stdin already closed). |

`serve-mcp` is the MCP transport, not a governance verdict. A failed MCP tool
call is a JSON-RPC `error` frame; its `message` is the command's own text.
