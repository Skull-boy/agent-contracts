from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .validator import load_contract, validate_contract


@dataclass(frozen=True)
class LintWarning:
    rule_id: str
    title: str
    message: str
    severity: str = "warning"  # "warning" or "error"


@dataclass(frozen=True)
class LintResult:
    valid_structure: bool
    warnings: tuple[LintWarning, ...]


def lint_contract(contract_path: str | Path) -> LintResult:
    """
    Perform Tier 2 semantic analysis on an Agent Contract.
    Evaluates semantic consistency rules (ACxxx taxonomy) beyond structural JSON Schema validation.
    """
    val_res = validate_contract(contract_path)
    if not val_res.valid:
        return LintResult(
            valid_structure=False,
            warnings=(
                LintWarning(
                    rule_id="AC000",
                    title="Structural Validation Failed",
                    message="Contract must pass Tier 1 structural validation before semantic linting.",
                    severity="error",
                ),
            ),
        )

    contract = load_contract(contract_path)
    if not isinstance(contract, dict):
        return LintResult(valid_structure=True, warnings=())

    warnings: list[LintWarning] = []

    # Rule AC101: Permission write action without declared side effect
    permissions = contract.get("permissions", [])
    side_effects = contract.get("side_effects", [])
    se_resources = set()
    for se in side_effects:
        if isinstance(se, dict) and "resource" in se:
            se_resources.add(se["resource"])

    for perm in permissions:
        if isinstance(perm, dict):
            res_name = perm.get("resource")
            actions = perm.get("actions", [])
            if any(act in ("write", "create", "update", "delete", "initiate_transaction") for act in actions):
                if res_name and res_name not in se_resources and not side_effects:
                    warnings.append(
                        LintWarning(
                            rule_id="AC101",
                            title="Unbounded Write Permission",
                            message=f"Permission grants write action on '{res_name}' but no side_effects are declared.",
                            severity="warning",
                        )
                    )

    # Rule AC103: Capability name duplicating operational permission verb
    capabilities = contract.get("capabilities", [])
    for cap in capabilities:
        cap_name = cap.get("name") if isinstance(cap, dict) else str(cap)
        if isinstance(cap_name, str):
            lowered = cap_name.lower()
            if any(lowered.startswith(prefix) for prefix in ("read_", "write_", "delete_", "create_", "update_")):
                warnings.append(
                    LintWarning(
                        rule_id="AC103",
                        title="Capability Duplicating Permission",
                        message=f"Capability '{cap_name}' appears to duplicate an operational permission. Capabilities should express high-level semantic intent.",
                        severity="warning",
                    )
                )

    # Rule AC201: High risk level without approval requirements
    risk = contract.get("risk", {})
    risk_level = risk.get("level") if isinstance(risk, dict) else None
    approvals = contract.get("approvals", [])

    if risk_level in ("high", "critical") and not approvals:
        warnings.append(
            LintWarning(
                rule_id="AC201",
                title="Unprotected High-Risk System",
                message=f"Risk level is '{risk_level}' but no approval boundaries are specified in 'approvals'.",
                severity="warning",
            )
        )

    # Rule AC401: Required dependency without recovery strategy
    dependencies = contract.get("dependencies", [])
    recovery = contract.get("recovery")

    has_required_dep = any(
        isinstance(d, dict) and d.get("required", True) for d in dependencies
    )
    if has_required_dep and (recovery is None or recovery == "none" or (isinstance(recovery, dict) and recovery.get("strategy") == "none")):
        warnings.append(
            LintWarning(
                rule_id="AC401",
                title="Missing Recovery Strategy for Required Dependency",
                message="Contract lists required dependencies but specifies no recovery strategy.",
                severity="warning",
            )
        )

    # Rule AC601: Observable side effect with observability level none
    observability = contract.get("observability")
    obs_level = None
    if isinstance(observability, dict):
        obs_level = observability.get("level")
    elif isinstance(observability, str):
        obs_level = observability

    if side_effects and obs_level == "none":
        warnings.append(
            LintWarning(
                rule_id="AC601",
                title="Unobserved Side Effect",
                message="Contract declares external side_effects but observability level is 'none'.",
                severity="warning",
            )
        )

    return LintResult(
        valid_structure=True,
        warnings=tuple(warnings),
    )
