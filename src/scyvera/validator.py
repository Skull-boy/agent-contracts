from dataclasses import dataclass
from enum import Enum
import importlib.resources
import json
import logging
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .exceptions import ContractFileNameError

logger = logging.getLogger(__name__)

PACKAGE_ROOT = Path(__file__).resolve().parent


def _resolve_package_schema(relative_path: str) -> Path:
    """Resolve packaged schema path using importlib.resources with fallback."""
    try:
        traversable = importlib.resources.files("scyvera").joinpath(relative_path)
        p = Path(str(traversable))
        if p.exists():
            return p
    except Exception:
        pass
    return PACKAGE_ROOT / relative_path


SCHEMA_V1_PATH = _resolve_package_schema("schemas/v1/contract.schema.json")
SCHEMA_V1_1_PATH = _resolve_package_schema("schemas/v1.1/contract.schema.json")
DEFAULT_SCHEMA_PATH = SCHEMA_V1_PATH


class ContractVersion(Enum):
    """Supported Agent Contract specification versions."""
    V1 = "1"
    V1_1 = "1.1"


# DESIGN DECISION: These defaults are applied by the loader when a v1.1
# contract omits the lifecycle field. This matches the user-approved design:
# lifecycle is optional at the schema level, defaults applied here with a
# logging.warning() so contract authors know they're operating on inferred
# values and can make it explicit.
LIFECYCLE_DEFAULTS: dict[str, Any] = {
    "mode": "request-response",
    "initiation": "human-only",
    "resumability": "stateless",
}


@dataclass(frozen=True)
class ValidationError:
    path: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[ValidationError, ...]


def detect_contract_version(contract: dict[str, Any]) -> ContractVersion | None:
    """Detect the contract specification version.

    Priority:
      1. Explicit ``contract_version`` field (added in v1.1)
      2. ``version`` field value
      3. Default to V1 if neither is present
      4. Return None if an unsupported version is explicitly specified
    """
    # DESIGN DECISION: Version detection is explicit, not inferred from field
    # presence. contract_version is checked first because it is the v1.1+
    # discriminator. The version field is the fallback for v1 contracts.
    cv = contract.get("contract_version")
    if cv is not None:
        cv_str = str(cv)
        if cv_str == "1.1":
            return ContractVersion.V1_1
        if cv_str == "1":
            return ContractVersion.V1
        return None

    if "version" in contract:
        version = contract.get("version")
        if version == 1.1 or version == "1.1":
            return ContractVersion.V1_1
        if version == 1 or version == "1":
            return ContractVersion.V1
        if version is None:
            return ContractVersion.V1
        return None

    return ContractVersion.V1


def apply_lifecycle_defaults(contract: dict[str, Any]) -> dict[str, Any]:
    """Apply lifecycle defaults for v1.1 contracts missing the lifecycle field.

    Returns a shallow copy of the contract with lifecycle populated.
    Emits a logging.warning() when defaults are applied so contract
    authors know they are operating on inferred values.

    Only applies to v1.1 contracts. v1 contracts are returned unchanged.
    """
    version = detect_contract_version(contract)
    if version != ContractVersion.V1_1:
        return contract

    if "lifecycle" not in contract:
        logger.warning(
            "Contract does not declare a lifecycle field. "
            "Applying defaults: %s. Make lifecycle explicit to silence this warning.",
            LIFECYCLE_DEFAULTS,
        )
        result = dict(contract)
        result["lifecycle"] = dict(LIFECYCLE_DEFAULTS)
        return result

    return contract


def load_contract(path: str | Path) -> Any:
    """Load an Agent Contract from a YAML file.

    Raises ContractFileNameError if the file uses .yml instead of .yaml.
    """
    contract_path = Path(path)

    # DESIGN DECISION: The spec mandates contract.yaml as the canonical name.
    # We reject .yml at load time rather than silently accepting it, because
    # silent acceptance would let inconsistent naming propagate through the
    # ecosystem. The error message is actionable — it tells the author exactly
    # what to do and where the requirement is documented.
    if contract_path.suffix == ".yml":
        raise ContractFileNameError(str(contract_path))

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

    version = detect_contract_version(contract)
    if version == ContractVersion.V1:
        return SCHEMA_V1_PATH
    if version == ContractVersion.V1_1:
        return SCHEMA_V1_1_PATH

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