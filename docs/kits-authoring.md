# Authoring a Scyvera adoption kit

An adoption kit is a small, declarative bundle that tells an adopter how to use
one shipped conformance target with Scyvera: the target's reference contract,
the exact check path, the result codes, and the honest limits. A kit is
**auxiliary integration**. It never ships engine code, never duplicates a
scanner rule, never changes enforcement, and never calls the network.

Read [`CONTRIBUTING.md`](../CONTRIBUTING.md) before you start. The contribution
workflow, commit style, review checklist, and fail-closed rules all apply to
kits.

---

## 1. Where a kit lives

The canonical location is one directory per target:

```text
kits/<target>/
```

Two shipped examples follow that layout:

- [`kits/n8n/`](../kits/n8n/) — the competitor-feature-parity watcher.
- [`kits/langgraph/`](../kits/langgraph/) — the duplicate-issue detector.

### The frozen-pin constraint (read this before adding a directory)

`tests/test_m32_kits.py` currently pins the **exact** top-level contents of
`kits/` to `{"README.md", "n8n", "langgraph"}` and pins each shipped kit to
exactly six files. A new directory under `kits/` fails the suite until the test
is updated.

The repository's own workflow is explicit: add the target to `TARGETS` in
`tests/test_m32_kits.py`, then run the full suite and the dogfood audit. Do that
when your contribution is allowed to touch `tests/`.

If a task forbids test changes (for example a `safe:no-core-change` issue), do
**not** fork the test and do **not** leave the suite red. Author the kit under:

```text
docs/kits/<target>/
```

and link it from [`kits/README.md`](../kits/README.md). That is how the Google
ADK reference kit at [`docs/kits/google-adk/`](./kits/google-adk/) exists. The
file contract below applies to both locations; only the parent directory
differs until the pin can be updated.

**Never** add a stray file to `kits/` or to a shipped kit directory without the
matching pin update. `kits/README.md` is the only non-kit file at the top level.

---

## 2. Required files

Every kit — shipped or proposed — contains this shape:

```text
kits/<target>/                    # or docs/kits/<target>/ while the pin is frozen
├── README.md                     # what it is, target framework, limits, how to run
├── KIT.md                        # house-template integration notes
├── contract.template.yaml        # valid contract fixture, editable fields marked
├── verify.sh                     # POSIX verifier (exit 0/1/2)
├── verify.ps1                    # PowerShell verifier (same behavior)
└── reference/
    ├── exit-codes.md             # byte-identical to the M3.1 skill table
    ├── finding-codes.md          # byte-identical to the M3.1 skill table
    └── <framework artifacts>     # reference agent, boundary notes, fixtures
```

The two shipped kits predate the `README.md` requirement and are pinned to
their exact six-file set (no README, code tables under `reference/`). When you
register a **new shipped kit**, update `REQUIRED_FILES` in
`tests/test_m32_kits.py` to match the template above, including `README.md`,
and keep the two code tables under `reference/` so the lockstep check still
finds them.

Rules that the existing kit tests enforce:

- **`contract.template.yaml`**, never `contract.yml` or `contract.template.yml`.
- The two result-code tables live under `reference/` and are **byte-identical**
  copies of `skills/scyvera-governance/reference/{exit-codes,finding-codes}.md`.
  Never rewrite them in a kit. To change a table: edit the skill, re-copy into
  every kit, refresh `python -m tools.lock_skill`, and run
  `tests/test_m31_skill.py` plus `tests/test_m32_kits.py`.
- No engine code, no vendored `scyvera` module, no scanner rule, no network
  client, no credentials, no generated binaries.
- Keep every file ASCII unless the framework artifact genuinely needs Unicode.
  Narrow Windows codepages must not crash the verify output.

`README.md` is the adopter-facing overview. `KIT.md` follows the house template:
a three-step path plus an honest scope section. Put anything that is a
framework-specific artifact (sample agent, boundary diagram, request/response
trace) under `reference/`.

---

## 3. The contract fixture

`contract.template.yaml` is a **read-only fixture** for the framework's
reference agent. It is copied by the adopter, not enforced in place.

Requirements:

1. **Valid against the shipped schema.** Use `version: 1.1` (or `1.2` when the
   fixture genuinely needs guardrails). v1 is legacy; do not use it for a new
   kit.
2. **Lint clean.** `scyvera lint` must report zero semantic warnings. The
   common traps:
   - write permissions without `side_effects` (`AC101`);
   - capability names starting with `read_`, `write_`, `delete_`, `create_`, or
     `update_` (`AC103`);
   - `risk.level: high`/`critical` with no `approvals` (`AC201`);
   - a required dependency with no `recovery` (`AC401`);
   - side effects with `observability.level: none` (`AC601`);
   - `irreversible: true` with no approval boundary (`AC302`);
   - `provisional: false` spelled out (`AC801`).
3. **Mark editable fields with `# EDIT`.** The shipped kit test requires at
   least five markers. Point them at the adopter's names, resources, verbs,
   approvals, dependencies, recovery, replay, state, and observability.
4. **Declare the real surface.** No wildcard resource or action. Name the
   resource/verb pairs the framework reference actually uses. An irreversible
   action needs an `approvals` entry naming a human role.
5. **`provisional` is a demonstration, not a default.** If the kit exists to
   show draft mode, include a clearly labeled example file or a one-line diff in
   `KIT.md` with `provisional: true`, and say it is draft-only. A scaffold
   template that every adopter copies should normally omit the field. When
   present, it must be a real boolean; the string `"true"` is a schema error.

Validate and lint before committing:

```bash
scyvera validate docs/kits/<target>/contract.template.yaml
scyvera lint     docs/kits/<target>/contract.template.yaml
scyvera check    docs/kits/<target>/contract.template.yaml --tier 0
```

A fixture that is not itself valid teaches the wrong thing.

---

## 4. `verify.sh` and `verify.ps1`

Both scripts must be **stdlib-portable, offline, read-only, idempotent, and
deterministic**. They are a teaching surface and a smoke test, not an
installer.

### Exit-code contract

| Code | Meaning |
|---|---|
| `0` | Every check the kit claims passed. Warnings that are documented as warn-only also exit `0`. |
| `1` | A real finding or contract deviation. Never downgrade it to a pass. |
| `2` | Usage/IO/unverifiable state: `scyvera` is missing, the fixture is absent, or the target has no adapter for the claimed tier. |

Preserve the engine's code; do not invent a new vocabulary.

### Required behavior

1. Resolve the repository root relative to the script, not the caller's `cwd`.
2. Check the install with `scyvera --version`; exit `2` when it is missing.
3. Run the checks the kit actually claims:
   - `scyvera validate <template>`
   - `scyvera lint <template>`
   - `scyvera check <template> --tier 0` (Tier 0 is always available)
   - `scyvera check <target> --tier 1` **only if** a Tier-1 adapter claims the
     target; otherwise say Tier 1 is not available instead of faking it.
   - optionally `scyvera audit <kit>` when the kit should be blast-radius clean.
4. Capture the exit code (`code=$?` in POSIX, `$LASTEXITCODE` in PowerShell)
   and exit with it on failure.
5. Print an `expected:` line so a human can compare the live output, then a
   final `verified (exit 0)` line.
6. Contain no `curl`, `wget`, `ssh`, `sudo`, `Invoke-WebRequest`, URL, token,
   credential, or install command. No elevation. No network.

`verify.sh` runs wherever a POSIX `sh` exists. `verify.ps1` is parse-checked on
Windows and executed by PowerShell users; keep both behaviorally identical.

**Do not claim a tier the engine cannot resolve.** "Tier 1 is unavailable for
this framework" is a correct, useful result. A fabricated PASS is not.

---

## 5. Reference the shared `vectors/` corpus — read-only

`vectors/` is the cross-runtime conformance corpus (RFC 0005 §6). It is
**read-only input**, pinned by `suite-version`, and shared by every runtime.

- A kit may point at `vectors/` and document how to run
  `scyvera vectors` (optionally `--category contract-model`,
  `gate-decision`, or `trace-roundtrip`).
- Do **not** copy, edit, reorder, regenerate, or vendor vector files into a
  kit.
- Do **not** add a kit-specific vector file. A new vector is a corpus change
  with its own review and a possible `suite-version` bump.
- Do **not** claim conformance by reading a kit's own files. The claim is
  "passes the shared corpus at the pinned `suite-version`", checked by the
  runner.
- A framework runtime is accepted against the **same bytes** as every other
  runtime; no kit gets a private corpus.

Typical read-only invocation:

```bash
scyvera vectors
scyvera vectors --category gate-decision
```

---

## 6. Document honest limitations

Every kit keeps an **Honest limitations** (or **Honest Tier N scope**) section
in both `README.md` and `KIT.md`. It is not optional marketing copy; it is part
of the product. State, at minimum:

- **What tier the kit actually verifies.** Tier 0 is structural; Tier 1 is
  static declared-vs-code; Tier 2 is runtime trace. Absence of an adapter is a
  `2`, not a pass.
- **What the framework can do that the kit cannot see.** Dynamic dispatch,
  reflection, aliases, runtime-assembled URLs, tools invoked outside the
  wrapper, model behavior, and prompt injection are common blind spots.
- **The orchestration/enforcement boundary.** A framework orchestrates; Scyvera
  enforces at the gate. A tool outside the gate is ungoverned. The contract on
  disk is authority; an in-memory guess is not.
- **Provisional/draft semantics.** Full mode refuses `provisional: true`; draft
  mode still denies undeclared actions and still gates irreversible actions;
  promotion is human-only; permanent draft buys no destructive authority
  (RFC 0005 §7.2, threat T15).
- **The honest audit limit.** Pattern-level, review-grade; a missing finding is
  not evidence of absence. Link
  [`docs/language-coverage.md`](./language-coverage.md) instead of implying
  completeness.
- **What the reference artifact is not.** Illustrative code is not a runnable,
  version-pinned integration; say so.

Write the limits in the same voice as the shipped kits: direct, specific, and
without a claim the engine cannot back.

---

## 7. Do not touch core

Kits are additive integrations. They must not change the product they integrate
with.

Do **not** modify:

- `src/scyvera/**` (engines, CLI, adapters, enforcer, audit rules);
- `schemas/**` (contract schemas);
- `vectors/**` (the shared corpus);
- `tests/**` (except the explicit `TARGETS` registration that the kit pin
  requires, when your task allows it);
- the CLI or its commands.

Do **not** change:

- exit codes (`0` pass / `1` fail / `2` usage or unverifiable);
- `audit --json` bytes, `check` render bytes, or trace JSONL bytes;
- public API or enforcement behavior.

Do **not** add Python dependencies. The repository-wide rule is stdlib +
PyYAML + jsonschema; a kit is not a reason to widen the trust base.

If you need a new Tier-1 adapter, a schema field, a new vector, or a new engine
behavior, stop: that is a separate RFC / lane with its own review. A kit can
*document* a missing adapter; it cannot become one.

---

## 8. Pre-PR checklist

```bash
# Fixture gates
scyvera validate docs/kits/<target>/contract.template.yaml
scyvera lint     docs/kits/<target>/contract.template.yaml
scyvera check    docs/kits/<target>/contract.template.yaml --tier 0

# Kit scripts
sh   docs/kits/<target>/verify.sh
pwsh docs/kits/<target>/verify.ps1

# Repository gates
python -m pytest tests/ -q
scyvera audit . --fail-under 92
git diff --stat src/scyvera schemas vectors tests
```

The last command must be empty for a docs/kits-only contribution. If you
registered a new shipped kit, the `tests/test_m32_kits.py` addition is the
intended exception and must be called out in the PR.

Also confirm:

- [ ] Reference-code tables are byte-identical to the skill copies.
- [ ] No real credentials, tokens, webhook URLs, or personal data.
- [ ] No new dependency, no network call, no install step in a verify script.
- [ ] `README.md` and `KIT.md` both state the honest scope and link
      `docs/language-coverage.md`.
- [ ] Commit messages use conventional style (`docs:`, `feat:`, `test:` …).
- [ ] Branch is based on current `main`; never push to `main`; never
      force-push.

---

## 9. Minimal scaffold

```text
docs/kits/<target>/
├── README.md
├── KIT.md
├── contract.template.yaml
├── verify.sh
├── verify.ps1
└── reference/
    ├── exit-codes.md
    ├── finding-codes.md
    └── <target>_agent.py
```

Start from the Google ADK reference kit when in doubt:
[`docs/kits/google-adk/`](./kits/google-adk/). It is deliberately small, it
passes the same structural gates, and it states the orchestration-vs-enforcement
boundary without overclaiming.
