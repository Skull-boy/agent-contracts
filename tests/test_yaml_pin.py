"""Deserialization pin for PyYAML loading paths (roadmap PD-4).

Scyvera reads untrusted YAML (contracts, policy packs, registry sources), so
every load must go through the safe loader family. This module enforces that
guarantee in two independent ways:

- **Static**: walk every ``.py`` file under ``src/scyvera`` and reject any
  ``yaml.load(...)`` call that does not pass an explicit safe ``Loader``.
  ``yaml.safe_load`` / ``safe_load_all`` / ``safe_load_file`` are accepted.
- **Runtime**: patch ``yaml.unsafe_load`` (and the other unsafe/full loaders)
  to raise, then exercise the four known call sites — CLI discovery,
  validator, registry, and policy packs — plus the audit scan. Nothing may
  reach an unsafe loader.

The static detector is itself mutation-tested, so introducing ``yaml.load``
into ``src/scyvera`` fails this file loudly instead of silently passing.
"""

from __future__ import annotations

import contextlib
import importlib
import re
import sys
from pathlib import Path
from typing import Iterator
from unittest import mock

import pytest
import yaml

from scyvera.audit import scan_tree
from scyvera.cli import main
from scyvera.enforcer import ContractEnforcer
from scyvera.packs import load_pack
from scyvera.registry import ContractRegistry
from scyvera.validator import validate_contract

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "scyvera"
GITHUB_CONTRACT = ROOT / "tests" / "fixtures" / "github_contract.yaml"
VALID_CONTRACTS = (
    ROOT / "tests" / "fixtures" / "v1.1" / "valid-minimal.yaml",
    ROOT / "tests" / "fixtures" / "v1.1" / "valid-full.yaml",
)
LANGGRAPH_TARGET = ROOT / "implementations" / "langgraph" / "duplicate-issue-detector"

#: A call to ``yaml.load`` — never ``yaml.safe_load`` / ``yaml.unsafe_load``.
YAML_LOAD = re.compile(r"\byaml\.load\s*\(")

#: An explicit safe Loader argument, which makes ``yaml.load`` acceptable.
SAFE_LOADER = re.compile(r"Loader\s*=\s*(?:yaml\.)?C?SafeLoader\b")

KNOWN_CALL_SITES = (
    "scyvera.cli",
    "scyvera.validator",
    "scyvera.registry",
    "scyvera.packs",
)


def _unsafe_yaml_load_lines(source: str) -> list[int]:
    """Return 1-based line numbers of unsafe ``yaml.load`` calls in ``source``.

    A ``yaml.load`` call that passes ``Loader=yaml.SafeLoader`` (or
    ``yaml.CSafeLoader``) is explicitly safe and is not reported.
    """
    unsafe: list[int] = []
    for match in YAML_LOAD.finditer(source):
        tail = source[match.start() : match.start() + 300]
        if SAFE_LOADER.search(tail):
            continue
        unsafe.append(source.count("\n", 0, match.start()) + 1)
    return unsafe


@contextlib.contextmanager
def _forbid_unsafe_yaml() -> Iterator[None]:
    """Make every unsafe PyYAML loader entry point fail loudly."""
    message = "unsafe YAML loader reached during a pinned safe path"
    with contextlib.ExitStack() as stack:
        for name in ("unsafe_load", "unsafe_load_all", "full_load", "full_load_all"):
            stack.enter_context(
                mock.patch.object(yaml, name, side_effect=AssertionError(message))
            )
        yield


# ---------------------------------------------------------------------------
# Static pin
# ---------------------------------------------------------------------------


def test_no_source_file_calls_yaml_load_unsafely() -> None:
    offenders: dict[str, list[int]] = {}
    files = sorted(SRC.rglob("*.py"))
    assert files, "source tree walk must find Python files"
    for path in files:
        lines = _unsafe_yaml_load_lines(path.read_text(encoding="utf-8"))
        if lines:
            offenders[str(path.relative_to(ROOT))] = lines
    assert offenders == {}, f"unsafe yaml.load found: {offenders}"


@pytest.mark.parametrize("module_name", KNOWN_CALL_SITES)
def test_known_call_site_exposes_safe_load(module_name: str) -> None:
    module = importlib.import_module(module_name)
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "yaml.safe_load" in source
    assert _unsafe_yaml_load_lines(source) == []


def test_static_pin_detects_injected_yaml_load() -> None:
    """Self-referential mutation test: the pin must fail on ``yaml.load``."""
    injected = "def load_it(stream):\n    return yaml.load(stream)\n"
    assert _unsafe_yaml_load_lines(injected) == [2]


def test_static_pin_allows_explicit_safe_loader() -> None:
    allowed = "value = yaml.load(stream, Loader=yaml.SafeLoader)\n"
    assert _unsafe_yaml_load_lines(allowed) == []


# ---------------------------------------------------------------------------
# Runtime pin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("contract_path", VALID_CONTRACTS, ids=lambda path: path.name)
def test_validate_contract_never_reaches_unsafe_load(contract_path: Path) -> None:
    with _forbid_unsafe_yaml():
        result = validate_contract(contract_path)
    assert result.valid is True


@pytest.fixture
def fixture_tree(tmp_path: Path) -> Path:
    """A small representative tree for the audit runtime pin."""
    (tmp_path / "contract.yaml").write_text(
        "version: 1\nworkflow: pin-fixture\npermissions:\n  - github.read\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("TOKEN=not-a-real-secret\n", encoding="utf-8")
    (tmp_path / "deploy.sh").write_text("#!/bin/sh\nnpm publish\n", encoding="utf-8")
    (tmp_path / "agent.py").write_text(
        "import subprocess\n\nsubprocess.run(['git', 'push'])\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.mark.parametrize("scan_file", [False, True], ids=["tree", "single-file"])
def test_audit_scan_never_reaches_unsafe_load(fixture_tree: Path, scan_file: bool) -> None:
    target = fixture_tree / "contract.yaml" if scan_file else fixture_tree
    with _forbid_unsafe_yaml():
        report = scan_tree(target)
    assert report.stats["files_scanned"] >= 1


def test_policy_pack_load_never_reaches_unsafe_load() -> None:
    with _forbid_unsafe_yaml():
        pack = load_pack("dev-agent")
    assert pack.name == "dev-agent"


def test_registry_register_never_reaches_unsafe_load(tmp_path: Path) -> None:
    registry = ContractRegistry(path=str(tmp_path / "registry.jsonl"))
    enforcer = ContractEnforcer.load(GITHUB_CONTRACT)
    with _forbid_unsafe_yaml():
        entry = enforcer.register(registry)
    assert entry.contract_source == "file"
    assert isinstance(entry.content, dict)


def test_cli_discovery_never_reaches_unsafe_load(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["scyvera", "check", str(LANGGRAPH_TARGET), "--tier", "1"],
    )
    with _forbid_unsafe_yaml():
        exit_code = main()
    capsys.readouterr()
    assert exit_code == 0
