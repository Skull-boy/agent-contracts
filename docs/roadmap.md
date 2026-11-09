# Scyvera Implementation Roadmap (v1.2 → v1.4)

This is the **single source of truth** for what to build next, in what order, and how each step is verified. It operationalizes [RFC 0003](../rfcs/0003-harness-distribution-eval-and-integrity.md) into concrete, non-overlapping tasks. Nothing here is speculative: every task has a defined deliverable, acceptance criteria, and tests. Do not skip or reorder tasks without updating this file — tasks are sequenced so that each one is buildable using only what was merged before it.

---

## 0. How to Use This Roadmap

- **Task IDs** follow `M\<phase\>.\<n\>` (e.g. `M1.3`). Statuses update here in `<status>` blocks: `[planned] → [in-progress] → [done] → [blocked-if X]`.
- **Definition of Done (DoD)** for any task means: reference docs/spec consistent with this file, implementation with tests, exceptions follow the existing hierarchy in `src/scyvera/exceptions.py`, and `pytest tests/` passes with no new failures.
- **Never change existing public API** in this program. Additive changes only (matches the backward-compatibility convention used since v0.3). New names go in `__init__.py` with `__all__` updated.
- **All new code lives in a dedicated module** (e.g., `src/scyvera/chain.py`, `trace.py`, `conformance.py`). Do not grow `enforcer.py` / `registry.py` with new responsibilities.

### Glossary (definitions locked for this program)

| Term | Definition |
|---|---|
| **Harness** | An agent framework/runtime that drives LLM-based tool-orchestration (Claude Code, Codex, Gemini CLI, OpenCode). |
| **Artifact** | Any distributed file for users: wheel, `SKILL.md` skill, Gemini config snippet, SBOM, attestation file. |
| **Attestation** | A signed record binding artifact hashes + schema version + release metadata, produced in CI. |
| **Hash chain** | Serialized sequence where each entry stores `SHA-256(previous entry)`; breaks on any rewrite (T13). |
| **Conformance Tier 0/1/2** | Three levels of "does implementation X conform to contract Y" (structural / static / runtime-trace) — see RFC 0003 §C3. |
| **Trace** | Flat JSON log entry emitted when any action occurs: `{node_id, action_name, action_type, declared, result, contract_hash, timestamp}` — see RFC 0003 §C4. |
| **Eval case** | `(scenario, expected_trace, score_weights)` fixture under `implementations/<framework>/evals/`. |
| **Re-seal ritual** | T12-mandatory flow any contract regeneration must follow before being enforcer-loadable again. |
| **Fail-closed** | On error, deny action (vs fail-open). Existing default for gating; see RFC 0003 §C5. |

---

## Phase 0 — Release Hygiene (1 session, ~small effort)

| Task | Deliverable | Acceptance | Tests |
|---|---|---|---|
| **M0.1** | Update `CHANGELOG.md` "Unreleased" → promoted to `1.2.0` in `pyproject.toml` | CHANGELOG and pyproject agree | `pytest tests/` passes; build succeeds — **done 2026-10-31 (release v1.2.0)** |
| **M0.2** | Regenerate docs table in README (`docs/` tree, `examples/v1.1/` list, `patterns/`) | README matches reality, all links resolve | manual check — **done 2026-10-31** |
| **M0.3** | Rename the repository architecture doc to `docs/architecture.md` (was a misspelled filename referenced from README and `implementations/rfcs/01`) | Zero stale references to the old filename remain | `grep -r` for the old name returns nothing — **done 2026-10-31** |

**Gate:** after this phase, tag `v1.2.0` is unblocked; Phases 1–3 build on it.

---

## Phase 1 — Core Hardening (RFC 0003 §C1, §C2; T11–T14)

| Task | Deliverable | Acceptance | Tests |
|---|---|---|---|
| **M1.1** | **Hash-chained registry** (`src/scyvera/chain.py`): extend every new `RegistryEntry` with `prev_hash`; add `ContractRegistry.verify_chain()` and `upgrade_chain()` migration | Every new entry carries the chain; old files upgradeable but never silently re-written; `verify_chain()` raises `RegistryError` on break | `tests/test_registry_chain.py` covering: valid chain passes, reordered/spliced file fails, `upgrade_chain()` succeeds once then is idempotent, chain failure blocks `get_at_time()`<br>M1.1 shipped on `feat/hash-chained-registry`: `chain.py` provides `GENESIS_HASH`, `canonical_entry_bytes`, `next_prev_hash`, `ChainInterval`, `compute_chain_intervals`, and `verify_chain_entries`; `RegistryEntry.prev_hash` chains every new entry, chained files verify eagerly at load (mixed formats and breaks raise `RegistryError`), legacy files stay readable but refuse `register()` until the explicit `upgrade_chain()` writes a `<registry>.prechain` snapshot, logs a warning, and backfills the full history. `verify_chain()`, `get_at_time()`, and `get_history()` fail closed on tamper. **done (pending merge).** |
| **M1.2** | **Trace schema layer** (`src/scyvera/trace.py`): JSON trace record compatible with existing `AuditEntry` | Any AuditEntry round-trips losslessly to a Trace record | `tests/test_trace.py`: round-trip + malformed-trace rejection <br>M1.2 shipped on `feat/trace-schema-eval-harness`: `src/scyvera/trace.py` defines the RFC 0003 C4 `TraceEntry` (`node_id`, `action_name`, `action_type`, `declared`, `result` = allowed/pending_approval/violation, `hash_of_contract`, `timestamp`, plus `reason` and `contract_field_reference`) with lossless `trace_from_audit()` / `audit_from_trace()` conversions and a frozen `TraceLog` whose canonical JSONL rejects malformed lines with line numbers. `declared` is derived from default-deny reasons; the module is pure (no I/O, printing, or wall clock). **done (pending merge).** |
| **M1.3** | **Contract identity pinning** at `ContractEnforcer.load()`: enforcer computes canonical absolute path, refuses symlink escapes, cross-checks `contract_hash` against registry latest (T12/T14) | Loader raises `ContractViolationError` on symlink-escape contract; registers identity-warning when contract was never registry-registered | `tests/test_contract_identity.py`: symlink escape attempt, symlink-replacement post-load, unregistered-contract warning<br>M1.3 shipped on `feat/identity-pinning-reseal`: `ContractIdentity` pins `canonical_path` + load-time SHA-256 + `resolved_symlink`; `load()` refuses symlink escapes with `ContractViolationError` before reading content; the optional `registry=` cross-check records `matches-registry` / `stale-registry` / `unregistered` / `divergent-registry` receipts (warnings logged and typed); `verify_integrity()` detects a post-load symlink swap. **done (pending merge).** |
| **M1.4** | **Re-seal ritual** (`src/scyvera/reseal.py`): regeneration flow requiring re-validate → re-lint → re-register (new version) → warning-audit record | No path rebuilds an enforcer without going through `reseal()` or explicitly disabling via documented dev flag | `tests/test_reseal.py`: valid regeneration passes; skipped-registration regeneration is rejected<br>M1.4 shipped on `feat/identity-pinning-reseal`: `reseal()` runs validate → lint with zero errors → chain-verified register → frozen, timestamp-free `ResealRecord` → fresh enforcer; identical content reuses the entry, changed content produces version N+1, and skipped/partial registration raises `ResealError`; `allow_unsealed_reseal=True` (default `False`) is the documented dev/test escape hatch. **done (pending merge).** |
| **M1.5** | **Distribution threat-model doc completeness**: `docs/threat-model-distribution.md` statuses move from *Planned* → *Enforced for M1.x scope, remaining noted* | All T11–T14 statuses reflect reality after Phase 1 | Manual doc review |

**Gate:** Phase 1 DoD = "a Scyvera consumer can prove (a) which contract governed a given node historically via a verifiable chain, (b) that the loaded contract matched the registered intent, and (c) that the verifying package itself is intact → verified by `scyvera verify-chain` and `scyvera self-check`."

---

## Phase 2A — Adoption Funnel (RFC 0004, adoption-first)

These tasks do **not** depend on M2.1–M2.3 (they share module layout and test conventions only). They ship *before* the rest of Phase 2 deliberately: `scyvera audit` is the product's front door.

| Task | Deliverable | Acceptance | Tests |
|---|---|---|---|
| **M2.0a** | **Audit scan engine** (`src/scyvera/audit.py` + `audit_rules.py`): AUxxx rule registry, per-file pure scanners, determinism, skip list, size caps, binary sniff, symlink refusal (T14-consistent) | `scyvera audit . --json` emits `report_version: 1` report; output deterministic across runs; read-only (no writes) | `tests/test_audit.py`: fixture corpus in `tests/fixtures/audit/`, determinism byte-identical re-run, no-write guarantee, cross-platform `.ps1`/`.sh` severity<br>M2.0a.1 scoring refinement: per-rule diminishing loads + fixture quarantine; dogfood test `test_audit_dogfood.py` enforces Shielded<br>**done 2026-11-01 (PRs #43, #44)**. |
| **M2.0b** | **Blast Radius Report rendering**: terminal format (band-first), `--badge` shields.io snippet, `--fail-under <score>` CI gate exit code | Badge emits band only (score-free, per RFC 0004 §4); `--fail-under` honored | `tests/test_audit_report.py`: render determinism, badge content, exit-code gating<br>M2.0b shipped on `feat/scyvera-report`: band-first terminal report in `report.py`, band-only `--badge`, validated `--fail-under` gate with clean one-line errors, and narrow-codepage fallback. **done 2026-11-01 (PR #45)**. |
| **M2.0c** | **Auto-contract draft** (`--generate <contract.yaml>`): findings-derived v1.1 draft (resources/permissions/side_effects/approvals), `--force` overwrite guard | Every generated draft PASSes `validate_contract` + `lint_contract` with zero warnings; `system.name` from repo dir; no overwrite without `--force` | `tests/test_audit_generate.py`: schema-accuracy dogfood sweep over full fixture corpus<br>M2.0c shipped on `feat/scyvera-generate`: `src/scyvera/generate.py` builds deterministic schema-valid drafts from scored findings, `--generate`/`--force`/`--pack` wired into the audit CLI, one additive JSON `draft_path` key, and a fixture-corpus sweep that pins zero lint warnings. **done 2026-11-02 (PR #46)**. |
| **M2.7** | **Policy Packs MVP**: `packs/<name>.yaml` with 6 golden packs (`dev-agent`, `github-safe`, `finance-ops`, `research-assistant`, `email-triage`, `devops-safe`), `--pack <name>` merge semantics, packaged in wheel | Every pack passes Tier 0 + lint in CI (`tests/test_packs.py` sweep); pack wins on conflict with heuristic-derived entries; local-only (no network fetch in v1) | `tests/test_packs.py`<br>M2.7 shipped on `feat/scyvera-packs`: `src/scyvera/packs.py` validates local packs, `--pack <name>` merges pack facts into `--generate` drafts (pack wins, finding-only extras appended), six golden packs ship in `packs/` and as wheel package data, and a pack × fixture-corpus sweep pins schema validity plus zero lint warnings. **done 2026-11-04 (PR #50)**. |

**Gate:** Phase 2A DoD = "a user with zero contract knowledge runs `scyvera audit .` in their repo, gets a shareable Blast Radius report and a schema-valid contract draft in two minutes." Dogfood requirement: `scyvera audit .` on this repo reports band `Shielded` in CI. **Gate met 2026-11-05: all of Phase 2A ships in [v1.3.0](https://github.com/Skull-boy/agent-contracts/releases/tag/v1.3.0) (PyPI: `scyvera` 1.3.0), with the 92/100 `Shielded` dogfood enforced in CI.**

---

## Phase 2 — Conformance & Evals (RFC 0003 §C3, §C4)

| Task | Deliverable | Acceptance | Tests |
|---|---|---|---|
| **M2.1** | **CLI contract-check entrypoint** (`scyvera check`, `--tier {0,1,2,auto}`) — `scyvera/conformance.py` + CLI plumbing | Tier 0 report is a superset of `validate` + `lint`; tier auto-degrades with explicit notice, never silently | `tests/test_conformance_cli.py`: tier 0 PASS/FAIL on existing fixtures in `tests/fixtures/`<br>M2.1 shipped on `feat/scyvera-conformance-check`: `src/scyvera/conformance.py` (pure engine: `check_contract`, `resolve_tier`, `render_check`, `CheckReport`, `CheckTier`, `TierNotImplementedError`), `scyvera check --tier {0,1,2,auto}` wired into the CLI (0/1/2 exit-code convention; explicit tiers 1/2 fail loudly with exit 2 until M2.2–M2.4), and the superset property pinned by tests. **done (pending merge).** |
| **M2.2** | **Tier 1 adapter interface** (`src/scyvera/conformance.py` static-analysis base + first `implementations/n8n/tier1.py` adapter over the 4 n8n reference workflows) | Undeclared external API hits reported as findings; adapters same API structure (`scan(node) → findings`) | `tests/test_tier1_n8n.py`: expected findings set per reference workflow<br>M2.2 shipped on `feat/n8n-tier1-adapter`: `src/scyvera/conformance.py` adds `Tier1Finding` / `Tier1Adapter` (fail-closed `scan`) and an additive `CheckReport.tier1_findings`; `implementations/n8n/tier1.py` scans all four reference workflows and reports T101 undeclared actions, T102 ungated writes, and T103 unused declarations; `scyvera check <dir> --tier 1` dispatches by target and keeps the 0/1/2 exit-code convention. **shipped on branch, pending merge.** |
| **M2.3** | **LangGraph Tier 1 adapter** (`implementations/langgraph/tier1.py`) on top of the existing reference impl | Same finding taxonomy as n8n adapter | `tests/test_tier1_langgraph.py`<br>M2.3 shipped on `feat/langgraph-tier1-adapter`: `implementations/langgraph/tier1.py` uses `ast` over every `.py` file in the target (package plus top-level scripts), maps gateway calls / direct HTTP clients / known SDK constructors to service tokens, extracts graph nodes, edges, and gates for `T102` reachability, and never imports or executes the target. The reference `duplicate-issue-detector` reports no `T101`/`T102` and six `T103` warnings; `scyvera check <dir> --tier 1` claims LangGraph targets by `contract.yaml` `framework: langgraph` or a parent-chain adapter, with the n8n branch unchanged. **done (pending merge).** |
| **M2.4** | **Trace-driven eval harness** (`src/scyvera/evals/`, optional install): eval case ingestion, scenario execution against a Python-based reference agent, trace scoring on the 4 axes (constraints, approval, recovery, replay) | For each shipped eval fixture in `implementations/*\/evals/*.yaml`, harness produces a stable score; same fixture score across two runs (deterministic) | `tests/test_evals.py`: deterministic scoring, rejection of malformed eval cases <br>M2.4 shipped on `feat/trace-schema-eval-harness`: `src/scyvera/evals/` loads fail-closed YAML eval cases (`{version, name, contract, agent, scenario, expected_trace, score_weights}`), runs a factory-built reference agent against a real `ContractEnforcer`, converts its audit log through the C4 trace, and scores constraints, approval, recovery, and replay with `EvalResult` (frozen, deterministic, timestamp-normalized). The shipped `implementations/langgraph/duplicate-issue-detector/evals/refund-agent.eval.yaml` exercises all four axes and pins 75.0 (the deliberate undeclared attempt is a constraint failure); `tests/test_evals.py` covers the golden score, independent axis failures, malformed cases, and JSONL round-trips. **done (pending merge).** |
| **M2.5** | **Report format unification**: single JSON report schema shared by Tier 0/1/2 and evals, renderable in CI (terminal pretty output) | All four modes emit the same top-level shape | `tests/test_report_shape.py` schema-conformance on fixtures <br>M2.5 shipped on `feat/unified-report`: the additive `src/scyvera/unified.py` envelope (`report_version`, `tool`, `mode`, `status`, `subject`, `summary`, `findings`, `data`) is emitted by `scyvera audit --unified`, `scyvera check --unified`, and `scyvera eval --json`, backed by `from_audit_report()` / `from_check_report()` / `from_eval_result()` and `schemas/report/v1/unified-report.schema.json`. Producer bytes stay pinned: `audit --json`, `render_check()`, and `EvalResult.to_json()` are unchanged, so "all four modes emit the same top-level shape" holds through the additive envelope rather than a rewrite of audit's published JSON. **done (pending merge).** |
| **M2.6** | **Guardrail DSL v1.2 schema slice** (`schemas/v1.2/contract.schema.json`, additive-only: optional `guardrails` object with `fail_closed`, `budgets`, `rate_limit`) | Old v1/v1.1 contracts validate identically; new v1.2 schema is a strict superset for backward compatibility | `tests/test_guardrails_schema.py`: all existing fixtures still PASS under v1.2; malformed guardrails section rejected <br>M2.6 shipped on `feat/guardrail-dsl-v1.2`: the v1.2 schema is a strict superset of v1.1 (version discriminator plus optional `guardrails`: `fail_closed`, `budgets.side_effects_per_window` + `window`, `rate_limit.max_calls_per_minute`, with `additionalProperties: false` inside each block); `ContractVersion.V1_2` and `SCHEMA_V1_2_PATH` wire validation, `apply_lifecycle_defaults()` treats v1.2 like v1.1, and AC701 warns when a v1/v1.1 contract carries guardrails that its version ignores. `ContractEnforcer` parses the block into frozen records and enforces rate limits over every gated attempt and side-effect budgets over admitted `side_effect` calls inside `_check_gate()`, denying with `GuardrailViolationError` and auditing `guardrails.rate_limit` / `guardrails.budgets`; `fail_closed` denies on evaluation failure, and an additive `clock=` makes window expiry testable without sleeps. **done (pending merge).** |

**Gate:** Phase 2 DoD = "a third-party agent implementation in n8n, LangGraph, or harness form can be conformance-checked end-to-end (Tier 0 or 1) with a single CLI command and a report an auditor can read."

---

## Phase 3 — Distribution (RFC 0003 §C6)

| Task | Deliverable | Acceptance | Tests |
|---|---|---|---|
| **M3.1** | **`scyvera-harness` skill** — `SKILL.md` in `.agents/skills/scyvera-harness/` + hash committed to `skills-lock.json`; ships with the skill's own `contract.yaml` (reflexive conformance, per RFC 0003 §5.4) | Skill teaches: init→contract, check before consequential actions, re-seal ritual enforcement; its own contract validates at Tier 0 | `tests/test_skill_contract.py`: bundled `contract.yaml` PASS at Tier 0; hash in lockfile matches file |
| **M3.2** | **Multi-runtime skill/extension packaging** — generate per-runtime snippets (OpenCode skill variant, Claude Code compatible, Gemini extension JSON, Codex plugin manifest) via `scyvera package --target {opencode,claude,gemini,codex}` | Each emitted artifact validates against its host-platform manifest requirements; each artifact carries hash + attestation pointer | `tests/test_packaging.py`: target-specific outputs conform to platform schemas shipped as fixtures |
| **M3.3** | **Sigstore + SBOM CI** — `.github/workflows/release-attest.yml` signs the wheel and emits SBOM + a signed release manifest binding `{wheel_hash, schema_version, adapter_floors, self_check_manifest}` | Workflow runs on tag push; artifacts appear on release page with attestation attachment | CI run on a test tag (dry-run workflow verified in a branch) <br>M3.3 shipped on `feat/attestation-selfcheck`: `.github/workflows/release-attest.yml` downloads the completed Publish-to-PyPI run's `dist` artifact and attests those exact bytes (never a rebuild), regenerates the self manifest from the installed wheel, gates on `scyvera self-check`, and uploads the wheel + CycloneDX 1.5 SBOM + signed `release-manifest.json` (`{wheel_hash, schema_version: "1.1", adapter_floors: {n8n: "1.0", langgraph: "1.0"}, self_check_manifest}`) to the tag's GitHub Release; `workflow_dispatch` is the branch dry run. **done (pending merge).** |
| **M3.4** | **`scyvera self-check`** CLI command verifying installed package against signed manifest (continues M1.5? no — this command ships here in the SPI after M3.3, since it consumes the manifest format M3.3 defines) | Verifies integrity of critical runtime files; fails closed if manifest missing/unverifiable | `tests/test_self_check.py`: tamper the test package copy → check fails; fresh copy → passes <br>M3.4 shipped on `feat/attestation-selfcheck`: `src/scyvera/selfcheck.py` generates a deterministic, timestamp-free manifest and `scyvera self-check [--json]` verifies the installed distribution via `importlib.resources` (never the CWD), failing closed on modified/missing/unlisted files and on a missing or unsupported manifest; exit codes are `0` clean, `1` deviation, `2` unverifiable (missing manifest is `2`). `_self_manifest.json` ships as package data. **done (pending merge).** |
| **M3.5** | **Documentation surface upgrade** — README + `docs/spec/` + `docs/architecture.md` cover the new distribution layer; each phase's docs inline-linked from this roadmap | No doc drift between RFC 0003, this roadmap, and reality | Manual review + link check |

**Gate:** Phase 3 DoD = "a user on Claude, Gemini, Codex, or OpenCode can install Scyvera as a first-class skill/plugin, verify its integrity, and run a conformance check end-to-end without touching the Python API."

---

## Production-Defensibility Program (cross-phase, the v1.4 gate)

**Goal:** the milestone where third parties are told *"use Scyvera in your main production
projects"* and every word of that claim is machine-checkable. Everything here is additive to the
phases above; task IDs below are new (PD-prefix) and never collide with `M`-tasks.

### The v1.4 production gate (verbatim DoD)

A team can:
1. **Install verifiably** — a release published with Sigstore signature + SBOM + provenance
   (M3.3), self-verifiable in place via `scyvera self-check` (M3.4), failing closed on mismatch.
2. **Prove history** — `registry.jsonl` is hash-chained so any rewrite is detectable (M1.1);
   contract loads refuse symlink escapes and unregistered re-seal paths (M1.3/M1.4).
3. **Gate their CI** — one line in the Actions workflow via the official `scyvera-audit-action`
   (PD-6), plus `scyvera check --fail-under` locally.
4. **Bound behavior** — contracts can carry optional guardrails (M2.6) and measured runs are
   scoreable (M2.4/M2.5).
5. **Reach every runtime** — harness skill + per-target packaging (M3.1/M3.2) and an MCP server
   mode so MCP-native agents call `scyvera` as a tool (PD-7).

Until all five hold, the README's positioning stays "beta-serious", not "production". This gate
is deliberately explicit so the marketing language can never outrun the merged code.

### Sequencing (explicit, ordered — overrides nothing, records the order)

```
1. M2.3 LangGraph Tier-1 adapter            (in flight; adoption depth)
2. PD-1..PD-4  trust-surface basics         (docs + CI hygiene; cheap, immediate)
3. M1.1-M1.4  registry integrity cluster    (hash chain, pinning, re-seal — the receipts)
4. M3.3/M3.4  signing + self-check          (make PyPI artifacts self-verifiable)
5. M2.6       guardrails                    (behavioral bounds production teams ask for)
6. M2.4/M2.5  eval harness + unified report (measured conformance)
7. M3.1/M3.2/PD-6/PD-7  distribution reach (skill, packaging, Action, MCP mode)
8. PD-8       optional Rust scanner         (only behind differential-output tests)
```

### New tasks (PD rows)

| Task | Deliverable | Acceptance |
|---|---|---|
| **PD-1** | `SECURITY.md` + supported-versions table + coordinated-disclosure route | SECURITY.md present, links from README; report/disclosure path unambiguous |
| **PD-2** | CI hardening: all workflow actions pinned by commit SHA, least-privilege `permissions:` on every workflow | Zero floating `@latest`/`@vX` action refs; per- workflow minimal token permissions |
| **PD-3** | Cross-platform test matrix: 3.10–3.14 × linux/windows/macOS | All matrix combinations green on PRs to main |
| **PD-4** | Deserialization pin: tests assert only `yaml.safe_load`/`yaml.safe_load_file` paths exist | no `yaml.load` without explicit unsafe refactor; enforced by test |
| **PD-5** | Published perf benchmark (synthetic 10k-file repo) | benchmark script + recorded numbers in docs; pre-answers big-repo claims |
| **PD-6** | Official `scyvera-audit-action` GitHub Action (installs scyvera, runs `audit --fail-under`, respects `--badge`) | Sample consuming repo; action pinned, tagged v1 <br>PD-6 shipped in 1.4.0: `.github/actions/scyvera-gate/action.yml` installs `scyvera>=1.3,<2` (accepts 1.4.0), runs audit/conformance modes, honors `--fail-under` and `--badge`, and is dogfooded on push/pull request. |
| **PD-7** | `scyvera mcp` server mode exposing validate/audit/check as MCP tools | stdio MCP server; deterministic outputs identical to CLI; usable by MCP-native harnesses <br>PD-7 shipped in 1.4.0 on `feat/pd7-mcp-server`: `scyvera serve-mcp` (the canonical name; the row's `scyvera mcp` wording is left as written) runs a stdlib-only, newline-delimited JSON-RPC 2.0 MCP server over stdio with `scyvera_audit`, `scyvera_validate`, `scyvera_check`, `scyvera_self_check`, and `scyvera_packages`; results are the existing engine payloads and diagnostics stay on stderr. |
| **PD-8** | *(Optional, deferred)* Rust scanner binary emitting byte-identical RFC 0004 reports | differential test suite: Rust output ≡ Python output across corpora; shipped as separate wheel only when scale demands |

### Mapping to existing rows

Lane A = M1.1–M1.4 + M3.3 + M3.4 (registry integrity, signing, self-check).
Lane B = M2.6 + M2.4 + M2.5 (guardrails, evals, unified reports).
Distribution reach = M3.1 + M3.2 + PD-6 + PD-7.

---

## Growth & Community Lane (cross-phase, RFC 0004 + positioning)

| Task | Deliverable | Acceptance |
|---|---|---|
| **G1** | README hero rewrite ("set once, enforced everywhere, provable forever") + animated GIF of a blocked agent action + audit badge in a prominent position | Hero states positioning sentence; GIF under 2 MB<br>G1 shipped on `docs/readme-g1`: hero rewritten around the no-contract funnel (scan → badge → gate → draft), dynamic test badge, Blast Radius badge, and the contract lane retained below. Animated GIF shipped 2026-11-03 (PR #49: `assets/scyvera-demo.gif`, 720px/14fps — 3.9 MB, deliberately above the 2 MB bar to keep motion fidelity; rendered from the 23s demo capture). **done 2026-11-03.** |
| **G2** | Launch film via `/brag` skill: 60s loopable clip (agent tries force-push → denied → receipt URL) | Film rendered 2026-11-05 via `/brag`: 23.0s, 1920x1080/30fps, five scenes (blocked delete → reveal → audit → contract draft → install), poster frame baked in at t=0 (`brag.jpg`) and share copy in `share-copy.txt`, all under `brag-output-2026-11-02-231336/` (scratch; uncommitted). Scope landed at 23s rather than 60s loopable; publication (README link vs. release asset) pending a hosting decision. **in-progress.** |
| **G3** | Showcase gallery + "contract/pack of the month" curation ritual (docs/community/SHOWCASE.md) | Gallery seeded with the 6 golden packs and 3 cross-domain examples |
| **G4** | Contributor ladder docs: "add a policy pack" as the recommended first PR path in CONTRIBUTING.md | CONTRIBUTING includes pack template + CI expectations |

---

## Phase 4 - Revisiting the Enforcer for Harness-Native Agents (post-Phases 1-3, optional)

| Task | Deliverable | Acceptance |
|---|---|---|
| **M4.1** | **Sliding-window invocation throttling** (from `threat-model-lifecycle.md` T1 and RFC 0002) — real burst detection inside `ContractEnforcer` for `lifecycle.busy`/downgrade attacks | Upgrade from warning to detectable ContractViolationError with preserved audit trail |
| **M4.2** | **Asynchronous approval channels** — pluggable `ApprovalChannel` interface (Telegram, Slack, Email, Webhook), implementing the existing `ApprovalPendingError` handling path | Current synchronous behavior remains the default; async channels opt-in |
| **M4.3** | **Multi-agent contract negotiation** — handshake protocol verifying contracts during agent-to-agent delegation (links to future `agent_to_agent` lifecycle field, pre-declared in RFC 0002 §4) | Handshake makes delegation fail-closed when the receiving agent's contract doesn't authorize the delegator's request |

---

## Progress Tracking

| Phase | Scope | Tasks Complete | DoD Summary |
|---|---|---|---|
| **P0** | Release Hygiene | 3/3 | v1.2.0 released |
| **P2A** | Adoption Funnel (RFC 0004) | 4/4 | `scyvera audit` front door live — shipped in v1.3.0 (2026-11-05) |
| **Growth** | Flywheel ops (RFC 0004 + positioning) | 1/4 (G2 film rendered, publication pending) | G1 done; launch film rendered (`/brag`, 2026-11-05) |
| **P1** | Core Hardening (C1, C2) | 0/5 | Provable chain, self-verifiable install, T12/T14 pinned |
| **P2** | Conformance & Evals (C3, C4) + Guardrails (C5) | 0/6 | `scyvera check` end-to-end |
| **P3** | Distribution (C6) | 0/5 | Skill/plugin installable + attested |
| **P4** | Post-release enforcer upgrades (optional) | 0/3 | T1 mitigation, async approvals, A2A handshake |
| **v1.4 gate** | Production-Defensibility Program (PD rows, cross-phase) | 6/8 PD rows shipped | Signed install + self-check + CI Action + MCP mode + hash-chained receipts; PD-5 benchmark open, PD-8 deferred |
| **v1.4.0** | Release 1.4.0 (2026-11-09) | shipped | Full platform on PyPI; remaining distribution reach: `scyvera-harness` skill (M3.1) and per-target packaging (M3.2) |

---

## Stranger-test hardening (R1)

R1 closes the false-PASS shapes found by cold-running `scyvera audit` on
realistic repositories. It is additive to the phases above.

| Item | Shipped behavior | Evidence |
|---|---|---|
| Combined imports | AU-NET-002 parses `import a, b` as a comma-separated list, so `import os, requests` and `import requests, os` both match; the existing `fetch(` probe is unchanged. | `tests/test_audit_stranger.py::test_combined_import_matches_regardless_of_position` |
| Agent/ML identity | AU-NET-002 recognizes `openai`, `anthropic`, `google.genai`, `cohere`, `botocore`, `boto3`, `huggingface_hub`, `wandb`, and `replicate`, names the detected library, and suggests the `permissions: network:egress:<host>` field. | `test_agent_library_is_named_in_the_finding`, `test_google_genai_is_detected_without_flagging_google_root` |
| Source credentials | New AU-SECRET-001 (high) finds hardcoded credential-like literals in source files across assignment styles, redacts the value, and suggests moving it to an environment variable. The value floor is shared with AU-ENV-002 (>=16 chars, no whitespace, entropy >=3.0, placeholder allowlist); fixtures stay quarantined and unscored. | `test_hardcoded_credentials_are_found_in_four_languages`, `test_secret_allowlist_and_value_floor` |
| Governance status | `governance_status(payload)` / `governance_report(payload)` perform a bounded (3 directory levels), read-only, name-based search for `contract.yaml`, honoring the scan's skip dirs and symlink refusal. The human render marks `[ungoverned]` and gives one next step on PASS; `--unified` adds `summary.governance` (`status`, `contract_path`). `audit --json` is unchanged. | `test_ungoverned_render_carries_banner_and_hint`, `test_unified_summary_carries_governance_additively`, `test_audit_json_bytes_exclude_governance` |

**Dogfood:** `scyvera audit .` remains 92/100 Shielded. The only self-match
introduced by the new rules was a documentation example in `audit_rules.py`;
the wording was corrected in the repository instead of lowering rule
severity. `tests/test_gateway.py` uses a placeholder token so the repository's
own test material stays outside the source-credential rule.

**Notes:** the task named `fac9a64` as the main tip; the branch was cut from
the then-current `origin/main` at `ea4d27a` (merged PR #70), which contains
that commit. No roadmap row existed for R1, so this section is additive.

---

## Multi-language pattern pack + BOM handling (R1b)

R1b extends the audit's line-pattern coverage to the source languages that
were being scanned but matched by almost nothing, and fixes a Windows BOM
correctness hole. It stays pattern-level and review-grade; Tier 1 adapters
remain the AST-aware layer.

| Item | Shipped behavior | Evidence |
|---|---|---|
| BOM handling | The scan decodes with `utf-8-sig`, and the shared `_source_lines()` helper strips a defensive leading/trailing U+FEFF per line. A BOM-prefixed combined import or credential literal now matches exactly like the non-BOM file; UTF-16 files still skip as binary. | `tests/test_audit_stranger.py::test_bom_prefixed_combined_import_matches_au_net_002`, `test_utf16_file_is_still_skipped_as_binary` |
| Language pack | AU-NET-002 gains documented per-family tables for Go, Java/Kotlin, Rust, C/C++, C#, PHP, and JS/TS. Every finding names the detected client and maps to `permissions: network:egress:<host>`; the six-language fixture set produces exactly six findings. | `test_language_pack_produces_exactly_six_network_findings`, `test_language_pack_names_the_client` |
| Wrapper-aware shell rules | One `_shell_wrapper_payloads()` helper extracts quoted commands from `system`/`os.system`/`subprocess`/`Runtime.exec`/`ProcessBuilder`/`exec.Command`/`child_process.exec`/`Process.Start` and feeds the existing AU-NET-001, AU-SH-001, and AU-GIT-001 checks. | `test_wrapper_aware_shell_rules_reach_source_files` |
| Source credentials | AU-SECRET-001 documents and tests Go `:=`, Java `String TOKEN =`, Rust `let`, C# `var`, JS `const`, C declarations, and credential-like callee calls such as `setApiKey("...")`; the R1 length/entropy floor is unchanged. | `test_source_secret_assignments_generalize_across_languages`, `test_source_secret_flags_bare_literal_passing` |
| Honest limits | New `docs/language-coverage.md` states the exact phrase “pattern-level, review-grade coverage — not AST or conformance-grade”, lists what each family catches, and records what is not caught. README points at it. | `test_language_coverage_doc_states_the_honest_limit` |

**Dogfood:** `scyvera audit .` remains 92/100 Shielded. The new fixtures live
under `tests/fixtures/stranger/`, so they are visible but quarantined and
unscored.
