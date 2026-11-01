"""Read-only audit scan engine for the Scyvera Blast Radius report.

Implements the scan and report contract from RFC 0004 §2 and §4: a bounded,
deterministic, read-only walk over a target tree that feeds every text file to
the AUxxx registry in :mod:`scyvera.audit_rules`.

Report shape is ``report_version: 1``. Findings are ordered by severity, then
rule id, then path; no timestamp is emitted, so repeated scans serialize
byte-identically.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

from .audit_rules import RULES, SEVERITY_WEIGHTS, Finding


REPORT_VERSION = 1
MAX_FILE_BYTES = 1024 * 1024
BINARY_SNIFF_BYTES = 8 * 1024
RULE_LOAD_COEFFICIENTS: tuple[float, ...] = (1.00, 0.25, 0.10)

SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "node_modules",
        "dist",
        "build",
        ".pytest_cache",
        ".tox",
        ".release-test",
        "brag-output",
        ".assurance",
        ".agents",
    }
)

_SEVERITY_RANK: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


class AuditError(Exception):
    """Raised when the audit target cannot be scanned safely."""


class SymlinkTargetError(AuditError):
    """Raised when the audit target is a symlink (threat T14).

    Following a symlinked target could escape the intended repository
    boundary, so audit refuses the target instead of resolving it.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        super().__init__(
            f"refusing to audit symlinked target (T14): {self.path}"
        )


@dataclass(frozen=True)
class AuditReport:
    """Deterministic Blast Radius report (RFC 0004 §4)."""

    report_version: int
    target: str
    score: int
    band: str
    stats: Mapping[str, Any]
    findings: tuple[Finding, ...]
    draft_available: bool
    packs_suggested: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        findings = [
            {
                "rule_id": finding.rule_id,
                "severity": finding.severity,
                "title": finding.title,
                "detail": finding.detail,
                "path": finding.path,
                "line": finding.line,
                "suggestion": dict(finding.suggestion),
                "scored": finding.scored,
            }
            for finding in self.findings
        ]

        return {
            "report_version": self.report_version,
            "target": self.target,
            "score": self.score,
            "band": self.band,
            "stats": {
                "files_scanned": self.stats["files_scanned"],
                "files_skipped": self.stats["files_skipped"],
                "findings": dict(self.stats["findings"]),
            },
            "findings": findings,
            "draft_available": self.draft_available,
            "packs_suggested": list(self.packs_suggested),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


def _display_target(target: Path) -> str:
    return target.as_posix()


def _band_for_score(score: int) -> str:
    if score >= 90:
        return "Shielded"
    if score >= 70:
        return "Controlled"
    if score >= 40:
        return "Exposed"
    return "Unbounded"


def _has_tests_fixtures_segment(path: str) -> bool:
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    return any(
        parts[index] == "tests" and parts[index + 1] == "fixtures"
        for index in range(len(parts) - 1)
    )


def _total_load(findings: list[Finding]) -> float:
    """Diminishing per-rule load: 1.00, 0.25, 0.10, then zero."""
    occurrences: dict[str, int] = {}
    total = 0.0

    for finding in findings:
        index = occurrences.get(finding.rule_id, 0)
        occurrences[finding.rule_id] = index + 1
        if index < len(RULE_LOAD_COEFFICIENTS):
            total += (
                SEVERITY_WEIGHTS[finding.severity]
                * RULE_LOAD_COEFFICIENTS[index]
            )

    return total


def _scan_file(
    file_path: Path,
    relative_path: str,
    filename: str,
) -> tuple[bool, list[Finding]]:
    """Return ``(scanned, findings)`` for one file.

    A ``False`` first element means the file was skipped because of the size
    cap, binary sniff, a symlink, or an unreadable file descriptor.
    """
    if file_path.is_symlink():
        return False, []

    try:
        if file_path.stat().st_size > MAX_FILE_BYTES:
            return False, []
        with file_path.open("rb") as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
    except OSError:
        return False, []

    if len(data) > MAX_FILE_BYTES:
        return False, []
    if b"\x00" in data[:BINARY_SNIFF_BYTES]:
        return False, []

    text = data.decode("utf-8", errors="replace")

    findings: list[Finding] = []
    for rule in RULES:
        findings.extend(rule(relative_path, text, filename))

    return True, findings


def scan_tree(target: Path) -> AuditReport:
    """Scan ``target`` read-only and return a deterministic AuditReport.

    Symlinked targets are refused (T14). Paths inside the report are relative
    to the scan root and normalized to ``/`` separators.
    """
    target_path = Path(target)

    if target_path.is_symlink():
        raise SymlinkTargetError(target_path)
    if not target_path.exists():
        raise FileNotFoundError(str(target_path))
    if not target_path.is_file() and not target_path.is_dir():
        raise AuditError(f"not a regular file or directory: {target_path}")

    findings: list[Finding] = []
    files_scanned = 0
    files_skipped = 0

    if target_path.is_file():
        scanned, file_findings = _scan_file(
            target_path,
            target_path.name,
            target_path.name,
        )
        if scanned:
            files_scanned = 1
            findings.extend(file_findings)
        else:
            files_skipped = 1
    else:
        for dirpath, dirnames, filenames in os.walk(
            target_path,
            topdown=True,
            followlinks=False,
        ):
            kept_dirs: list[str] = []
            for dirname in sorted(dirnames):
                if dirname in SKIP_DIRS:
                    continue
                child = Path(dirpath) / dirname
                if child.is_symlink():
                    continue
                kept_dirs.append(dirname)
            dirnames[:] = kept_dirs

            for filename in sorted(filenames):
                file_path = Path(dirpath) / filename
                relative_path = file_path.relative_to(target_path).as_posix()
                scanned, file_findings = _scan_file(
                    file_path,
                    relative_path,
                    filename,
                )
                if scanned:
                    files_scanned += 1
                    findings.extend(file_findings)
                else:
                    files_skipped += 1

    quarantine_all = _has_tests_fixtures_segment(
        target_path.resolve().as_posix()
    )
    findings = [
        replace(finding, scored=False)
        if quarantine_all or finding.path.startswith("tests/fixtures/")
        else finding
        for finding in findings
    ]

    findings.sort(
        key=lambda finding: (
            _SEVERITY_RANK[finding.severity],
            finding.rule_id,
            finding.path,
            finding.line if finding.line is not None else 0,
        )
    )

    scored_findings = [finding for finding in findings if finding.scored]
    score = max(0, 100 - math.ceil(_total_load(scored_findings)))

    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for finding in scored_findings:
        severity_counts[finding.severity] += 1

    return AuditReport(
        report_version=REPORT_VERSION,
        target=_display_target(target_path),
        score=score,
        band=_band_for_score(score),
        stats={
            "files_scanned": files_scanned,
            "files_skipped": files_skipped,
            "findings": severity_counts,
        },
        findings=tuple(findings),
        draft_available=bool(findings),
        packs_suggested=("github-safe",) if findings else (),
    )
