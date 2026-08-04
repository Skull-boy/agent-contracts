# 📊 Competitor Feature-Parity Watcher

Watches your competitors' changelogs weekly, and uses an LLM to judge which updates actually matter to your product — not just a raw feed of everything they shipped.

---

## 📖 Overview

Most "competitor tracker" tools dump every changelog entry at you, which quickly becomes noise you stop reading. This workflow is different: it compares each new update against your own product's actual feature list, scores how relevant/threatening it is (1–5), and only surfaces the ones worth your attention.

It checks two kinds of sources — competitors with an RSS/Atom feed, and competitors who only have a plain changelog webpage (handled via LLM-based extraction as a fallback). Either way, nothing gets re-reported twice: a state store remembers what's already been seen, so you only get genuinely new updates each week.

---

## 🏗️ Architecture

```
Weekly Trigger
   → Loop each competitor
       → RSS feed? → Read RSS Feed
       → Webpage?  → Fetch page → LLM extracts structured updates
   → Compare against last week's saved state (Google Sheets)
   → New items? → LLM scores relevance against YOUR feature list
   → Score ≥ 3? → Save to "flagged updates" sheet
   → Save today's state, move to next competitor
→ Once all competitors are checked: build one digest, send via Telegram
```

---

## 🚀 Getting Started

### Prerequisites
- **n8n instance** — self-hosted or Cloud
- **Google account** — for the state-tracking spreadsheet (free)
- **OpenRouter API key** — free tier available, no credit card required (see below)
- **Telegram bot** — for receiving the weekly digest

### Step 1 — Set up the Google Sheet (do this carefully — most setup issues happen here)

1. Go to [sheets.google.com](https://sheets.google.com) and create a new blank spreadsheet. Name it anything, e.g. `n8n-competitor-watcher-state`.
2. Create **two tabs** in that spreadsheet (right-click the tab bar at the bottom → rename, or use the `+` button to add a new one). Spelling and capitalization must match exactly:

   **Tab 1: `CompetitorState`** — Row 1 headers:
   ```
   competitor | lastCheckedDate
   ```

   **Tab 2: `FlaggedUpdates`** — Row 1 headers:
   ```
   competitor | title | score | reason | link | scanDate
   ```

3. Copy the **Sheet ID** from the spreadsheet's URL:
   ```
   https://docs.google.com/spreadsheets/d/THIS_PART_IS_YOUR_SHEET_ID/edit
   ```

4. In n8n, this workflow has **4 separate Google Sheets nodes**. Each one needs **two things set**, not just one:
   - **Document** field → paste your real Sheet ID (replaces `REPLACE_GOOGLE_SHEET_ID`)
   - **Sheet Within Document** field → click it and select the correct tab from the dropdown that appears — this field does **not** fill in automatically just because the Document ID is set; it's a separate click every time.

   | Node name | Sheet Within Document → select |
   |---|---|
   | Look Up Last Checked | `CompetitorState` |
   | Update Last-Checked State | `CompetitorState` |
   | Save Flagged Updates | `FlaggedUpdates` |
   | Get This Week's Flagged Updates | `FlaggedUpdates` |

5. Test each node individually with **Execute step** (not "Execute workflow") after setting it, one at a time — this catches a misconfigured node immediately instead of surfacing four errors at once during a full run.

### Step 2 — Get an OpenRouter API key
1. Sign up at [openrouter.ai](https://openrouter.ai) — no credit card required
2. Generate a key from the Keys page
3. Paste it into the `Authorization` header of both LLM nodes, replacing `REPLACE_OPENROUTER_API_KEY`
4. The workflow defaults to free-tier models with automatic fallback — check [openrouter.ai/models](https://openrouter.ai/models) before your first real run, since the free model lineup rotates and the specific model names in this workflow may need updating

### Step 3 — Set up Telegram
Same as the other workflows in this collection — create a bot via @BotFather, get your chat ID, add both to the "Send Digest" node's credentials and `REPLACE_YOUR_TELEGRAM_CHAT_ID`.

### Step 4 — Fill in your product context and watchlist
- **"Your Product Context" node** — list your product's actual current features. This is what the LLM judges relevance against, so keep it accurate and current.
- **"Competitor Watchlist" node** — add each competitor with their changelog URL and whether it's `rss` or `webpage`. For any public GitHub repo, `https://github.com/OWNER/REPO/releases.atom` always works as a reliable RSS source for testing.

---

## 🕹️ Usage
Once configured, it runs automatically on the weekly schedule. You can also trigger it manually via "Execute workflow" to test the full path end-to-end before trusting the schedule.

---

## 🔑 Placeholders to Replace

| Placeholder | Where | What to put |
|---|---|---|
| `productName` / `features` | Your Product Context node | Your product's real current feature list |
| Competitor list | Competitor Watchlist node | Name, changelog URL, and `rss`/`webpage` per competitor |
| `REPLACE_GOOGLE_SHEET_ID` | 4 Google Sheets nodes | Your spreadsheet's ID (see Step 1) |
| Google Sheets credential | Same 4 nodes | OAuth connection to your Google account |
| `REPLACE_OPENROUTER_API_KEY` | 2 LLM nodes | Your OpenRouter API key |
| `REPLACE_YOUR_TELEGRAM_CHAT_ID` + credential | Send Digest node | Your bot token + chat ID |

---

## 🔮 Roadmap
- [ ] Slack/Discord as alternative digest destinations
- [ ] Configurable relevance threshold (currently hardcoded at score ≥ 3)
- [ ] Auto-detect RSS feed availability instead of manually tagging each competitor

---

## 🔒 Security Notes
- The webpage-extraction path sends up to 8,000 characters of a competitor's public changelog page to an LLM — no private data involved, but be aware raw page content leaves your machine when using a hosted API
- Free-tier LLM usage may log prompts/completions depending on the model provider — check each model's data policy on OpenRouter if that matters for your use case
- This workflow only reads public changelog pages; it never authenticates as or scrapes behind any competitor's login wall

---

Part of the [n8n_workflows](../../) collection. See the [root README](../../README.md) for the full workflow index, and [CONTRIBUTING.md](../../CONTRIBUTING.md) for how to submit changes.
