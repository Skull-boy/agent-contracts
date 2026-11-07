# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — Conformance CLI (M2.1, RFC 0003 §C3)
- **New `scyvera check <contract.yaml>` command**: runs the Tier 0 (structural) conformance check — a strict superset of `scyvera validate` + `scyvera lint` — as one report combining schema-validation errors and ACxxx semantic warnings. Exit codes follow the house convention: `0` pass (or warn-only, matching `lint`), `1` fail, `2` usage/IO error.
- **`--tier {0,1,2,auto}` with explicit degradation, never silently**: `auto` (the default) resolves to the highest implemented tier — today tier 0 — and prints a `note:` line saying so; explicitly requesting tier 1 (static) or tier 2 (runtime-trace) exits `2` with a clean one-line stderr message until the M2.2–M2.4 adapters ship.
- **New `scyvera/conformance.py` module**: `check_contract()`, `resolve_tier()`, `render_check()` plus the `CheckReport` / `CheckTier` data types and `ConformanceError` / `TierNotImplementedError`. Pure engine (no printing, no writes, no new dependencies), frozen immutable results, exported from the `scyvera` package (`__all__` updated).
- RFC delta raised, not silently changed: RFC 0003 §C3 specifies `--tier {0,1,2}` while roadmap M2.1 requires `{0,1,2,auto}`; the implementation follows the roadmap (the stricter operational spec) pending a one-line RFC amendment.

### Added — Tier 1 static adapter, n8n (M2.2, RFC 0003 §C3)
- **`Tier1Finding` and `Tier1Adapter` in `scyvera/conformance.py`**: the shared static-analysis contract — a frozen finding record (`code`, `title`, `message`, `path`, `node_id`, `severity`) and an abstract adapter whose concrete `scan(target, contract_path)` is a fail-closed template. `scan` runs `validate_contract` first and raises `Tier1ContractError` rather than comparing code to a contract the schema rejects. `CheckReport` gains an additive `tier1_findings` tuple (default `()`), so tier 0 output and call sites are unchanged.
- **First adapter, `implementations/n8n/tier1.py`**: parses `workflow.json` with the standard-library `json` parser only, recognises the reference node types (including `httpRequest`, Webhook triggers, GitHub, Telegram, Google Sheets, Discord, OpenAI, Ollama, and `executeCommand`), maps them to canonical services, and compares them with v1.0 free-text and v1.1 mapped `permissions` / `resources` / `side_effects`. Unknown externally-reaching node types produce findings instead of being skipped; disabled nodes are still inspected because one toggle re-enables the call.
- **Finding taxonomy**: `T101` undeclared action (error), `T102` ungated call (error; a write reachable from a trigger without traversing a declared approval gate), and `T103` unused declaration (warning). RFC 0003 §C3 names only undeclared findings, so `T103` is an additive symmetry extension and never fails a check on its own.
- **CLI dispatch**: `scyvera check <implementation-dir> --tier 1` discovers the adapter for the target, renders `[T101] title: message` detail lines in the house style, exits `1` on any T101 or error-severity T102, `0` for warn-only output, and `2` with a clean one-line stderr when no adapter claims the target. `--tier 2` still fails loudly with its unchanged not-implemented message.
- **Evidence**: `tests/test_tier1_n8n.py` pins the exact findings for all four committed n8n workflows (`duplicate-issue-detector` reports both undeclared Ollama endpoints; the other three are conformant), plus mutation tests for an undeclared host and a bypassed approval gate, the fail-closed contract path, and read-only/deterministic guarantees.

### Added — Tier 1 adapter, LangGraph (M2.3, RFC 0003 §C3)
- **New `implementations/langgraph/tier1.py`**: `LangGraphTier1Adapter` plus a module-level `create_adapter()` factory for the CLI loader. The target directory is the implementation surface, so every `.py` file under it is scanned, including top-level scripts such as `backfill.py`; the adapter parses source with `ast` and never imports, executes, or writes to the target package.
- **Detection**: gateway method calls (`GitHubGateway`, `QdrantGateway`, `BaseGateway`) map to service/action tokens and count as gated; direct `httpx`/`requests`/`urllib` calls derive a service from literal hosts, f-strings, `.format`, and attribute chains; known SDK constructors without a gateway (`OpenAI`, `Github`, `QdrantClient`, ...) map to their service. Unknown gateway methods, unknown hosts, and unparseable source fail closed as findings rather than being skipped.
- **Graph reachability**: `add_node`, `add_edge`, `add_conditional_edges`, and `set_entry_point` are extracted from the AST without importing LangGraph. When the contract declares an approval point, a write-capable node reachable from the graph entry without traversing a gate node is `T102`; gateway calls are exempt because the runtime gateway enforces the contract. Functions outside the graph are covered by `T101` only.
- **Contract compatibility**: v1 free-text permissions (for example `github: issues:read+write` and `qdrant: read+write on one collection`) are compared alongside v1.1 mapped entries. The reference `duplicate-issue-detector` contract produces no `T101`/`T102` and six `T103` warnings (`github.close`, `github.label`, `github.merge`, `qdrant.delete`, and its two prose side-effect sentences).
- **CLI discovery**: a target is claimed for LangGraph when its `contract.yaml` declares `framework: langgraph`, or when a Python-source target has a parent chain exposing `implementations/langgraph/tier1.py`. The n8n branch (workflow JSON, walk-up, sibling fallback) is unchanged, and an unclaimed target still exits `2` with the one-line "no tier 1 adapter" message.
- **Evidence**: `tests/test_tier1_langgraph.py` pins the exact reference findings and messages, mutation tests for an undeclared `httpx` host and an ungated write (plus a fully gated graph that suppresses `T102`), fail-closed contract and unparseable-source paths, read-only/deterministic guarantees, discovery, and the CLI 0/1/2 matrix with the n8n commands unchanged.
### Added — Trust surface (PD-1..PD-4, Production-Defensibility Program)
- **`SECURITY.md` (PD-1)**: supported-versions table (1.x supported; a commented 2.x row marks where the next major slots in), coordinated disclosure through GitHub Security Advisories with an explicit "do not open public issues" rule, an honest bus-factor-1 response target (acknowledgment within 7 days, no SLA), scope split between Scyvera's parsing/enforcement/audit code and out-of-scope user agents, n8n hosts, and reference-implementation dependencies, plus default reporter credit in the advisory. The README badge row links to it without touching the existing Blast Radius badge.
- **CI hardening (PD-2)**: every workflow action is pinned by full commit SHA with a version comment — `actions/checkout@11d5960a326750d5838078e36cf38b85af677262` (v4.4.0), `actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065` (v5.6.0), and `pypa/gh-action-pypi-publish@7245906fb61fa33a13554f9d5fb856fe61758086` (v1.14.3, `release/v1`). All three workflows now declare top-level `permissions: contents: read`; the publish job keeps its job-level `id-token: write` because the body authenticates through PyPI Trusted Publishing (OIDC), not an API token. No repository secrets were added.
- **Cross-platform test matrix (PD-3)**: `validate-contracts.yml` now runs the suite across `ubuntu-latest` / `windows-latest` / `macos-latest` × Python 3.10–3.14 with `fail-fast: false`, so one outlier reports alongside the rest. The wheel build and CLI verification stay a single `ubuntu-latest` / Python 3.12 job (`build-wheel`) to keep cost bounded; the lint-gateway job remains single-slot.
- **Deserialization pin (PD-4)**: new `tests/test_yaml_pin.py` statically walks every source file under `src/scyvera` and rejects any `yaml.load(...)` call without an explicit safe `Loader`, mutation-tests that detector with an injected unsafe call, checks the four known call sites (CLI discovery, validator, registry, packs) by source, and runtime-pins `yaml.unsafe_load` / `unsafe_load_all` / `full_load` / `full_load_all` to raise while exercising `validate_contract`, `scan_tree`, `load_pack`, registry registration, and CLI tier 1 discovery.

### Added — Hash-chained registry (M1.1, RFC 0003 §C1)
- **New `src/scyvera/chain.py`**: pure chain mechanics with no I/O or printing. `GENESIS_HASH` is the RFC value `"0" * 64`; `canonical_entry_bytes()` is the single source of truth for the persisted UTF-8 JSON (`json.dumps(..., separators=(",", ":"))`, no trailing newline); `next_prev_hash()` is SHA-256 over those bytes; `ChainInterval`, `compute_chain_intervals()`, and `verify_chain_entries()` expose the expected-versus-stored link for every position. All are exported from the `scyvera` package.
- **`RegistryEntry.prev_hash`**: every new entry carries the SHA-256 of the previous entry's canonical bytes (genesis for the first). `_append_to_file()` now persists the exact bytes `canonical_entry_bytes()` produces, so stored and hashed records cannot diverge. Files written before C1 (`prev_hash` absent/null on every line) still load and answer queries, but `register()` fails closed with a message pointing at `upgrade_chain()`.
- **`ContractRegistry.verify_chain()`**: recomputes the chain from `registry.jsonl` alone and raises `RegistryError` on a break, splice, reorder, edit, fabricated insertion, missing link, or mixed chained/legacy file. A pre-chain file never gets a passing verdict. Chained registries verify eagerly at load, and `get_at_time()` / `get_history()` re-verify before answering provenance questions.
- **`ContractRegistry.upgrade_chain()`**: the explicit, one-time migration required by RFC 0003 §C1. It writes `<registry>.prechain` beside the file, logs a warning, and deterministically backfills `prev_hash` across the full history; it returns the snapshot path and is an idempotent no-op on an already-chained registry. The docstring records the historical caveat: backfilled hashes prove integrity from the upgrade moment, not before it.
- **Evidence**: `tests/test_registry_chain.py` pins the valid chain (including genesis and reload), tamper scenarios (reorder, splice/edit, forged insertion, truncation), eager-load failures, legacy query/append behavior, one-time migration with snapshot and warning, idempotent registration, atomic append failure, and deterministic canonical bytes. The existing `tests/test_registry.py` suite stays green and unchanged.

### Added — Contract identity pinning (M1.3, T12/T14)
- **Canonical identity at load**: `ContractEnforcer.load()` resolves the requested path once to an absolute canonical path, stores it in a frozen `ContractIdentity` receipt (`canonical_path`, `load_hash`, `resolved_symlink`, `crosscheck`, `registry_entry_id`, `registry_version`, `warnings`), and exposes it via the new `contract_identity` property. `verify_integrity()` reads only that pinned path and re-resolves the requested path solely to detect a post-load symlink swap (T14); a swap raises `ContractTamperError` even when the original target is untouched.
- **Symlink refusal**: a contract whose canonical target is outside the lexical parent directory of the addressed path raises `ContractViolationError` before content is read; a same-directory symlink is allowed and recorded as `resolved_symlink=True`. `ContractViolationError` gains an additive `reason=` keyword for load-time violations without changing existing three-argument messages.
- **Registry cross-check (T12)**: new optional `registry=` / `allow_unsealed_reseal=False` keyword arguments on `load()` keep the default path byte-identical. With a registry, the receipt reports `matches-registry`, `stale-registry` (logged warning), `unregistered` (logged warning), or `divergent-registry`; genuinely changed content at an already-registered path is refused unless the documented dev flag is set, so regeneration must go through `reseal()`.
- **Path-keyed file history**: `ContractRegistry` now versions file contracts by canonical path (they have no `node_id`) and exposes `get_history_by_path()` / `get_latest_by_path()`; declaration versioning, idempotency, and chain semantics are unchanged.
- **Evidence**: `tests/test_contract_identity.py` pins symlink escape, same-directory symlinks, post-load symlink replacement, unregistered/stale/matching receipts, the frozen identity type, the unchanged default load, and the M1.4 refusal boundary. Symlink cases skip where the platform forbids symlink creation.

### Added — Re-seal ritual (M1.4, T12)
- **New `src/scyvera/reseal.py`**: `reseal(new_contract_path, registry)` runs the mandatory T12 flow — `validate_contract` → `lint_contract` with zero errors (warnings logged and recorded) → chain-verified `ContractRegistry.register()` → frozen `ResealRecord` → fresh `ContractEnforcer`. Identical content reuses the existing entry; changed content must produce version N+1. A skipped or partial registration raises `ResealError` instead of returning a governable enforcer, and an invalid contract is rejected before anything is registered.
- **Audit record**: `ResealResult` pairs the fresh enforcer with a timestamp-free `ResealRecord` (`canonical_path`, `contract_hash`, `entry_id`, `version`, `node_id`, `contract_source`, `lint_warnings`, `reused_existing_entry`); provenance time stays in the registry entry.
- **Dev escape hatch**: `ContractEnforcer.load()` and `from_declaration()` accept `allow_unsealed_reseal=True` (default `False`), documented for test scaffolds and dev iteration only. The default-loaded/default-built path is unchanged; production regeneration cannot bypass `reseal()`.
- **Evidence**: `tests/test_reseal.py` pins valid regeneration (version N+1 plus a working enforcer), lint warnings recorded without blocking, skipped and partial registration rejection, invalid/lint-error rejection before registration, legacy-registry refusal, same-content idempotency, and the dev-flag boundary.

### Added — Release attestation (M3.3, RFC 0003 §C6)
- **New `.github/workflows/release-attest.yml`**: after "Publish to PyPI" succeeds, downloads that run's `dist` artifact and attests the exact bytes already on PyPI — never a rebuild, so the attested wheel and the published wheel are identical by construction. It installs the wheel into an isolated venv, regenerates the self manifest from the installed tree, runs `scyvera self-check` as a gate, emits a CycloneDX 1.5 SBOM, builds the release manifest, signs all three with Sigstore build provenance, and uploads them to the tag's GitHub Release. A `workflow_dispatch` dry-run runs the same generation/attestation steps from a branch and skips the Release upload.
- **New `tools/build_release_manifest.py`**: deterministic release bundle binding `{wheel_hash, schema_version, adapter_floors, self_check_manifest}` per RFC 0003 §C6. `schema_version` is `"1.1"`; `adapter_floors` records the current library-scope floors (`n8n` and `langgraph`, both `"1.0"`); the self-check manifest is embedded by value so verification material travels with the attestation.
- **New `tools/generate_sbom.py`**: minimal deterministic CycloneDX 1.5 SBOM with no third-party SBOM tooling — a component for `scyvera` (name/version from `pyproject.toml` via `tomllib`, MIT license, wheel SHA-256) plus the declared runtime dependencies. `pydantic` is recorded as an `optional` component only when installed (it arrives transitively through the Qdrant gateway path, not as a direct dependency); absent optional packages are omitted so the SBOM stays a truthful snapshot.
- **`publish-pypi.yml`**: one additive step uploads the built `dist/` as the `dist` artifact (90-day retention, the maximum, `if-no-files-found: error`) for the attestation workflow to consume. Every other byte of the publish path is unchanged, and all new actions are pinned by full commit SHA with dated version comments.

### Added — self-check (M3.4, RFC 0003 §C2)
- **New `scyvera self-check [--json]` command**: verifies every runtime file in the *installed* `scyvera` distribution against the packaged `_self_manifest.json`. Resolution goes through `importlib.resources`, never the current directory, so a dev checkout cannot silently stand in for an install. Fail-closed on any modified, missing, or unlisted file — additions are tampering surface, for example a dropped-in module override (T5-consistent).
- **New `src/scyvera/selfcheck.py` engine**: `generate_manifest(package_path) -> bytes` emits canonical, timestamp-free JSON (`sort_keys`, compact separators, lexicographically sorted POSIX paths) with `{manifest_version, name, version, files[{path, sha256}]}`; `self_check(package_path=None) -> SelfCheckResult` returns frozen `SelfCheckResult` / `SelfCheckEntry` / `SelfCheckFailure` values, reports every deviation, and never prints or mutates the tree. Exclusions are `__pycache__/`, `*.pyc`, `*.pyo`, `.git*`, `*.egg-info/`, `*.dist-info/`, plus the manifest itself (it cannot hash itself; the exclusion is exact, not a wildcard). Manifest paths are validated as safe relative POSIX paths so a hostile manifest cannot redirect verification outside the package.
- **Exit codes documented and pinned**: `0` clean; `1` integrity deviation or manifest/installed version mismatch; `2` unverifiable — missing, malformed, or unsupported manifest, or an IO/installed-distribution problem. A missing manifest is deliberately `2` rather than `1`: the install cannot be verified instead of a deviation having been detected. The message names the path and points at a signed-release reinstall.
- **Package data**: `_self_manifest.json` ships in the wheel via `[tool.setuptools.package-data]`; `tools/generate_self_manifest.py` regenerates it from `src/scyvera` for dev or from an installed tree for release attestation. A committed manifest reflects the current tree at build time.
- **Evidence**: `tests/test_self_check.py` pins a fresh installed-style copy passing, tampered Python and bundled schema files failing with the file named, removals and unlisted additions failing, `__pycache__` exclusion, missing/malformed/unsupported manifests, version mismatch, path traversal, determinism, engine purity, frozen result types, and the CLI `0`/`1`/`2` matrix including `--json`.

### Added — Guardrail DSL v1.2 (M2.6, RFC 0003 §C5)
- **New v1.2 schema slice** (`src/scyvera/schemas/v1.2/contract.schema.json`, mirrored at `schemas/v1.2/`): a strict superset of v1.1. Only the version discriminator moves to `1.2`/`"1.2"` and one optional top-level `guardrails` object is added: `fail_closed` (boolean), `budgets` (`side_effects_per_window` >= 1 plus a `window` matching `^[0-9]+(s|m|h|d)$`), and `rate_limit` (`max_calls_per_minute` >= 1). `additionalProperties: false` inside every guardrails object rejects typos; `guardrails: {}` is a valid, explicit no-op. v1 and v1.1 contracts are unaffected byte-for-byte.
- **Validator wiring**: `ContractVersion.V1_2`, `detect_contract_version()` accepts `1.2` from `contract_version` and `version`, `SCHEMA_V1_2_PATH` resolves the bundled schema, and `apply_lifecycle_defaults()` treats v1.2 like v1.1 (optional lifecycle with the same defaults and warning). An explicitly unsupported version still fails loudly.
- **Linter AC701**: a v1/v1.1 contract that carries a top-level `guardrails` key now warns that guardrails require version 1.2 and are IGNORED by that contract version. It is a warning, never an error, so old contracts validate and lint exactly as before.
- **Runtime enforcement**: `ContractEnforcer` parses the block into frozen `Guardrails` / `Budgets` / `RateLimit` records exposed as `.guardrails`. In `_check_gate()`, after integrity/declaration/approval and before ALLOWED, `rate_limit` counts every gated attempt (allowed, denied, and pending) in a sliding 60-second window, and `budgets` counts only admitted `side_effect` executions in the declared window. Exceeding either denies with the new `GuardrailViolationError` (a `ContractViolationError` subclass) and audits `DENIED` with `guardrails.rate_limit` or `guardrails.budgets`.
- **fail_closed**: `true` denies when guardrail evaluation itself fails (bad clock, corrupted state, unknown window unit) and audits `guardrails.fail_closed`; `false` preserves the documented fail-open choice. Omitted or empty guardrails leave behavior exactly as before.
- **Testability and scope**: `load()` and `from_declaration()` accept an additive `clock=Callable[[], datetime]` used only for guardrail windows, so expiry is proven without sleeps. Counters are per enforcer instance and per process — honestly documented as not a distributed quota.
- **Evidence**: `tests/test_guardrails_schema.py` proves the strict-superset property across every existing contract fixture, rejects malformed guardrails at each level, pins AC701, and covers the CLI. `tests/test_guardrails_enforcement.py` pins budget/rate arithmetic, window expiry, attempt counting (including denied/pending), fail-closed/fail-open, async gates, declarations, and unchanged no-guardrail behavior.

### Added — Trace schema (M1.2)
- **New `src/scyvera/trace.py`**: the RFC 0003 §C4 execution trace. `TraceEntry` carries `node_id`, `action_name`, `action_type`, `declared`, `result` (`allowed` / `pending_approval` / `violation`), `hash_of_contract`, and `timestamp`, plus `reason` and `contract_field_reference` so every `AuditEntry` the enforcer can emit round-trips losslessly through `trace_from_audit()` / `audit_from_trace()`. `declared` is derived from the enforcer's undeclared-denial reason; guardrail and integrity denials stay declared.
- **`TraceLog`**: ordered, immutable collection with canonical JSONL (`sort_keys`, compact separators, one object per line, UTF-8). `from_jsonl()` fails closed on malformed lines with the 1-based line number, missing/unknown fields, wrong types, unknown results, bad digests, and non-ISO-8601 timestamps, all through the new `TraceError` (`ValueError` subclass). Empty logs are valid. The module is pure: no I/O, printing, or wall clock.
- **Evidence**: `tests/test_trace.py` pins round-trips for all three decisions, declared derivation, exact field sets, malformed input rejection, canonical bytes, and JSONL line numbers.

### Added — Eval harness (M2.4)
- **New `src/scyvera/evals/` package**: trace-driven evaluation on the four RFC 0003 §C4 axes. Eval cases are YAML fixtures (`{version, name, contract, agent, scenario, expected_trace, score_weights}`) loaded with fail-closed `EvalCaseError`: missing/unknown keys, bad weights, unknown action types/decisions, escaping or missing contracts, unsupported versions, empty scenarios, and unimportable factories are all rejected before execution.
- **Agent convention**: `factory(enforcer)` returns an object with one gated method per scenario action, named by lowercasing the action and replacing non-alphanumeric runs with `_` (`github:issues:read` -> `github_issues_read`). The harness executes steps in order, applies `enforcer.approve()` for `approve: true`, converts the audit log through `trace_from_audit()`, and records non-scyvera exceptions as recovery failures. It imports only the standard library and `scyvera`.
- **Scoring**: constraints (`0.0` on any undeclared attempt), approval (`0.0` on an unapproved approval-required/irreversible execution), recovery (mechanical expected-decision match), and replay (fresh-enforcer rerun must produce the identical decision sequence). `EvalResult` is frozen and deterministic; trace timestamps are normalized to a fixed ISO-8601 sentinel so serialized results are byte-identical across runs. Total is `100 × Σ(weight × axis)`, rounded to six decimals.
- **Golden fixture**: `implementations/langgraph/duplicate-issue-detector/evals/refund-agent.eval.yaml` plus a stdlib-only agent fixture and contract exercises a read, a pending approval, an approved write, and a deliberate undeclared action. It pins `constraints=0.0`, `approval=1.0`, `recovery=1.0`, `replay=1.0`, total `75.0` (the undeclared attempt is intentionally a constraint failure).
- **Docs**: new [`docs/evals.md`](./docs/evals.md) covers the case format, factory convention, axis semantics, determinism, and the 75-point rationale. `tests/test_evals.py` pins the golden score, per-axis failures, malformed-case rejection, and JSONL round-trips.

## [1.3.0] — 2026-11-04

### Added — Policy Packs (M2.7)
- **New `--pack <name>` flag**: `scyvera audit . --generate contract.yaml --pack github-safe` applies a local Policy Pack to the generated v1.1 draft (RFC 0004 §6). The pack supplies the draft's `domain`, forces `irreversibly_forbidden` effects to `irreversible: true` while removing their approval entries, and forces `requires_approval` actions to `required: true`. Pack constraints win over heuristic-derived entries; finding-only extras are appended. `--pack` without `--generate` exits `2` with one actionable stderr line.
- **Six golden packs**: `dev-agent`, `github-safe`, `finance-ops`, `research-assistant`, `email-triage`, and `devops-safe` ship under `packs/` and as wheel package data under `src/scyvera/packs/`. Loading is filesystem-only with no network fetch; pack names cannot escape the packs directory, and symlinked packs are refused (T14).
- **Pack QA sweep**: `tests/test_packs.py` loads every golden pack, applies it to every fixture corpus, writes the draft, and requires Tier 0 schema validation plus Tier 2 lint with zero warnings. It also pins the repository and packaged copies byte-for-byte.
- **Cap placement**: `cap_side_effects_per_window` is accepted under `derive` (the RFC 0004 §6 template) or under `construction` (the section's prose), but not both, so either literal reading of the RFC validates while the pack can never carry two conflicting caps.
- **Docs**: new [`docs/policy-packs.md`](./docs/policy-packs.md) documents the format, merge semantics, and the add-a-pack workflow.

### Changed — Documentation (Growth lane G1)
- **README rewritten around the no-contract funnel**: the hero now states the positioning sentence and leads with `scyvera audit` → report → badge → CI gate → generated draft, with hand-written contract authoring moved to the second path. The runtime enforcer, gateways, registry, builder, honesty sections, and domain examples remain.
- **Badges made non-stale**: the hardcoded test count is replaced by the `validate-contracts.yml` GitHub Actions badge; the row now adds PyPI, Python 3.10+, and this repository's own Shielded Blast Radius badge.
- **2-Minute Demo**: the README embeds `assets/scyvera-demo.gif`, a terminal capture of the audit, the generated draft, and the blocked action.
- **Roadmap refreshed**: `docs/roadmap.md` marks G1 as shipped and links each M2.0x/M2.7 row to its shipped note, so the plan and the changelog stay in step.

### Added — Auto-contract drafts (M2.0c)
- **New `--generate <contract.yaml>` flag**: `scyvera audit` now turns a scan into a ready-to-review v1.1 contract draft. Scored findings merge into `resources`, `permissions`, `side_effects`, and `approvals`; `system.name` comes from the scanned repository directory, `domain` is `software`, and `risk.level` tracks the worst scored severity. Critical findings mark matching side effects `irreversible`; medium and high findings never do (RFC 0004 §10.1). The report still prints exactly as before, followed by one line naming the written draft.
- **New `--force` overwrite guard**: `--generate` refuses to replace an existing file unless `--force` is passed, exiting `2` with a single actionable stderr line. `--force` without `--generate` is rejected the same way.
- **Additive JSON `draft_path`**: with `--json --generate`, the report gains one top-level `"draft_path"` key. Without `--generate`, `--json` output stays byte-identical.
- **Schema-accuracy guarantee**: every fixture corpus is drafted, written, re-read from disk, and validated in tests, so a draft that would fail `scyvera validate` or `scyvera lint` cannot ship.

### Added — Blast Radius Report (M2.0b)
- **Band-first terminal report**: `scyvera audit` now renders the Blast Radius report the way RFC 0004 §2 pins it — status and target first, then the score and band, a `Scanned N files (...)` breakdown, scored findings grouped by severity, and the contract suggestion footer. Quarantined fixture findings stay in `--json` but are never rendered.
- **New `--badge` flag**: emits a shields.io badge pinned to the Blast Radius band (never the numeric score, so published badges do not flap when scoring internals evolve). With `--json`, the report gains one additive top-level `"badge"` key; without `--badge`, `--json` output is byte-identical to before.
- **New `--fail-under <score>` CI gate**: exits `1` when the Blast Radius score is below the threshold and `0` otherwise, independent of whether findings exist. Thresholds are validated as integers from 0 to 100; invalid input exits `2` with a single actionable stderr line and no usage wall or traceback.
- **Windows-safe output**: the renderer falls back from the pinned em dash to `->` when the attached stdout encoding cannot represent it, so narrow console codepages (cp437/cp850) can never crash an audit run.

### Added — Audit Scan Engine (M2.0a)
- **New `scyvera audit [path]` command**: a bounded, read-only walk over a target tree scores it against the 11-rule AUxxx registry (`src/scyvera/audit_rules.py`) and emits a deterministic report — findings ordered by severity, rule id, and path, with no timestamp. `--json` prints that report as `report_version: 1` and nothing else.
- **Hardened scanning**: vendored and tooling directories (`.git`, `.venv`, `node_modules`, `dist`, `build`, `.agents`, and others) are skipped, files larger than 1 MiB are not read, binary content is sniffed and ignored, and symlinks are refused rather than followed (T14-consistent).
- **Diminishing per-rule loads (M2.0a.1)**: the first three occurrences of a rule contribute `1.00`, `0.25`, and `0.10` of its base weight, so one rule can add at most `1.35 x base`; the score is `max(0, 100 - ceil(total_load))`.
- **Fixture quarantine (M2.0a.1)**: findings under `tests/fixtures/`, or from a scan whose target is itself a fixture, stay visible in the report but contribute nothing to score, band, exit code, `draft_available`, `packs_suggested`, or `stats.findings`; a fixtures-only scan reports PASS and exits `0`.
- **Executable-context allowlist (M2.0a.1)**: `AU-SH-001`, `AU-GIT-001`, and `AU-NET-001` fire only in executable contexts — shell, PowerShell, batch, `Dockerfile*`, Makefile/justfile, and workflow `run:` blocks — never in prose, arbitrary YAML/JSON, or documentation.
- **Production hardening (PR #44)**: one typed executable-line parser now backs every context dialect, workflow `run:` blocks no longer leak indentation into a following `env:` block (fixing an AU-CI-001 false positive), and quarantine semantics are consistent end to end.
- **Dogfood gate**: `tests/test_audit_dogfood.py` runs `scyvera audit .` against this repository in CI and pins the Shielded band, so drift fails loudly instead of silently.
- **Docs**: RFC 0004 defines the report contract, scoring formula, and exit-code semantics; `CONTRIBUTING.md` and `.gitguardian.yaml` document the synthetic-fixture policy (scanner configuration excludes the path — tests are never weakened).

---

## [1.2.0] — 2026-10-31

### Added — Contract Registry, Dynamic Declarations & Gate Integrity (unreleased → released)
- **Contract Registry (`ContractRegistry`, `RegistryEntry`, `RegistryError`) (Phase 2)**:
  - Versioned, append-only, JSON-lines persistent store for registered contracts (`.scyvera/registry.jsonl`).
  - Idempotent registration on duplicate SHA-256 hash.
  - Automatic version incrementing per `node_id`.
  - Query APIs: `get_latest(node_id)`, `get_by_hash(contract_hash)`, `get_history(node_id)`, `get_at_time(node_id, timestamp)`, `list_nodes()`, `size()`, `has_hash(contract_hash)`.
  - Atomic writes using temporary file pattern to guarantee durability.
  - Fail-closed error handling raising `RegistryError` on corrupt or unreadable files.
- **Fail-Closed Gate Integrity (Threat T5 hardening)**:
  - `ContractEnforcer.gate()` now runs `verify_integrity()` before declaration checks; tampered or replaced contracts deny the action with an audited `DENIED` audit entry and raise `ContractTamperError` with recovery guidance instead of executing.
- **Governance Documentation & Distribution Roadmap (RFC 0003)**:
  - `docs/roadmap.md` — phased, task-gated implementation plan (P0–P4) with a locked glossary.
  - `rfcs/0003-harness-distribution-eval-and-integrity.md` — hash-chained registry, self-check, tiered conformance checking, trace-based eval harness, guardrail DSL, attested distribution artifacts.
  - `docs/threat-model-distribution.md` — distribution-layer threats T11–T14 (dependency confusion, contract substitution, registry history rewrite, symlink abuse).
  - `docs/architecture.md` renamed from the misspelled `achitecture.md`; README documentation tree refreshed.
- **Dynamic Contract Declarations (`ContractEnforcer.from_declaration()`) (Phase 1)**:
  - Create fully governed `ContractEnforcer` instances from in-memory Python dictionaries without requiring a `contract.yaml` file on disk.
  - Deep copy and cryptographic sealing with SHA-256 integrity hash at creation time.
  - Strict declaration validation (`DeclarationValidationError`) rejecting unknown fields, invalid `node_id` formatting, empty permissions, and wildcard injection (Threat T7).
  - Full feature parity with file-based enforcers: `@enforcer.gate(...)`, `verify_integrity()`, audit logs, and `approve()` work identically.
- **Enforcer Registration Integration**:
  - `ContractEnforcer.register(registry)` method to register an enforcer's contract directly into a registry and store `registry_entry_id`.
  - Added `node_id`, `contract_source`, and `registry_entry_id` properties to `ContractEnforcer`.
- **Expanded Test Suite**:
  - Added comprehensive test suites: `tests/test_declaration.py` (Phase 1) and `tests/test_registry.py` (Phase 2), bringing total tests to 141 passing tests.

---

## [1.1.3] — 2026-09-05

### Added
- **Gateway Enforcement Layer (`BaseGateway`, `GitHubGateway`, `QdrantGateway`)**:
  - Single enforcement boundary for external API operations and credential management.
  - Per-instance `@enforcer.gate` wrapping with default-deny semantics.
  - Optional dependency handling for `PyGithub` and `qdrant-client` to keep core package dependency-light.
- **Gateway Exception Wrapping**:
  - Introduced `GatewayError` to encapsulate third-party API client exceptions.
- Added GitHub Actions workflow for gateway linting (`.github/workflows/lint-gateway.yml`).

### Changed
- `ContractEnforcer.gate()` now supports `"read"` as an action type alias for permission gating.

---

## [1.1.2] — 2026-08-30

### Changed
- Version bump with packaging corrections
- pip install scyvera resolves to this release as latest stable
- T8 warning now correctly emitted via logging module 
  (scyvera.enforcer logger) instead of warnings.warn
- T7 wildcard rejection enforced at JSON schema level in addition 
  to Python load-time check — validate_contract() now catches 
  wildcards independently of ContractEnforcer

---

## [1.0.0] — 2026-08-30

### Added — Runtime Enforcer (Step 3)
- `ContractEnforcer` class: load, freeze, gate, audit, integrity verification
- `ContractEnforcer.gate(action_name, action_type)` decorator — default-deny enforcement of declared side_effects and permissions
- `ContractEnforcer.verify_integrity()` — SHA-256 check detects contract file replacement after load (T5)
- `ContractEnforcer.get_audit_log()` — returns deep-copy frozen AuditEntry list (T9)
- `ContractVersionError` — raised on schema version mismatch (T10)
- `ContractTamperError` — raised on frozen object mutation or disk file replacement (T5, T9)
- `ApprovalPendingError` — raised when action hits an approval_point; approval channel routing is caller's responsibility (stub, documented)
- `assert_gated(fn)` utility for integration test suites (T4)
- T7: wildcard permissions rejected at schema level AND Python load time
- T8: irreversible side effect + empty approval_points emits logging.WARNING via scyvera.enforcer logger
- 59-test suite covering all threat models T1–T10

### Stable Public API (semver-protected from v1.0.0)
- ContractEnforcer.load / gate / get_audit_log / verify_integrity / assert_gated
- ContractViolationError, ContractTamperError, ApprovalPendingError, ContractVersionError, AuditEntry

### What scyvera does NOT guarantee (documented in README)
- Cannot prevent gate bypass if integrator calls ungated function directly (T4 — known limitation)
- Cannot verify that gated function's internal behavior matches its declared permission string (T6 — known limitation)
- Integrity check protects AFTER load only, not before (T5)

---

## [0.3.0] — 2026-08-30

### Added — Contract v1.1 Spec + lifecycle field (Step 2)
- `lifecycle` field added to contract spec (optional, backward compatible)
- v1.1 JSON schema at schemas/v1.1/contract.schema.json
- Default applied by loader when lifecycle absent: {mode: request-response, initiation: human-only, resumability: stateless}
- loader emits logging.WARNING when defaults are applied
- `irreversible` boolean field on side_effects entries
- RFC 0002 (lifecycle field) added to rfcs/
- Three worked examples in spec: request-response, scheduled, persistent
- T1/T2/T3 threat mitigations documented

### Migration
- All v1 contracts (no lifecycle field) remain valid
- No breaking changes to validate_contract() or CLI

---

## [0.2.0] — 2026-08-30

### Fixed — Repository Cleanup (Step 1)
- Canonical filename is now contract.yaml everywhere; contract.yml references removed
- Loader raises actionable error on contract.yml: "Found contract.yml — rename to contract.yaml"
- Backslash folder issue resolved (if it existed)

### Migration
- Rename any contract.yml files to contract.yaml
