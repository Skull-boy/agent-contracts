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
| **M1.1** | **Hash-chained registry** (`src/scyvera/chain.py`): extend every new `RegistryEntry` with `prev_hash`; add `ContractRegistry.verify_chain()` and `upgrade_chain()` migration | Every new entry carries the chain; old files upgradeable but never silently re-written; `verify_chain()` raises `RegistryError` on break | `tests/test_registry_chain.py` covering: valid chain passes, reordered/spliced file fails, `upgrade_chain()` succeeds once then is idempotent, chain failure blocks `get_at_time()` |
| **M1.2** | **Trace schema layer** (`src/scyvera/trace.py`): JSON trace record compatible with existing `AuditEntry` | Any AuditEntry round-trips losslessly to a Trace record | `tests/test_trace.py`: round-trip + malformed-trace rejection |
| **M1.3** | **Contract identity pinning** at `ContractEnforcer.load()`: enforcer computes canonical absolute path, refuses symlink escapes, cross-checks `contract_hash` against registry latest (T12/T14) | Loader raises `ContractViolationError` on symlink-escape contract; registers identity-warning when contract was never registry-registered | `tests/test_contract_identity.py`: symlink escape attempt, symlink-replacement post-load, unregistered-contract warning |
| **M1.4** | **Re-seal ritual** (`src/scyvera/reseal.py`): regeneration flow requiring re-validate → re-lint → re-register (new version) → warning-audit record | No path rebuilds an enforcer without going through `reseal()` or explicitly disabling via documented dev flag | `tests/test_reseal.py`: valid regeneration passes; skipped-registration regeneration is rejected |
| **M1.5** | **Distribution threat-model doc completeness**: `docs/threat-model-distribution.md` statuses move from *Planned* → *Enforced for M1.x scope, remaining noted* | All T11–T14 statuses reflect reality after Phase 1 | Manual doc review |

**Gate:** Phase 1 DoD = "a Scyvera consumer can prove (a) which contract governed a given node historically via a verifiable chain, (b) that the loaded contract matched the registered intent, and (c) that the verifying package itself is intact → verified by `scyvera verify-chain` and `scyvera self-check`."

---

## Phase 2A — Adoption Funnel (RFC 0004, adoption-first)

These tasks do **not** depend on M2.1–M2.3 (they share module layout and test conventions only). They ship *before* the rest of Phase 2 deliberately: `scyvera audit` is the product's front door.

| Task | Deliverable | Acceptance | Tests |
|---|---|---|---|
| **M2.0a** | **Audit scan engine** (`src/scyvera/audit.py` + `audit_rules.py`): AUxxx rule registry, per-file pure scanners, determinism, skip list, size caps, binary sniff, symlink refusal (T14-consistent) | `scyvera audit . --json` emits `report_version: 1` report; output deterministic across runs; read-only (no writes) | `tests/test_audit.py`: fixture corpus in `tests/fixtures/audit/`, determinism byte-identical re-run, no-write guarantee, cross-platform `.ps1`/`.sh` severity |
| **M2.0b** | **Blast Radius Report rendering**: terminal format (band-first), `--badge` shields.io snippet, `--fail-under <score>` CI gate exit code | Badge emits band only (score-free, per RFC 0004 §4); `--fail-under` honored | `tests/test_audit_report.py`: render determinism, badge content, exit-code gating |
| **M2.0c** | **Auto-contract draft** (`--generate <contract.yaml>`): findings-derived v1.1 draft (resources/permissions/side_effects/approvals), `--force` overwrite guard | Every generated draft PASSes `validate_contract` + `lint_contract` with zero warnings; `system.name` from repo dir; no overwrite without `--force` | `tests/test_audit_generate.py`: schema-accuracy dogfood sweep over full fixture corpus |
| **M2.7** | **Policy Packs MVP**: `packs/<name>.yaml` with 6 golden packs (`dev-agent`, `github-safe`, `finance-ops`, `research-assistant`, `email-triage`, `devops-safe`), `--pack <name>` merge semantics, packaged in wheel | Every pack passes Tier 0 + lint in CI (`tests/test_packs.py` sweep); pack wins on conflict with heuristic-derived entries; local-only (no network fetch in v1) | `tests/test_packs.py` |

**Gate:** Phase 2A DoD = "a user with zero contract knowledge runs `scyvera audit .` in their repo, gets a shareable Blast Radius report and a schema-valid contract draft in two minutes." Dogfood requirement: `scyvera audit .` on this repo reports band `Shielded` in CI.

---

## Phase 2 — Conformance & Evals (RFC 0003 §C3, §C4)

| Task | Deliverable | Acceptance | Tests |
|---|---|---|---|
| **M2.1** | **CLI contract-check entrypoint** (`scyvera check`, `--tier {0,1,2,auto}`) — `scyvera/conformance.py` + CLI plumbing | Tier 0 report is a superset of `validate` + `lint`; tier auto-degrades with explicit notice, never silently | `tests/test_conformance_cli.py`: tier 0 PASS/FAIL on existing fixtures in `tests/fixtures/` |
| **M2.2** | **Tier 1 adapter interface** (`src/scyvera/conformance.py` static-analysis base + first `implementations/n8n/tier1.py` adapter over the 4 n8n reference workflows) | Undeclared external API hits reported as findings; adapters same API structure (`scan(node) → findings`) | `tests/test_tier1_n8n.py`: expected findings set per reference workflow |
| **M2.3** | **LangGraph Tier 1 adapter** (`implementations/langgraph/tier1.py`) on top of the existing reference impl | Same finding taxonomy as n8n adapter | `tests/test_tier1_langgraph.py` |
| **M2.4** | **Trace-driven eval harness** (`src/scyvera/evals/`, optional install): eval case ingestion, scenario execution against a Python-based reference agent, trace scoring on the 4 axes (constraints, approval, recovery, replay) | For each shipped eval fixture in `implementations/*\/evals/*.yaml`, harness produces a stable score; same fixture score across two runs (deterministic) | `tests/test_evals.py`: deterministic scoring, rejection of malformed eval cases |
| **M2.5** | **Report format unification**: single JSON report schema shared by Tier 0/1/2 and evals, renderable in CI (terminal pretty output) | All four modes emit the same top-level shape | `tests/test_report_shape.py` schema-conformance on fixtures |
| **M2.6** | **Guardrail DSL v1.2 schema slice** (`schemas/v1.2/contract.schema.json`, additive-only: optional `guardrails` object with `fail_closed`, `budgets`, `rate_limit`) | Old v1/v1.1 contracts validate identically; new v1.2 schema is a strict superset for backward compatibility | `tests/test_guardrails_schema.py`: all existing fixtures still PASS under v1.2; malformed guardrails section rejected |

**Gate:** Phase 2 DoD = "a third-party agent implementation in n8n, LangGraph, or harness form can be conformance-checked end-to-end (Tier 0 or 1) with a single CLI command and a report an auditor can read."

---

## Phase 3 — Distribution (RFC 0003 §C6)

| Task | Deliverable | Acceptance | Tests |
|---|---|---|---|
| **M3.1** | **`scyvera-harness` skill** — `SKILL.md` in `.agents/skills/scyvera-harness/` + hash committed to `skills-lock.json`; ships with the skill's own `contract.yaml` (reflexive conformance, per RFC 0003 §5.4) | Skill teaches: init→contract, check before consequential actions, re-seal ritual enforcement; its own contract validates at Tier 0 | `tests/test_skill_contract.py`: bundled `contract.yaml` PASS at Tier 0; hash in lockfile matches file |
| **M3.2** | **Multi-runtime skill/extension packaging** — generate per-runtime snippets (OpenCode skill variant, Claude Code compatible, Gemini extension JSON, Codex plugin manifest) via `scyvera package --target {opencode,claude,gemini,codex}` | Each emitted artifact validates against its host-platform manifest requirements; each artifact carries hash + attestation pointer | `tests/test_packaging.py`: target-specific outputs conform to platform schemas shipped as fixtures |
| **M3.3** | **Sigstore + SBOM CI** — `.github/workflows/release-attest.yml` signs the wheel and emits SBOM + a signed release manifest binding `{wheel_hash, schema_version, adapter_floors, self_check_manifest}` | Workflow runs on tag push; artifacts appear on release page with attestation attachment | CI run on a test tag (dry-run workflow verified in a branch) |
| **M3.4** | **`scyvera self-check`** CLI command verifying installed package against signed manifest (continues M1.5? no — this command ships here in the SPI after M3.3, since it consumes the manifest format M3.3 defines) | Verifies integrity of critical runtime files; fails closed if manifest missing/unverifiable | `tests/test_self_check.py`: tamper the test package copy → check fails; fresh copy → passes |
| **M3.5** | **Documentation surface upgrade** — README + `docs/spec/` + `docs/architecture.md` cover the new distribution layer; each phase's docs inline-linked from this roadmap | No doc drift between RFC 0003, this roadmap, and reality | Manual review + link check |

**Gate:** Phase 3 DoD = "a user on Claude, Gemini, Codex, or OpenCode can install Scyvera as a first-class skill/plugin, verify its integrity, and run a conformance check end-to-end without touching the Python API."

---

## Growth & Community Lane (cross-phase, RFC 0004 + positioning)

| Task | Deliverable | Acceptance |
|---|---|---|
| **G1** | README hero rewrite ("set once, enforced everywhere, provable forever") + animated GIF of a blocked agent action + audit badge in a prominent position | Hero states positioning sentence; GIF under 2 MB |
| **G2** | Launch film via `/brag` skill: 60s loopable clip (agent tries force-push → denied → receipt URL) | Video published to brag-output/ and linked from README |
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
| **P2A** | Adoption Funnel (RFC 0004) | 0/4 | `scyvera audit` front door live |
| **Growth** | Flywheel ops (RFC 0004 + positioning) | 0/4 | Launch film + packs gallery live |
| **P1** | Core Hardening (C1, C2) | 0/5 | Provable chain, self-verifiable install, T12/T14 pinned |
| **P2** | Conformance & Evals (C3, C4) + Guardrails (C5) | 0/6 | `scyvera check` end-to-end |
| **P3** | Distribution (C6) | 0/5 | Skill/plugin installable + attested |
| **P4** | Post-release enforcer upgrades (optional) | 0/3 | T1 mitigation, async approvals, A2A handshake |
