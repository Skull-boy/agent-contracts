from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI

from scyvera import ContractEnforcer
from scyvera.exceptions import GatewayError
from scyvera.gateway import GitHubGateway

from .state import State

log = logging.getLogger(__name__)

_EMBED_MODEL = "text-embedding-3-small"
_EMBED_DIMS = 1536
_MAX_CHARS = 6000
_SEARCH_LIMIT = 5


def _get_enforcer() -> ContractEnforcer:
    """Load the workflow contract enforcer.

    The contract is resolved relative to this file so the gateway
    always enforces the contract that ships with the workflow.
    """
    contract_path = Path(__file__).resolve().parent.parent / "contract.yaml"
    return ContractEnforcer.load(contract_path)


def detect(state: State) -> dict[str, Any]:
    """Fetch issue title + body from GitHub. Read-only, no side effects."""
    log.info("DETECT  #%d from %s/%s", state["issue_number"], state["repo_owner"], state["repo_name"])
    try:
        enforcer = _get_enforcer()
        gateway = GitHubGateway(enforcer, token=state["github_token"])
        issue = gateway.read_issue(
            f"{state['repo_owner']}/{state['repo_name']}",
            state["issue_number"],
        )
    except (GatewayError, Exception) as exc:
        log.error("DETECT  error: %s", exc)
        raise

    title = issue.title or ""
    body = issue.body or ""
    combined = f"{title}\n\n{body}".strip()[:_MAX_CHARS]
    log.info("DETECT  title=%r body_len=%d", title, len(body))
    return {
        "issue_title": title,
        "issue_body": body,
        "combined_text": combined,
        "run_log": state["run_log"] + [f"detect: #{state['issue_number']} {title!r:.50}"],
    }


def judge(state: State) -> dict[str, Any]:
    """Embed text via OpenAI, search Qdrant, return best match score."""
    log.info("JUDGE   embedding #%d", state["issue_number"])

    try:
        resp = OpenAI(api_key=state["openai_api_key"]).embeddings.create(
            model=_EMBED_MODEL, input=state["combined_text"]
        )
    except Exception as exc:
        log.error("JUDGE   embed error: %s", exc)
        raise

    vector = resp.data[0].embedding
    if len(vector) != _EMBED_DIMS:
        raise ValueError(f"Expected {_EMBED_DIMS}-dim vector, got {len(vector)}")
    log.info("JUDGE   embedded, dims=%d", len(vector))

    headers = {"Content-Type": "application/json"}
    if state["qdrant_api_key"]:
        headers["api-key"] = state["qdrant_api_key"]
    try:
        r = httpx.post(
            f"{state['qdrant_url'].rstrip('/')}/collections/{state['qdrant_collection']}/points/search",
            json={"vector": vector, "limit": _SEARCH_LIMIT, "with_payload": True},
            headers=headers,
            timeout=30.0,
        )
        r.raise_for_status()
    except Exception as exc:
        log.error("JUDGE   search error: %s", exc)
        raise

    results = [
        hit for hit in r.json().get("result", [])
        if hit.get("payload", {}).get("issueNumber") != state["issue_number"]
    ]

    best_score = 0.0
    match_number = None
    match_title = None
    if results:
        best = results[0]
        best_score = float(best.get("score", 0.0))
        match_number = best.get("payload", {}).get("issueNumber")
        match_title = best.get("payload", {}).get("title")

    log.info("JUDGE   score=%.4f match=#%s", best_score, match_number)
    return {
        "vector": vector,
        "best_score": best_score,
        "match_number": match_number,
        "match_title": match_title,
        "run_log": state["run_log"] + [f"judge: score={best_score:.4f} match=#{match_number}"],
    }


def act(state: State) -> dict[str, Any]:
    """Post one duplicate comment on the triggering issue."""
    log.info(
        "ACT     posting comment on #%d → #%s score=%.4f",
        state["issue_number"], state["match_number"], state["best_score"],
    )
    body = (
        f"🔍 This issue looks similar to #{state['match_number']} — "
        f"\"{state['match_title']}\" (similarity: {state['best_score']:.3f}).\n\n"
        "This is an automated suggestion — a maintainer will confirm."
    )
    try:
        enforcer = _get_enforcer()
        gateway = GitHubGateway(enforcer, token=state["github_token"])
        gateway.post_comment(
            f"{state['repo_owner']}/{state['repo_name']}",
            state["issue_number"],
            body,
        )
    except (GatewayError, Exception) as exc:
        log.error("ACT     error: %s", exc)
        raise
    log.info("ACT     comment posted")
    return {
        "comment_posted": True,
        "run_log": state["run_log"] + [
            f"act: commented on #{state['issue_number']} → #{state['match_number']}"
        ],
    }


def index(state: State) -> dict[str, Any]:
    """Upsert this issue's vector into Qdrant. Always runs regardless of duplicate result."""
    log.info("INDEX   upserting #%d into %s", state["issue_number"], state["qdrant_collection"])
    headers = {"Content-Type": "application/json"}
    if state["qdrant_api_key"]:
        headers["api-key"] = state["qdrant_api_key"]
    try:
        r = httpx.put(
            f"{state['qdrant_url'].rstrip('/')}/collections/{state['qdrant_collection']}/points",
            json={"points": [{
                "id": state["issue_number"],
                "vector": state["vector"],
                "payload": {
                    "issueNumber": state["issue_number"],
                    "title": state["issue_title"],
                    "url": (
                        f"https://github.com/{state['repo_owner']}"
                        f"/{state['repo_name']}/issues/{state['issue_number']}"
                    ),
                },
            }]},
            headers=headers,
            timeout=30.0,
        )
        r.raise_for_status()
    except Exception as exc:
        log.error("INDEX   error: %s", exc)
        raise
    log.info("INDEX   done")
    return {
        "indexed": True,
        "run_log": state["run_log"] + [f"index: upserted #{state['issue_number']}"],
    }
