# Telegram → GitHub → Antigravity Pipeline

Message a GitHub issue number to a Telegram bot, and a local LLM reads the issue, hands off the actual coding work to Antigravity, sends you the resulting diff for review, and only pushes to a working branch once you explicitly approve it on Telegram.

> **Warning**: At first try not to use paid API of OpenAI or Claude directly. Try it out from OpenRouter or try out local model based API as its sensible.

---

## 📖 Overview

This workflow turns Telegram into a remote control for a local coding agent, while keeping a human approval gate before anything reaches GitHub. It runs entirely on infrastructure you own — a locally hosted LLM and a self-hosted n8n instance — so there are no per-token API costs and no code or data leaves your machine except the final approved push.

**Nothing is ever pushed without an explicit "Approve" tap from you.**

---

## 🏗️ Architecture

```
Telegram message ("check issue #12 in myrepo")
        │
        ▼
Authorization check (your Telegram chat ID only)
        │
        ▼
Parse issue number + repo from the message
        │
        ▼
Fetch the issue from GitHub
        │
        ▼
Local LLM (llama.cpp/Ollama) reasons about the issue
and writes a clear prompt for the coding agent
        │
        ▼
Antigravity CLI executes the prompt and writes the code
        │
        ▼
Git diff is captured
        │
        ▼
Diff is sent to you on Telegram — workflow pauses here
        │
   ┌────┴────┐
   ▼         ▼
Approve    Reject
   │         │
   ▼         ▼
Push to   Discard,
branch    notify you
```

---

## ✨ Key Features

- 📱 **Trigger from anywhere** — no laptop access needed to kick off a task, just Telegram
- 🔒 **Locked to one user** — the workflow only responds to your specific Telegram chat ID
- 🧠 **Local reasoning** — an on-device LLM (via llama.cpp or Ollama) interprets the issue and writes the working prompt, no cloud LLM bill for this step
- 🛠️ **Delegated coding** — the actual code is written by Antigravity's own model, via its `agy` CLI
- 🛡️ **Human-in-the-loop by default** — the workflow always pauses for your explicit approval before touching GitHub
- 🌿 **Branch-safe** — pushes only ever go to a dedicated working branch, never directly to `main`

---

## 🚀 Getting Started

### Prerequisites
- **n8n** — self-hosted (Docker recommended), not n8n Cloud, since this workflow shells out to local commands (`git`, `agy`) that only exist on your machine
- **A local LLM server** — llama.cpp (`llama-server.exe`) or Ollama, exposing an OpenAI-compatible endpoint (default: `http://localhost:11434/v1`)
- **Antigravity** — installed locally with the `agy` CLI available on your PATH
- **A Telegram bot** — created via [@BotFather](https://t.me/BotFather)
- **GitHub fine-grained Personal Access Token** — scoped to only the repo(s) you intend to automate, with Contents + Pull requests permissions only (no admin, no other repos)
- **Git installed locally**, with the target repo already cloned to your machine

### Installation
1. In n8n: **Workflows → Import from File**, select `workflow.json` from this folder
2. Set up credentials:
   - **Telegram API** — paste your BotFather token
   - **GitHub API** — paste your fine-grained PAT
   - **Ollama/llama.cpp** — base URL `http://localhost:11434/v1` (no API key needed for localhost)
3. Fill in the placeholders below (see table)
4. Activate the workflow

### Placeholders to replace before running

| Placeholder | Node | What to put |
|---|---|---|
| `REPLACE_WITH_YOUR_TELEGRAM_CHAT_ID` | "Is It Me?" | Your numeric Telegram ID (get it from [@userinfobot](https://t.me/userinfobot)) |
| `REPLACE_DEFAULT_OWNER/REPLACE_DEFAULT_REPO` | "Parse Telegram Message" | Fallback GitHub `owner/repo` if not specified in your message |
| `REPLACE_WITH_LOCAL_REPO_FOLDER` | "Run Antigravity CLI", "Get Git Diff", "Push To Branch" | Local filesystem path to your cloned repo |
| `hermes3-custom` (model name) | "Local llama.cpp Server" | Your actual local model name/tag if different |

---

## 🕹️ Usage

1. Message your bot on Telegram:
   ```
   check issue #12 in myusername/myrepo
   ```
2. Wait — the workflow fetches the issue, reasons about it locally, and hands it to Antigravity
3. You'll receive a Telegram message with the resulting diff and two buttons: **✅ Push it** / **❌ Discard**
4. Tap **Push it** to create a branch (`fix-issue-<number>`), commit, and push — or tap **Discard** to drop the changes with nothing sent to GitHub
5. Open a pull request from the pushed branch when you're ready to merge

---

## 🔒 Security Notes

- The Telegram chat ID check is your primary access control — don't skip setting it
- Keep the GitHub token scoped to a single repo with the minimum permissions needed
- Set up branch protection on `main` in the target repo so this workflow (or anything else) can never push there directly
- Treat GitHub issue content as untrusted input — the LLM reasoning step reads whatever is in the issue body, so don't run this against repos where issues can be opened by untrusted third parties without reviewing the diff carefully before approving

---

## 🔮 Possible Improvements

- [ ] Auto-open a pull request after pushing, instead of stopping at the branch push
- [ ] Add a "run tests" step before sending the diff for approval
- [ ] Support voice-message triggers via Telegram + Whisper for hands-free triggering
- [ ] Add a timeout/reminder if the approval message goes unanswered

---

## 📄 License

Distributed under the repository's [MIT License](../../LICENSE).
