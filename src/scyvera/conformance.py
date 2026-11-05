"""Conformance checking across the RFC 0003 §C3 check tiers.

RFC 0003 §C3 formalizes what it means for an implementation to conform to
its contract in three independently shippable tiers:

- **Tier 0 — Structural**: PASS/FAIL of ``contract.yaml`` against the JSON
  Schema plus the ACxxx semantic lint. Declaration conformance; this tier is
  a thin alias over the existing ``scyvera validate`` + ``scyvera lint``
  behavior, exposed as one combined report (roadmap task M2.1).
- **Tier 1 — Static Declared vs Code**: conformance-by-inspection over
  implementation source (roadmap M2.2/M2.3). This module owns the shared
  :class:`Tier1Adapter` interface; each framework ships one adapter (the
  first is ``implementations/n8n/tier1.py``).
- **Tier 2 — Runtime Trace**: conformance-by-measurement over an execution
  trace (roadmap M2.4, not implemented in this release).

Tier 1 finding taxonomy (RFC 0003 §C3 row "Tier 1"):

- ``T101`` **undeclared action** (error): the implementation performs an
  external action for which the contract declares no permission or side
  effect.
- ``T102`` **ungated call** (error): the contract declares an approval /
  gateway gate, yet an externally-reaching write is reachable from a trigger
  without traversing any gate node.
- ``T103`` **unused declaration** (warning): the contract declares a
  permission the implementation never exercises. RFC 0003 §C3 only names
  *undeclared* findings; T103 is an additive symmetry extension (roadmap
  M2.2), so it is informational and never fails a check on its own.

Tier resolution never degrades silently: ``tier="auto"`` resolves to tier 0
(the CLI default) and carries an explicit note in the report, and requesting a
tier that cannot run raises :class:`ConformanceError` (mapped to exit code 2 by
the CLI) rather than producing a plausible-looking pass. Tier 1 raises
:class:`Tier1UnavailableError` when no adapter claims the target; tier 2 still
raises :class:`TierNotImplementedError` until roadmap M2.4 ships.

Rendering follows the scan/format split established in
:mod:`scyvera.report`: ``check_contract`` gathers, ``render_check`` formats,
and neither writes to the filesystem nor prints.
"""

from __future__ import annotations

import abc
import enum
from dataclasses import dataclass
from pathlib import Path

from .linter import LintWarning, lint_contract
from .validator import ValidationError, validate_contract

__all__ = [
    "CheckReport",
    "CheckTier",
    "ConformanceError",
    "Tier1Adapter",
    "Tier1ContractError",
    "Tier1Finding",
    "Tier1UnavailableError",
    "TierNotImplementedError",
    "check_contract",
    "render_check",
    "resolve_tier",
]


class ConformanceError(Exception):
    """Base error for the RFC 0003 §C3 conformance layer."""


class Tier1ContractError(ConformanceError):
    """A tier 1 adapter refused to scan an invalid contract.

    Static analysis against a contract that fails tier 0 validation would
    compare code to declarations the schema does not even accept, so the
    adapter fails closed instead of emitting plausible-looking findings.
    """


class Tier1UnavailableError(ConformanceError):
    """Tier 1 was requested but no adapter claims the target.

    This is a usage error (exit code 2), never a silent pass: a target with
    no adapter cannot be certified as conformant.
    """


class TierNotImplementedError(ConformanceError):
    """A conformance tier was requested before its implementation ships.

    Tier 1 adapters land with roadmap tasks M2.2/M2.3 and Tier 2 with M2.4.
    Tier 2 must fail loudly (per the fail-closed philosophy and the RFC 0003
    §C3 "never silently" rule) instead of fabricating a plausible pass.
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
class Tier1Finding:
    """One static declared-vs-code finding (RFC 0003 §C3, roadmap M2.2).

    Attributes:
        code: Finding taxonomy code: ``T101`` (undeclared action), ``T102``
            (ungated call), or ``T103`` (unused declaration).
        title: Short human-readable title matching the taxonomy.
        message: One-line explanation naming the node and the missing or
            mismatched declaration.
        path: File the finding came from (the workflow JSON for T101/T102,
            the contract for T103).
        node_id: Identifier of the workflow node, or ``""`` when the finding
            is about a contract declaration rather than a node.
        severity: ``"error"`` (fails the check) or ``"warning"``
            (informational, exit code 0).
    """

    code: str
    title: str
    message: str
    path: str
    node_id: str
    severity: str


class Tier1Adapter(abc.ABC):
    """Base class for Tier 1 static adapters (RFC 0003 §C3, roadmap M2.2).

    Every adapter shares one API — ``scan(target, contract_path)`` returning
    an ordered tuple of :class:`Tier1Finding` — so the CLI can dispatch by
    target without framework-specific knowledge.

    :meth:`scan` is a fail-closed template: it runs
    :func:`scyvera.validator.validate_contract` **before** delegating to
    :meth:`_scan` and raises :class:`Tier1ContractError` when the contract is
    invalid. Subclasses implement only the static extraction step and cannot
    accidentally scan against an invalid contract.

    Guardrail: adapters are read-only and never print. They may parse the
    target tree but must not write to it, shell out, or open a network
    connection at scan time.
    """

    @abc.abstractmethod
    def _scan(
        self, target: Path, contract_path: Path
    ) -> tuple[Tier1Finding, ...]:
        """Extract findings from a target that already passed validation."""

    def scan(self, target: Path, contract_path: Path) -> tuple[Tier1Finding, ...]:
        """Run the tier 1 adapter against ``target`` and ``contract_path``.

        Args:
            target: Implementation directory the adapter inspects.
            contract_path: Contract the implementation claims to conform to.

        Returns:
            Ordered, immutable tuple of findings (empty means conformant).

        Raises:
            Tier1ContractError: The contract fails tier 0 validation, so no
                comparison is attempted (fail-closed).
        """
        target = Path(target)
        contract_path = Path(contract_path)
        validation_result = validate_contract(contract_path)
        if not validation_result.valid:
            details = "; ".join(
                f"{error.path}: {error.message}" if error.path else error.message
                for error in validation_result.errors
            )
            raise Tier1ContractError(
                f"refusing to scan {target} against {contract_path}: "
                f"contract is invalid ({details or 'validation failed'})"
            )
        return tuple(self._scan(target, contract_path))


@dataclass(frozen=True)
class CheckReport:
    """Result of one conformance check run over a single contract.

    ``valid`` is the Tier 0 PASS/FAIL verdict: schema validation passed and
    no ``error``-severity lint finding (AC000 structural breakdown) fired.
    Soft ACxxx warnings do not flip the verdict — they keep the report at
    ``WARN`` with exit code 0, exactly like ``scyvera lint`` treats them, so
    the combined check remains a strict superset of both source commands.

    ``tier1_findings`` is additive: it stays empty for tier 0 and tier 2, so
    existing call sites and output are unchanged. Tier 1 findings never
    rewrite ``valid``; :attr:`tier1_failed` carries their verdict separately.
    """

    contract_path: str
    tier: CheckTier
    tier_note: str | None
    valid: bool
    validation_errors: tuple[ValidationError, ...]
    warnings: tuple[LintWarning, ...]
    tier1_findings: tuple[Tier1Finding, ...] = ()

    @property
    def error_warnings(self) -> tuple[LintWarning, ...]:
        """Lint findings carrying ``severity="error"`` (e.g. AC000)."""
        return tuple(w for w in self.warnings if w.severity == "error")

    @property
    def soft_warnings(self) -> tuple[LintWarning, ...]:
        """Lint findings with plain ``severity="warning"``."""
        return tuple(w for w in self.warnings if w.severity != "error")

    @property
    def tier1_failed(self) -> bool:
        """Whether a tier 1 finding fails the check (``T101`` or error ``T102``)."""
        return any(
            finding.code == "T101"
            or (finding.code == "T102" and finding.severity == "error")
            for finding in self.tier1_findings
        )


def resolve_tier(tier: str | CheckTier | None) -> tuple[CheckTier, str | None]:
    """Resolve a requested tier into ``(implemented_tier, note)``.

    - Explicit ``0`` / ``CheckTier.STRUCTURAL`` resolves as itself, with no
      note.
    - Explicit ``1`` / ``CheckTier.STATIC`` resolves as itself (roadmap M2.2);
      whether an adapter exists is a per-target question answered by
      :func:`check_contract` / the CLI.
    - ``auto`` (also ``None``) resolves to tier 0 and returns an explicit note
      so the degradation is always visible (RFC 0003 §C3: "never silently").
      Auto never opts into tier 1 because static analysis is only meaningful
      where an adapter claims the target.
    - Explicit ``2`` raises :class:`TierNotImplementedError` until roadmap
      M2.4 ships.

    Raises:
        TierNotImplementedError: When the unimplemented tier 2 is requested
            explicitly.
        ValueError: When ``tier`` is not a recognized specification.
    """
    if tier is None or (isinstance(tier, str) and tier.strip().lower() == "auto"):
        note = (
            "--tier auto resolved to tier 0 (structural); request --tier 1 "
            "(static) explicitly for an adapter-backed target, and tier 2 "
            "(runtime-trace) is not yet implemented (roadmap M2.4)"
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
    target: str | Path | None = None,
    adapter: Tier1Adapter | None = None,
) -> CheckReport:
    """Run a conformance check over one Agent Contract file.

    Tier 0 calls :func:`scyvera.validator.validate_contract` and
    :func:`scyvera.linter.lint_contract` on the same file — the literal union
    of ``scyvera validate`` and ``scyvera lint`` — and combines both result
    sets into one :class:`CheckReport` so the report is a superset of the two
    commands. Filesystem exceptions (``FileNotFoundError``, ``PermissionError``,
    ``yaml.YAMLError``, ``ContractFileNameError``) propagate untouched, exactly
    as in the individual commands; presentation stays in the CLI (RFC 0003 §C3
    keeps the CLI a thin alias).

    Tier 1 performs the same tier 0 pass and then hands the target to an
    adapter (roadmap M2.2). The contract is validated first, so an invalid
    contract never reaches static analysis: the report carries the tier 0
    failure and no tier 1 findings. The adapter itself also fails closed (see
    :meth:`Tier1Adapter.scan`).

    Args:
        contract_path: Path to the contract file (``.yaml`` only, matching
            ``scyvera validate``).
        schema_path: Optional custom JSON Schema path, passed through to the
            validator.
        tier: Requested tier (``"auto"``, ``"0"``, ``"1"``, ``"2"`` or a
            :class:`CheckTier`). See :func:`resolve_tier` for resolution
            semantics.
        target: Implementation directory for a tier 1 adapter. Defaults to the
            contract's parent directory.
        adapter: Tier 1 adapter to run. Required for tier 1; the CLI discovers
            one for the target before calling this function.

    Returns:
        The combined :class:`CheckReport` for the requested tier.

    Raises:
        Tier1UnavailableError: Tier 1 was requested without an adapter.
        TierNotImplementedError: Tier 2 was requested explicitly.
        ValueError: When ``tier`` is not a recognized specification.
    """
    resolved_tier, tier_note = resolve_tier(tier)

    validation_result = validate_contract(contract_path, schema_path=schema_path)
    lint_result = lint_contract(contract_path)

    valid = validation_result.valid and lint_result.valid_structure and not any(
        warning.severity == "error" for warning in lint_result.warnings
    )

    tier1_findings: tuple[Tier1Finding, ...] = ()
    if resolved_tier is CheckTier.STATIC and valid:
        scan_target = Path(target) if target is not None else Path(contract_path).parent
        if adapter is None:
            raise Tier1UnavailableError(
                f"tier 1 (static) requires an adapter for {scan_target}; "
                "no tier 1 adapter is available for this target"
            )
        tier1_findings = adapter.scan(scan_target, Path(contract_path))

    return CheckReport(
        contract_path=str(contract_path),
        tier=resolved_tier,
        tier_note=tier_note,
        valid=valid,
        validation_errors=validation_result.errors,
        warnings=lint_result.warnings,
        tier1_findings=tier1_findings,
    )


def _status_line(report: CheckReport) -> str:
    """Build the first line of the rendered report (house PASS/WARN/FAIL)."""
    if report.tier is CheckTier.STATIC:
        if not report.valid:
            return (
                f"FAIL  {report.contract_path} (tier {report.tier}: "
                "schema validation + ACxxx lint)"
            )
        if report.tier1_failed:
            return (
                f"FAIL  {report.contract_path} (tier {report.tier}: "
                f"{len(report.tier1_findings)} tier-1 finding(s))"
            )
        if report.tier1_findings or report.soft_warnings:
            return (
                f"WARN  {report.contract_path} (tier {report.tier}: "
                f"{len(report.tier1_findings)} tier-1 finding(s))"
            )
        return (
            f"PASS  {report.contract_path} (tier {report.tier}: "
            "0 tier-1 findings)"
        )
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
    then ACxxx lint findings, then tier 1 ``[T10x] title: message`` lines).
    All output is ASCII, so the report is safe on narrow codepages; the
    ``encoding`` parameter exists to keep the signature symmetric with
    :func:`scyvera.report.render_report` and is reserved for the unified
    report format (roadmap M2.5).

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
    for finding in report.tier1_findings:
        lines.append(f"      [{finding.code}] {finding.title}: {finding.message}")
    return "\n".join(lines) + "\n"
