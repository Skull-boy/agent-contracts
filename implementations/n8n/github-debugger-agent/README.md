# 🐞 AI-Powered GitHub Debugger Agent

An automated code quality agent that fetches your code, detects bugs using an LLM, and fixes them — but only when you say so.

---

## 📖 Overview

This n8n workflow acts as a **human-in-the-loop DevOps bot**. It autonomously audits a GitHub repository for bugs, inefficiencies, and redundancy, then reports its findings — it never commits blindly.

Instead of pushing AI-generated fixes straight to your repo, it sends a detailed report to Discord. You review the findings, and only if you approve (via a secure webhook link) does the agent push the fix to your repository.

---

## ✨ Key Features

- 📂 **Auto-Fetch** — recursively scans a GitHub repository for source files (`.js`, `.ts`, `.py`, `.cpp`, and more)
- 🧠 **Intelligent Analysis** — uses an LLM to identify logic errors, inefficient algorithms (e.g. avoidable O(n²) patterns), and redundant code
- 🛡️ **Human-in-the-Loop** — zero code is committed without an explicit approval click
- 🔔 **Real-Time Reporting** — delivers formatted Markdown bug reports directly to Discord
- ⚡ **Automated Fixes** — applies the AI-suggested fix immediately upon approval

---

## 🏗️ Architecture

The workflow runs as a linear 4-phase pipeline:

1. **Ingestion** — fetches the repo's file tree from GitHub and filters for source code files
2. **Analysis** — the LLM reads each file and returns a structured report plus a suggested fix
3. **Authorization** — the workflow pauses and sends a report + approval link to Discord
4. **Execution** — once approved, the workflow resumes and commits the fix via the GitHub API

---

## 🚀 Getting Started

### Prerequisites
- **n8n instance** — self-hosted or Cloud (v1.0+)
- **GitHub account** — a fine-grained Personal Access Token scoped to the specific repo you're auditing, with **Contents: Read & Write** permission only (avoid broader scopes)
- **LLM API access** — an OpenAI API key (GPT-4o or similar), or swap in a local model via Ollama/llama.cpp for a fully free, private setup
- **Discord server** — with permission to create a webhook

### Installation
1. **Import the workflow**
   In n8n: **Workflows → Import from File**, and select `workflow.json` from this folder.
2. **Configure credentials**
   - GitHub API — create a credential using your fine-grained Personal Access Token
   - LLM provider — create a credential using your OpenAI API key, or point the LLM node at your local Ollama/llama.cpp server instead
3. **Set up node values**
   - **Manual Trigger** — set your default Owner, Repo, and Branch
   - **Send to Discord** — paste your Discord Webhook URL
   - **Filter Code Files** *(optional)* — add extra file extensions if needed

---

## 🕹️ Usage

1. **Trigger the agent** — open the workflow in n8n and run it (Manual Trigger, or your own scheduled/event trigger)
2. **Wait for analysis** — the agent processes files in batches
3. **Check Discord** — you'll receive a report per flagged file, e.g. "🐞 Bug Report for `src/app.js`"
4. **Approve or ignore**
   - To fix: click the **Approve & Commit** link in the message
   - To skip: ignore the message — no changes are made

---

## 🔑 Placeholders to Replace

| Placeholder | Where | What to put |
|---|---|---|
| GitHub credential | Credentials panel | Your fine-grained PAT, scoped to one repo |
| LLM credential | Credentials panel | Your OpenAI key, or your local server's base URL |
| Discord Webhook URL | "Send to Discord" node | Your server's webhook URL |
| Owner / Repo / Branch | Manual Trigger node | The repo you want this agent auditing |

---

## 🔮 Roadmap

- [ ] **Pull Request integration** — open a PR on a `fix/ai-branch` instead of committing directly to `main`
- [ ] **RAG / context-awareness** — use a vector store so the agent understands cross-file dependencies
- [ ] **Local LLM support** — swap OpenAI for Ollama/llama.cpp for a fully private, zero-cost setup
- [ ] **Compiler loop** — run a build/test command to verify the fix before requesting approval

---

## 🔒 Security Notes

- Scope the GitHub token to exactly one repository — never a classic token with full `repo` access across your account
- Never grant this workflow permission to push directly to `main` — pair it with branch protection on the target repo
- Treat the Discord approval link as sensitive — anyone with that link can trigger the commit

---

Part of the [n8n_workflows](../../) collection. See the [root README](../../README.md) for the full workflow index, and [CONTRIBUTING.md](../../CONTRIBUTING.md) for how to submit changes.
