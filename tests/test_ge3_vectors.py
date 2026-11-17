"""RFC 0005 section 6 conformance suite and runner tests (GEP GE-3).

Pins the shared acceptance corpus and the reference runner:

* the suite loads from ``vectors/`` at the pinned version and every vector
  executes (no skips, no subset);
* configuration errors fail closed with exit code ``2`` and name the file;
* two runs produce byte-identical output;
* ``scyvera vectors --json`` is a valid RFC 0003 unified envelope;
* the ``check``-on-provisional gap (RFC 0005 section 8 Q8) is closed as a
  warn-only marker with byte-identical output for non-provisional contracts;
* ``write_provisional_contract`` is atomic: a failure never leaves a partial
  contract behind.

Promotion orchestration is intentionally not a vector category (RFC 0005
sections 6.1 and 6.10, Q5), so its non-negotiables are pinned here against the
real engine instead.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest
from jsonschema import Draft202012Validator

from scyvera import (
    ContractEnforcer,
    ContractRegistry,
    PromotionIntent,
    ProvisionalContractError,
    ResealError,
    VectorSuiteError,
    reseal,
)
from scyvera.cli import main
from scyvera.conformance import check_contract, render_check
from scyvera.generate import write_provisional_contract
from scyvera.unified import load_report_schema
from scyvera.vectors import CATEGORIES, load_suite, run_suite
VECTORS_ROOT = Path(__file__).resolve().parent.parent / "vectors"


def _copy_suite(tmp_path: Path) -> Path:
    root = tmp_path / "vectors"
    shutil.copytree(VECTORS_ROOT, root)
    return root


def _run_cli(monkeypatch: pytest.MonkeyPatch, capsys, *args: str) -> tuple[int, str, str]:
    monkeypatch.setattr("sys.argv", ["scyvera", "vectors", *args])
    code = main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _provisional_contract(path: Path) -> Path:
    path.write_text(
        "version: 1.1\n"
        "provisional: true\n"
        "system:\n"
        "  name: ge3-agent\n"
        "lifecycle:\n"
        "  mode: request-response\n"
        "  initiation: human-only\n"
        "permissions: []\n"
        "side_effects: []\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Corpus loading and execution
# ---------------------------------------------------------------------------


def test_suite_loads_at_the_pinned_version() -> None:
    suite = load_suite(VECTORS_ROOT)

    assert suite.suite_version == 1
    assert len(suite.vectors) == 33
    counts = {
        category: sum(1 for v in suite.vectors if v.category == category)
        for category in CATEGORIES
    }
    assert counts == {
        "contract-model": 11,
        "gate-decision": 13,
        "trace-roundtrip": 9,
    }


def test_every_vector_executes_and_passes() -> None:
    run = run_suite(load_suite(VECTORS_ROOT))

    assert run.total == 33
    assert run.failed == 0, [failure.to_dict() for failure in run.failures]
    assert run.passed == 33
    assert run.failures == ()


def test_vectors_are_sorted_by_id() -> None:
    suite = load_suite(VECTORS_ROOT)
    ids = [vector.id for vector in suite.vectors]

    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))


def test_category_filter_selects_exactly_one_category() -> None:
    suite = load_suite(VECTORS_ROOT)

    for category in CATEGORIES:
        run = run_suite(suite, category=category)
        expected = sum(1 for v in suite.vectors if v.category == category)
        assert run.total == expected
        assert run.failed == 0


def test_unknown_category_fails_closed() -> None:
    suite = load_suite(VECTORS_ROOT)

    with pytest.raises(VectorSuiteError, match="unknown category"):
        run_suite(suite, category="promotion")


def test_determinism_two_runs_are_byte_identical() -> None:
    first = run_suite(load_suite(VECTORS_ROOT)).to_json()
    second = run_suite(load_suite(VECTORS_ROOT)).to_json()

    assert first == second
    assert first == (
        '{"failed":0,"failures":[],"passed":33,"suite_version":1,"total":33}\n'
    )


def test_one_crashing_vector_does_not_abort_the_suite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scyvera import vectors as vectors_module

    def explode(vector):
        raise RuntimeError("boom at C:/secret/path")

    monkeypatch.setitem(vectors_module._EXECUTORS, "gate-decision", explode)
    run = run_suite(load_suite(VECTORS_ROOT))

    assert run.total == 33
    assert run.failed == 13
    assert run.passed == 20
    assert {failure.reason for failure in run.failures} == {
        "runner error: RuntimeError"
    }
    assert all("secret" not in failure.reason for failure in run.failures)


def test_runner_hands_the_enforcer_a_resolved_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """macOS /var and Windows 8.3 temp names must not look like T14 escapes."""
    captured: list[Path] = []
    real_load = ContractEnforcer.load.__func__

    def spy(cls, path, *args, **kwargs):
        captured.append(Path(path))
        return real_load(cls, path, *args, **kwargs)

    monkeypatch.setattr(ContractEnforcer, "load", classmethod(spy))
    run_suite(load_suite(VECTORS_ROOT))

    assert captured
    assert all(path == path.resolve() for path in captured)


def test_runner_tolerates_a_symlinked_temp_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduces macOS, where tempfile returns /var but resolve() gives /private/var."""
    real = tmp_path / "real-temp"
    real.mkdir()
    link = tmp_path / "linked-temp"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this platform")

    class _LinkedTempDir:
        def __init__(self, *args, **kwargs):
            self.name = str(link)

        def __enter__(self):
            return str(link)

        def __exit__(self, *exc_info):
            return False

    monkeypatch.setattr("scyvera.vectors.tempfile.TemporaryDirectory", _LinkedTempDir)

    run = run_suite(load_suite(VECTORS_ROOT))
    assert run.failed == 0, [failure.to_dict() for failure in run.failures]


# ---------------------------------------------------------------------------
# Fail-closed suite configuration (exit code 2)
# ---------------------------------------------------------------------------


def test_missing_suite_version_fails_closed(tmp_path: Path) -> None:
    root = _copy_suite(tmp_path)
    (root / "suite-version").unlink()

    with pytest.raises(VectorSuiteError, match="missing"):
        load_suite(root)


def test_malformed_suite_version_fails_closed(tmp_path: Path) -> None:
    root = _copy_suite(tmp_path)
    (root / "suite-version").write_text(
        "suite-version: 01\n", encoding="utf-8", newline="\n"
    )

    with pytest.raises(VectorSuiteError, match="suite-version"):
        load_suite(root)


def test_version_directory_mismatch_fails_closed(tmp_path: Path) -> None:
    root = _copy_suite(tmp_path)
    (root / "suite-version").write_text(
        "suite-version: 2\n", encoding="utf-8", newline="\n"
    )

    with pytest.raises(VectorSuiteError, match="v2.*missing"):
        load_suite(root)


def test_malformed_vector_names_the_file(tmp_path: Path) -> None:
    root = _copy_suite(tmp_path)
    target = root / "v1" / "gate-decision" / "gd-0001-declared-permission-allowed.json"
    target.write_text("{not json", encoding="utf-8", newline="\n")

    with pytest.raises(VectorSuiteError) as excinfo:
        load_suite(root)
    assert target.name in str(excinfo.value)


def test_non_canonical_vector_fails_closed(tmp_path: Path) -> None:
    root = _copy_suite(tmp_path)
    target = root / "v1" / "gate-decision" / "gd-0001-declared-permission-allowed.json"
    target.write_text(
        json.dumps(json.loads(target.read_text(encoding="utf-8"))),
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(VectorSuiteError, match="canonical"):
        load_suite(root)


def test_unknown_envelope_key_fails_closed(tmp_path: Path) -> None:
    root = _copy_suite(tmp_path)
    target = root / "v1" / "trace-roundtrip" / "tr-0003-absent-provisional-parsed.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    target.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(VectorSuiteError, match="unknown key"):
        load_suite(root)


def test_unknown_category_directory_fails_closed(tmp_path: Path) -> None:
    """RFC 0005 section 6.1: the category names are exact and closed."""
    root = _copy_suite(tmp_path)
    (root / "v1" / "promotion").mkdir()

    with pytest.raises(VectorSuiteError, match="unknown category 'promotion'"):
        load_suite(root)


def test_wrong_vector_suite_version_fails_closed(tmp_path: Path) -> None:
    root = _copy_suite(tmp_path)
    target = root / "v1" / "contract-model" / "cm-0003-provisional-absent-valid.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["suite_version"] = 0
    target.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(VectorSuiteError, match="must equal suite-version 1"):
        load_suite(root)


def test_symlinked_root_is_refused(tmp_path: Path) -> None:
    real = _copy_suite(tmp_path)
    link = tmp_path / "linked-vectors"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this platform")

    with pytest.raises(VectorSuiteError, match="symlink"):
        load_suite(link)


# ---------------------------------------------------------------------------
# CLI exit-code matrix and unified JSON
# ---------------------------------------------------------------------------


def test_cli_passes_and_prints_per_category_counts(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    code, out, err = _run_cli(monkeypatch, capsys, "--root", str(VECTORS_ROOT))

    assert code == 0
    assert err == ""
    assert out.splitlines()[0] == (
        "PASS  33 vectors (suite-version 1): 33 passed, 0 failed"
    )
    assert "      contract-model: 11 passed, 0 failed" in out
    assert "      gate-decision: 13 passed, 0 failed" in out
    assert "      trace-roundtrip: 9 passed, 0 failed" in out


def test_cli_returns_one_on_a_failing_vector(
    monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path
) -> None:
    root = _copy_suite(tmp_path)
    target = root / "v1" / "gate-decision" / "gd-0001-declared-permission-allowed.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["expect"]["decisions"] = ["DENIED"]
    target.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    code, out, err = _run_cli(monkeypatch, capsys, "--root", str(root))

    assert code == 1
    assert err == ""
    assert "FAIL  33 vectors" in out
    assert "gd-0001-declared-permission-allowed" in out


def test_cli_returns_two_on_a_suite_error(
    monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path
) -> None:
    root = _copy_suite(tmp_path)
    (root / "suite-version").write_text(
        "suite-version: 2\n", encoding="utf-8", newline="\n"
    )

    code, out, err = _run_cli(monkeypatch, capsys, "--root", str(root))

    assert code == 2
    assert out == ""
    assert "scyvera vectors: error:" in err


def test_cli_json_is_a_valid_unified_envelope(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    code, out, err = _run_cli(
        monkeypatch, capsys, "--root", str(VECTORS_ROOT), "--json"
    )

    assert code == 0
    assert err == ""
    payload = json.loads(out)
    Draft202012Validator(load_report_schema()).validate(payload)
    assert payload["mode"] == "vectors"
    assert payload["status"] == "PASS"
    assert payload["summary"] == {
        "suite_version": 1,
        "total": 33,
        "passed": 33,
        "failed": 0,
    }
    assert payload["data"] == {
        "suite_version": 1,
        "total": 33,
        "passed": 33,
        "failed": 0,
        "failures": [],
    }


def test_cli_json_status_is_fail_for_a_failing_vector(
    monkeypatch: pytest.MonkeyPatch, capsys, tmp_path: Path
) -> None:
    root = _copy_suite(tmp_path)
    target = root / "v1" / "trace-roundtrip" / "tr-0003-absent-provisional-parsed.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["expect"] = {
        "result": "rejected",
        "error_code": "TraceError",
        "message_contains": "never",
    }
    target.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    code, out, _ = _run_cli(
        monkeypatch, capsys, "--root", str(root), "--json"
    )

    assert code == 1
    payload = json.loads(out)
    assert payload["status"] == "FAIL"
    assert payload["findings"][0]["id"] == "tr-0003-absent-provisional-parsed"


def test_cli_json_is_deterministic(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    first = _run_cli(monkeypatch, capsys, "--root", str(VECTORS_ROOT), "--json")[1]
    second = _run_cli(monkeypatch, capsys, "--root", str(VECTORS_ROOT), "--json")[1]

    assert first == second


# ---------------------------------------------------------------------------
# RFC 0005 section 8 Q8: check on a provisional contract
# ---------------------------------------------------------------------------


def test_check_warns_on_a_provisional_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    contract = _provisional_contract(tmp_path / "contract.yaml")
    monkeypatch.setattr("sys.argv", ["scyvera", "check", str(contract), "--tier", "0"])

    code = main()
    out = capsys.readouterr().out

    assert code == 0  # warn-only, matching the lint convention
    assert out.splitlines()[0].startswith("WARN  ")
    assert out.splitlines()[0].endswith("(tier 0 (structural): provisional contract)")
    assert "[provisional]" in out
    assert "scyvera promote" in out


def test_check_on_a_non_provisional_contract_is_unchanged(tmp_path: Path) -> None:
    contract = _provisional_contract(tmp_path / "contract.yaml")
    contract.write_text(
        contract.read_text(encoding="utf-8").replace("provisional: true\n", ""),
        encoding="utf-8",
    )

    report = check_contract(contract, tier="0")
    text = render_check(report)

    assert report.provisional is False
    assert text.splitlines()[0].startswith("PASS  ")
    assert text.splitlines()[0].endswith(
        "(tier 0 (structural): 0 schema errors, 0 semantic warnings)"
    )
    assert "[provisional]" not in text


def test_check_report_dict_omits_provisional_when_false(tmp_path: Path) -> None:
    contract = _provisional_contract(tmp_path / "contract.yaml")

    provisional = check_contract(contract, tier="0")
    assert provisional.to_dict()["provisional"] is True

    full = contract.with_name("full.yaml")
    full.write_text(
        contract.read_text(encoding="utf-8").replace("provisional: true\n", ""),
        encoding="utf-8",
    )
    assert "provisional" not in check_contract(full, tier="0").to_dict()


# ---------------------------------------------------------------------------
# Atomic provisional write (GE-2 follow-up)
# ---------------------------------------------------------------------------


def _draft() -> dict:
    return {
        "version": 1.1,
        "provisional": True,
        "system": {"name": "atomic-agent"},
        "lifecycle": {"mode": "request-response", "initiation": "human-only"},
        "permissions": [],
        "side_effects": [],
    }


def test_atomic_write_replaces_only_after_validation(tmp_path: Path) -> None:
    target = tmp_path / "contract.yaml"
    write_provisional_contract(_draft(), target)

    assert target.is_file()
    assert "provisional: true" in target.read_text(encoding="utf-8")
    assert list(tmp_path.glob(".*.tmp")) == []


def test_failed_validation_leaves_the_old_file_untouched(tmp_path: Path) -> None:
    target = tmp_path / "contract.yaml"
    target.write_text("OLD CONTRACT\n", encoding="utf-8")

    with pytest.raises(ValueError, match="failed"):
        write_provisional_contract({"version": 99}, target)

    assert target.read_text(encoding="utf-8") == "OLD CONTRACT\n"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_failed_validation_leaves_nothing_when_no_old_file(tmp_path: Path) -> None:
    target = tmp_path / "contract.yaml"

    with pytest.raises(ValueError, match="failed"):
        write_provisional_contract({"version": 99}, target)

    assert not target.exists()
    assert list(tmp_path.glob(".*.tmp")) == []


def test_crash_during_replace_leaves_the_old_file_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "contract.yaml"
    target.write_text("OLD CONTRACT\n", encoding="utf-8")

    def explode(source, destination):
        raise OSError("simulated crash")

    monkeypatch.setattr("scyvera.generate.os.replace", explode)

    with pytest.raises(OSError, match="simulated crash"):
        write_provisional_contract(_draft(), target)

    assert target.read_text(encoding="utf-8") == "OLD CONTRACT\n"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_crash_mid_write_leaves_no_partial_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "contract.yaml"

    def half_write(draft, path):
        Path(path).write_text("version: 1.1\nprovisional: tr", encoding="ascii")
        raise OSError("simulated mid-write crash")

    monkeypatch.setattr("scyvera.generate.write_draft", half_write)

    with pytest.raises(OSError, match="mid-write"):
        write_provisional_contract(_draft(), target)

    assert not target.exists()
    assert list(tmp_path.glob(".*.tmp")) == []


def test_written_contract_loads_only_in_draft_mode(tmp_path: Path) -> None:
    target = tmp_path / "contract.yaml"
    write_provisional_contract(_draft(), target)

    draft = ContractEnforcer.load(target, mode="draft")
    assert draft.is_provisional is True
    with pytest.raises(ProvisionalContractError):
        ContractEnforcer.load(target)


# ---------------------------------------------------------------------------
# Promotion non-negotiables (tests, not vectors: RFC 0005 sections 6.1/6.10)
# ---------------------------------------------------------------------------


def _promotable(tmp_path: Path) -> tuple[Path, ContractRegistry]:
    contract = _provisional_contract(tmp_path / "contract.yaml")
    registry = ContractRegistry(tmp_path / "registry.jsonl")
    ContractEnforcer.load(contract, mode="draft").register(registry)
    contract.write_text(
        contract.read_text(encoding="utf-8").replace("provisional: true\n", ""),
        encoding="utf-8",
    )
    return contract, registry


def test_silent_promotion_is_rejected(tmp_path: Path) -> None:
    contract, registry = _promotable(tmp_path)

    with pytest.raises(ResealError, match="PromotionIntent"):
        reseal(contract, registry)


def test_hand_editing_the_flag_away_is_not_a_promotion(tmp_path: Path) -> None:
    contract, registry = _promotable(tmp_path)

    with pytest.raises(ProvisionalContractError, match="draft entry"):
        ContractEnforcer.load(contract, registry=registry)


def test_repeat_promotion_is_refused(tmp_path: Path) -> None:
    contract, registry = _promotable(tmp_path)
    reseal(
        contract,
        registry,
        promotion=PromotionIntent(reviewer="alice", intent="reviewed"),
    )

    with pytest.raises(ResealError, match="not a promotion"):
        reseal(
            contract,
            registry,
            promotion=PromotionIntent(reviewer="alice", intent="again"),
        )


def test_there_is_no_time_based_promotion() -> None:
    import inspect

    from scyvera import reseal as reseal_function

    parameters = set(inspect.signature(reseal_function).parameters)

    assert not {"expires_at", "max_age", "ttl", "schedule"} & parameters
