# Google ADK adoption kit

A declarative, read-only adoption kit for teams building agents with
[Google ADK](https://google.github.io/adk-docs/) (Agent Development Kit). It
supplies a valid v1.1 contract template, integration notes, an illustrative ADK
wiring file, verification scripts, and the canonical result-code tables.

**Target framework:** Google ADK for Python (`LlmAgent` + Python tool
callables). This kit does not install ADK, import it during verification, or
call a model.

**Status:** reference implementation, **Tier 0 only**. There is no Google ADK
Tier-1 adapter in this release, so `scyvera check --tier 1` exits `2` with
"no tier 1 adapter". The kit never fakes a higher tier.

> **The kit is orchestration, not enforcement.** ADK chooses which tool the
> model wants to call; the Scyvera gate inside the tool decides whether it may
> run. Without a gate around the tool there is no enforcement, and without a
> provisional contract on disk there is no inference-time enforcement.

## Why Google ADK (and not an upgrade)

Issue #85 offered either a new Google ADK kit or a clearly justified upgrade to
the shipped n8n/langgraph kits. Google ADK was chosen because:

1. Its tools are ordinary Python callables, so the enforcement boundary can be
   shown in a few lines (`@enforcer.gate(...)` + `assert_gated`) instead of
   hidden behind a visual workflow or graph runtime.
2. It adds a genuinely new framework surface. The two shipped kits are pinned
   file-for-file by `tests/test_m32_kits.py`; an "upgrade" would have to change
   those pins while adding no new framework coverage.

## Contents

```text
docs/kits/google-adk/
├── README.md                  # this file: what it is, limits, how to run
├── KIT.md                     # house-template integration path
├── contract.template.yaml     # valid v1.1 fixture, every editable field # EDIT
├── verify.sh                  # POSIX verifier (exit 0/1/2)
├── verify.ps1                 # PowerShell verifier (same behavior)
└── reference/
    ├── adk_agent.py           # illustrative ADK + Scyvera wiring (not executed)
    ├── boundary.md            # orchestration-vs-enforcement boundary
    ├── exit-codes.md          # byte-identical to the M3.1 skill table
    └── finding-codes.md       # byte-identical to the M3.1 skill table
```

The canonical file list for a kit is in
[`docs/kits-authoring.md`](../../kits-authoring.md). This kit lives under
`docs/kits/` rather than `kits/` because the shipped-kit pin in
`tests/test_m32_kits.py` requires a test change to register a new target, and
issue #85 is `safe:no-core-change`. The authoring guide records that trade-off.

## Run it

From the repository root:

```bash
sh docs/kits/google-adk/verify.sh          # POSIX
pwsh docs/kits/google-adk/verify.ps1       # PowerShell
```

Both scripts are idempotent, read-only, offline, and preserve the engine's exit
code. They run:

```bash
scyvera validate docs/kits/google-adk/contract.template.yaml
scyvera lint     docs/kits/google-adk/contract.template.yaml
scyvera check    docs/kits/google-adk/contract.template.yaml --tier 0
scyvera audit    docs/kits/google-adk
```

Expected result (exit `0`):

```text
verify.sh: scyvera 1.4.0
PASS  docs/kits/google-adk/contract.template.yaml
PASS  docs/kits/google-adk/contract.template.yaml (0 semantic warnings)
PASS  docs/kits/google-adk/contract.template.yaml (tier 0 (structural): 0 schema errors, 0 semantic warnings)
PASS  docs/kits/google-adk - exploit risk none (score 100/100) [ungoverned]
verify.sh: expected: PASS tier 0, 0 schema errors, 0 semantic warnings, audit 100/100 (exit 0)
verify.sh: tier 1 is not claimed: no Google ADK adapter exists yet
verify.sh: google-adk kit verified (exit 0)
```

`[ungoverned]` is correct here: the fixture is named `contract.template.yaml`,
not `contract.yaml`, because it is not yet the governing contract. Copy and
rename it (step 1 below) and `scyvera audit .` reports the target as governed.
The renderer prints an em dash where this page shows the `-`; the band and score
are the machine-relevant parts.

## Adopt it

1. **Copy the fixture** to `contract.yaml` beside your ADK agent. The loader
   rejects `.yml`; the canonical name is `contract.yaml`.
2. **Replace every `# EDIT` field** — agent name, domain, resources,
   permissions, side effects, approvals, dependencies, state, recovery, replay,
   observability, and risk.
3. **Wire the gate** the way `reference/adk_agent.py` shows: load the contract
   from disk once at process start, decorate every externally reaching tool
   with `@enforcer.gate("resource:action", ...)`, and call
   `ContractEnforcer.assert_gated(tool)` for every tool before constructing the
   ADK agent. A tool outside the gate is invisible to Scyvera.
4. **Run the same checks the kit runs**, with the path to *your* adopter
   contract:

   ```bash
   scyvera validate contract.yaml
   scyvera lint contract.yaml
   scyvera check contract.yaml --tier 0   # Tier 1: unavailable for ADK today
   ```

## Provisional contracts and draft mode in ADK

A provisional contract is a real file on disk, not authority inferred in
memory:

```yaml
version: 1.1
provisional: true
```

```python
enforcer = ContractEnforcer.load(
    "contract.yaml", mode="draft", registry="registry.jsonl"
)
```

* `ContractEnforcer.load("contract.yaml")` in full mode raises
  `ProvisionalContractError` and names the promotion ritual.
* Draft mode accepts a provisional contract only. Declared actions are allowed;
  undeclared actions are denied; irreversible actions still default-deny behind
  an approval gate even when `approvals` is empty; every audit and trace entry
  is marked `provisional`.
* Promotion is human-only (`scyvera promote`, re-seal, reviewer + intent +
  diff-hash). No time-based, event-based, or agent-executed promotion.
* Keeping an agent in draft forever buys no destructive authority and is
  recorded as threat T15 (RFC 0005 §7.2).

The full boundary is written out in
[`reference/boundary.md`](./reference/boundary.md).

## Honest limitations

- **No Tier-1 adapter.** `scyvera check --tier 1` on an ADK directory exits `2`
  ("no tier 1 adapter"). This kit proves structure (Tier 0) and blast radius
  (audit) only. Do not describe an ADK target as Tier-1 conformant.
- **Orchestration is not enforcement.** ADK will happily execute a tool that is
  not wrapped. `assert_gated` catches that at agent-construction time, but it
  cannot catch a tool invoked outside the agent or a hand-written client that
  never imports Scyvera.
- **The contract is a declaration, not proof.** Tier 0 validates and lints the
  YAML; it does not compare the declaration with your Python source. That
  declared-vs-code comparison is what a future ADK Tier-1 adapter would need to
  provide.
- **Static analysis is pattern-level.** A missing audit finding is not evidence
  that a capability is absent. See
  [`docs/language-coverage.md`](../../language-coverage.md).
- **The reference file is illustrative.** `reference/adk_agent.py` is not
  imported or executed by the kit and does not pin an ADK version. Pin ADK and
  your model versions in your own project.
- **No network, credentials, or installs.** The kit scripts never install
  packages, reach the network, or read secrets.

## Result codes

- [`reference/exit-codes.md`](./reference/exit-codes.md) — the `0` / `1` / `2`
  convention for `validate`, `lint`, `check`, `audit`, and the other commands.
- [`reference/finding-codes.md`](./reference/finding-codes.md) — `ACxxx`,
  `AUxxx`, and `T101`–`T103` meanings and severities.

Both tables are byte-identical to the M3.1 skill reference. Do not edit the
copies; update the skill and re-copy.

## Related

- [`docs/kits-authoring.md`](../../kits-authoring.md) — scaffold a new kit.
- [`kits/README.md`](../../../kits/README.md) — the shipped-kit format and pin.
- [`rfcs/0005-provisional-contracts.md`](../../../rfcs/0005-provisional-contracts.md)
  — provisional contracts, draft mode, threat deltas.
- [`docs/language-coverage.md`](../../language-coverage.md) — audit's honest
  pattern-level limits.
