# Policy Packs

A Policy Pack is a local, facts-only YAML file that bounds a contract draft
produced by `scyvera audit --generate`. Packs contain no logic and are never
fetched over the network: the CLI loads them from the installed
`packs/<name>.yaml` copy only (RFC 0004 §6, §10.2).

A pack is a **starting boundary, not an audit result**. It does not scan a
repository, does not replace `scyvera audit`, and does not certify anything.
It lets a domain start from a named boundary instead of a blank draft.

## Usage

```bash
scyvera audit . --generate contract.yaml --pack github-safe
```

`--pack` requires `--generate`, because the pack is applied to the draft. The
generated draft is a normal v1.1 contract: `scyvera validate contract.yaml` and
`scyvera lint contract.yaml` both pass with zero warnings.

```text
Draft contract written to contract.yaml (validate with: scyvera validate contract.yaml).
```

## Golden packs

| Pack | Domain | Use it for |
|---|---|---|
| `dev-agent` | software | Coding agents working inside a local repository |
| `github-safe` | software | Coding agents working in a git repository |
| `finance-ops` | finance | Agents that prepare or execute financial operations |
| `research-assistant` | research | Literature and data research assistants |
| `email-triage` | business | Agents that triage shared inboxes |
| `devops-safe` | software | Agents that operate CI, containers, and deploys |

## File format

Packs live at `packs/<name>.yaml` in the repository and ship in the wheel as
package data under `src/scyvera/packs/` (the same mirroring convention used by
`schemas/`). Both copies must be byte-identical; `tests/test_packs.py` enforces
that.

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

Unknown keys are rejected rather than ignored, so a typo fails CI instead of
silently weakening a boundary.

## Merge semantics

When a pack is applied to a generated draft:

- **Pack wins on conflict.** A type in `irreversibly_forbidden` is forced to
  `irreversible: true`, and any approval entry for that effect is removed (the
  RFC pins "no approvals offered"). A type in `requires_approval` is forced to
  `required: true`, adding the approval entry when absent.
- **Finding-only extras are appended.** Entries the pack does not mention are
  kept exactly as the audit derived them.
- **Domain comes from the pack.** The draft's `domain` is the pack's `domain`.
- **`cap_side_effects_per_window` becomes a v1.1 constraint.** It is written
  as `constraints: [{type: side_effects_per_window, maximum: N}]`, using the
  v1.1 `constraints` section rather than a schema extension.

## Adding a pack

1. Copy an existing file under `packs/` to `packs/<name>.yaml`.
2. Fill in `pack`, `version`, `domain`, `description`, `derive`, and
   `construction`, keeping `contract_version: "1.1"`.
3. Copy the file to `src/scyvera/packs/<name>.yaml` so it ships in the wheel.
4. Run:

   ```bash
   pytest tests/test_packs.py -q
   ```

   The sweep loads the pack, applies it to every fixture corpus, writes the
   draft, and requires Tier 0 schema validation plus Tier 2 lint with zero
   warnings. A new golden pack also needs an entry in `GOLDEN_PACK_NAMES` in
   `tests/test_packs.py`.
