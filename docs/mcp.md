# MCP server mode (PD-7)

The Model Context Protocol (MCP) is a JSON-RPC 2.0 interface that lets an agent
host discover and call tools exposed by an out-of-process server over stdio.
`scyvera serve-mcp` is that server for Scyvera: it surfaces the same engines the
CLI dispatches to, so an MCP-native host can audit a workspace, validate a
contract, run a conformance tier, verify an install, and read package metadata
without shelling out.

## Install and run

```bash
pip install scyvera
scyvera serve-mcp
```

The process reads newline-delimited JSON-RPC 2.0 from stdin and writes one JSON
object per line to stdout. Nothing is printed at startup; diagnostics go to
stderr. Exit codes: `0` clean shutdown, `2` startup failure (stdin was already
closed when the server started).

## Claude Desktop

Add the server to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "scyvera": {
      "command": "scyvera",
      "args": ["serve-mcp"]
    }
  }
}
```

## Generic MCP clients

Any client that spawns a stdio server works the same way: start
`scyvera serve-mcp`, send `initialize`, then `notifications/initialized`, then
`tools/list` / `tools/call`.

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"scyvera_audit","arguments":{"path":"."}}}
```

Batching is rejected with JSON-RPC `-32600`: MCP uses one request per line.

## Tools

| Tool | Inputs | Result shape |
|---|---|---|
| `scyvera_audit` | `path` | `report_version: 1` Blast Radius payload plus `unified` (the M2.5 envelope) from the same scan. |
| `scyvera_validate` | `contract_path` | Tier 0 `CheckReport`: `valid`, `validation_errors`, `warnings`, `tier1_findings`. |
| `scyvera_check` | `target`, `tier?` | `CheckReport` for tiers `0`, `1`, or `auto`; tier 2 returns the CLI's loud refusal. |
| `scyvera_self_check` | — | `self_check_version: 1` payload plus `status` (`ok`/`report`/`error`) and `exit_code` (`0`/`1`/`2`). |
| `scyvera_packages` | — | Static metadata: version, specification versions, protocol version, capabilities. |

Every result is JSON text inside a standard MCP `content` block; rendering is
the host's job.

## Scope

PD-7 exposes inspection and conformance tools over MCP; it does not expose a
governed-runtime host. Enforcement stays in-process via the
`ContractEnforcer` in the agent's own runtime.

## Safety notes

- Tool inputs are paths only. The server opens them; it never runs a shell, a
  child process, or code supplied in an argument.
- Scans are read-only and reuse the audit engine's 1 MiB per-file cap and
  symlink refusal.
- `scyvera_check --tier 1` loads the same static adapter the CLI loads for a
  claimed target. Those adapters parse source (`json` for n8n, `ast` for
  LangGraph); they do not import the target package.
