"""
Comprehensive test suite for Scyvera Runtime Enforcer.

Verifies:
- Happy paths for permissions and side effects
- Default-deny contract violations
- Approval gates and ApprovalPendingError
- Tamper resistance (in-memory freezing and on-disk SHA-256)
- Threat mitigations T4–T10
- Backward compatibility with v1 contracts
"""
import logging
from pathlib import Path
import warnings

import pytest

from scyvera import (
    ApprovalPendingError,
    AuditEntry,
    ContractEnforcer,
    ContractTamperError,
    ContractValidationError,
    ContractVersionError,
    ContractViolationError,
)


ROOT = Path(__file__).resolve().parent.parent
DUPLICATE_ISSUE_CONTRACT = (
    ROOT
    / "implementations"
    / "n8n"
    / "duplicate-issue-detector"
    / "contract.yaml"
)
LIFECYCLE_FIXTURES = ROOT / "tests" / "fixtures" / "v1.1"


# =============================================================================
# 1. Happy Path Tests
# =============================================================================

def test_enforcer_loads_v1_contract_with_defaults():
    """A v1 contract loads cleanly and defaults lifecycle to request-response."""
    enforcer = ContractEnforcer.load(DUPLICATE_ISSUE_CONTRACT)
    assert enforcer.integrity_hash is not None
    assert len(enforcer.integrity_hash) == 64
    assert enforcer.contract["lifecycle"]["mode"] == "request-response"
    assert enforcer.contract["lifecycle"]["initiation"] == "human-only"
    assert enforcer.contract["lifecycle"]["resumability"] == "stateless"


def test_allowed_permission_passes_gate_and_logs():
    """An allowed permission executes and creates an ALLOWED audit entry."""
    enforcer = ContractEnforcer.load(DUPLICATE_ISSUE_CONTRACT)

    @enforcer.gate("github: issues:write", "permission")
    def post_to_github(issue_id: int, message: str) -> str:
        return f"Commented on {issue_id}: {message}"

    result = post_to_github(123, "Looks like a duplicate")
    assert result == "Commented on 123: Looks like a duplicate"

    audit = enforcer.get_audit_log()
    assert len(audit) == 1
    assert audit[0].action_name == "github: issues:write"
    assert audit[0].action_type == "permission"
    assert audit[0].decision == "ALLOWED"
    assert audit[0].contract_field_reference == "permissions"


def test_allowed_side_effect_passes_gate_and_logs():
    """An allowed side effect executes and creates an ALLOWED audit entry."""
    enforcer = ContractEnforcer.load(DUPLICATE_ISSUE_CONTRACT)

    @enforcer.gate("comment", "side_effect")
    def write_comment(body: str) -> bool:
        return True

    assert write_comment("Duplicate detected") is True

    audit = enforcer.get_audit_log()
    assert len(audit) == 1
    assert audit[0].action_name == "comment"
    assert audit[0].action_type == "side_effect"
    assert audit[0].decision == "ALLOWED"
    assert audit[0].contract_field_reference == "side_effects"


# =============================================================================
# 2. Contract Violation Paths (Default-Deny)
# =============================================================================

def test_undeclared_permission_raises_violation():
    """An undeclared permission raises ContractViolationError naming permissions."""
    enforcer = ContractEnforcer.load(DUPLICATE_ISSUE_CONTRACT)

    @enforcer.gate("aws_s3:read", "permission")
    def read_s3_bucket():
        return "data"

    with pytest.raises(ContractViolationError) as exc_info:
        read_s3_bucket()

    err = exc_info.value
    assert err.action_name == "aws_s3:read"
    assert err.suggestion == "permissions"
    assert "not declared" in str(err)
    assert "Suggestion: Declare this action in the 'permissions' field" in str(err)

    audit = enforcer.get_audit_log()
    assert len(audit) == 1
    assert audit[0].decision == "DENIED"


def test_undeclared_side_effect_raises_violation():
    """An undeclared side effect raises ContractViolationError naming side_effects."""
    enforcer = ContractEnforcer.load(DUPLICATE_ISSUE_CONTRACT)

    @enforcer.gate("delete_repository", "side_effect")
    def delete_repo():
        return "deleted"

    with pytest.raises(ContractViolationError) as exc_info:
        delete_repo()

    err = exc_info.value
    assert err.action_name == "delete_repository"
    assert err.suggestion == "side_effects"
    assert "Suggestion: Declare this action in the 'side_effects' field" in str(err)

    audit = enforcer.get_audit_log()
    assert len(audit) == 1
    assert audit[0].decision == "DENIED"


# =============================================================================
# 3. Approval Paths
# =============================================================================

def test_approval_point_raises_approval_pending_error(tmp_path):
    """An action defined in approvals raises ApprovalPendingError with approval config."""
    contract_file = tmp_path / "contract.yaml"
    contract_file.write_text(
        """version: 1.1
system:
  name: deployment-agent
lifecycle:
  mode: request-response
inputs: []
outputs: []
permissions:
  - resource: prod_cluster
    actions: [deploy]
side_effects:
  - type: deployment
    resource: prod_cluster
    description: Deploys code to production
approvals:
  - action: prod_cluster:deploy
    required: true
    approver: secops_lead
    channel: telegram
    timeout: "15m"
dependencies: []
state:
  persistence: none
recovery:
  strategy: retry
replay:
  mode: idempotent
observability:
  level: basic
risk:
  level: high
""",
        encoding="utf-8",
    )

    enforcer = ContractEnforcer.load(contract_file)

    @enforcer.gate("prod_cluster:deploy", "side_effect")
    def deploy_to_prod():
        return "Deployed!"

    # Execution is halted prior to running deploy_to_prod
    with pytest.raises(ApprovalPendingError) as exc_info:
        deploy_to_prod()

    err = exc_info.value
    assert err.action_name == "prod_cluster:deploy"
    assert err.approval_config["approver"] == "secops_lead"
    assert err.approval_config["channel"] == "telegram"
    assert err.approval_config["timeout"] == "15m"

    audit = enforcer.get_audit_log()
    assert len(audit) == 1
    assert audit[0].decision == "PENDING"

    # Manual approval unblocks the action
    enforcer.approve("prod_cluster:deploy", token="AUTH_TOKEN_999")
    res = deploy_to_prod()
    assert res == "Deployed!"


# =============================================================================
# 4. Tamper Resistance Tests (T5, T9)
# =============================================================================

def test_contract_object_is_immutable():
    """Attempting to mutate the frozen contract object raises ContractTamperError."""
    enforcer = ContractEnforcer.load(DUPLICATE_ISSUE_CONTRACT)

    with pytest.raises(ContractTamperError):
        enforcer.contract["side_effects"] = []

    with pytest.raises(ContractTamperError):
        enforcer.contract["permissions"].append({"rogue": "root"})


def test_verify_integrity_passes_on_unmodified_file():
    """verify_integrity() succeeds when file content is intact."""
    enforcer = ContractEnforcer.load(DUPLICATE_ISSUE_CONTRACT)
    assert enforcer.verify_integrity() is True


def test_verify_integrity_raises_on_disk_modification(tmp_path):
    """verify_integrity() raises ContractTamperError when disk content changes (T5)."""
    contract_file = tmp_path / "contract.yaml"
    contract_file.write_text(
        "version: 1\nworkflow: test\ninputs: []\noutputs: []\npermissions: []\n"
        "side_effects: []\napproval_points: []\nrecovery_strategy: retry\n"
        "replay_semantics: idempotent\ndependencies: []\nstate: none\nobservability: []\n",
        encoding="utf-8",
    )

    enforcer = ContractEnforcer.load(contract_file)
    assert enforcer.verify_integrity() is True

    # Malicious actor tampers with the file on disk
    contract_file.write_text("TAMPERED CONTENT", encoding="utf-8")

    with pytest.raises(ContractTamperError) as exc_info:
        enforcer.verify_integrity()
    assert "tampered with on disk" in str(exc_info.value)


# =============================================================================
# 5. Threat-Specific Tests (T4, T7, T8, T9, T10)
# =============================================================================

def test_t4_assert_gated_utility():
    """assert_gated(fn) validates whether a function is protected by an enforcer gate."""
    enforcer = ContractEnforcer.load(DUPLICATE_ISSUE_CONTRACT)

    def ungated_function():
        return "raw"

    @enforcer.gate("github: issues:write", "permission")
    def gated_function():
        return "secure"

    assert enforcer.assert_gated(gated_function) is True

    with pytest.raises(ContractViolationError) as exc_info:
        enforcer.assert_gated(ungated_function)
    assert "Decorate this function with @enforcer.gate" in str(exc_info.value)


def test_t7_wildcard_permission_fails_at_load_time(tmp_path):
    """A contract with permissions: ['*'] is rejected at load time (T7)."""
    contract_file = tmp_path / "contract.yaml"
    contract_file.write_text(
        """version: 1.1
system:
  name: malicious-agent
lifecycle:
  mode: request-response
inputs: []
outputs: []
permissions:
  - "*"
side_effects: []
approvals: []
dependencies: []
state:
  persistence: none
recovery:
  strategy: retry
replay:
  mode: idempotent
observability:
  level: basic
risk:
  level: high
""",
        encoding="utf-8",
    )

    with pytest.raises(ContractValidationError) as exc_info:
        ContractEnforcer.load(contract_file)
    assert "Wildcard permission" in str(exc_info.value)



def test_t7_invalid_service_scope_pattern_fails_at_load_time(tmp_path):
    """A flat permission string not following service:scope fails at load time (T7)."""
    contract_file = tmp_path / "contract.yaml"
    contract_file.write_text(
        """version: 1.1
system:
  name: bad-pattern-agent
lifecycle:
  mode: request-response
inputs: []
outputs: []
permissions:
  - "invalid_unscoped_permission"
side_effects: []
approvals: []
dependencies: []
state:
  persistence: none
recovery:
  strategy: retry
replay:
  mode: idempotent
observability:
  level: basic
risk:
  level: low
""",
        encoding="utf-8",
    )

    with pytest.raises(ContractValidationError) as exc_info:
        ContractEnforcer.load(contract_file)
    assert "service:scope pattern" in str(exc_info.value)


def test_t8_irreversible_side_effect_empty_approvals_warns(tmp_path, caplog):
    """A contract with irreversible: true and empty approvals emits a warning (T8)."""
    contract_file = tmp_path / "contract.yaml"
    contract_file.write_text(
        """version: 1.1
system:
  name: destructive-agent
lifecycle:
  mode: request-response
inputs: []
outputs: []
permissions: []
side_effects:
  - type: drop_database
    resource: production
    irreversible: true
approvals: []
dependencies: []
state:
  persistence: none
recovery:
  strategy: retry
replay:
  mode: idempotent
observability:
  level: basic
risk:
  level: high
""",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="scyvera.enforcer"):
        ContractEnforcer.load(contract_file)
    assert "declares irreversible side effect" in caplog.text
    assert "drop_database" in caplog.text


def test_t9_audit_log_tamper_proofing():
    """Modifying the returned audit log list does not alter the enforcer's log (T9)."""
    enforcer = ContractEnforcer.load(DUPLICATE_ISSUE_CONTRACT)

    @enforcer.gate("github: issues:write", "permission")
    def act():
        return True

    act()

    audit_copy = enforcer.get_audit_log()
    assert len(audit_copy) == 1

    # Tamper with the returned copy
    audit_copy.clear()
    assert len(audit_copy) == 0

    # Internal log remains intact
    assert len(enforcer.get_audit_log()) == 1


def test_t10_explicit_v1_1_missing_lifecycle_raises_version_error(tmp_path):
    """A contract declaring contract_version: '1.1' without lifecycle raises ContractVersionError (T10)."""
    contract_file = tmp_path / "contract.yaml"
    contract_file.write_text(
        """version: 1.1
contract_version: "1.1"
system:
  name: missing-lifecycle-agent
inputs: []
outputs: []
permissions: []
side_effects: []
approvals: []
dependencies: []
state:
  persistence: none
recovery:
  strategy: retry
replay:
  mode: idempotent
observability:
  level: basic
risk:
  level: low
""",
        encoding="utf-8",
    )

    with pytest.raises(ContractVersionError) as exc_info:
        ContractEnforcer.load(contract_file)
    assert "missing the required 'lifecycle' field" in str(exc_info.value)
