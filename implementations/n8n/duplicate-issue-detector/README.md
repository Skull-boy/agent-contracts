# 🔍 Semantic Duplicate Issue Detector

Automatically flags likely-duplicate GitHub issues using semantic similarity — not keyword matching — and leaves the final call to a maintainer.

> **Warning**: At first try not to use paid API of OpenAI or Claude directly. Try it out from OpenRouter or try out local model based API as its sensible.

---

## 📖 Overview

Large repositories drown in duplicate issues that waste maintainer time re-explaining the same thing. Keyword search misses most duplicates because people describe the same bug in completely different words.

This workflow embeds every issue into a vector, compares new issues against everything already indexed, and — only above a confidence threshold — comments on the new issue linking to its likely duplicate, with the actual similarity score shown. It never closes, labels, or edits anything on its own; it only leaves a comment for a human to confirm.

---

## 🏗️ Architecture

This workflow ships as **two separate flows in one file**:

**1. Backfill (manual trigger, run once)**
```
Manual Trigger → Get All Open Issues → Loop (1 at a time)
   → Embed (OpenAI) → Index into Qdrant → Wait 1s → next issue
```

**2. Live Detection (GitHub trigger, runs forever after)**
```
New Issue Opened → filter action=opened → Embed (OpenAI)
   → Search Qdrant for closest match → score ≥ 0.87?
        → yes: comment with matched issue # and score
        → either way: index this issue into Qdrant
```

The backfill flow exists because duplicate detection is useless with an empty vector store — every issue needs a baseline to compare against before the live trigger is worth turning on.

---

## 🚀 Getting Started

### Prerequisites
- **n8n instance** — self-hosted or Cloud
- **GitHub account** — fine-grained Personal Access Token scoped to one repo, with **Issues: Read & Write** permission
- **OpenAI API key** — used only for embeddings (`text-embedding-3-small`), which cost a fraction of a cent per issue — not the same cost tier as chat completion models
- **Qdrant instance** — free to self-host via Docker, or use Qdrant Cloud's free tier

### Installation
1. **Import the workflow** — n8n: **Workflows → Import from File**, select `workflow.json`
2. **Set credentials** — GitHub PAT, OpenAI API key
3. **Fill in the placeholders** (table below)

---

## ⚠️ Before You Trust It Running Unattended

Skipping any of these three steps means the workflow will either fail outright or silently do nothing useful — do them in order, before turning on the live trigger:

1. **Create the Qdrant collection first.** It needs to exist with the correct vector size before either flow will work — `text-embedding-3-small` produces 1536-dimensional vectors:
   ```bash
   curl -X PUT "{qdrant_url}/collections/{collection_name}" \
     -H "Content-Type: application/json" \
     -d '{"vectors": {"size": 1536, "distance": "Cosine"}}'
   ```

2. **Run the backfill flow once, manually, before enabling the live trigger.** This is the step most duplicate-detector tutorials skip entirely — without it, the live trigger has nothing to compare new issues against, and will run for weeks appearing to work while actually catching nothing.

3. **Tune the similarity threshold (default `0.87`) against your own repo.** Test it against a few issue pairs you already know are true duplicates, and a few that just share vocabulary but aren't. Adjust the "Score >= 0.87?" node's threshold up or down based on what you see — a threshold tuned on someone else's repo won't necessarily fit yours.

---

## 🔑 Placeholders to Replace

| Placeholder | Where | What to put |
|---|---|---|
| `REPLACE_OWNER` / `REPLACE_REPO` | 3 GitHub nodes | Your repo owner/name |
| GitHub credential | 3 GitHub nodes | Fine-grained PAT, Issues read+write only |
| OpenAI credential | 2 embedding nodes | Your OpenAI API key |
| `REPLACE_QDRANT_URL` | 4 HTTP Request nodes | Your Qdrant instance URL |
| `REPLACE_COLLECTION_NAME` | Same 4 nodes | Any name, e.g. `github-issues` |
| `REPLACE_QDRANT_API_KEY` | Same 4 nodes | Your Qdrant API key (Qdrant Cloud) or leave as-is for local Qdrant |

---

## 🕹️ Usage

1. Complete the 3 pre-flight steps above
2. Enable the GitHub trigger — the workflow now runs automatically on every new issue
3. When a likely duplicate is flagged, review the comment and matched issue yourself — the bot never closes or labels anything, it only surfaces a suggestion

---

## 🔮 Roadmap

- [ ] Auto-label flagged issues (e.g. `possible-duplicate`) in addition to commenting
- [ ] Support closed issues in the similarity search, not just open ones
- [ ] Local embedding option (Ollama `nomic-embed-text`) as a free, private alternative to OpenAI — documented as a swap-in, same pattern as this collection's other workflows
- [ ] Auto re-tune threshold suggestion based on maintainer feedback (thumbs up/down on the comment)

---

## 🔒 Security Notes

- Scope the GitHub token to exactly one repository, Issues permission only — this workflow never needs Contents or Admin access
- Your Qdrant instance stores issue titles/bodies as payload data — if self-hosting, make sure it isn't publicly exposed without authentication
- The 0.87 threshold is a starting point, not a guarantee — always keep the human-confirmation step; don't wire this to auto-close issues without review

---

Part of the [n8n_workflows](../../) collection. See the [root README](../../README.md) for the full workflow index, and [CONTRIBUTING.md](../../CONTRIBUTING.md) for how to submit changes.
