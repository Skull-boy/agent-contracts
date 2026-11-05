"""Conformance checking across the RFC 0003 §C3 check tiers.

RFC 0003 §C3 formalizes what it means for an implementation to conform to
its contract in three independently shippable tiers:

- **Tier 0 — Structural**: PASS/FAIL of ``contract.yaml`` against the JSON
  Schema plus the ACxxx semantic lint. Declaration conformance; this tier is
  a thin alias over the existing ``scyvera validate`` + ``scyvera lint``
  behavior, exposed as one combined report (roadmap task M2.1).
- **Tier 1 — Static Declared vs Code**: conformance-by-inspection over
  implementation source (roadmap M2.2/M2.3, not implemented in this release).
- **Tier 2 — Runtime Trace**: conformance-by-measurement over an execution
  trace (roadmap M2.4, not implemented in this release).

Tier resolution never degrades silently: ``tier="auto"`` resolves to the
highest implemented tier and carries an explicit note in the report, and
requesting an unimplemented tier explicitly raises
:class:`TierNotImplementedError` (mapped to exit code 2 by the CLI) rather
than producing a plausible-looking pass.

Rendering follows the scan/format split established in
:mod:`scyvera.report`: ``check_contract`` gathers, ``render_check`` formats,
and neither writes to the filesystem nor prints.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from .linter import LintWarning, lint_contract
from .validator import ValidationError, validate_contract

__all__ = [
    "CheckReport",
    "CheckTier",
    "ConformanceError",
    "TierNotImplementedError",
    "check_contract",
    "render_check",
    "resolve_tier",
]


class ConformanceError(Exception):
    """Base error for the RFC 0003 §C3 conformance layer."""


class TierNotImplementedError(ConformanceError):
    """A conformance tier was requested before its implementation ships.

    Tier 1 implementations land with roadmap tasks M2.2/M2.3 and Tier 2 with
    M2.4. Until then, both must fail loudly (per the fail-closed philosophy
    and the RFC 0003 §C3 "never silently" rule) instead of fabricating a
    plausible pass.
    """


class CheckTier(enum.IntEnum):
    """Conformance tier identifiers (RFC 0003 §C3).

    ``auto`` from the CLI (and roadmap M2.1) is a *resolution policy*, not a
    tier, so it never appears here; use :func:`resolve_tier`.
    """

    STRUCTURAL = 0
    STATIC = 1
    TRACE = 2

    def __str__(self) -> str:
        names = {
            CheckTier.STRUCTURAL: "structural",
            CheckTier.STATIC: "static",
            CheckTier.TRACE: "runtime-trace",
        }
        return f"{int(self)} ({names[self]})"


@dataclass(frozen=True)
class CheckReport:
    """Result of one conformance check run over a single contract.

    ``valid`` is the Tier 0 PASS/FAIL verdict: schema validation passed and
    no ``error``-severity lint finding (AC000 structural breakdown) fired.
    Soft ACxxx warnings do not flip the verdict — they keep the report at
    ``WARN`` with exit code 0, exactly like ``scyvera lint`` treats them, so
    the combined check remains a strict superset of both source commands.
    """

    contract_path: str
    tier: CheckTier
    tier_note: str | None
    valid: bool
    validation_errors: tuple[ValidationError, ...]
    warnings: tuple[LintWarning, ...]

    @property
    def error_warnings(self) -> tuple[LintWarning, ...]:
        """Lint findings carrying ``severity="error"`` (e.g. AC000)."""
        return tuple(w for w in self.warnings if w.severity == "error")

    @property
    def soft_warnings(self) -> tuple[LintWarning, ...]:
        """Lint findings with plain ``severity="warning"``."""
        return tuple(w for w in self.warnings if w.severity != "error")


def resolve_tier(tier: str | CheckTier | None) -> tuple[CheckTier, str | None]:
    """Resolve a requested tier into ``(implemented_tier, note)``.

    - Explicit ``0`` / ``CheckTier.STRUCTURAL`` resolves as itself, with no
      note.
    - ``auto`` (also ``None``) resolves to the highest implemented tier and
      returns an explicit note so the degradation is always visible (RFC 0003
      §C3: "never silently").
    - Explicit ``1`` / ``2`` raise :class:`TierNotImplementedError` until
      their roadmap tasks (M2.2/M2.3/M2.4) ship.

    Raises:
        TierNotImplementedError: When an unimplemented tier is requested
            explicitly.
        ValueError: When ``tier`` is not a recognized specification.
    """
    if tier is None or (isinstance(tier, str) and tier.strip().lower() == "auto"):
        note = (
            "--tier auto resolved to tier 0 (structural); tiers 1 (static) "
            "and 2 (runtime-trace) are not yet implemented (roadmap M2.2, M2.4)"
        )
        return CheckTier.STRUCTURAL, note

    if isinstance(tier, CheckTier):
        requested = tier
    elif isinstance(tier, str) and str(tier) in {"0", "1", "2"}:
        requested = CheckTier(int(str(tier)))
    else:
        raise ValueError(
            f"unknown tier {tier!r}; expected one of 0, 1, 2, auto "
            "(or a CheckTier instance)"
        )

    if requested is CheckTier.STATIC:
        raise TierNotImplementedError(
            "tier 1 (static declared-vs-code) is not implemented yet; "
            "it ships with roadmap tasks M2.2/M2.3. Use --tier 0 or "
            "--tier auto."
        )
    if requested is CheckTier.TRACE:
        raise TierNotImplementedError(
            "tier 2 (runtime-trace) is not implemented yet; it ships "
            "with roadmap task M2.4. Use --tier 0 or --tier auto."
        )
    return requested, None


def check_contract(
    contract_path: str | Path,
    *,
    schema_path: str | Path | None = None,
    tier: str | CheckTier | None = "auto",
) -> CheckReport:
    """Run a conformance check over one Agent Contract file.

    Tier 0 (the only implemented tier) calls
    :func:`scyvera.validator.validate_contract` and
    :func:`scyvera.linter.lint_contract` on the same file — the literal
    union of ``scyvera validate`` and ``scyvera lint`` — and combines both
    result sets into one :class:`CheckReport` so the report is a superset
    of the two commands. Filesystem exceptions (``FileNotFoundError``,
    ``PermissionError``, ``yaml.YAMLError``, ``ContractFileNameError``)
    propagate untouched, exactly as in the individual commands;
    presentation stays in the CLI (RFC 0003 §C3 keeps the CLI a thin alias).

    Args:
        contract_path: Path to the contract file (``.yaml`` only, matching
            ``scyvera validate``).
        schema_path: Optional custom JSON Schema path, passed through to the
            validator.
        tier: Requested tier (``"auto"``, ``"0"``, ``"1"``, ``"2"`` or a
            :class:`CheckTier`). See :func:`resolve_tier` for resolution
            semantics.

    Returns:
        The combined :class:`CheckReport` for the requested tier.

    Raises:
        TierNotImplementedError: When an unimplemented tier (1 or 2) is
            requested explicitly.
        ValueError: When ``tier`` is not a recognized specification.
    """
    resolved_tier, tier_note = resolve_tier(tier)

    validation_result = validate_contract(contract_path, schema_path=schema_path)
    lint_result = lint_contract(contract_path)

    valid = validation_result.valid and lint_result.valid_structure and not any(
        warning.severity == "error" for warning in lint_result.warnings
    )

    return CheckReport(
        contract_path=str(contract_path),
        tier=resolved_tier,
        tier_note=tier_note,
        valid=valid,
        validation_errors=validation_result.errors,
        warnings=lint_result.warnings,
    )


def _status_line(report: CheckReport) -> str:
    """Build the first line of the rendered report (house PASS/WARN/FAIL)."""
    if not report.valid:
        return (
            f"FAIL  {report.contract_path} (tier {report.tier}: "
            "schema validation + ACxxx lint)"
        )
    if report.soft_warnings:
        return (
            f"WARN  {report.contract_path} (tier {report.tier}: "
            f"{len(report.soft_warnings)} semantic warning(s))"
        )
    return (
        f"PASS  {report.contract_path} (tier {report.tier}: "
        "0 schema errors, 0 semantic warnings)"
    )


def render_check(report: CheckReport, *, encoding: str | None = None) -> str:
    """Render a :class:`CheckReport` as the terminal ``scyvera check`` text.

    Pure function: reads the report, returns a multi-line string, and never
    touches the filesystem or stdout. Output shape mirrors the CLI house
    style used by ``run_validate``/``run_lint`` — one ``PASS``/``WARN``/
    ``FAIL`` status line, an optional ``note:`` line whenever the tier was
    auto-resolved, then 6-space-indented detail lines (schema errors first,
    then ACxxx lint findings). All output is ASCII, so the report is safe
    on narrow codepages; the ``encoding`` parameter exists to keep the
    signature symmetric with :func:`scyvera.report.render_report` and is
    reserved for the unified report format (roadmap M2.5).

    Args:
        report: The :class:`CheckReport` to render.
        encoding: Reserved for renderer parity with the audit report; v1
            output never emits non-ASCII, so nothing is substituted.

    Returns:
        The rendered report, ending in a newline.
    """
    del encoding  # v1 output is ASCII-only; kept for renderer parity.

    lines = [_status_line(report)]
    if report.tier_note:
        lines.append(f"      note: {report.tier_note}")
    for error in report.validation_errors:
        if error.path:
            lines.append(f"      {error.path}: {error.message}")
        else:
            lines.append(f"      {error.message}")
    for warning in report.warnings:
        lines.append(f"      [{warning.rule_id}] {warning.title}: {warning.message}")
    return "\n".join(lines) + "\n"
