"""
Comprehensive test suite for Scyvera Declaration-based Contract Enforcement.

Verifies:
- from_declaration() creation with valid and invalid inputs
- node_id pattern enforcement
- Wildcard rejection (T7) in declarations
- Unknown field rejection
- Deep copy isolation
- Runtime gate enforcement identical to file-based contracts
- Approval gates on declaration-based enforcers
- Audit log correctness for declaration-based enforcers
- Cryptographic sealing and tamper detection for both file and declaration contracts
- contract_source and node_id property correctness
"""
from pathlib import Path

import pytest

from scyvera import (
    ApprovalPendingError,
    AuditEntry,
    ContractEnforcer,
    ContractTamperError,
    ContractViolationError,
    DeclarationValidationError,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures"
GITHUB_CONTRACT = FIXTURES / "github_contract.yaml"


# =============================================================================
# 1. Creation Tests
# =============================================================================

def test_from_declaration_valid_minimal():
    """Only required fields: node_id, permissions. Must create enforcer without raising."""
    enforcer = ContractEnforcer.from_declaration({
        "node_id": "researcher-v1",
        "permissions": ["qdrant.search"],
    })
    assert enforcer is not None
    assert enforcer.contract_source == "declaration"
    assert enforcer.node_id == "researcher-v1"
    assert enforcer.integrity_hash is not None
    assert len(enforcer.integrity_hash) == 64


def test_from_declaration_valid_full():
    """All fields present and valid. Must create enforcer without raising."""
    enforcer = ContractEnforcer.from_declaration({
        "node_id": "audit-agent-v2",
        "permissions": ["github.read", "qdrant.search"],
        "side_effects": ["github.comment"],
        "approval_points": ["github.merge"],
        "lifecycle": "ephemeral",
        "state": "session",
        "recovery_strategy": "retry",
        "observability": {"level": "audit", "sinks": ["stdout"]},
    })
    assert enforcer is not None
    assert enforcer.contract_source == "declaration"
    assert enforcer.node_id == "audit-agent-v2"


def test_from_declaration_missing_node_id():
    """DeclarationValidationError, field='node_id'."""
    with pytest.raises(DeclarationValidationError) as exc_info:
        ContractEnforcer.from_declaration({
            "permissions": ["github.read"],
        })
    assert exc_info.value.field == "node_id"
    assert "missing required field" in exc_info.value.reason


def test_from_declaration_invalid_node_id_no_version():
    """'researcher' (no -vN suffix) raises DeclarationValidationError."""
    with pytest.raises(DeclarationValidationError) as exc_info:
        ContractEnforcer.from_declaration({
            "node_id": "researcher",
            "permissions": [],
        })
    assert exc_info.value.field == "node_id"
    assert "does not match required pattern" in exc_info.value.reason


def test_from_declaration_invalid_node_id_uppercase():
    """'Researcher-v1' (uppercase) raises DeclarationValidationError."""
    with pytest.raises(DeclarationValidationError) as exc_info:
        ContractEnforcer.from_declaration({
            "node_id": "Researcher-v1",
            "permissions": [],
        })
    assert exc_info.value.field == "node_id"
    assert "does not match required pattern" in exc_info.value.reason


def test_from_declaration_invalid_node_id_underscore():
    """'researcher_agent-v1' (underscore) raises DeclarationValidationError."""
    with pytest.raises(DeclarationValidationError) as exc_info:
        ContractEnforcer.from_declaration({
            "node_id": "researcher_agent-v1",
            "permissions": [],
        })
    assert exc_info.value.field == "node_id"
    assert "does not match required pattern" in exc_info.value.reason


def test_from_declaration_missing_permissions():
    """DeclarationValidationError, field='permissions'."""
    with pytest.raises(DeclarationValidationError) as exc_info:
        ContractEnforcer.from_declaration({
            "node_id": "test-v1",
        })
    assert exc_info.value.field == "permissions"
    assert "missing required field" in exc_info.value.reason


def test_from_declaration_wildcard_in_permissions():
    """Wildcards in permissions raise DeclarationValidationError (T7)."""
    # Glob-style wildcard
    with pytest.raises(DeclarationValidationError) as exc_info:
        ContractEnforcer.from_declaration({
            "node_id": "test-v1",
            "permissions": ["github.*"],
        })
    assert exc_info.value.field == "permissions"
    assert "wildcard" in exc_info.value.reason.lower()

    # Bare wildcard
    with pytest.raises(DeclarationValidationError) as exc_info:
        ContractEnforcer.from_declaration({
            "node_id": "test-v1",
            "permissions": ["*"],
        })
    assert exc_info.value.field == "permissions"
    assert "wildcard" in exc_info.value.reason.lower()


def test_from_declaration_unknown_field():
    """Unknown keys raise DeclarationValidationError with the unknown field name."""
    with pytest.raises(DeclarationValidationError) as exc_info:
        ContractEnforcer.from_declaration({
            "node_id": "test-v1",
            "permissions": [],
            "foo": "bar",
        })
    assert exc_info.value.field == "foo"
    assert "unknown field" in exc_info.value.reason


def test_from_declaration_empty_permissions_allowed():
    """permissions=[] is valid — no actions declared, everything is denied by default."""
    enforcer = ContractEnforcer.from_declaration({
        "node_id": "deny-all-v1",
        "permissions": [],
    })
    assert enforcer is not None
    assert enforcer.node_id == "deny-all-v1"


def test_from_declaration_does_not_hold_reference():
    """Deep copy prevents caller mutation from affecting the sealed declaration."""
    declaration = {
        "node_id": "safe-agent-v1",
        "permissions": ["github.read"],
    }
    enforcer = ContractEnforcer.from_declaration(declaration)

    # Mutate the original dict after creation
    declaration["node_id"] = "TAMPERED"
    declaration["permissions"].append("admin.*")

    # verify_integrity must still pass — proves deep copy was made
    enforcer.verify_integrity()
    assert enforcer.node_id == "safe-agent-v1"


# =============================================================================
# 2. Enforcement Tests (Real ContractEnforcer, Not Mocks)
# =============================================================================

def test_declaration_gate_blocks_undeclared_action():
    """Undeclared action raises ContractViolationError."""
    enforcer = ContractEnforcer.from_declaration({
        "node_id": "test-v1",
        "permissions": ["github.read"],
    })

    @enforcer.gate("github.merge", "side_effect")
    def merge_pr():
        return "merged"

    with pytest.raises(ContractViolationError) as exc_info:
        merge_pr()
    assert exc_info.value.action_name == "github.merge"


def test_declaration_gate_allows_declared_action():
    """Declared action executes without raising."""
    enforcer = ContractEnforcer.from_declaration({
        "node_id": "reader-v1",
        "permissions": ["github.read"],
        "side_effects": ["github.read"],
    })

    @enforcer.gate("github.read", "read")
    def read_issue():
        return "issue data"

    result = read_issue()
    assert result == "issue data"


def test_declaration_gate_blocks_approval_required():
    """Action requiring approval raises ApprovalPendingError."""
    enforcer = ContractEnforcer.from_declaration({
        "node_id": "deploy-v1",
        "permissions": ["prod.deploy"],
        "side_effects": ["prod.deploy"],
        "approval_points": ["prod.deploy"],
    })

    @enforcer.gate("prod.deploy", "side_effect")
    def deploy():
        return "deployed"

    with pytest.raises(ApprovalPendingError) as exc_info:
        deploy()
    assert exc_info.value.action_name == "prod.deploy"


def test_declaration_gate_allows_after_approval_granted():
    """After approval is granted, action executes and audit log shows ALLOWED."""
    enforcer = ContractEnforcer.from_declaration({
        "node_id": "deploy-v1",
        "permissions": ["prod.deploy"],
        "side_effects": ["prod.deploy"],
        "approval_points": ["prod.deploy"],
    })

    @enforcer.gate("prod.deploy", "side_effect")
    def deploy():
        return "deployed"

    # First attempt raises ApprovalPendingError
    with pytest.raises(ApprovalPendingError):
        deploy()

    # Grant approval
    enforcer.approve("prod.deploy", token="AUTH_TOKEN_001")

    # Now it executes
    result = deploy()
    assert result == "deployed"

    audit = enforcer.get_audit_log()
    # PENDING, approval, ALLOWED
    allowed_entries = [e for e in audit if e.decision == "ALLOWED"]
    assert len(allowed_entries) >= 1


def test_declaration_audit_log_records_denied():
    """Undeclared action produces a DENIED audit entry with correct action name."""
    enforcer = ContractEnforcer.from_declaration({
        "node_id": "audited-v1",
        "permissions": ["github.read"],
    })

    @enforcer.gate("admin.delete", "side_effect")
    def delete_everything():
        return "deleted"

    with pytest.raises(ContractViolationError):
        delete_everything()

    audit = enforcer.get_audit_log()
    assert len(audit) == 1
    assert audit[0].decision == "DENIED"
    assert audit[0].action_name == "admin.delete"


def test_declaration_audit_log_records_pending():
    """Approval-required action produces a PENDING audit entry."""
    enforcer = ContractEnforcer.from_declaration({
        "node_id": "pending-v1",
        "permissions": ["db.drop"],
        "side_effects": ["db.drop"],
        "approval_points": ["db.drop"],
    })

    @enforcer.gate("db.drop", "side_effect")
    def drop_database():
        return "dropped"

    with pytest.raises(ApprovalPendingError):
        drop_database()

    audit = enforcer.get_audit_log()
    assert len(audit) == 1
    assert audit[0].decision == "PENDING"
    assert audit[0].action_name == "db.drop"


# =============================================================================
# 3. Integrity Tests
# =============================================================================

def test_declaration_verify_integrity_passes_on_creation():
    """Fresh declaration passes verify_integrity()."""
    enforcer = ContractEnforcer.from_declaration({
        "node_id": "fresh-v1",
        "permissions": ["github.read"],
    })
    assert enforcer.verify_integrity() is True


def test_declaration_verify_integrity_detects_tampering():
    """Directly mutating _sealed_declaration triggers ContractTamperError."""
    enforcer = ContractEnforcer.from_declaration({
        "node_id": "sealed-v1",
        "permissions": ["github.read"],
    })

    # Directly mutate the private sealed declaration (simulating memory attack)
    enforcer._sealed_declaration["permissions"] = ["admin.*", "root.*"]

    with pytest.raises(ContractTamperError) as exc_info:
        enforcer.verify_integrity()
    assert "tampered" in str(exc_info.value).lower()


def test_file_contract_verify_integrity_passes():
    """File-based contract passes verify_integrity() on unmodified file."""
    enforcer = ContractEnforcer.load(GITHUB_CONTRACT)
    assert enforcer.verify_integrity() is True


def test_file_contract_verify_integrity_detects_file_change(tmp_path):
    """File modification after load triggers ContractTamperError."""
    contract_file = tmp_path / "contract.yaml"
    contract_file.write_text(
        "version: 1\nworkflow: test\ninputs: []\noutputs: []\npermissions: []\n"
        "side_effects: []\napproval_points: []\nrecovery_strategy: retry\n"
        "replay_semantics: idempotent\ndependencies: []\nstate: none\nobservability: []\n",
        encoding="utf-8",
    )

    enforcer = ContractEnforcer.load(contract_file)
    assert enforcer.verify_integrity() is True

    # Modify the file after loading
    contract_file.write_text("TAMPERED CONTENT", encoding="utf-8")

    with pytest.raises(ContractTamperError) as exc_info:
        enforcer.verify_integrity()
    assert "tampered" in str(exc_info.value).lower()


def test_contract_source_property_file():
    """File-based contract has contract_source == 'file'."""
    enforcer = ContractEnforcer.load(GITHUB_CONTRACT)
    assert enforcer.contract_source == "file"


def test_contract_source_property_declaration():
    """Declaration-based contract has contract_source == 'declaration'."""
    enforcer = ContractEnforcer.from_declaration({
        "node_id": "source-test-v1",
        "permissions": [],
    })
    assert enforcer.contract_source == "declaration"


def test_node_id_property_declaration():
    """Declaration-based contract has the declared node_id."""
    enforcer = ContractEnforcer.from_declaration({
        "node_id": "my-agent-v3",
        "permissions": [],
    })
    assert enforcer.node_id == "my-agent-v3"


def test_node_id_property_file():
    """File-based contract has node_id == None."""
    enforcer = ContractEnforcer.load(GITHUB_CONTRACT)
    assert enforcer.node_id is None
