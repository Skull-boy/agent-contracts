"""Standard-library + scyvera reference agent for the M2.4 eval harness.

The eval harness calls one method per scenario action, named by lowercasing
the action and replacing runs of non-alphanumeric characters with ``_``:

- ``github:issues:read`` -> ``github_issues_read``
- ``db:write`` -> ``db_write``
- ``admin:delete`` -> ``admin_delete``

Every method performs exactly one gated call. ``admin:delete`` is declared in
the contract on purpose *not* to exist, so the scenario can exercise the
constraint axis with a real default-deny violation.
"""
from __future__ import annotations

from typing import Any

from scyvera import ContractEnforcer


class RefundAgent:
    """Minimal refund agent whose public methods are gated at construction."""

    def __init__(self, enforcer: ContractEnforcer) -> None:
        self.executed: list[str] = []
        self.github_issues_read = enforcer.gate(
            "github:issues:read", "read"
        )(self._read_issue)
        self.db_write = enforcer.gate(
            "db:write", "side_effect"
        )(self._write_record)
        self.admin_delete = enforcer.gate(
            "admin:delete", "permission"
        )(self._delete_everything)

    def _read_issue(self) -> dict[str, Any]:
        self.executed.append("read")
        return {"issue": 1, "title": "refund request"}

    def _write_record(self) -> str:
        self.executed.append("write")
        return "refund recorded"

    def _delete_everything(self) -> str:
        self.executed.append("delete")
        return "deleted"


def make_agent(enforcer: ContractEnforcer) -> RefundAgent:
    """Factory consumed by the harness: ``factory(enforcer) -> object``."""
    return RefundAgent(enforcer)
