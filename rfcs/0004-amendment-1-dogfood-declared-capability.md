# RFC 0004 — Amendment 1: Dogfood Covenant for a Declared and Approved Capability

> [!NOTE]
> **Status: Accepted (2026-11-18)**
> Amends [RFC 0004](./0004-audit-cli-blast-radius-and-policy-packs.md) §7, check #1 only. No other
> section of RFC 0004 is changed, and no prior text in that RFC is rewritten.
>
> Author: Scyvera Core Team / Agent Contracts Working Group
> Applies to: `scyvera` 1.4.x and later

---

## 1. What check #1 originally pinned

RFC 0004 §7 check #1 reads, in full:

> **Dogfood**: `scyvera audit .` runs against the Scyvera repo itself in CI; result is asserted in a
> test snapshot (band must remain `Shielded` at 1.3.0 release; if drift occurs, the test fails
> loudly, not silently).

That sentence is **release-scoped**: `Shielded` was the bar for the 1.3.0 release, the release that
shipped the audit funnel. The snapshot it produced — 92/100 `Shielded` — was then carried forward
unchanged as a permanent, exact-value test pin. The pin outlived the scope of the requirement it came
from, and by 1.4.x it was no longer describing a release gate; it was forbidding the repository from
ever exercising a capability its own product documents.

## 2. What changed, and why the number moved

The repository now commits the npm publish workflow documented in
`runtimes/ts/PUBLISHING.md` and declares and approves the capability it exercises in a root
`contract.yaml` (`permissions: ["registry:publish"]`,
`approvals: [{action: registry:publish, required: true}]`, approver `repository_maintainer`).

`AU-CI-002` ("deploy or publish job detected") is a **high** severity rule, and severity is a weight,
not a coefficient:

| Component | Value |
|---|---|
| `SEVERITY_WEIGHTS["high"]` | 8 |
| `RULE_LOAD_COEFFICIENTS[0]` (first occurrence) | 1.0 |
| `AU-CI-002` contribution | **8.0** |
| Pre-change scored load (4× `AU-N8N-001`, 2× `AU-NET-002`, diminishing coefficients) | **7.8** |
| New scored load | 7.8 + 8.0 = **15.8** |
| Score = `max(0, 100 - ceil(15.8))` | **84** |
| Band (70–89) | **Controlled** |

So the honest delta is **92 → 84**, `Shielded → Controlled`, not a one-point drift. Governance
detection is render-only by design (`scyvera.audit`), so declaring the capability correctly reports
`governed` and correctly does **not** discount the finding. The finding is real: the workflow can
publish to a public registry.

## 3. The new invariant

The dogfood gate is no longer "the score never moves". It is a **covenant** with three parts, all of
which are asserted by `tests/test_audit_dogfood.py`:

1. `scyvera audit .` reports exactly **84/100 `Controlled`** and governance `governed`.
2. The scored findings are **exactly** the known set: one `AU-CI-002` on
   `.github/workflows/publish-scyvera-ts.yml`, plus the six pre-existing demo findings (four
   `AU-N8N-001`, two `AU-NET-002`). Anything else fails the test.
3. `contract.yaml` declares `registry:publish` and carries
   `{action: registry:publish, required: true}` with a human approver role. **Removing that approval
   fails the test.** The gate therefore enforces "declared and approved", not "waived".

Changing any part of this covenant — a new scored finding, a different score or band, a removed
approval — requires a new amendment and a matching test change. It cannot be done by editing a
number in isolation.

## 4. Rejected alternatives

| Alternative | Why it was rejected |
|---|---|
| Fix the six demo findings to buy back the 8 points | It would restore 92 without touching the new capability, but it edits `implementations/**` demo material for a scoring reason, expands the change far beyond the publish lane, and can break the Tier 1 reference adapters. Improving the demos is its own change, not a precondition for an honest score. |
| Move the publish workflow off `main` (branch-only or separate repo) | The capability would then be undeclared, unregistered, and untested on the branch that ships it. That is the exact "papering over" RFC 0004 §7 exists to prevent, and it would leave `PUBLISHING.md` describing a workflow the repository does not have. |
| Soften `AU-CI-002` or lower its severity | The rule is true here: a CI job really can publish a public package. Lowering the weight to protect the number would make the score a marketing claim instead of a measurement. |
| Keep the exact 92 pin and leave the suite red | A permanently red suite is not a gate; it trains contributors to ignore the gate. The covenant replaces a stale snapshot with a precise, reviewable assertion. |

## 5. Follow-up lane

The score can return to `Shielded` **without hiding anything** if the audit learns to discount a
finding that the repository's own contract declares and approves. That is a product change to
`scyvera.audit` (not a rule change), and it is recorded on the roadmap as *audit honors declared and
approved capabilities (governed findings)*. Until that ships, 84/100 `Controlled` is the correct
number and the covenant above is the correct gate.
