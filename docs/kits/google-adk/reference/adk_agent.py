"""Illustrative Google ADK + Scyvera wiring for the adoption kit.

This file is a reference artifact, not a runtime dependency of the kit:

* Google ADK is the adopter's framework, not a Scyvera dependency.
* The kit's verify scripts never import or execute this module.
* Replace the ``NotImplementedError`` bodies with your own clients.

The boundary this file demonstrates: ADK decides *which tool* the model asks
for; the Scyvera gate decides *whether that tool may run*. Every externally
reaching ADK tool must sit behind ``enforcer.gate(...)``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from google.adk.agents import LlmAgent

from scyvera.enforcer import ContractEnforcer

CONTRACT_PATH = Path("contract.yaml")
REGISTRY_PATH = Path("registry.jsonl")


def build_enforcer(mode: Literal["full", "draft"] = "full") -> ContractEnforcer:
    """Load the contract that is actually on disk.

    ``full`` is the production path. It refuses ``provisional: true`` with
    ``ProvisionalContractError``. Do not catch that error and silently fall
    back to draft mode: the mode is a human decision, not an agent decision.

    ``draft`` is only for a provisional contract written to disk (for example
    by ``scyvera init --infer``). Draft mode still denies undeclared actions
    and still puts irreversible actions behind an approval gate.
    """
    return ContractEnforcer.load(CONTRACT_PATH, mode=mode, registry=REGISTRY_PATH)


def build_agent(enforcer: ContractEnforcer) -> LlmAgent:
    """Build the ADK agent and fail closed on any ungated tool."""

    @enforcer.gate("support:read", "read")
    def read_issue(issue_number: int) -> dict[str, Any]:
        """Read one issue through the adopter's client."""
        raise NotImplementedError("wire the GitHub read client here")

    @enforcer.gate("support:comment", "side_effect")
    def post_comment(issue_number: int, body: str) -> str:
        """Post one triage comment through the adopter's client."""
        raise NotImplementedError("wire the GitHub comment client here")

    @enforcer.gate("support:close", "side_effect")
    def close_issue(issue_number: int) -> None:
        """Close an issue.

        The gate raises ``ApprovalPendingError`` until a human calls
        ``enforcer.approve("support:close")`` through a review channel the
        agent cannot reach.
        """
        raise NotImplementedError("wire the GitHub close client here")

    tools = [read_issue, post_comment, close_issue]

    # A tool registered outside the gate is invisible to Scyvera. Refuse to
    # construct the agent in that state instead of pretending it is governed.
    for tool in tools:
        ContractEnforcer.assert_gated(tool)

    return LlmAgent(
        name="support_triage_agent",
        model="gemini-2.0-flash",
        instruction=(
            "Read the issue, draft a bounded reply, and stop. Never close an "
            "issue: closing is a human decision."
        ),
        tools=tools,
    )


def main() -> None:
    enforcer = build_enforcer()
    agent = build_agent(enforcer)
    # ADK's Runner is orchestration. Every tool call still passes through the
    # enforcer's gate before any external effect.
    print(f"built {agent.name} with {len(agent.tools)} gated tools")


if __name__ == "__main__":
    main()
