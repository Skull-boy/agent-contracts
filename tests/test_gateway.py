"""Tests for the gateway enforcement layer.

All external clients (PyGithub, qdrant-client) are mocked — no real API calls.
Enforcer is real, loaded from the fixture contract, not mocked.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scyvera import (
    ApprovalPendingError,
    ContractEnforcer,
    ContractViolationError,
    GatewayError,
    GitHubGateway,
    QdrantGateway,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "github_contract.yaml"


# =============================================================================
# Structural tests
# =============================================================================


def test_github_gateway_all_methods_are_gated():
    """Every GitHubGateway method is decorated with @enforcer.gate."""
    enforcer = ContractEnforcer.load(FIXTURE)
    gw = GitHubGateway(enforcer, token="fake")
    enforcer.assert_gated(gw.post_comment)
    enforcer.assert_gated(gw.close_issue)
    enforcer.assert_gated(gw.merge_pr)
    enforcer.assert_gated(gw.create_label)
    enforcer.assert_gated(gw.read_issue)
    enforcer.assert_gated(gw.list_issues)
    enforcer.assert_gated(gw.read_pr_files)


def test_qdrant_gateway_all_methods_are_gated():
    """Every QdrantGateway method is decorated with @enforcer.gate."""
    enforcer = ContractEnforcer.load(FIXTURE)
    gw = QdrantGateway(enforcer, url="http://localhost:6333", api_key="fake")
    enforcer.assert_gated(gw.search)
    enforcer.assert_gated(gw.upsert)
    enforcer.assert_gated(gw.delete)


# =============================================================================
# Enforcement tests
# =============================================================================


def test_undeclared_action_raises_violation():
    """Contract declares only github.read — post_comment must raise ContractViolationError."""
    enforcer = ContractEnforcer.load(FIXTURE)
    gw = GitHubGateway(enforcer, token="fake")

    with pytest.raises(ContractViolationError) as exc_info:
        gw.post_comment("owner/repo", 1, "hello")

    assert exc_info.value.action_name == "github.comment"


def test_approval_required_action_raises_pending():
    """github.merge requires approval — merge_pr without approval raises ApprovalPendingError."""
    enforcer = ContractEnforcer.load(FIXTURE)
    gw = GitHubGateway(enforcer, token="fake")

    with pytest.raises(ApprovalPendingError) as exc_info:
        gw.merge_pr("owner/repo", 99)

    assert exc_info.value.action_name == "github.merge"


def test_approved_action_executes():
    """After approval, merge_pr executes and audit log shows ALLOWED."""
    enforcer = ContractEnforcer.load(FIXTURE)
    with patch("scyvera.gateway.Github") as MockGithub:
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.merge.return_value = {"merged": True}
        mock_repo.get_pull.return_value = mock_pr
        mock_client = MagicMock()
        mock_client.get_repo.return_value = mock_repo
        MockGithub.return_value = mock_client

        gw = GitHubGateway(enforcer, token="fake")
        enforcer.approve("github.merge", token="test-token")
        result = gw.merge_pr("owner/repo", 42)

        assert result == {"merged": True}
        audit = enforcer.get_audit_log()
        # Last entry should be ALLOWED for github.merge
        allowed = [e for e in audit if e.action_name == "github.merge" and e.decision == "ALLOWED"]
        assert len(allowed) >= 1


def test_read_action_executes_without_approval():
    """read_issue executes with no approval needed, audit shows ALLOWED."""
    enforcer = ContractEnforcer.load(FIXTURE)
    with patch("scyvera.gateway.Github") as MockGithub:
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        mock_issue.title = "Test"
        mock_repo.get_issue.return_value = mock_issue
        mock_client = MagicMock()
        mock_client.get_repo.return_value = mock_repo
        MockGithub.return_value = mock_client

        gw = GitHubGateway(enforcer, token="fake")
        result = gw.read_issue("owner/repo", 1)

        assert result == mock_issue
        audit = enforcer.get_audit_log()
        allowed = [e for e in audit if e.action_name == "github.read" and e.decision == "ALLOWED"]
        assert len(allowed) >= 1


def test_token_not_accessible_outside_gateway():
    """GitHubGateway has no public attribute that returns the token."""
    enforcer = ContractEnforcer.load(FIXTURE)
    gw = GitHubGateway(enforcer, token="super-secret-token")

    assert not hasattr(gw, "token")
    assert not hasattr(gw, "api_key")
    # Private attributes should exist but not public
    assert hasattr(gw, "_token")
    # Ensure dir does not expose public token
    public_attrs = [a for a in dir(gw) if not a.startswith("_")]
    assert "token" not in public_attrs
    assert "api_key" not in public_attrs


def test_client_not_accessible_outside_gateway():
    """No public attribute returns the raw client."""
    enforcer = ContractEnforcer.load(FIXTURE)
    gw = GitHubGateway(enforcer, token="fake")
    public_attrs = [a for a in dir(gw) if not a.startswith("_")]
    assert "client" not in public_attrs
    assert "_client" in dir(gw)
    assert hasattr(gw, "_client")
    assert not hasattr(gw, "client")

    qgw = QdrantGateway(enforcer, url="http://localhost:6333", api_key="fake")
    public_q = [a for a in dir(qgw) if not a.startswith("_")]
    assert "client" not in public_q


def test_gateway_error_wraps_client_exception():
    """Mock PyGithub to raise GithubException — GatewayError is raised, not GithubException."""
    try:
        from github.GithubException import GithubException
    except ImportError:
        class GithubException(Exception):  # type: ignore[no-redef]
            def __init__(self, status=500, data="boom", headers=None):
                super().__init__(data)
                self.status = status
                self.data = data

    enforcer = ContractEnforcer.load(FIXTURE)
    with patch("scyvera.gateway.Github") as MockGithub:
        mock_repo = MagicMock()
        mock_repo.get_issue.side_effect = GithubException(500, "boom", headers=None)
        mock_client = MagicMock()
        mock_client.get_repo.return_value = mock_repo
        MockGithub.return_value = mock_client

        # Need to approve read? read_issue does not require approval, so no approve needed.
        # But choose an allowed action; read_issue is allowed.
        gw = GitHubGateway(enforcer, token="fake")

        with pytest.raises(GatewayError) as exc_info:
            gw.read_issue("owner/repo", 1)

        assert isinstance(exc_info.value, GatewayError)
        assert exc_info.value.action == "github.read"
        assert isinstance(exc_info.value.original_exception, GithubException)
        assert "boom" in str(exc_info.value.original_exception)


def test_audit_log_records_denied():
    """Undeclared action attempt → audit log has DENIED entry with action name."""
    enforcer = ContractEnforcer.load(FIXTURE)
    gw = GitHubGateway(enforcer, token="fake")

    try:
        gw.post_comment("owner/repo", 1, "hi")
    except ContractViolationError:
        pass

    audit = enforcer.get_audit_log()
    denied = [e for e in audit if e.decision == "DENIED"]
    assert len(denied) >= 1
    assert any(e.action_name == "github.comment" for e in denied)


def test_audit_log_records_pending():
    """Approval-required action → audit log has PENDING entry."""
    enforcer = ContractEnforcer.load(FIXTURE)
    gw = GitHubGateway(enforcer, token="fake")

    try:
        gw.merge_pr("owner/repo", 1)
    except ApprovalPendingError:
        pass

    audit = enforcer.get_audit_log()
    pending = [e for e in audit if e.decision == "PENDING"]
    assert len(pending) >= 1
    assert any(e.action_name == "github.merge" for e in pending)


# =============================================================================
# Optional dependency fallback tests
# =============================================================================


def test_github_gateway_missing_dependency_raises_import_error():
    """When PyGithub is not installed, initializing GitHubGateway raises ImportError."""
    enforcer = ContractEnforcer.load(FIXTURE)
    with patch("scyvera.gateway.Github", None):
        with pytest.raises(ImportError) as exc_info:
            GitHubGateway(enforcer, token="fake")
        assert "PyGithub is required" in str(exc_info.value)
        assert "scyvera[github]" in str(exc_info.value)


def test_qdrant_gateway_missing_dependency_raises_import_error():
    """When qdrant-client is not installed, initializing QdrantGateway raises ImportError."""
    enforcer = ContractEnforcer.load(FIXTURE)
    with patch("scyvera.gateway.QdrantClient", None):
        with pytest.raises(ImportError) as exc_info:
            QdrantGateway(enforcer, url="http://localhost:6333", api_key="fake")
        assert "qdrant-client is required" in str(exc_info.value)
        assert "scyvera[qdrant]" in str(exc_info.value)
