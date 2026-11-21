# GE-5 — `scyvera-rs`: native Rust runtime

> Status: **Phase 0 decisions recorded 2026-11-21.** Implementation status is tracked in the
> build-order table at the end; this document is the decision record, not a progress report.

The roadmap row is [GE-5](./roadmap.md): *"`scyvera-rs` — native Rust runtime, cargo-first, same
scope as GE-4 via the vectors; published to crates.io under the same attestation discipline."*

Exit acceptance: passes ALL vectors at the pinned suite version in its own CI; crate published;
the Python implementation remains the reference semantics.

---

## 1. Non-negotiables carried into this lane

1. **Native Rust only.** No spawning Python, no embedded interpreter, no wrapper around
   `scyvera`. A wrapper would duplicate the trust base the runtime exists to replace.
2. **One shared corpus, one pinned suite version.** All 33 vectors at `suite-version: 1`, all
   three categories. No subset, no edits to `vectors/`, no edits to `suite-version`.
3. **Python is the reference.** When Rust and Python disagree, Rust is wrong unless an accepted
   RFC change says otherwise. Spec conflicts are raised, never silently reworded.
4. **Additive only.** No changes to `runtimes/ts/`, `schemas/`, or the vector bytes.
5. **Shared exit codes**: `0` clean, `1` findings/drift, `2` usage or configuration error.
6. **No direct commits to `main`.** Branch + PR; the maintainer merges.
7. **One lane at a time.** GE-6 stays deferred.

---

## 2. Publishing and attestation reality check

**crates.io does not have npm's model, and the difference is material.** The check below was run
against primary sources on 2026-11-21, not assumed.

### 2.1 What crates.io supports today

| Capability | Reality on 2026-11-21 |
|---|---|
| Trusted publishing (OIDC, no long-lived token) | **Generally available for GitHub Actions.** The flow is [RFC 3691](https://rust-lang.github.io/rfcs/3691-trusted-publishing-cratesio.html); the user-facing procedure is <https://crates.io/docs/trusted-publishing>. GitHub Actions and GitLab CI (public beta) are supported; the exchange endpoint is `POST /api/v1/trusted_publishing/tokens`. |
| First publish without a token | **Not possible.** *"Your crate must already be published to crates.io (initial publish requires an API token)"* — crates.io's own prerequisite list. The trusted-publisher configuration lives on the crate's settings page, so it cannot exist before the crate does. |
| Token lifetime | 30 minutes, automatically revoked by the auth action's `post` step. |
| Workflow binding | The trusted publisher is configured with repository owner, repository name, **workflow filename**, and an optional **environment**. A publish from any other workflow filename, repository, or environment is rejected. |
| Registry-native provenance (SLSA-style) | **No.** crates.io records *which trusted publisher* published a version and exposes crates.io's own sha256 of the uploaded `.crate`; it does not produce or host a build-provenance attestation, and it does not rebuild or reproduce the artifact. |
| Enforce trusted publishing only | Opt-in `trustpub_only` flag on the crate (crates.io #12361): once set, API-token publishes are rejected with `403`. Visible via `GET /api/v1/crates/{name}`. |

### 2.2 Options evaluated

| Option | Verdict |
|---|---|
| **(a) Protected workflow + scoped crates.io token in a protected environment** | Rejected as the steady state. It works, but it reintroduces the long-lived credential this lane is supposed to avoid, and rotation becomes a maintainer chore with no registry-side proof. Retained **only** as the one-time bootstrap (see below), because crates.io requires it. |
| **(b) Attest the built `.crate` with GitHub OIDC `actions/attest-build-provenance`** | **Adopted, additively.** The attestation is signed by GitHub, stored against this repository, and verifiable with `gh attestation verify <file> --repo Skull-boy/scyvera`. It proves *which workflow, commit, and ref produced these bytes*. It does **not** prove the registry serves those bytes; that link is a digest comparison the verifier performs (see §2.4). |
| **(c) crates.io trusted publishing** | **Adopted, as the publish credential.** `rust-lang/crates-io-auth-action@v1` exchanges the workflow's OIDC token for a 30-minute publish token; no `CARGO_REGISTRY_TOKEN` secret exists in the repository. |

### 2.3 Chosen release path

Bootstrap and steady state are deliberately different, and the difference is recorded rather than
hidden:

1. **Bootstrap (human, once).** The maintainer publishes `scyvera-rs` `<version>` from a clean
   checkout with a scoped, short-lived crates.io API token, after `cargo publish --dry-run` and the
   full local gate pass. This is the only publish that uses a token, because the crate must exist
   before a trusted publisher can be attached.
2. **Attach the trusted publisher.** crates.io → crate → *Settings → Trusted Publishing*, GitHub
   Actions: repository `Skull-boy/scyvera`, workflow `publish-scyvera-rs.yml`, environment
   `crates-io-production`.
3. **Enable `trustpub_only`.** After one successful trusted publish, flip the flag so API-token
   publishes are refused. This is what makes "no long-lived credential" a registry-enforced fact
   rather than a workflow convention.
4. **Steady state (CI).** `.github/workflows/publish-scyvera-rs.yml` runs on a published GitHub
   Release or `workflow_dispatch`, behind the `crates-io-production` environment (maintainer is the
   required reviewer), with `permissions: id-token: write`. It verifies the tag
   (`scyvera-rs-v<version>`), the suite pin, `cargo test`, `cargo clippy -D warnings`, the vector
   run, `cargo publish --dry-run`, then builds the `.crate`, attests it, and publishes.

### 2.4 What is attested, and what is not

**Attested** (`actions/attest-build-provenance`, subject `target/package/scyvera-rs-<version>.crate`):
the SHA-256 digest of that exact file, the workflow path, the repository, the commit SHA, and the
ref. Verifiable offline against GitHub's Sigstore bundle via `gh attestation verify`.

**Not attested — stated plainly:**

- crates.io does not verify, reproduce, or sign the build. The published tarball is trusted because
  the publisher's credential was trusted, not because the registry checked it.
- The attestation covers the `.crate` **we** built. Proving the registry serves those bytes means
  downloading `https://crates.io/api/v1/crates/scyvera-rs/<version>/download`, hashing it, and
  comparing to both the attested subject digest and the sha256 crates.io reports. Until someone
  runs that comparison, "attested" means "the build we intended", not "the bytes on the registry".
- No `rust-toolchain` reproducibility claim: the build is not bit-for-bit reproducible across
  versions of rustc, and this lane does not assert that it is.
- The initial bootstrap publish (§2.3 step 1) predates the trusted publisher. Its provenance is
  the release record (commit, tag, checksum), not an OIDC exchange.

### 2.5 Crate name

`scyvera-rs` was verified free on 2026-11-21 (`GET https://api.crates.io/api/v1/crates/scyvera-rs`
→ `404`). This must be re-checked immediately before the bootstrap publish; the name is only
reserved by publishing.

### 2.6 Rejected publishing alternatives

| Alternative | Why rejected |
|---|---|
| Publish from a maintainer laptop for every release | No workflow binding, no environment gate, no OIDC identity, no attestation subject tied to a commit. It is the model trusted publishing exists to replace. |
| Keep a long-lived `CARGO_REGISTRY_TOKEN` secret | A leaked secret can publish any version of the crate. `trustpub_only` cannot be enabled, because it would then block the only credential the workflow has. |
| Claim npm-style SLSA provenance for the crate | False. npm's registry hosts and validates provenance; crates.io does not. The README and CHANGELOG say "GitHub artifact attestation", never "crates.io provenance". |
| Publish under a new crate named `scyvera` | Taken/ambiguous, and `scyvera-rs` states the runtime honestly. |

---

## 3. Repository location

**Decision: `runtimes/rs/` inside this monorepo**, exactly as GE-4 decided for `runtimes/ts/`.

Rationale (recorded, not relitigated):

- **One RFC source.** The Rust runtime implements RFC 0005 and must be reviewable against the same
  text as the Python reference and the TypeScript runtime.
- **`vectors/` reachable by relative path.** The Rust CI runs the same bytes as Python and TS, at
  the same pinned `suite-version`, in one repository. A separate repository would need a
  corpus-sync mechanism — a new failure mode — for no isolation gain.
- **Differential runs in one CI.** A vector-semantics change is visible in one diff, across all
  runtimes, instead of three independent histories.
- **Additive.** The crate is a workspace member with its own `Cargo.toml`; it does not couple the
  Python package's build to Rust.

The crate is still an independent **package** (its own semver, its own crates.io release), which is
what the roadmap line "separate package, crates.io" means.

---

## 4. MSRV

**Decision: `rust-version = "1.85"` (edition 2021), tested in CI alongside current stable.**

- 1.85 is the MSRV floor of the only runtime dependency, `yaml-rust2` 0.13. Pinning lower would be
  a claim the dependency graph forbids.
- Edition 2021 rather than 2024: the runtime adds no language features that edition 2024 would
  improve, and a conservative edition keeps the MSRV honest for adopters on older toolchains.
- CI matrix: `1.85.0` and `stable`. Clippy runs on stable only (`-D warnings`); MSRV proves the
  crate still builds and the test suite still passes, which is the property adopters care about.

---

## 5. Dependency policy

**One runtime dependency: `yaml-rust2` with `default-features = false`.**

| Need | Approach | Why not a crate |
|---|---|---|
| YAML loading | `yaml-rust2` (pure Rust, MIT/Apache-2.0, MSRV 1.85) | A YAML parser is explicitly allowed and is not worth hand-writing. `default-features = false` drops the `encoding_rs` feature; the loader decodes UTF-8 itself and fails closed. |
| JSON parse/serialize | Hand-written, in `src/json.rs` | Keeps the trust base small, rejects duplicate keys the way the Python reference does, and preserves number literals so canonical output is byte-exact. |
| Canonical JSON / JSONL bytes | Hand-written writer | Must reproduce Python's `sort_keys`, `ensure_ascii` (vectors) and `ensure_ascii=False` (trace) exactly. A generic serializer would need configuration to match, and none of the rust JSON crates guarantee Python's spacing and escaping rules. |
| JSON Schema validation | Hand-written evaluator over the real schema files | The schemas use a closed keyword set (`type`, `required`, `properties`, `additionalProperties`, `items`, `minProperties`, `maxProperties`, `const`, `enum`, `anyOf`, `oneOf`, `not`, `if`/`then`, `minLength`, `maxLength`, `pattern`, `minimum`, `maximum`) and exactly two regex patterns. An unknown keyword fails closed. No `$ref`, no `format`, no dynamic scope. |
| SHA-256 | Hand-written, in `src/sha256.rs` | Needed for contract identity and tamper detection. Verified against NIST test vectors in unit tests. |
| Date/time formatting | Hand-written ISO-8601 formatter | Audit timestamps only; no timezone database, no wall-clock dependency in any vector path. |
| Temp directories | `std::env::temp_dir` + unique suffix | The vector runner needs a scratch dir per contract; no crate required. |

`cargo tree` must show exactly one non-std dependency. That is checked in CI so the claim stays
true.

---

## 6. Spec reading done before coding

- **RFC 0005 §6** (vector format, §6.1–§6.10): layout, envelope, canonical codes, determinism,
  runner obligations, and what is *not* in the suite (promotion, audit rules, skills, performance).
- **`vectors/README.md`** and **`vectors/CHANGELOG.md`**: the tamper-denial mapping to
  `ContractViolationError` + `message_contains: "tampered"`, and the JSON-Pointer normalization of
  `contract-model` error paths.
- **`runtimes/ts/src/*`** as the behavioral template: `contract.ts` (load order, T14, wildcard
  refusal), `enforcer.ts` (integrity → declaration → approval → guardrails → allowed, draft-mode
  irreversibility), `trace.ts` (C4 schema, fail-closed parsing, canonical JSONL), `vectors.ts`
  (fail-closed loader, per-category executors), `cli.ts` (exit codes).
- **`src/scyvera/vectors.py`** for the byte-exact canonical forms: vector files are
  `json.dumps(sort_keys=True, indent=2, ensure_ascii=True) + "\n"`; results are compact with
  `ensure_ascii=True`; trace JSONL is compact with `ensure_ascii=False`.

Where Rust idioms differ, behavior is ported and structure is not: errors are one enum with a
canonical-code mapping instead of a class hierarchy; the contract is an immutable
`BTreeMap`-backed value instead of a deep-frozen object; the enforcer owns its audit log as a
`Vec` instead of a JS array.

---

## 7. Build order and status

| Step | Artifact | Status |
|---|---|---|
| 1 | `runtimes/rs/` scaffold: workspace member, `rust-version`, fmt/clippy clean | **shipped in this lane** |
| 2 | Contract model: v1/v1.1/v1.2 loading, provisional rules, lifecycle defaults, wildcard refusal | **shipped in this lane** |
| 3 | Enforcer: default-deny, approval boundaries, draft-mode irreversibility | **shipped in this lane** |
| 4 | Trace: C4 JSONL, fail-closed parse, canonical output | **shipped in this lane** |
| 5 | Vector runner over all three categories | **shipped in this lane** |
| 6 | CLI: `validate`, `gate`, `vectors`; `lint`/`check`/`audit` refuse with exit `2` (see §7.1) | **shipped in this lane** |
| 7 | CI: `.github/workflows/scyvera-rs.yml` with MSRV + stable, suite-drift check | **built, unproven until the PR's CI runs** |
| 8 | Release path: bootstrap publish, trusted publisher, `trustpub_only`, attested `.crate` | **not started** — requires a human maintainer with a crates.io credential |

The status column is intentionally blunt: a workflow that has never run is
**built, not proven**, and this document is not updated to say "published" until
crates.io serves the crate.

### 7.1 Deviation from the requested CLI surface

The lane brief lists `scyvera-rs {validate,lint,check,audit,vectors}`. This
implementation ships `validate`, `gate`, and `vectors`, and makes `lint`,
`check`, and `audit` exit `2` with an explicit explanation.

Reason: `lint`, `check`, and `audit` are Python-owned by locked decision. The
roadmap's GEP non-goals say "No TS reimplementation of the audit rule
registry", and RFC 0005 §6.10 keeps audit out of the cross-runtime suite. The
Rust audit binary is the separate **GE-6** lane, which is explicitly deferred
("one lane at a time"). Implementing any of the three here would either
duplicate the audit engine (GE-6's whole job) or wrap the Python CLI (forbidden
by non-negotiable #1). A loud exit `2` is the honest alternative to a fake
implementation.

`gate` is included because it is the RFC 0005 §4.2 decision surface and is what
the gate-decision vectors exercise; it is also present in `scyvera-ts`, so the
two native runtimes stay comparable.

### 7.2 Evidence recorded by this lane

- `cargo test --locked`: 78 tests green (34 unit, 3 binary, 41 integration
  across contract-model, gate, trace, suite, and CLI).
- `cargo run -- vectors --root ../..`: **33/33 at suite-version 1** — 11
  contract-model, 13 gate-decision, 9 trace-roundtrip.
- `cargo fmt --all --check` and
  `cargo clippy --all-targets -- -D warnings`: clean.
- `cargo tree --depth 1`: exactly one direct dependency.
- Publication: **not done** in this lane. No crate, tag, or attestation is
  claimed.
