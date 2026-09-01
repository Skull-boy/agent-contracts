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
   → Embed (OpenAI or Ollama) → Index into Qdrant → Wait 1s → next issue
```

**2. Live Detection (GitHub trigger, runs forever after)**
```
New Issue Opened → filter action=opened → Embed (OpenAI or Ollama)
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
- **Embedding provider** — OpenAI (`text-embedding-3-small`) by default, or a self-hosted Ollama server running `nomic-embed-text`
- **Qdrant instance** — free to self-host via Docker, or use Qdrant Cloud's free tier

### Installation
1. **Import the workflow** — n8n: **Workflows → Import from File**, select `workflow.json`
2. **Set credentials** — GitHub PAT and, when using the default provider, an OpenAI API key
3. **Fill in the placeholders** (table below)

### Local Ollama option

Both flows include a disabled Ollama HTTP Request node alongside the enabled OpenAI node. To use local embeddings:

1. Install [Ollama](https://ollama.com), then pull the default model:
   ```bash
   ollama pull nomic-embed-text
   ```
2. Set `REPLACE_OLLAMA_BASE_URL` in both Ollama nodes to the URL reachable from n8n (for example, `http://localhost:11434`). n8n Cloud cannot reach a service on your computer's `localhost`; use a self-hosted n8n instance or an appropriately exposed Ollama endpoint.
3. In both the live and backfill paths, disable the OpenAI node and enable the corresponding Ollama node. Do not leave both providers enabled, or each issue will be processed twice.
4. Recreate the Qdrant collection before switching providers. `nomic-embed-text` returns 768-dimensional vectors, so the collection must use size `768`; do not mix them with the existing 1536-dimensional OpenAI vectors. Run the backfill flow again after recreating the collection.

To use another Ollama embedding model, change the model name in both Ollama nodes and create the Qdrant collection with that model's actual output dimension.

---

## ⚠️ Before You Trust It Running Unattended

Skipping any of these three steps means the workflow will either fail outright or silently do nothing useful — do them in order, before turning on the live trigger:

1. **Create the Qdrant collection first.** It needs to exist with the correct vector size before either flow will work. The default OpenAI path uses 1536-dimensional `text-embedding-3-small` vectors:
   ```bash
   curl -X PUT "{qdrant_url}/collections/{collection_name}" \
     -H "Content-Type: application/json" \
     -d '{"vectors": {"size": 1536, "distance": "Cosine"}}'
   ```
   If you switch to Ollama, use the local model's output dimension instead (768 for `nomic-embed-text`; see the local setup above).

2. **Run the backfill flow once, manually, before enabling the live trigger.** This is the step most duplicate-detector tutorials skip entirely — without it, the live trigger has nothing to compare new issues against, and will run for weeks appearing to work while actually catching nothing.

3. **Tune the similarity threshold (default `0.87`) against your own repo.** Test it against a few issue pairs you already know are true duplicates, and a few that just share vocabulary but aren't. Adjust the "Score >= 0.87?" node's threshold up or down based on what you see — a threshold tuned on someone else's repo won't necessarily fit yours.

---

## 🔑 Placeholders to Replace

| Placeholder | Where | What to put |
|---|---|---|
| `REPLACE_OWNER` / `REPLACE_REPO` | 3 GitHub nodes | Your repo owner/name |
| GitHub credential | 3 GitHub nodes | Fine-grained PAT, Issues read+write only |
| OpenAI credential | 2 embedding nodes | Your OpenAI API key |
| `REPLACE_OLLAMA_BASE_URL` | 2 disabled Ollama nodes | Ollama base URL reachable from n8n, without the `/api` suffix |
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
- [x] Local embedding option (Ollama `nomic-embed-text`) as a free, private alternative to OpenAI — documented as a swap-in, same pattern as this collection's other workflows
- [ ] Auto re-tune threshold suggestion based on maintainer feedback (thumbs up/down on the comment)

---

## 🔒 Security Notes

- Scope the GitHub token to exactly one repository, Issues permission only — this workflow never needs Contents or Admin access
- Your Qdrant instance stores issue titles/bodies as payload data — if self-hosting, make sure it isn't publicly exposed without authentication
- The 0.87 threshold is a starting point, not a guarantee — always keep the human-confirmation step; don't wire this to auto-close issues without review

---

Part of the [n8n_workflows](../../) collection. See the [root README](../../README.md) for the full workflow index, and [CONTRIBUTING.md](../../CONTRIBUTING.md) for how to submit changes.
