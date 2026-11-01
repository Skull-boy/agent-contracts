"""Permanent dogfood guardrail for RFC 0004 §7 check #1 (M2.0a.1).

This repository is the product's first customer: `scyvera audit .` must stay
in the ``Shielded`` band, and the intentional bad files under
``tests/fixtures/`` must remain visible but quarantined (``scored == false``).
Never mark these tests skip.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scyvera.audit import AuditReport, scan_tree


ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def repository_report() -> AuditReport:
    return scan_tree(ROOT)


def test_repository_scans_as_shielded(repository_report: AuditReport) -> None:
    assert repository_report.band == "Shielded"
    assert repository_report.score >= 90


def test_positive_fixture_findings_are_quarantined(
    repository_report: AuditReport,
) -> None:
    fixture_findings = [
        finding
        for finding in repository_report.findings
        if finding.path.startswith("tests/fixtures/")
    ]
    known_finding = [
        finding
        for finding in fixture_findings
        if finding.rule_id == "AU-SH-001"
        and finding.path == "tests/fixtures/audit/positive/scripts/clean.sh"
    ]

    assert fixture_findings
    assert known_finding
    assert all(finding.scored is False for finding in fixture_findings)
