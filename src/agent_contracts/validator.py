from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json

import yaml
from jsonschema import Draft202012Validator


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


def load_schema(path: str | Path) -> dict[str, Any]:
    """Load an Agent Contract JSON Schema."""
    schema_path = Path(path)

    with schema_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def validate_contract(
    contract_path: str | Path,
    schema_path: str | Path,
) -> ValidationResult:
    """
    Validate one Agent Contract against an Agent Contract JSON Schema.

    This function performs no printing and does not terminate the process.
    Callers decide how validation results should be presented.
    """
    contract = load_contract(contract_path)
    schema = load_schema(schema_path)

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