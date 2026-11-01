> [!NOTE]
> **RFC Status: Proposed (implementation to start on `feat/scyvera-audit`)**
> This RFC specifies the **adoption funnel**: `scyvera audit`, the Blast Radius Report, and Policy Packs. It is the implementation plan for Move 1–3 of the positioning upgrade, built directly on top of the Tier 1 static-analysis work planned in [`docs/roadmap.md`](../docs/roadmap.md) (M2.2) and the v1.1 contract schema.
>
> Author: Scyvera Core Team / Agent Contracts Working Group
> Created: 2026-10-31
> Target: `scyvera` 1.3.0

---

# RFC 0004: `scyvera audit` — Auto-Contracts, Blast Radius Reports & Policy Packs

## 1. Problem Statement

Scyvera's governance is strong but requires the user to already understand the contract model. The result: people who would benefit never reach the value, because the first step is authoring a YAML document. The fix is to invert the funnel: **the contract is generated from the repo as a byproduct of analysis**, and the first artifact a new user receives is not a schema explanation — it is a shock-and-clarity report of what their agent environment is currently capable of, plus a one-line path to bound it.

Three artifacts, one command each:

1. `scyvera audit .` → Blast Radius Report (terminal, JSON, badge markdown) + exit code suitable for CI.
2. `scyvera audit . --generate contract.yaml` → a **schema-valid v1.1 contract draft** derived from findings.
3. `scyvera audit . --pack github-safe` → the draft **bound by a community Policy Pack**, not raw heuristics.

This replaces "explain the spec" with "here is what your repo lets an agent do — sign here to bound it."

## 2. CLI Contract (UX is the product — pinned exactly)

```text
scyvera audit [path]

        Scans [path] (default `.`) with the AUxxx rule registry and prints the
        Blast Radius Report. With no flag, reads-only: never writes any file.

Flags:
  --json                       Emit machine-readable report (report_version: 1)
  --generate <contract.yaml>   Write a v1.1 contract draft derived from findings
  --pack <name>                Apply a Policy Pack to the draft (implies --generate)
  --fail-under <score>         Exit 1 if score < threshold (CI gate mode)
  --stamp                      Include generated_at timestamp (default: omit for
                               deterministic output; timestamps break diffing)
  --force                      Allow --generate to overwrite an existing file
```

- Output conventions follow the existing CLI (`PASS` / `WARN` / `FAIL` prefixes; exit codes: `0` clean, `1` findings or `--fail-under` threshold breach, `2` usage/IO error).
- Default human output (pinned format, score band first — the number people screenshot):

```text
PASS  . — exploit risk none (score 100/100)
```
or, with findings:

```text
WARN  .
      Blast Radius: 71/100 (Exposed)
      Scanned 214 files (2 manifests, 3 workflow files, 41 source files)

      CRITICAL  [AU-NET-001] install-script execution (curl … | sh)
                .github/workflows/release.yml:52
      HIGH      [AU-SH-001] recursive delete in shell script
                scripts/clean.sh:8
      MEDIUM    [AU-NET-002] outbound network calls in source (requests)
                src/foo/client.py + 2 more

      With a contract: force-push -> requires approval; .env -> unread;
      npm publish -> forbidden.  Run with --generate to draft one.
```

- **Windows/POSIX parity**: path separators are normalized to `/` in reports; case-sensitive rule matching stays per-OS for shell scripts (`.ps1` for Windows PowerShell idioms, `.sh` for POSIX).
- **Performance guarantees** (non-MVP bar): skip list `.git .venv node_modules dist build .pytest_cache .tox .release-test brag-output .assurance`; file-size cap of 1 MB per scanned file; binary sniff (NUL byte in the first 8 KB → skipped, counted in `files_skipped`); symlinked targets are refused with a T14-consistent error; total scan bounded (no unbounded recursion, follows only 1 level of nested repo root symlink).

## 3. AUxxx Rule Registry (the analysis core)

Rules live in `src/scyvera/audit_rules.py` as a flat, append-only registry — the same pattern as the ACxxx linter taxonomy. Each rule is a pure function over `(path, text, filename)` returning zero or more findings. No shared mutable state; scanners are per-file so the registry is trivially testable.

```python
@dataclass(frozen=True)
class Finding:
    rule_id: str          # "AU-NET-001"
    severity: str         # "critical" | "high" | "medium" | "low"
    title: str
    detail: str
    path: str             # workspace-relative, "/"-separated
    line: int | None
    suggestion: Mapping[str, Any]   # draft-contract fragment (see §5)
```

### Launch registry (v1 scope)

| Rule ID | Trigger | Severity | Draft suggestion (fragment) |
|---|---|---|---|
| `AU-ENV-001` | `.env` / `.env.*` file present | medium | `{resource: "dotenv_secrets", type: "secrets", access: "read"}` in `resources` |
| `AU-ENV-002` | secret-looking key in a committed env file (e.g. `KEY=…` with high-entropy value) | critical | `permissions: ["secrets:read"]` + approval entry |
| `AU-SH-001` | destructive FS op (`rm -rf`, `del /s`, `Remove-Item … -Recurse -Force`) | critical | `side_effects: [{type: "file_delete", resource: "workspace", irreversible: true}]` |
| `AU-GIT-001` | `git push --force` / `reset --hard` / `branch -D` | high | permission `git_ref:write` + approval entry |
| `AU-NET-001` | piped install (`curl … \| sh`, `iwr … \| iex`) | critical | side effect `remote_execution` (irreversible) |
| `AU-NET-002` | outbound client libs (`requests`, `httpx`, `urllib`, `socket`, `aiohttp`, `fetch`) | medium | capability note + suggested `network:egress:<host>` permissions |
| `AU-CI-001` | workflow with `permissions: write-all` or secret in `run:` | high | side effect `ci_deploy_write` |
| `AU-CI-002` | deploy/publish job detected (`npm publish`, `twine upload`, `docker push`, `kubectl apply`) | high | permission `registry:publish` + approval entry |
| `AU-DOC-001` | Dockerfile privileged / risky volume mounts | high | side effect `host_mount` |
| `AU-N8N-001` | n8n `workflow.json` with `httpRequest` / email / write-node types | medium | side effect `external_api_write` |
| `AU-DEP-001` | ≥ 25 unpinned dependencies in a manifest | low | observability suggestion |

- Registry is data, not code paths: adding a rule = adding an entry + tests; no CLI changes.
- False-positive control is a **QA requirement**, not a nice-to-have: every rule ships with a positive fixture, a negative fixture, and a "no finding on Scyvera's own repo invariants" test (dogfooding, §7).

## 4. Blast Radius Report (schema `report_version: 1`)

Deterministic first, shareable second:

- **Scoring**: `score = 100 − min(100, Σ severity_weight)`, weights: critical 15, high 8, medium 3, low 1. Bands: ≥ 90 `Shielded`, 70–89 `Controlled`, 40–69 `Exposed`, < 40 `Unbounded`.
- Order of findings in all output: severity desc, then rule_id, then path — never file-system order (determinism across runs and machines).
- No timestamps unless `--stamp`; both variants serialize identically otherwise.
- `--json` emits exactly:

```json
{
  "report_version": 1,
  "target": ".",
  "score": 71,
  "band": "Exposed",
  "stats": {"files_scanned": 214, "files_skipped": 9, "findings": {"critical": 1, "high": 1, "medium": 1, "low": 0}},
  "findings": [ { "rule_id": "…", "severity": "…", "title": "…", "detail": "…", "path": "…", "line": 52, "suggestion": {} } ],
  "draft_available": true,
  "packs_suggested": ["github-safe"]
}
```

- Badge markdown (`--badge`) emits a shields.io snippet pinned to the band, not the raw score (avoids churn):

```markdown
[![Blast Radius: Exposed](https://img.shields.io/badge/blast%20radius-Exposed-red)](scyvera)
```

### 4.1 Scoring refinement (M2.0a.1)

Scoring now applies diminishing per-rule loads instead of a flat sum: findings are grouped by `rule_id` and the first three occurrences contribute `base × 1.00`, `base × 0.25`, and `base × 0.10` respectively, while every further occurrence contributes zero, so one rule can add at most `1.35 × base`. The reported score is `max(0, 100 − ceil(total_load))` with the bands above unchanged, and `AU-SH-001`, `AU-GIT-001`, and `AU-NET-001` fire only in executable contexts (`*.sh`, `*.ps1`, `*.bat`, `*.cmd`, `Dockerfile*`, workflow `run:` values, and Makefile/justfile content), never in prose, arbitrary YAML/JSON, or documentation. Findings whose normalized path starts with `tests/fixtures/` stay in the report but carry `scored: false` and contribute nothing to the score, band, or `stats.findings`, which now counts scored findings only. The scan skip list also includes `.agents` so installed skill tooling is never audited.

## 5. Contract Draft Generation (`--generate`)

- Produces a v1.1 contract (version defaults seen in `cli.py run_init`) whose `resources`, `permissions`, `side_effects`, and `approvals` sections are **derived from findings' suggestion fragments**, deduplicated, and ordered deterministically.
- `system.name` = repo directory name; `domain` = `"software"` unless `--pack <name>` supplies the pack's domain; `risk.level` derived from the worst dominant severity.
- **Hard QA rule**: every generated draft must PASS `validate_contract()` on v1.1 and `lint_contract()` with zero warnings. This is enforced by a test that generates contracts for every fixture corpus and runs both — the generator cannot drift from the schema without tests failing (dogfooding discipline: the draft is a Scyvera release artifact quality-wise).
- `--generate` refuses to overwrite an existing contract without `--force` (same convention as `init`).

## 6. Policy Packs (the community artifact)

- Location: `packs/<name>.yaml` in the repository (also shipped in the wheel via `package-data`, mirroring `schemas/`).
- Pack structure (facts only, no logic):

```yaml
pack: github-safe
version: "1.0.0"
domain: software
description: Boundaries for coding agents working in a git repository.
derive:
  irreversibly_forbidden:      # mapped to irreversible side effects, no approvals offered
    - file_delete
    - remote_execution
  requires_approval:           # mapped to approval entries
    - git_ref_write
    - ci_deploy_write
  cap_side_effects_per_window: 10
construction:
  contract_version: "1.1"      # packs are validated against the matching schema
```

- `--pack <name>` applies pack `derive.*` and `construction.cap_*` to the generated draft (merging findings-derived entries with pack constraints; pack wins on conflict, finding-only extras appended).
- **Every pack must pass Tier 0 + Tier 2 lint in CI** (a `tests/test_packs.py` sweep) — this turns "add a pack" into the easiest, most guided first-PR: a new contributor copies a pack template, fills it in, and CI tells them if it's valid before any review.
- Pack names are domain-recognizable, not security-guarantees: docs state clearly that a pack is a starting boundary, not an audit result.

## 7. QA Bar (what makes this not feel like an MVP)

1. **Dogfood**: `scyvera audit .` runs against the Scyvera repo itself in CI; result is asserted in a test snapshot (band must remain `Shielded` at 1.3.0 release; if drift occurs, the test fails loudly, not silently).
2. **Fixture corpus**: `tests/fixtures/audit/` contains a miniature synthetic repo (env file, shell script, workflow, python source, dockerfile, n8n json) — one per scanner — plus negative variants. Scanned against in tests via relative path resolution (same pattern as existing FIXTURE logic).
3. **Determinism test**: same corpus scanned twice produces byte-identical JSON.
4. **Cross-platform test**: synthetic repo with a `.ps1` destructive script on the Windows path style; POSIX variants for `.sh`.
5. **Schema-accuracy test**: every `--generate` result validates against v1.1 with zero lint warnings (see §5).
6. **No-write guarantee test**: default `scyvera audit` produces no file changes to the target (snapshot `git status` before/after inside a sandbox fixture).
7. **Exit-code test**: `--fail-under` gating honored for CI.

## 8. Rollout & Sequencing (M-IDs added to roadmap)

| Task | Deliverable | Gate |
|---|---|---|
| **M2.0a** | `audit_rules.py` registry + `audit.py` scan engine + JSON report + determinism + fixture corpus | §7 checks 2, 3, 6 |
| **M2.0b** | Terminal renderer + `--badge` + `--fail-under` CI gate | §7 checks 2, 4, 7 |
| **M2.0c** | `--generate` contract drafts + schema-accuracy dogfood test | §7 checks 5 |
| **M2.7** | `packs/` MVP (6 golden packs: `dev-agent`, `github-safe`, `finance-ops`, `research-assistant`, `email-triage`, `devops-safe`) + pack CI sweep + wheel packaging | §6 sweep |
| **Growth lane** | README hero rewrite + audit GIF + `/brag` launch film + showcase gallery | Post-M2.7 |

Dependencies: M2.0a–c do **not** depend on M2.1 (CLI conformance entrypoint) — they share the module layout and test conventions but run independently; the `audit` command ships before `check` is completed, on purpose (adoption-first strategy).

## 9. Non-Goals

- Not an enforcement engine change: `audit` reads and drafts, it does not gate (gating stays with `ContractEnforcer`).
- No network access, no telemetry: scans are purely local, report leaves the machine only when the user chooses to share it.
- No auto-correction of files: `--generate` writes exactly one new file (the contract draft), nothing else.
- No Python-version-specific AST analysis in v1 (regex/`pathlib` scanning is enough for rule coverage at this level); AST adapters remain the M2.1+ domain of static conformance.

## 10. Open Questions & Resolutions

1. **Q: Should findings graft `irreversible` side effects into the draft contract automatically?**
   - **Resolution**: Yes for critical severity, and only those — an audit-drafted contract should never mark a `medium` finding as irreversible; that level of constraint belongs to a pack or to the user editing the one line.
2. **Q: Should `--pack` require the pack file to exist locally, or should it fetch from GitHub?**
   - **Resolution**: v1 is local-only (no network access is a hard requirement); fetching is a later feature gated behind explicit `--from-github <org/repo>` once release attestation (RFC 0003 §C6) exists to keep the supply chain auditable.
3. **Q: Does the Blast Radius score become a stable public metric people compete on?**
   - **Resolution**: Not in v1. Badge emits band only (§4) precisely so the metric can evolve without users' badges flapping; score semantics may be revised in v2 with a documented scoring RFC.
