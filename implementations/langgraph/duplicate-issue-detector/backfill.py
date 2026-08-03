"""
Backfill: embed every open issue in a repo and upsert into Qdrant.
Run once before enabling live detection.

Usage:
    python backfill.py --repo owner/repo
    python backfill.py --repo owner/repo --dry-run
    python backfill.py --repo owner/repo --delay 0.3
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import httpx
from github import Github
from openai import OpenAI

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

_EMBED_MODEL = "text-embedding-3-small"
_MAX_CHARS = 6000


def _env(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        log.error("Missing env var: %s", name)
        sys.exit(1)
    return v


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True, metavar="OWNER/REPO")
    p.add_argument("--delay", type=float, default=1.0, help="seconds between issues (default 1.0)")
    p.add_argument("--dry-run", action="store_true", help="fetch and embed, but skip Qdrant writes")
    args = p.parse_args()

    owner, repo_name = args.repo.split("/", 1)
    github_token = _env("GITHUB_TOKEN")
    openai_api_key = _env("OPENAI_API_KEY")
    qdrant_url = _env("QDRANT_URL")
    qdrant_collection = _env("QDRANT_COLLECTION")
    qdrant_api_key = os.getenv("QDRANT_API_KEY", "")

    qdrant_headers = {"Content-Type": "application/json"}
    if qdrant_api_key:
        qdrant_headers["api-key"] = qdrant_api_key

    oai = OpenAI(api_key=openai_api_key)
    repo = Github(github_token).get_repo(f"{owner}/{repo_name}")
    issues = list(repo.get_issues(state="open"))
    log.info("Found %d open issues in %s", len(issues), args.repo)

    for i, issue in enumerate(issues, 1):
        combined = f"{issue.title}\n\n{issue.body or ''}".strip()[:_MAX_CHARS]
        log.info("[%d/%d] embedding #%d %r", i, len(issues), issue.number, issue.title[:60])

        vector = oai.embeddings.create(model=_EMBED_MODEL, input=combined).data[0].embedding

        if not args.dry_run:
            r = httpx.put(
                f"{qdrant_url.rstrip('/')}/collections/{qdrant_collection}/points",
                json={"points": [{
                    "id": issue.number,
                    "vector": vector,
                    "payload": {
                        "issueNumber": issue.number,
                        "title": issue.title,
                        "url": issue.html_url,
                    },
                }]},
                headers=qdrant_headers,
                timeout=30.0,
            )
            r.raise_for_status()
            log.info("[%d/%d] upserted #%d", i, len(issues), issue.number)
        else:
            log.info("[%d/%d] dry-run, skipping upsert", i, len(issues))

        if i < len(issues):
            time.sleep(args.delay)

    log.info("Backfill complete: %d issues processed", len(issues))


if __name__ == "__main__":
    main()
