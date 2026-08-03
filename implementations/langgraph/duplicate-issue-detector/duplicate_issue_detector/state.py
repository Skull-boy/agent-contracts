from __future__ import annotations
from typing import Optional
from typing_extensions import TypedDict


class State(TypedDict):
    # inputs — set once at invocation, never changed by nodes
    issue_number: int
    repo_owner: str
    repo_name: str
    threshold: float
    github_token: str
    openai_api_key: str
    qdrant_url: str
    qdrant_collection: str
    qdrant_api_key: str

    # populated by detect
    issue_title: Optional[str]
    issue_body: Optional[str]
    combined_text: Optional[str]

    # populated by judge
    vector: Optional[list[float]]
    best_score: float
    match_number: Optional[int]
    match_title: Optional[str]

    # populated by act / index
    comment_posted: bool
    indexed: bool

    # execution trace
    run_log: list[str]
