<div align="center">

<img src="assets/logo.png" width="450" alt="agent-contracts"/>

# agent-contracts

**Portable contracts for agentic workflows — permissions, side effects, approval boundaries, recovery, and execution guarantees.**

MCP and A2A are standardizing how agents interact with tools and with each other. agent-contracts is the layer above that: what an agent is allowed to do, what requires approval, what side effects it may create, and what should happen when execution fails.

![License](https://img.shields.io/github/license/Skull-boy/agent-contracts)
![Stars](https://img.shields.io/github/stars/Skull-boy/agent-contracts)
![Issues](https://img.shields.io/github/issues/Skull-boy/agent-contracts)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)

</div>

This repository is organized around a documented set of reusable automation **patterns**, each with a framework-agnostic specification and a **Contract** declaring exactly what a given implementation is allowed to do. Read [`docs/workflow-engineering.md`](./docs/workflow-engineering.md) for the full reasoning, [`docs/architecture.md`](./docs/architecture.md) for how the pieces fit together, and [`WORKFLOW-CONTRACT-SPEC.md`](./WORKFLOW-CONTRACT-SPEC.md) for the spec itself. n8n is the first implementation, not the identity — Make, LangGraph, LangChain, or anything that comes after are equally valid targets for the same Contract.

> **Contract rollout status:** newly added implementations ship with a full v1 Contract (ten fields, `README.md` + `contract.yaml`) from day one. Earlier workflows are being migrated to the same format — tracked in [this issue](../../issues) — check a given implementation's own README for its current status.

---

## 🧩 What This Actually Is

MCP and A2A solved *how agents talk* — to tools, to each other. Neither says anything about what an agent is actually allowed to do once it's talking. That gap is what this repository is for.

The n8n workflow is the *implementation*, not the point. What's reusable is the pattern underneath it — `fetch → classify → route → notify`, or `detect → judge → approve → act` — the same shape whether it's built in n8n, LangGraph, or something that doesn't exist yet. Every implementation here documents that pattern explicitly, and declares a Contract governing it, so the ideas are portable even if you never touch n8n.

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

---

## 🧠 The Model

```
Pattern  →  Implementation  →  Contract
```

A **Pattern** is the abstract, framework-agnostic shape (`patterns/`). An **Implementation** is one concrete realization of it in a specific framework (`implementations/<framework>/<name>/`). A **Contract** describes exactly what that one implementation is allowed to do — it belongs to the implementation, not the pattern, because permissions and side effects are specific to how something was actually built. Full reasoning in [`docs/architecture.md`](./docs/architecture.md).

Structural and governance changes to this model itself go through an RFC, recorded permanently in [`rfcs/`](./rfcs) once decided.

---

## 📂 Repository Structure

```
agent-contracts/
├── README.md
├── WORKFLOW-CONTRACT-SPEC.md
├── CONTRIBUTING.md
├── CONTRIBUTORS.md
├── LICENSE
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
├── implementations/
│   └── n8n/
│       ├── github-debugger-agent/
│       ├── telegram-github-antigravity-pipeline/
│       ├── duplicate-issue-detector/
│       │   ├── workflow.json
│       │   ├── contract.yaml
│       │   └── README.md
│       ├── competitor-feature-parity-watcher/
│       ├── job-application-silent-rejection-detector/
│       └── telegram-structured-solver-pdf/
└── rfcs/
    └── 0001-contract-model.md
```

Each implementation lives in its own folder under `implementations/<framework>/`, so the collection can grow — across frameworks, not just within n8n — without the root becoming cluttered.

> **This structure reflects the direction proposed in the open Migration RFC.** If that RFC hasn't been resolved with the community members it was raised with yet, confirm this tree matches what's actually merged on `main` before treating it as current fact rather than intent.

---

## 🗂️ Implementation Index

| Implementation | Description | Stack |
|---|---|---|
| [GitHub Debugger Agent](./implementations/n8n/github-debugger-agent) | Scans a repo for bugs/inefficiencies with an LLM, reports to Discord, fixes only on approval | n8n, OpenAI/GPT-4o, GitHub API, Discord |
| [Telegram → GitHub → Antigravity Pipeline](./implementations/n8n/telegram-github-antigravity-pipeline) | Message an issue number on Telegram; a local LLM reasons about it, Antigravity codes the fix, you approve, it pushes | n8n, Ollama/llama.cpp, GitHub API, Antigravity CLI, Telegram |
| [Semantic Duplicate Issue Detector](./implementations/n8n/duplicate-issue-detector) | Flags likely-duplicate GitHub issues using semantic similarity, comments with the match — never closes/labels without review | n8n, OpenAI Embeddings, Qdrant, GitHub API |
| [Competitor Feature-Parity Watcher](./implementations/n8n/competitor-feature-parity-watcher) | Watches competitor changelogs weekly; an LLM scores relevance (with debuggable reason codes) against your own feature list | n8n, OpenRouter, Google Sheets, RSS |
| [Job Application Silent-Rejection Detector](./implementations/n8n/job-application-silent-rejection-detector) | Watches postings you've applied to for status changes — a real signal instead of indefinite silence | n8n, OpenRouter, Google Sheets |
| [Telegram Structured Solver → PDF](./implementations/n8n/telegram-structured-solver-pdf) | Message an assignment to a bot; an agent solves it step-by-step in strict JSON with a self-correcting retry loop, returns a formatted PDF | n8n, OpenAI, Telegram, PDFShift |

*(New implementations are added regularly — see [open issues](../../issues) or watch this repo for updates.)*

---

## 🚀 Getting Started

**Prerequisites (common to most n8n implementations in this repo):**
- An n8n instance — self-hosted (Docker) or n8n Cloud (v1.28+ recommended for native Ollama support)
- Git and a GitHub account, with a fine-grained Personal Access Token scoped to the specific repo you're automating
- Any implementation-specific requirements — see its own README (LLM provider, messaging platform, etc.)

**To use any implementation:**
1. Open its folder under `implementations/<framework>/`
2. Read its README for its Contract, prerequisites, and setup steps
3. In n8n: **Workflows → Import from File**, select its `workflow.json`
4. Fill in the credentials and placeholder values called out in its README
5. Test on a throwaway/sandbox repo before pointing it at anything important

---

## 🔐 Before You Import Any Implementation — Check This First

Workflow files can embed logic that touches credentials, files, and external services. Before importing anything from this repo (or anywhere else):

- [ ] Open the raw `workflow.json` and skim every `httpRequest` node's URL — does every destination make sense for what it claims to do?
- [ ] Check every node with a credential attached — does it request only the permissions its Contract says it needs?
- [ ] Look for anything that sends data to an unfamiliar or unexplained external domain
- [ ] Never import something that asks for broader credential scope than its stated Contract requires

This applies to every implementation in this repo too — if you spot something that doesn't match its documented Contract, please open an issue.

---

## 🤝 Contributing

Contributions are welcome — new implementations, new patterns, fixes to existing ones, clearer documentation, or a Contract for something that doesn't have one yet. See [CONTRIBUTING.md](./CONTRIBUTING.md) for the full process. In short:

1. Fork the repo
2. Add your implementation under `implementations/<framework>/<name>/`, including its `workflow.json`, `contract.yaml`, and `README.md`
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
