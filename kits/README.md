# Adoption kits (M3.2)

A kit is a self-contained, declarative bundle for one shipped conformance
target. It tells an adopter what to install, how to run the target's check, and
what to copy into their repository. A kit never ships engine code, never
duplicates a scanner rule, and never calls the network.

## Required contents

Every `kits/<target>/` directory contains **exactly** these files:

```text
kits/<target>/
├── KIT.md                     # what it governs, three-step path, honest scope
├── contract.template.yaml     # the target's reference contract, "# EDIT" fields
├── verify.sh                  # POSIX check wrapper (no network, no secrets)
├── verify.ps1                 # PowerShell check wrapper (same behavior)
└── reference/
    ├── finding-codes.md       # copied from the M3.1 skill, byte-identical
    └── exit-codes.md          # copied from the M3.1 skill, byte-identical
```

`kits/README.md` (this file) is the only non-kit file at the top level. A kit
directory with an extra file fails `tests/test_m32_kits.py`.

## Lockstep rule

`kits/<target>/reference/*.md` are copies of
`skills/scyvera-governance/reference/*.md`, not rewrites. The suite compares
bytes in both directions. To change a table:

1. Edit `skills/scyvera-governance/reference/<table>.md`.
2. Re-copy it into every `kits/*/reference/` directory.
3. Refresh the skill hash lock: `python -m tools.lock_skill`.
4. Run `tests/test_m31_skill.py` and `tests/test_m32_kits.py`.

The lockstep is deliberate: the finding and exit-code vocabulary is the
contract between the kits and the engine, and two drifting copies would let an
adopter read an outdated rule ID.

## Verify-script contract

Both scripts must remain stdlib-portable and offline:

- check the install with `scyvera --version` (exit `2` if it is missing);
- run `scyvera check implementations/<target>/<reference> --tier 1` from the
  repository root;
- capture the engine exit code and exit with it;
- print the expected finding summary so a human can compare it to the live
  output;
- contain no `curl`, `wget`, `ssh`, `sudo`, `Invoke-WebRequest`, token, or URL.

`verify.sh` runs wherever a POSIX `sh` exists. `verify.ps1` is parse-checked on
Windows and executed by PowerShell users; the kit's own test suite documents
that split.

## Add a kit for a new target

1. Confirm `implementations/<target>/` has a contract and a Tier 1 adapter that
   `scyvera check` discovers. Run the check by hand and record the exact
   expected summary.
2. Create `kits/<target>/` with the six required files.
3. Copy `contract.yaml` into `contract.template.yaml` and mark every
   adopter-relevant field with an inline `# EDIT` comment.
4. Copy the two reference tables from the skill and verify byte equality.
5. Write `KIT.md` with the three-step path, the reference target, the pinned
   expected output, and an honest scope section that links
   `docs/language-coverage.md`.
6. Add the target and its reference path to `tests/test_m32_kits.py`
   (`TARGETS`), then run the full suite and the repository dogfood
   (`scyvera audit . --fail-under 92`).

No engine file, workflow, or package manifest changes are part of adding a kit.
