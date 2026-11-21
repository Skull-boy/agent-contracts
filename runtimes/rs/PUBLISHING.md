# Publishing `scyvera-rs`

**Status: not published yet.** This document is the runbook; it is not evidence
that a crate exists. The first publish is a human action (see §2), because
crates.io requires an API token until the crate exists.

Publishing is never automatic on merge. The repository prepares the artifact,
attests it, and the maintainer approves the release.

## 1. What crates.io actually supports (checked 2026-11-21)

| Capability | Reality |
|---|---|
| Trusted publishing (OIDC, no long-lived token) | **Generally available for GitHub Actions.** [RFC 3691](https://rust-lang.github.io/rfcs/3691-trusted-publishing-cratesio.html), docs at <https://crates.io/docs/trusted-publishing>. The workflow exchanges its OIDC token via `rust-lang/crates-io-auth-action@v1` for a 30-minute publish token. |
| First publish without a token | **No.** crates.io's own prerequisite: *"Your crate must already be published to crates.io (initial publish requires an API token)."* The trusted-publisher configuration lives on the crate settings page. |
| Workflow binding | The trusted publisher stores repository owner, repository name, **workflow filename**, and an optional **environment**. A publish from any other workflow, repository, or environment is rejected. |
| Registry-native build provenance | **No.** crates.io records which trusted publisher published a version and its own sha256 of the uploaded `.crate`. It does not produce SLSA provenance, and it does not rebuild or reproduce the artifact. |
| Token-based publishes after setup | Can be forbidden with the crate's opt-in `trustpub_only` flag (crates.io #12361): API-token publishes then fail with `403`. |

This is materially different from npm, where the registry hosts SLSA provenance.
Do not describe the crate as "published with registry provenance".

## 2. Bootstrap publish (human, once)

The crate name must be free at this moment: the 2026-11-21 check returned `404`
for `https://crates.io/api/v1/crates/scyvera-rs`, but a name is only reserved by
publishing.

From a clean checkout of the merge commit, on the release branch:

```sh
cd runtimes/rs
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test --locked
cargo run -- vectors --root ../../vectors
cargo publish --dry-run --locked
cargo publish --locked
```

`cargo publish` prompts for a crates.io API token. Use a **scoped, short-lived**
token (crates.io → Account Settings → API Tokens, scope `publish-new` +
`publish-update`, shortest practical expiry), and revoke it immediately after
the publish succeeds. Do not store it in the repository or in a repository
secret; this bootstrap is the only step that uses a token.

Then, in crates.io → `scyvera-rs` → *Settings → Trusted Publishing*, add:

| Field | Value |
|---|---|
| Platform | GitHub Actions |
| Repository owner | `Skull-boy` |
| Repository name | `scyvera` |
| Workflow filename | `publish-scyvera-rs.yml` |
| Environment | `crates-io-production` |

Finally, after one successful trusted publish, enable **`trustpub_only`** so
token publishes are refused by the registry. Confirm with
`GET https://crates.io/api/v1/crates/scyvera-rs` → `"trustpub_only": true`.

## 3. Steady-state release (CI)

`.github/workflows/publish-scyvera-rs.yml` runs on a published GitHub Release or
`workflow_dispatch`, behind the `crates-io-production` environment (the
maintainer is the required reviewer).

Release procedure:

1. Decide the version. `0.x` is intentional until the runtime has a published
   track record.
2. Update `runtimes/rs/Cargo.toml` `version` and `Cargo.lock`, and add a
   `CHANGELOG.md` entry. Merge through a PR; never push `main`.
3. Tag the merged commit `scyvera-rs-v<version>` and push the tag. The tag is
   namespaced because `v<version>` belongs to the Python package and
   `scyvera-ts-v<version>` to the TypeScript runtime.
4. Create a GitHub Release on that tag (a release event runs the workflow from
   the tagged commit).
5. The run pauses at the `crates-io-production` environment. Open the run,
   review, and approve.
6. The run verifies the tag and the suite pin (`PINNED_SUITE_VERSION: "1"`),
   runs `cargo test --locked`, `cargo clippy`, the full vector suite,
   `cargo package --locked`, attests the `.crate`, then publishes with the
   short-lived OIDC token.

The workflow exits `2` (never a silent pass) if the tag, the suite pin, or the
package version disagree.

## 4. What is attested, and what is not

**Attested** — `actions/attest-build-provenance` over
`target/package/scyvera-rs-<version>.crate`:

- the SHA-256 of that exact file;
- the workflow path, repository, commit SHA, and ref that built it.

Verify with GitHub CLI:

```sh
gh attestation verify scyvera-rs-<version>.crate --repo Skull-boy/scyvera
```

**Not attested — stated plainly:**

- crates.io does not verify, rebuild, or sign the code. The registry trusts the
  publisher credential, not the build.
- The attestation covers the `.crate` **we** produced. Proving the registry
  serves those bytes requires downloading and hashing:

  ```sh
  curl -L -o published.crate https://crates.io/api/v1/crates/scyvera-rs/<version>/download
  sha256sum published.crate scyvera-rs-<version>.crate
  ```

  The two digests must match, and the registry's reported checksum
  (`https://crates.io/api/v1/crates/scyvera-rs/<version>` → `checksum`) must
  match both. Record that comparison in the CHANGELOG entry for the release.
- No bit-for-bit reproducibility claim: the same source built by a different
  rustc version is not asserted to produce identical bytes.
- The bootstrap publish (§2) predates the trusted publisher. Its provenance is
  the commit, tag, and the checksum recorded at publish time — not an OIDC
  exchange.

## 5. Local preflight

```sh
cd runtimes/rs
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test --locked
cargo run -- vectors --root ../../vectors     # 33/33 at suite-version 1
cargo publish --dry-run --locked
```

Do not continue if any step is red, if `vectors/suite-version` is not exactly
`suite-version: 1`, or if the working tree is dirty.

## 6. Known packaging notes

- The crate includes `src/`, `schemas/`, `README.md`, `PUBLISHING.md`, `LICENSE`,
  and `Cargo.toml` (see `include` in `Cargo.toml`). `schemas/` is a byte-identical
  copy of the monorepo's `schemas/`; a test asserts equality while the monorepo
  layout is present, and the copy is what ships.
- `Cargo.lock` is committed. The release workflow publishes with `--locked`, so
  the dependency set that passed CI is the set that ships.
- `publish = true` is the default; no `publish = ["..."]` allowlist is needed
  because crates.io is the only target.
