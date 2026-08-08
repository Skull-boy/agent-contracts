# RFC 02 — Contract v1.1: Domain Independence

**Status:** Proposed / In Progress
**Author:** [Shinjan Das](https://github.com/Skull-boy)
**Depends on:** [RFC 01 — Contract Model](./01-contract-model.md)

---

## 1. Summary

Contract v1 was designed, and its examples were chosen, around coding and developer agents (GitHub bots, issue detectors, CI-adjacent pipelines). This RFC proposes that **domain independence become a first-class requirement of the spec, alongside its existing framework independence**, and defines the process for getting there.

This RFC does **not** propose specific new schema fields. It proposes the audit and validation process that must happen before any fields are added, changed, or removed for v1.1.

---

## 2. Motivation

Framework independence was already a founding goal — n8n is one implementation target among several. Domain independence was not: nothing in Contract v1 has been tested against agents outside coding/developer contexts (research agents, student-facing agents, finance agents, business-workflow agents, healthcare-workflow agents, etc.).

Without this work, the spec risks:
- encoding coding-agent assumptions as if they were universal
- becoming unusable, or usable only with hacks, for non-coding domains
- staying inaccessible to non-technical authors, since the only interface today is a hand-written `contract.yaml`

## 3. Non-goals

This RFC does **not** propose:
- a visual contract builder or any specific authoring UI
- a finalized Core + Profiles + Extensions schema
- healthcare, finance, or any other domain being "supported" — regulated domains are stress tests for the model, not certified use cases
- a compatibility, negotiation, or runtime-conformance protocol

Those are downstream of this work, tracked separately once this audit concludes.

## 4. Guiding distinction

```
AGENT IMPLEMENTATION  ≠  AGENT CONTRACT
```

The contract describes the boundary around an agent (inputs, outputs, permissions, side effects, approval points, recovery, replay semantics) — not its internal reasoning, framework, or orchestration. Any v1.1 change must be evaluated against whether it respects this boundary.

It's also worth stating plainly: a structurally valid contract is not proof of a trustworthy, verified, or enforced agent. v1.1 changes the *representation*, not this trust model.

## 5. Process

No schema field is added, generalized, moved to a profile, deprecated, or removed until this sequence has been run:

1. **Freeze assumptions** — write down what Contract v1 currently assumes about agents, explicitly.
2. **Inspect current v1** — spec, schema, package, and every existing implementation's `contract.yaml`.
3. **Identify coding/developer-specific assumptions** — flag anything that only makes sense because the first examples were GitHub/CI-adjacent agents.
4. **Build heterogeneous agent archetypes** — at minimum:
   - coding / GitHub agent
   - student learning assistant
   - scientific research agent
   - financial analysis agent
   - business workflow agent
   - customer-support agent
   - healthcare workflow/support agent
   - browser automation agent
   - data analysis agent
   - enterprise approval/procurement agent
   - education/teaching agent
   - multi-agent coordinator
5. **Attempt to model all archetypes using v1** — no schema changes yet, just fit-testing.
6. **Record where the model breaks or becomes unnatural** for each archetype.
7. **Classify every existing v1 concept** as one of: `KEEP`, `GENERALIZE`, `MOVE TO PROFILE`, `DEPRECATE`, `REMOVE`, `MISSING`.
8. **Derive candidate universal primitives** from the classification.
9. **Design Contract Core v1.1** from those primitives.
10. **Design profiles/extensions** around the core (e.g. a `dev` profile, `research` profile) — only after the core is defensible on its own.
11. **Prototype both a developer authoring path (YAML/SDK/CLI) and a non-technical authoring path** against the same canonical contract.
12. **Validate the model against the heterogeneous archetypes again**, now with the redesigned core.
13. **Only then stabilize and implement v1.1.**

## 6. Open questions this RFC exists to answer

- Is the current permission model too tool-centric? Is a more general concept of **authority** (may recommend / may read / may modify / may approve / may execute / requires human approval) more domain-independent than today's tool-scoped permissions?
- What distinguishes a *semantic* capability ("can analyze financial data") from an *operational* one ("can call endpoint X")? Does the spec need to represent both?
- What belongs in a universal core versus a domain profile? (Domain-specific nouns like `github_repository`, `medical_record`, `invoice` are presumed **not** to belong in the core — to be confirmed by the audit.)
- Does human participation (approval, escalation, review) belong in the contract model itself, or is it purely a policy/environment concern layered on top?

## 7. Success criteria for v1.1

v1.1 is not judged only by "does JSON Schema validation pass." It should be evaluated against:

- **Domain neutrality** — can fundamentally different agents be represented without unnatural hacks?
- **Framework neutrality** — does the contract avoid coupling to one agent framework?
- **User accessibility** — can a non-programmer create/use a contract without understanding YAML?
- **Developer ergonomics** — can developers still work directly and efficiently with contracts?
- **Extensibility** — can domains add necessary semantics without bloating the core?
- **Semantic clarity** — do terms like capability, permission, authority, constraint, requirement, and guarantee have precise, non-overlapping meanings?
- **Machine readability** — can tooling reliably process the result?
- **Evolvability** — can the spec change over time without becoming unmaintainable?

## 8. Explicit anti-goals

- Do not turn v1.1 into one giant universal YAML schema.
- Do not add every domain concept directly to the core.
- Do not design only around GitHub/coding agents.
- Do not assume users understand schemas.
- Do not confuse tool access with authority.
- Do not confuse a declared capability with a verified one.
- Do not confuse contract validation with runtime enforcement or safety.
- Do not claim universal applicability before it's been tested against the archetypes above.
- Do not build profiles before the core is defensible on its own.
- Do not build any UI before the underlying contract semantics are settled.
- Do not preserve a v1 abstraction for backward-compatibility's sake alone if it's architecturally wrong.

## 9. Status of this RFC

This RFC captures the process, not the outcome. It should be marked `Accepted` once Steps 1–8 above (the audit and archetype-fit phase) are complete and their findings are recorded — at that point a follow-up RFC (`03-contract-core-v1-1.md` or similar) should propose the actual Core + Profiles schema derived from the audit.

Until then, no PR should add fields to `schemas/v1/contract.schema.json` on the basis of "v1.1 domain independence" without linking back to an audit finding in this RFC's tracking issue.
