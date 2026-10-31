> [!NOTE]
> **RFC Status: Proposed**
> This RFC defines the hardening, conformance-checking, evaluation, and distribution layer to be built on top of Agent Contracts v1.1 and `scyvera` 1.1.3. It introduces **no breaking changes** to the existing public API or to the v1/v1.1 schemas. Implementation sequencing, acceptance criteria, and step-level tasks are tracked in [`docs/roadmap.md`](../docs/roadmap.md).
>
> Author: Scyvera Core Team / Agent Contracts Working Group
> Created: 2026-10-31
> Target: `scyvera` 1.2.x and above (optional schema additions in v1.2)

---

# RFC 0003: Harness Distribution, Conformance Evaluation & Integrity Layer

## 1. Problem Statement

Scyvera has reached three working governance tiers — static validation, runtime enforcement, and append-only provenance — proven against two framework implementations (n8n, LangGraph). However, at the *distribution boundary* several gaps prevent it from being adopted as a universal trust layer:

1. **The registry is append-only by policy, not by structure.** A write-capable attacker can rewrite `registry.jsonl` with fabricated-but-plausible history without ever "deleting" anything (Threat T13).
2. **The enforcer cannot prove its own credibility.** A consumer cannot verify that the installed `scyvera` runtime itself matches the released, reviewed version (T11, sub-case of T5 applied to the package rather than the contract).
3. **"Conformance" is informal.** An integrator cannot give an auditor a machine-checkable answer for "does agent X actually run inside contract Y?" across n8n, LangGraph, harness-based agents, or other frameworks.
4. **There is no eval or guardrail incentive.** Contracts exist to be *enforced*, but the framework ecosystem (Claude skills, Gemini extensions, Codex plugins, OpenCode/harness skills) contains categories of agents that cannot embed the Python enforcer — yet still need a checkable, comparable declaration of authority.
5. **Distribution artifacts lack integrity anchors.** If Scyvera ships as a skill or plugin, the skill itself must be hash-locked and attested or consumers re-inherit exactly the untrusted-artifact problem Scyvera exists to solve.

---

## 2. Proposed Design

The RFC defines six composable components. They are layered so that each builds on prior work and none requires breaking changes to the current public API.

### C1: Hash-Chained Contract Registry

Extend `ContractRegistry` so every appended `RegistryEntry` carries a `prev_hash` field — the SHA-256 of the immediately preceding serialized entry (or a fixed genesis value `"0" * 64` for the first entry).

- **Invariants**:
  - The chain is recomputable from the file alone: given a valid `registry.jsonl`, `verify_chain()` must succeed if and only if every entry in sequence has `prev_hash == SHA-256(serialized previous entry)`.
  - `verify_chain()` raises `RegistryError` (fail closed) on any break, splice, reorder, or fabricated insertion — this is the T13 mitigation.
  - `verify_chain()` is required before registry queries answer provenance questions (`get_at_time()`, `get_history()`).
- **Backward compatibility**: registry files written before C1 must be sealable via a one-time `upgrade_chain()` migration that snapshots the pre-chain state, emits a warning, then continues appending chained entries.

### C2: Package Self-Integrity (`scyvera self-check`)

Introduce a signed manifest of Scyvera's own runtime files (enforcer, validator, linter, registry, gateway modules + bundled schemas).

- The manifest lists `{path, sha256}` for each runtime-critical file.
- `scyvera self-check` verifies the installed distribution against the manifest and reports integrity failures as a fail-closed error.
- Release pipeline (C6) generates the manifest and signs it alongside the wheel; this is the T11 mitigation.
- This applies T5 (file replacement → tampering detection) from the *contract* layer to the *enforcer itself*.

### C3: Conformance Check Tiers

Formalize what it means for an implementation to conform to its contract, in three independently shippable tiers:

| Tier | Name | Input | Output | Trust |
|---|---|---|---|---|
| **0** | Structural | `contract.yaml` | PASS/FAIL vs JSON Schema + semantic lint (ACxxx) | Declaration conformance (existing `validate` + `lint`) |
| **1** | Static Declared vs Code | `contract.yaml` + implementation source (AST, workflow JSON) | List of undeclared permissions / side effects / ungated externally-hitting calls | Conformance-by-inspection |
| **2** | Runtime Trace | `contract.yaml` + execution trace (JSON log of gated calls with outcomes) | PASS/FAIL vs contract's permission + side-effect + approval model | Conformance-by-measurement |

- CLI: `scyvera check <target>` with flag `--tier {0,1,2}`. Tier 0 is a thin alias over existing `validate` + `lint`; Tiers 1 and 2 introduce new modules.
- Tier 1 adapters are per-runtime: `implementations/<framework>/tier1.py` (starting with the existing n8n `workflow.json` and LangGraph adapters).
- Tier 2 requires the trace schema (below); without a trace, Tier 2 degrades to Tier 1 with an explicit report note (never silently).

### C4: Trace Schema & Eval Harness

Introduce a first-class **execution trace** artifact so that any agent runtime (Python enforcer, n8n webhook, LangGraph run, harness skill, MCP wrapper) can emit comparable results.

- **Trace entry** (flat, JSON-serializable): `{node_id, action_name, action_type, declared, result: {allowed | pending_approval | violation}, hash_of_contract, timestamp}`.
- Compatibility: this is exactly what the current `AuditEntry` stores for Python enforcement calls; the trace schema generalizes `AuditEntry` so the *same* shape is used at all conformance tiers.
- **Eval harness** (`scyvera/evals/`, optional install): runs a target implementation against a synthetic or fixture scenario, collects a trace, scores it against the contract on four axes:
  1. Constraint satisfaction (no undeclared call or side effect)
  2. Approval-boundary respect (every irreversible action hits an approval or a registered bypass)
  3. Recovery behavior (failure paths match `recovery_strategy`)
  4. Replay safety (re-running the trace produces identical side-effect decisions)
- Eval cases are defined as `{scenario_input, expected_trace, score_weights}` fixtures under `implementations/<framework>/evals/`.

### C5: Guardrail DSL (v1.2 Optional Schema Extension)

Additive fields under a new, optional top-level `guardrails` object. All fields are optional and default-safe; the v1/v1.1 schemas are unchanged, and a loader that does not know about `guardrails` silently ignores it (additive-only principle).

```yaml
guardrails:
  fail_closed: true            # on auth/timeout/parsing failure, deny rather than permit
  budgets:
    side_effects_per_window: 10
    window: "1h"
  rate_limit:
    max_calls_per_minute: 30
```

- Enforced by `ContractEnforcer` and `BaseGateway` through the same gate layer, not through framework-specific middleware, so it is portable to all runtimes.
- Omitted `guardrails` retains today's behavior exactly (fail-open on request parsing, no budget). An explicit `guardrails` block flips the policy to fail-closed semantics.

### C6: Distribution Artifacts with Attestation

Scyvera ships as a first-class *installable trust layer* on agent-platform surfaces:

1. **`scyvera-harness` skill** — a `SKILL.md`-style skill instructing coding agents (OpenCode, Claude Code, Codex, Gemini CLI and compatible harness skills) to:
   - generate a contract for their task scope (`scyvera init`),
   - run Tier 0/1 checking before consequential actions,
   - treat their own file edits as the contract's declared surface,
   - refuse to regenerate contracts that violate T12 re-seal ritual rules.
2. **Gemini / Codex extension packaging** — JSON schemas (already portable) plus a small converter emitting per-runtime config snippets; no runtime behavior change, conformance is checkable via C3/Tier 2 for any runtime that emits the C4 trace shape.
3. **Integrity & provenance** of the artifacts themselves:
   - `skills-lock.json` continues to hash-lock every shipped skill (`computedHash` are generated in CI, not manually).
   - Releases are **signed with Sigstore** and publish an **SBOM** alongside the wheel.
   - The release manifest and attestation bundle `{wheel hash, schema version, adapter version floors, self-check manifest}` and are verifiable via C2 `scyvera self-check` / C1 registry, closing T11–T14 end to end.

---

## 3. What This Unlocks

1. **Auditable provenance trips** (C1 + C3): "was agent X's action committed while contract version Y governed it?" becomes answerable with a checkable chain.
2. **Cross-runtime conformance** (C3 + C4): any runtime that can emit a trace can be scored on the same 4-axis rubric regardless of implementation.
3. **Guardrails without framework lock-in** (C5): budget/rate/fail-closed semantics travel with the contract, not the code.
4. **Installable trust layer** (C6): the skill and plugin artifacts carry their own integrity chain (`computedHash` → sigstore → SBOM → self-check), matching how the registry already works.

---

## 4. Non-Goals

- Not an **agent runtime or orchestrator**. Scyvera still does not execute agent logic.
- Not a **new agent spec**. Contract v1.1 remains normative; C5 adds only additive optional guardrail fields.
- Not an **LLM prompt-safety layer**. T12 treats contract substitution as a state-channel problem, not a prompt-content problem.
- Not a **sandboxed/OS-level isolation** solution. The runtime is still invoked inside a host process; C2/C6 raise the cost of the package being swapped, not of the host being compromised.

---

## 5. Open Questions & Resolutions

1. **Q: Should Tier 1 static analysis attempt to detect T6 (permission string spoofing) semantically?**
   - **Resolution**: No. Tier 1 only *surfaces* undeclared code-level capability (import/AST level). T6 semantic spoofing remains a contract-author responsibility plus optional future evaluator, not a requirement for C3.
2. **Q: Should `ContractRegistry` migrate automatically to chain format on first append after upgrade, or require explicit upgrade?**
   - **Resolution**: Explicit via `upgrade_chain()` with a warning — fail-closed philosophy; never silently reformat provenance data.
3. **Q: Do all conformance tiers emit a single unified report format?**
   - **Resolution**: Yes. Tier 0/1/2 all produce the same JSON report shape for machine consumption and rendering consistency.
4. **Q: Does the `scyvera-harness` skill itself need a contract?**
   - **Resolution**: Yes, reflexively — the skill ships with a `contract.yaml` describing its own reads/writes, consumed as both its own conformance check and as a worked Tier 0 example.
