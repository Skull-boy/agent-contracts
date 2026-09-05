"""Gateway module — single enforcement boundary for external API calls.

All credentials and all external API calls live exclusively inside gated
gateway classes. No other module holds a token or imports a raw API client.
Bypass is structurally impossible, not just discouraged.

Design:
- :class:`BaseGateway` — abstract base that stores the injected enforcer.
- :class:`GitHubGateway` — gated GitHub operations via PyGithub.
- :class:`QdrantGateway` — gated Qdrant operations via qdrant-client.
- Every public method is gated with ``@enforcer.gate(...)`` using the
  injected enforcer instance. Gating is applied per-instance in ``__init__``
  so the injected enforcer is used, not a global singleton.
- All raw client exceptions are caught and re-raised as
  :class:`scyvera.exceptions.GatewayError`.
"""

from __future__ import annotations

import abc
import warnings
from typing import Any

try:
    from github import Github
    try:
        from github.Auth import Token as GithubToken  # type: ignore[import-not-found]
    except Exception:
        GithubToken = None  # type: ignore[assignment]
except ImportError:
    Github = None  # type: ignore[assignment]
    GithubToken = None  # type: ignore[assignment]

try:
    from qdrant_client import QdrantClient
except ImportError:
    QdrantClient = None  # type: ignore[assignment]

from .enforcer import ContractEnforcer
from .exceptions import GatewayError


class BaseGateway(abc.ABC):
    """Abstract base for all gateway implementations.

    The enforcer is injected — the gateway never creates its own enforcer.
    The enforcer is the single source of truth for contract decisions.
    """

    def __init__(self, enforcer: ContractEnforcer) -> None:
        """Initialize the gateway with an injected enforcer.

        Args:
            enforcer: The :class:`ContractEnforcer` that governs all
                gateway operations. Must be provided by the caller.
        """
        self._enforcer: ContractEnforcer = enforcer


class GitHubGateway(BaseGateway):
    """Gated gateway for GitHub API operations.

    All credentials are held privately. The raw PyGithub client is never
    exposed outside this class. Every method is gated via the injected
    enforcer, ensuring contract enforcement cannot be bypassed.
    """

    def __init__(self, enforcer: ContractEnforcer, token: str) -> None:
        """Initialize the GitHub gateway.

        Args:
            enforcer: Contract enforcer that governs all operations.
            token: GitHub personal access token. Stored privately as
                ``self._token`` and never exposed outside the class.
        """
        super().__init__(enforcer)
        if Github is None:
            raise ImportError(
                "PyGithub is required for GitHubGateway. Install it with 'pip install PyGithub' or 'pip install scyvera[github]'."
            )
        self._token: str = token
        if GithubToken is not None:
            self._client: Github = Github(auth=GithubToken(token))
        else:
            self._client: Github = Github(token)

        # Apply per-instance gating using the injected enforcer.
        # Each method is wrapped so ``enforcer.assert_gated`` succeeds
        # on the bound instance methods and contract decisions are
        # evaluated against the injected contract.
        self.post_comment = enforcer.gate("github.comment", "side_effect")(self.post_comment)  # type: ignore[method-assign]
        self.close_issue = enforcer.gate("github.close", "side_effect")(self.close_issue)  # type: ignore[method-assign]
        self.merge_pr = enforcer.gate("github.merge", "side_effect")(self.merge_pr)  # type: ignore[method-assign]
        self.create_label = enforcer.gate("github.label", "side_effect")(self.create_label)  # type: ignore[method-assign]
        self.read_issue = enforcer.gate("github.read", "read")(self.read_issue)  # type: ignore[method-assign]
        self.list_issues = enforcer.gate("github.read", "read")(self.list_issues)  # type: ignore[method-assign]
        self.read_pr_files = enforcer.gate("github.read", "read")(self.read_pr_files)  # type: ignore[method-assign]

    def post_comment(self, repo_name: str, issue_number: int, body: str) -> Any:
        """Post a comment on a GitHub issue.

        Args:
            repo_name: Repository in ``owner/name`` form.
            issue_number: Issue number to comment on.
            body: Markdown body of the comment.

        Returns:
            The created comment object from PyGithub.

        Raises:
            GatewayError: If the underlying GitHub API call fails.
            ContractViolationError: If ``github.comment`` is not declared.
            ApprovalPendingError: If ``github.comment`` requires approval.
        """
        try:
            repo = self._client.get_repo(repo_name)
            issue = repo.get_issue(number=issue_number)
            return issue.create_comment(body)
        except GatewayError:
            raise
        except Exception as exc:
            raise GatewayError("github.comment", exc) from exc

    def close_issue(self, repo_name: str, issue_number: int) -> Any:
        """Close a GitHub issue.

        Args:
            repo_name: Repository in ``owner/name`` form.
            issue_number: Issue number to close.

        Returns:
            The updated issue object.

        Raises:
            GatewayError: If the underlying GitHub API call fails.
        """
        try:
            repo = self._client.get_repo(repo_name)
            issue = repo.get_issue(number=issue_number)
            return issue.edit(state="closed")
        except GatewayError:
            raise
        except Exception as exc:
            raise GatewayError("github.close", exc) from exc

    def merge_pr(self, repo_name: str, pr_number: int) -> Any:
        """Merge a GitHub pull request.

        Args:
            repo_name: Repository in ``owner/name`` form.
            pr_number: Pull request number to merge.

        Returns:
            The merge result from PyGithub.

        Raises:
            GatewayError: If the underlying GitHub API call fails.
        """
        try:
            repo = self._client.get_repo(repo_name)
            pr = repo.get_pull(number=pr_number)
            return pr.merge()
        except GatewayError:
            raise
        except Exception as exc:
            raise GatewayError("github.merge", exc) from exc

    def create_label(self, repo_name: str, issue_number: int, label: str) -> Any:
        """Add a label to a GitHub issue.

        Args:
            repo_name: Repository in ``owner/name`` form.
            issue_number: Issue number to label.
            label: Label name to add.

        Returns:
            The result of the label addition.

        Raises:
            GatewayError: If the underlying GitHub API call fails.
        """
        try:
            repo = self._client.get_repo(repo_name)
            issue = repo.get_issue(number=issue_number)
            return issue.add_to_labels(label)
        except GatewayError:
            raise
        except Exception as exc:
            raise GatewayError("github.label", exc) from exc

    def read_issue(self, repo_name: str, issue_number: int) -> Any:
        """Read a GitHub issue.

        Args:
            repo_name: Repository in ``owner/name`` form.
            issue_number: Issue number to read.

        Returns:
            The issue object from PyGithub.

        Raises:
            GatewayError: If the underlying GitHub API call fails.
        """
        try:
            repo = self._client.get_repo(repo_name)
            return repo.get_issue(number=issue_number)
        except GatewayError:
            raise
        except Exception as exc:
            raise GatewayError("github.read", exc) from exc

    def list_issues(self, repo_name: str, state: str = "open") -> Any:
        """List issues in a GitHub repository.

        Args:
            repo_name: Repository in ``owner/name`` form.
            state: Issue state filter (e.g. ``"open"``, ``"closed"``, ``"all"``).

        Returns:
            A paginated list of issues from PyGithub.

        Raises:
            GatewayError: If the underlying GitHub API call fails.
        """
        try:
            repo = self._client.get_repo(repo_name)
            return repo.get_issues(state=state)
        except GatewayError:
            raise
        except Exception as exc:
            raise GatewayError("github.read", exc) from exc

    def read_pr_files(self, repo_name: str, pr_number: int) -> Any:
        """Read files changed in a GitHub pull request.

        Args:
            repo_name: Repository in ``owner/name`` form.
            pr_number: Pull request number.

        Returns:
            A paginated list of files from PyGithub.

        Raises:
            GatewayError: If the underlying GitHub API call fails.
        """
        try:
            repo = self._client.get_repo(repo_name)
            pr = repo.get_pull(number=pr_number)
            return pr.get_files()
        except GatewayError:
            raise
        except Exception as exc:
            raise GatewayError("github.read", exc) from exc


class QdrantGateway(BaseGateway):
    """Gated gateway for Qdrant vector database operations.

    All credentials are held privately. The raw Qdrant client is never
    exposed outside this class. Every method is gated via the injected
    enforcer.
    """

    def __init__(self, enforcer: ContractEnforcer, url: str, api_key: str) -> None:
        """Initialize the Qdrant gateway.

        Args:
            enforcer: Contract enforcer that governs all operations.
            url: Qdrant instance URL.
            api_key: Qdrant API key. Stored privately and never exposed.
        """
        super().__init__(enforcer)
        if QdrantClient is None:
            raise ImportError(
                "qdrant-client is required for QdrantGateway. Install it with 'pip install qdrant-client' or 'pip install scyvera[qdrant]'."
            )
        self._url: str = url
        self._api_key: str = api_key
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._client: QdrantClient = QdrantClient(url=url, api_key=api_key)

        # Apply per-instance gating using the injected enforcer.
        self.search = enforcer.gate("qdrant.search", "read")(self.search)  # type: ignore[method-assign]
        self.upsert = enforcer.gate("qdrant.write", "side_effect")(self.upsert)  # type: ignore[method-assign]
        self.delete = enforcer.gate("qdrant.delete", "side_effect")(self.delete)  # type: ignore[method-assign]

    def search(self, collection: str, vector: list[float], limit: int = 10) -> Any:
        """Search for nearest vectors in a Qdrant collection.

        Args:
            collection: Collection name to search in.
            vector: Query vector.
            limit: Maximum number of results to return.

        Returns:
            Query results from Qdrant.

        Raises:
            GatewayError: If the underlying Qdrant API call fails.
        """
        try:
            # Prefer query_points (new API) with fallback to search if available.
            if hasattr(self._client, "query_points"):
                return self._client.query_points(
                    collection_name=collection, query=vector, limit=limit
                )
            # Fallback for older clients that expose search
            return self._client.search(  # type: ignore[attr-defined]
                collection_name=collection, query_vector=vector, limit=limit
            )
        except GatewayError:
            raise
        except Exception as exc:
            raise GatewayError("qdrant.search", exc) from exc

    def upsert(self, collection: str, points: list[Any]) -> Any:
        """Upsert points into a Qdrant collection.

        Args:
            collection: Collection name to upsert into.
            points: Points to upsert.

        Returns:
            The update result from Qdrant.

        Raises:
            GatewayError: If the underlying Qdrant API call fails.
        """
        try:
            return self._client.upsert(collection_name=collection, points=points)
        except GatewayError:
            raise
        except Exception as exc:
            raise GatewayError("qdrant.write", exc) from exc

    def delete(self, collection: str, ids: list[Any]) -> Any:
        """Delete points from a Qdrant collection.

        Args:
            collection: Collection name to delete from.
            ids: Point IDs to delete.

        Returns:
            The update result from Qdrant.

        Raises:
            GatewayError: If the underlying Qdrant API call fails.
        """
        try:
            return self._client.delete(
                collection_name=collection, points_selector=ids
            )
        except GatewayError:
            raise
        except Exception as exc:
            raise GatewayError("qdrant.delete", exc) from exc
