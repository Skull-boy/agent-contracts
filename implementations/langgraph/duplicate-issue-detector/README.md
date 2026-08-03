# 🔍 Semantic Duplicate Issue Detector — LangGraph

**Framework:** LangGraph  
**Pattern:** [`detect → judge → approve → act`](../../../patterns/detect-judge-approve-act.md)  
**n8n reference implementation:** [`../n8n/duplicate-issue-detector`](../../n8n/duplicate-issue-detector/)  
**Contract:** [`contract.yaml`](./contract.yaml)

> **Warning**: At first try not to use paid API of OpenAI or Claude directly. Try it out from OpenRouter or try out local model based API as its sensible.

---

## What this is

A LangGraph implementation of the same duplicate-issue-detection logic as the
[n8n workflow](../../n8n/duplicate-issue-detector/), built to demonstrate that the
`detect → judge → approve → act` pattern is genuinely framework-agnostic —
the same shape, the same contract semantics, a different runtime.

**What it does:**  
When run against a GitHub issue, it embeds the issue text with OpenAI's
`text-embedding-3-small`, searches a Qdrant vector store for semantically
similar previously-indexed issues, and — only above a configurable similarity
threshold — posts a single comment linking to the probable duplicate. It then
indexes the current issue so future issues can find it.

**What it never does:**  
Closes, labels, reassigns, or edits any issue. The contract's `approval_points`
is intentionally empty because the only side effect is a comment, not an
irreversible action.

---

## Architecture

```
START
  │
  ▼
detect_node         ← fetches issue title + body from GitHub API (READ ONLY)
  │
  ▼
judge_node          ← embeds text (OpenAI) + searches Qdrant for closest match
  │
  ├── score >= threshold ─────────────────────────────────────┐
  │                                                            │
  ▼                                                            │
act_node            ← posts ONE comment on the triggering issue│
  │                                                            │
  ▼                                                            │
index_node          ← upserts this issue's vector into Qdrant ◄┘
  │
  ▼
END
```

### Pattern slots

| Slot | Node | Notes |
|---|---|---|
| **Detect** | `detect_node` | GitHub API read, no side effects |
| **Judge** | `judge_node` | OpenAI embed + Qdrant search, no external side effects |
| **Approve** | *(routing function)* | Contract says `approval_points: []` — the router is the decision boundary; no human gate needed for a comment-only action |
| **Act** | `act_node` + `index_node` | Two bounded side effects declared in the contract |

### How this differs from the n8n implementation

| Dimension | n8n | LangGraph |
|---|---|---|
| Trigger | GitHub webhook (live) | CLI invocation / programmatic call |
| Backfill | Second flow in same file, manual trigger | Separate `backfill.py` script |
| State | n8n execution context + Qdrant | Python TypedDict + Qdrant |
| Observability | n8n execution log | stderr log + stdout JSON summary |
| Retry | n8n's built-in retry UI | Raises on first failure (per contract) |

**What didn't vary:** the four-stage pattern, the declared permissions, the
`approval_points: []` claim, and the principle that indexing uses issue number
as the idempotency key.

---

## Prerequisites

- Python **3.11+**
- A **GitHub fine-grained Personal Access Token** scoped to one repository:
  - Permission: **Issues** → Read and Write
  - (Never Contents, Admin, or any repo-wide write permission)
- An **OpenAI API key** (for `text-embedding-3-small` embeddings — not chat completions)
- A **Qdrant instance**:
  - Local: `docker run -p 6333:6333 qdrant/qdrant` (free, no key needed)
  - Cloud: [Qdrant Cloud free tier](https://cloud.qdrant.io) (1 GB free)

---

## Setup

### 1. Install dependencies

```bash
cd implementations/langgraph/duplicate-issue-detector
pip install -e ".[dev]"
```

### 2. Create the Qdrant collection (one-time)

Run this once before any other step. `text-embedding-3-small` produces
1 536-dimensional vectors; the collection must match that size:

```bash
curl -X PUT "$QDRANT_URL/collections/$QDRANT_COLLECTION" \
  -H "Content-Type: application/json" \
  -H "api-key: $QDRANT_API_KEY" \
  -d '{"vectors": {"size": 1536, "distance": "Cosine"}}'
```

For a local unauthenticated instance, omit the `-H "api-key: ..."` header.

### 3. Configure credentials

```bash
cp .env.example .env
# Edit .env with your actual values — never commit this file
```

| Variable | Description |
|---|---|
| `GITHUB_TOKEN` | Fine-grained PAT, issues:read + issues:write |
| `OPENAI_API_KEY` | OpenAI key (embeddings only) |
| `QDRANT_URL` | e.g. `http://localhost:6333` |
| `QDRANT_COLLECTION` | Name of your collection, e.g. `github-issues` |
| `QDRANT_API_KEY` | Qdrant Cloud key — leave blank for local |

### 4. Backfill existing issues (one-time, before live use)

Without this step, the vector store is empty and detection will never fire:

```bash
python backfill.py --repo your-org/your-repo
```

The backfill embeds every open issue and upserts it into Qdrant. It takes
roughly 1–2 seconds per issue (the default 1-second delay avoids OpenAI
rate limits). A 200-issue repo takes ~3–4 minutes.

```bash
# Dry-run first to verify API access without writing anything:
python backfill.py --repo your-org/your-repo --dry-run

# Custom delay if you have a higher OpenAI tier:
python backfill.py --repo your-org/your-repo --delay 0.3
```

---

## Usage

### Run on a specific issue

```bash
python -m duplicate_issue_detector --issue 42 --repo your-org/your-repo
```

```bash
# With a custom threshold:
python -m duplicate_issue_detector --issue 42 --repo your-org/your-repo --threshold 0.90
```

**Output** (stdout, JSON):
```json
{
  "issue_number": 42,
  "repo": "your-org/your-repo",
  "threshold": 0.87,
  "issue_title": "App crashes on startup",
  "best_match_score": 0.921,
  "best_match_issue_number": 7,
  "best_match_title": "Application fails to start on Windows",
  "comment_posted": true,
  "indexed": true,
  "run_log": [
    "detect: fetched #42 title='App crashes on startup'",
    "judge: score=0.9210 match=#7",
    "act: posted comment on #42 → match=#7",
    "index: upserted #42 into github-issues"
  ]
}
```

**Logs** (stderr):
```
20:15:01 INFO    START  [repo=your-org/your-repo, issue=#42, threshold=0.87]
20:15:01 INFO    DETECT  fetching issue #42 from your-org/your-repo
20:15:02 INFO    JUDGE   embedding issue #42
20:15:03 INFO    JUDGE   best_score=0.9210, match=#7 ('Application fails to start on Windows')
20:15:03 INFO    ACT     posting duplicate comment on #42 (match=#7, score=0.9210)
20:15:04 INFO    INDEX   upserting point id=42 into github-issues
20:15:04 INFO    END    [comment_posted=True, indexed=True, best_score=0.9210]
```

### Use as a library

```python
from duplicate_issue_detector import run

final_state = run(
    issue_number=42,
    repo_owner="your-org",
    repo_name="your-repo",
    threshold=0.87,
    qdrant_url="http://localhost:6333",
    qdrant_collection="github-issues",
    qdrant_api_key="",
    github_token="ghp_...",
    openai_api_key="sk-...",
)

if final_state["comment_posted"]:
    print(f"Flagged as duplicate of #{final_state['best_match_issue_number']}")
```

---

## Threshold tuning

The default threshold of `0.87` is a starting point, not a universal truth.
Before running this unattended:

1. Run on 5–10 issue pairs you **know** are true duplicates — check the scores
2. Run on 5–10 pairs that share vocabulary but aren't duplicates — check those too
3. Set the threshold to the midpoint that separates your two groups cleanly

A threshold tuned on someone else's repo won't necessarily fit yours.

---

## Running the tests

```bash
# Run all tests (fully offline, no API calls):
pytest tests/ -v

# Run with coverage:
pytest tests/ -v --tb=short
```

All tests mock external calls (GitHub, OpenAI, Qdrant). No API keys required.

---

## Contract

Full machine-readable contract: [`contract.yaml`](./contract.yaml)

| Field | Value |
|---|---|
| **Inputs** | GitHub issue number; title + body fetched at runtime |
| **Outputs** | One GitHub comment (if duplicate found) |
| **Permissions** | `github: issues:read+write`, `openai: embeddings:read`, `qdrant: read+write on one collection` |
| **Side effects** | One comment (conditional) + one Qdrant upsert (always) |
| **Approval points** | None — comment-only, not destructive |
| **Recovery** | Raises loudly on any dependency failure; nothing is silently swallowed |
| **Replay semantics** | Idempotent on Qdrant (issue number is point ID); comment is NOT idempotent |

---

## Security notes

- Scope the GitHub token to **one repository** and **Issues permission only** —
  this workflow never needs Contents, Admin, or any org-level scope
- Your Qdrant collection stores issue titles and bodies as payload — if
  self-hosting, ensure it's not publicly accessible without authentication
- Never commit a real `.env` file — it is in `.gitignore`
- The `0.87` threshold is a starting point; a false positive posts an
  unhelpful comment, a false negative misses a duplicate — tune it

---

## Relationship to the pattern and the n8n implementation

This implementation is the first evidence for or against the core claim of the
[`agent-contracts`](../../../) repository: that patterns outlive frameworks.

The `detect → judge → approve → act` shape is identical between this and the
n8n workflow. What varied:

- The **Detect trigger** (n8n webhook vs. CLI invocation)
- The **state container** (n8n execution context vs. Python TypedDict)
- The **observability** (n8n execution log vs. structured stderr + stdout JSON)

What did **not** vary:
- The four-stage structure
- The declared permissions
- The `approval_points: []` claim and its justification
- The idempotency mechanism (issue number as vector store key)
- The principle that the Act stage only performs what the Contract lists

See [`docs/workflow-engineering.md`](../../../docs/workflow-engineering.md#why-do-patterns-outlive-frameworks)
for the hypothesis this implementation is testing.

---

Part of the [`agent-contracts`](../../../) collection.
Pattern: [`detect-judge-approve-act`](../../../patterns/detect-judge-approve-act.md)
