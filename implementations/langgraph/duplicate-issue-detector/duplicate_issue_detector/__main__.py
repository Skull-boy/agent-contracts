"""Run: python -m duplicate_issue_detector --issue 42 --repo owner/repo"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from .graph import run

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")


def _env(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        print(f"ERROR: {name} not set", file=sys.stderr)
        sys.exit(1)
    return v


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--issue", "-i", type=int, required=True)
    p.add_argument("--repo", "-r", required=True, metavar="OWNER/REPO")
    p.add_argument("--threshold", "-t", type=float, default=0.87)
    args = p.parse_args()

    parts = args.repo.split("/", 1)
    if len(parts) != 2:
        print("ERROR: --repo must be owner/repo", file=sys.stderr)
        sys.exit(1)
    owner, repo = parts

    try:
        result = run(
            issue_number=args.issue,
            repo_owner=owner,
            repo_name=repo,
            threshold=args.threshold,
            github_token=_env("GITHUB_TOKEN"),
            openai_api_key=_env("OPENAI_API_KEY"),
            qdrant_url=_env("QDRANT_URL"),
            qdrant_collection=_env("QDRANT_COLLECTION"),
            qdrant_api_key=os.getenv("QDRANT_API_KEY", ""),
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    print(json.dumps({
        "issue_number": result["issue_number"],
        "repo": args.repo,
        "threshold": args.threshold,
        "issue_title": result.get("issue_title"),
        "best_score": result.get("best_score", 0.0),
        "match_number": result.get("match_number"),
        "match_title": result.get("match_title"),
        "comment_posted": result.get("comment_posted", False),
        "indexed": result.get("indexed", False),
        "run_log": result.get("run_log", []),
    }, indent=2))


if __name__ == "__main__":
    main()
