# Language pack fixture: multilingual customer service

This folder is a **documentation and teaching fixture**. It shows what a
non-English, non-ASCII Agent Contract v1.1 looks like when it is written to the
same standard as the English examples in `examples/v1.1/`, and it exercises the
UTF-8/BOM handling that the R1b language-pack work fixed in `scyvera`.

Nothing here is a production agent, and no code in `src/scyvera/` or `tests/`
loads these files. The fixture exists to be read, validated, and copied as a
starting point.

## What is in the box

| File | Purpose |
| --- | --- |
| `fixtures/mehrsprachiger-kundenservice/contract.yaml` | The primary contract: a German-language returns and repairs desk that also answers in French and Japanese. |
| `fixtures/mehrsprachiger-kundenservice/contract.provisional.yaml` | The same service in **draft** form: `provisional: true`, an inferred version string, and a header comment. |
| `fixtures/mehrsprachiger-kundenservice/contract.bom.yaml` | A byte-for-byte copy of `contract.yaml` with a UTF-8 BOM (`EF BB BF`) prepended. |

All three files use LF line endings, as required by `.gitattributes`.

## What the fixture demonstrates

The contract is not an English example with translated strings. It is a
coherent service whose primary language is German, with French and Japanese
vocabulary carried inline where a real team would use it:

- **Non-ASCII metadata.** System name, purpose, capability descriptions,
  constraints, and approver conditions are written in German (`Rückgabefrist`,
  `Erstattungsbetrag`, `serviceteam_leitung`). French and Japanese appear in the
  same fields (`délai de retour`, `ordre de réparation`, `返品期限`, `修理依頼`).
- **Unicode resource identifiers.** `顧客データ` (customer data) and
  `werkstattaufträge` (workshop orders) are used as permission and side-effect
  resource names. The names must match across `permissions.resources` and
  `side_effects.resource`, so a normalization bug in either direction shows up
  immediately.
- **Multi-language side effects.** Each side effect describes its real-world
  consequence in more than one language, and the irreversible cancellation
  (`storno`) is explicitly marked `irreversible: true` with a matching approval
  boundary.
- **Governance signals that survive translation.** The contract sets
  `risk.level: high`, declares approval boundaries for cancellation and refunds,
  gives every required dependency a recovery strategy, and uses
  `observability.level: audit`. It therefore lints with zero warnings while
  still describing a risky agent.
- **Draft semantics.** `contract.provisional.yaml` sets `provisional: true` and
  an `0.1.0-inferred` version, which is how a statically inferred draft is meant
  to be marked before a human promotes it.

## Validate it

From the repository root:

```bash
scyvera validate examples/language-pack/fixtures/mehrsprachiger-kundenservice/contract.yaml
scyvera lint     examples/language-pack/fixtures/mehrsprachiger-kundenservice/contract.yaml
scyvera check    examples/language-pack/fixtures/mehrsprachiger-kundenservice/contract.yaml --tier 0
```

Expected output:

```text
PASS  examples/language-pack/fixtures/mehrsprachiger-kundenservice/contract.yaml
PASS  examples/language-pack/fixtures/mehrsprachiger-kundenservice/contract.yaml (0 semantic warnings)
PASS  examples/language-pack/fixtures/mehrsprachiger-kundenservice/contract.yaml (tier 0 (structural): 0 schema errors, 0 semantic warnings)
```

The draft and BOM variants validate the same way:

```bash
scyvera validate examples/language-pack/fixtures/mehrsprachiger-kundenservice/contract.provisional.yaml
scyvera validate examples/language-pack/fixtures/mehrsprachiger-kundenservice/contract.bom.yaml
```

Confirm the BOM really is present:

```bash
python -c "from pathlib import Path; print(Path('examples/language-pack/fixtures/mehrsprachiger-kundenservice/contract.bom.yaml').read_bytes()[:3].hex())"
# efbbbf
```

Audit the folder to see governance detection resolve the primary contract:

```bash
scyvera audit examples/language-pack --fail-under 100
```

Expected summary: `100` / `Shielded`, `governance.status: governed`, and
`contract_path: fixtures/mehrsprachiger-kundenservice/contract.yaml`.

## Why the fixture is nested under `fixtures/`

`scyvera audit` detects governance with a bounded, name-based search for
`contract.yaml` (three directory levels below the audit target). This folder is
a teaching fixture, not a deployed agent, so it is deliberately kept below that
boundary relative to the repository root. A repo-wide `scyvera audit .` therefore
keeps reporting the repository's own implementation contracts, while
`scyvera audit examples/language-pack` still finds and reports this fixture.
That is the intended behaviour in both directions, and the commands above show
it explicitly.

## Honest limitations

- **Not wired into CI or tests.** The fixture is intentionally unreferenced by
  `src/scyvera/` and `tests/`. If it drifts, the normal suite will not catch it;
  the commands above are the check.
- **The translations are authored, not verified.** They are plausible German,
  French, and Japanese service vocabulary, but they have not been reviewed by a
  native speaker or a localization vendor, and the schema does not validate
  language codes or translation quality.
- **The BOM variant proves loader tolerance, not network behaviour.** Both the
  validator (PyYAML) and the audit scan accept a leading BOM. The file does not
  test other encodings, UTF-16, or a BOM in the middle of a stream.
- **`provisional: true` is a declaration.** `scyvera validate` accepts a
  provisional contract; refusing it is the job of a full-mode enforcer before
  promotion. This fixture does not exercise that enforcement path.
- **The resource names are synthetic.** `顧客データ`, `bestellungen`, and
  `werkstattaufträge` do not correspond to any real CRM or workshop system.
- **Line endings depend on tooling.** `.gitattributes` normalizes these files to
  LF, but a Windows editor that rewrites the working tree can reintroduce CRLF;
  re-run the validation commands after editing.

## Scope

This contribution only adds files under `examples/`. It does not change
`src/scyvera/**`, `schemas/**`, `vectors/**`, `tests/**`, the CLI, exit codes,
or any public API.
