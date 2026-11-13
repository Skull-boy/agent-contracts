"""Reflexive conformance pin for the M3.1 skill (RFC 0003 §C6).

The skill ships a ``contract.yaml`` describing its own reads and writes. The
same Tier 0 check the skill teaches must PASS against the skill itself.
"""

from __future__ import annotations

from pathlib import Path

from scyvera.conformance import check_contract

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "skills" / "scyvera-governance" / "contract.yaml"


def test_bundled_skill_contract_passes_tier0() -> None:
    report = check_contract(CONTRACT, tier="0")
    assert report.valid is True
    assert report.validation_errors == ()
    assert report.warnings == ()
    assert report.tier1_failed is False
