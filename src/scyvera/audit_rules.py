"""AUxxx rule registry for the Scyvera audit engine.

Implements the launch rule set defined in RFC 0004 §3. Every rule is a pure
function over ``(path, text, filename)`` and returns zero or more
:class:`Finding` objects; rules never touch the filesystem or shared state.
Adding a rule means adding an entry to :data:`RULES` plus its tests.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import Any, Callable, Literal, Mapping


SEVERITY_WEIGHTS: dict[str, int] = {
    "critical": 15,
    "high": 8,
    "medium": 3,
    "low": 1,
}


@dataclass(frozen=True)
class Finding:
    """A single audit finding (RFC 0004 §3).

    ``scored`` is the M2.0a.1 quarantine marker: fixture findings remain in
    the report but contribute nothing to score, band, or scored stats.
    """

    rule_id: str
    severity: str
    title: str
    detail: str
    path: str
    line: int | None
    suggestion: Mapping[str, Any]
    scored: bool = True


@dataclass(frozen=True)
class AuditRule:
    """A registry entry: metadata plus a pure per-file scanner."""

    rule_id: str
    severity: str
    title: str
    scan: Callable[[str, str, str], list[Finding]]

    def __call__(self, path: str, text: str, filename: str) -> list[Finding]:
        return self.scan(path, text, filename)


_Matcher = Callable[
    [str, str, str],
    list[tuple[int | None, str, Mapping[str, Any]]],
]


def _rule(
    rule_id: str,
    severity: str,
    title: str,
    matcher: _Matcher,
) -> AuditRule:
    """Wrap a matcher so it emits fully-attributed findings."""

    def scan(path: str, text: str, filename: str) -> list[Finding]:
        return [
            Finding(
                rule_id=rule_id,
                severity=severity,
                title=title,
                detail=detail,
                path=path,
                line=line,
                suggestion=suggestion,
            )
            for line, detail, suggestion in matcher(path, text, filename)
        ]

    return AuditRule(rule_id=rule_id, severity=severity, title=title, scan=scan)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_ENV_FILE_RE = re.compile(r"^\.env(?:\..*)?$")
# Committed dotenv templates are documentation, not live secrets: they are
# checked in on purpose with placeholder values. Real dotenv files, including
# .env.local and .env.production, are still audited.
_ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")
_SECRET_KEY_RE = re.compile(
    r"(?:^|_)(?:api_?key|secret|token|password|passwd|pwd|private_?key|"
    r"access_?key|credential)(?:_|$)",
    re.IGNORECASE,
)
_PLACEHOLDER_VALUE_RE = re.compile(
    r"^(?:changeme|change[-_]me|your[-_].*|example.*|placeholder.*|dummy.*|"
    r"test.*|todo|<.*>|\$\{.*\}|\$[A-Z_]+|x{4,}|\*+|-+)$",
    re.IGNORECASE,
)

_SHELL_SUFFIXES = frozenset({".sh", ".bash", ".zsh", ".ksh"})
_POWERSHELL_SUFFIXES = frozenset({".ps1", ".psm1"})
_BATCH_SUFFIXES = frozenset({".bat", ".cmd"})
_MAKE_BASENAMES = frozenset({"makefile", "gnumakefile", "justfile"})
_MAKE_SUFFIXES = frozenset({".mk"})

_SOURCE_SUFFIXES = frozenset(
    {
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".cjs",
        ".rb",
        ".go",
        ".php",
        ".java",
        ".kt",
        ".kts",
        ".cs",
        ".rs",
        ".swift",
        ".lua",
        ".r",
        ".ipynb",
    }
)

_RM_RF_RE = re.compile(r"\brm\s+([^\s;&|`]+(?:\s+[^\s;&|`]+)*)")
_PS_REMOVE_ITEM_RE = re.compile(r"\bRemove-Item\b", re.IGNORECASE)
_PS_RECURSE_RE = re.compile(r"(?:^|\s)-Recurse\b", re.IGNORECASE)
_PS_FORCE_RE = re.compile(r"(?:^|\s)-Force\b", re.IGNORECASE)
_DEL_RECURSIVE_RE = re.compile(r"\b(?:del|erase)\b[^\r\n]*\s/s(?:\s|$)", re.IGNORECASE)

_GIT_FORCE_PUSH_RE = re.compile(
    r"\bgit\s+push\b[^\r\n]*(?:--force(?:-with-lease)?\b|(?<![\w-])-f\b)",
    re.IGNORECASE,
)
_GIT_RESET_HARD_RE = re.compile(r"\bgit\s+reset\b[^\r\n]*\s--hard\b", re.IGNORECASE)
_GIT_BRANCH_DELETE_RE = re.compile(r"\bgit\s+branch\b[^\r\n]*\s-D\b")

_CURL_PIPE_RE = re.compile(
    r"\b(?:curl|wget)\b[^\r\n|]*\|\s*(?:sudo\s+)?"
    r"(?:sh|bash|zsh|dash|ksh|fish|python[0-9.]*|perl|ruby|node)\b",
    re.IGNORECASE,
)
_IWR_PIPE_RE = re.compile(
    r"\b(?:iwr|irm|Invoke-WebRequest|Invoke-RestMethod)\b[^\r\n|]*\|\s*"
    r"(?:iex|Invoke-Expression)\b",
    re.IGNORECASE,
)
_NET_LIB_RE = re.compile(
    r"\b(?:import|from)\s+(requests|httpx|urllib|socket|aiohttp)\b"
    r"|\bfetch\s*\(",
    re.IGNORECASE,
)
_URL_HOST_RE = re.compile(r"https?://([A-Za-z0-9.-]+)")

_WORKFLOW_SUFFIXES = frozenset({".yml", ".yaml"})
_WRITE_ALL_RE = re.compile(
    r"^\s*(?:-\s+)?permissions:\s*write-all\s*(?:#.*)?$",
    re.IGNORECASE,
)
_RUN_KEY_RE = re.compile(r"^(\s*)(?:-\s+)?run:\s*(.*)$")
_SECRET_REF_RE = re.compile(r"\bsecrets\.[A-Za-z0-9_]+")
_CI_PUBLISH_RE = re.compile(
    r"\b(?:npm\s+publish|twine\s+upload|docker\s+push|kubectl\s+apply)\b",
    re.IGNORECASE,
)

_DOCKER_PRIVILEGED_RE = re.compile(r"--privileged\b", re.IGNORECASE)
_DOCKER_SOCKET_RE = re.compile(r"/var/run/docker\.sock\b")
_DOCKER_ROOT_MOUNT_RE = re.compile(r"(?:-v|--volume)\s+/:(?:/|\s|$)")

_N8N_RISK_NODE_TYPES = (
    "httprequest",
    "emailsend",
    "gmail",
    "microsoftoutlook",
    "googlesheets",
    "postgres",
    "mysql",
    "mongodb",
    "slack",
    "airtable",
    "ftp",
    "writebinaryfile",
    "awss3",
    "telegram",
    "discord",
    "notion",
)
_REQUIREMENTS_RE = re.compile(
    r"^requirements(?:[-_.][A-Za-z0-9_.-]+)?\.txt$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _ExecutableLine:
    """A physical source line that a shell-like context may execute."""

    number: int
    text: str


# Shell dialect a file executes in. "generic" is a multi-dialect context
# (Dockerfile, Makefile/justfile, workflow run block) where any supported
# shell syntax may legitimately appear.
_ShellKind = Literal["posix", "powershell", "batch", "generic"]


def _is_env_file(filename: str) -> bool:
    lowered = filename.lower()
    if any(lowered.endswith(suffix) for suffix in _ENV_TEMPLATE_SUFFIXES):
        return False
    return _ENV_FILE_RE.match(filename) is not None


def _is_makefile(filename: str) -> bool:
    lowered = filename.lower()
    return (
        lowered in _MAKE_BASENAMES
        or Path(filename).suffix.lower() in _MAKE_SUFFIXES
    )


def _shell_kind(filename: str) -> _ShellKind | None:
    """Classify a file by the shell it executes, if it executes one."""
    suffix = Path(filename).suffix.lower()

    if suffix in _SHELL_SUFFIXES:
        return "posix"
    if suffix in _POWERSHELL_SUFFIXES:
        return "powershell"
    if suffix in _BATCH_SUFFIXES:
        return "batch"
    if _is_dockerfile(filename) or _is_makefile(filename):
        return "generic"
    if suffix in _WORKFLOW_SUFFIXES:
        return "generic"
    return None


def _workflow_run_lines(text: str) -> tuple[_ExecutableLine, ...]:
    """Extract the physical lines that make up workflow ``run:`` values.

    GitHub Actions executes only the scalar value of a step's ``run`` key.
    Both inline values (``run: make test``) and block scalars (``run: |``)
    are supported. YAML outside those blocks is never exposed to the
    shell/git/network rules, so prose and configuration cannot be mistaken
    for commands.
    """
    lines: list[_ExecutableLine] = []
    run_indent: int | None = None

    for number, raw in enumerate(text.splitlines(), start=1):
        run_match = _RUN_KEY_RE.match(raw)
        if run_match is not None:
            run_indent = len(run_match.group(1))
            remainder = run_match.group(2).strip()

            if not remainder:
                # A null ``run:`` key has no executable value.
                run_indent = None
                continue

            if remainder.startswith(("|", ">")):
                # Block scalar: its indented body follows on later lines.
                continue

            lines.append(_ExecutableLine(number, remainder))
            run_indent = None
            continue

        if run_indent is None:
            continue

        if not raw.strip():
            # Blank lines belong to a block scalar and do not end it.
            continue

        if len(raw) - len(raw.lstrip()) > run_indent:
            lines.append(_ExecutableLine(number, raw))
        else:
            run_indent = None

    return tuple(lines)


def _executable_lines(
    text: str,
    filename: str,
) -> tuple[_ExecutableLine, ...] | None:
    """Return executable lines, or ``None`` when there is no such context.

    Shell scripts, Dockerfiles, and Makefiles/justfiles execute essentially
    every line. Workflow YAML exposes only its ``run:`` values. Everything
    else (documentation, prose, arbitrary YAML/JSON) returns ``None``.
    """
    suffix = Path(filename).suffix.lower()

    if suffix in _WORKFLOW_SUFFIXES:
        return _workflow_run_lines(text)

    if _shell_kind(filename) is None:
        return None

    return tuple(
        _ExecutableLine(number, line)
        for number, line in enumerate(text.splitlines(), start=1)
    )


def _is_comment_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith(("#", "//", "<!--"))


def _shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum(
        (count / length) * math.log2(count / length)
        for count in counts.values()
    )


def _looks_like_secret(value: str) -> bool:
    if len(value) < 16:
        return False
    if _PLACEHOLDER_VALUE_RE.match(value):
        return False
    if re.search(r"\s", value):
        return False
    return _shannon_entropy(value) >= 3.0


def _rm_is_recursive_and_force(line: str) -> bool:
    for match in _RM_RF_RE.finditer(line):
        recursive = False
        force = False
        for token in match.group(1).split():
            if token.startswith("--"):
                if token == "--recursive":
                    recursive = True
                elif token == "--force":
                    force = True
            elif token.startswith("-") and len(token) > 1:
                flags = token[1:]
                if "r" in flags or "R" in flags:
                    recursive = True
                if "f" in flags:
                    force = True
        if recursive and force:
            return True
    return False


def _ps_remove_is_recursive_and_force(line: str) -> bool:
    return bool(
        _PS_REMOVE_ITEM_RE.search(line)
        and _PS_RECURSE_RE.search(line)
        and _PS_FORCE_RE.search(line)
    )


def _git_destructive_match(line: str) -> str | None:
    if _GIT_FORCE_PUSH_RE.search(line):
        return "force push"
    if _GIT_RESET_HARD_RE.search(line):
        return "hard reset"
    if _GIT_BRANCH_DELETE_RE.search(line):
        return "branch delete"
    return None


def _is_dockerfile(filename: str) -> bool:
    lowered = filename.lower()
    return (
        lowered == "dockerfile"
        or lowered.startswith("dockerfile.")
        or lowered.endswith(".dockerfile")
    )


def _network_permission(text: str) -> str:
    host_match = _URL_HOST_RE.search(text)
    host = host_match.group(1) if host_match else "external"
    safe_host = re.sub(r"[^A-Za-z0-9_-]", "_", host).strip("_") or "external"
    return f"network:egress:{safe_host}"


# ---------------------------------------------------------------------------
# Matchers (pure; return line/detail/suggestion tuples)
# ---------------------------------------------------------------------------


def _match_env_present(
    path: str, text: str, filename: str
) -> list[tuple[int | None, str, Mapping[str, Any]]]:
    if not _is_env_file(filename):
        return []
    return [
        (
            None,
            f"Environment file '{filename}' is present in the scanned tree and "
            "may carry committed credentials.",
            {
                "resources": [
                    {
                        "name": "dotenv_secrets",
                        "resource": "dotenv_secrets",
                        "type": "secrets",
                        "access": "read",
                    }
                ]
            },
        )
    ]


def _match_env_secret(
    path: str, text: str, filename: str
) -> list[tuple[int | None, str, Mapping[str, Any]]]:
    if not _is_env_file(filename):
        return []

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"").strip()
        if not key or not _SECRET_KEY_RE.search(key):
            continue
        if not _looks_like_secret(value):
            continue

        return [
            (
                number,
                f"Key '{key}' in '{filename}' appears to hold a committed secret "
                "(value redacted). Rotate it and remove it from the repository.",
                {
                    "permissions": ["secrets:read"],
                    "approvals": [{"action": "secrets:read", "required": True}],
                },
            )
        ]
    return []


def _match_shell_delete(
    path: str, text: str, filename: str
) -> list[tuple[int | None, str, Mapping[str, Any]]]:
    executable = _executable_lines(text, filename)
    if executable is None:
        return []

    kind = _shell_kind(filename)
    for item in executable:
        line = item.text.strip()
        if not line or _is_comment_line(line):
            continue

        matched: str | None = None
        if kind in ("posix", "generic") and _rm_is_recursive_and_force(line):
            matched = "rm -rf"
        elif kind in ("powershell", "generic") and (
            _ps_remove_is_recursive_and_force(line)
        ):
            matched = "Remove-Item -Recurse -Force"
        elif kind in ("batch", "generic") and _DEL_RECURSIVE_RE.search(line):
            matched = "del /s"

        if matched is not None:
            return [
                (
                    item.number,
                    f"Destructive filesystem command '{matched}' found in '{filename}'.",
                    {
                        "side_effects": [
                            {
                                "type": "file_delete",
                                "resource": "workspace",
                                "irreversible": True,
                            }
                        ]
                    },
                )
            ]
    return []


def _match_git_destructive(
    path: str, text: str, filename: str
) -> list[tuple[int | None, str, Mapping[str, Any]]]:
    executable = _executable_lines(text, filename)
    if executable is None:
        return []

    for item in executable:
        line = item.text.strip()
        if not line or _is_comment_line(line):
            continue
        matched = _git_destructive_match(line)
        if matched is not None:
            return [
                (
                    item.number,
                    f"History-rewriting command '{matched}' found in '{filename}'.",
                    {
                        "permissions": ["git_ref:write"],
                        "approvals": [
                            {"action": "git_ref:write", "required": True}
                        ],
                    },
                )
            ]
    return []


def _match_piped_install(
    path: str, text: str, filename: str
) -> list[tuple[int | None, str, Mapping[str, Any]]]:
    executable = _executable_lines(text, filename)
    if executable is None:
        return []

    for item in executable:
        line = item.text.strip()
        if not line or _is_comment_line(line):
            continue
        if _CURL_PIPE_RE.search(line) or _IWR_PIPE_RE.search(line):
            return [
                (
                    item.number,
                    f"Remote install script is piped directly into an interpreter in '{filename}'.",
                    {
                        "side_effects": [
                            {
                                "type": "remote_execution",
                                "resource": "network",
                                "irreversible": True,
                            }
                        ]
                    },
                )
            ]
    return []


def _match_network_client(
    path: str, text: str, filename: str
) -> list[tuple[int | None, str, Mapping[str, Any]]]:
    if Path(filename).suffix.lower() not in _SOURCE_SUFFIXES:
        return []

    for number, raw in enumerate(text.splitlines(), start=1):
        if _is_comment_line(raw):
            continue
        match = _NET_LIB_RE.search(raw)
        if match is None:
            continue

        library = match.group(1) or "fetch"
        return [
            (
                number,
                f"Outbound network client '{library}' is used in '{filename}'.",
                {
                    "capabilities": [
                        {
                            "name": "outbound_network",
                            "description": f"Outbound network access via {library}",
                        }
                    ],
                    "permissions": [_network_permission(text)],
                },
            )
        ]
    return []


def _match_ci_write(
    path: str, text: str, filename: str
) -> list[tuple[int | None, str, Mapping[str, Any]]]:
    if Path(filename).suffix.lower() not in _WORKFLOW_SUFFIXES:
        return []

    write_all_line: int | None = None
    secret_line: int | None = None

    # Reuse the single workflow run-block parser so an inline ``run:`` cannot
    # leak its indentation into a following ``env:`` block (which would
    # misreport a safe secret reference as command-line interpolation).
    run_lines = _workflow_run_lines(text)
    run_line_numbers = {item.number for item in run_lines}

    for item in run_lines:
        if _SECRET_REF_RE.search(item.text):
            secret_line = item.number
            break

    for number, raw in enumerate(text.splitlines(), start=1):
        if number in run_line_numbers:
            continue

        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if _WRITE_ALL_RE.match(raw):
            write_all_line = number
            break

    if write_all_line is None and secret_line is None:
        return []

    issues: list[str] = []
    if write_all_line is not None:
        issues.append(f"'permissions: write-all' at line {write_all_line}")
    if secret_line is not None:
        issues.append(f"secret reference in a run block at line {secret_line}")

    return [
        (
            write_all_line if write_all_line is not None else secret_line,
            f"Workflow '{filename}' grants broad CI write access: "
            + "; ".join(issues)
            + ".",
            {
                "side_effects": [
                    {"type": "ci_deploy_write", "resource": "ci"}
                ]
            },
        )
    ]


def _match_ci_publish(
    path: str, text: str, filename: str
) -> list[tuple[int | None, str, Mapping[str, Any]]]:
    if Path(filename).suffix.lower() not in _WORKFLOW_SUFFIXES:
        return []

    for number, raw in enumerate(text.splitlines(), start=1):
        if _is_comment_line(raw):
            continue
        match = _CI_PUBLISH_RE.search(raw)
        if match is None:
            continue
        return [
            (
                number,
                f"Deploy/publish command '{match.group(0)}' found in '{filename}'.",
                {
                    "permissions": ["registry:publish"],
                    "approvals": [
                        {"action": "registry:publish", "required": True}
                    ],
                },
            )
        ]
    return []


def _match_docker_risk(
    path: str, text: str, filename: str
) -> list[tuple[int | None, str, Mapping[str, Any]]]:
    if not _is_dockerfile(filename):
        return []

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        risk: str | None = None
        if _DOCKER_PRIVILEGED_RE.search(line):
            risk = "--privileged"
        elif _DOCKER_SOCKET_RE.search(line):
            risk = "docker.sock mount"
        elif _DOCKER_ROOT_MOUNT_RE.search(line):
            risk = "root filesystem mount"

        if risk is not None:
            return [
                (
                    number,
                    f"Dockerfile '{filename}' requests host-level access ({risk}).",
                    {
                        "side_effects": [
                            {"type": "host_mount", "resource": "host"}
                        ]
                    },
                )
            ]
    return []


def _match_n8n_external_write(
    path: str, text: str, filename: str
) -> list[tuple[int | None, str, Mapping[str, Any]]]:
    if filename.lower() != "workflow.json":
        return []

    lowered = text.lower()
    for node_type in _N8N_RISK_NODE_TYPES:
        index = lowered.find(node_type)
        if index == -1:
            continue
        line = text.count("\n", 0, index) + 1
        return [
            (
                line,
                f"n8n workflow '{filename}' contains an external-write node "
                f"('{node_type}').",
                {
                    "side_effects": [
                        {
                            "type": "external_api_write",
                            "resource": "external_api",
                        }
                    ]
                },
            )
        ]
    return []


def _match_unpinned_dependencies(
    path: str, text: str, filename: str
) -> list[tuple[int | None, str, Mapping[str, Any]]]:
    if _REQUIREMENTS_RE.match(filename) is None:
        return []

    unpinned = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.split(" #", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        requirement = line.split(";", 1)[0].strip()
        if not requirement:
            continue
        if "==" in requirement:
            continue
        unpinned += 1

    if unpinned < 25:
        return []

    return [
        (
            None,
            f"Dependency manifest '{filename}' has {unpinned} dependencies "
            "without an exact version pin.",
            {
                "observability": {
                    "level": "audit",
                    "sinks": ["dependency_audit"],
                }
            },
        )
    ]


# ---------------------------------------------------------------------------
# Flat, append-only registry (RFC 0004 §3)
# ---------------------------------------------------------------------------

RULES: list[AuditRule] = [
    _rule(
        "AU-ENV-001",
        "medium",
        "dotenv secrets file present",
        _match_env_present,
    ),
    _rule(
        "AU-ENV-002",
        "critical",
        "secret committed in env file",
        _match_env_secret,
    ),
    _rule(
        "AU-SH-001",
        "critical",
        "recursive delete in shell script",
        _match_shell_delete,
    ),
    _rule(
        "AU-GIT-001",
        "high",
        "destructive git operation",
        _match_git_destructive,
    ),
    _rule(
        "AU-NET-001",
        "critical",
        "install-script execution (remote script piped to shell)",
        _match_piped_install,
    ),
    _rule(
        "AU-NET-002",
        "medium",
        "outbound network calls in source",
        _match_network_client,
    ),
    _rule(
        "AU-CI-001",
        "high",
        "workflow grants write-all or exposes secrets in run",
        _match_ci_write,
    ),
    _rule(
        "AU-CI-002",
        "high",
        "deploy or publish job detected",
        _match_ci_publish,
    ),
    _rule(
        "AU-DOC-001",
        "high",
        "privileged container or risky host mount",
        _match_docker_risk,
    ),
    _rule(
        "AU-N8N-001",
        "medium",
        "n8n workflow with external writes",
        _match_n8n_external_write,
    ),
    _rule(
        "AU-DEP-001",
        "low",
        "unpinned dependency manifest",
        _match_unpinned_dependencies,
    ),
]
