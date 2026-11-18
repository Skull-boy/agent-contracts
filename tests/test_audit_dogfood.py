"""Permanent dogfood guardrail for RFC 0004 §7 check #1 (M2.0a.1).

This repository is the product's first customer. Since
[RFC 0004 Amendment 1](../rfcs/0004-amendment-1-dogfood-declared-capability.md)
(2026-11-18) the guardrail is a covenant rather than a fixed band: `scyvera
audit .` must produce exactly the scored findings declared below, and the root
`contract.yaml` must declare and approve the capability that introduces the one
high finding (AU-CI-002 for the npm publish workflow).

The intentional bad files under ``tests/fixtures/`` must remain visible but
quarantined (``scored == false``). Never mark these tests skip.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scyvera.audit import AuditReport, scan_tree
from scyvera.validator import load_contract


ROOT = Path(__file__).resolve().parent.parent

#: The exact scored-findings covenant (RFC 0004 Amendment 1). Every entry is
#: ``(severity, rule_id, path)``. Adding or removing a scored finding is a
#: covenant change: update this table together with a new amendment, never
#: silence a finding.
EXPECTED_SCORED_FINDINGS = frozenset(
    {
        ("high", "AU-CI-002", ".github/workflows/publish-scyvera-ts.yml"),
        (
            "medium",
            "AU-N8N-001",
            "implementations/n8n/competitor-feature-parity-watcher/workflow.json",
        ),
        (
            "medium",
            "AU-N8N-001",
            "implementations/n8n/duplicate-issue-detector/workflow.json",
        ),
        (
            "medium",
            "AU-N8N-001",
            "implementations/n8n/github-debugger-agent/workflow.json",
        ),
        (
            "medium",
            "AU-N8N-001",
            "implementations/n8n/telegram-github-antigravity-pipeline/workflow.json",
        ),
        (
            "medium",
            "AU-NET-002",
            "implementations/langgraph/duplicate-issue-detector/backfill.py",
        ),
        (
            "medium",
            "AU-NET-002",
            "implementations/langgraph/duplicate-issue-detector/duplicate_issue_detector/nodes.py",
        ),
    }
)


@pytest.fixture(scope="module")
def repository_report() -> AuditReport:
    return scan_tree(ROOT)


def test_repository_scans_to_the_declared_covenant(
    repository_report: AuditReport,
) -> None:
    """Pin the honest post-enablement numbers and the exact scored surface."""
    assert repository_report.score == 84
    assert repository_report.band == "Controlled"
    assert repository_report.governance == "governed"

    scored = frozenset(
        (finding.severity, finding.rule_id, finding.path)
        for finding in repository_report.findings
        if finding.scored
    )
    assert scored == EXPECTED_SCORED_FINDINGS


def test_root_contract_declares_and_approves_the_publish_capability() -> None:
    """The one high finding is declared and approved, not hidden.

    AU-CI-002's own remediation metadata prescribes this exact permission and
    approval pair. Removing the approval must fail this test: that is what
    makes the covenant an approval rather than a waiver.
    """
    contract = load_contract(ROOT / "contract.yaml")

    assert "registry:publish" in contract["permissions"]

    publish_approvals = [
        approval
        for approval in contract["approvals"]
        if isinstance(approval, dict)
        and approval.get("action") == "registry:publish"
        and approval.get("required") is True
    ]
    assert publish_approvals, (
        "contract.yaml must approve registry:publish with required: true"
    )
    assert all(
        isinstance(approval.get("approver"), str)
        and approval["approver"].strip()
        for approval in publish_approvals
    ), "registry:publish must name a human approver role"


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
