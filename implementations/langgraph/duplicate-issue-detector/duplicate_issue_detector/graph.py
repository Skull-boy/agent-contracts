from __future__ import annotations

import logging
from typing import Literal

from langgraph.graph import END, START, StateGraph

from .nodes import act, detect, index, judge
from .state import State

log = logging.getLogger(__name__)


def _route(state: State) -> Literal["act", "index"]:
    if state["best_score"] >= state["threshold"]:
        log.info("ROUTE   score=%.4f >= threshold=%.4f → act", state["best_score"], state["threshold"])
        return "act"
    log.info("ROUTE   score=%.4f < threshold=%.4f → index", state["best_score"], state["threshold"])
    return "index"


def build_graph():
    g = StateGraph(State)
    g.add_node("detect", detect)
    g.add_node("judge", judge)
    g.add_node("act", act)
    g.add_node("index", index)

    g.add_edge(START, "detect")
    g.add_edge("detect", "judge")
    g.add_conditional_edges("judge", _route, {"act": "act", "index": "index"})
    g.add_edge("act", "index")
    g.add_edge("index", END)

    return g.compile()


def run(
    issue_number: int,
    repo_owner: str,
    repo_name: str,
    *,
    threshold: float = 0.87,
    qdrant_url: str,
    qdrant_collection: str,
    qdrant_api_key: str = "",
    github_token: str,
    openai_api_key: str,
) -> State:
    initial: State = {
        "issue_number": issue_number,
        "repo_owner": repo_owner,
        "repo_name": repo_name,
        "threshold": threshold,
        "github_token": github_token,
        "openai_api_key": openai_api_key,
        "qdrant_url": qdrant_url,
        "qdrant_collection": qdrant_collection,
        "qdrant_api_key": qdrant_api_key,
        "issue_title": None,
        "issue_body": None,
        "combined_text": None,
        "vector": None,
        "best_score": 0.0,
        "match_number": None,
        "match_title": None,
        "comment_posted": False,
        "indexed": False,
        "run_log": [],
    }
    log.info("START   repo=%s/%s issue=#%d threshold=%.2f", repo_owner, repo_name, issue_number, threshold)
    result = build_graph().invoke(initial)
    log.info("END     comment_posted=%s indexed=%s score=%.4f",
             result.get("comment_posted"), result.get("indexed"), result.get("best_score", 0.0))
    return result
