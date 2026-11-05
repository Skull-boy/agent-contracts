"""Tier 1 static adapter for n8n workflows (RFC 0003 §C3, roadmap M2.2).

RFC 0003 §C3 defines Tier 1 as conformance-by-inspection: compare the services
and gates a workflow declares in its JSON with what the contract declares
(permissions, side effects, approvals). This adapter implements that comparison
for n8n:

- ``T101`` **undeclared action** (error): a node reaches an external service
  for which the contract declares no permission. This includes disabled
  nodes — a disabled ``httpRequest`` is one toggle away from acting, so it is
  still part of the declared implementation surface.
- ``T102`` **ungated call** (error): the contract declares an approval gate,
  but a write-capable node is reachable from a trigger without traversing a
  gate node (``wait`` with ``resume: webhook`` or Telegram ``sendAndWait``).
- ``T103`` **unused declaration** (warning): the contract declares a
  permission the workflow never exercises. RFC 0003 §C3 only names
  *undeclared* findings; T103 is an additive symmetry extension and never
  fails a check on its own.

The adapter is pure static analysis: it reads ``workflow.json`` with the
standard-library :mod:`json` parser and the contract with PyYAML, and it never
writes to the target, shells out, or opens a network connection. It shares the
:class:`scyvera.conformance.Tier1Adapter` API with every future adapter, so the
CLI can dispatch on target shape alone.

The service mapping is deliberately explicit rather than clever. Known n8n
node types map to canonical service tokens; ``httpRequest`` maps by URL host
or placeholder (``REPLACE_OLLAMA_BASE_URL`` -> ``local-llm``); unknown node
types are treated as externally reaching and therefore produce a finding
instead of being skipped, matching the fail-closed philosophy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from scyvera.conformance import Tier1Adapter, Tier1Finding

__all__ = ["N8nTier1Adapter"]

# n8n node types that only transform data or control flow inside the runtime.
# They cannot reach an external service on their own. Keep this list
# conservative: if a node talks to the outside (Postgres, SSH, FTP, ...), it
# must fall through to the unknown-node path and produce a finding.
_INTERNAL_TYPES = frozenset(
    {
        "aggregate",
        "code",
        "compareDatasets",
        "compression",
        "convertToFile",
        "crypto",
        "dateTime",
        "editImage",
        "errorTrigger",
        "executeWorkflow",
        "executeWorkflowTrigger",
        "extractFromFile",
        "filter",
        "function",
        "functionItem",
        "html",
        "if",
        "itemLists",
        "limit",
        "manualTrigger",
        "markdown",
        "merge",
        "noOp",
        "readBinaryFile",
        "removeDuplicates",
        "renameKeys",
        "respondToWebhook",
        "scheduleTrigger",
        "set",
        "sort",
        "splitInBatches",
        "splitOut",
        "start",
        "stickyNote",
        "stopAndError",
        "switch",
        "wait",
        "webhook",
        "writeBinaryFile",
        "xml",
    }
)

# Canonical service aliases. Contracts are prose in v1.0 and loose mappings in
# v1.1, so tokens are normalised before comparison (``google_sheets`` and
# ``google-sheets`` must match; ``antigravity-cli`` is the contract's name for
# the local shell).
_SERVICE_ALIASES = {
    "antigravity": "local-shell",
    "antigravity-cli": "local-shell",
    "cli": "local-shell",
    "execute-command": "local-shell",
    "executecommand": "local-shell",
    "local-shell": "local-shell",
    "shell": "local-shell",
    "local-llm": "local-llm",
    "llama": "local-llm",
    "llama-cpp": "local-llm",
    "lmstudio": "local-llm",
    "local-model": "local-llm",
    "ollama": "local-llm",
    "googlesheets": "google-sheets",
    "google-sheet": "google-sheets",
    "google-sheets": "google-sheets",
    "sheets": "google-sheets",
    "http": "network",
    "https": "network",
    "internet": "network",
    "network": "network",
    "rss": "network",
    "web": "network",
    "github-api": "github",
    "open-ai": "openai",
    "openai-api": "openai",
    "telegram-bot": "telegram",
}

# URL host/placeholder markers. Order matters where one marker contains
# another (OLLAMA before LLAMA).
_HOST_MARKERS = (
    ("OLLAMA", "local-llm"),
    ("LLAMA", "local-llm"),
    ("QDRANT", "qdrant"),
    ("OPENAI", "openai"),
    ("TELEGRAM", "telegram"),
    ("GITHUB", "github"),
    ("DISCORD", "discord"),
    ("GOOGLE", "google-sheets"),
    ("SHEET", "google-sheets"),
)

# Commands that change state. Everything else from executeCommand is treated
# as a local read/run and does not require an approval gate.
_WRITE_COMMAND_MARKERS = (
    "git push",
    "git commit",
    "git add",
    "git merge",
    "git tag",
    "rm ",
    "rmdir ",
    "del ",
    "mv ",
    "chmod ",
    "chown ",
    "npm publish",
    "docker push",
    "kubectl apply",
    "terraform apply",
    "set-content",
    "out-file",
    "invoke-webrequest",
    "curl -x post",
)


@dataclass(frozen=True)
class _NodeCapability:
    """One externally-reaching capability extracted from a workflow node."""

    node_id: str
    service: str
    action: str
    detail: str
    is_gate: bool = False


@dataclass(frozen=True)
class _ContractDeclarations:
    """Service declarations extracted from a v1.0 or v1.1 contract."""

    services: frozenset[str]
    permission_services: frozenset[str]
    requires_approval: bool


def _canonical_service(token: str) -> str:
    """Normalise a contract or implementation token to a canonical service."""
    cleaned = token.strip().lower().replace("_", "-").replace(" ", "-")
    head = cleaned.split(":", 1)[0]
    return _SERVICE_ALIASES.get(head, head)


def _display(value: str) -> str:
    """Keep finding text ASCII so narrow console codepages cannot crash."""
    return value.encode("ascii", "replace").decode("ascii")


def _declaration_token(item: Any) -> str | None:
    """Extract one service token from a v1.0 or v1.1 declaration entry.

    PyYAML parses a v1.0 permission line such as ``- github: issues:write`` as
    a single-key mapping, so both the free-text mapping form and the v1.1
    ``{resource, actions}`` form must be accepted.
    """
    if isinstance(item, str):
        head = item.split(":", 1)[0].strip()
        return _canonical_service(head) if head else None
    if isinstance(item, Mapping):
        for key in ("service", "resource", "name"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return _canonical_service(value)
        for key in item:
            if isinstance(key, str) and key.strip():
                return _canonical_service(key)
    return None


def _contract_declarations(contract: Mapping[str, Any]) -> _ContractDeclarations:
    """Read permissions, resources, side effects, and approval gates."""
    services: set[str] = set()
    permission_services: set[str] = set()

    permissions = contract.get("permissions") or []
    if isinstance(permissions, Mapping):
        entries: list[Any] = [
            {"service": key, "actions": value} for key, value in permissions.items()
        ]
    elif isinstance(permissions, list):
        entries = permissions
    else:
        entries = []

    for entry in entries:
        token = _declaration_token(entry)
        if token:
            services.add(token)
            permission_services.add(token)

    resources = contract.get("resources") or []
    if isinstance(resources, list):
        for resource in resources:
            token = _declaration_token(resource)
            if token:
                services.add(token)

    side_effects = contract.get("side_effects") or []
    if isinstance(side_effects, list):
        for effect in side_effects:
            if isinstance(effect, Mapping):
                token = _declaration_token(effect)
                if token:
                    services.add(token)
                    permission_services.add(token)

    approval_points = contract.get("approval_points") or []
    approvals = contract.get("approvals") or []
    requires_approval = bool(approval_points) or any(
        not (isinstance(entry, Mapping) and entry.get("required") is False)
        for entry in approvals
    )

    return _ContractDeclarations(
        services=frozenset(services),
        permission_services=frozenset(permission_services),
        requires_approval=requires_approval,
    )


def _load_contract(path: Path) -> Mapping[str, Any]:
    """Load a contract without normalising it (validation already happened)."""
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data if isinstance(data, Mapping) else {}


def _host_detail(url: str) -> str:
    return _display(url if len(url) <= 120 else url[:117] + "...")


def _literal_host_and_port(url: str) -> tuple[str, int | None]:
    """Extract ``(host, port)`` from a literal URL without a network parser.

    ``urllib.parse`` is deliberately avoided: the repository's AU-NET-002
    audit rule treats any ``urllib`` import as an outbound-network capability,
    and the adapter performs no network I/O at scan time.
    """
    rest = url.split("://", 1)[1] if "://" in url else url
    authority = rest.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "@" in authority:
        authority = authority.rsplit("@", 1)[1]

    port: int | None = None
    if authority.startswith("["):
        host, _, tail = authority[1:].partition("]")
        if tail.startswith(":"):
            try:
                port = int(tail[1:])
            except ValueError:
                port = None
        return host.lower(), port

    if ":" in authority:
        host, _, raw_port = authority.rpartition(":")
        try:
            port = int(raw_port)
        except ValueError:
            host = authority
    else:
        host = authority
    return host.lower(), port


def _service_from_url(url: str) -> tuple[str, str]:
    """Map an ``httpRequest`` URL or n8n expression to ``(service, detail)``."""
    text = url.strip()
    if not text:
        return "network", "empty URL"

    upper = text.upper()
    for marker, service in _HOST_MARKERS:
        if marker in upper:
            return service, _host_detail(text)

    if text.startswith("=") or "{{" in text:
        # A dynamic URL (``={{ $json.changelogUrl }}``) is declared as generic
        # network access; the adapter cannot resolve the host statically.
        return "network", _host_detail(text)

    host, port = _literal_host_and_port(text)
    if not host:
        return "network", _host_detail(text)
    if host.endswith("openai.com"):
        return "openai", _host_detail(text)
    if host in {"localhost", "127.0.0.1", "::1"}:
        if port == 11434:
            return "local-llm", _host_detail(text)
        return "localhost", _host_detail(text)

    labels = [label for label in host.split(".") if label]
    if len(labels) >= 2:
        return _canonical_service(labels[-2]), _host_detail(text)
    return _canonical_service(labels[0]), _host_detail(text)


def _command_is_write(command: str) -> bool:
    lowered = command.lower()
    return any(marker in lowered for marker in _WRITE_COMMAND_MARKERS)


def _is_gate_node(node_type: str, parameters: Mapping[str, Any]) -> bool:
    """Return True for nodes that implement an explicit human approval gate."""
    short = node_type.rsplit(".", 1)[-1]
    if short == "wait":
        return str(parameters.get("resume", "")).lower() == "webhook"
    if short == "telegram":
        operation = str(parameters.get("operation", "")).lower()
        response_type = str(parameters.get("responseType", "")).lower()
        return operation == "sendandwait" or response_type == "approval"
    return False


def _capability_for_node(node: Mapping[str, Any]) -> _NodeCapability | None:
    """Extract the externally-reaching capability of one workflow node."""
    name = str(node.get("name", ""))
    node_type = str(node.get("type", ""))
    parameters = node.get("parameters")
    if not isinstance(parameters, Mapping):
        parameters = {}
    short = node_type.rsplit(".", 1)[-1]
    is_gate = _is_gate_node(node_type, parameters)

    if is_gate:
        service = "telegram" if short == "telegram" else "approval-gate"
        detail = "sendAndWait approval" if short == "telegram" else "webhook approval"
        return _NodeCapability(name, service, "gate", detail, is_gate=True)
    if short == "githubTrigger":
        return _NodeCapability(name, "github", "trigger", "issues webhook")
    if short == "telegramTrigger":
        return _NodeCapability(name, "telegram", "trigger", "message updates")

    if short in _INTERNAL_TYPES:
        return None

    if node_type.startswith("@n8n/n8n-nodes-langchain."):
        lowered = short.lower()
        if "ollama" in lowered:
            base = str((parameters.get("options") or {}).get("baseURL", ""))
            return _NodeCapability(
                name, "local-llm", "inference", f"model={short} ({base or 'local'})"
            )
        if "openai" in lowered:
            model = str(parameters.get("model", ""))
            return _NodeCapability(name, "openai", "inference", f"model={model}")
        if short == "agent":
            # The agent node orchestrates; the attached model node is the
            # process that actually reaches the service.
            return None
        return _NodeCapability(name, "langchain", "unknown", node_type)

    if short == "github":
        operation = str(parameters.get("operation", "")).lower()
        read_operations = {"", "get", "getall", "gettree", "list"}
        action = "read" if operation in read_operations else "write"
        return _NodeCapability(
            name, "github", action, f"operation={operation or 'get'}"
        )

    if short == "telegram":
        operation = str(parameters.get("operation", "")).lower()
        return _NodeCapability(
            name, "telegram", "send", f"operation={operation or 'send'}"
        )

    if short == "googleSheets":
        operation = str(parameters.get("operation", "")).lower()
        action = "read" if operation in {"", "lookup", "getall", "read"} else "write"
        return _NodeCapability(
            name, "google-sheets", action, f"operation={operation or 'lookup'}"
        )

    if short == "discord":
        return _NodeCapability(name, "discord", "send", "webhook message")

    if short == "openAi":
        model = str(parameters.get("model", ""))
        return _NodeCapability(name, "openai", "inference", f"model={model}")

    if short == "rssFeedRead":
        url = str(parameters.get("url", ""))
        return _NodeCapability(name, "network", "read", f"rss={_host_detail(url)}")

    if short == "httpRequest":
        method = str(parameters.get("method", "GET")).upper()
        url = str(parameters.get("url", ""))
        service, detail = _service_from_url(url)
        action = "read" if method in {"GET", "HEAD", "OPTIONS"} else "write"
        return _NodeCapability(name, service, action, f"{method} {detail}")

    if short == "executeCommand":
        command = str(parameters.get("command", ""))
        action = "write" if _command_is_write(command) else "execute"
        return _NodeCapability(
            name, "local-shell", action, f"command={_host_detail(command)}"
        )

    # Unknown node types are assumed to reach the outside. Reporting an
    # undeclared service is the fail-closed choice; the alternative (skip)
    # would let a Postgres/SSH/cloud node pass unmentioned.
    return _NodeCapability(name, _canonical_service(short), "unknown", node_type)


def _is_trigger(node: Mapping[str, Any]) -> bool:
    short = str(node.get("type", "")).rsplit(".", 1)[-1]
    return short.endswith("Trigger") or short in {"webhook", "start"}


def _edges(workflow: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    """Build the ``main``-connection graph used for gate reachability."""
    connections = workflow.get("connections") or {}
    graph: dict[str, tuple[str, ...]] = {}
    if not isinstance(connections, Mapping):
        return graph
    for source, spec in connections.items():
        targets: list[str] = []
        if isinstance(spec, Mapping):
            for branch in spec.get("main") or []:
                for edge in branch or []:
                    if isinstance(edge, Mapping):
                        target = edge.get("node")
                        if isinstance(target, str):
                            targets.append(target)
        graph[str(source)] = tuple(targets)
    return graph


def _reachable_without_gate(
    graph: Mapping[str, tuple[str, ...]],
    starts: tuple[str, ...],
    target: str,
    gates: frozenset[str],
) -> bool:
    """BFS from every trigger to ``target`` while refusing to enter gates."""
    seen = set(starts)
    queue = list(starts)
    while queue:
        current = queue.pop()
        if current == target:
            return True
        for neighbour in graph.get(current, ()):
            if neighbour in gates or neighbour in seen:
                continue
            seen.add(neighbour)
            queue.append(neighbour)
    return False


class N8nTier1Adapter(Tier1Adapter):
    """Tier 1 adapter for n8n workflow JSON (RFC 0003 §C3, roadmap M2.2)."""

    framework = "n8n"

    def _scan(
        self, target: Path, contract_path: Path
    ) -> tuple[Tier1Finding, ...]:
        workflow_path = target / "workflow.json"
        with workflow_path.open("r", encoding="utf-8") as handle:
            workflow = json.load(handle)
        if not isinstance(workflow, Mapping):
            raise ValueError(f"{workflow_path}: expected a JSON object")

        contract = _load_contract(contract_path)
        declarations = _contract_declarations(contract)

        nodes = [
            node
            for node in workflow.get("nodes") or []
            if isinstance(node, Mapping)
        ]
        capabilities = [
            capability
            for node in nodes
            if (capability := _capability_for_node(node)) is not None
        ]

        findings: list[Tier1Finding] = []
        workflow_display = _display(str(workflow_path))

        # T101 — every reached service must be declared.
        for capability in capabilities:
            if capability.is_gate or capability.service in declarations.services:
                continue
            findings.append(
                Tier1Finding(
                    code="T101",
                    title="undeclared action",
                    message=(
                        f"node '{_display(capability.node_id)}' reaches "
                        f"'{_display(capability.service)}' "
                        f"({_display(capability.detail)}) but the contract "
                        "declares no permission for it"
                    ),
                    path=workflow_display,
                    node_id=_display(capability.node_id),
                    severity="error",
                )
            )

        # T102 — when a gate is declared, writes must sit behind one.
        if declarations.requires_approval:
            gates = frozenset(
                capability.node_id for capability in capabilities if capability.is_gate
            )
            triggers = tuple(
                str(node.get("name", "")) for node in nodes if _is_trigger(node)
            )
            if triggers:
                graph = _edges(workflow)
                for capability in capabilities:
                    if capability.is_gate or capability.action != "write":
                        continue
                    if _reachable_without_gate(
                        graph, triggers, capability.node_id, gates
                    ):
                        findings.append(
                            Tier1Finding(
                                code="T102",
                                title="ungated call",
                                message=(
                                    f"node '{_display(capability.node_id)}' performs "
                                    f"a '{_display(capability.service)}' write "
                                    "reachable from a trigger without traversing "
                                    "an approval gate"
                                ),
                                path=workflow_display,
                                node_id=_display(capability.node_id),
                                severity="error",
                            )
                        )

        # T103 — declared permissions the implementation never exercises.
        exercised = {capability.service for capability in capabilities}
        contract_display = _display(str(contract_path))
        for service in sorted(declarations.permission_services - exercised):
            findings.append(
                Tier1Finding(
                    code="T103",
                    title="unused declaration",
                    message=(
                        f"contract declares a permission for "
                        f"'{_display(service)}' but the workflow never exercises it"
                    ),
                    path=contract_display,
                    node_id="",
                    severity="warning",
                )
            )

        return tuple(findings)
