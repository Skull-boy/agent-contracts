from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import tempfile
import yaml

from .validator import validate_contract, ValidationResult


@dataclass
class SystemIdentity:
    name: str
    purpose: str | None = None
    version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"name": self.name}
        if self.purpose is not None:
            data["purpose"] = self.purpose
        if self.version is not None:
            data["version"] = self.version
        return data


# Backward-compatibility alias
AgentIdentity = SystemIdentity


class Contract:
    """
    High-level, type-safe programmatic builder for Agent Contracts.
    Allows non-YAML experts to define, serialize, and validate Agent Contracts in Python.
    """
    def __init__(
        self,
        name: str,
        purpose: str | None = None,
        version: float | str = 1.1,
        system_version: str | None = None,
    ) -> None:
        self.version = version
        self.system = SystemIdentity(name=name, purpose=purpose, version=system_version)
        self.agent = self.system  # Backward-compatibility property alias
        self.domain: str | None = None
        self.capabilities: list[dict[str, Any] | str] = []
        self.resources: list[dict[str, Any] | str] = []
        self.inputs: list[dict[str, Any] | str] = []
        self.outputs: list[dict[str, Any] | str] = []
        self.permissions: list[dict[str, Any]] = []
        self.constraints: list[dict[str, Any]] = []
        self.side_effects: list[dict[str, Any] | str] = []
        self.approvals: list[dict[str, Any] | str] = []
        self.dependencies: list[dict[str, Any] | str] = []
        self.state: dict[str, Any] | str | None = None
        self.recovery: dict[str, Any] | str | None = None
        self.replay: dict[str, Any] | str | None = None
        self.observability: dict[str, Any] | list[str] | str | None = None
        self.artifacts: list[dict[str, Any]] = []
        self.security: dict[str, Any] | None = None
        self.risk: dict[str, Any] | None = None
        self.implementation: dict[str, Any] | None = None

    def set_domain(self, domain: str) -> Contract:
        self.domain = domain
        return self

    def add_capability(self, name: str, description: str | None = None) -> Contract:
        if description:
            self.capabilities.append({"name": name, "description": description})
        else:
            self.capabilities.append(name)
        return self

    def add_resource(self, name: str, type: str | None = None, access: str | None = None) -> Contract:
        res: dict[str, Any] = {"name": name}
        if type:
            res["type"] = type
        if access:
            res["access"] = access
        self.resources.append(res)
        return self

    def add_input(self, name: str, type: str | None = None, required: bool = True) -> Contract:
        inp: dict[str, Any] = {"name": name, "required": required}
        if type:
            inp["type"] = type
        self.inputs.append(inp)
        return self

    def add_output(self, name: str, type: str | None = None) -> Contract:
        out: dict[str, Any] = {"name": name}
        if type:
            out["type"] = type
        self.outputs.append(out)
        return self

    def add_permission(self, resource: str, actions: list[str], scope: str | None = None) -> Contract:
        perm: dict[str, Any] = {"resource": resource, "actions": actions}
        if scope:
            perm["scope"] = scope
        self.permissions.append(perm)
        return self

    def add_constraint(
        self,
        type: str,
        maximum: float | int | None = None,
        minimum: float | int | None = None,
        currency: str | None = None,
        unit: str | None = None,
        allowed: list[str] | None = None,
        description: str | None = None,
    ) -> Contract:
        c: dict[str, Any] = {"type": type}
        if maximum is not None:
            c["maximum"] = maximum
        if minimum is not None:
            c["minimum"] = minimum
        if currency is not None:
            c["currency"] = currency
        if unit is not None:
            c["unit"] = unit
        if allowed is not None:
            c["allowed"] = allowed
        if description is not None:
            c["description"] = description
        self.constraints.append(c)
        return self

    def add_side_effect(self, type: str, resource: str | None = None, description: str | None = None) -> Contract:
        se: dict[str, Any] = {"type": type}
        if resource:
            se["resource"] = resource
        if description:
            se["description"] = description
        self.side_effects.append(se)
        return self

    def add_approval(self, action: str, required: bool = True, approver: str | None = None, condition: str | None = None) -> Contract:
        app: dict[str, Any] = {"action": action, "required": required}
        if approver:
            app["approver"] = approver
        if condition:
            app["condition"] = condition
        self.approvals.append(app)
        return self

    def add_dependency(self, name: str, type: str | None = None, required: bool = True) -> Contract:
        dep: dict[str, Any] = {"name": name, "required": required}
        if type:
            dep["type"] = type
        self.dependencies.append(dep)
        return self

    def set_state(self, persistence: str, scope: str | None = None, storage: str | None = None) -> Contract:
        st: dict[str, Any] = {"persistence": persistence}
        if scope:
            st["scope"] = scope
        if storage:
            st["storage"] = storage
        self.state = st
        return self

    def set_recovery(self, strategy: str, details: str | None = None) -> Contract:
        rec: dict[str, Any] = {"strategy": strategy}
        if details:
            rec["details"] = details
        self.recovery = rec
        return self

    def set_replay(self, mode: str, details: str | None = None) -> Contract:
        rep: dict[str, Any] = {"mode": mode}
        if details:
            rep["details"] = details
        self.replay = rep
        return self

    def set_observability(self, level: str, sinks: list[str] | None = None) -> Contract:
        obs: dict[str, Any] = {"level": level}
        if sinks:
            obs["sinks"] = sinks
        self.observability = obs
        return self

    def add_artifact(
        self,
        name: str,
        type: str,
        source: str | None = None,
        integrity_required: bool = False,
        provenance_required: bool = False,
    ) -> Contract:
        art: dict[str, Any] = {
            "name": name,
            "type": type,
            "integrity_required": integrity_required,
            "provenance_required": provenance_required,
        }
        if source:
            art["source"] = source
        self.artifacts.append(art)
        return self

    def set_risk(self, level: str, category: str | None = None) -> Contract:
        r: dict[str, Any] = {"level": level}
        if category:
            r["category"] = category
        self.risk = r
        return self

    def set_implementation(
        self,
        framework: str | None = None,
        runtime: str | None = None,
        language: str | None = None,
        repository: str | None = None,
    ) -> Contract:
        impl: dict[str, Any] = {}
        if framework:
            impl["framework"] = framework
        if runtime:
            impl["runtime"] = runtime
        if language:
            impl["language"] = language
        if repository:
            impl["repository"] = repository
        self.implementation = impl
        return self

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"version": self.version}

        if self.version in (1.1, "1.1"):
            data["system"] = self.system.to_dict()
        else:
            data["agent"] = self.agent.to_dict()

        if self.domain:
            data["domain"] = self.domain
        if self.capabilities:
            data["capabilities"] = self.capabilities
        if self.resources:
            data["resources"] = self.resources
        if self.inputs:
            data["inputs"] = self.inputs
        if self.outputs:
            data["outputs"] = self.outputs
        if self.permissions:
            data["permissions"] = self.permissions
        if self.constraints:
            data["constraints"] = self.constraints
        if self.side_effects:
            data["side_effects"] = self.side_effects
        if self.approvals:
            data["approvals"] = self.approvals
        if self.dependencies:
            data["dependencies"] = self.dependencies
        if self.state is not None:
            data["state"] = self.state
        if self.recovery is not None:
            data["recovery"] = self.recovery
        if self.replay is not None:
            data["replay"] = self.replay
        if self.observability is not None:
            data["observability"] = self.observability
        if self.artifacts:
            data["artifacts"] = self.artifacts
        if self.security is not None:
            data["security"] = self.security
        if self.risk is not None:
            data["risk"] = self.risk
        if self.implementation is not None:
            data["implementation"] = self.implementation
        return data

    def to_yaml(self) -> str:
        return yaml.dump(self.to_dict(), sort_keys=False)

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            yaml.dump(self.to_dict(), f, sort_keys=False)
        return p

    def validate(self) -> ValidationResult:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as tmp:
            tmp_path = Path(tmp.name)
            yaml.dump(self.to_dict(), tmp, sort_keys=False)

        try:
            return validate_contract(tmp_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
