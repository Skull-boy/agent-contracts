"""Unified report envelope for every Scyvera evidence mode (roadmap M2.5).

RFC 0003 §C3/C4 define four independent evidence producers: the RFC 0004
Blast Radius audit, the tier 0/1/2 conformance checks, and the trace-driven
eval harness. This module adds one *additive* envelope so CI and downstream
tooling can consume the same top-level shape from all of them without changing
any producer's published output::

    {
      "report_version": 1,
      "tool": "scyvera",
      "mode": "audit" | "check-tier0" | "check-tier1" | "check-tier2" | "eval",
      "status": "PASS" | "WARN" | "FAIL",
      "subject": "<scanned path | contract path | eval case name>",
      "summary": { ...mode summary... },
      "findings": [
        {"id", "severity", "title", "message", "path", "node_id"}, ...
      ],
      "data": { ...the mode's FULL existing payload, unchanged... }
    }

The envelope is a projection, never a rewrite. ``audit --json``,
``render_check()``, and :meth:`scyvera.evals.EvalResult.to_json` keep their
existing bytes; the unified shape is reached through ``--unified`` (audit and
check) and ``eval --json``, or through the pure functions below.

Normalization rules (pinned by ``tests/test_report_shape.py``):

- Finding severity is normalized to the audit vocabulary
  (``critical``/``high``/``medium``/``low``/``info``). Schema/validation and
  tier 1 ``error`` findings map to ``high``; lint warnings and tier 1 warnings
  map to ``low``; eval warnings map to ``info``. Every source's original
  severity remains visible in ``data``.
- Findings are ordered by severity, then id, then path, then node id, title,
  and message. Identical input therefore produces identical bytes.
- No timestamp, hostname, or wall-clock value is emitted anywhere.

Status mapping:

===============  ==========================================================
Mode             Rule
===============  ==========================================================
audit            ``FAIL`` when ``--fail-under`` is breached; ``WARN`` when
                 any finding is present (scored or quarantined) without a
                 breach; ``PASS`` when the report carries no findings.
check-tier0      ``FAIL`` when schema validation or an error-severity ACxxx
                 fires; ``WARN`` for soft warnings only; ``PASS`` otherwise.
check-tier1      ``FAIL`` when ``tier1_failed`` is true (T101 or error T102);
                 ``WARN`` for T103-only findings or soft warnings; ``PASS``
                 when clean. ``tier_note`` is preserved in ``summary``.
check-tier2      Representable in the schema; no adapter ships, so the CLI
                 keeps its loud exit-2 refusal instead of fabricating a pass.
eval             ``FAIL`` when ``expected_ok`` is false; ``WARN`` otherwise.
===============  ==========================================================
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.resources
import json
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids import cycles
    from .conformance import CheckReport
    from .evals.runner import EvalResult

__all__ = [
    "MODES",
    "REPORT_SCHEMA_VERSION",
    "REPORT_STATUSES",
    "SEVERITIES",
    "UNIFIED_REPORT_SCHEMA_PATH",
    "UnifiedFinding",
    "UnifiedReport",
    "UnifiedReportError",
    "audit_status",
    "check_status",
    "eval_status",
    "from_audit_report",
    "from_check_report",
    "from_eval_result",
    "load_report_schema",
]

#: Envelope schema version (independent of the contract schema versions).
REPORT_SCHEMA_VERSION: int = 1

#: Envelope producer name; pinned in the schema as a constant.
TOOL_NAME: str = "scyvera"

#: Every mode the schema can represent, in canonical order.
MODES: tuple[str, ...] = (
    "audit",
    "check-tier0",
    "check-tier1",
    "check-tier2",
    "eval",
)

#: The three verdicts every mode maps onto.
REPORT_STATUSES: tuple[str, ...] = ("PASS", "WARN", "FAIL")

#: Normalized finding severities (the audit vocabulary plus ``info``).
SEVERITIES: tuple[str, ...] = ("critical", "high", "medium", "low", "info")

_SEVERITY_RANK: Mapping[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}

UNIFIED_REPORT_SCHEMA_RELATIVE_PATH = "schemas/report/v1/unified-report.schema.json"


def _resolve_package_schema(relative_path: str) -> Path:
    """Resolve the packaged report schema using ``importlib.resources``."""
    try:
        traversable = importlib.resources.files("scyvera").joinpath(relative_path)
        candidate = Path(str(traversable))
        if candidate.exists():
            return candidate
    except Exception:  # pragma: no cover - defensive fallback
        pass
    return Path(__file__).resolve().parent / relative_path


#: Packaged unified-report JSON Schema location.
UNIFIED_REPORT_SCHEMA_PATH: Path = _resolve_package_schema(
    UNIFIED_REPORT_SCHEMA_RELATIVE_PATH
)


class UnifiedReportError(ValueError):
    """Raised when a unified envelope cannot be built.

    ``ValueError`` is the house base for parse/validation failures (see
    :class:`scyvera.exceptions.TraceError` and
    :class:`scyvera.guardrails.GuardrailConfigError`), so callers can reject
    bad input without importing this module's internals.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


def load_report_schema(
    path: str | Path = UNIFIED_REPORT_SCHEMA_PATH,
) -> dict[str, Any]:
    """Load the unified-report JSON Schema from ``path``.

    Args:
        path: Schema path; defaults to the packaged copy.

    Returns:
        The parsed schema as a mapping.

    Raises:
        FileNotFoundError: The schema file does not exist.
        json.JSONDecodeError: The schema is not valid JSON.
    """
    schema_path = Path(path)
    with schema_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _require_str(value: Any, field: str, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise UnifiedReportError(
            f"unified field '{field}' must be a string, got "
            f"{type(value).__name__}"
        )
    if not allow_empty and not value:
        raise UnifiedReportError(
            f"unified field '{field}' must be a non-empty string"
        )
    return value


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise UnifiedReportError(
            f"unified field '{field}' must be a mapping, got "
            f"{type(value).__name__}"
        )
    return value


@dataclass(frozen=True)
class UnifiedFinding:
    """One normalized finding in the shared envelope.

    Attributes:
        id: Producer finding id (``AU-NET-002``, ``AC101``, ``T101``,
            ``AC000`` for schema errors, or ``EVAL`` for eval warnings).
        severity: ``critical``, ``high``, ``medium``, ``low``, or ``info``.
        title: Short human-readable title.
        message: One-line explanation.
        path: Source path, or the contract path for contract-level findings.
        node_id: Workflow node id, or ``""`` when the finding is not about a
            node (the same convention as :class:`scyvera.conformance.Tier1Finding`).
    """

    id: str
    severity: str
    title: str
    message: str
    path: str
    node_id: str = ""

    def __post_init__(self) -> None:
        _require_str(self.id, "id", allow_empty=False)
        if self.severity not in SEVERITIES:
            raise UnifiedReportError(
                f"unified finding severity must be one of {list(SEVERITIES)}, "
                f"got {self.severity!r}"
            )
        _require_str(self.title, "title")
        _require_str(self.message, "message")
        _require_str(self.path, "path")
        _require_str(self.node_id, "node_id")

    def to_dict(self) -> dict[str, Any]:
        """Return the exact six-key finding record."""
        return {
            "id": self.id,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "path": self.path,
            "node_id": self.node_id,
        }


@dataclass(frozen=True)
class UnifiedReport:
    """The additive report envelope shared by audit, check, and eval.

    ``summary`` is a small mode-specific digest; ``data`` is the producer's
    full existing payload, preserved key-by-value. Findings are normalized and
    sorted in :meth:`__post_init__`, so construction order can never leak into
    the serialized bytes.
    """

    mode: str
    status: str
    subject: str
    summary: Mapping[str, Any]
    findings: tuple[UnifiedFinding, ...]
    data: Mapping[str, Any]
    report_version: int = REPORT_SCHEMA_VERSION
    tool: str = TOOL_NAME

    def __post_init__(self) -> None:
        if self.report_version != REPORT_SCHEMA_VERSION:
            raise UnifiedReportError(
                "unified report_version must be "
                f"{REPORT_SCHEMA_VERSION}, got {self.report_version!r}"
            )
        if self.tool != TOOL_NAME:
            raise UnifiedReportError(
                f"unified tool must be {TOOL_NAME!r}, got {self.tool!r}"
            )
        if self.mode not in MODES:
            raise UnifiedReportError(
                f"unified mode must be one of {list(MODES)}, got {self.mode!r}"
            )
        if self.status not in REPORT_STATUSES:
            raise UnifiedReportError(
                "unified status must be one of "
                f"{list(REPORT_STATUSES)}, got {self.status!r}"
            )
        _require_str(self.subject, "subject", allow_empty=False)
        _require_mapping(self.summary, "summary")
        _require_mapping(self.data, "data")

        findings = tuple(self.findings)
        for finding in findings:
            if not isinstance(finding, UnifiedFinding):
                raise UnifiedReportError(
                    "unified findings must be UnifiedFinding values, got "
                    f"{type(finding).__name__}"
                )
        object.__setattr__(
            self,
            "findings",
            tuple(
                sorted(
                    findings,
                    key=lambda item: (
                        _SEVERITY_RANK[item.severity],
                        item.id,
                        item.path,
                        item.node_id,
                        item.title,
                        item.message,
                    ),
                )
            ),
        )
        object.__setattr__(self, "summary", MappingProxyType(dict(self.summary)))
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical eight-key envelope as a plain mapping."""
        return {
            "report_version": self.report_version,
            "tool": self.tool,
            "mode": self.mode,
            "status": self.status,
            "subject": self.subject,
            "summary": dict(self.summary),
            "findings": [finding.to_dict() for finding in self.findings],
            "data": dict(self.data),
        }

    def to_json(self) -> str:
        """Serialize deterministically: sorted keys, fixed separators.

        No timestamp is included, so identical input produces byte-identical
        output across processes and platforms.
        """
        return json.dumps(
            self.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )


# ---------------------------------------------------------------------------
# Status mappings (Task A-2)
# ---------------------------------------------------------------------------


def audit_status(payload: Mapping[str, Any], threshold: int | None = None) -> str:
    """Map an audit payload to ``PASS`` / ``WARN`` / ``FAIL``.

    ``FAIL`` requires an explicit ``--fail-under`` breach. Any finding
    (scored or fixture-quarantined) without a breach is ``WARN``; a report
    with no findings at all is ``PASS``, matching the audit renderer's
    clean-run line.
    """
    if not isinstance(payload, Mapping):
        raise UnifiedReportError(
            f"audit payload must be a mapping, got {type(payload).__name__}"
        )
    score = payload.get("score")
    if threshold is not None:
        numeric_score = score if isinstance(score, (int, float)) else 0
        if numeric_score < threshold:
            return "FAIL"
    findings = payload.get("findings") or []
    return "WARN" if findings else "PASS"


def check_status(report: "CheckReport") -> str:
    """Map a :class:`CheckReport` to ``PASS`` / ``WARN`` / ``FAIL``.

    FAIL: tier 0 invalid (schema or error-severity ACxxx) or a failing tier 1
    finding (``T101`` / error ``T102``). WARN: soft warnings or T103-only
    findings. PASS: clean.
    """
    if not report.valid or report.error_warnings:
        return "FAIL"
    if report.tier1_failed:
        return "FAIL"
    if report.tier1_findings or report.soft_warnings:
        return "WARN"
    return "PASS"


def eval_status(result: "EvalResult") -> str:
    """Map an :class:`EvalResult` to ``WARN`` or ``FAIL``.

    The eval harness has no PASS verdict in the unified envelope: a run that
    matches ``expected_trace`` is a warning-grade artifact (it is a measurement,
    not a certification), and a mismatch is a failure.
    """
    return "WARN" if result.expected_ok else "FAIL"


# ---------------------------------------------------------------------------
# Finding normalization (Task A-3)
# ---------------------------------------------------------------------------


def _audit_findings(payload: Mapping[str, Any]) -> tuple[UnifiedFinding, ...]:
    findings: list[UnifiedFinding] = []
    for entry in payload.get("findings") or []:
        if not isinstance(entry, Mapping):
            continue
        severity = entry.get("severity")
        normalized = severity if severity in SEVERITIES else "info"
        findings.append(
            UnifiedFinding(
                id=str(entry.get("rule_id") or "AU-UNKNOWN"),
                severity=normalized,
                title=str(entry.get("title") or "Audit finding"),
                message=str(entry.get("detail") or ""),
                path=str(entry.get("path") or ""),
            )
        )
    return tuple(findings)


def _check_findings(report: "CheckReport") -> tuple[UnifiedFinding, ...]:
    findings: list[UnifiedFinding] = []
    for error in report.validation_errors:
        message = f"{error.path}: {error.message}" if error.path else error.message
        findings.append(
            UnifiedFinding(
                id="AC000",
                severity="high",
                title="Contract schema error",
                message=message,
                path=report.contract_path,
            )
        )
    for warning in report.warnings:
        findings.append(
            UnifiedFinding(
                id=warning.rule_id,
                severity="high" if warning.severity == "error" else "low",
                title=warning.title,
                message=warning.message,
                path=report.contract_path,
            )
        )
    for finding in report.tier1_findings:
        findings.append(
            UnifiedFinding(
                id=finding.code,
                severity="high" if finding.severity == "error" else "low",
                title=finding.title,
                message=finding.message,
                path=finding.path,
                node_id=finding.node_id,
            )
        )
    return tuple(findings)


def _eval_findings(result: "EvalResult") -> tuple[UnifiedFinding, ...]:
    return tuple(
        UnifiedFinding(
            id="EVAL",
            severity="info",
            title="Eval warning",
            message=warning,
            path="",
        )
        for warning in result.warnings
    )


# ---------------------------------------------------------------------------
# Projections (Task A-4)
# ---------------------------------------------------------------------------


def from_audit_report(
    payload: dict[str, Any],
    *,
    subject: str,
    status: str,
) -> UnifiedReport:
    """Project an RFC 0004 audit payload into the unified envelope.

    Args:
        payload: The exact mapping produced by
            :meth:`scyvera.audit.AuditReport.to_dict`, optionally with the
            published ``badge`` / ``draft_path`` keys.
        subject: Scanned path to carry as the envelope subject.
        status: Verdict from :func:`audit_status`.

    Returns:
        A frozen :class:`UnifiedReport` whose ``data`` is the payload
        key-by-value.
    """
    data = _require_mapping(payload, "payload")
    stats = data.get("stats") or {}
    if not isinstance(stats, Mapping):
        stats = {}
    findings = data.get("findings") or []
    if not isinstance(findings, list):
        findings = []
    scored = sum(
        1
        for entry in findings
        if not (isinstance(entry, Mapping) and entry.get("scored") is False)
    )
    summary = {
        "score": data.get("score"),
        "band": data.get("band"),
        "files_scanned": stats.get("files_scanned", 0),
        "files_skipped": stats.get("files_skipped", 0),
        "findings": dict(stats.get("findings") or {}),
        "draft_available": bool(data.get("draft_available", False)),
        "scored_findings": scored,
        "quarantined_findings": len(findings) - scored,
    }
    return UnifiedReport(
        mode="audit",
        status=status,
        subject=subject,
        summary=summary,
        findings=_audit_findings(data),
        data=dict(data),
    )


def from_check_report(report: "CheckReport") -> UnifiedReport:
    """Project a :class:`CheckReport` into the unified envelope.

    The report's additive ``to_dict()`` payload becomes ``data``; nothing in
    :func:`scyvera.conformance.render_check` or the tier resolution path is
    touched.
    """
    mode = f"check-tier{int(report.tier)}"
    summary = {
        "tier": int(report.tier),
        "tier_note": report.tier_note,
        "valid": report.valid,
        "schema_errors": len(report.validation_errors),
        "lint_warnings": len(report.warnings),
        "error_warnings": len(report.error_warnings),
        "tier1_findings": len(report.tier1_findings),
        "tier1_failed": report.tier1_failed,
    }
    return UnifiedReport(
        mode=mode,
        status=check_status(report),
        subject=report.contract_path,
        summary=summary,
        findings=_check_findings(report),
        data=report.to_dict(),
    )


def from_eval_result(result: "EvalResult") -> UnifiedReport:
    """Project an :class:`EvalResult` into the unified envelope.

    ``EvalResult.to_dict()`` is reused unchanged as ``data``; the summary
    carries the total and the four axis scores.
    """
    data = result.to_dict()
    summary = {
        "total": result.total,
        "axes": result.axes.as_dict(),
        "expected_ok": result.expected_ok,
        "trace_entries": len(result.trace.entries),
        "warnings": len(result.warnings),
    }
    return UnifiedReport(
        mode="eval",
        status=eval_status(result),
        subject=result.name,
        summary=summary,
        findings=_eval_findings(result),
        data=data,
    )
