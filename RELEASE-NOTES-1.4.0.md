# Scyvera 1.4.0

Released 2026-11-09.

1.4.0 is the first release to carry the full platform that shipped on `main`
since 1.3.0: conformance checking, registry integrity, guardrails, measured
eval, unified reports, self-check and attestation, the `scyvera-gate` Action,
MCP server mode, and the R1/R1b audit hardening. The version is a minor bump,
not a patch, because these are new features and two new audit rules.

## Highlights

- **`scyvera check`** runs Tier 0 structural conformance and discovers static
  Tier 1 adapters for n8n workflow JSON and LangGraph source. `T101` and
  error-severity `T102` fail; `T103` warns. Adapters parse source; they never
  import or execute the target.
- **Registry integrity** includes the hash-chained `registry.jsonl`, canonical
  contract identity pinning, symlink/unregistered re-seal refusal, and the
  explicit `reseal()` ritual (validate → lint with zero errors → chain-verified
  register → fresh enforcer).
- **Guardrails v1.2** adds optional `fail_closed`, `budgets`, and `rate_limit`
  enforcement with audited denials. v1 and v1.1 contracts are unchanged.
- **Trace and eval** ships the canonical JSONL trace schema and a deterministic
  four-axis eval harness with the golden refund-agent case.
- **Unified reports** add the shared eight-key envelope: `scyvera eval`, plus
  additive `--unified` output on `audit` and `check`. Existing `--json` bytes
  do not move.
- **`scyvera self-check`** verifies installed runtime files against the packaged
  manifest. Release attestation downloads the exact published wheel, gates on
  the manifest, emits a CycloneDX 1.5 SBOM, and signs the release bundle with
  Sigstore.
- **`scyvera-gate`** is the composite GitHub Action for audit and conformance
  gates; it installs `scyvera>=1.3,<2`, so it accepts 1.4.0.
- **`scyvera serve-mcp`** exposes the engines over stdio JSON-RPC as MCP tools.
- **Audit hardening**: combined imports, agent/ML SDKs, source credentials,
  honest `[ungoverned]` status, BOM handling, and pattern-level coverage for
  Go, Java/Kotlin, Rust, C/C++, C#, PHP, and JS/TS.

## Honest limitations

- **Not production-certified.** The v1.4 production gate is satisfied on four
  of five conditions. The fifth — distribution reach — still lacks the
  `scyvera-harness` skill (M3.1) and per-target packaging (M3.2). The project
  remains beta-serious, and the Python classifier still says Beta.
- **Tier 2 is not implemented.** The unified schema can represent a
  runtime-trace conformance mode, but `scyvera check --tier 2` exits `2` with
  its not-implemented message.
- **Audit is pattern-level, review-grade.** It has no AST, type resolution,
  data-flow analysis, or framework graph; those belong to Tier 1 adapters.
  Absence of an audit finding is not evidence that a boundary is absent. See
  `docs/language-coverage.md`.
- **Guardrail counters are per enforcer instance and per process**, not a
  distributed quota across replicas.
- **Self-check is not sandboxing.** It detects changes to the installed
  `scyvera` package after install; it does not verify the interpreter or
  third-party packages. The root of trust is the signed release attestation,
  not the manifest alone.
- **PD-5 (published benchmark) is open and PD-8 (Rust scanner) remains
  deferred.**

## Upgrade notes

- No migration is required for v1 and v1.1 contracts.
- A pre-chain `registry.jsonl` still loads for queries, but `register()` fails
  closed until the explicit one-time `upgrade_chain()` migration is run.
- Guardrail blocks require the v1.2 contract version; AC701 warns on older
  contracts that carry them.

## Verification

- Full suite: see `docs/releases/1.4.0-verification.md`.
- Dogfood: `scyvera audit .` remains 92/100 Shielded.
- Release tag: `v1.4.0`; publish and attestation are handled by the existing
  tag-triggered workflows after the merge commit is tagged.
