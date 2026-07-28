# Workflow Engineering

**Status:** Draft
**Applies to:** every workflow, pattern, and contract in this repository — the reasoning everything else points back to

---

## Why this exists

Most automation gets built once, works, and disappears into whoever built it. The workflow runs, the problem gets solved, and the thinking behind it — why it's shaped the way it is, what it's allowed to touch, what happens when it fails — never leaves that one person's head.

Workflow engineering is the discipline of writing that thinking down in a form other people can actually use: not just the finished automation, but the reasoning underneath it, in a shape that survives past the tool it happened to be built in.

This document is the reasoning. [`WORKFLOW-CONTRACT-SPEC.md`](../WORKFLOW-CONTRACT-SPEC.md) is the mechanism it leads to.

---

## Why isn't JSON enough?

An exported `workflow.json` tells you *what* a workflow does, node by node. It tells you nothing about *why* it's built that way, what happens when a dependency fails, or what it's allowed to do that isn't obvious from reading node names.

A JSON file is also silently coupled to one person's specific setup — their credential scoping, their assumptions about what "done" means, their tolerance for failure. Import it without that context and you've imported behavior you don't actually understand yet.

JSON is the artifact. It was never meant to be the documentation.

---

## Why aren't screenshots enough?

A screenshot of a workflow canvas proves something was built. It proves nothing about whether it's safe to reuse, what it actually does when something goes wrong, or whether the person sharing it understood their own design decisions or got lucky.

Screenshots are proof of existence. They're not proof of engineering.

---

## What makes a workflow reusable?

Not the node layout. Not the specific API calls. What survives being rebuilt in a different tool is the *shape* underneath it — `fetch → classify → route → notify`, or `detect → judge → approve → act`. That shape is a **Pattern**. The n8n workflow is one **Implementation** of it.

A workflow is reusable when someone could describe its logic to you on a whiteboard, in a framework you've never touched, and you'd know exactly what to build.

---

## Why do contracts matter?

Documentation describes. Contracts commit.

A README can say a workflow "only comments on GitHub issues" — a claim, true until someone edits the workflow and forgets to update the sentence next to it. A **Contract** is a fixed-shape declaration of what a workflow is allowed to do: its permissions, its side effects, where a human has to approve before anything irreversible happens, what happens when a dependency fails. Written so a human — and eventually a tool — can check whether the implementation actually matches what it claims.

This isn't hypothetical. Every workflow in this repository is expected to ship one, and the [Semantic Duplicate Issue Detector](../workflows/duplicate-issue-detector) is the first fully worked example — Contract written, checked against the real implementation, not just described in prose.

---

## Why do patterns outlive frameworks?

This is the part of this document we can't yet prove, and we want to be honest about that rather than pretend otherwise.

The claim: a Pattern like `detect → judge → approve → act`, once its Contract is well-specified, should be rebuildable in LangGraph, OpenAI Agents, Semantic Kernel, or whatever comes after them — because the *pattern* isn't tied to n8n, only today's *implementation* of it is.

We believe this. We haven't demonstrated it yet. Every implementation in this repository today is n8n. The real test of this claim is a second-framework implementation of an existing pattern — and until that exists, "patterns outlive frameworks" is a hypothesis this repository is organized around, not a fact it has already proven.

If you build that second implementation, you're not adding a folder. You're the first real evidence for or against the core idea this repository is betting on.

---

## Why does this repository exist?

It started as a place to stop letting useful n8n workflows die in a private folder. That's still true, and it's still valuable on its own.

But repeated, independent conversation — on Reddit, in issues, in PR discussion — kept arriving at the same missing piece, described in different words by different people who hadn't read each other's comments. Not "share more workflows." A shared, checkable contract for what an automated system is allowed to do, and a vocabulary for talking about the pattern underneath a workflow independently of the tool it's built in.

That's what this repository is actually trying to be: a place where the engineering reasoning behind automation is written down and argued about in public, with n8n as the first implementation, not the identity.

---

## Vocabulary

Consistent terms, defined once, used the same way everywhere else in this repository:

| Term | Definition |
|---|---|
| **Pattern** | The reusable, framework-independent shape of a workflow — e.g. `detect → judge → approve → act`. Abstract; not tied to any tool. |
| **Contract** | A fixed-shape declaration of one specific implementation's behavior — permissions, side effects, approval points, recovery strategy. Concrete; specific to one implementation. See [`WORKFLOW-CONTRACT-SPEC.md`](../WORKFLOW-CONTRACT-SPEC.md). |
| **Implementation** | One realization of a Pattern in a specific framework — the n8n `workflow.json`, a future LangGraph graph, etc. A Pattern can have multiple Implementations, each with its own Contract. |
| **Replay Semantics** | Whether it's safe to run a workflow again on the same input — idempotent, append-only, or unsafe-to-repeat. |
| **Side Effects** | Every action a workflow can take in the world. If it's not declared, the workflow shouldn't do it. |
| **Recovery Strategy** | What a workflow does when a dependency fails mid-run — retry, fail loudly, fail silently and log. |
| **Human Approval Boundary** | The point in a workflow where it stops and requires explicit human sign-off before proceeding to anything irreversible. |
| **Observability Hooks** | What a workflow surfaces about its own execution — logs, digest messages, dashboards — so its behavior isn't a black box after the fact. |

---

## Relationship to Other Documents

This document explains *why*. [`WORKFLOW-CONTRACT-SPEC.md`](../WORKFLOW-CONTRACT-SPEC.md) defines *how* — the exact fields, format, and versioning process a Contract follows. Read this one first; it's the reasoning the spec assumes you already have.

---

## Non-Goals

- **This is not a roadmap.** It doesn't list what ships when — see the repository's issues and RFCs for that.
- **This is not a specification.** It defines no checkable format itself; `WORKFLOW-CONTRACT-SPEC.md` does that.
- **This is not a finished claim.** The "patterns outlive frameworks" section is a stated hypothesis, not a demonstrated result — this document changes when the evidence changes, including the parts of it that are still unproven today.
