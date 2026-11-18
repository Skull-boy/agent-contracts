# scyvera-ts

**Native TypeScript runtime for Agent Contracts — v0.1.0 (pre-release).**

The npm package is **`@scyvera/scyvera-ts`** (scoped, public). The installed
command remains **`scyvera-ts`**: the `bin` mapping is independent of the
package name, so every `npx scyvera-ts ...` example below stays valid.

`scyvera-ts` implements the contract model, the default-deny gate, the trace
JSONL schema, and the conformance-vector runner described by
[RFC 0005](../../rfcs/0005-provisional-contracts.md) and
[RFC 0003 §C4](../../rfcs/0003-harness-distribution-eval-and-integrity.md).
It is a **native** implementation: it never spawns Python, shells out to the
PyPI package, or embeds a Python interpreter/WASM build.

The Python package in this repository remains the reference semantics. This
runtime is accepted only by passing the same shared corpus at the same pinned
suite version ([`vectors/`](../../vectors/README.md)).

## Status and scope (no overclaim)

`0.1.0` means **pre-release honesty**: the package has not proven itself
against a stable published vector suite long enough to be `1.x`. It is
implemented against suite version **1** (33 vectors).

### Implemented

- **Contract model**: v1, v1.1, and v1.2 YAML loading with the RFC 0005
  `provisional` rules (boolean-only; rejected on v1 even as `false`; accepted
  on v1.1/v1.2), lifecycle defaults, wildcard refusal, and a fail-closed
  schema check for the shapes the runtime depends on.
- **Load modes**: `full` (default) refuses `provisional: true` with a
  `ProvisionalContractError` naming promotion; `draft` accepts only
  provisional contracts and refuses a non-provisional contract as
  `ContractValidationError`.
- **Default-deny gate**: integrity → declaration → approval → guardrails →
  allowed. Undeclared actions are denied. Declared reversible side effects are
  allowed. In draft mode, irreversible actions (declared `irreversible: true`
  or the RFC 0005 §4.3 closed verb set) default-deny behind an approval gate
  even when the contract declares no approvals. Full mode keeps its pre-RFC
  T8 behavior.
- **Guardrails (v1.2 subset)**: `fail_closed`, per-enforcer sliding
  `rate_limit`, and `side_effects_per_window` budgets.
- **Trace JSONL**: RFC 0003 §C4 fields plus the additive RFC 0005 §4.4
  `provisional` field, emitted only when `true`; strict parse rejection of
  unknown fields, non-boolean `provisional`, bad hashes, bad timestamps, and
  unknown results. Canonical output is sorted-key, compact, newline-terminated.
- **Vector runner**: fail-closed suite loading (version, categories, envelope,
  canonical JSON, duplicate IDs) and the canonical RFC 0005 §6.8 result object.

### Not implemented (honest limits)

- **No audit rules** (`AU-*`), no `scyvera audit`, no policy packs, no
  generator/inference, no registry, no promotion CLI, no re-seal. RFC 0005
  §6.10 keeps those out of the cross-runtime corpus; they remain Python-owned.
- **No JSON-Schema engine**: the schema checker covers the constructs used by
  the bundled v1/v1.1/v1.2 shapes (types, required, `anyOf`/`oneOf`, `const`,
  `enum`, `if`/`then`, `properties`, `additionalProperties`, `items`,
  `pattern`, length/minimum bounds, `not`). A future schema construct must be
  added explicitly; unknown constructs are not silently ignored when they
  would affect a contract field the runtime reads.
- **No distributed quotas**: guardrail counters are per enforcer instance and
  per process, matching the Python honest limitation.
- **No signed reviewer identity**: promotion is not implemented at all here.
- **No cryptography beyond SHA-256** (`node:crypto`) for contract integrity.
- **No T1 lifecycle detection**: draft mode is a contract-status mode, not a
  lifecycle mode (RFC 0005 §9.8).
- **No Rust runtime**: `scyvera-rs` is a separate lane.

## Install and build

Not published yet. Once published, install the scoped package:

```sh
npm install @scyvera/scyvera-ts
npx scyvera-ts --version        # the installed command stays unscoped
```

Until then, build from this directory:

```sh
npm ci
npm run build
npm test
npm run vectors        # runs ../../vectors at the pinned suite version
```

Requires Node >= 20 and ESM.

## CLI

```text
scyvera-ts vectors [--root <dir>] [--category <name>] [--json]
scyvera-ts gate --contract <file> --mode <full|draft> \
  --action <name> --action-type <permission|side_effect|read>
```

- `vectors` prints a PASS/FAIL summary with per-category counts. `--json`
  prints the canonical RFC 0005 §6.8 result object.
- `gate` loads a contract, runs one gated action, prints the decision and the
  audit reason, and exits `0` when allowed, `1` when denied/pending.
- Exit codes everywhere: `0` pass, `1` failure/denial, `2` usage or suite
  configuration error. The TS CLI mirrors the Python exit-code constitution.

## Repository location

This runtime lives in the **same repository** as `runtimes/ts/`, not in a
separate repository. The decision and rationale are recorded on the GE-4 row
in [`docs/roadmap.md`](../../docs/roadmap.md): one RFC source, `vectors/`
reachable by relative path, and differential checks in one CI.

## YAML dependency

The only runtime dependency is [`yaml`](https://eemeli.org/yaml/) pinned to
`2.9.1`. Node has no standard YAML parser; `yaml` is a zero-dependency,
actively maintained YAML 1.2 implementation. `js-yaml` was the alternative; it
brings a second runtime dependency and a larger parser surface for no
additional capability here.

## Fixtures

The demonstration contract under `demo/` is intentionally provisional and is
used by the README/demo command. It is not shipped in the npm package
(`files` includes `dist/src`, docs, and license only).
