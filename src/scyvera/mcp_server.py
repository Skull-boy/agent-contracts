"""Minimal Model Context Protocol server for scyvera (roadmap PD-7).

The transport is newline-delimited JSON-RPC 2.0 over stdio. This module is
deliberately small and stdlib-only: it never starts a child process, never
loads a plugin from the wire, and never treats a tool argument as code. Every
tool result is produced by the same engine functions the CLI dispatches to, so
MCP output and CLI output cannot drift.

stdout carries protocol frames only; a host parses one JSON object per line.
:func:`serve` never prints: diagnostics belong on stderr, and none are emitted
today because every failure is a JSON-RPC error frame.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, TextIO

import yaml

from . import __version__
from .audit import (
    MAX_FILE_BYTES,
    AuditError,
    SymlinkTargetError,
    scan_tree,
    unify_audit_report,
)
from .conformance import (
    CheckTier,
    Tier1ContractError,
    Tier1UnavailableError,
    TierNotImplementedError,
    check_contract,
    resolve_tier,
)
from .exceptions import ContractFileNameError
from .selfcheck import SelfCheckError, self_check

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "scyvera-mcp"

HELP_LINE = (
    "scyvera serve-mcp          Run scyvera as an out-of-process MCP server "
    "over stdio."
)

# JSON-RPC 2.0 error codes (https://www.jsonrpc.org/specification#error_object).
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

_CAPABILITIES: dict[str, Any] = {"tools": {"listChanged": False}}
_SPEC_VERSIONS = ("1", "1.1", "1.2")


class _InvalidParams(Exception):
    """A request argument is missing, unexpected, or of the wrong type."""


class _ToolError(Exception):
    """A tool ran and failed; reported as a JSON-RPC error, never a result."""


@dataclass(frozen=True)
class McpTool:
    """One MCP tool: a wire name, a schema, and an engine-backed handler."""

    name: str
    description: str
    input_schema: Mapping[str, Any]
    handler: Callable[[Mapping[str, Any]], dict[str, Any]]

    def describe(self) -> dict[str, Any]:
        """Return the ``tools/list`` entry for this tool."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": dict(self.input_schema),
        }


# ---------------------------------------------------------------------------
# Input discipline
# ---------------------------------------------------------------------------


def _path_argument(raw: Any, field: str) -> Path:
    """Turn a wire argument into a path without following a symlink root.

    Only the final component is inspected, exactly like the audit engine's
    target check: refusing a symlink *chain* would also refuse legitimate
    platform paths such as macOS's ``/var`` -> ``/private/var``.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise _InvalidParams(f"'{field}' must be a non-empty path string")
    path = Path(raw)
    if os.path.islink(path):
        raise _ToolError(f"{field} is a symlink and is refused: {raw}")
    return path


def _refuse_oversized(path: Path, tool_name: str) -> None:
    """Reuse the audit engine's 1 MiB read cap for contract files."""
    try:
        if path.is_file() and path.stat().st_size > MAX_FILE_BYTES:
            raise _ToolError(
                f"{tool_name}: {path} exceeds the {MAX_FILE_BYTES}-byte read cap"
            )
    except OSError as error:
        raise _ToolError(f"{tool_name}: cannot stat {path}: {error}") from None


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _audit_handler(arguments: Mapping[str, Any]) -> dict[str, Any]:
    path = _path_argument(arguments["path"], "path")
    _refuse_oversized(path, "scyvera_audit")
    try:
        report = scan_tree(path)
    except SymlinkTargetError:
        raise _ToolError(f"scyvera_audit: refusing symlink target: {path}") from None
    except FileNotFoundError:
        raise _ToolError(f"scyvera_audit: path not found: {path}") from None
    except PermissionError:
        raise _ToolError(f"scyvera_audit: permission denied: {path}") from None
    except AuditError as error:
        raise _ToolError(f"scyvera_audit: {error}") from None

    payload = report.to_dict()
    # Same run, no re-scan: the envelope is projected from the payload above.
    payload["unified"] = unify_audit_report(payload).to_dict()
    return payload


def _validate_handler(arguments: Mapping[str, Any]) -> dict[str, Any]:
    contract = _path_argument(arguments["contract_path"], "contract_path")
    _refuse_oversized(contract, "scyvera_validate")
    try:
        report = check_contract(contract, tier="0")
    except ContractFileNameError as error:
        raise _ToolError(f"scyvera_validate: {error}") from None
    except FileNotFoundError:
        raise _ToolError(f"scyvera_validate: file not found: {contract}") from None
    except PermissionError:
        raise _ToolError(f"scyvera_validate: permission denied: {contract}") from None
    except yaml.YAMLError as error:
        raise _ToolError(f"scyvera_validate: invalid YAML: {error}") from None
    return report.to_dict()


def _check_handler(arguments: Mapping[str, Any]) -> dict[str, Any]:
    target = _path_argument(arguments["target"], "target")
    tier = arguments.get("tier", "auto")
    if not isinstance(tier, str):
        raise _InvalidParams("'tier' must be a string")
    contract = target / "contract.yaml" if target.is_dir() else target
    _refuse_oversized(contract, "scyvera_check")

    try:
        resolved, _ = resolve_tier(tier)
    except TierNotImplementedError as error:
        # Deliberately the CLI's one-line message: same refusal, other transport.
        raise _ToolError(f"scyvera check: error: {error}") from None
    except ValueError as error:
        raise _InvalidParams(str(error)) from None

    adapter = None
    if resolved is CheckTier.STATIC:
        from .cli import _discover_tier1_adapter

        adapter = _discover_tier1_adapter(target)
        if adapter is None:
            raise _ToolError(
                f"scyvera check: error: no tier 1 adapter for {target} "
                "(expected workflow.json + contract.yaml with a supported "
                "adapter)"
            )

    try:
        report = check_contract(contract, tier=tier, target=target, adapter=adapter)
    except TierNotImplementedError as error:
        raise _ToolError(f"scyvera check: error: {error}") from None
    except Tier1UnavailableError as error:
        raise _ToolError(f"scyvera check: error: {error}") from None
    except Tier1ContractError as error:
        raise _ToolError(f"scyvera check: cannot run tier 1: {error}") from None
    except ContractFileNameError as error:
        raise _ToolError(f"scyvera check: error: {error}") from None
    except FileNotFoundError:
        raise _ToolError(f"scyvera check: file not found: {contract}") from None
    except PermissionError:
        raise _ToolError(f"scyvera check: permission denied: {contract}") from None
    except yaml.YAMLError as error:
        raise _ToolError(f"scyvera check: invalid YAML: {error}") from None
    return report.to_dict()


def _self_check_handler(arguments: Mapping[str, Any]) -> dict[str, Any]:
    try:
        result = self_check()
    except SelfCheckError as error:
        raise _ToolError(f"scyvera_self_check: {error}") from None

    from .cli import _self_check_exit_code

    exit_code = _self_check_exit_code(result)
    payload = result.to_dict()
    payload["status"] = {0: "ok", 1: "report", 2: "error"}[exit_code]
    payload["exit_code"] = exit_code
    return payload


def _packages_handler(arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": "scyvera",
        "version": __version__,
        "protocol_version": PROTOCOL_VERSION,
        "spec_versions": list(_SPEC_VERSIONS),
        "capabilities": ["audit", "check", "packages", "self-check", "validate"],
        "tools": [tool.name for tool in TOOLS],
    }


TOOLS: tuple[McpTool, ...] = (
    McpTool(
        name="scyvera_audit",
        description=(
            "Scan a path read-only. Returns the report_version: 1 Blast Radius "
            "payload (target, score, band, stats, findings, draft_available, "
            "packs_suggested) plus a 'unified' key holding the M2.5 envelope "
            "for the same run. Both come from one scan."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory to scan."}
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        handler=_audit_handler,
    ),
    McpTool(
        name="scyvera_validate",
        description=(
            "Validate a contract at tier 0. Returns the CheckReport payload: "
            "valid, validation_errors, warnings, tier1_findings, tier1_failed."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "contract_path": {
                    "type": "string",
                    "description": "Path to contract.yaml.",
                }
            },
            "required": ["contract_path"],
            "additionalProperties": False,
        },
        handler=_validate_handler,
    ),
    McpTool(
        name="scyvera_check",
        description=(
            "Run the RFC 0003 conformance check. Returns the CheckReport "
            "payload. 'tier' defaults to auto; tier 2 fails loudly with the "
            "CLI's own message instead of reporting a pass."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Contract file or implementation directory.",
                },
                "tier": {
                    "type": "string",
                    "enum": ["0", "1", "2", "auto"],
                    "description": "Conformance tier (default: auto).",
                },
            },
            "required": ["target"],
            "additionalProperties": False,
        },
        handler=_check_handler,
    ),
    McpTool(
        name="scyvera_self_check",
        description=(
            "Verify the installed distribution against its signed manifest. "
            "Returns the self_check_version: 1 payload plus status "
            "(ok|report|error) and exit_code (0|1|2)."
        ),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        handler=_self_check_handler,
    ),
    McpTool(
        name="scyvera_packages",
        description=(
            "Return static metadata: version, supported specification versions, "
            "MCP protocol version, and capabilities. Deterministic; no I/O."
        ),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        handler=_packages_handler,
    ),
)

_TOOLS_BY_NAME: dict[str, McpTool] = {tool.name: tool for tool in TOOLS}


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


def _json_line(payload: Mapping[str, Any]) -> str:
    """Serialize one frame: sorted keys, compact separators, no padding."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _result(request_id: Any, result: Mapping[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": dict(result)}


def _validate_arguments(
    tool: McpTool, arguments: Any
) -> Mapping[str, Any]:
    if not isinstance(arguments, dict):
        raise _InvalidParams("'arguments' must be an object")
    properties = tool.input_schema.get("properties", {})
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        raise _InvalidParams(f"unexpected argument(s): {', '.join(unknown)}")
    missing = [name for name in tool.input_schema.get("required", []) if name not in arguments]
    if missing:
        raise _InvalidParams(f"missing required argument(s): {', '.join(missing)}")
    for name, value in arguments.items():
        spec = properties[name]
        if spec.get("type") == "string" and not isinstance(value, str):
            raise _InvalidParams(f"argument '{name}' must be a string")
        choices = spec.get("enum")
        if choices is not None and value not in choices:
            raise _InvalidParams(
                f"argument '{name}' must be one of {', '.join(choices)}"
            )
    return arguments


def _call_tool(params: Any) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise _InvalidParams("'params' must be an object")
    name = params.get("name")
    if not isinstance(name, str):
        raise _InvalidParams("'params.name' must be a string")
    tool = _TOOLS_BY_NAME.get(name)
    if tool is None:
        raise _InvalidParams(f"unknown tool: {name}")
    arguments = _validate_arguments(tool, params.get("arguments", {}))
    payload = tool.handler(arguments)
    return {
        "content": [{"type": "text", "text": _json_line(payload)}],
        "isError": False,
    }


class McpServer:
    """One JSON-RPC dispatcher; holds no request state between messages."""

    def __init__(self, stdout: TextIO) -> None:
        self._stdout = stdout

    def emit(self, response: Mapping[str, Any]) -> None:
        self._stdout.write(_json_line(response) + "\n")
        self._stdout.flush()

    def handle_line(self, line: str) -> dict[str, Any] | None:
        try:
            message = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return _error(None, PARSE_ERROR, "Parse error")
        return self.handle_message(message)

    def handle_message(self, message: Any) -> dict[str, Any] | None:
        if isinstance(message, list):
            return _error(
                None,
                INVALID_REQUEST,
                "Invalid Request: batch requests are not supported",
            )
        if not isinstance(message, dict):
            return _error(None, INVALID_REQUEST, "Invalid Request")

        notification = "id" not in message
        request_id = message.get("id")
        method = message.get("method")

        if message.get("jsonrpc") != "2.0" or not isinstance(method, str) or not method:
            if notification:
                return None
            return _error(request_id, INVALID_REQUEST, "Invalid Request")

        try:
            result = self._dispatch(method, message.get("params"))
        except _MethodNotFound as error:
            return None if notification else _error(
                request_id, METHOD_NOT_FOUND, f"Method not found: {error.method}"
            )
        except _InvalidParams as error:
            return None if notification else _error(
                request_id, INVALID_PARAMS, f"Invalid params: {error}"
            )
        except _ToolError as error:
            return None if notification else _error(
                request_id, INTERNAL_ERROR, str(error)
            )
        except Exception as error:  # never let one bad request kill the server
            return None if notification else _error(
                request_id,
                INTERNAL_ERROR,
                f"Internal error: {type(error).__name__}: {error}",
            )

        if result is None:
            # Notifications (initialized, cancelled, ...) never get a response.
            return None
        if notification:
            return None
        return _result(request_id, result)

    def _dispatch(self, method: str, params: Any) -> dict[str, Any] | None:
        if method in ("initialized", "notifications/initialized"):
            return None
        if method == "initialize":
            return {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": dict(_CAPABILITIES),
                "serverInfo": {"name": SERVER_NAME, "version": __version__},
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [tool.describe() for tool in TOOLS]}
        if method == "tools/call":
            return _call_tool(params)
        raise _MethodNotFound(method)


class _MethodNotFound(Exception):
    def __init__(self, method: str) -> None:
        super().__init__(method)
        self.method = method


def serve(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    """Serve JSON-RPC frames until EOF.

    Returns ``0`` after a clean shutdown and ``2`` when the input stream is
    already closed (the "started, but the host is gone" case). Nothing is
    written at startup: a host may treat any unprompted stdout byte as fatal.
    """
    input_stream = sys.stdin if stdin is None else stdin
    output_stream = sys.stdout if stdout is None else stdout
    server = McpServer(output_stream)

    if input_stream is None:
        return 2

    saw_input = False
    while True:
        line = input_stream.readline()
        if line == "":
            return 0 if saw_input else 2
        if not line.strip():
            continue
        saw_input = True
        response = server.handle_line(line)
        if response is not None:
            server.emit(response)
