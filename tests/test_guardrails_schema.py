"""Schema, linter, and CLI coverage for the v1.2 guardrails slice (M2.6).

RFC 0003 §C5 adds one optional top-level ``guardrails`` object in v1.2:
``fail_closed``, ``budgets`` (``side_effects_per_window`` + ``window``), and
``rate_limit`` (``max_calls_per_minute``). The slice must be additive:

- every v1/v1.1 contract keeps its exact current validation result;
- bumping only the version to 1.2 never turns a valid contract invalid;
- malformed guardrails are rejected rather than silently ignored;
- a pre-v1.2 contract that still carries ``guardrails`` lints with AC701 so a
  team cannot believe a budget is enforced when the runtime ignores it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scyvera import (
    SCHEMA_V1_1_PATH,
    SCHEMA_V1_2_PATH,
    ContractVersion,
    apply_lifecycle_defaults,
    detect_contract_version,
    lint_contract,
    validate_contract,
)
from scyvera.cli import main as cli_main
import yaml


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
PACKAGED_V1_2 = ROOT / "src" / "scyvera" / "schemas" / "v1.2" / "contract.schema.json"
ROOT_V1_2 = ROOT / "schemas" / "v1.2" / "contract.schema.json"

_BASE = """version: 1.2
system:
  name: Guardrail Demo
permissions:
  - github:issues:read
side_effects:
  - db:write
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "contract.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _guarded(body: str) -> str:
    return _BASE + body


def _contract_fixtures() -> list[tuple[str, Path, dict]]:
    """Return parseable, version-detectable contract fixtures.

    Audit fixtures are scanner inputs, not contracts, and malformed/empty root
    fixtures have no version to read, so they are excluded by construction.
    """
    found: list[tuple[str, Path, dict]] = []
    for path in sorted(FIXTURES.rglob("*.yaml")):
        if "audit" in path.parts:
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        if detect_contract_version(data) is None:
            continue
        found.append((path.relative_to(FIXTURES).as_posix(), path, data))
    return found


# ---------------------------------------------------------------------------
# Strict-superset properties
# ---------------------------------------------------------------------------


def test_packaged_v12_schema_matches_repository_copy() -> None:
    assert ROOT_V1_2.exists()
    assert PACKAGED_V1_2.exists()
    assert SCHEMA_V1_2_PATH.exists()
    assert (
        ROOT_V1_2.read_text(encoding="utf-8")
        == PACKAGED_V1_2.read_text(encoding="utf-8")
    )


def test_v12_schema_is_a_strict_superset_of_v11() -> None:
    v11 = json.loads(SCHEMA_V1_1_PATH.read_text(encoding="utf-8"))
    v12 = json.loads(SCHEMA_V1_2_PATH.read_text(encoding="utf-8"))

    assert v12["required"] == v11["required"]
    assert v12["anyOf"] == v11["anyOf"]
    assert v12["if"] == v11["if"]
    assert v12["then"] == v11["then"]
    assert v12["additionalProperties"] is True
    assert v11["additionalProperties"] is True

    for name, definition in v11["properties"].items():
        if name == "version":
            continue
        assert v12["properties"][name] == definition, name

    assert v12["properties"]["version"]["oneOf"] == [
        {"type": "number", "const": 1.2},
        {"type": "string", "const": "1.2"},
    ]
    guardrails = v12["properties"]["guardrails"]
    assert guardrails["additionalProperties"] is False
    assert set(guardrails["properties"]) == {
        "fail_closed",
        "budgets",
        "rate_limit",
    }


@pytest.mark.parametrize(
    ("relpath", "path", "data"),
    _contract_fixtures(),
    ids=[item[0] for item in _contract_fixtures()],
)
def test_fixture_result_is_unchanged_when_only_version_is_bumped(
    tmp_path: Path,
    relpath: str,
    path: Path,
    data: dict,
) -> None:
    original = validate_contract(path)

    bumped = copy.deepcopy(data)
    bumped["version"] = 1.2
    if "contract_version" in bumped:
        bumped["contract_version"] = "1.2"
    candidate = _write(tmp_path, yaml.safe_dump(bumped, sort_keys=False))
    upgraded = validate_contract(candidate)

    assert upgraded.valid is original.valid, relpath
    if original.valid:
        assert upgraded.errors == (), relpath


def test_valid_fixtures_keep_passing_under_their_own_version() -> None:
    passing = {
        relpath
        for relpath, path, _data in _contract_fixtures()
        if validate_contract(path).valid
    }
    assert "github_contract.yaml" in passing
    assert "v1.1/valid-minimal.yaml" in passing
    assert "v1.1/valid-full.yaml" in passing


# ---------------------------------------------------------------------------
# Valid v1.2 shapes
# ---------------------------------------------------------------------------


def test_guardrails_absent_is_valid(tmp_path: Path) -> None:
    result = validate_contract(_write(tmp_path, _BASE))
    assert result.valid is True
    assert result.errors == ()


def test_empty_guardrails_is_an_explicit_noop(tmp_path: Path) -> None:
    result = validate_contract(_write(tmp_path, _guarded("guardrails: {}\n")))
    assert result.valid is True
    assert result.errors == ()


def test_full_guardrails_block_is_valid(tmp_path: Path) -> None:
    body = (
        "guardrails:\n"
        "  fail_closed: true\n"
        "  budgets:\n"
        "    side_effects_per_window: 10\n"
        '    window: "1h"\n'
        "  rate_limit:\n"
        "    max_calls_per_minute: 30\n"
    )
    result = validate_contract(_write(tmp_path, _guarded(body)))
    assert result.valid is True
    assert result.errors == ()


@pytest.mark.parametrize("window", ["1s", "30m", "2h", "7d"])
def test_supported_window_units_validate(tmp_path: Path, window: str) -> None:
    body = (
        "guardrails:\n"
        "  budgets:\n"
        "    side_effects_per_window: 1\n"
        f'    window: "{window}"\n'
    )
    result = validate_contract(_write(tmp_path, _guarded(body)))
    assert result.valid is True


# ---------------------------------------------------------------------------
# Malformed guardrails are rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        # Unknown key at each level
        "guardrails:\n  side_effects_per_hour: 5\n",
        (
            "guardrails:\n"
            "  budgets:\n"
            "    side_effects_per_hour: 5\n"
            '    window: "1h"\n'
        ),
        (
            "guardrails:\n"
            "  rate_limit:\n"
            "    max_calls_per_hour: 5\n"
        ),
        # Budget limits must be positive integers
        (
            "guardrails:\n"
            "  budgets:\n"
            "    side_effects_per_window: 0\n"
            '    window: "1h"\n'
        ),
        (
            "guardrails:\n"
            "  budgets:\n"
            "    side_effects_per_window: -1\n"
            '    window: "1h"\n'
        ),
        # Window grammar
        (
            "guardrails:\n"
            "  budgets:\n"
            "    side_effects_per_window: 1\n"
            '    window: "1w"\n'
        ),
        (
            "guardrails:\n"
            "  budgets:\n"
            "    side_effects_per_window: 1\n"
            '    window: "hour"\n'
        ),
        (
            "guardrails:\n"
            "  budgets:\n"
            "    side_effects_per_window: 1\n"
            '    window: ""\n'
        ),
        # Rate limit must be a positive integer
        "guardrails:\n  rate_limit:\n    max_calls_per_minute: 0\n",
        "guardrails:\n  rate_limit:\n    max_calls_per_minute: -1\n",
        # Type errors
        "guardrails: []\n",
        "guardrails: not-an-object\n",
        "guardrails:\n  fail_closed: yes-please\n",
        "guardrails:\n  fail_closed: 1\n",
        "guardrails:\n  budgets: []\n",
        "guardrails:\n  rate_limit: []\n",
    ],
)
def test_malformed_guardrails_are_rejected(tmp_path: Path, body: str) -> None:
    result = validate_contract(_write(tmp_path, _guarded(body)))
    assert result.valid is False
    assert result.errors
    assert any(
        "guardrails" in error.path or "guardrails" in error.message
        for error in result.errors
    )


def test_unsupported_version_still_errors_identically(tmp_path: Path) -> None:
    result = validate_contract(
        _write(tmp_path, "version: 2.0\nsystem:\n  name: Future\n")
    )
    assert result.valid is False
    assert len(result.errors) == 1
    assert result.errors[0].path == "version"
    assert "Unsupported specification version" in result.errors[0].message


# ---------------------------------------------------------------------------
# Version detection and lifecycle defaults
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "contract",
    [
        {"version": 1.2},
        {"version": "1.2"},
        {"contract_version": "1.2"},
        {"version": 1.1, "contract_version": "1.2"},
    ],
)
def test_v12_version_detection(contract: dict) -> None:
    assert detect_contract_version(contract) is ContractVersion.V1_2


def test_v12_lifecycle_defaults_match_v11_behavior() -> None:
    contract = {"version": 1.2, "system": {"name": "No Lifecycle"}}
    filled = apply_lifecycle_defaults(contract)
    assert filled["lifecycle"] == {
        "mode": "request-response",
        "initiation": "human-only",
        "resumability": "stateless",
    }
    assert "lifecycle" not in contract  # input is not mutated

    v1 = {"version": 1, "workflow": "plain"}
    assert apply_lifecycle_defaults(v1) is v1


# ---------------------------------------------------------------------------
# AC701: pre-v1.2 guardrails are ignored
# ---------------------------------------------------------------------------


def test_ac701_warns_on_v11_guardrails(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "version: 1.1\n"
        "system:\n"
        "  name: Old Contract\n"
        "guardrails:\n"
        "  rate_limit:\n"
        "    max_calls_per_minute: 5\n",
    )
    assert validate_contract(path).valid is True
    result = lint_contract(path)
    assert result.valid_structure is True
    ac701 = [warning for warning in result.warnings if warning.rule_id == "AC701"]
    assert len(ac701) == 1
    assert ac701[0].severity == "warning"
    assert "version 1.2" in ac701[0].message
    assert "IGNORED" in ac701[0].message


def test_ac701_warns_on_v1_guardrails(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "version: 1\n"
        "workflow: legacy\n"
        "inputs: []\n"
        "outputs: []\n"
        "permissions: []\n"
        "side_effects: []\n"
        "approval_points: []\n"
        "recovery_strategy: none\n"
        "replay_semantics: none\n"
        "dependencies: []\n"
        "state: none\n"
        "observability: []\n"
        "guardrails:\n"
        "  fail_closed: true\n",
    )
    assert validate_contract(path).valid is True
    result = lint_contract(path)
    assert [warning.rule_id for warning in result.warnings].count("AC701") == 1


def test_ac701_does_not_fire_on_v12_guardrails(tmp_path: Path) -> None:
    body = (
        "guardrails:\n"
        "  fail_closed: true\n"
        "  budgets:\n"
        "    side_effects_per_window: 2\n"
        '    window: "1h"\n'
    )
    result = lint_contract(_write(tmp_path, _guarded(body)))
    assert result.valid_structure is True
    assert "AC701" not in {warning.rule_id for warning in result.warnings}


# ---------------------------------------------------------------------------
# CLI sanity
# ---------------------------------------------------------------------------


def test_cli_validate_lint_check_accept_v12_guardrails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    body = (
        "guardrails:\n"
        "  fail_closed: true\n"
        "  budgets:\n"
        "    side_effects_per_window: 2\n"
        '    window: "1h"\n'
        "  rate_limit:\n"
        "    max_calls_per_minute: 10\n"
    )
    path = _write(tmp_path, _guarded(body))

    for command in ("validate", "lint", "check"):
        monkeypatch.setattr("sys.argv", ["scyvera", command, str(path)])
        assert cli_main() == 0, command

    output = capsys.readouterr().out
    assert "0 semantic warnings" in output or "PASS" in output


def test_cli_rejects_malformed_guardrails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _write(
        tmp_path,
        _guarded(
            "guardrails:\n"
            "  budgets:\n"
            "    side_effects_per_hour: 5\n"
            '    window: "1h"\n'
        ),
    )
    for command in ("validate", "lint", "check"):
        monkeypatch.setattr("sys.argv", ["scyvera", command, str(path)])
        assert cli_main() == 1, command
        output = capsys.readouterr().out
        assert "FAIL" in output, command
        if command == "lint":
            # The linter's documented convention is AC000 for any structural
            # failure; validate/check surface the underlying schema error.
            assert "AC000" in output, command
        else:
            assert "guardrails" in output, command


def test_cli_lint_warns_but_exits_zero_on_v11_guardrails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _write(
        tmp_path,
        "version: 1.1\n"
        "system:\n"
        "  name: Old Contract\n"
        "guardrails:\n"
        "  fail_closed: true\n",
    )
    monkeypatch.setattr("sys.argv", ["scyvera", "lint", str(path)])
    assert cli_main() == 0
    output = capsys.readouterr().out
    assert "WARN" in output
    assert "AC701" in output
