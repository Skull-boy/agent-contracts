# Publishing `@scyvera/scyvera-ts`

Publishing is a **human action**. This repository prepares the artifact and
documents the provenance procedure; it never publishes on merge. No npm token is
stored in the repository, and this GE-4 session did not publish anything.

The npm **package** is scoped: `@scyvera/scyvera-ts`. The installed **command**
stays unscoped: `scyvera-ts`. They are independent — the `bin` mapping
(`"scyvera-ts": "./dist/src/cli.js"`) does not follow the package name, so
`npx scyvera-ts` remains correct after the rename.

## Why the publish workflow is committed and gated

The repository's own dogfood audit has a high-severity rule for CI jobs that
run `npm publish` (AU-CI-002, "deploy or publish job detected"). That rule is
correct here: a CI job really can publish a public package. The workflow is
therefore **committed and gated**, not hidden:

- The repository root `contract.yaml` declares `permissions: ["registry:publish"]`
  and approves it with `{action: registry:publish, required: true}` and the
  human role `repository_maintainer`. It is a full-authority, non-provisional
  contract, registered through the re-seal ritual.
- The workflow runs behind the `npm-production` environment, so a human
  approves every run at the moment of publication.
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

`npm publish` prints:

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
   publish rights on `@scyvera/scyvera-ts`, and has 2FA enabled.
2. Add a repository secret `NPM_TOKEN` holding a **granular** npm token named
   `scyvera-ts-publish`, scoped to **read-and-write** permission on the package
   `@scyvera/scyvera-ts` (not a broad account-wide publish token).
3. Create the GitHub environment `npm-production` and require a reviewer.
4. Use a workflow with minimal permissions: `contents: read` and
   `id-token: write` (the latter is only for npm provenance/OIDC).

Scoped packages default to **restricted** visibility. Every publish command
below passes `--access public` explicitly, and `package.json` keeps
`publishConfig.access: "public"`. Do not remove either: a restricted publish
would either fail or create a private package, which is not the intent.

## Preflight (local, from `runtimes/ts`)

```sh
npm ci
npm test                     # package tests + pinned suite-version test
npm run vectors              # 33/33 at suite-version 1
npm publish --dry-run --provenance --access public
```

Do not continue if any step is red, if `vectors/suite-version` differs from the
runtime's `PINNED_SUITE_VERSION` (currently `1`), or if the working tree is
dirty.

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
   the tag), approve the `npm-production` environment gate, and let it run the
   same local preflight before `npm publish --provenance --access public`.
6. Confirm the npm page shows the **Provenance** attestation linking the tarball
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
        description: "npm publish --dry-run only"
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
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262
      - uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020
        with:
          node-version: 22
          registry-url: https://registry.npmjs.org
          cache: npm
          cache-dependency-path: runtimes/ts/package-lock.json
      - run: npm ci
      - name: Verify tag and suite pin
        run: |
          version="$(node -p "require('./package.json').version")"
          test "${GITHUB_REF_NAME}" = "scyvera-ts-v${version}"
          suite="$(tr -d '\r' < ../../vectors/suite-version)"
          test "${suite}" = "suite-version: ${PINNED_SUITE_VERSION}"
      - run: npm test
      - run: npm run vectors
      - name: Publish with provenance
        run: |
          if [ "${{ inputs.dry-run }}" = "true" ]; then
            npm publish --dry-run --provenance --access public
          else
            npm publish --provenance --access public
          fi
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
```

## Post-publish verification

```sh
npm view @scyvera/scyvera-ts@<version> version dist.integrity
npm install @scyvera/scyvera-ts@<version>
npx scyvera-ts --version
npx scyvera-ts vectors --root <path-to-vectors>
```

## Rollback

- Prefer `npm deprecate @scyvera/scyvera-ts@<version> "<reason>"` and publish a
  fixed patch.
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
