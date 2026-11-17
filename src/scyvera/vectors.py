"""Conformance vector suite loader and runner (RFC 0005 section 6, GE-3).

The suite under ``vectors/`` is the shared acceptance corpus for every GEP
runtime. This module is the **Python reference runner**; it is not part of the
cross-runtime contract. The contract is the bytes: ``suite-version``, the
per-version directory, and the canonical JSON envelopes described in RFC 0005
sections 6.1-6.8.

Design rules inherited from the RFC and the rest of the package:

* Fail closed. A missing/malformed ``suite-version``, an unknown envelope key,
  a wrong category or version, a duplicate ID, a symlink, or a non-canonical
  vector file raises :class:`VectorSuiteError` naming the file. Nothing is
  coerced.
* Execute every vector, sorted by ID, and never stop at the first failure.
* Produce a deterministic result object: no timestamps, no absolute paths, no
  host object addresses, failures sorted by ID. Two runs over the same suite
  serialize to identical bytes.
* Never write to ``vectors/`` and never import or execute a target
  implementation. Contracts are materialized in a temporary directory.

The categories are exactly the three RFC 0005 section 6.1 names:
``contract-model``, ``gate-decision``, and ``trace-roundtrip``. Promotion
orchestration is deliberately absent (section 6.10 and section 8 Q5).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import re
import tempfile
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence

import yaml

from .enforcer import ContractEnforcer
from .exceptions import (
    ApprovalPendingError,
    ContractTamperError,
    ContractValidationError,
    ContractViolationError,
    GuardrailViolationError,
    ProvisionalContractError,
    TraceError,
)
from .trace import TraceLog
from .validator import validate_contract

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids import cycles
    from .unified import UnifiedReport

__all__ = [
    "CATEGORIES",
    "SUITE_VERSION_FILENAME",
    "Vector",
    "VectorFailure",
    "VectorRun",
    "VectorSuite",
    "VectorSuiteError",
    "load_suite",
    "run_suite",
]

#: The three category directory names. RFC 0005 section 6.1: exact and closed.
CATEGORIES: tuple[str, ...] = (
    "contract-model",
    "gate-decision",
    "trace-roundtrip",
)

#: The single source of truth for the corpus version.
SUITE_VERSION_FILENAME: str = "suite-version"

_CATEGORY_PREFIX: Mapping[str, str] = {
    "contract-model": "cm",
    "gate-decision": "gd",
    "trace-roundtrip": "tr",
}

_SUITE_VERSION_RE = re.compile(r"^suite-version: (0|[1-9][0-9]*)\n$")
_VECTOR_ID_RE = re.compile(
    r"^(cm|gd|tr)-[0-9]{4}-[a-z0-9]+(?:-[a-z0-9]+)*$"
)

_ENVELOPE_REQUIRED = frozenset(
    {
        "vector_version",
        "suite_version",
        "category",
        "id",
        "description",
        "input",
        "expect",
    }
)
_ENVELOPE_OPTIONAL = frozenset({"notes"})

_CANONICAL_CODES = frozenset(
    {
        "ContractViolationError",
        "ApprovalPendingError",
        "ProvisionalContractError",
        "ContractValidationError",
        "TraceError",
        "GuardrailViolationError",
    }
)


class VectorSuiteError(ValueError):
    """Raised when the vector suite cannot be loaded or is structurally invalid.

    This is the suite-configuration failure the CLI maps to exit code ``2``.
    The message always names the offending file or directory.
    """


@dataclass(frozen=True)
class Vector:
    """One validated conformance vector.

    ``input`` and ``expect`` are read-only mappings. ``path`` is loader
    metadata and is never serialized into results.
    """

    suite_version: int
    category: str
    id: str
    description: str
    input: Mapping[str, Any]
    expect: Mapping[str, Any]
    notes: str | None
    path: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "input", MappingProxyType(dict(self.input)))
        object.__setattr__(self, "expect", MappingProxyType(dict(self.expect)))


@dataclass(frozen=True)
class VectorSuite:
    """A validated suite: its pinned version and its vectors."""

    suite_version: int
    root: Path
    vectors: tuple[Vector, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "vectors", tuple(self.vectors))


@dataclass(frozen=True)
class VectorFailure:
    """One failed vector; ``reason`` is a stable, path-free sentence."""

    id: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "reason": self.reason}


@dataclass(frozen=True)
class VectorRun:
    """The canonical RFC 0005 section 6.8 result of one suite execution."""

    suite_version: int
    total: int
    passed: int
    failed: int
    failures: tuple[VectorFailure, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "failures", tuple(self.failures))

    def to_dict(self) -> dict[str, Any]:
        """Return the exact five-key canonical result object."""
        return {
            "suite_version": self.suite_version,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "failures": [failure.to_dict() for failure in self.failures],
        }

    def to_json(self) -> str:
        """Serialize the canonical result: sorted keys, compact, one newline."""
        return (
            json.dumps(
                self.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
            + "\n"
        )

    def unified(self) -> "UnifiedReport":
        """Project this run into the RFC 0003 unified envelope (mode vectors)."""
        from .unified import from_vectors_result

        return from_vectors_result(self)


# ---------------------------------------------------------------------------
# Loading (fail closed)
# ---------------------------------------------------------------------------


def _fail(message: str) -> "VectorSuiteError":
    return VectorSuiteError(message)


def _read_text(path: Path, *, what: str) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise _fail(f"cannot read {what} '{path}': {exc}") from exc
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _fail(f"{what} '{path}' is not valid UTF-8: {exc}") from exc


def _parse_suite_version(root: Path) -> int:
    path = root / SUITE_VERSION_FILENAME
    if not path.is_file():
        raise _fail(f"vector suite is missing '{path}'")
    text = _read_text(path, what="suite-version")
    match = _SUITE_VERSION_RE.match(text)
    if match is None:
        raise _fail(
            f"'{path}' must be exactly 'suite-version: <integer>\\n' with no "
            "BOM, comments, or extra keys"
        )
    return int(match.group(1))


def _reject_symlink(path: Path, *, what: str) -> None:
    if path.is_symlink():
        raise _fail(f"{what} '{path}' must not be a symlink (RFC 0005 section 6.1)")


def _no_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VectorSuiteError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _load_json(path: Path) -> tuple[Any, str]:
    text = _read_text(path, what="vector")
    try:
        payload = json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except VectorSuiteError as exc:
        raise _fail(f"vector '{path}': {exc}") from exc
    except json.JSONDecodeError as exc:
        raise _fail(
            f"vector '{path}' is not valid JSON: {exc.msg} at column {exc.colno}"
        ) from exc
    return payload, text


def _require_canonical(path: Path, payload: Any, text: str) -> None:
    canonical = (
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    )
    if text != canonical:
        raise _fail(
            f"vector '{path}' is not in canonical JSON form (sorted keys, "
            "two-space indent, one trailing newline)"
        )


def _require_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise _fail(f"{where} must be a JSON object, got {type(value).__name__}")
    return value


def _require_str(value: Any, where: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise _fail(f"{where} must be a non-empty string")
    return value


def _require_int(value: Any, where: str) -> int:
    if type(value) is not int:
        raise _fail(f"{where} must be an integer, got {type(value).__name__}")
    return value


def _require_bool(value: Any, where: str) -> bool:
    if type(value) is not bool:
        raise _fail(f"{where} must be a boolean, got {type(value).__name__}")
    return value


def _require_error_code(value: Any, where: str) -> str:
    code = _require_str(value, where)
    if code not in _CANONICAL_CODES:
        raise _fail(
            f"{where} must be one of {', '.join(sorted(_CANONICAL_CODES))}, "
            f"got {code!r}"
        )
    return code


def _reject_unknown(
    data: Mapping[str, Any], allowed: frozenset[str], where: str
) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise _fail(f"{where} has unknown key(s): {', '.join(unknown)}")


def _validate_contract_model_input(data: Mapping[str, Any], where: str) -> None:
    _reject_unknown(
        data, frozenset({"operation", "mode", "filename", "contract"}), where
    )
    operation = data.get("operation")
    if operation not in ("validate", "load"):
        raise _fail(f"{where}.operation must be 'validate' or 'load'")
    if operation == "load":
        if "mode" not in data:
            raise _fail(f"{where}.mode is required for operation 'load'")
        if data["mode"] not in ("full", "draft"):
            raise _fail(f"{where}.mode must be 'full' or 'draft'")
    elif "mode" in data:
        raise _fail(f"{where}.mode must be absent for operation 'validate'")
    filename = data.get("filename", "contract.yaml")
    if not isinstance(filename, str) or not filename.endswith(".yaml"):
        raise _fail(f"{where}.filename must be a string ending in '.yaml'")
    _require_mapping(data.get("contract"), f"{where}.contract")


def _validate_gate_input(data: Mapping[str, Any], where: str) -> None:
    _reject_unknown(
        data, frozenset({"mode", "contract", "scenario", "tamper_before"}), where
    )
    if data.get("mode") not in ("full", "draft"):
        raise _fail(f"{where}.mode must be 'full' or 'draft'")
    _require_mapping(data.get("contract"), f"{where}.contract")
    scenario = data.get("scenario")
    if not isinstance(scenario, list) or not scenario:
        raise _fail(f"{where}.scenario must be a non-empty array")
    for index, step in enumerate(scenario):
        step_where = f"{where}.scenario[{index}]"
        step_map = _require_mapping(step, step_where)
        _reject_unknown(
            step_map, frozenset({"action", "action_type", "approve"}), step_where
        )
        _require_str(step_map.get("action"), f"{step_where}.action")
        if step_map.get("action_type") not in ("permission", "side_effect", "read"):
            raise _fail(
                f"{step_where}.action_type must be 'permission', 'side_effect', "
                "or 'read'"
            )
        if "approve" in step_map:
            _require_bool(step_map["approve"], f"{step_where}.approve")
    if "tamper_before" in data:
        _require_bool(data["tamper_before"], f"{where}.tamper_before")


def _validate_trace_input(data: Mapping[str, Any], where: str) -> None:
    _reject_unknown(data, frozenset({"jsonl", "operation"}), where)
    if data.get("operation") not in ("roundtrip", "parse"):
        raise _fail(f"{where}.operation must be 'roundtrip' or 'parse'")
    _require_str(data.get("jsonl"), f"{where}.jsonl", allow_empty=True)


_INPUT_VALIDATORS: Mapping[str, Callable[[Mapping[str, Any], str], None]] = {
    "contract-model": _validate_contract_model_input,
    "gate-decision": _validate_gate_input,
    "trace-roundtrip": _validate_trace_input,
}


def _validate_contract_model_expect(
    data: Mapping[str, Any], where: str
) -> None:
    result = data.get("result")
    if result not in ("valid", "invalid", "loaded", "rejected"):
        raise _fail(f"{where}.result is not a valid contract-model result")
    errors = data.get("errors", [])
    if not isinstance(errors, list):
        raise _fail(f"{where}.errors must be an array")
    if result == "invalid":
        if "errors" not in data:
            raise _fail(f"{where}.errors is required for result 'invalid'")
    elif errors:
        raise _fail(f"{where}.errors must be [] unless result is 'invalid'")
    for index, item in enumerate(errors):
        item_where = f"{where}.errors[{index}]"
        item_map = _require_mapping(item, item_where)
        _reject_unknown(item_map, frozenset({"path", "message_contains"}), item_where)
        if "path" not in item_map:
            raise _fail(f"{item_where}.path is required (use null for any path)")
        if item_map["path"] is not None and not isinstance(item_map["path"], str):
            raise _fail(f"{item_where}.path must be a string or null")
        _require_str(
            item_map.get("message_contains"), f"{item_where}.message_contains"
        )
    if result == "rejected":
        _require_error_code(data.get("error_code"), f"{where}.error_code")
        _require_str(data.get("message_contains"), f"{where}.message_contains")
    elif "error_code" in data or "message_contains" in data:
        raise _fail(
            f"{where}.error_code/message_contains are only valid for 'rejected'"
        )


def _validate_gate_expect(data: Mapping[str, Any], where: str) -> None:
    _reject_unknown(data, frozenset({"decisions", "errors"}), where)
    decisions = data.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        raise _fail(f"{where}.decisions must be a non-empty array")
    for index, decision in enumerate(decisions):
        if decision not in ("ALLOWED", "DENIED", "PENDING"):
            raise _fail(
                f"{where}.decisions[{index}] must be ALLOWED, DENIED, or PENDING"
            )
    errors = data.get("errors", [])
    if not isinstance(errors, list):
        raise _fail(f"{where}.errors must be an array")
    for index, item in enumerate(errors):
        item_where = f"{where}.errors[{index}]"
        item_map = _require_mapping(item, item_where)
        _reject_unknown(
            item_map,
            frozenset({"index", "error_code", "message_contains"}),
            item_where,
        )
        _require_int(item_map.get("index"), f"{item_where}.index")
        if item_map["index"] < 0:
            raise _fail(f"{item_where}.index must be non-negative")
        _require_error_code(
            item_map.get("error_code"), f"{item_where}.error_code"
        )
        _require_str(
            item_map.get("message_contains"), f"{item_where}.message_contains"
        )


def _validate_trace_expect(data: Mapping[str, Any], where: str) -> None:
    _reject_unknown(
        data, frozenset({"result", "canonical_jsonl", "error_code", "message_contains"}),
        where,
    )
    result = data.get("result")
    if result not in ("roundtrip", "parsed", "rejected"):
        raise _fail(f"{where}.result is not a valid trace-roundtrip result")
    if result == "roundtrip":
        _require_str(
            data.get("canonical_jsonl"),
            f"{where}.canonical_jsonl",
            allow_empty=True,
        )
    elif "canonical_jsonl" in data:
        raise _fail(f"{where}.canonical_jsonl is only valid for 'roundtrip'")
    if result == "rejected":
        _require_error_code(data.get("error_code"), f"{where}.error_code")
        _require_str(data.get("message_contains"), f"{where}.message_contains")
    elif "error_code" in data or "message_contains" in data:
        raise _fail(
            f"{where}.error_code/message_contains are only valid for 'rejected'"
        )


_EXPECT_VALIDATORS: Mapping[str, Callable[[Mapping[str, Any], str], None]] = {
    "contract-model": _validate_contract_model_expect,
    "gate-decision": _validate_gate_expect,
    "trace-roundtrip": _validate_trace_expect,
}


def _build_vector(
    payload: Mapping[str, Any],
    *,
    path: Path,
    category: str,
    suite_version: int,
) -> Vector:
    where = f"vector '{path}'"
    _reject_unknown(payload, _ENVELOPE_REQUIRED | _ENVELOPE_OPTIONAL, where)
    missing = sorted(_ENVELOPE_REQUIRED - set(payload))
    if missing:
        raise _fail(f"{where} is missing key(s): {', '.join(missing)}")

    if _require_int(payload["vector_version"], f"{where}.vector_version") != 1:
        raise _fail(f"{where}.vector_version must be 1")
    if (
        _require_int(payload["suite_version"], f"{where}.suite_version")
        != suite_version
    ):
        raise _fail(
            f"{where}.suite_version must equal suite-version {suite_version}"
        )
    if payload["category"] != category:
        raise _fail(f"{where}.category must equal the directory name '{category}'")

    vector_id = _require_str(payload["id"], f"{where}.id")
    if _VECTOR_ID_RE.match(vector_id) is None:
        raise _fail(f"{where}.id is not a valid vector ID")
    if not vector_id.startswith(_CATEGORY_PREFIX[category] + "-"):
        raise _fail(
            f"{where}.id must start with '{_CATEGORY_PREFIX[category]}-' for "
            f"category '{category}'"
        )

    description = _require_str(payload["description"], f"{where}.description")
    if "\n" in description:
        raise _fail(f"{where}.description must be one line with no newline")

    notes = payload.get("notes")
    if notes is not None:
        _require_str(notes, f"{where}.notes")

    vector_input = _require_mapping(payload["input"], f"{where}.input")
    vector_expect = _require_mapping(payload["expect"], f"{where}.expect")
    _INPUT_VALIDATORS[category](vector_input, f"{where}.input")
    _EXPECT_VALIDATORS[category](vector_expect, f"{where}.expect")
    if category == "gate-decision":
        scenario = vector_input["scenario"]
        decisions = vector_expect["decisions"]
        if len(decisions) != len(scenario):
            raise _fail(
                f"{where}.expect.decisions must have one entry per scenario "
                f"step ({len(scenario)}), got {len(decisions)}"
            )

    return Vector(
        suite_version=suite_version,
        category=category,
        id=vector_id,
        description=description,
        input=vector_input,
        expect=vector_expect,
        notes=notes,
        path=path,
    )


def _category_files(category_dir: Path) -> list[Path]:
    try:
        entries = sorted(category_dir.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise _fail(f"cannot read category directory '{category_dir}': {exc}") from exc
    files: list[Path] = []
    for entry in entries:
        _reject_symlink(entry, what="vector entry")
        if entry.is_dir():
            raise _fail(
                f"vector file '{entry}' must not be nested deeper than the "
                "category directory"
            )
        if entry.suffix != ".json":
            raise _fail(
                f"unexpected file '{entry}' in a category directory; vectors "
                "must be named '<id>.json'"
            )
        files.append(entry)
    return files


def load_suite(root: str | Path = "vectors") -> VectorSuite:
    """Load and validate a conformance vector suite.

    Args:
        root: Directory containing ``suite-version`` and ``v<N>/``. Defaults to
            ``vectors`` relative to the current working directory.

    Returns:
        A validated, immutable :class:`VectorSuite`. Version ``0`` returns an
        empty suite (zero vectors).

    Raises:
        VectorSuiteError: On a missing/malformed ``suite-version``, a missing
            version directory, a symlink, a non-canonical or malformed vector,
            a wrong category/version/ID, or a duplicate ID.
    """
    root_path = Path(root)
    if not root_path.exists():
        raise _fail(f"vector suite not found at '{root_path}'")
    if not root_path.is_dir():
        raise _fail(f"vector suite root '{root_path}' is not a directory")
    _reject_symlink(root_path, what="vector suite root")

    suite_version = _parse_suite_version(root_path)
    if suite_version == 0:
        return VectorSuite(suite_version=0, root=root_path, vectors=())

    version_dir = root_path / f"v{suite_version}"
    if not version_dir.is_dir():
        raise _fail(
            f"suite-version is {suite_version} but '{version_dir}' is missing"
        )
    _reject_symlink(version_dir, what="version directory")

    known_entries = set(CATEGORIES)
    try:
        version_entries = sorted(version_dir.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise _fail(f"cannot read version directory '{version_dir}': {exc}") from exc
    for entry in version_entries:
        if entry.name not in known_entries:
            raise _fail(
                f"unknown category '{entry.name}' in '{version_dir}'; allowed "
                f"categories are {', '.join(CATEGORIES)}"
            )

    vectors: list[Vector] = []
    seen_ids: dict[str, Path] = {}
    for category in CATEGORIES:
        category_dir = version_dir / category
        if not category_dir.is_dir():
            raise _fail(f"missing category directory '{category_dir}'")
        _reject_symlink(category_dir, what="category directory")
        for vector_path in _category_files(category_dir):
            payload, text = _load_json(vector_path)
            _require_canonical(vector_path, payload, text)
            payload_map = _require_mapping(payload, f"vector '{vector_path}'")
            vector = _build_vector(
                payload_map,
                path=vector_path,
                category=category,
                suite_version=suite_version,
            )
            if vector_path.stem != vector.id:
                raise _fail(
                    f"vector file '{vector_path}' must be named '{vector.id}.json'"
                )
            if vector.id in seen_ids:
                raise _fail(
                    f"duplicate vector ID '{vector.id}' in '{vector_path}' and "
                    f"'{seen_ids[vector.id]}'"
                )
            seen_ids[vector.id] = vector_path
            vectors.append(vector)

    return VectorSuite(
        suite_version=suite_version,
        root=root_path,
        vectors=tuple(sorted(vectors, key=lambda item: item.id)),
    )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _canonical_code(exc: BaseException) -> str:
    """Map a native exception to the RFC 0005 section 6.7 canonical code.

    ``ContractTamperError`` has no dedicated code in section 6.7. Integrity
    denials are reported as ``ContractViolationError`` (the section's
    "load-time violation" bucket) so the vector stays cross-runtime; the
    message substring still distinguishes tamper in the vector's
    ``message_contains``.
    """
    if isinstance(exc, ProvisionalContractError):
        return "ProvisionalContractError"
    if isinstance(exc, ApprovalPendingError):
        return "ApprovalPendingError"
    if isinstance(exc, GuardrailViolationError):
        return "GuardrailViolationError"
    if isinstance(exc, ContractValidationError):
        return "ContractValidationError"
    if isinstance(exc, TraceError):
        return "TraceError"
    if isinstance(exc, ContractTamperError):
        return "ContractViolationError"
    if isinstance(exc, ContractViolationError):
        return "ContractViolationError"
    return type(exc).__name__


def _json_pointer(path: str) -> str:
    """Convert the validator's dotted path to the RFC 0005 section 6.3 pointer."""
    if not path:
        return ""
    return "/" + path.replace(".", "/")


def _write_contract(
    contract: Mapping[str, Any], directory: Path, filename: str
) -> Path:
    # Resolve before handing the path to the enforcer. macOS exposes /var as a
    # symlink to /private/var and Windows temp dirs can be 8.3 short names
    # (RUNNER~1); the enforcer's T14 escape check compares resolve() output to
    # the addressed directory, so an unresolved temp path looks like an escape.
    directory = Path(directory).resolve()
    path = directory / filename
    path.write_text(
        yaml.safe_dump(dict(contract), sort_keys=True, allow_unicode=False),
        encoding="utf-8",
    )
    return path


def _match_contract_errors(
    expected: Sequence[Mapping[str, Any]],
    actual: Sequence[tuple[str, str]],
    where: str,
) -> str | None:
    remaining = list(actual)
    for item in expected:
        path = item["path"]
        needle = item["message_contains"]
        match = None
        for candidate in remaining:
            if path is not None and candidate[0] != path:
                continue
            if needle not in candidate[1]:
                continue
            match = candidate
            break
        if match is None:
            return (
                f"{where}: no error matched path={path!r} "
                f"message_contains={needle!r}"
            )
        remaining.remove(match)
    if not expected and actual:
        return f"{where}: expected no errors, got {len(actual)}"
    return None


def _run_contract_model(vector: Vector) -> str | None:
    data = vector.input
    expect = vector.expect
    operation = data["operation"]
    with tempfile.TemporaryDirectory(prefix="scyvera-vector-") as tmp:
        contract_path = _write_contract(
            data["contract"], Path(tmp), data.get("filename", "contract.yaml")
        )

        if operation == "validate":
            result = validate_contract(contract_path)
            actual_result = "valid" if result.valid else "invalid"
            if actual_result != expect["result"]:
                if result.errors:
                    first = result.errors[0]
                    detail = f"{first.path}: {first.message}" if first.path else first.message
                else:
                    detail = "no validation errors"
                return (
                    f"expected result {expect['result']!r}, got "
                    f"{actual_result!r} ({detail})"
                )
            if expect["result"] == "invalid":
                actual_errors = [
                    (_json_pointer(error.path), error.message)
                    for error in result.errors
                ]
                return _match_contract_errors(
                    expect["errors"], actual_errors, "validation errors"
                )
            return None

        mode = data["mode"]
        try:
            ContractEnforcer.load(contract_path, mode=mode)
        except Exception as exc:  # noqa: BLE001 - the vector asserts the type
            actual_result = "rejected"
            code = _canonical_code(exc)
            message = str(exc)
        else:
            actual_result = "loaded"
            code = ""
            message = ""

        if actual_result != expect["result"]:
            return (
                f"expected result {expect['result']!r}, got {actual_result!r}"
                + (f" ({code}: {message})" if code else "")
            )
        if expect["result"] == "rejected":
            if code != expect["error_code"]:
                return (
                    f"expected error_code {expect['error_code']!r}, got {code!r}"
                )
            if expect["message_contains"] not in message:
                return (
                    f"expected message_contains {expect['message_contains']!r}, "
                    f"got {message!r}"
                )
        return None


def _decide(
    enforcer: ContractEnforcer, action: str, action_type: str
) -> tuple[str, BaseException | None]:
    try:

        @enforcer.gate(action, action_type)  # type: ignore[arg-type]
        def _probe() -> None:
            return None

        _probe()
    except ApprovalPendingError as exc:
        return "PENDING", exc
    except ContractTamperError as exc:
        return "DENIED", exc
    except ContractViolationError as exc:
        return "DENIED", exc
    return "ALLOWED", None


def _run_gate(vector: Vector) -> str | None:
    data = vector.input
    expect = vector.expect
    scenario = data["scenario"]
    decisions = expect["decisions"]
    if len(decisions) != len(scenario):
        return (
            f"expected {len(decisions)} decisions for {len(scenario)} steps"
        )

    with tempfile.TemporaryDirectory(prefix="scyvera-vector-") as tmp:
        contract_path = _write_contract(
            data["contract"], Path(tmp), "contract.yaml"
        )
        try:
            enforcer = ContractEnforcer.load(contract_path, mode=data["mode"])
        except Exception as exc:  # noqa: BLE001 - a vector contract must load
            return f"contract failed to load: {_canonical_code(exc)}: {exc}"

        if data.get("tamper_before", False):
            contract_path.write_text(
                contract_path.read_text(encoding="utf-8") + "\n# tampered\n",
                encoding="utf-8",
            )

        actual_decisions: list[str] = []
        actual_errors: list[tuple[int, str, str]] = []
        for index, step in enumerate(scenario):
            if step.get("approve", False):
                enforcer.approve(step["action"])
            decision, error = _decide(
                enforcer, step["action"], step["action_type"]
            )
            actual_decisions.append(decision)
            if error is not None:
                actual_errors.append(
                    (index, _canonical_code(error), str(error))
                )

    if actual_decisions != decisions:
        return f"expected decisions {decisions!r}, got {actual_decisions!r}"

    expected_errors = expect.get("errors", [])
    if len(actual_errors) != len(expected_errors):
        return (
            f"expected {len(expected_errors)} error(s), got "
            f"{len(actual_errors)}: {[(i, c) for i, c, _ in actual_errors]!r}"
        )
    by_index = {item["index"]: item for item in expected_errors}
    for index, code, message in actual_errors:
        item = by_index.get(index)
        if item is None:
            return f"unexpected error at step {index}: {code}: {message}"
        if item["error_code"] != code:
            return (
                f"step {index}: expected error_code {item['error_code']!r}, "
                f"got {code!r}"
            )
        if item["message_contains"] not in message:
            return (
                f"step {index}: expected message_contains "
                f"{item['message_contains']!r}, got {message!r}"
            )
    missing = sorted(set(by_index) - {index for index, _, _ in actual_errors})
    if missing:
        return f"expected error(s) at step(s) {missing} but none occurred"
    return None


def _run_trace(vector: Vector) -> str | None:
    data = vector.input
    expect = vector.expect
    operation = data["operation"]

    if operation == "roundtrip":
        try:
            canonical = TraceLog.from_jsonl(data["jsonl"]).to_jsonl()
        except Exception as exc:  # noqa: BLE001 - the vector asserts behavior
            return f"roundtrip raised {_canonical_code(exc)}: {exc}"
        if expect["result"] != "roundtrip":
            return f"expected result {expect['result']!r}, got 'roundtrip'"
        if canonical != expect["canonical_jsonl"]:
            return (
                "canonical_jsonl mismatch: expected "
                f"{expect['canonical_jsonl']!r}, got {canonical!r}"
            )
        return None

    try:
        TraceLog.from_jsonl(data["jsonl"])
    except Exception as exc:  # noqa: BLE001 - the vector asserts behavior
        actual_result = "rejected"
        code = _canonical_code(exc)
        message = str(exc)
    else:
        actual_result = "parsed"
        code = ""
        message = ""

    if actual_result != expect["result"]:
        return f"expected result {expect['result']!r}, got {actual_result!r}"
    if expect["result"] == "rejected":
        if code != expect["error_code"]:
            return f"expected error_code {expect['error_code']!r}, got {code!r}"
        if expect["message_contains"] not in message:
            return (
                f"expected message_contains {expect['message_contains']!r}, "
                f"got {message!r}"
            )
    return None


_EXECUTORS: Mapping[str, Callable[[Vector], str | None]] = {
    "contract-model": _run_contract_model,
    "gate-decision": _run_gate,
    "trace-roundtrip": _run_trace,
}


def run_suite(
    suite: VectorSuite,
    *,
    category: str | None = None,
) -> VectorRun:
    """Execute every vector in ``suite`` (optionally one category).

    Args:
        suite: A validated suite from :func:`load_suite`.
        category: One of :data:`CATEGORIES`, or ``None`` for all three.

    Returns:
        The canonical :class:`VectorRun`, with failures sorted by vector ID.

    Raises:
        VectorSuiteError: If ``category`` is not one of :data:`CATEGORIES`.
    """
    if category is not None and category not in CATEGORIES:
        raise _fail(
            f"unknown category {category!r}; allowed categories are "
            f"{', '.join(CATEGORIES)}"
        )

    selected = [
        vector
        for vector in suite.vectors
        if category is None or vector.category == category
    ]
    failures: list[VectorFailure] = []
    for vector in selected:
        try:
            reason = _EXECUTORS[vector.category](vector)
        except Exception as exc:  # noqa: BLE001 - one bad vector must not abort the suite
            # Keep the reason stable and path-free (RFC 0005 section 6.8).
            reason = f"runner error: {type(exc).__name__}"
        if reason is not None:
            failures.append(VectorFailure(id=vector.id, reason=reason))

    failures.sort(key=lambda item: item.id)
    total = len(selected)
    failed = len(failures)
    return VectorRun(
        suite_version=suite.suite_version,
        total=total,
        passed=total - failed,
        failed=failed,
        failures=tuple(failures),
    )
