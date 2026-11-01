"""Read-only audit scan engine for the Scyvera Blast Radius report.

Implements the scan and report contract from RFC 0004 §2 and §4: a bounded,
deterministic, read-only walk over a target tree that feeds every text file to
the AUxxx registry in :mod:`scyvera.audit_rules`.

Report shape is ``report_version: 1``. Findings are ordered by severity, then
rule id, then path; no timestamp is emitted, so repeated scans serialize
byte-identically.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import math
import os
from pathlib import Path
from types import MappingProxyType
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

#: Stable order and names for the terminal ``Scanned N files (...)``
#: breakdown. The count is presentation metadata and is never serialized, so
#: ``--json`` output remains byte-identical (M2.0b).
FILE_KINDS: tuple[str, ...] = (
    "manifests",
    "workflows",
    "source",
    "shell",
    "containers",
    "env",
    "docs",
    "other",
)

_MANIFEST_NAMES = frozenset(
    {
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "pipfile",
        "pipfile.lock",
        "poetry.lock",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "cargo.toml",
        "cargo.lock",
        "go.mod",
        "go.sum",
        "gemfile",
        "gemfile.lock",
        "composer.json",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "environment.yml",
        "environment.yaml",
    }
)
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
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".kts",
        ".rb",
        ".php",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".hpp",
        ".cs",
        ".swift",
        ".scala",
    }
)
_SHELL_SUFFIXES = frozenset(
    {".sh", ".bash", ".zsh", ".ksh", ".ps1", ".psm1", ".bat", ".cmd"}
)
_DOC_SUFFIXES = frozenset({".md", ".markdown", ".rst", ".adoc", ".txt"})


def _is_workflow_path(relative_path: str) -> bool:
    parts = relative_path.replace("\\", "/").split("/")
    return any(
        parts[index] == ".github" and parts[index + 1] == "workflows"
        for index in range(len(parts) - 1)
    )


def _file_kind(relative_path: str) -> str:
    """Classify one scanned file for the terminal breakdown (M2.0b).

    Classification is deterministic and purely name-based; it never reads the
    file again. Unknown names fall back to ``"other"`` so the breakdown can
    never omit a scanned file.
    """
    name = Path(relative_path).name
    lowered = name.lower()
    suffix = Path(lowered).suffix

    if _is_workflow_path(relative_path):
        return "workflows"
    if lowered.startswith(("dockerfile", "containerfile")):
        return "containers"
    if lowered.startswith("docker-compose") and suffix in {".yml", ".yaml"}:
        return "containers"
    if lowered.startswith(".env"):
        return "env"
    if lowered in _MANIFEST_NAMES or (
        lowered.startswith("requirements") and lowered.endswith(".txt")
    ):
        return "manifests"
    if suffix in _SOURCE_SUFFIXES:
        return "source"
    if suffix in _SHELL_SUFFIXES:
        return "shell"
    if suffix in _DOC_SUFFIXES:
        return "docs"
    return "other"


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
    """Deterministic Blast Radius report (RFC 0004 §4).

    ``file_kinds`` is terminal-renderer metadata: the number of scanned files
    per :data:`FILE_KINDS` category. It is deliberately excluded from
    :meth:`to_dict`, so ``--json`` output stays byte-identical (M2.0b).
    """

    report_version: int
    target: str
    score: int
    band: str
    stats: Mapping[str, Any]
    findings: tuple[Finding, ...]
    draft_available: bool
    packs_suggested: tuple[str, ...]
    file_kinds: Mapping[str, int] = field(
        default_factory=lambda: MappingProxyType({})
    )

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


def _is_fixture_path(path: str) -> bool:
    """True for workspace-relative paths inside ``tests/fixtures/``."""
    return path.replace("\\", "/").startswith("tests/fixtures/")


def _is_fixture_target(target: Path) -> bool:
    """True when the scan target itself lives under ``tests/fixtures``.

    Relative finding paths lose the ``tests/fixtures/`` prefix when the
    target is a fixture directory, so a direct fixture scan is quarantined
    wholesale instead of being scored as production code.
    """
    parts = [
        part for part in target.resolve().as_posix().split("/") if part
    ]
    return any(
        parts[index] == "tests" and parts[index + 1] == "fixtures"
        for index in range(len(parts) - 1)
    )


def _quarantine_findings(
    findings: list[Finding],
    target: Path,
) -> list[Finding]:
    """Mark intentional fixture findings as unscored.

    Quarantined findings stay in the report so fixture coverage remains
    visible, but they never change the score, band, or severity stats.
    """
    quarantine_all = _is_fixture_target(target)
    return [
        replace(finding, scored=False)
        if quarantine_all or _is_fixture_path(finding.path)
        else finding
        for finding in findings
    ]


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

    Findings inside ``tests/fixtures/`` are intentional test material. They
    are marked ``scored=False`` and excluded from the score, band, exit
    code, and ``stats.findings`` while remaining visible in the report.
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
    file_kind_counts: dict[str, int] = {}

    if target_path.is_file():
        scanned, file_findings = _scan_file(
            target_path,
            target_path.name,
            target_path.name,
        )
        if scanned:
            files_scanned = 1
            findings.extend(file_findings)
            kind = _file_kind(target_path.as_posix())
            file_kind_counts[kind] = file_kind_counts.get(kind, 0) + 1
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
                    kind = _file_kind(relative_path)
                    file_kind_counts[kind] = (
                        file_kind_counts.get(kind, 0) + 1
                    )
                else:
                    files_skipped += 1

    findings = _quarantine_findings(findings, target_path)

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
        draft_available=bool(scored_findings),
        packs_suggested=("github-safe",) if scored_findings else (),
        file_kinds=MappingProxyType(
            {
                kind: file_kind_counts[kind]
                for kind in FILE_KINDS
                if kind in file_kind_counts
            }
        ),
    )
