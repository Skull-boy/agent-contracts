"""Grep-pins for the GE-1 specification skeleton (RFC 0005 + vectors/).

This test is deliberately tiny: it pins the files GE-1 is allowed to create,
the suite version pin GE-3 fills in, and the six GEP normative anchors that
GE-2/GE-3 implement. It asserts no engine behaviour and adds no dependencies.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RFC = ROOT / "rfcs" / "0005-provisional-contracts.md"
VECTORS = ROOT / "vectors"
README = VECTORS / "README.md"
SUITE_VERSION = VECTORS / "suite-version"

REQUIRED_SECTIONS = (
    "## 1. Abstract",
    "## 2. Terminology",
    "## 3. Provisional Contracts (normative)",
    "## 4. Draft Mode (normative)",
    "## 5. Promotion Ritual (normative)",
    "## 6. Conformance Vector Suite (normative format, non-normative runner)",
    "## 7. Threat Model Deltas",
    "## 8. Open Questions",
    "## 9. Conflicts Considered",
)

NORMATIVE_ANCHORS = (
    "A runtime MUST NOT perform inference-time enforcement without a "
    "provisional contract on disk.",
    "Irreversible actions MUST default-deny with an approval gate even in "
    "draft mode.",
    "Promotion MUST be human-only and MUST use the existing re-seal machinery.",
    "Promotion MUST NOT be silent or automatic.",
    "Agent-side skills MUST hold no authority over contracts.",
    "Every runtime MUST pass the same pinned conformance-vector suite version.",
)


def test_suite_version_is_pinned() -> None:
    raw = SUITE_VERSION.read_bytes()
    # Git may check the extensionless file out with CRLF on Windows; the
    # canonical bytes in the repository are LF. Pin the content, not the
    # checkout's line-ending artifact.
    assert not raw.startswith(b"\xef\xbb\xbf")
    normalized = raw.replace(b"\r\n", b"\n")
    assert normalized == b"suite-version: 1\n"
    assert re.fullmatch(rb"suite-version: (0|[1-9][0-9]*)\n", normalized)
    assert int(normalized.decode("ascii").split(": ", 1)[1]) == 1
    # GE-3 populated the first non-empty suite at v1.
    assert (VECTORS / "v1").is_dir()


def test_vectors_readme_points_at_rfc_0005_section_6() -> None:
    text = README.read_text(encoding="utf-8")
    assert "RFC 0005" in text
    assert "RFC 0005 §6" in text
    assert "Suite version 1" in text
    assert "GE-3" in text


def test_rfc_0005_exists_and_is_draft() -> None:
    assert RFC.is_file()
    text = RFC.read_text(encoding="utf-8")
    assert "# RFC 0005:" in text
    assert "**Status**: Draft" in text


@pytest.mark.parametrize("heading", REQUIRED_SECTIONS)
def test_rfc_0005_has_required_section(heading: str) -> None:
    assert heading in RFC.read_text(encoding="utf-8")


@pytest.mark.parametrize("anchor", NORMATIVE_ANCHORS)
def test_rfc_0005_encodes_normative_anchor(anchor: str) -> None:
    assert anchor in RFC.read_text(encoding="utf-8")
