# Contributing to Scyvera

Thanks for considering a contribution — this repository grows through community-submitted contracts, framework reference implementations, specification proposals, audit rules, and governance tooling in `scyvera`.

Scyvera is a Python package (`scyvera`) plus a specification and a set of reference implementations. Everyone from policy authors to Python contributors should find a lane below.

---

## 📌 Ground Rules

- **Never push directly to `main`.** All changes — new implementations, Python code, docs, schemas — go through a feature branch and a pull request. `main` only receives merges after review.
- **Canonical naming is `contract.yaml`** — never `contract.yml`. The loader and schema reject `.yml` extensions.
- **Every implementation declares a contract** — any workflow or agent implementation must include a valid `contract.yaml` alongside its code or workflow definition.
- **Run the test suite** — all Python tests must pass (`pytest tests/ -v`). The same suite runs across Windows, Linux, and macOS on Python 3.10–3.14.
- **No real credentials, tokens, chat IDs, webhook URLs, or personal data** in anything you commit. Use clear placeholders (`REPLACE_ME`, `YOUR_KEY`, etc.).
- **Fail closed.** New code paths that cannot verify something must say so and exit non-zero for the CLI; never degrade silently.
- **No new runtime dependencies** without discussion. The runtime is stdlib + PyYAML + jsonschema; optional adapters live behind extras.

---

## 🧭 Contribution Workflow

### 1. Fork and clone the repository

Click **Fork** on GitHub, then clone your fork locally:

```bash
git clone https://github.com/<your-username>/agent-contracts.git
cd agent-contracts
```

### 2. Set up the development environment

Python **3.10–3.14** is supported; use whichever version you have.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate

pip install -e ".[dev]"
```

`[dev]` adds pytest, build, PyGithub, and qdrant-client. If you work on the gateways, install `".[all,dev]"`.

Verify the suite:

```bash
pytest tests/ -v
```

### 3. Create a feature branch

Always branch off an up-to-date `main`:

```bash
git fetch origin
git switch -c feature/<short-description> origin/main
```

Examples:

```bash
git switch -c feature/langgraph-research-assistant
git switch -c feature/audit-rule-weak-approval
git switch -c fix/windows-badge-encoding
```

### 4. Make the change, then run the gates

The minimum bar before opening a PR:

```bash
pytest tests/ -q
scyvera audit . --fail-under 90
scyvera self-check            # optional locally; see the manifest note below
```

---

## 🛠️ Areas to Contribute

### A. Python package (`src/scyvera/`)

| Module | Responsibility |
|---|---|
| `audit.py` / `audit_rules.py` | Deterministic Blast Radius scan engine and the AUxxx rule registry. |
| `report.py` | Band-first terminal renderer, badge, and encoding-safe output. |
| `generate.py` | Findings-derived v1.1 contract drafts and `--force` semantics. |
| `packs.py` | Local Policy Pack loading, validation, and merge rules. |
| `validator.py` / `linter.py` | JSON Schema validation and Tier 2 ACxxx semantic rules. |
| `conformance.py` | Tier 0/1 conformance engine, `Tier1Adapter`, and `T101`–`T103`. |
| `enforcer.py` | Runtime default-deny gating, identity pinning, dynamic declarations, audit log. |
| `gateway.py` | Gated clients (`BaseGateway`, `GitHubGateway`, `QdrantGateway`). Raw SDK imports and credentials must live **only** here. |
| `registry.py` / `chain.py` | Append-only registry, hash-chain mechanics, verification, migration. |
| `reseal.py` | The validate → lint → re-register → seal ritual. |
| `selfcheck.py` | Installed-package manifest generation and verification. |
| `cli.py` | Argument parsing and presentation; engines stay pure. |

CLI subcommands today: `validate`, `lint`, `check`, `self-check`, `audit`, `init`.

#### Engine/CLI split

Engines are pure functions and frozen dataclasses: no printing, no global state, no writes to the tree, no timestamps in serialized output. Presentation, exit codes, and user-facing messages belong in `cli.py` / `report.py`. Follow the existing pattern:

- `0` success, `1` a real finding/deviation, `2` usage, IO, or unverifiable state.
- Fail closed: missing or malformed inputs never become a passing result.
- Deterministic output: sorted keys and paths, no wall-clock fields in anything that is hashed or attested.
- Encoding-safe terminal output: the renderer must survive narrow Windows codepages.

`tests/test_self_check.py`, `tests/test_conformance_cli.py`, and `tests/test_audit_report.py` are good templates for CLI and engine tests.

#### Manifest note

If you edit **any file under `src/scyvera/`**, regenerate the shipped manifest and commit it:

```bash
python -m tools.generate_self_manifest
```

`src/scyvera/_self_manifest.json` is package data and is verified by `scyvera self-check`. A stale manifest makes a wheel install fail its own integrity check. Docs, tests, and tooling changes do not affect the manifest.

### B. Audit rules (`audit_rules.py` + fixtures)

New AUxxx rules need:

1. A registry entry with id, title, severity, and remediation text.
2. At least one positive fixture under `tests/fixtures/audit/` and one clean case.
3. A test pinning the finding path and severity, plus the exit-code behavior.
4. No false positives on this repository: `tests/test_audit_dogfood.py` must stay `Shielded`.

Do not mark the dogfood test skip or xfail. If a new rule lowers the repository score, fix the rule or the finding, not the gate.

### C. Policy Packs (`packs/`)

Start from the template and rules in [`docs/policy-packs.md`](./docs/policy-packs.md). Every pack must:

- Validate against the pack schema.
- Merge deterministically into `--generate` drafts; pack constraints win over heuristic entries.
- Pass the `tests/test_packs.py` sweep (schema + zero-warning lint over the fixture corpus).
- Be mirrored into `src/scyvera/packs/` as wheel data, byte-for-byte.

### D. Implementations (`implementations/<framework>/<name>/`)

```text
implementations/
└── <framework>/
    └── <name>/
        ├── contract.yaml    # Mandatory machine-readable contract
        ├── README.md        # Documentation with a ## Contract section
        └── <source files>   # workflow.json, Python files, or graph definitions
```

Validate and conformance-check before opening a PR:

```bash
scyvera validate implementations/<framework>/<name>/contract.yaml
scyvera lint implementations/<framework>/<name>/contract.yaml
scyvera check implementations/<framework>/<name> --tier 1
```

Tier 1 adapters never import or execute the target: n8n is parsed as JSON, LangGraph as Python `ast`. New framework adapters implement `Tier1Adapter` in `conformance.py` and add a fixture-driven test.

### E. Domain-neutral examples (`examples/v1.1/`)

Reference contracts illustrating governance patterns across education, research, finance, healthcare, and software. Every example must validate cleanly against `schemas/v1.1/contract.schema.json`, and the repository-wide script must stay green:

```bash
python scripts/validate_contracts.py
```

### F. Specification RFCs (`rfcs/`)

Proposed changes to the contract model follow the RFC process:

1. Open an issue tagged `rfc` to discuss motivation and trade-offs.
2. Submit a formal RFC document in `rfcs/` following the numbered template.
3. Include at least one worked example proving the proposed field or change.
4. Note backward compatibility explicitly — additive changes are preferred, and old contracts must keep validating.

### G. Documentation (`README.md`, `docs/`, `CONTRIBUTING.md`)

Docs are part of the product. When behavior changes, update the affected page in the same PR. In particular:

- `docs/roadmap.md` gets a shipped note on the task row.
- `CHANGELOG.md` gets a section under `[Unreleased]`.
- CLI help text and `--help` output must match the documented exit codes.

---

## ✅ PR Review Checklist

Before opening a pull request, confirm:

- [ ] `pytest tests/ -q` passes locally on at least one OS.
- [ ] `scyvera audit . --fail-under 90` exits `0` (the dogfood gate).
- [ ] New CLI behavior has tests for `0`, `1`, and `2` exit codes.
- [ ] Engines print nothing and write nothing to the scanned tree.
- [ ] Serialized/hashed artifacts are deterministic (sorted, timestamp-free).
- [ ] If you changed `src/scyvera/`, `_self_manifest.json` was regenerated and is committed.
- [ ] New contracts use `contract.yaml` (never `.yml`) and pass `scyvera validate` + `scyvera lint`.
- [ ] Policy Packs pass the schema/lint sweep and are mirrored into `src/scyvera/packs/`.
- [ ] GitHub Actions additions are pinned by full commit SHA with a version comment, and jobs declare least-privilege `permissions:`.
- [ ] No real credentials, tokens, or personal data anywhere in the diff.
- [ ] `CHANGELOG.md` and the relevant `docs/` page are updated.
- [ ] Commit messages follow conventional style (`feat:`, `fix:`, `test:`, `docs:`, `ci:`, `refactor:`).
- [ ] Branch is based on current `main` (rebase rather than merge commits if needed).

Windows/macOS contributors: 6 symlink tests skip where the OS forbids link creation. That is expected; do not add new unconditional skips, and do not skip on Linux CI.

---

## 🧪 Running Things Locally

| Command | What it does |
|---|---|
| `pytest tests/ -q` | Full suite. |
| `pytest tests/test_self_check.py -v` | Package-integrity and CLI exit-code tests. |
| `pytest tests/test_audit_dogfood.py -v` | Confirms the repository stays `Shielded`. |
| `scyvera audit . --generate /tmp/contract.yaml` | Produces a draft from the repository scan. |
| `scyvera check <path> --tier 1` | Runs the static adapter for n8n or LangGraph. |
| `python -m tools.generate_self_manifest` | Regenerates the shipped manifest after `src/scyvera/` edits. |
| `python scripts/validate_contracts.py` | Validates every contract in the repository. |
| `python -m build` | Builds the wheel and sdist into `dist/`. |

To prove an install end to end:

```bash
python -m build
python -m venv /tmp/scyvera-check
/tmp/scyvera-check/bin/pip install dist/*.whl
/tmp/scyvera-check/bin/scyvera self-check
```

On Windows, use the venv's `Scripts\` directory instead of `bin/`.

---

## 🚀 Release and Attestation (Maintainers)

Releases are two-stage and must stay that way:

1. **Publish to PyPI** (`publish-pypi.yml`) runs on a `v*` tag, builds once, uploads `dist/` as the `dist` artifact, and publishes with Trusted Publishing (OIDC).
2. **Release Attestation** (`release-attest.yml`) runs after that publish succeeds, downloads the **same** `dist` artifact (never a rebuild), installs the wheel in a clean venv, regenerates the self manifest from the installed tree, gates on `scyvera self-check`, generates the CycloneDX SBOM and the RFC 0003 §C6 release manifest, signs them with Sigstore build provenance, and uploads them to the GitHub Release.

`release-attest.yml` also has a `workflow_dispatch` dry-run path for branch validation; it runs the same generation and signing steps and skips the release upload.

Rules for maintainers:

- Never attest a rebuild. The published and attested wheels must be byte-identical by construction.
- Never push a tag with a red matrix.
- Never force-push a release branch.
- If the workflows change, verify both parse as YAML and that every `uses:` is a 40-character commit SHA with a dated version comment.

---

## 🐛 Reporting Issues

Found a bug or have an idea? Open an [Issue](https://github.com/Skull-boy/agent-contracts/issues) describing:

- What happened vs. what you expected.
- Steps to reproduce, with a sample contract or code.
- Environment: OS, Python version, and `scyvera` package version (`scyvera self-check` reports the installed version).

---

## 🔒 Security Vulnerability Reporting

If you discover a security vulnerability or accidental credential exposure, **do not open a public issue**. Follow the coordinated disclosure process in [`SECURITY.md`](./SECURITY.md) — report privately through GitHub Security Advisories so it can be mitigated before publication.

---

## 🧪 Synthetic Fixture Policy (audit / scanner tests)

Scyvera's audit engine is tested against **intentionally dangerous-looking fixture material** under `tests/fixtures/audit/` — fake committed secrets, destructive shell commands, broad CI permissions. This is deliberate: a security scanner must prove its detectors fire, and those fixtures are the proof.

Rules for anyone adding or touching fixture material:

- Fixture secret values must be **non-usable synthetic strings**: dashed leet-style words (e.g. `API_KEY=H3llo-Th1s-1s-Dummy-V4lu3`), never credential-format prefixes (`sk_`, `AKIA`, `ghp_`, `Bearer`, JWT shapes) and never live-pattern values.
- The path `tests/fixtures/audit/**` is **scanner-ignored by configuration**. Two places must agree:
  - **Repository**: [`.gitguardian.yaml`](./.gitguardian.yaml) excludes the path for local `ggshield` runs, and GitHub Push Protection must allowlist it in repository settings.
  - **GitGuardian dashboard**: the GitHub App reads exclusions from the dashboard, not from `.gitguardian.yaml`, so `tests/fixtures/audit/**` must also be added to the repository's path exclusions there. This is documented policy, not an oversight — never "fix" a scanner warning by weakening the fixture.
- If a real scanner still flags a new fixture value, resolve it via the project's scanner configuration; do not delete positive test cases.
- For real-world examples elsewhere in the repo (`examples/`, `implementations/`), plain placeholders (`changeme`, `${ENV_VAR}`) are preferred.

---

## 📄 Code of Conduct

Be respectful, be constructive, and assume good faith. This is a collaborative open-source community. Harassment, personal attacks, and credential leaks are not acceptable.
