"""
Gate integrity tests — verify that gated calls fail closed when
contracts are tampered with on disk or in memory.

These tests MUST FAIL against the current code (where _check_gate()
does not call verify_integrity()). After the fix in Phase 3, they
should all PASS.
"""
from __future__ import annotations

import asyncio
import json
import pytest

from scyvera import (
    AuditEntry,
    ContractEnforcer,
    ContractTamperError,
    ContractViolationError,
)


# ────────────────────────────────────────────────────────────────
# Helper: build a minimal inline contract yaml in tmp_path
# ────────────────────────────────────────────────────────────────

def _minimal_contract_yaml(tmp_path) -> Path:
    """Write a minimal valid contract yaml and return its Path."""
    p = tmp_path / "contract.yaml"
    p.write_text(
        "version: 1.1\n"
        "system:\n"
        "  name: test-agent\n"
        "lifecycle:\n"
        "  mode: request-response\n"
        "permissions:\n"
        "  - resource: tasks\n"
        "    actions: [read]\n"
        "side_effects: []\n"
        "approval_points: []\n"
        "recovery_strategy: retry\n"
        "replay_semantics: idempotent\n"
        "dependencies: []\n"
        "state: none\n"
        "observability: []\n",
        encoding="utf-8",
    )
    return p


# ────────────────────────────────────────────────────────────────
# 1. File contract edited after load
# ────────────────────────────────────────────────────────────────

def test_file_contract_edited_after_load_raises_tamper(
    tmp_path,
):
    """Gated call raises ContractTamperError after file edit; body does NOT run; audit = DENIED."""
    from scyvera.enforcer import ContractEnforcer as _CE

    contract_path = _minimal_contract_yaml(tmp_path)
    agent = _CE.load(contract_path)

    # Flag to prove the wrapped body never executed
    ran = False

    @agent.gate("tasks:read", "read")
    def read_task() -> str:
        nonlocal ran
        ran = True
        return "queued task"

    # Edit the contract on disk
    contract_path.write_text(
        contract_path.read_text(encoding="utf-8") + "\n# rogue permissions injected after load",
        encoding="utf-8",
    )

    # The gated call must fail closed
    with pytest.raises(ContractTamperError):
        read_task()

    # Body must not have run
    assert ran is False, "Wrapped body should NOT run after tamper"

    # Audit log must contain a DENIED entry
    audit = agent.get_audit_log()
    denied = [e for e in audit if e.decision == "DENIED"]
    assert len(denied) >= 1, "Expected at least one DENIED audit entry after tamper"


# ────────────────────────────────────────────────────────────────
# 2. File contract deleted after load
# ────────────────────────────────────────────────────────────────

def test_file_contract_deleted_after_load_raises_tamper(
    tmp_path,
):
    """After deleting the contract file, verify_integrity (and gate) raises ContractTamperError, not OSError."""
    contract_path = _minimal_contract_yaml(tmp_path)
    agent = ContractEnforcer.load(contract_path)

    # Delete the file from disk
    contract_path.unlink()

    # verify_integrity must raise ContractTamperError, not FileNotFoundError/OSError
    with pytest.raises(ContractTamperError):
        agent.verify_integrity()

    # Also: a gated call should raise ContractTamperError, not FileNotFoundError
    ran = False

    @agent.gate("tasks:read", "read")
    def read_task() -> str:
        nonlocal ran
        ran = True
        return "queued task"

    with pytest.raises(ContractTamperError):
        read_task()

    assert ran is False


# ────────────────────────────────────────────────────────────────
# 3. File rewritten with identical bytes: calls still work
# ────────────────────────────────────────────────────────────────

def test_file_rewritten_identical_bytes_calls_still_work(tmp_path):
    """Rewriting a contract file with identical bytes does NOT break gated calls."""
    contract_path = _minimal_contract_yaml(tmp_path)
    agent = ContractEnforcer.load(contract_path)

    ran = False

    @agent.gate("tasks:read", "read")
    def read_task() -> str:
        nonlocal ran
        ran = True
        return "queued task"

    # Rewrite with identical bytes
    original = contract_path.read_bytes()
    contract_path.write_bytes(original)  # identical content

    result = read_task()
    assert result == "queued task"
    assert ran is True

    # Audit should have an ALLOWED entry
    audit = agent.get_audit_log()
    allowed = [e for e in audit if e.decision == "ALLOWED"]
    assert len(allowed) >= 1


# ────────────────────────────────────────────────────────────────
# 4. Declaration contract's sealed state altered
# ────────────────────────────────────────────────────────────────

def test_declaration_tampered_sealed_state_raises_tamper(
    tmp_path,
):
    """Mutating a declaration contract's sealed state raises ContractTamperError; gated body not executed; audit = DENIED."""
    declaration = {
        "node_id": "test-agent-v1",
        "permissions": ["tasks:read"],
        "side_effects": [],
        "approval_points": [],
        "lifecycle": "request-response",
        "state": "none",
        "recovery_strategy": "retry",
        "observability": {},  # must be dict, not list
    }
    agent = ContractEnforcer.from_declaration(declaration)

    # Mutate the sealed declaration (simulates memory attack)
    agent._sealed_declaration["permissions"] = ["admin:*"]

    ran = False

    @agent.gate("tasks:read", "read")
    def read_task() -> str:
        nonlocal ran
        ran = True
        return "queued task"

    # Must raise ContractTamperError, not silently pass
    with pytest.raises(ContractTamperError):
        read_task()

    # Body must not have run
    assert ran is False

    # Audit must contain DENIED entry
    audit = agent.get_audit_log()
    denied = [e for e in audit if e.decision == "DENIED"]
    assert len(denied) >= 1


# ────────────────────────────────────────────────────────────────
# 5. Tamper after an approval was granted: still blocked
# ────────────────────────────────────────────────────────────────

def test_tamper_after_approval_still_blocked(tmp_path):
    """Granting approval does NOT bypass integrity verification after tamper."""
    contract_path = _minimal_contract_yaml(tmp_path)
    agent = ContractEnforcer.load(contract_path)

    # Grant a manual approval
    agent.approve("tasks:read")

    # Tamper with the contract on disk
    contract_path.write_text(
        contract_path.read_text(encoding="utf-8") + "\n# rogue permissions",
        encoding="utf-8",
    )

    ran = False

    @agent.gate("tasks:read", "read")
    def read_task() -> str:
        nonlocal ran
        ran = True
        return "queued task"

    # Must still be blocked even though approval was granted
    with pytest.raises(ContractTamperError):
        read_task()

    assert ran is False


# ────────────────────────────────────────────────────────────────
# 6. read, permission and side_effect action types all blocked on tamper
# ────────────────────────────────────────────────────────────────

def test_all_action_types_blocked_on_tamper(tmp_path):
    """read, permission and side_effect are all blocked when contract is tampered."""
    from scyvera.enforcer import ContractEnforcer as _CE

    # --- read (permission) ---
    p1 = tmp_path / "c1.yaml"
    p1.write_text(
        "version: 1.1\n"
        "system:\n"
        "  name: test-agent\n"
        "lifecycle:\n"
        "  mode: request-response\n"
        "permissions:\n"
        "  - resource: tasks\n"
        "    actions: [read]\n"
        "side_effects: []\n"
        "approval_points: []\n"
        "recovery_strategy: retry\n"
        "dependencies: []\n"
        "state: none\n"
        "observability: []\n",
        encoding="utf-8",
    )
    agent = _CE.load(p1)

    # Edit contract on disk
    p1.write_text(
        p1.read_text(encoding="utf-8") + "\n# rogue permissions",
        encoding="utf-8",
    )

    ran_read = False
    @agent.gate("tasks:read", "read")
    def do_read() -> None:
        nonlocal ran_read
        ran_read = True
    with pytest.raises(ContractTamperError):
        do_read()
    assert ran_read is False

    # --- permission ---
    p2 = tmp_path / "c2.yaml"
    p2.write_text(
        "version: 1.1\n"
        "system:\n"
        "  name: test-agent\n"
        "lifecycle:\n"
        "  mode: request-response\n"
        "permissions:\n"
        "  - resource: prod_cluster\n"
        "    actions: [deploy]\n"
        "side_effects: []\n"
        "approval_points: []\n"
        "recovery_strategy: retry\n"
        "dependencies: []\n"
        "state: none\n"
        "observability: []\n",
        encoding="utf-8",
    )
    agent2 = _CE.load(p2)

    p2.write_text(
        p2.read_text(encoding="utf-8") + "\n# rogue permissions",
        encoding="utf-8",
    )

    ran_perm = False
    @agent2.gate("github:issues:write", "permission")
    def do_perm() -> None:
        nonlocal ran_perm
        ran_perm = True
    with pytest.raises(ContractTamperError):
        do_perm()
    assert ran_perm is False

    # --- side_effect ---
    p3 = tmp_path / "c3.yaml"
    p3.write_text(
        "version: 1.1\n"
        "system:\n"
        "  name: test-agent\n"
        "lifecycle:\n"
        "  mode: request-response\n"
        "permissions: []\n"
        "side_effects: []\n"
        "approval_points: []\n"
        "recovery_strategy: retry\n"
        "dependencies: []\n"
        "state: none\n"
        "observability: []\n",
        encoding="utf-8",
    )
    agent3 = _CE.load(p3)

    p3.write_text(
        p3.read_text(encoding="utf-8") + "\n# rogue permissions",
        encoding="utf-8",
    )

    ran_se = False
    @agent3.gate("comment", "side_effect")
    def do_side_effect() -> None:
        nonlocal ran_se
        ran_se = True
    with pytest.raises(ContractTamperError):
        do_side_effect()
    assert ran_se is False


# ────────────────────────────────────────────────────────────────
# 7. Tamper blocks GitHubGateway and QdrantGateway methods
# ────────────────────────────────────────────────────────────────

def test_tamper_blocks_gateway_methods(tmp_path, monkeypatch):
    """Tampering the contract blocks both GitHubGateway and QdrantGateway methods."""
    from scyvera.enforcer import ContractEnforcer as _CE
    import sys as _sys

# --- GitHubGateway ---
    contract_path = _minimal_contract_yaml(tmp_path)
    agent = _CE.load(contract_path)

    # Tamper on disk
    contract_path.write_text(
        contract_path.read_text(encoding="utf-8") + "\n# rogue permissions",
        encoding="utf-8",
    )

    # Ensure github module exists with a Github class before the gateway imports it
    github_mod = type("github", (), {"Github": type("Github", (), {})})()
    _sys.modules["github"] = github_mod

    from scyvera.gateway import GitHubGateway

    gw = GitHubGateway(agent, "token-123")

    ran = False
    try:
        gw.post_comment("org/repo", 1, "body")
        ran = True  # should not reach here
    except ContractTamperError:
        pass  # expected — integrity check blocked the call

    assert ran is False

    # Restore
    del _sys.modules["github"]

    # --- QdrantGateway ---
    contract_path2 = tmp_path / "q2.yaml"
    contract_path2.write_text(
        "version: 1.1\n"
        "system:\n"
        "  name: test-agent\n"
        "lifecycle:\n"
        "  mode: request-response\n"
        "permissions: []\n"
        "side_effects: []\n"
        "approval_points: []\n"
        "recovery_strategy: retry\n"
        "dependencies: []\n"
        "state: none\n"
        "observability: []\n",
        encoding="utf-8",
    )
    agent2 = _CE.load(contract_path2)

    # Tamper on disk
    contract_path2.write_text(
        contract_path2.read_text(encoding="utf-8") + "\n# rogue permissions",
        encoding="utf-8",
    )

    # Ensure qdrant_client module exists with QdrantClient class
    qdrant_mod = type("qdrant_client", (), {"QdrantClient": type("QdrantClient", (), {})})()
    _sys.modules["qdrant_client"] = qdrant_mod

    from scyvera.gateway import QdrantGateway

    gw2 = QdrantGateway(agent2, "http://localhost:6533", "api-key-123")

    ran2 = False
    try:
        gw2.search("collection", [0.1, 0.2, 0.3])
        ran2 = True  # should not reach here
    except ContractTamperError:
        pass  # expected — integrity check blocked the call

    assert ran2 is False

    # Restore
    del _sys.modules["qdrant_client"]


# ────────────────────────────────────────────────────────────────
# 8. Untouched contract: normal calls work, no extra audit entries
# ────────────────────────────────────────────────────────────────

def test_untouched_contract_normal_calls_work(tmp_path):
    """Contract not tampered: gated calls succeed normally, no unexpected audit entries."""
    contract_path = _minimal_contract_yaml(tmp_path)
    agent = ContractEnforcer.load(contract_path)

    ran = False

    @agent.gate("tasks:read", "read")
    def read_task() -> str:
        nonlocal ran
        ran = True
        return "queued task"

    result = read_task()
    assert result == "queued task"
    assert ran is True

    audit = agent.get_audit_log()
    allowed = [e for e in audit if e.decision == "ALLOWED"]
    # At minimum the gate decision + the execution
    assert len(allowed) >= 1


# ────────────────────────────────────────────────────────────────
# 9. Two enforcers: tampering one leaves the other working
# ────────────────────────────────────────────────────────────────

def test_two_enforcers_tampering_one_leaves_other_working(tmp_path):
    """Tampering one enforcer's contract does NOT affect the other enforcer."""
    # Create contract paths directly under tmp_path (avoid nested dirs)
    p1 = tmp_path / "enc1.yaml"
    p2 = tmp_path / "enc2.yaml"
    p1.write_text(
        "version: 1.1\n"
        "system:\n"
        "  name: test-agent\n"
        "lifecycle:\n"
        "  mode: request-response\n"
        "permissions:\n"
        "  - resource: tasks\n"
        "    actions: [read]\n"
        "side_effects: []\n"
        "approval_points: []\n"
        "recovery_strategy: retry\n"
        "dependencies: []\n"
        "state: none\n"
        "observability: []\n",
        encoding="utf-8",
    )
    p2.write_text(
        "version: 1.1\n"
        "system:\n"
        "  name: test-agent-2\n"
        "lifecycle:\n"
        "  mode: request-response\n"
        "permissions:\n"
        "  - resource: tasks\n"
        "    actions: [read]\n"
        "side_effects: []\n"
        "approval_points: []\n"
        "recovery_strategy: retry\n"
        "dependencies: []\n"
        "state: none\n"
        "observability: []\n",
        encoding="utf-8",
    )

    agent1 = ContractEnforcer.load(p1)
    agent2 = ContractEnforcer.load(p2)

    # Tamper only agent1's contract
    p1.write_text(
        p1.read_text(encoding="utf-8") + "\n# rogue permissions",
        encoding="utf-8",
    )

    # agent2's gated call must still work fine
    ran = False

    @agent2.gate("tasks:read", "read")
    def read_task() -> str:
        nonlocal ran
        ran = True
        return "queued task"

    result = read_task()
    assert result == "queued task"
    assert ran is True

    # agent1's gated call must be blocked
    ran1 = False

    @agent1.gate("tasks:read", "read")
    def read_task1() -> str:
        nonlocal ran1
        ran1 = True
        return "queued task 1"

    with pytest.raises(ContractTamperError):
        read_task1()
    assert ran1 is False


# ────────────────────────────────────────────────────────────────
# 10. Violation message for declaration contract contains node_id, never 'None'
# ────────────────────────────────────────────────────────────────

def test_declaration_violation_message_contains_node_id(tmp_path):
    """ContractViolationError for declaration contracts must contain node_id, never the text 'None'."""
    declaration = {
        "node_id": "my-special-agent-v1",
        "permissions": ["tasks:read"],
        "side_effects": [],
        "approval_points": [],
        "lifecycle": "request-response",
        "state": "none",
        "recovery_strategy": "retry",
        "observability": {},  # must be dict, not list
    }
    agent = ContractEnforcer.from_declaration(declaration)

    try:
        @agent.gate("admin:delete", "side_effect")
        def delete_thing() -> None:
            pass
        delete_thing()
    except ContractViolationError as exc:
        msg = str(exc)
        # Must contain the node_id, NOT the literal word "None"
        assert "my-special-agent-v1" in msg, (
            f"Violation message should contain node_id 'my-special-agent-v1', got: {msg}"
        )
        assert "None" not in msg, (
            f"Violation message must not contain the literal 'None', got: {msg}"
        )


# ────────────────────────────────────────────────────────────────
# 11. Violation message for file contract contains the file name
# ────────────────────────────────────────────────────────────────

def test_file_violation_message_contains_file_name(tmp_path):
    """ContractViolationError for file contracts must contain the file name, never the literal 'None'."""
    contract_path = _minimal_contract_yaml(tmp_path)
    agent = ContractEnforcer.load(contract_path)

    try:
        @agent.gate("aws_s3:read", "permission")
        def read_s3() -> None:
            pass
        read_s3()
    except ContractViolationError as exc:
        msg = str(exc)
        # Must contain the contract file name, not the literal "None"
        assert "contract.yaml" in msg, (
            f"Violation message should contain contract file name, got: {msg}"
        )
        assert "None" not in msg, (
            f"Violation message must not contain the literal 'None', got: {msg}"
        )


# ────────────────────────────────────────────────────────────────
# 12. Tamper message includes recovery guidance
# ────────────────────────────────────────────────────────────────

def test_tamper_message_includes_recovery_guidance(tmp_path):
    """ContractTamperError message must end with recovery guidance."""
    contract_path = _minimal_contract_yaml(tmp_path)
    agent = ContractEnforcer.load(contract_path)

    # Tamper the contract on disk
    contract_path.write_text(
        contract_path.read_text(encoding="utf-8") + "\n# rogue permissions",
        encoding="utf-8",
    )

    try:
        agent.verify_integrity()
    except ContractTamperError as exc:
        msg = str(exc)
        # Must end with guidance text
        lower = msg.lower()
        assert "reload" in lower or "restart" in lower, (
            f"Tamper error message must include reload or restart guidance, got: {msg}"
        )


# ────────────────────────────────────────────────────────────────
# 13. Async gated functions also fail closed on tamper
# ────────────────────────────────────────────────────────────────

def test_async_gated_function_blocked_on_tamper(tmp_path):
    """Async gated functions are also blocked when contract is tampered."""
    from scyvera.enforcer import ContractEnforcer as _CE

    contract_path = _minimal_contract_yaml(tmp_path)
    agent = _CE.load(contract_path)

    # Tamper on disk
    contract_path.write_text(
        contract_path.read_text(encoding="utf-8") + "\n# rogue permissions",
        encoding="utf-8",
    )

    ran = False

    @agent.gate("tasks:read", "read")
    async def async_read_task() -> str:
        nonlocal ran
        ran = True
        return "queued task async"

    # Must raise ContractTamperError even for async
    with pytest.raises(ContractTamperError):
        asyncio.run(async_read_task())

    assert ran is False