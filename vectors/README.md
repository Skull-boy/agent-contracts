# Conformance Vectors

This directory is the shared acceptance corpus for every GEP runtime. The
format authority is **[RFC 0005 §6](../rfcs/0005-provisional-contracts.md#6-conformance-vector-suite-normative-format-non-normative-runner)**.
Read that section before adding, changing, or running a vector.

## Status

**Suite version 1 ships 33 vectors across the three RFC 0005 §6.1
categories.** The Python reference runner lives in `src/scyvera/vectors.py` and
is exposed as `scyvera vectors`.

`suite-version: 0` meant "empty skeleton" in GE-1. The first non-empty suite is
version `1`; GE-3 added the `v1/` tree and bumped `suite-version` to `1`.

## Layout

```text
vectors/
  README.md          # this file
  CHANGELOG.md       # one section per suite version
  suite-version      # exactly: suite-version: <integer>\n
  v<N>/
    contract-model/
      <id>.json
    gate-decision/
      <id>.json
    trace-roundtrip/
      <id>.json
```

The three categories are closed: `contract-model`, `gate-decision`, and
`trace-roundtrip`. Promotion orchestration is Python-only in v0/v1 and is not a
cross-runtime category (RFC 0005 §6.10, §8 Q5); its non-negotiables are pinned
by `tests/test_ge3_vectors.py` instead.

## Rules

- `suite-version` is the single source of truth. Every runtime's CI pins the
  same integer and fails on drift (RFC 0005 §6.2, anchor A6).
- Any vector addition, change, or removal increments `suite-version` by one and
  lands with a `CHANGELOG.md` entry in the same commit (RFC 0005 §6.8).
- Conformance at a version is all-or-nothing. A runtime MUST NOT skip a
  category, run a subset, or report a percentage pass as conformance.
- Vectors are deterministic: no wall clock, no filesystem order, no absolute
  paths, no host-language exception names. Error matching uses the canonical
  `error_code` plus a `message_contains` substring (RFC 0005 §6.7).
- Vector files use canonical JSON: UTF-8, no BOM, LF, sorted keys, two-space
  indent, one trailing newline.

## Adding a vector (GE-3 onward)

1. Pick the category and allocate a never-reused ID:
   `cm-NNNN-slug`, `gd-NNNN-slug`, or `tr-NNNN-slug`.
2. Write the envelope and category shape exactly as RFC 0005 §6.3-§6.6
   specifies. Unknown keys are rejected.
3. Run the reference runner twice and confirm byte-identical output.
4. Bump `suite-version`, add the changelog section, and update every runtime's
   pinned version in the same release train.

## Running the suite

```text
scyvera vectors                  # all vectors, human PASS/FAIL + per-category counts
scyvera vectors --category gate-decision
scyvera vectors --json           # RFC 0003 unified envelope, mode "vectors"
```

Exit codes: `0` all pass, `1` at least one failure, `2` suite configuration or
usage error. The canonical RFC 0005 §6.8 result object is carried unchanged in
the unified envelope's `data` key.

The Python runner is the reference semantics, not a dependency. `scyvera-ts`
and `scyvera-rs` implement their own runners against these same bytes.
