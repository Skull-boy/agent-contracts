"""Wire-level pins for the PD-7 MCP server (roadmap PD-7).

Unlike ``tests/test_pd6_action.py`` — which can only pin a GitHub-declared
interface statically — the MCP contract is a byte protocol, so these pins are
executable: every test drives ``serve`` over two in-memory text streams, the
same newline-delimited JSON-RPC 2.0 shape as stdio.

What is pinned here: the JSON-RPC error codes (-32700, -32600, -32601,
-32602), one-error-per-bad-line with the stream continuing, the five-tool
surface and its schemas, live tool results from the real engines, CLI parity
for tier 2 refusal, stdout purity (handlers never print), and the absence of
any process or dynamic-code surface in the module.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
from pathlib import Path

import pytest

from scyvera.audit import scan_tree
from scyvera.cli import build_parser, run_check
from scyvera.mcp_server import (
    HELP_LINE,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    PROTOCOL_VERSION,
    TOOLS,
    serve,
)

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "src" / "scyvera" / "mcp_server.py"

VALID_CONTRACT = "version: 1.1\nagent:\n  name: Minimal Assistant\n"

EXPECTED_TOOLS = [
    "scyvera_audit",
    "scyvera_validate",
    "scyvera_check",
    "scyvera_self_check",
    "scyvera_packages",
]

EXPECTED_REQUIRED = {
    "scyvera_audit": ["path"],
    "scyvera_validate": ["contract_path"],
    "scyvera_check": ["target"],
    "scyvera_self_check": [],
    "scyvera_packages": [],
}


def session(requests):
    """Run one scripted session; return (exit, parsed responses, raw stdout)."""
    lines = [
        request if isinstance(request, str) else json.dumps(request)
        for request in requests
    ]
    stdin = io.StringIO("\n".join(lines) + "\n")
    stdout = io.StringIO()
    code = serve(stdin=stdin, stdout=stdout)
    raw = stdout.getvalue()
    responses = [json.loads(line) for line in raw.splitlines() if line.strip()]
    return code, responses, raw


def call(tool: str, arguments: dict, request_id: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }


def payload_of(tool: str, arguments: dict) -> dict:
    code, responses, _ = session([call(tool, arguments)])
    assert code == 0
    (response,) = responses
    assert response["result"]["isError"] is False
    (content,) = response["result"]["content"]
    assert content["type"] == "text"
    return json.loads(content["text"])


def payload_error(tool: str, arguments: dict) -> dict:
    _, responses, _ = session([call(tool, arguments)])
    (response,) = responses
    assert "error" in response, response
    return response["error"]


def write_contract(tmp_path: Path, text: str = VALID_CONTRACT) -> Path:
    contract = tmp_path / "contract.yaml"
    contract.write_text(text, encoding="utf-8")
    return contract


# ---------------------------------------------------------------------------
# JSON-RPC wire behaviour
# ---------------------------------------------------------------------------


def test_parse_error_is_one_frame_and_the_stream_continues() -> None:
    code, responses, _ = session(
        ["{oops", {"jsonrpc": "2.0", "id": 2, "method": "ping"}]
    )
    assert code == 0
    assert len(responses) == 2
    assert responses[0] == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": PARSE_ERROR, "message": "Parse error"},
    }
    assert responses[1] == {"jsonrpc": "2.0", "id": 2, "result": {}}


def test_unknown_method_is_method_not_found() -> None:
    _, responses, _ = session(
        [{"jsonrpc": "2.0", "id": 7, "method": "tools/delete-everything"}]
    )
    (response,) = responses
    assert response["error"] == {
        "code": METHOD_NOT_FOUND,
        "message": "Method not found: tools/delete-everything",
    }
    assert response["id"] == 7


def test_invalid_params_are_rejected_before_any_engine_runs() -> None:
    _, responses, _ = session(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"arguments": {}},
            },
            call("scyvera_nope", {}),
            call("scyvera_audit", {}),
            call("scyvera_audit", {"path": ".", "extra": "no"}),
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "scyvera_packages", "arguments": []},
            },
        ]
    )
    assert [response["error"]["code"] for response in responses] == [
        INVALID_PARAMS
    ] * 5
    assert "params.name" in responses[0]["error"]["message"]
    assert "unknown tool" in responses[1]["error"]["message"]
    assert "missing required argument(s): path" in responses[2]["error"]["message"]
    assert "unexpected argument(s): extra" in responses[3]["error"]["message"]
    assert "'arguments' must be an object" in responses[4]["error"]["message"]


def test_batch_requests_are_rejected_with_invalid_request() -> None:
    _, responses, _ = session(
        [
            [{"jsonrpc": "2.0", "id": 1, "method": "ping"}],
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        ]
    )
    assert len(responses) == 2
    assert responses[0]["error"] == {
        "code": INVALID_REQUEST,
        "message": "Invalid Request: batch requests are not supported",
    }
    assert responses[0]["id"] is None
    assert responses[1]["result"] == {}


def test_notifications_never_receive_a_response() -> None:
    _, responses, raw = session(
        [
            {"jsonrpc": "2.0", "method": "initialized"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "method": "unknown/notification"},
            {"jsonrpc": "2.0", "id": 3, "method": "ping"},
        ]
    )
    assert len(responses) == 1
    assert responses[0]["id"] == 3
    assert raw.count("\n") == 1


def test_invalid_jsonrpc_version_and_non_object_frames() -> None:
    _, responses, _ = session(
        [
            {"jsonrpc": "1.0", "id": 1, "method": "ping"},
            "42",
            {"id": 3, "method": "ping"},
        ]
    )
    assert [response["error"]["code"] for response in responses] == [
        INVALID_REQUEST
    ] * 3
    assert responses[0]["id"] == 1
    assert responses[1]["id"] is None
    assert responses[2]["id"] == 3


# ---------------------------------------------------------------------------
# Handshake and tool registry
# ---------------------------------------------------------------------------


def test_initialize_pins_protocol_version_and_capabilities() -> None:
    _, responses, _ = session(
        [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}]
    )
    result = responses[0]["result"]
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"]["name"] == "scyvera-mcp"
    assert result["serverInfo"]["version"]


def test_tools_list_is_the_five_tool_contract() -> None:
    _, responses, _ = session(
        [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}]
    )
    listed = responses[0]["result"]["tools"]
    assert [tool["name"] for tool in listed] == EXPECTED_TOOLS
    for tool in listed:
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert list(schema["required"]) == EXPECTED_REQUIRED[tool["name"]]
        assert tool["description"]


def test_registry_order_matches_tools_list() -> None:
    assert [tool.name for tool in TOOLS] == EXPECTED_TOOLS


# ---------------------------------------------------------------------------
# Live tool results
# ---------------------------------------------------------------------------


def test_validate_live_call_reports_a_valid_contract(tmp_path: Path) -> None:
    contract = write_contract(tmp_path)
    payload = payload_of("scyvera_validate", {"contract_path": str(contract)})
    assert payload["valid"] is True
    assert payload["tier"] == 0
    assert payload["validation_errors"] == []
    assert payload["warnings"] == []


def test_validate_corrupt_yaml_is_a_deterministic_jsonrpc_error(
    tmp_path: Path,
) -> None:
    contract = write_contract(tmp_path, "version: [unclosed\n")
    first = payload_error("scyvera_validate", {"contract_path": str(contract)})
    second = payload_error("scyvera_validate", {"contract_path": str(contract)})
    assert first["code"] == INTERNAL_ERROR
    assert first["message"].startswith("scyvera_validate: invalid YAML:")
    assert first == second


def test_audit_returns_one_run_with_payload_and_unified(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# clean\n", encoding="utf-8")
    code, responses, raw = session([call("scyvera_audit", {"path": str(tmp_path)})])
    assert code == 0
    payload = json.loads(responses[0]["result"]["content"][0]["text"])

    assert payload["report_version"] == 1
    assert payload["unified"]["mode"] == "audit"
    assert payload["unified"]["report_version"] == 1
    assert payload["unified"]["data"] == {
        key: value for key, value in payload.items() if key != "unified"
    }
    assert payload["unified"]["summary"]["score"] == payload["score"]

    # Byte-identical to a second run and structurally identical to the engine.
    engine_payload = scan_tree(tmp_path).to_dict()
    assert payload["unified"]["data"] == engine_payload
    _, _, second_raw = session([call("scyvera_audit", {"path": str(tmp_path)})])
    assert raw == second_raw


def test_check_tier1_matches_the_cli_on_the_reference_target(capsys) -> None:
    target = ROOT / "implementations" / "langgraph" / "duplicate-issue-detector"
    cli_code = run_check(target, tier="1")
    cli_output = capsys.readouterr().out
    assert cli_code == 0

    payload = payload_of("scyvera_check", {"target": str(target), "tier": "1"})
    assert payload["valid"] is True
    assert payload["tier"] == 1
    assert payload["tier1_failed"] is False
    assert len(payload["tier1_findings"]) == 6
    assert "WARN" in cli_output


def test_tier2_refusal_matches_the_cli_message(capsys, tmp_path: Path) -> None:
    contract = write_contract(tmp_path)
    cli_code = run_check(contract, tier="2")
    cli_stderr = capsys.readouterr().err
    assert cli_code == 2
    assert cli_stderr.startswith("scyvera check: error: tier 2")

    error = payload_error("scyvera_check", {"target": str(contract), "tier": "2"})
    assert error["code"] == INTERNAL_ERROR
    assert error["message"] == cli_stderr.strip()


def test_missing_target_is_a_jsonrpc_error(tmp_path: Path) -> None:
    error = payload_error(
        "scyvera_audit", {"path": str(tmp_path / "does-not-exist")}
    )
    assert error["code"] == INTERNAL_ERROR
    assert error["message"].startswith("scyvera_audit: path not found:")


def test_symlinked_target_is_refused(tmp_path: Path, monkeypatch) -> None:
    # Patching the link check keeps the pin identical on every platform
    # (Windows CI cannot create symlinks without elevation).
    monkeypatch.setattr("scyvera.mcp_server.os.path.islink", lambda path: True)
    error = payload_error("scyvera_audit", {"path": str(tmp_path)})
    assert error["code"] == INTERNAL_ERROR
    assert "symlink" in error["message"]


def test_self_check_payload_preserves_the_exit_code_mapping() -> None:
    payload = payload_of("scyvera_self_check", {})
    assert payload["self_check_version"] == 1
    assert payload["exit_code"] in (0, 1, 2)
    assert payload["status"] == {0: "ok", 1: "report", 2: "error"}[
        payload["exit_code"]
    ]


def test_packages_is_static_metadata() -> None:
    payload = payload_of("scyvera_packages", {})
    assert payload["name"] == "scyvera"
    assert payload["version"]
    assert payload["spec_versions"] == ["1", "1.1", "1.2"]
    assert payload["protocol_version"] == PROTOCOL_VERSION
    assert payload["tools"] == EXPECTED_TOOLS
    assert set(payload["capabilities"]) >= {"audit", "check", "validate"}


# ---------------------------------------------------------------------------
# Stdout purity and shutdown semantics
# ---------------------------------------------------------------------------


def test_every_emitted_line_is_one_json_object() -> None:
    _, _, raw = session(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            "{not json",
            {"jsonrpc": "2.0", "method": "initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            [{"jsonrpc": "2.0", "id": 3, "method": "ping"}],
            {"jsonrpc": "2.0", "id": 4, "method": "ping"},
        ]
    )
    lines = raw.splitlines()
    assert lines
    for line in lines:
        assert line == line.rstrip()
        assert isinstance(json.loads(line), dict)


def test_tool_handlers_never_write_to_stdout(tmp_path: Path) -> None:
    contract = write_contract(tmp_path)
    (tmp_path / "README.md").write_text("# clean\n", encoding="utf-8")
    cases = [
        ("scyvera_audit", {"path": str(tmp_path)}),
        ("scyvera_validate", {"contract_path": str(contract)}),
        ("scyvera_check", {"target": str(contract), "tier": "0"}),
        ("scyvera_self_check", {}),
        ("scyvera_packages", {}),
    ]
    tools = {tool.name: tool for tool in TOOLS}
    for name, arguments in cases:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            tools[name].handler(arguments)
        assert stdout.getvalue() == "", f"{name} wrote to stdout"
        assert stderr.getvalue() == "", f"{name} wrote to stderr"


def test_serve_reports_closed_input_and_clean_eof() -> None:
    assert serve(stdin=io.StringIO(""), stdout=io.StringIO()) == 2
    assert (
        serve(
            stdin=io.StringIO('{"jsonrpc":"2.0","id":1,"method":"ping"}\n'),
            stdout=io.StringIO(),
        )
        == 0
    )


# ---------------------------------------------------------------------------
# CLI registration and the no-process-surface pin
# ---------------------------------------------------------------------------


def test_cli_registers_serve_mcp_and_prints_the_usage_line(capsys) -> None:
    parser = build_parser()
    args = parser.parse_args(["serve-mcp"])
    assert args.command == "serve-mcp"

    with pytest.raises(SystemExit) as raised:
        parser.parse_args(["serve-mcp", "--help"])
    assert raised.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    assert " ".join(HELP_LINE.split()) in help_text


def test_module_has_no_process_or_dynamic_code_surface() -> None:
    source = MODULE.read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "socket" not in source
    assert "print(" not in source
    assert re.search(r"\b(?:eval|exec)\b", source) is None
