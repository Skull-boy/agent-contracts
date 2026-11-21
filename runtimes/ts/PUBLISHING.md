# Publishing `@scyvera/scyvera-ts`

Publishing is a **human action**. This repository prepares the artifact and
documents the provenance procedure; it never publishes or stages on merge. No
npm token is stored in the repository: CI authenticates with GitHub OIDC
trusted publishing, and a maintainer approves the published version with 2FA on
npmjs.com. `0.1.0` (2026-11-18) was the last direct publish; `0.1.1`
(2026-11-21) was the first release staged through GE-4b.

The npm **package** is scoped: `@scyvera/scyvera-ts`. The installed **command**
stays unscoped: `scyvera-ts`. They are independent — the `bin` mapping
(`"scyvera-ts": "./dist/src/cli.js"`) does not follow the package name, so
`npx scyvera-ts` remains correct after the rename.

## Why the publish workflow is committed and gated

The repository's own dogfood audit has a high-severity rule for CI jobs that
run `npm publish` or `npm stage publish` (AU-CI-002, "deploy or publish job
detected"). That rule is correct here: a CI job really can publish a public
package, and staging is the same capability with the 2FA step deferred. The
workflow is therefore **committed and gated**, not hidden:

- The repository root `contract.yaml` declares `permissions: ["registry:publish"]`
  and approves it with `{action: registry:publish, required: true}` and the
  human role `repository_maintainer`. It is a full-authority, non-provisional
  contract, registered through the re-seal ritual.
- The workflow runs behind the `npm-production` environment, so a human
  approves every run. Approving the job only stages the release; a second, 2FA
  approval on npmjs.com is what publishes it.
- The dogfood score is **84/100 `Controlled`**, not 92/100 `Shielded`. The
  finding contributes its full high-severity weight (8.0) and is still scored:
  governance detection is render-only and does not discount it. This is
  recorded, not papered over.
- **RFC 0004 Amendment 1** (`rfcs/0004-amendment-1-dogfood-declared-capability.md`)
  records the math (7.8 + 8.0 = 15.8, `ceil` → 16 → 84), the rejected
  alternatives, and the new covenant: the dogfood test pins the exact scored
  surface and fails if the `registry:publish` approval is removed.

The workflow stays committed because moving it off `main` would leave the
capability undeclared, unregistered, and untested on the branch that ships it —
the exact papering-over that AU-CI-002 exists to prevent.

## Known cosmetic warning

`npm publish` (and `npm stage publish`) prints:

```text
npm warn publish "bin[scyvera-ts]" script name was cleaned
```

This is **cosmetic**. npm normalizes the leading `./` in the `bin` path at pack
time and the produced tarball has a working `scyvera-ts` executable.
`npm pkg fix` is deliberately **not** run: its only change is to rewrite
`"scyvera-ts": "./dist/src/cli.js"` to `"scyvera-ts": "dist/src/cli.js"`, which
`runtimes/ts/test/native.test.ts` pins by `deepEqual`; applied alone it leaves
the package suite at 68/69. Any future cleanup must change the manifest and the
test pin in one commit, with the warning as the stated reason.

## One-time maintainer setup

1. Confirm the npm account is a member of the `@scyvera` npm organization with
   write access to `@scyvera/scyvera-ts`, and has 2FA enabled.
2. Create the GitHub environment `npm-production` and require a reviewer.
3. Configure the package's **Trusted Publisher** (npmjs.com → package →
   Settings → Trusted publishing) for GitHub Actions:
   - organization/user `Skull-boy`, repository `scyvera`;
   - workflow filename `publish-scyvera-ts.yml` (filename only);
   - environment `npm-production`;
   - allowed action **`npm stage publish` only** — do not grant `npm publish`,
     and do not grant `npm dist-tag` (the staged tag is applied by the stage
     operation itself).
   The CLI equivalent (npm ≥ 11.15.0, 2FA prompt) is:
   `npm trust github @scyvera/scyvera-ts --file publish-scyvera-ts.yml --repo Skull-boy/scyvera --env npm-production --allow-stage-publish`
4. There is **no `NPM_TOKEN` secret**. The workflow declares `id-token: write`
   and npm exchanges the GitHub OIDC token for a short-lived publish token. Do
   not add a token secret as a shortcut: that would defeat the reason this path
   exists.
5. After the first staged release succeeds, set the package's publishing access
   to **"Require two-factor authentication and disallow tokens"**. Trusted
   publishers keep working; token publishes stop.

A newly created trusted publisher must complete its first successful publish
**within 2 days** or it expires unvalidated. Create it immediately before a
release, not weeks ahead.

Scoped packages default to **restricted** visibility. Every publish command
below passes `--access public` explicitly, and `package.json` keeps
`publishConfig.access: "public"`. Do not remove either: a restricted publish
would either fail or create a private package, which is not the intent.

## Preflight (local, from `runtimes/ts`)

```sh
npm ci
npm test                     # package tests + pinned suite-version test
npm run vectors              # 33/33 at suite-version 1
npm stage publish --dry-run --provenance --access public
```

The dry run needs npm CLI ≥ 11.15.0 and Node ≥ 22.14.0 (the staged-publish
floor; the workflow installs and checks npm 11 itself). Do not continue if any
step is red, if `vectors/suite-version` differs from the runtime's
`PINNED_SUITE_VERSION` (currently `1`), or if the working tree is dirty.

## Release procedure

1. Decide the version. `0.x` is intentional until the runtime has a stable
   published track record; never jump to `1.0.0` just to look finished.
2. Update the version in `runtimes/ts/package.json` (and the lockfile's root
   version) and add a `CHANGELOG.md` entry.
3. Merge through the normal PR path; never push `main`.
4. Tag the merged commit with `scyvera-ts-v<version>` (for example
   `scyvera-ts-v0.1.0`) and push the tag. The runtime tag is namespaced because
   the bare `v<version>` tag namespace belongs to the Python package (for
   example `v0.1.0`); reusing it would collide with an existing release tag.
5. Run the committed publish workflow (release published, or manual dispatch on
   the tag) and approve the `npm-production` environment gate. It runs the same
   local preflight, then `npm stage publish --provenance --access public`.
   Staging needs no 2FA and puts nothing live.
6. Review the staged version (npmjs.com → **Staged Packages**, or
   `npm stage list @scyvera/scyvera-ts`) and approve it with 2FA. Approval is
   what publishes the tarball and moves `latest`.
7. Confirm the npm page shows the **Provenance** attestation linking the tarball
   to this repository and workflow. A release without provenance is a failed
   release.

### Exact workflow (committed at `.github/workflows/publish-scyvera-ts.yml`)

```yaml
name: Publish @scyvera/scyvera-ts
on:
  release:
    types: [published]
  workflow_dispatch:
    inputs:
      dry-run:
        description: "npm stage publish --dry-run only"
        type: boolean
        default: true

permissions:
  contents: read
  id-token: write

jobs:
  publish:
    runs-on: ubuntu-latest
    environment: npm-production
    defaults:
      run:
        working-directory: runtimes/ts
    env:
      PINNED_SUITE_VERSION: "1"
      NPM_CLI_MAJOR: "11"
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262
      - uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020
        with:
          node-version: 22
          registry-url: https://registry.npmjs.org
          # No dependency cache in a release build: a cached node_modules tree
          # is an input to the artifact that gets attested, and npm's
          # trusted-publishing guidance is to never cache release builds.
      - name: Pin npm 11 for staged publishing
        run: |
          npm install -g "npm@${NPM_CLI_MAJOR}"
          version="$(npm --version)"
          major="${version%%.*}"
          if [ "${major}" -lt 11 ]; then
            echo "::error::staged publishing requires npm >= 11.15.0, got ${version}"
            exit 1
          fi
      - run: npm ci
      - name: Verify tag and suite pin
        run: |
          version="$(node -p "require('./package.json').version")"
          test "${GITHUB_REF_NAME}" = "scyvera-ts-v${version}"
          suite="$(tr -d '\r' < ../../vectors/suite-version)"
          test "${suite}" = "suite-version: ${PINNED_SUITE_VERSION}"
      - run: npm test
      - run: npm run vectors
      - name: Stage the release (OIDC, no token)
        run: |
          if [ "${{ inputs.dry-run }}" = "true" ]; then
            npm stage publish --dry-run --provenance --access public
          else
            npm stage publish --provenance --access public
          fi
```

## Rollout of the staged path (GE-4b)

Release runs use the workflow at the tagged commit, so GE-4b takes effect on
the tag after this change merges, not on the release that introduced it.
Before that tag:

1. **Configure the trusted publisher** (step 3 above) immediately before
   tagging. An unvalidated configuration expires after 2 days; a validated one
   persists.
2. **Keep the 2-day window honest.** The first run under the trusted publisher
   must actually stage a version. If it fails with `ENEEDAUTH`, the repository
   or workflow filename does not match the npm configuration exactly - both
   are case-sensitive - or the runner is not GitHub-hosted.
3. **Only then** restrict token access ("Require 2FA and disallow tokens") and
   revoke any publish token that still exists. Removing token access first
   would leave no working publish path if the trusted publisher were
   misconfigured.

Why `npm install -g npm@11` is pinned rather than `@latest`: staged publishing
needs npm CLI ≥ 11.15.0, while npm 12 requires Node
`^22.22.2 || ^24.15.0 || >=26`; a runner on an older Node 22 patch fails with
`EBADENGINE`. The workflow installs npm 11 and fails early if the installed
major is below 11.

If the OIDC path has to be reverted, that is a workflow change like any other:
restore the token step, recreate `NPM_TOKEN`, and record why in the CHANGELOG.
Do not push a token back as an emergency edit on a tag.

## Post-publish verification

Review the staged version before approving it:

```sh
npm stage list @scyvera/scyvera-ts
npm stage view <stage-id>
npm stage download <stage-id>     # inspect the exact tarball
npm stage reject <stage-id>       # 2FA; removes it without publishing
```

After approval, verify the live release:

```sh
npm view @scyvera/scyvera-ts@<version> version dist.integrity
npm view @scyvera/scyvera-ts@<version> dist.attestations
npm install @scyvera/scyvera-ts@<version>
npx scyvera-ts --version
npx scyvera-ts vectors --root <path-to-vectors>
```

`dist.attestations` must list both the npm publish attestation and a
`slsa.dev/provenance/v1` statement. Decode the SLSA payload and confirm the
source repository, `refs/tags/scyvera-ts-v<version>`, and
`.github/workflows/publish-scyvera-ts.yml` — a release without that link is a
failed release, regardless of what the package page shows.

## Rollback

- Before approval, prefer `npm stage reject <stage-id>` (2FA): nothing is live
  and no version number is spent.
- After publication, prefer `npm deprecate @scyvera/scyvera-ts@<version> "<reason>"`
  and publish a fixed patch.
- Do not unpublish a version that consumers may already depend on; npm's
  unpublish policy is time-limited and destructive.
- A bad release does not change the conformance claim: the runtime is only
  conformant at the pinned suite version, and a red vector run blocks the next
  publish.

## What this procedure does not do

- It does not publish the Python package (`scyvera` has its own release flow).
- It does not publish `scyvera-rs`.
- It does not promote provisional contracts or hold contract authority. The TS
  runtime has no promotion command (RFC 0005 §5.6, A5).
