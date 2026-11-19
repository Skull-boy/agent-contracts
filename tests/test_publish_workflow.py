"""The release workflow stays staged, token-free, and human-gated.

GE-4b replaced direct ``npm publish`` (backed by an ``NPM_TOKEN`` secret) with
``npm stage publish`` over GitHub OIDC trusted publishing. These assertions run
on every PR, so a future edit cannot quietly reintroduce a long-lived publish
token or a direct publish before that edit reaches a release tag.

The workflow file name is part of the contract: the trusted publisher on
npmjs.com is bound to ``publish-scyvera-ts.yml``, and AU-CI-002's dogfood
covenant pins this exact path.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "publish-scyvera-ts.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")
DOCUMENT = yaml.safe_load(TEXT)

RUN_BLOCKS = [
    step["run"]
    for step in DOCUMENT["jobs"]["publish"]["steps"]
    if isinstance(step, dict) and "run" in step
]
RUN_TEXT = "\n".join(RUN_BLOCKS)


def test_workflow_is_valid_yaml_with_minimal_permissions() -> None:
    assert isinstance(DOCUMENT, dict)
    assert DOCUMENT["permissions"] == {"contents": "read", "id-token": "write"}


def test_workflow_is_triggered_by_a_published_release() -> None:
    # PyYAML reads the bare `on:` key as the boolean True (YAML 1.1).
    triggers = DOCUMENT[True]
    assert triggers["release"]["types"] == ["published"]
    assert "workflow_dispatch" in triggers


def test_workflow_runs_behind_the_environment_gate() -> None:
    assert DOCUMENT["jobs"]["publish"]["environment"] == "npm-production"


def test_release_is_staged_not_published() -> None:
    assert "npm stage publish --provenance --access public" in RUN_TEXT
    assert "npm stage publish --dry-run" in RUN_TEXT
    for line in RUN_TEXT.splitlines():
        assert not line.strip().startswith("npm publish")


def test_workflow_carries_no_long_lived_token() -> None:
    assert "NODE_AUTH_TOKEN" not in TEXT
    assert "secrets." not in TEXT


def test_workflow_pins_npm_11_for_staged_publishing() -> None:
    assert DOCUMENT["jobs"]["publish"]["env"]["NPM_CLI_MAJOR"] == "11"
    assert 'npm install -g "npm@${NPM_CLI_MAJOR}"' in RUN_TEXT


@pytest.mark.parametrize(
    "required",
    [
        'test "${GITHUB_REF_NAME}" = "scyvera-ts-v${version}"',
        "vectors/suite-version",
        "npm test",
        "npm run vectors",
    ],
)
def test_release_guardrails_are_preserved(required: str) -> None:
    assert required in RUN_TEXT
