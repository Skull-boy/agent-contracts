# Conformance Vector Suite Changelog

One section per `suite-version`. Any vector addition, removal, or semantic
change bumps the version by one and lands here in the same commit (RFC 0005
§6.8). A semantic change to an existing vector is labelled `### Breaking` and
must name the runtimes that have to change.

## [1] - 2026-11-17

### Added

First non-empty suite (GE-3). Pins the RFC 0005 contract-model, gate-decision,
and trace-roundtrip semantics against the Python reference engine.

`contract-model` (11):

- `cm-0001-provisional-flag-valid` — `provisional: true` validates on v1.1.
- `cm-0002-provisional-false-valid` — explicit `false` validates on v1.1.
- `cm-0003-provisional-absent-valid` — an absent key validates on v1.1.
- `cm-0004-provisional-non-boolean-invalid` — a string flag is invalid.
- `cm-0005-provisional-on-v1-invalid` — v1 rejects the key.
- `cm-0006-provisional-v12-valid` — the field is allowed on v1.2.
- `cm-0007-invalid-permissions-type` — a non-array `permissions` is invalid.
- `cm-0008-draft-load-provisional` — draft mode loads a provisional contract.
- `cm-0009-full-load-provisional-rejected` — full mode raises
  `ProvisionalContractError` (anchor A1).
- `cm-0010-draft-load-non-provisional-rejected` — draft mode is not a relaxed
  mode.
- `cm-0011-full-load-promoted` — a promoted full contract loads.

`gate-decision` (13):

- `gd-0001-declared-permission-allowed`
- `gd-0002-undeclared-permission-denied`
- `gd-0003-declared-side-effect-allowed`
- `gd-0004-undeclared-side-effect-denied`
- `gd-0005-approval-pending-then-allowed`
- `gd-0006-tampered-contract-denied`
- `gd-0007-draft-declared-permission-allowed`
- `gd-0008-draft-undeclared-permission-denied`
- `gd-0009-draft-irreversible-pending` — anchor A2: irreversible default-deny
  in draft mode with no approvals declared.
- `gd-0010-draft-irreversible-allowed-after-approve`
- `gd-0011-draft-reversible-allowed`
- `gd-0012-full-irreversible-allowed` — pins RFC 0005 §8 Q2: full-mode T8 is
  unchanged in v1.
- `gd-0013-guardrail-budget-denied`

`trace-roundtrip` (9):

- `tr-0001-full-mode-roundtrip` — byte-identical canonical JSONL without
  `provisional`.
- `tr-0002-draft-mode-roundtrip` — `provisional: true` is emitted.
- `tr-0003-absent-provisional-parsed` — absence parses as full mode.
- `tr-0004-null-provisional-rejected`
- `tr-0005-string-provisional-rejected`
- `tr-0006-unknown-field-rejected`
- `tr-0007-bad-hash-rejected`
- `tr-0008-bad-timestamp-rejected`
- `tr-0009-unknown-result-rejected`

### Notes for runtime implementers

- Integrity denials (`T5`/tamper) have no dedicated code in RFC 0005 §6.7.
  This suite maps them to the canonical `ContractViolationError` code and uses
  `message_contains: "tampered"` to distinguish the case. A runtime may raise
  its own tamper type, but must map it to `ContractViolationError` at the
  runner boundary.
- Promotion orchestration is deliberately absent: RFC 0005 §6.10 and §8 Q5
  keep the registry/CLI flow out of the cross-runtime corpus in v1.
- `contract-model` error `path` values are RFC 6901 JSON Pointers. The Python
  validator's internal dotted path is normalized at the runner boundary.
