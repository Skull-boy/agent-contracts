"""Tests for package self-integrity and the ``scyvera self-check`` CLI.

Roadmap M3.4 / RFC 0003 §C2 acceptance: a fresh installed-style package copy
passes, while a tampered copy fails. The tests also pin the fail-closed edges:
missing/modified/removed/unlisted files, missing or unsupported manifests,
version mismatch, exclusion rules, result immutability, engine purity, and the
documented CLI exit-code split (``0`` clean, ``1`` deviation, ``2``
unverifiable/IO).

The version cross-check intentionally compares the manifest against the
*installed distribution* version. Test copies are therefore given the current
``importlib.metadata`` version explicitly, so the suite is independent of a
developer's editable-install bookkeeping.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil

import pytest

from scyvera.cli import main
from scyvera.selfcheck import (
    CHECK_MODIFIED,
    CHECK_MISSING,
    CHECK_UNLISTED,
    FAILURE_MANIFEST_MISSING,
    FAILURE_MANIFEST_VERSION_MISMATCH,
    FAILURE_MISSING,
    FAILURE_MODIFIED,
    FAILURE_UNLISTED,
    FAILURE_VERSION_MISMATCH,
    SELF_MANIFEST_FILENAME,
    SelfCheckEntry,
    SelfCheckError,
    SelfCheckFailure,
    SelfCheckResult,
    generate_manifest,
    self_check,
)


ROOT = Path(__file__).resolve().parent.parent
SOURCE_PACKAGE = ROOT / "src" / "scyvera"
INSTALLED_VERSION = importlib.metadata.version("scyvera")
_COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


def _fresh_copy(tmp_path: Path) -> Path:
    """Create an installed-style package tree with a matching manifest."""
    target = tmp_path / "site-packages" / "scyvera"
    shutil.copytree(SOURCE_PACKAGE, target, ignore=_COPY_IGNORE)

    manifest = json.loads(generate_manifest(target))
    manifest["version"] = INSTALLED_VERSION
    (target / SELF_MANIFEST_FILENAME).write_text(
        json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return target


def _result(
    *,
    failures: tuple[SelfCheckFailure, ...] = (),
    entries: tuple[SelfCheckEntry, ...] = (),
    manifest_version: str | None = "1",
) -> SelfCheckResult:
    return SelfCheckResult(
        entries=entries,
        passed=not failures,
        failures=failures,
        manifest_version=manifest_version,
        package_version=INSTALLED_VERSION,
    )


def _failure_codes(result: SelfCheckResult) -> set[str]:
    return {failure.code for failure in result.failures}


def _tree_digest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


# ---------------------------------------------------------------------------
# Fresh and tampered installed-style copies
# ---------------------------------------------------------------------------


def test_fresh_installed_style_copy_passes(tmp_path: Path) -> None:
    package = _fresh_copy(tmp_path)

    result = self_check(package)

    assert result.passed is True
    assert result.failures == ()
    assert result.manifest_version == "1"
    assert result.package_version == INSTALLED_VERSION
    assert result.entries
    assert all(entry.status == "ok" for entry in result.entries)
    assert SELF_MANIFEST_FILENAME not in {entry.path for entry in result.entries}


def test_modified_python_file_fails_and_is_named(tmp_path: Path) -> None:
    package = _fresh_copy(tmp_path)
    target = package / "enforcer.py"
    target.write_bytes(target.read_bytes() + b"\n# tampered\n")

    result = self_check(package)

    assert result.passed is False
    assert FAILURE_MODIFIED in _failure_codes(result)
    modified = [f for f in result.failures if f.code == FAILURE_MODIFIED]
    assert [failure.path for failure in modified] == ["enforcer.py"]
    entry = next(entry for entry in result.entries if entry.path == "enforcer.py")
    assert entry.status == CHECK_MODIFIED
    assert entry.expected_sha256 != entry.actual_sha256


def test_modified_bundled_schema_fails(tmp_path: Path) -> None:
    package = _fresh_copy(tmp_path)
    schema = package / "schemas" / "v1.1" / "contract.schema.json"
    schema.write_bytes(schema.read_bytes() + b" ")

    result = self_check(package)

    assert result.passed is False
    assert [
        failure.path
        for failure in result.failures
        if failure.code == FAILURE_MODIFIED
    ] == ["schemas/v1.1/contract.schema.json"]


def test_removed_file_fails(tmp_path: Path) -> None:
    package = _fresh_copy(tmp_path)
    (package / "registry.py").unlink()

    result = self_check(package)

    assert result.passed is False
    assert FAILURE_MISSING in _failure_codes(result)
    missing = [f for f in result.failures if f.code == FAILURE_MISSING]
    assert [failure.path for failure in missing] == ["registry.py"]
    entry = next(entry for entry in result.entries if entry.path == "registry.py")
    assert entry.status == CHECK_MISSING
    assert entry.actual_sha256 is None


def test_unlisted_addition_fails(tmp_path: Path) -> None:
    package = _fresh_copy(tmp_path)
    (package / "dropped_in_override.py").write_text(
        "raise SystemExit('override')\n",
        encoding="utf-8",
    )

    result = self_check(package)

    assert result.passed is False
    assert FAILURE_UNLISTED in _failure_codes(result)
    unlisted = [f for f in result.failures if f.code == FAILURE_UNLISTED]
    assert [failure.path for failure in unlisted] == ["dropped_in_override.py"]
    entry = next(
        entry for entry in result.entries
        if entry.path == "dropped_in_override.py"
    )
    assert entry.status == CHECK_UNLISTED
    assert entry.expected_sha256 is None


def test_pycache_addition_is_excluded(tmp_path: Path) -> None:
    package = _fresh_copy(tmp_path)
    cache = package / "__pycache__"
    cache.mkdir()
    (cache / "x.pyc").write_bytes(b"\x00\x01")

    result = self_check(package)

    assert result.passed is True
    assert all("__pycache__" not in entry.path for entry in result.entries)


# ---------------------------------------------------------------------------
# Manifest-level fail-closed behavior
# ---------------------------------------------------------------------------


def test_missing_manifest_fails_closed_with_actionable_message(
    tmp_path: Path,
) -> None:
    package = _fresh_copy(tmp_path)
    (package / SELF_MANIFEST_FILENAME).unlink()

    result = self_check(package)

    assert result.passed is False
    assert result.manifest_version is None
    assert [failure.code for failure in result.failures] == [
        FAILURE_MANIFEST_MISSING
    ]
    message = result.failures[0].message
    assert "signed release" in message
    assert "installed distribution" in message


def test_manifest_version_mismatch_fails(tmp_path: Path) -> None:
    package = _fresh_copy(tmp_path)
    manifest_path = package / SELF_MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = "0.0.0"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    result = self_check(package)

    assert result.passed is False
    assert FAILURE_VERSION_MISMATCH in _failure_codes(result)
    assert result.manifest_version == "1"
    assert result.package_version == INSTALLED_VERSION


def test_unsupported_manifest_version_fails_closed(tmp_path: Path) -> None:
    package = _fresh_copy(tmp_path)
    manifest_path = package / SELF_MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["manifest_version"] = "2"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    result = self_check(package)

    assert result.passed is False
    assert result.manifest_version == "2"
    assert [failure.code for failure in result.failures] == [
        FAILURE_MANIFEST_VERSION_MISMATCH
    ]


def test_malformed_manifest_fails_closed(tmp_path: Path) -> None:
    package = _fresh_copy(tmp_path)
    (package / SELF_MANIFEST_FILENAME).write_text("{not json", encoding="utf-8")

    result = self_check(package)

    assert result.passed is False
    assert result.manifest_version is None
    assert result.failures[0].code == "manifest-invalid"


def test_path_traversal_in_manifest_is_rejected(tmp_path: Path) -> None:
    package = _fresh_copy(tmp_path)
    manifest_path = package / SELF_MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append({"path": "../outside.py", "sha256": "0" * 64})
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    result = self_check(package)

    assert result.passed is False
    assert result.failures[0].code == "manifest-invalid"


def test_nonexistent_package_path_raises_self_check_error(tmp_path: Path) -> None:
    with pytest.raises(SelfCheckError):
        self_check(tmp_path / "does-not-exist")


# ---------------------------------------------------------------------------
# Determinism, purity, and immutable result types
# ---------------------------------------------------------------------------


def test_generate_manifest_is_deterministic_and_sorted(tmp_path: Path) -> None:
    package = _fresh_copy(tmp_path)

    first = generate_manifest(package)
    second = generate_manifest(package)

    assert first == second
    payload = json.loads(first)
    assert payload["manifest_version"] == "1"
    assert payload["name"] == "scyvera"
    paths = [entry["path"] for entry in payload["files"]]
    assert paths == sorted(paths)
    assert SELF_MANIFEST_FILENAME not in paths
    assert all("\\" not in path for path in paths)


def test_self_check_is_silent_and_does_not_mutate_the_tree(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    package = _fresh_copy(tmp_path)
    before = _tree_digest(package)

    result = self_check(package)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert result.passed is True
    assert _tree_digest(package) == before


def test_result_types_are_frozen(tmp_path: Path) -> None:
    package = _fresh_copy(tmp_path)
    (package / "extra.py").write_text("x = 1\n", encoding="utf-8")
    result = self_check(package)

    assert isinstance(result.entries, tuple)
    assert isinstance(result.failures, tuple)
    assert result.failures
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.passed = True  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.failures[0].code = "other"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.entries[0].status = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CLI presentation and exit codes
# ---------------------------------------------------------------------------


def test_cli_self_check_clean_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["scyvera", "self-check"])

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "PASS  self-check  scyvera" in output
    assert "manifest: 1" in output
    assert "verified:" in output


def test_cli_self_check_json_clean_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["scyvera", "self-check", "--json"])

    exit_code = main()
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["self_check_version"] == 1
    assert payload["passed"] is True
    assert payload["package_version"] == INSTALLED_VERSION
    assert payload["entries"]


def test_cli_self_check_deviation_returns_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    failure = SelfCheckFailure(
        code=FAILURE_MODIFIED,
        path="enforcer.py",
        message="SHA-256 does not match the signed manifest",
    )
    entry = SelfCheckEntry(
        path="enforcer.py",
        expected_sha256="a" * 64,
        actual_sha256="b" * 64,
        status=CHECK_MODIFIED,
    )
    monkeypatch.setattr(
        "scyvera.cli.self_check",
        lambda: _result(failures=(failure,), entries=(entry,)),
    )
    monkeypatch.setattr("sys.argv", ["scyvera", "self-check"])

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "FAIL  self-check" in output
    assert "enforcer.py" in output
    assert "modified" in output


def test_cli_self_check_missing_manifest_returns_two(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    failure = SelfCheckFailure(
        code=FAILURE_MANIFEST_MISSING,
        path=None,
        message="no self-check manifest; reinstall from a signed release",
    )
    monkeypatch.setattr(
        "scyvera.cli.self_check",
        lambda: _result(failures=(failure,), manifest_version=None),
    )
    monkeypatch.setattr("sys.argv", ["scyvera", "self-check"])

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 2
    assert "manifest: missing" in output
    assert "manifest-missing" in output


def test_cli_self_check_engine_error_returns_two(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def explode() -> SelfCheckResult:
        raise SelfCheckError("package-path", "installed package not found")

    monkeypatch.setattr("scyvera.cli.self_check", explode)
    monkeypatch.setattr("sys.argv", ["scyvera", "self-check"])

    exit_code = main()
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "scyvera self-check: error" in captured.err
    assert "installed package not found" in captured.err
