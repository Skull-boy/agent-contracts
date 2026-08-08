from dataclasses import dataclass
import importlib.resources
import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

PACKAGE_ROOT = Path(__file__).resolve().parent


def _resolve_package_schema(relative_path: str) -> Path:
    """Resolve packaged schema path using importlib.resources with fallback."""
    try:
        traversable = importlib.resources.files("agent_contracts").joinpath(relative_path)
        p = Path(str(traversable))
        if p.exists():
            return p
    except Exception:
        pass
    return PACKAGE_ROOT / relative_path


SCHEMA_V1_PATH = _resolve_package_schema("schemas/v1/contract.schema.json")
SCHEMA_V1_1_PATH = _resolve_package_schema("schemas/v1.1/contract.schema.json")
DEFAULT_SCHEMA_PATH = SCHEMA_V1_PATH


@dataclass(frozen=True)
class ValidationError:
    path: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[ValidationError, ...]


def load_contract(path: str | Path) -> Any:
    """Load an Agent Contract from a YAML file."""
    contract_path = Path(path)

    with contract_path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def load_schema(path: str | Path = DEFAULT_SCHEMA_PATH) -> dict[str, Any]:
    """Load an Agent Contract JSON Schema."""
    schema_path = Path(path)

    with schema_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def resolve_schema_path(contract: Any, custom_schema_path: str | Path | None = None) -> Path | None:
    """Determine the schema path based on explicit override or contract version."""
    if custom_schema_path is not None:
        return Path(custom_schema_path)

    if not isinstance(contract, dict):
        return SCHEMA_V1_PATH

    version = contract.get("version")

    if version == 1 or version == "1":
        return SCHEMA_V1_PATH
    elif version == 1.1 or version == "1.1":
        return SCHEMA_V1_1_PATH
    elif version is None:
        return SCHEMA_V1_PATH

    return None


def validate_contract(
    contract_path: str | Path,
    schema_path: str | Path | None = None,
) -> ValidationResult:
    """
    Validate one Agent Contract.

    By default, the Contract is validated against the schema matching its
    declared version (v1 or v1.1) bundled with this package.

    A custom schema path may be supplied explicitly for development,
    testing, or experimental schema versions.

    This function performs no printing and does not terminate the process.
    Callers decide how validation results should be presented.
    """
    contract = load_contract(contract_path)

    if contract is None:
        return ValidationResult(
            valid=False,
            errors=(
                ValidationError(
                    path="",
                    message="contract.yaml is empty",
                ),
            ),
        )

    resolved_path = resolve_schema_path(contract, schema_path)

    if resolved_path is None:
        ver = contract.get("version") if isinstance(contract, dict) else None
        return ValidationResult(
            valid=False,
            errors=(
                ValidationError(
                    path="version",
                    message=f"Unsupported specification version: {ver}",
                ),
            ),
        )

    schema = load_schema(resolved_path)

    validator = Draft202012Validator(schema)

    validation_errors = sorted(
        validator.iter_errors(contract),
        key=lambda error: list(error.absolute_path),
    )

    errors = tuple(
        ValidationError(
            path=".".join(str(part) for part in error.absolute_path),
            message=error.message,
        )
        for error in validation_errors
    )

    return ValidationResult(
        valid=not errors,
        errors=errors,
    )