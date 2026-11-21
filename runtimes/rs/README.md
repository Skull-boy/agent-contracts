# scyvera-rs

Native Rust runtime for **Agent Contracts**: the RFC 0005 provisional-contract
model, a default-deny gate with approval boundaries, the RFC 0003 §C4 trace with
the additive `provisional` field, and the shared conformance-vector runner.

It is a native implementation, not a binding. Nothing here spawns Python,
embeds an interpreter, or shells out to the `scyvera` CLI. The Python package
remains the reference semantics; when the two disagree, Rust is wrong unless an
accepted RFC change says otherwise.

```console
$ cargo install scyvera-rs
$ scyvera-rs vectors --root ../../vectors
PASS  33 vectors (suite-version 1): 33 passed, 0 failed
      contract-model: 11 passed, 0 failed
      gate-decision: 13 passed, 0 failed
      trace-roundtrip: 9 passed, 0 failed
```

## Scope

In scope — the cross-runtime surface pinned by
[RFC 0005 §6](../rfcs/0005-provisional-contracts.md):

| Capability | Command / API |
|---|---|
| Contract model for specification versions 1, 1.1, 1.2 | `validate`, `scyvera_rs::contract` |
| Load modes: full vs draft, typed refusal of a provisional contract in full mode | `scyvera_rs::contract::load_contract_file` |
| Default-deny gate: declaration → approval → guardrails, draft-mode irreversibility | `gate`, `scyvera_rs::enforcer` |
| Trace JSONL: fail-closed parse, canonical bytes | `scyvera_rs::trace` |
| Conformance vectors: all three categories, pinned suite version | `vectors` |

Out of scope by design, and stated rather than faked:

- **`audit`, `lint`, `check`** — the AUxxx rule registry, the ACxxx semantic
  lint rules, and the conformance-tier adapters are Python-owned
  (RFC 0005 §6.10 pins audit out of the cross-runtime suite). The Rust audit
  binary is the separate, deferred **GE-6** lane. `scyvera-rs audit` exits `2`
  with that explanation instead of pretending to audit.
- **Registry, re-seal, and promotion orchestration** — Python-only in v1
  (RFC 0005 §6.10, §8 Q5).
- **Policy packs** — Python-only.

## Install

```console
cargo install scyvera-rs
```

MSRV: **Rust 1.85**, edition 2021. CI builds and tests both `1.85.0` and current
stable.

The crate has **one direct dependency**: [`yaml-rust2`](https://crates.io/crates/yaml-rust2)
with `default-features = false`. JSON parsing, canonical JSON/JSONL output,
SHA-256, ISO-8601 formatting, and the JSON Schema subset the contract schemas
use are implemented in this crate. `cargo tree --depth 1` is asserted in CI.

## Usage

### Validate a contract

```console
$ scyvera-rs validate contract.yaml
PASS  contract.yaml
```

Exit codes: `0` valid, `1` findings (schema/validation), `2` usage or IO.

### Gate one action

```console
$ scyvera-rs gate --contract contract.yaml --mode full \
    --action github:issues:read --action-type permission
ALLOWED  github:issues:read
       Action 'github:issues:read' matched declared contract specification.
```

```console
$ scyvera-rs gate --contract contract.yaml --mode full \
    --action force_push --action-type side_effect
DENIED  force_push
       Contract violation: Action 'force_push' is not declared in 'contract.yaml'. ...
```

A pending approval exits `1` and prints the approval reason. `--approve` grants a
manual approval for that action before the gate is evaluated; `--audit` prints
every audit entry (decision, action, type, reason).

### Run the shared vectors

```console
$ scyvera-rs vectors --root ../../vectors
$ scyvera-rs vectors --root ../../vectors --category gate-decision
$ scyvera-rs vectors --root ../../vectors --json
```

`--json` emits the canonical RFC 0005 §6.8 result object: sorted keys, compact
separators, one trailing newline. Exit codes: `0` all pass, `1` at least one
failure, `2` suite configuration or usage error (including a suite-version
mismatch — a runtime must never run a subset of a newer suite).

The runner reads `vectors/suite-version` first and refuses to run if it does not
equal the pinned `1`. It never writes to `vectors/`, never imports a target, and
rejects symlinked suite paths, non-canonical vector files, unknown categories,
duplicate IDs, and unknown envelope keys.

## Contract model

- **Versions**: `1`, `1.1`, `1.2`, resolved like the Python validator: explicit
  `contract_version` first, then `version`, then v1.
- **Provisional**: `provisional` is boolean-only. On v1 it is rejected even when
  `false`; on v1.1 and v1.2 it is accepted. `draft` mode loads only provisional
  contracts; `full` mode refuses one with `ProvisionalContractError` (message
  names the promotion ritual).
- **Lifecycle defaults**: v1.1/v1.2 contracts without a `lifecycle` block gain
  `{mode: request-response, initiation: human-only, resumability: stateless}`
  after validation. v1 contracts are unchanged.
- **Wildcards**: `*`, `all`, and `any` are refused in `permissions` (including
  object-form values and action lists) and `side_effects` (Threat T7).
- **Paths**: `.yml` is rejected; a contract that resolves outside the directory
  it was addressed in is refused (T14 symlink escape).
- **Identity**: the SHA-256 of the exact bytes read at load time is pinned and
  re-checked before every gate decision. Removal, modification, or a post-load
  path swap denies the action with a `tampered` reason.

## Gate semantics

Pipeline, in order: **integrity → declaration → approval → guardrails →
allowed**.

- Undeclared actions are denied; `read` is an alias for `permission`.
- Approval points and required approvals raise `ApprovalPendingError` until
  `approve` is called for that action.
- Draft mode adds exactly one rule: an irreversible side effect requires human
  approval even when the draft declares none (RFC 0005 §4.2, anchor A2).
  Irreversibility uses the same matching algorithm as the gate, then a
  token-level phrase check (`delete`, `destroy`, `drop`, `truncate`, `purge`,
  `erase`, `wipe`, `force push`, `remote execution`, `publish`, `deploy`,
  `merge`, `close`, `transfer`, `payment`, `overwrite`, `revoke`).
- Guardrails (`rate_limit`, `budgets`, `fail_closed`) are per-enforcer-instance
  counters, exactly like the Python reference. They are not a distributed quota.
- Every decision is appended to an audit trail carrying the decision, action
  type, reason, contract field reference, and the draft-mode `provisional` flag.

## Trace

`TraceLog::from_jsonl` is fail-closed: unknown or missing fields, a non-boolean
`provisional`, a non-hex `hash_of_contract`, a non-ISO-8601 `timestamp`, or an
unknown `result` is rejected with `TraceError`. Serialization is canonical —
sorted keys, compact separators, UTF-8, one object per line, newline-terminated —
and a full-mode entry omits `provisional`, so pre-RFC-0005 trace bytes are
unchanged.

## Documented differences from the reference implementation

These are deliberate, narrow, and fail closed:

| Area | Python reference | scyvera-rs |
|---|---|---|
| YAML booleans | PyYAML is YAML 1.1, so `yes`/`on` are `true` | YAML 1.2 core schema; `yes`/`on` stay strings, which then fail schema validation |
| Duplicate YAML keys | last value wins | last value wins (same) |
| JSON Schema coverage | full draft-2020-12 validator | the closed keyword subset the contract schemas use; an unknown keyword or unsupported `pattern` is a validation error, never a silent pass |
| Schema location | `schemas/<version>/` | copied byte-for-byte into this crate; a monorepo test asserts equality |
| `lint`/`check`/`audit` | full engines | not implemented; exit `2` with an explanation (audit is GE-6) |

## Conformance

- Suite version: **1** (33 vectors: 11 contract-model, 13 gate-decision,
  9 trace-roundtrip).
- The CI job `scyvera-rs` reads `vectors/suite-version`, compares it to the
  pinned `1`, and exits `2` on drift before running anything.
- RFC 0005 §6.7 canonical codes are produced by `Error::code()`:
  `ContractViolationError`, `ApprovalPendingError`, `ProvisionalContractError`,
  `ContractValidationError`, `TraceError`, `GuardrailViolationError`. Integrity
  denials map to `ContractViolationError` with a `tampered` message, per
  `vectors/CHANGELOG.md`.

## Development

```console
$ cargo fmt --check
$ cargo clippy --all-targets -- -D warnings
$ cargo test
$ cargo run -- vectors --root ../../vectors
```

`cargo test` includes the full 33-vector suite plus unit and integration tests
for the contract model, gate, trace, and CLI exit codes.

## License

MIT. See [LICENSE](./LICENSE).
