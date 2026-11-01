# Contributing to Agent Contracts

Thanks for considering a contribution — this repository grows through community-submitted contracts, framework reference implementations, specification proposals, and governance tooling in `scyvera`.

---

## 📌 Ground Rules

- **Never push directly to `main`.** All changes — new implementations, python code, doc updates, schemas — go through a feature branch and a pull request. `main` only receives merges after review.
- **Canonical naming is `contract.yaml`** — never use `contract.yml`. The loader and schema reject `.yml` extensions.
- **Every implementation declares a Contract** — any workflow or agent implementation must include a valid `contract.yaml` alongside its code or workflow definition.
- **Run the test suite** — all Python tests must pass (`pytest tests/ -v`).
- **No real credentials, tokens, chat IDs, webhook URLs, or personal data** in anything you commit. Use clear placeholders (`REPLACE_ME`, `YOUR_KEY`, etc.).

---

## 🧭 Contribution Workflow

### 1. Fork and Clone the Repository
Click **Fork** on GitHub, then clone your fork locally:
```bash
git clone https://github.com/<your-username>/agent-contracts.git
cd agent-contracts
```

### 2. Set Up Development Environment
Install development dependencies:
```bash
pip install -e ".[dev]"
```

Verify that the test suite passes:
```bash
pytest tests/ -v
```

### 3. Create a Feature Branch
Always branch off `main`:
```bash
git checkout -b feature/<short-description>
```
Examples:
```bash
git checkout -b feature/langgraph-research-assistant
git checkout -b feature/enforcer-metrics
```

### 4. Areas to Contribute

#### A. Python Package (`src/scyvera/`)
If improving or extending the core governance layer:
- **`enforcer.py`**: Runtime enforcement engine (`ContractEnforcer.load`, `ContractEnforcer.from_declaration`, `@gate`).
- **`gateway.py`**: Gated gateway clients (`BaseGateway`, `GitHubGateway`, `QdrantGateway`). Remember: all raw client imports and credentials must live strictly inside `gateway.py` to pass `.github/workflows/lint-gateway.yml`.
- **`registry.py`**: Versioned, append-only contract registry (`ContractRegistry`).
- **`validator.py` & `linter.py`**: Structural JSON Schema validator and Tier 2 semantic linter.
- **`cli.py`**: Command-line interface (`scyvera validate`, `scyvera lint`, `scyvera init`).

#### B. Implementations (`implementations/<framework>/<name>/`)
Structure new agent or workflow implementations like this:
```text
implementations/
└── <framework>/
    └── <name>/
        ├── contract.yaml    # Mandatory machine-readable contract
        ├── README.md        # Documentation with ## Contract section
        └── <source files>   # workflow.json, python files, or graph definitions
```
Validate your contract with the CLI:
```bash
scyvera validate implementations/<framework>/<name>/contract.yaml
scyvera lint implementations/<framework>/<name>/contract.yaml
```

#### C. Domain-Neutral Examples (`examples/v1.1/`)
Reference contracts illustrating governance patterns across education, research, finance, healthcare, etc. Every example must validate cleanly against `schemas/v1.1/contract.schema.json`.

#### D. Specification RFCs (`rfcs/`)
Proposed changes to the contract specification model follow the RFC process:
1. Open an issue tagged `rfc` to discuss motivation and trade-offs.
2. Submit a formal RFC document in `rfcs/` following the numbered template.
3. Include at least one worked example proving the proposed field or change.

---

## ✅ PR Review Checklist

Before opening a pull request, confirm:
- [ ] All tests pass: `pytest tests/ -v`
- [ ] Gateway lint passes (no raw SDK imports outside `gateway.py`): verify against `tests/test_gateway.py`
- [ ] All `contract.yaml` files pass schema validation (`scyvera validate <path>`)
- [ ] Canonical naming: every contract uses `contract.yaml` (never `.yml`)
- [ ] No real credentials, tokens, or personal data anywhere in the diff
- [ ] Commit messages follow conventional commit style (`feat:`, `fix:`, `docs:`, etc.)
- [ ] Branch is up to date with `main`

---

## 🐛 Reporting Issues

Found a bug or have an idea? Open an [Issue](https://github.com/Skull-boy/agent-contracts/issues) describing:
- What happened vs. what you expected
- Steps to reproduce, with sample contract or code
- Environment (Python version, OS, `scyvera` package version)

---

## 🔒 Security Vulnerability Reporting

If you discover a security vulnerability or accidental credential exposure in an example, please **do not open a public issue**. Contact the maintainer directly so it can be mitigated responsibly.

---

## 🧪 Synthetic Fixture Policy (audit / scanner tests)

Scyvera's audit engine is tested against **intentionally dangerous-looking fixture material** under `tests/fixtures/audit/` — fake committed secrets, destructive shell commands, broad CI permissions. This is deliberate: a secret-scanner project must prove its detectors fire, and those fixtures are the proof.

Rules for anyone adding or touching fixture material:

- Fixture secret values must be **non-usable synthetic strings**: dashed leet-style words (e.g. `API_KEY=H3llo-Th1s-1s-Dummy-V4lu3`), never credential-format prefixes (`sk_`, `AKIA`, `ghp_`, `Bearer`, JWT shapes) and never live-pattern values.
- The path `tests/fixtures/audit/**` is **scanner-ignored by configuration** (GitHub Push Protection allowlist + GitGuardian path exclusion). This is documented policy, not an oversight — never "fix" a scanner warning by weakening the fixture.
- If a real scanner still flags a new fixture value, resolve it via the project's scanner configuration; do not delete positive test cases.
- For real-world examples elsewhere in the repo (`examples/`, `implementations/`), plain placeholders (`changeme`, `${ENV_VAR}`) are preferred.

---

## 📄 Code of Conduct

Be respectful, be constructive, and assume good faith. This is a collaborative open-source community.
