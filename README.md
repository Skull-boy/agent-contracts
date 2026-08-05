<div align="center">

<img src="assets/logo.png" width="450" alt="agent-contracts"/>

# agent-contracts

**A portable contract layer for AI agents — what they're allowed to do, what requires approval, what side effects they may create, and what happens when execution fails.**

MCP and A2A are standardizing how agents talk to tools and to each other. Nobody has standardized what an agent is actually *allowed to do* once it's talking. `agent-contracts` is that layer.

![License](https://img.shields.io/github/license/Skull-boy/agent-contracts)
![Stars](https://img.shields.io/github/stars/Skull-boy/agent-contracts)
![Issues](https://img.shields.io/github/issues/Skull-boy/agent-contracts)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)

</div>

This repository is organized around a documented set of reusable automation **patterns**, each with a framework-agnostic specification and a **Contract** declaring exactly what a given implementation is allowed to do. Read [`docs/workflow-engineering.md`](./docs/workflow-engineering.md) for the full reasoning, [`docs/architecture.md`](./docs/architecture.md) for how the pieces fit together, and [`WORKFLOW-CONTRACT-SPEC.md`](./WORKFLOW-CONTRACT-SPEC.md) for the spec itself. n8n and LangGraph are implementation targets, not the identity — Make, LangChain, or anything that comes after are equally valid.

> **Contract rollout status:** newly added implementations ship with a full v1 Contract (ten fields, `README.md` + `contract.yaml`) from day one. Earlier workflows are being migrated to the same format — tracked in [this issue](../../issues) — check a given implementation's own README for its current status.

> **Spec status — v1.1 in design:** Contract v1 was shaped by coding/developer-agent examples (GitHub bots, issue detectors). v1.1 is an active redesign to make the spec domain-independent — usable for research, finance, education, healthcare-workflow, and other non-coding agents — and accessible to non-technical authors, not just YAML/CLI users. This is design work in progress, not a shipped feature. Follow it in [`implementations/rfcs/`](./implementations/rfcs).

> **Warning**: At first try not to use paid API of OpenAI or Claude directly. Try it out from OpenRouter or try out local model based API as its sensible.

---

## 🧩 What This Actually Is

MCP and A2A solved *how agents talk* — to tools, to each other. Neither says anything about what an agent is actually allowed to do once it's talking. That gap is what this repository is for.

Today, every implementation here is a concrete automation built in n8n or LangGraph — the current lineup leans developer/coding-agent because that's what got built first. What's reusable isn't the framework, it's the pattern underneath: `fetch → classify → route → notify`, or `detect → judge → approve → act` — the same shape regardless of what runs it. Every implementation documents that pattern explicitly and declares a Contract governing it, so the ideas stay portable even if you never touch n8n or Python.

The Contract model itself is framework-independent by design, and the project is now working to make it domain-independent too — see the v1.1 note above. That work is happening in the open; nothing below claims domain independence that doesn't exist yet.

This direction came directly out of a [community discussion](https://www.reddit.com/r/AI_Agents/comments/1v6dny2/) where several people, independently, converged on the same conclusion: the missing piece in agentic automation isn't more agents — it's a shared, checkable contract for what they're allowed to do.

---

## 📋 Every Implementation Documents a Contract

Instead of just a prose README, each implementation ships:

- **Inputs** — what data goes in
- **Outputs** — what it produces, if anything
- **Permissions** — exactly what it can read/write, scoped precisely, nothing implied
- **Side Effects** — every action it can take, explicitly bounded
- **Approval Points** — where a human has to say yes before anything irreversible happens
- **Recovery Strategy** — what it does when a dependency fails, instead of failing silently
- **Replay Semantics** — whether it's safe to run twice on the same input, and why
- **Dependencies, State, Observability** — what it needs, what persists, what it surfaces about its own execution

This is what "human-in-the-loop by default" actually means in practice — not a slogan, a checkable spec per implementation. Each field is documented in depth in [`docs/concepts/`](./docs/concepts).

A valid Contract is not proof of a safe or trustworthy agent — it's a structural declaration. What it declares still has to be verified, enforced, and observed at runtime; those are separate, harder problems the project is working toward, not solved ones.

---

## 🧠 The Model

```
Pattern  →  Implementation  →  Contract
```

A **Pattern** is the abstract, framework-agnostic shape (`patterns/`). An **Implementation** is one concrete realization of it in a specific framework (`implementations/<framework>/<name>/`). A **Contract** describes exactly what that one implementation is allowed to do — it belongs to the implementation, not the pattern, because permissions and side effects are specific to how something was actually built. Full reasoning in [`docs/architecture.md`](./docs/architecture.md).

Structural and governance changes to this model itself go through an RFC, recorded permanently in `implementations/rfcs/` once decided.

---

## 📂 Repository Structure

```
agent-contracts/
├── README.md
├── WORKFLOW-CONTRACT-SPEC.md
├── CONTRIBUTING.md
├── CONTRIBUTORS.md
├── LICENSE
├── requirements-dev.txt
├── .github/
│   └── workflows/
│       └── validate-contracts.yml
├── assets/
│   ├── logo.png
│   └── logo-light.jpeg
├── docs/
│   ├── workflow-engineering.md
│   ├── architecture.md
│   └── concepts/
│       ├── permissions.md
│       ├── side-effects.md
│       ├── approval-boundaries.md
│       ├── replay-semantics.md
│       └── recovery.md
├── patterns/
│   └── detect-judge-approve-act.md
├── schemas/
│   └── v1/
│       └── contract.schema.json
├── scripts/
│   └── validate_contracts.py
└── implementations/
    ├── n8n/
    │   ├── github-debugger-agent/
    │   │   ├── workflow.json
    │   │   ├── contract.yaml
    │   │   └── README.md
    │   ├── telegram-github-antigravity-pipeline/
    │   │   ├── workflow.json
    │   │   ├── contract.yaml
    │   │   └── README.md
    │   ├── duplicate-issue-detector/
    │   │   ├── workflow.json
    │   │   ├── contract.yaml
    │   │   └── README.md
    │   └── competitor-feature-parity-watcher/
    │       ├── workflow.json
    │       ├── contract.yaml
    │       └── README.md
    ├── langgraph/
    │   ├── duplicate-issue-detector/
    │   │   ├── duplicate_issue_detector/
    │   │   │   ├── __init__.py
    │   │   │   ├── __main__.py
    │   │   │   ├── graph.py
    │   │   │   ├── nodes.py
    │   │   │   └── state.py
    │   │   ├── backfill.py
    │   │   ├── pyproject.toml
    │   │   ├── contract.yaml
    │   │   ├── .env.example
    │   │   └── README.md
    │   └── telegram-github-antigravity-pipeline/
    └── rfcs/
        └── 01-contract-model.md
```

Each implementation lives in its own folder under `implementations/<framework>/`, so the collection can grow — across frameworks, not just within n8n — without the root becoming cluttered.

---

## 🗂️ Implementation Index

### n8n

| Implementation | Description | Stack |
|---|---|---|
| [GitHub Debugger Agent](./implementations/n8n/github-debugger-agent) | Scans a repo for bugs/inefficiencies with an LLM, reports to Discord, fixes only on approval | n8n, OpenAI/GPT-4o, GitHub API, Discord |
| [Telegram → GitHub → Antigravity Pipeline](./implementations/n8n/telegram-github-antigravity-pipeline) | Message an issue number on Telegram; a local LLM reasons about it, Antigravity codes the fix, you approve, it pushes | n8n, Ollama/llama.cpp, GitHub API, Antigravity CLI, Telegram |
| [Semantic Duplicate Issue Detector](./implementations/n8n/duplicate-issue-detector) | Flags likely-duplicate GitHub issues using semantic similarity, comments with the match — never closes/labels without review | n8n, OpenAI Embeddings, Qdrant, GitHub API |
| [Competitor Feature-Parity Watcher](./implementations/n8n/competitor-feature-parity-watcher) | Watches competitor changelogs weekly; an LLM scores relevance (with debuggable reason codes) against your own feature list | n8n, OpenRouter, Google Sheets, RSS |

### LangGraph

| Implementation | Description | Stack |
|---|---|---|
| [Semantic Duplicate Issue Detector](./implementations/langgraph/duplicate-issue-detector) | Python-native port of the duplicate-detector: LangGraph graph, Qdrant vector store, backfill script for existing issues | LangGraph, OpenAI Embeddings, Qdrant, GitHub API |
| [Telegram → GitHub → Antigravity Pipeline](./implementations/langgraph/telegram-github-antigravity-pipeline) | LangGraph port of the Telegram → GitHub pipeline | LangGraph, GitHub API, Antigravity CLI, Telegram |

*(New implementations are added regularly — see [open issues](../../issues) or watch this repo for updates. Implementations outside the coding/developer-agent space are on the v1.1 roadmap, not yet present.)*

---

## 🚀 Getting Started

**Prerequisites (common to all implementations):**
- Git and a GitHub account, with a fine-grained Personal Access Token scoped to the specific repo you're automating
- Any implementation-specific requirements — see its own README (LLM provider, messaging platform, vector store, etc.)

**n8n implementations:**
1. Open the implementation folder under `implementations/n8n/<name>/`
2. Read its `README.md` for its Contract, prerequisites, and setup steps
3. In n8n: **Workflows → Import from File**, select its `workflow.json`
4. Fill in the credentials and placeholder values called out in its README
5. Test on a throwaway/sandbox repo before pointing it at anything important

**LangGraph implementations:**
1. Open the implementation folder under `implementations/langgraph/<name>/`
2. Read its `README.md` — each ships a `pyproject.toml` and `.env.example`
3. Install dependencies: `pip install -e .` (or `uv sync`)
4. Copy `.env.example` to `.env` and fill in your secrets
5. Run via `python -m <package_name>` or the entry point documented in its README

---

## 🔐 Before You Import Any Implementation — Check This First

Workflow files can embed logic that touches credentials, files, and external services. Before importing anything from this repo (or anywhere else):

- [ ] Open the raw `workflow.json` and skim every `httpRequest` node's URL — does every destination make sense for what it claims to do?
- [ ] Check every node with a credential attached — does it request only the permissions its Contract says it needs?
- [ ] Look for anything that sends data to an unfamiliar or unexplained external domain
- [ ] Never import something that asks for broader credential scope than its stated Contract requires

This applies to every implementation in this repo too — if you spot something that doesn't match its documented Contract, please open an issue.

---

## 🗺️ Where the Spec Is Headed (v1.1)

Contract v1 was designed and proven against coding/developer agents. That's now understood to be a starting substrate, not the ceiling — v1.1 is a deliberate audit-and-redesign effort to make the spec:

- **Domain-independent** — usable for research, education, finance, business-workflow, and healthcare-workflow agents, not just coding agents
- **Framework-independent** — already true in principle (n8n + LangGraph prove it), being stress-tested further
- **Accessible to non-technical authors** — YAML/JSON is a representation format, not meant to be the only way to create a contract

This is genuinely in the design/audit phase — classifying existing Contract v1 fields, testing them against non-coding agent archetypes, and only then extending the schema. Nothing in this section describes a shipped feature. Follow progress in [`implementations/rfcs/`](./implementations/rfcs) and open issues tagged `v1.1`.

---

## 🤝 Contributing

Contributions are welcome — new implementations, new patterns, fixes to existing ones, clearer documentation, or a Contract for something that doesn't have one yet. See [CONTRIBUTING.md](./CONTRIBUTING.md) for the full process. In short:

1. Fork the repo
2. Add your implementation under `implementations/<framework>/<name>/`, including its `workflow.json` (or equivalent), `contract.yaml`, and `README.md`
3. Open a pull request — branch off `main`, never commit directly to it
4. Check the [open issues](../../issues) tagged `good first issue` or `help wanted` if you're not sure where to start
5. Proposing a change to the Contract spec or the repository's own structure? That goes through an RFC — see [`docs/architecture.md`](./docs/architecture.md#how-a-contribution-actually-moves-through-this)

If your submission handles credentials, tokens, or personal data anywhere in its JSON, scrub them and replace with placeholders (e.g. `REPLACE_ME`) before committing — see the [Security Note](#-security-note) below.

Everyone who contributes code or meaningfully shapes this project through discussion is credited in [CONTRIBUTORS.md](./CONTRIBUTORS.md).

---

## 🔒 Security Note

n8n exports can embed credential *references* but not raw secrets by default — still, always double-check your exported JSON before committing. Never commit:
- API keys, tokens, or webhook secrets
- Real chat IDs, user IDs, or email addresses
- Real repo names/paths if they reveal something private

Use placeholder values (`REPLACE_ME`, `YOUR_CHAT_ID`, etc.) in anything published here.

---

## 📄 License

Distributed under the MIT License — see [LICENSE](./LICENSE) for details. You're free to use, modify, and redistribute anything here, including commercially, with attribution.

---

Built and maintained by [Shinjan Das](https://github.com/Skull-boy) — see [CONTRIBUTORS.md](./CONTRIBUTORS.md) for everyone who's helped shape it. Issues and PRs welcome.
