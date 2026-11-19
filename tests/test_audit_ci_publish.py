"""AU-CI-002 detects every registry publish entry point, staged included.

GE-4b moved the release workflow from ``npm publish`` to ``npm stage publish``.
Staging is still a publish capability - it puts the tarball in the registry's
staging area and only defers the 2FA approval - so the rule must keep
reporting it. A regression here would silently drop the repository's one high
finding and break the dogfood covenant in ``tests/test_audit_dogfood.py``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scyvera.audit import scan_tree


def _write_workflow(root: Path, command: str) -> None:
    path = root / ".github" / "workflows" / "release.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "on: [workflow_dispatch]\n"
        "jobs:\n"
        "  release:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        f"      - run: {command}\n",
        encoding="utf-8",
    )


def _findings(root: Path):
    return [f for f in scan_tree(root).findings if f.rule_id == "AU-CI-002"]


@pytest.mark.parametrize(
    "command",
    [
        "npm publish --provenance --access public",
        "npm stage publish --provenance --access public",
        "npm stage publish",
        "NPM_TOKEN=x npm stage publish",
    ],
)
def test_publish_commands_are_detected(tmp_path: Path, command: str) -> None:
    _write_workflow(tmp_path, command)

    findings = _findings(tmp_path)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "high"
    assert finding.path == ".github/workflows/release.yml"
    assert finding.suggestion["permissions"] == ["registry:publish"]
    assert finding.suggestion["approvals"] == [
        {"action": "registry:publish", "required": True}
    ]


@pytest.mark.parametrize(
    "command",
    [
        "npm stage list",
        "npm stage view 1234",
        "npm stage approve 1234",
        "npm stage reject 1234",
        "npm stage download 1234",
    ],
)
def test_non_publish_stage_commands_are_not_detected(
    tmp_path: Path, command: str
) -> None:
    _write_workflow(tmp_path, command)

    assert _findings(tmp_path) == []
