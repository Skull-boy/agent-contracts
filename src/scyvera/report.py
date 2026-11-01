"""Human-facing renderers for the Blast Radius report (RFC 0004 §2, §4).

The audit engine in :mod:`scyvera.audit` scans; this module formats. Renderers
are pure functions over an :class:`~scyvera.audit.AuditReport`: they perform no
I/O, keep no global state, and return strings. Future formats (Markdown,
GitHub Action annotations) can therefore be added without threading
presentation through the scan engine.

Version 1 deliberately emits no ANSI color. The report is designed to be
pasted into issues, pull requests, and CI logs where escape sequences are
noise; color is a later, opt-in feature, not an oversight.
"""
from __future__ import annotations

import sys
from types import MappingProxyType
from typing import Mapping

from .audit import FILE_KINDS, AuditReport
from .audit_rules import Finding


__all__ = ["BAND_COLORS", "render_badge", "render_report"]


_PINNED_DASH = "\u2014"  # RFC 0004 §2 pins an em dash.
_ASCII_DASH = "->"
_INDENT = " " * 6
_SEVERITY_WIDTH = len("CRITICAL")
_DETAIL_INDENT = " " * (len(_INDENT) + _SEVERITY_WIDTH + 2)
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

_KIND_ORDER = FILE_KINDS
_KIND_LABELS: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "manifests": ("manifest", "manifests"),
        "workflows": ("workflow file", "workflow files"),
        "source": ("source file", "source files"),
        "shell": ("shell script", "shell scripts"),
        "containers": ("container file", "container files"),
        "env": ("env file", "env files"),
        "docs": ("doc file", "doc files"),
        "other": ("other file", "other files"),
    }
)

#: Shields.io color per Blast Radius band (RFC 0004 §4, §10.3).
BAND_COLORS: Mapping[str, str] = MappingProxyType(
    {
        "Shielded": "green",
        "Controlled": "yellow",
        "Exposed": "orange",
        "Unbounded": "red",
    }
)


def _resolve_encoding(encoding: str | None) -> str:
    """Resolve the target encoding, falling back to UTF-8 when unknown."""
    candidate = encoding or getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        "".encode(candidate)
    except LookupError:
        return "utf-8"
    return candidate


def _dash_for(encoding: str) -> str:
    """Return the pinned em dash when ``encoding`` can represent it."""
    try:
        _PINNED_DASH.encode(encoding)
    except UnicodeEncodeError:
        return _ASCII_DASH
    return _PINNED_DASH


def _make_encodable(text: str, encoding: str) -> str:
    """Return ``text`` in ``encoding`` without ever raising an encode error.

    The pinned layout is attempted first. Only characters the stream cannot
    represent are replaced, so a narrow Windows codepage still renders a
    usable report instead of crashing the CLI.
    """
    try:
        text.encode(encoding)
    except UnicodeEncodeError:
        return text.encode(encoding, errors="replace").decode(encoding)
    return text


def _counted(count: int, single: str, plural: str) -> str:
    return f"{count} {single if count == 1 else plural}"


def _breakdown_parts(file_kinds: Mapping[str, int]) -> list[str]:
    parts: list[str] = []

    for kind in _KIND_ORDER:
        count = file_kinds.get(kind, 0)
        if count <= 0:
            continue
        single, plural = _KIND_LABELS[kind]
        parts.append(_counted(count, single, plural))

    for kind in sorted(file_kinds):
        if kind in _KIND_ORDER:
            continue
        count = file_kinds[kind]
        if count > 0:
            parts.append(_counted(count, kind, f"{kind}s"))

    return parts


def _scanned_line(report: AuditReport) -> str:
    files = int(report.stats.get("files_scanned", 0))
    line = f"{_INDENT}Scanned {_counted(files, 'file', 'files')}"
    breakdown = _breakdown_parts(report.file_kinds)
    if breakdown:
        line += f" ({', '.join(breakdown)})"
    return line


def _finding_rows(scored: list[Finding]) -> list[str]:
    ordered = sorted(
        scored,
        key=lambda finding: (
            _SEVERITY_RANK.get(finding.severity, len(_SEVERITY_RANK)),
            finding.rule_id,
            finding.path,
            finding.line if finding.line is not None else 0,
        ),
    )

    # Collapse repeated findings of the same rule and title. The first
    # location is the deterministic representative; the count keeps the
    # multiplicity visible without flooding the terminal.
    groups: dict[tuple[str, str], list[Finding]] = {}
    for finding in ordered:
        groups.setdefault((finding.rule_id, finding.title), []).append(finding)

    rows: list[str] = []
    for (rule_id, title), group in groups.items():
        severity = group[0].severity.upper()
        rows.append(
            f"{_INDENT}{severity:<{_SEVERITY_WIDTH}}  [{rule_id}] {title}"
        )

        first = group[0]
        location = first.path
        if first.line is not None:
            location += f":{first.line}"
        if len(group) > 1:
            location += f" + {len(group) - 1} more"
        rows.append(f"{_DETAIL_INDENT}{location}")

    return rows


def render_report(
    report: AuditReport,
    *,
    encoding: str | None = None,
) -> str:
    """Render the band-first terminal report for ``report`` (RFC 0004 §2).

    Only scored findings are rendered, ordered by severity (descending), rule
    id, and path. Findings that share a rule id and title collapse into one
    row with a deterministic ``+ N more`` suffix.

    ``encoding`` defaults to the encoding of the attached stdout. When that
    encoding cannot represent the pinned em dash, the renderer emits ``->``
    instead and guarantees the returned string is encodable, so a narrow
    Windows codepage can never crash the CLI.
    """
    resolved = _resolve_encoding(encoding)
    dash = _dash_for(resolved)
    scored = [finding for finding in report.findings if finding.scored]

    if not scored:
        text = (
            f"PASS  {report.target} {dash} exploit risk none "
            f"(score {report.score}/100)"
        )
        return _make_encodable(text, resolved)

    status = (
        "FAIL"
        if any(finding.severity == "critical" for finding in scored)
        else "WARN"
    )

    lines = [
        f"{status}  {report.target}",
        f"{_INDENT}Blast Radius: {report.score}/100 ({report.band})",
        _scanned_line(report),
        "",
        *_finding_rows(scored),
        "",
        f"{_INDENT}With a contract: force-push -> requires approval; "
        ".env -> unread;",
        f"{_INDENT}npm publish -> forbidden.  "
        "Run with --generate to draft one.",
    ]
    return _make_encodable("\n".join(lines), resolved)


def render_badge(report: AuditReport) -> str:
    """Return the band-only shields.io badge for ``report`` (RFC 0004 §4).

    The badge carries the band, never the numeric score, so future scoring
    refinements do not make badges published by users flap (RFC 0004 §10.3).
    """
    try:
        color = BAND_COLORS[report.band]
    except KeyError:
        raise ValueError(
            f"unknown Blast Radius band: {report.band!r}"
        ) from None

    return (
        f"[![Blast Radius: {report.band}]"
        f"(https://img.shields.io/badge/blast%20radius-{report.band}-{color})]"
        "(scyvera)"
    )
