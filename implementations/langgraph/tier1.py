"""Tier 1 static adapter for LangGraph implementations (RFC 0003 §C3, M2.3).

RFC 0003 §C3 defines Tier 1 as conformance-by-inspection: compare the services
and approval gates an implementation actually exercises with what the contract
declares (permissions, side effects, approval points). This adapter implements
that comparison for LangGraph's Python source.

Scope is deliberately the whole implementation directory, not just the
importable package: every ``.py`` file under the target is part of the
implementation surface, including top-level scripts such as ``backfill.py``.
A script that can write to Qdrant or GitHub is a capability of the
implementation even though it never appears in ``graph.py``.

The adapter is pure static analysis. It reads Python source and parses it with
:mod:`ast`; it never imports the target package (whose ``httpx``, ``openai``,
``langgraph``, or Qdrant dependencies may not exist in the scan environment),
never executes target code, never writes, and never opens a socket.

Detection is intentionally explicit and fail-closed:

- ``T101`` **undeclared action** (error): a gateway method, direct HTTP call,
  or known SDK instantiation reaches a service the contract does not declare.
  Unknown gateway methods and unparseable source produce findings rather than
  being skipped.
- ``T102`` **ungated call** (error): the contract declares an approval gate,
  but a write-capable graph node is reachable from the graph entry without
  traversing a gate node. Gateway calls count as gated because the gateway
  enforces the contract at runtime; direct HTTP and SDK calls do not.
- ``T103`` **unused declaration** (warning): the contract declares a
  permission the implementation never exercises. RFC 0003 §C3 names only
  *undeclared* findings; T103 is the same additive symmetry extension used by
  the n8n adapter and never fails a check on its own.

The reference contract is ``version: 1``, so free-text permissions such as
``github: issues:read+write`` and ``qdrant: read+write on one collection`` are
accepted alongside v1.1 mapped entries.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from scyvera.conformance import (
    ContractDeclarations,
    Tier1Adapter,
    Tier1Finding,
    canonical_service,
    extract_contract_declarations,
)

__all__ = ["LangGraphTier1Adapter", "create_adapter"]

# Scyvera gateway classes are runtime enforcement boundaries: a call through
# one is already gated by the contract, so it maps to an exercised capability
# but never to T102.
_GATEWAY_SERVICES = {
    "BaseGateway": "base",
    "GitHubGateway": "github",
    "QdrantGateway": "qdrant",
}

_GITHUB_METHODS: Mapping[str, str] = {
    "read": "read",
    "read_issue": "read",
    "read_issues": "read",
    "get_issue": "read",
    "list_issues": "read",
    "post_comment": "comment",
    "create_comment": "comment",
    "comment": "comment",
    "close_issue": "close",
    "label_issue": "label",
    "add_labels": "label",
    "merge": "merge",
    "merge_pull_request": "merge",
}

_QDRANT_METHODS: Mapping[str, str] = {
    "search": "search",
    "query": "search",
    "upsert": "write",
    "write": "write",
    "add": "write",
    "delete": "delete",
}

# Known SDK constructors that reach an external service without a gateway.
# QdrantClient is left at service granularity because its methods vary; the
# service declaration is still checked, and an unscanned write cannot be
# claimed as exercised.
_SDK_CLASSES: Mapping[str, tuple[str, str]] = {
    "Anthropic": ("anthropic", "inference"),
    "AsyncOpenAI": ("openai", "embeddings"),
    "ChatOpenAI": ("openai", "inference"),
    "Github": ("github", "read"),
    "GoogleGenerativeAI": ("google", "inference"),
    "Ollama": ("local-llm", "inference"),
    "OpenAI": ("openai", "embeddings"),
    "QdrantClient": ("qdrant", "unknown"),
}

_HTTP_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "request"}
)

_WRITE_ACTIONS = frozenset(
    {"write", "comment", "close", "delete", "label", "merge", "publish", "execute"}
)

_GATE_MARKERS = (
    "approval",
    "approve",
    "confirm",
    "gate",
    "human",
    "interrupt",
    "review",
)

# URL markers are checked in order; the first match wins. ``qdrant`` and
# ``github`` dominate the f-string/attribute forms used by the reference
# implementation, where the literal host lives in an environment variable.
_URL_MARKERS: tuple[tuple[str, str], ...] = (
    ("qdrant", "qdrant"),
    ("github", "github"),
    ("openai", "openai"),
    ("anthropic", "anthropic"),
    ("ollama", "local-llm"),
    ("11434", "local-llm"),
    ("telegram", "telegram"),
    ("discord", "discord"),
    ("slack", "slack"),
    ("stripe", "stripe"),
    ("googleapis", "google"),
    ("sheets", "google-sheets"),
    ("google", "google"),
)

_SKIP_DIRECTORIES = frozenset(
    {".git", ".venv", "__pycache__", "build", "dist", "node_modules", "venv"}
)


@dataclass(frozen=True)
class _Capability:
    """One externally-reaching capability extracted from source."""

    node_id: str
    service: str
    action: str
    detail: str
    path: str
    gated: bool = False
    unknown: bool = False

    @property
    def tokens(self) -> frozenset[str]:
        """Service and service.action tokens this capability exercises."""
        tokens = {self.service}
        if self.action and self.action != "unknown":
            tokens.add(f"{self.service}.{self.action}")
        return frozenset(tokens)

    @property
    def is_write(self) -> bool:
        """Whether the capability changes external state."""
        return self.action in _WRITE_ACTIONS


@dataclass(frozen=True)
class _ParsedModule:
    """AST facts for one source file."""

    path: str
    tree: ast.Module
    imports: Mapping[str, str]
    functions: Mapping[str, tuple[_Capability, ...]]
    module_capabilities: tuple[_Capability, ...]
    gate_functions: frozenset[str]


@dataclass(frozen=True)
class _GraphFacts:
    """LangGraph node/edge structure extracted without importing langgraph."""

    nodes: Mapping[str, str]
    edges: Mapping[str, tuple[str, ...]]
    starts: tuple[str, ...]


def _display(value: str) -> str:
    """Keep finding text ASCII so narrow console codepages cannot crash."""
    return value.encode("ascii", "replace").decode("ascii")


def _detail(value: str) -> str:
    """Collapse whitespace and truncate a detail string for one-line output."""
    text = " ".join(value.split())
    return _display(text if len(text) <= 120 else text[:117] + "...")


def _python_files(target: Path) -> tuple[Path, ...]:
    """Every ``.py`` file under ``target``, excluding tooling directories."""
    if target.is_file():
        return (target,) if target.suffix == ".py" else ()
    files = [
        path
        for path in target.rglob("*.py")
        if path.is_file() and not (_SKIP_DIRECTORIES & set(path.parts))
    ]
    return tuple(sorted(files))


def _import_map(tree: ast.Module) -> dict[str, str]:
    """Map local import aliases to resolvable dotted names."""
    imports: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    imports[alias.asname] = alias.name
                else:
                    root = alias.name.split(".", 1)[0]
                    imports[root] = root
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                imports[local] = f"{module}.{alias.name}" if module else alias.name
    return imports


def _resolve_expr(expr: ast.expr, imports: Mapping[str, str]) -> str:
    """Resolve a Name/Attribute expression to a dotted name without importing."""
    if isinstance(expr, ast.Name):
        return imports.get(expr.id, expr.id)
    if isinstance(expr, ast.Attribute):
        base = _resolve_expr(expr.value, imports)
        return f"{base}.{expr.attr}" if base else expr.attr
    return ast.unparse(expr)


def _call_short(call: ast.Call, imports: Mapping[str, str]) -> str:
    """Return the final component of a call target (``add_node``, ``post``)."""
    return _resolve_expr(call.func, imports).rsplit(".", 1)[-1]


def _walk_owned(node: ast.AST) -> Iterable[ast.AST]:
    """Yield descendants, refusing to cross into nested defs or classes."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef)):
            continue
        yield child
        yield from _walk_owned(child)


def _iter_owned_calls(node: ast.AST) -> Iterable[ast.Call]:
    """Yield calls in ``node`` without descending into nested definitions."""
    if isinstance(node, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef)):
        return
    if isinstance(node, ast.Call):
        yield node
    for child in ast.iter_child_nodes(node):
        yield from _iter_owned_calls(child)


def _gateway_class(call: ast.Call, imports: Mapping[str, str]) -> str | None:
    """Return the Scyvera gateway class a call constructs, if any."""
    resolved = _resolve_expr(call.func, imports)
    short = resolved.rsplit(".", 1)[-1]
    if short not in _GATEWAY_SERVICES:
        return None
    if resolved.startswith("scyvera.") or resolved == short:
        return short
    return None


def _gateway_vars(
    func: ast.FunctionDef | ast.AsyncFunctionDef, imports: Mapping[str, str]
) -> dict[str, str]:
    """Map local variables assigned from a Scyvera gateway constructor."""
    variables: dict[str, str] = {}
    for node in _walk_owned(func):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            gateway = _gateway_class(node.value, imports)
            if gateway is None:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    variables[target.id] = gateway
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Call):
            gateway = _gateway_class(node.value, imports)
            if gateway is not None and isinstance(node.target, ast.Name):
                variables[node.target.id] = gateway
    return variables


def _literal_str(expr: ast.expr | None) -> str | None:
    """Return a string constant, when the expression is one."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    return None


def _keyword_str(call: ast.Call, name: str) -> str | None:
    """Return a string keyword argument by name."""
    for keyword in call.keywords:
        if keyword.arg == name:
            return _literal_str(keyword.value)
    return None


def _host_from_url(value: str) -> str:
    """Extract a lowercase host from a literal URL without urllib/net I/O."""
    rest = value.split("://", 1)[1] if "://" in value else value
    authority = rest.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "@" in authority:
        authority = authority.rsplit("@", 1)[1]
    if authority.startswith("["):
        return authority[1:].partition("]")[0].lower()
    return authority.rpartition(":")[0].lower() if ":" in authority else authority.lower()


def _service_from_host(host: str) -> str:
    """Map a literal host to a canonical service token."""
    if not host:
        return "network"
    if host.endswith("openai.com"):
        return "openai"
    if host in {"localhost", "127.0.0.1", "::1"}:
        return "local-llm" if host == "127.0.0.1" else "localhost"
    if host.endswith("github.com") or host.endswith("githubusercontent.com"):
        return "github"
    labels = [label for label in host.split(".") if label]
    if len(labels) >= 2:
        return canonical_service(labels[-2])
    return canonical_service(labels[0]) if labels else "network"


def _literal_hosts(expr: ast.expr) -> tuple[str, ...]:
    """Collect host-looking string constants from a URL expression."""
    hosts: list[str] = []
    for node in ast.walk(expr):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        value = node.value.strip()
        if "://" in value:
            host = _host_from_url(value)
        elif value.startswith("//"):
            host = _host_from_url("https:" + value)
        elif "." in value and "/" not in value and " " not in value:
            host = value.partition(":")[0]
        else:
            continue
        if host:
            hosts.append(host)
    return tuple(hosts)


def _action_for(method: str, text: str) -> str:
    """Derive the exercised action from an HTTP method and URL text."""
    lowered = text.lower()
    if "search" in lowered or "query" in lowered:
        return "search"
    if "delete" in lowered:
        return "delete"
    upper = method.upper()
    if upper in {"GET", "HEAD", "OPTIONS"}:
        return "read"
    if upper == "DELETE":
        return "delete"
    if upper in {"POST", "PUT", "PATCH"}:
        return "write"
    return "read"


def _service_for_url(
    expr: ast.expr | None, method: str
) -> tuple[str, str, str]:
    """Return ``(service, detail, action)`` for an HTTP URL expression."""
    text = ast.unparse(expr) if expr is not None else "<dynamic>"
    lowered = text.lower()

    for marker, service in _URL_MARKERS:
        if marker in lowered:
            return service, _detail(text), _action_for(method, text)

    for host in _literal_hosts(expr) if expr is not None else ():
        service = _service_from_host(host)
        if service != "network":
            return service, _detail(text), _action_for(method, text)

    return "network", _detail(text), _action_for(method, text)


def _gateway_capability(
    gateway: str,
    method: str,
    *,
    node_id: str,
    path: str,
) -> _Capability:
    """Map a gateway method call to the capability it exercises."""
    service = _GATEWAY_SERVICES[gateway]
    methods = _GITHUB_METHODS if service == "github" else _QDRANT_METHODS
    action = methods.get(method.lower())
    if action is None:
        return _Capability(
            node_id=node_id,
            service=service,
            action="unknown",
            detail=f"{gateway}.{method}()",
            path=path,
            gated=True,
            unknown=True,
        )
    return _Capability(
        node_id=node_id,
        service=service,
        action=action,
        detail=f"{gateway}.{method}()",
        path=path,
        gated=True,
    )


def _http_capability(
    call: ast.Call,
    method: str,
    *,
    node_id: str,
    path: str,
) -> _Capability:
    """Build a capability for an ``httpx``/``requests`` call."""
    url_expr: ast.expr | None
    if method.lower() == "request":
        url_expr = call.args[1] if len(call.args) > 1 else None
        if url_expr is None:
            for keyword in call.keywords:
                if keyword.arg == "url":
                    url_expr = keyword.value
        explicit = _literal_str(call.args[0]) if call.args else None
        http_method = (explicit or _keyword_str(call, "method") or "GET").upper()
    else:
        url_expr = call.args[0] if call.args else None
        if url_expr is None:
            for keyword in call.keywords:
                if keyword.arg == "url":
                    url_expr = keyword.value
        http_method = method.upper()

    service, detail, action = _service_for_url(url_expr, http_method)
    return _Capability(
        node_id=node_id,
        service=service,
        action=action,
        detail=f"{http_method} {detail}",
        path=path,
    )


def _urlopen_capability(
    call: ast.Call,
    imports: Mapping[str, str],
    *,
    node_id: str,
    path: str,
) -> _Capability:
    """Build a capability for ``urllib.request.urlopen``/``Request``."""
    first = call.args[0] if call.args else None
    if first is None:
        for keyword in call.keywords:
            if keyword.arg == "url":
                first = keyword.value
                break

    method = "GET"
    url_expr = first
    if isinstance(first, ast.Call) and _call_short(first, imports) == "Request":
        url_expr = first.args[0] if first.args else None
        method = (
            _keyword_str(first, "method")
            or ("POST" if any(keyword.arg == "data" for keyword in first.keywords) else "GET")
        ).upper()

    service, detail, action = _service_for_url(url_expr, method)
    return _Capability(
        node_id=node_id,
        service=service,
        action=action,
        detail=f"{method} {detail}",
        path=path,
    )


def _capability_for_call(
    call: ast.Call,
    gateway_vars: Mapping[str, str],
    imports: Mapping[str, str],
    *,
    node_id: str,
    path: str,
) -> _Capability | None:
    """Classify one call site, returning ``None`` for non-external calls."""
    func = call.func

    # A method call on a gateway variable (or an inline gateway constructor).
    if isinstance(func, ast.Attribute):
        gateway: str | None = None
        if isinstance(func.value, ast.Name):
            gateway = gateway_vars.get(func.value.id)
        elif isinstance(func.value, ast.Call):
            gateway = _gateway_class(func.value, imports)
        if gateway is not None:
            return _gateway_capability(
                gateway, func.attr, node_id=node_id, path=path
            )

    resolved = _resolve_expr(func, imports)
    short = resolved.rsplit(".", 1)[-1]

    if resolved.startswith(("httpx.", "requests.")) and short in _HTTP_METHODS:
        return _http_capability(call, short, node_id=node_id, path=path)

    if short == "urlopen" and ("urllib" in resolved or resolved == "urlopen"):
        return _urlopen_capability(call, imports, node_id=node_id, path=path)

    sdk = _SDK_CLASSES.get(short)
    if sdk is not None and (resolved == short or resolved.endswith(f".{short}")):
        service, action = sdk
        return _Capability(
            node_id=node_id,
            service=service,
            action=action,
            detail=f"{short}()",
            path=path,
        )

    return None


def _gate_function_names(functions: Mapping[str, ast.AST]) -> frozenset[str]:
    """Functions whose body calls a LangGraph interrupt (human-in-the-loop)."""
    gates: set[str] = set()
    for name, node in functions.items():
        for call in _iter_owned_calls(node):
            if "interrupt" in _call_short_without_imports(call).lower():
                gates.add(name)
                break
    return frozenset(gates)


def _call_short_without_imports(call: ast.Call) -> str:
    """Best-effort final call name for gate detection."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _scan_function(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: Mapping[str, str],
    path: str,
    node_id: str,
) -> tuple[_Capability, ...]:
    """Collect capabilities exercised by one function body."""
    gateway_vars = _gateway_vars(func, imports)
    capabilities: list[_Capability] = []
    for statement in func.body:
        for call in _iter_owned_calls(statement):
            capability = _capability_for_call(
                call,
                gateway_vars,
                imports,
                node_id=node_id,
                path=path,
            )
            if capability is not None:
                capabilities.append(capability)
    return _unique_capabilities(capabilities)


def _unique_capabilities(
    capabilities: Iterable[_Capability],
) -> tuple[_Capability, ...]:
    """Deduplicate capabilities while preserving source order."""
    seen: set[tuple[Any, ...]] = set()
    unique: list[_Capability] = []
    for capability in capabilities:
        key = (
            capability.node_id,
            capability.service,
            capability.action,
            capability.detail,
            capability.path,
            capability.gated,
            capability.unknown,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(capability)
    return tuple(unique)


def _parse_module(path: Path) -> _ParsedModule:
    """Parse one source file without importing or executing it."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    imports = _import_map(tree)

    functions: dict[str, tuple[_Capability, ...]] = {}
    function_nodes: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            functions[node.name] = _scan_function(
                node, imports, str(path), node.name
            )
            function_nodes[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.AsyncFunctionDef, ast.FunctionDef)):
                    name = f"{node.name}.{item.name}"
                    functions[name] = _scan_function(
                        item, imports, str(path), name
                    )
                    function_nodes[name] = item

    module_capabilities: list[_Capability] = []
    for statement in tree.body:
        if isinstance(statement, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef)):
            continue
        for call in _iter_owned_calls(statement):
            capability = _capability_for_call(
                call,
                {},
                imports,
                node_id="<module>",
                path=str(path),
            )
            if capability is not None:
                module_capabilities.append(capability)

    return _ParsedModule(
        path=str(path),
        tree=tree,
        imports=imports,
        functions=functions,
        module_capabilities=_unique_capabilities(module_capabilities),
        gate_functions=_gate_function_names(function_nodes),
    )


def _endpoint(expr: ast.expr | None, imports: Mapping[str, str]) -> str | None:
    """Resolve a graph node identifier (``START``, ``END``, or a string)."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        resolved = _resolve_expr(expr, imports)
        return resolved.rsplit(".", 1)[-1]
    return None


def _function_name(expr: ast.expr | None, imports: Mapping[str, str]) -> str | None:
    """Resolve an ``add_node`` function argument to a short function name."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.Name):
        return imports.get(expr.id, expr.id).rsplit(".", 1)[-1]
    if isinstance(expr, ast.Attribute):
        return expr.attr
    return None


def _build_graph(modules: Iterable[_ParsedModule]) -> _GraphFacts:
    """Extract node ids, edges, and entry points from ``add_*`` calls."""
    nodes: dict[str, str] = {}
    edge_lists: dict[str, list[str]] = {}

    def add_edge(source: str | None, target: str | None) -> None:
        if source and target:
            edge_lists.setdefault(source, []).append(target)

    for module in modules:
        for node in ast.walk(module.tree):
            if not isinstance(node, ast.Call):
                continue
            short = _call_short(node, module.imports)

            if short == "add_node" and len(node.args) >= 2:
                node_id = _literal_str(node.args[0])
                function = _function_name(node.args[1], module.imports)
                if node_id and function:
                    nodes[node_id] = function
            elif short == "add_edge" and len(node.args) >= 2:
                add_edge(
                    _endpoint(node.args[0], module.imports),
                    _endpoint(node.args[1], module.imports),
                )
            elif short == "add_conditional_edges" and len(node.args) >= 3:
                source = _endpoint(node.args[0], module.imports)
                mapping = node.args[2]
                if source and isinstance(mapping, ast.Dict):
                    for value in mapping.values:
                        add_edge(source, _endpoint(value, module.imports))
            elif short == "set_entry_point" and node.args:
                add_edge("START", _endpoint(node.args[0], module.imports))

    edges = {
        source: tuple(dict.fromkeys(targets))
        for source, targets in edge_lists.items()
    }
    starts = edges.get("START", ())
    if not starts:
        incoming = {
            target
            for source, targets in edges.items()
            if source != "START"
            for target in targets
            if target != "END"
        }
        starts = tuple(sorted(node for node in nodes if node not in incoming))
    return _GraphFacts(nodes=nodes, edges=edges, starts=starts)


def _reachable_without_gate(
    graph: _GraphFacts,
    target: str,
    gates: frozenset[str],
) -> bool:
    """BFS from the graph entry to ``target`` while refusing to enter gates."""
    if not graph.starts:
        # A graph we could not read is not evidence of safety: fail closed.
        return True
    seen = set(graph.starts)
    queue = list(graph.starts)
    while queue:
        current = queue.pop()
        if current == target:
            return True
        for neighbour in graph.edges.get(current, ()):
            if neighbour in gates or neighbour in seen:
                continue
            seen.add(neighbour)
            queue.append(neighbour)
    return False


def _looks_like_gate(name: str) -> bool:
    """Whether a node id or function name names an approval boundary."""
    lowered = name.lower()
    return any(marker in lowered for marker in _GATE_MARKERS)


def _gate_nodes(
    graph: _GraphFacts, modules: Iterable[_ParsedModule]
) -> frozenset[str]:
    """Node ids that implement an explicit approval boundary."""
    gate_functions: set[str] = set()
    for module in modules:
        gate_functions.update(module.gate_functions)

    gates: set[str] = set()
    for node_id, function in graph.nodes.items():
        if (
            _looks_like_gate(node_id)
            or _looks_like_gate(function)
            or function in gate_functions
        ):
            gates.add(node_id)
    return frozenset(gates)


def _load_contract(path: Path) -> Mapping[str, Any]:
    """Load an already-validated contract for declaration comparison."""
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data if isinstance(data, Mapping) else {}


def _t101_finding(capability: _Capability) -> Tier1Finding:
    """Build an undeclared-action finding for one capability."""
    if capability.unknown:
        message = (
            f"node '{_display(capability.node_id)}' calls an unmapped "
            f"capability ('{_display(capability.service)}', "
            f"{_display(capability.detail)}) that the adapter cannot verify "
            "against the contract"
        )
    else:
        message = (
            f"node '{_display(capability.node_id)}' reaches "
            f"'{_display(capability.service)}' "
            f"({_display(capability.detail)}) but the contract declares no "
            "permission for it"
        )
    return Tier1Finding(
        code="T101",
        title="undeclared action",
        message=message,
        path=capability.path,
        node_id=_display(capability.node_id),
        severity="error",
    )


class LangGraphTier1Adapter(Tier1Adapter):
    """Tier 1 adapter for LangGraph Python implementations (RFC 0003 §C3)."""

    framework = "langgraph"

    def _scan(
        self, target: Path, contract_path: Path
    ) -> tuple[Tier1Finding, ...]:
        target = Path(target)
        contract_path = Path(contract_path)

        modules: list[_ParsedModule] = []
        findings: list[Tier1Finding] = []
        for path in _python_files(target):
            try:
                modules.append(_parse_module(path))
            except (SyntaxError, UnicodeDecodeError) as error:
                capability = _Capability(
                    node_id="<module>",
                    service="unparseable-source",
                    action="unknown",
                    detail=f"{path.name}: {error}",
                    path=str(path),
                    unknown=True,
                )
                findings.append(_t101_finding(capability))

        contract = _load_contract(contract_path)
        declarations: ContractDeclarations = extract_contract_declarations(contract)
        graph = _build_graph(modules)

        capabilities = [
            capability
            for module in modules
            for capability in module.module_capabilities
        ]
        for module in modules:
            for function_caps in module.functions.values():
                capabilities.extend(function_caps)

        # T101 — every reached service must be declared. Unknown gateway
        # methods and unparseable source fail closed regardless of service.
        for capability in capabilities:
            if capability.unknown or capability.service not in declarations.services:
                findings.append(_t101_finding(capability))

        functions: dict[str, tuple[_Capability, ...]] = {}
        for module in modules:
            for name, function_caps in module.functions.items():
                if name in functions:
                    functions[name] = _unique_capabilities(
                        (*functions[name], *function_caps)
                    )
                else:
                    functions[name] = function_caps

        node_capabilities: dict[str, tuple[_Capability, ...]] = {}
        for node_id, function in graph.nodes.items():
            function_caps = functions.get(function)
            if function_caps:
                node_capabilities[node_id] = function_caps

        # T102 — when a gate is declared, graph writes must sit behind one.
        if declarations.requires_approval:
            gates = _gate_nodes(graph, modules)
            for node_id in sorted(node_capabilities):
                if node_id in gates:
                    continue
                if not _reachable_without_gate(graph, node_id, gates):
                    continue
                seen_services: set[str] = set()
                for capability in node_capabilities[node_id]:
                    if capability.gated or not capability.is_write:
                        continue
                    if capability.service in seen_services:
                        continue
                    seen_services.add(capability.service)
                    findings.append(
                        Tier1Finding(
                            code="T102",
                            title="ungated call",
                            message=(
                                f"node '{_display(node_id)}' performs a "
                                f"'{_display(capability.service)}' "
                                f"{_display(capability.action)} reachable from "
                                "the graph entry without traversing an "
                                "approval gate"
                            ),
                            path=capability.path,
                            node_id=_display(node_id),
                            severity="error",
                        )
                    )

        # T103 — declared permissions the implementation never exercises.
        exercised: set[str] = set()
        for capability in capabilities:
            exercised.update(capability.tokens)
        contract_display = _display(str(contract_path))
        for token in sorted(declarations.permission_tokens - exercised):
            findings.append(
                Tier1Finding(
                    code="T103",
                    title="unused declaration",
                    message=(
                        f"contract declares a permission for "
                        f"'{_display(token)}' but the implementation never "
                        "exercises it"
                    ),
                    path=contract_display,
                    node_id="",
                    severity="warning",
                )
            )

        order = {"T101": 0, "T102": 1, "T103": 2}
        return tuple(
            sorted(
                findings,
                key=lambda finding: (
                    order.get(finding.code, 9),
                    finding.path,
                    finding.node_id,
                    finding.message,
                ),
            )
        )


def create_adapter() -> LangGraphTier1Adapter:
    """Factory used by the CLI's tier 1 adapter loader."""
    return LangGraphTier1Adapter()
