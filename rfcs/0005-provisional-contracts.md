> [!NOTE]
> **RFC Status: Draft**
> This RFC specifies the provisional-contract lifecycle and the conformance-vector
> suite format for the Governance Expansion Program (GEP). It is a
> **specification only**: it changes no engine, no schema file, and no test in
> this repository. GE-2 (draft governance) and GE-3 (vector suite) implement it.
> Until this RFC is accepted, the semantics below are the design authority for
> those tasks and any conflict with shipped code is a bug to raise, not a
> licence to reword the RFC.
>
> Author: Scyvera Core Team / Agent Contracts Working Group
> Created: 2026-11-14
> Target: Agent Contracts v1.1/v1.2 (additive) and the GEP runtime family
> (`scyvera` Python, `scyvera-ts`, `scyvera-rs`)

---

# RFC 0005: Provisional Contracts and the Conformance Vector Suite

- **Status**: Draft
- **Author**: Scyvera Core Team / Agent Contracts Working Group
- **Created**: 2026-11-14
- **Target Spec**: Agent Contracts v1.1 and v1.2 (additive); GEP runtimes
- **Related**: [`docs/roadmap.md`](../docs/roadmap.md) GEP section, RFC 0002,
  RFC 0003, RFC 0004, [`docs/threat-model-enforcer.md`](../docs/threat-model-enforcer.md),
  [`docs/threat-model-lifecycle.md`](../docs/threat-model-lifecycle.md),
  [`docs/threat-model-distribution.md`](../docs/threat-model-distribution.md)

---

## 1. Abstract

### 1.1 The problem: audit honesty is not a runtime path

A repository with no `contract.yaml` can already be audited. `scyvera audit`
produces a Blast Radius Report, names the capabilities the environment exposes,
and suggests a contract draft. That is honest, but it is not *governance*: the
agent still runs with no declared boundary, no gate, no approval boundary, and
no trace. The first step to governance is authoring a contract, and authoring a
contract from a blank page is the adoption tax that prevents the people who
need governance most from ever reaching it.

The obvious fix - let the agent infer its own contract at runtime and enforce
that - is the trap named in the GEP non-negotiables:

> "No inference-time enforcement without a provisional contract on disk."

Inference may *draft* a boundary. It may never *become* the authority that
enforces the boundary. The two must be separated in the artifact model, not
merely in documentation.

### 1.2 The solution: a provisional lifecycle, not inferred authority

This RFC introduces a lifecycle:

1. **Generate** a provisional contract by static inference over the target.
   The artifact is written to disk and marked `provisional: true`.
2. **Run in draft mode.** A draft-mode enforcer enforces the declared boundary
   exactly as a full enforcer does, except that irreversible actions always
   require an approval even when the draft declares no approval points.
3. **Promote** through an explicit human ritual that reuses the existing
   re-seal machinery. Promotion records who approved the change, why, and a
   deterministic diff of what changed. The promoted contract is an ordinary
   full contract and is the only form a production full-mode enforcer accepts.

The provisional contract is therefore a *real contract on disk* - hashed,
registered, versioned, audited, and enforced - whose authority is explicitly
time-limited and review-pending. It is not a shadow model, not a runtime
guess, and not a permission grant.

### 1.3 Why the vector suite is part of the same RFC

A standard implemented twice is two standards unless both implementations are
measured by the same corpus. The GEP will ship `scyvera-ts` and `scyvera-rs`,
and the only credible claim that they implement *one* standard is that every
runtime passes the *same* conformance vectors at the *same* pinned suite
version. The vector format lives in this RFC because the provisional lifecycle
adds decision vectors (draft vs. full, irreversible pending, promotion
refusal) that the suite must cover from its first non-empty version.

### 1.4 Normative anchors

The GEP non-negotiables are encoded below as six normative statements. They are
repeated in their owning sections; this table is the index GE-2 and GE-3 can
grep. The words MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY are used as
defined in RFC 2119.

| ID | Normative statement |
|---|---|
| **A1** | A runtime MUST NOT perform inference-time enforcement without a provisional contract on disk. |
| **A2** | Irreversible actions MUST default-deny with an approval gate even in draft mode. |
| **A3** | Promotion MUST be human-only and MUST use the existing re-seal machinery. |
| **A4** | Promotion MUST NOT be silent or automatic. |
| **A5** | Agent-side skills MUST hold no authority over contracts. |
| **A6** | Every runtime MUST pass the same pinned conformance-vector suite version. |

### 1.5 What this RFC does not do

- It does not add `provisional` to the v1 schema; provisional contracts require
  `contract_version` 1.1 or later.
- It does not implement the generator, the draft-mode enforcer, the promotion
  command, or the vector runner. GE-2 and GE-3 do.
- It does not add an LLM to any governance path. Generation is static analysis
  over repository content; enforcement is deterministic.
- It does not make `registry=` mandatory at load time. It specifies the
  consequences when it is supplied and records the residual risk when it is
  not (§7.3, §8 Q9).

---

## 2. Terminology

The definitions below are aligned with the glossary in
[`docs/roadmap.md`](../docs/roadmap.md). Where the roadmap uses a shorthand
(`contract_hash`), this RFC uses the RFC 0003 §C4 field name
(`hash_of_contract`) and says so explicitly.

| Term | Definition |
|---|---|
| **Provisional contract** | A contract whose top-level `provisional` field is exactly `true`. It is a complete, schema-valid, hashed, registered contract that a full-mode enforcer MUST refuse and a draft-mode enforcer MUST accept. |
| **Draft mode** | The enforcer mode that accepts a provisional contract. It preserves every full-mode gate, audit, and trace requirement, and adds an unconditional approval gate for irreversible actions. |
| **Full mode** | The default enforcer mode. It accepts only contracts that are not provisional. "Full" names the contract's lifecycle status, not a different enforcement algorithm. |
| **Generation** | Static inference over a target's files that produces a provisional contract. Generation is not enforcement and never holds authority. |
| **Draft entry** | A registry entry whose additive `draft` flag is `true`. It records that the registered contract was provisional at registration time. The flag is derived from the contract, not authored independently. |
| **Promotion** | The human-gated transition from a provisional contract to a full contract. It is exactly: edit the contract to the promoted form, run the existing re-seal ritual with a `PromotionIntent`, and record a promotion block on the new registry entry. |
| **PromotionIntent** | The explicit human statement of who is promoting and why: `reviewer`, `intent`, and an optional `reference`. It is supplied out of band; no default, environment variable, git identity, or agent context may fill it. |
| **Promotion receipt** | The immutable record of a promotion: reviewer, intent, reference, from/to entry IDs, from/to versions, from/to contract hashes, the deterministic diff, and the diff's SHA-256. |
| **Vector suite** | The versioned corpus of conformance vectors under `vectors/`. It is the shared acceptance corpus for every GEP runtime. |
| **Suite version** | The single non-negative integer in `vectors/suite-version`. Version `0` is the empty skeleton; every non-empty suite has version `>= 1`. |
| **Vector** | One JSON file under `vectors/v<N>/<category>/` with the envelope and category shape defined in §6. |
| **Vector category** | One of exactly three cross-runtime categories: `contract-model`, `gate-decision`, `trace-roundtrip`. |
| **Runner** | Any program that executes the vectors and reports pass/fail. The runner is non-normative; the vector bytes and matching rules are normative. |

---

## 3. Provisional Contracts (normative)

### 3.1 The `provisional` field

A contract MAY carry exactly one optional top-level field:

```yaml
provisional: true
```

- The value MUST be a JSON boolean. A string, number, null, or object is a
  validation error.
- `provisional: true` means the contract is provisional.
- `provisional: false` and an absent field both mean the contract is full.
  Absence is the canonical full form. `provisional: false` is accepted for
  backward compatibility but is non-canonical; the linter SHOULD warn (rule
  `AC801`, "redundant provisional flag") and promotion output MUST omit the
  field.
- The field is top-level. It MUST NOT be nested under `lifecycle`, `security`,
  `risk`, or any other block. Placement under another block is not recognized
  and does not make a contract provisional.
- The field is **not a version**. It MUST NOT change `contract_version` or
  `version`, and no runtime may encode draft status by inventing a new
  `contract_version`.
- A contract with `version: 1` (or a normalized version of `1`) MUST NOT be
  provisional. Loading or validating `provisional: true` on a v1 contract MUST
  fail closed with a `ContractValidationError` whose message names
  `contract_version` 1.1 or later. Generation therefore always produces v1.1
  (or v1.2 when guardrails are present).
- The field is preserved verbatim by `ContractEnforcer.load()`. The enforcer
  exposes a read-only `is_provisional` property derived from strict identity
  with `True`; it MUST NOT mutate the frozen contract to normalize the field.
- **`provisional: true` MUST be preserved verbatim through registry
  registration.** The registry's `content` field stores the parsed contract,
  including `provisional: true`, and the contract hash covers the exact file
  bytes. A registry entry whose `content["provisional"]` disagrees with its
  `draft` flag is corrupt and MUST fail closed on verification.

### 3.2 Schema placement and validation

`provisional` is an additive optional property on the v1.1 and v1.2 schemas:

```json
"provisional": {
  "type": "boolean",
  "default": false,
  "description": "True for a draft contract generated by static inference. A full-mode enforcer MUST refuse it until human promotion."
}
```

- The v1.1 schema currently sets `additionalProperties: true`, so an unfixed
  schema already accepts the field without a schema edit. Adding the explicit
  property is still required by GE-2 so the type is checked and documented.
- The v1 schema is unchanged. Existing v1 contracts validate exactly as before.
- Existing v1.1 contracts validate unchanged: the property is optional, has no
  conditional requirement, and does not change any required field, enum, or
  pattern.
- The validator MUST accept the field on v1.1/v1.2 and MUST reject it on v1.
- The linter rule `AC801` is a warning, not an error: it fires when
  `provisional: false` is explicitly present. It never changes
  `validate_contract()`'s result.

### 3.3 Registry treatment: the draft entry

Provisional contracts are registered through the existing versioning path. No
new registry file format, no new index, and no new versioning rule are
introduced.

- `RegistryEntry` gains one additive field, `draft: bool = False`, and one
  additive optional field, `promotion: dict | None = None` (§5.5).
- `ContractRegistry.register()` derives `draft` from the enforcer:
  `draft = enforcer.is_provisional`. It MUST NOT accept a caller-supplied
  draft flag that disagrees with the contract.
- A provisional contract registers as a normal next version for its canonical
  path (or version 1 for a new path). Promotion later registers version N+1 for
  the same path; the draft entry is never deleted or rewritten.
- `get_latest_by_path()` returns the draft entry until a promotion entry
  supersedes it.
- **Conditional serialization preserves the chain.** The existing
  `canonical_entry_bytes()` serializes `asdict(entry)`. Adding dataclass fields
  naively would add keys to every old line and break every existing chain.
  Therefore:
  - Existing fields are serialized in their existing order.
  - `draft` is serialized **only when `True`**.
  - `promotion` is serialized **only when it is not `None`**.
  - When both are absent (every pre-RFC-0005 entry and every ordinary full
    entry), the bytes are byte-identical to the pre-RFC-0005 encoding.
  - A promoted entry carries `promotion` and omits `draft`; that is a new
    entry, so the chain extends normally.
- Chain verification MUST recompute the same conditional encoding. A loader
  that sees `draft` or `promotion` in a file MUST include them in the hash
  input; a loader that does not see them MUST NOT invent them.
- The registry MUST enforce the consistency invariant on load and on append:
  `draft == (content.get("provisional") is True)` and
  `promotion is None or content.get("provisional") is not True`.
  A mismatch raises `RegistryError` and fails closed.

### 3.4 Generation input contract

The RFC specifies **which finding classes may contribute which contract
fields**, not the implementation. GE-2 may reuse `scyvera.generate.build_draft`,
the audit engine, and the Tier 1 adapters, but it MUST obey this table.

| Source | May contribute | MUST NOT contribute | Constraints |
|---|---|---|---|
| `AU-SH-001` (critical, recursive delete) | `side_effects` `file_delete`, `approvals` | anything else | `irreversible: true`; an approval boundary is required |
| `AU-NET-001` (critical, piped install) | `side_effects` `remote_execution`, `approvals` | anything else | `irreversible: true`; an approval boundary is required |
| `AU-GIT-001` (high, destructive git) | `side_effects` `git_ref_write`, `approvals` | `irreversible: true` | may be irreversible only if the action text matches the closed verb set in §4.3 or a pack says so |
| `AU-NET-002`, `AU-CI-001`, `AU-CI-002`, `AU-N8N-001` (external write/egress) | `permissions`, `side_effects` (reversible) | `irreversible: true` | no approval is invented unless the pack requires one |
| `AU-ENV-001`, `AU-ENV-002`, `AU-SECRET-001` (secret/exposure) | `risk`, `observability`, a draft comment | `permissions`, `side_effects`, `approvals` | a secret finding never grants authority |
| `AU-DEP-001`, `AU-DOC-001` (hygiene) | `risk`, a draft comment | `permissions`, `side_effects`, `approvals` | informational only |
| Tier 1 `T101` (undeclared action) | `permissions` for a read, `side_effects` for a write | `irreversible: true` | irreversible only when the action text matches §4.3; a write gains an approval if the finding is approval-related |
| Tier 1 `T102` (ungated call) | `side_effects`, `approvals` | `irreversible: true` unless §4.3 matches | the call is gated by declaration, not by importing the target |
| Tier 1 `T103` (unused declaration) | nothing | every authority field | removing an unused declaration must never add authority |
| Policy Pack `derive.irreversibly_forbidden` | `side_effects` with `irreversible: true` | `approvals` for those actions | "no approvals offered" (RFC 0004 §6) |
| Policy Pack `derive.requires_approval` | `approvals` | `irreversible: true` | pack wins over finding-derived entries |
| Policy Pack `construction.cap_side_effects_per_window` | `constraints` | `side_effects` | value copied verbatim |

Additional generation rules:

1. **Generation MUST set `provisional: true`.** A generated contract that is
   not provisional is not a draft and MUST NOT be produced by the generation
   path.
2. **Generation MUST write exactly one file** (the contract), following the
   RFC 0004 §9 no-side-effects rule. It MUST NOT write a registry entry, a
   trace, or a receipt. Registration happens when the contract is loaded and
   registered, not during generation.
3. **Generation MUST NOT invent authority.** Every emitted permission,
   side effect, and approval MUST be traceable to a row in the table above.
   The draft header SHOULD list the contributing finding IDs.
4. **Generation MUST be deterministic.** The same target bytes, pack, and
   options produce byte-identical YAML. Ordering follows RFC 0004 §5:
   structural dedupe, then deterministic sort.
5. **Generation MUST pass `validate_contract()` and `lint_contract()` with zero
   errors at generation time.** RFC 0004 §5's zero-warning bar is the stronger
   target and SHOULD be met; the mandatory bar is zero errors because a
   warning may legitimately describe the target (for example, an unused
   declaration). A generated provisional contract that fails validation MUST
   NOT be written.
6. **Generation MUST include a `lifecycle` block** compatible with v1.1. When
   the target does not reveal its invocation model, generation MUST use the
   conservative default `{mode: request-response, initiation: human-only}`.
   This is a boundary, not an inference of authority.
7. **An empty target still gets a contract.** If the audit finds no scored
   findings, generation MUST emit a valid provisional contract with empty
   `permissions`, `side_effects`, and `approvals` (plus the safe lifecycle
   default). The blank page is replaced by an explicitly empty, loadable
   boundary.
8. **Generation is static.** It MUST NOT execute, import, or instrument the
   target. It reads files, audit findings, Tier 1 findings, and pack facts.
9. **Generation MUST NOT run at enforcement time.** A runtime MUST NOT call the
   generator in the gate path, and a gate MUST NOT synthesize a contract from
   model output. The generated file must exist on disk before draft-mode load.

The normative anchor for all of the above is:

> A1. A runtime MUST NOT perform inference-time enforcement without a provisional contract on disk.

`ContractEnforcer.from_declaration()` remains an explicit, developer-authored
in-process declaration API. It MUST NOT be used to launder model output or
generated authority. If a declaration was inferred, it must be written to disk
as a provisional contract first.

### 3.5 Registry registration of a provisional contract

A provisional contract is registered exactly like any other file contract:

1. `ContractEnforcer.load(path, mode="draft")` validates, lints, hashes, and
   freezes the contract.
2. `ContractRegistry.register(enforcer)` appends the next version and sets
   `draft=True`.
3. `verify_chain()` remains the append precondition.
4. The entry's `content` preserves `provisional: true` verbatim.

The registry does not grant authority. It records that a provisional contract
was registered at a point in the chain.

---

## 4. Draft Mode (normative)

### 4.1 Load modes and typed refusal

`ContractEnforcer.load()` gains one keyword-only argument:

```python
ContractEnforcer.load(path, *, mode: Literal["full", "draft"] = "full", ...)
```

- `mode="full"` is the default. It is the only mode that accepts a
  non-provisional contract.
- `mode="draft"` accepts a provisional contract.
- `mode="draft"` on a non-provisional contract MUST fail closed with a
  `ContractValidationError` whose message says the contract is not provisional.
  Draft mode is not a general "relaxed" mode; it is the mode for provisional
  contracts only.
- `mode="full"` on a `provisional: true` contract MUST fail closed with a new
  typed error, `ProvisionalContractError`, a subclass of
  `ContractViolationError` so existing `except ContractViolationError` blocks
  keep catching it. The message MUST name the promotion step and the existing
  re-seal machinery. The normative template is:

  ```text
  Contract '<path>' is provisional (`provisional: true`) and cannot be loaded
  in full mode. Promote it first through the human promotion ritual
  (`scyvera.reseal.reseal()` with a PromotionIntent); the promoted contract
  MUST omit `provisional`.
  ```

  A test MUST assert that loading a provisional contract without `mode="draft"`
  raises `ProvisionalContractError` and that the message contains both
  `provisional` and `promotion`. This is GE-2's pinned acceptance criterion.
- Full-mode load with a registry whose latest entry for the same canonical path
  is a draft entry MUST also fail closed with `ProvisionalContractError`, even
  if the file on disk has had `provisional` removed by hand. The registry is
  the record of intent; a file that disagrees with it is a T12 substitution,
  not a promotion.
- Full-mode load without a registry cannot perform the history check. It still
  refuses a file that says `provisional: true`. The residual risk is recorded
  in §7.3 and §8 Q9.
- `ProvisionalContractError` MUST carry `action_name="load"`,
  `contract_path`, `suggestion`, and `reason` following the existing
  `ContractViolationError` shape.

### 4.2 Gate semantics

Draft mode slots into the existing pipeline; it does not fork it:

```text
0. integrity      verify_integrity()                     (unchanged)
1. declaration    declared? else DENIED                   (unchanged)
2. approval       explicit approval OR irreversible gate  (extended)
2b. guardrails    rate/budget/fail-closed                 (unchanged)
3. allowed        ALLOWED                                 (unchanged)
```

- **Declared permissions and declared reversible side effects ARE allowed** in
  draft mode, exactly as in full mode. Draft mode is not "deny everything"; a
  draft that denied its own declared surface would be unusable and would
  pressure operators to promote without review.
- **Undeclared actions MUST be denied** in draft mode with the same
  `ContractViolationError` and the same `DENIED` audit entry as full mode.
- **Irreversible actions MUST default-deny with an approval gate even in draft
  mode.** Concretely: if an action is irreversible (§4.3) and no approval has
  been granted for it in this enforcer session, the gate MUST append a
  `PENDING` audit entry and raise `ApprovalPendingError`. This is true even
  when the contract's `approval_points` and `approvals` lists are empty. If an
  approval has been granted through the existing `approve(action)` path, the
  action proceeds subject to the remaining gates.
- **Every gated call MUST be audited as today.** Draft mode does not suppress,
  coalesce, or delay audit entries.
- **Guardrails, integrity, and declaration order are unchanged.** A guardrail
  denial still cannot mask an undeclared action or a pending approval.
- **Draft mode MUST NOT relax lifecycle, wildcard, version, symlink, or
  hash-chain checks.** It changes exactly one decision: the implicit approval
  requirement for irreversible actions.

The normative anchor is:

> A2. Irreversible actions MUST default-deny with an approval gate even in draft mode.

The implicit approval configuration MUST be deterministic:

```json
{"action": "<action_name>", "required": true, "approver": "human", "source": "implicit-irreversible"}
```

If an explicit approval entry already matches the action, its configuration is
used instead. The `PENDING` reason SHOULD be:

```text
Action requires human confirmation prior to execution (irreversible in draft mode).
```

### 4.3 Irreversibility resolution

An action is irreversible for the purpose of §4.2 if either condition holds:

1. **Declared irreversible.** The matching side-effect declaration carries
   `irreversible: true` (`side_effects[].irreversible`). Matching follows the
   existing `_is_action_declared()` semantics for side effects: the action name
   matches the declaration's `type`, `resource`, `resource:type`, description,
   or the existing prefix/remainder rule. This RFC does not narrow or widen the
   existing matching algorithm.
2. **Closed verb set.** The action name or the matching side-effect
   declaration's `type`, `resource`, or `description`, after normalization,
   contains one of the following closed set members as a whole phrase:

   ```text
   delete, destroy, drop, truncate, purge, erase, wipe,
   force push, remote execution, publish, deploy, merge, close,
   transfer, payment, overwrite, revoke
   ```

   Normalization is: lowercase; replace `_` and `-` with a single space; replace
   any character outside `[a-z0-9]` with a space; collapse whitespace; split
   into tokens. A member matches when its token sequence appears contiguously.
   For example, `github:repo:force_push` normalizes to `github repo force push`
   and matches `force push`. `undelete` does not match `delete` because it is a
   different token.

The closed set is deliberately small and explicit. Adding a member is a
semantic change and MUST bump the vector suite version with a `BREAKING`
changelog note (§6.8).

The set is **not** a claim that every irreversible action is covered; it is a
floor. A contract author can always declare `irreversible: true` explicitly for
an action outside the set. Conversely, an author cannot avoid the gate by
renaming `delete` to a synonym that is not in the set and not declared; that is
a review problem, not a runtime guarantee. §8 Q6 records the open question of
whether draft mode should only allow finding-backed actions.

### 4.4 Audit and trace marking

A draft-mode decision MUST be visibly attributable to draft mode in every
evidence surface. The RFC chooses additive fields, not reason-only encoding,
because reason strings are human text and must not be the machine contract.

**Audit log.** `AuditEntry` gains one additive field:

```python
provisional: bool = False
```

- Every `AuditEntry` produced by a draft-mode enforcer - including `ALLOWED`,
  `DENIED`, `PENDING`, guardrail denials, and `approve()` entries - MUST carry
  `provisional=True`.
- Every entry produced by a full-mode enforcer MUST carry
  `provisional=False` (the default).
- The field is appended to the dataclass with a default, so existing
  six-argument constructions keep working. `get_audit_log()` still returns a
  deep copy.

**Trace.** `TraceEntry` gains one optional field:

```python
provisional: bool | None = None
```

- A trace entry emitted by a draft-mode enforcer MUST serialize
  `"provisional": true`.
- A trace entry emitted by a full-mode enforcer MUST omit the field. `None` is
  the internal "absent" value; `to_dict()` MUST omit it when `None` or `False`.
- `from_dict()` MUST accept an absent field (meaning full), MUST accept a
  boolean, and MUST reject `null`, strings, numbers, and objects. It MUST
  continue to reject unknown fields other than this one.
- Full-mode trace JSONL MUST be byte-identical to the pre-RFC-0005 output.
  `TraceLog.to_jsonl()` already sorts keys and uses compact separators; omitting
  the field preserves the bytes.
- The trace field is `provisional`, not `draft_mode`, so the trace and the
  contract use one vocabulary. A parser MAY call it "draft" in a UI, but the
  serialized key is `provisional`.

This is an additive change to the RFC 0003 §C4 shape. §9.3 raises the exact
textual tension and the resolution.

### 4.5 Governance status

`governance_report()` and `governance_status()` gain one additive status value:

```json
{"status": "provisional", "contract_path": "path/to/contract.yaml"}
```

- `status` is one of `"governed"`, `"provisional"`, or `"ungoverned"`.
- A provisional contract reports `"provisional"`, never `"governed"`.
- An unreadable or malformed contract reports `"ungoverned"` (fail closed;
  never claim provisional or governed on a parse error).
- The `contract_path` field and the rest of the envelope are unchanged.
- Existing consumers that know only `governed`/`ungoverned` MUST treat an
  unknown status as not-fully-governed. The Python renderer MUST show
  `[provisional]` in the terminal, and the unified envelope's
  `summary.governance.status` carries the new value additively.
- `scyvera audit` on a target with a provisional contract MUST visibly mark it.
  It MUST NOT quietly report `governed`.
- `scyvera check` SHOULD emit a warning when the target's contract is
  provisional. Whether this becomes an error for a specific tier is §8 Q8.

### 4.6 What draft mode does not relax

For the avoidance of doubt, draft mode does NOT:

- allow an undeclared action;
- skip integrity verification, hash pinning, symlink refusal, or chain checks;
- skip the approval gate for a declared approval point;
- disable guardrails;
- accept wildcard permissions or side effects;
- accept a v1 contract with `provisional: true`;
- permit `format` or schema violations;
- permit a missing contract file.

Draft mode is strictly *more* restrictive than full mode for irreversible
actions. It is never a bypass.

---

## 5. Promotion Ritual (normative)

### 5.1 Human gate and intent

Promotion is the only transition from provisional to full. The human gate is
the control; the engine enforces that the human's intent is present, explicit,
and bound to the diff.

`PromotionIntent` is a frozen value object:

```python
@dataclass(frozen=True)
class PromotionIntent:
    reviewer: str          # non-empty; the human who reviewed
    intent: str            # non-empty; why this promotion is approved
    reference: str | None = None  # optional issue/PR/ticket URL or ID
```

- `reviewer` and `intent` MUST be non-empty strings after stripping
  surrounding whitespace. Empty values MUST raise `ValueError` (or a typed
  `PromotionIntentError` if GE-2 prefers).
- The intent MUST be supplied explicitly by the caller. It MUST NOT be read
  from an environment variable, git config, CI variable, prompt, model output,
  or agent context. There is no default reviewer and no default intent.
- The promotion command MUST print the deterministic diff (§5.2) and MUST
  require the operator to confirm the first 12 or more hex characters of
  `diff_sha256` (for example `--confirm a1b2c3d4e5f6`). A bare `--yes`,
  `--force`, or empty confirmation MUST be rejected. This binds the human's
  confirmation to the exact change, not to "whatever the tool did".
- The command MUST NOT offer a non-interactive bypass. CI may run the command
  only by supplying a real `reviewer`, `intent`, and confirmation prefix that
  came from a human review.

The normative anchor is:

> A3. Promotion MUST be human-only and MUST use the existing re-seal machinery.

### 5.2 Deterministic diff

The promotion receipt must prove *what changed*, not merely *that something
changed*. The diff algorithm is specified so two runtimes compute the same
bytes.

- Inputs: `before` is the `content` mapping of the latest draft registry entry
  for the canonical path. `after` is the parsed content of the promoted
  contract that is about to be registered. `before` MUST come from the
  registry, never from a mutable file, so the reviewer is diffing against the
  recorded intent.
- The diff is a JSON array of change records:

  ```json
  {"op": "add" | "remove" | "replace", "path": "/json/pointer", "before": <value>, "after": <value>}
  ```

  - `before` is omitted for `add`; `after` is omitted for `remove`; both are
    present for `replace`.
  - `path` is an RFC 6901 JSON Pointer. The root is `""`. Object keys escape
    `~` as `~0` and `/` as `~1`. Array indices are decimal.
  - Objects are compared by key. A key present only in `after` is `add` at its
    path; a key present only in `before` is `remove`; a key in both recurses.
  - Arrays are compared index by index up to the shorter length. Extra
    elements in `after` are `add` at indices `min..len(after)-1` in ascending
    order. Extra elements in `before` are `remove` at indices
    `len(before)-1..min` in descending order, so earlier indices remain valid.
  - Records are sorted by `path` lexicographically, then by `op` in the order
    `add`, `remove`, `replace`, then by the canonical JSON of the record.
- The canonical diff bytes are:

  ```python
  json.dumps(changes, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
  ```

  `diff_sha256 = hashlib.sha256(diff_bytes).hexdigest()`.
- An empty diff (no changes) MUST fail promotion. A promotion that changes
  nothing is not a promotion.
- The removal of `provisional: true` MUST appear as a `remove` record at path
  `/provisional`. This is how the receipt proves the flag flip rather than
  merely asserting it.
- The diff is deterministic across Python, TypeScript, and Rust for the JSON
  data model used by contracts (objects, arrays, strings, numbers, booleans,
  null). Implementations MUST NOT rely on host-language object key order.

### 5.3 Re-seal steps

Promotion reuses `scyvera.reseal.reseal()` exactly; it does not invent a second
registration path.

The promoted contract MUST first be edited to its canonical full form: the
`provisional` key is removed. The existing re-seal ritual then runs:

1. `validate_contract()` passes.
2. `lint_contract()` reports zero error-severity warnings; ordinary warnings
   are recorded.
3. `verify_chain()` passes.
4. The contract is registered as version N+1 for the same canonical path.
5. A frozen, timestamp-free `ResealRecord` is produced.
6. A fresh enforcer is loaded and reports `matches-registry`.

`reseal()` gains one keyword-only argument:

```python
def reseal(
    new_contract_path,
    registry,
    *,
    promotion: PromotionIntent | None = None,
) -> ResealResult:
```

The transition rules are:

| Previous latest entry | New contract | `promotion` | Result |
|---|---|---|---|
| none | full | must be `None` | first registration, not a promotion |
| none | provisional | must be `None` | first registration, draft entry |
| draft | provisional | must be `None` | next draft version |
| draft | full | **required** | promotion; version N+1 with a `promotion` block |
| full | full | must be `None` | ordinary re-seal; no promotion block |
| full | provisional | **rejected** | a full contract cannot be demoted by re-seal |

- `draft -> full` without a `PromotionIntent` MUST raise
  `ResealError("promotion", ...)` with a message naming the missing reviewer
  intent. This closes the "just delete the flag and re-seal" bypass.
- `promotion` supplied when the transition is not `draft -> full` MUST raise
  `ResealError("promotion", ...)`. A promotion block on a non-promotion is
  evidence laundering.
- `promotion` supplied with a new contract that is still provisional MUST be
  rejected; you cannot promote to draft.
- The `ResealRecord` gains additive fields `draft: bool = False` and
  `promotion: dict | None = None` at the end. Existing keyword constructions
  keep working.
- `ResealResult` gains an additive `promotion_receipt: PromotionReceipt | None =
  None`.

The normative anchor is:

> A4. Promotion MUST NOT be silent or automatic.

### 5.4 Promotion receipt

The `PromotionReceipt` is the complete evidence object. It is returned by the
promotion path and MAY be written as a JSON sidecar for humans; the registry's
compact `promotion` block is the authoritative on-chain record.

```json
{
  "receipt_version": 1,
  "reviewer": "alice",
  "intent": "Reviewed the generated boundary; approvals match the runbook.",
  "reference": "https://github.com/org/repo/pull/123",
  "from_entry_id": "3f0c...",
  "to_entry_id": "9a71...",
  "from_version": 4,
  "to_version": 5,
  "from_contract_hash": "<64 hex>",
  "to_contract_hash": "<64 hex>",
  "diff": [{"op": "remove", "path": "/provisional"}],
  "diff_sha256": "<64 hex>"
}
```

- `from_entry_id`, `from_version`, and `from_contract_hash` MUST identify the
  latest draft entry that was reviewed.
- `to_entry_id`, `to_version`, and `to_contract_hash` MUST identify the newly
  registered full entry.
- `diff` and `diff_sha256` MUST be computed by §5.2 from the registry draft
  content and the registered promoted content.
- The receipt is immutable once returned. A verifier MUST recompute the diff
  and hash from the two registry entries and fail closed on any mismatch.
- The receipt MUST NOT contain a wall-clock timestamp. Provenance time lives in
  the registry entry's `registered_at`, preserving the existing reseal design
  (timestamp-free records for deterministic tests).
- `receipt_version` is `1`. A future incompatible receipt shape increments it.

**Registry `promotion` block.** The new full entry stores a compact block,
serialized only when present:

```json
{
  "reviewer": "alice",
  "intent": "Reviewed the generated boundary; approvals match the runbook.",
  "reference": "https://github.com/org/repo/pull/123",
  "from_entry_id": "3f0c...",
  "from_version": 4,
  "from_contract_hash": "<64 hex>",
  "diff_sha256": "<64 hex>"
}
```

The `to_*` values are the entry's own `entry_id`, `version`, and
`contract_hash`, so they are not duplicated inside the block. The full `diff`
is reconstructible from the draft entry's `content` and the promoted entry's
`content`, both of which are in the append-only registry. A verifier MUST be
able to reconstruct it; the hash is the commitment.

### 5.5 Promotion command surface

The reference CLI (GE-2) exposes:

```text
scyvera promote <contract.yaml> --registry <path> \
  --reviewer "<name>" --intent "<why>" [--reference <url>] \
  --confirm <diff-sha256-prefix>
```

- All of `--registry`, `--reviewer`, `--intent`, and `--confirm` are required.
- The command MUST refuse if the contract still says `provisional: true`
  (nothing to promote), if the contract is already full with no draft history
  (not a promotion), or if the previous latest entry is not a draft.
- The command MUST print the diff before asking for confirmation. In a
  non-interactive context it still requires `--confirm`; it MUST NOT infer
  consent from a TTY or a CI variable.
- The command MUST NOT be exposed as an MCP tool, a skill script, or an
  auto-run hook. See §5.6.

### 5.6 Prohibitions and agent-side authority

The normative anchor is:

> A5. Agent-side skills MUST hold no authority over contracts.

Therefore:

- A skill MAY run `scyvera init --infer` to produce a provisional contract. It
  MAY run `scyvera validate`, `scyvera lint`, `scyvera audit`, and `scyvera
  check`. Those are knowledge and inspection actions.
- A skill MUST NOT run `scyvera promote`, MUST NOT construct or supply a
  `PromotionIntent`, MUST NOT set `reviewer`/`intent` on a human's behalf, and
  MUST NOT edit `provisional: true` to absent in an automated flow.
- A skill MUST NOT expose promotion through an MCP tool, a slash command that
  auto-executes, or a wrapper that hides the diff and confirmation.
- A skill's own `contract.yaml` is a declaration of the skill's surface. It is
  not authority over another contract, another runtime, or the registry.
- An agent that is asked to "promote my contract" MUST refuse and direct the
  human to the command, showing the exact diff command. Refusal is the correct
  behaviour, not a limitation.

The engine, not the skill, enforces the gate. A skill that ignores these rules
is out of conformance, but it still cannot promote without a `PromotionIntent`
that the engine can record.

### 5.7 Promotion failure modes

All promotion failures are fail-closed and MUST NOT leave a partial promotion:

| Condition | Result |
|---|---|
| Contract still provisional | `ResealError("promotion", "contract is still provisional")` |
| No prior draft entry | `ResealError("promotion", "not a promotion")` |
| Prior entry is full | `ResealError("promotion", "not a promotion")` |
| Missing reviewer or intent | `PromotionIntentError` / `ValueError` before any write |
| Confirmation prefix mismatch | `ResealError("promotion", ...)`, no registration |
| Empty diff | `ResealError("promotion", "no changes")` |
| Validation/lint failure | existing `ResealError("validate"|"lint", ...)` |
| Chain break | existing `ResealError("register", ...)` |
| Registration returns wrong version | existing `ResealError("register", ...)` |
| Fresh enforcer identity mismatch | existing `ResealError("identity", ...)` |

A failure after the registry append but before the fresh-enforcer check is
still a failure; the appended entry stays (append-only) and the operator must
investigate. The RFC does not permit a compensating delete.

---

## 6. Conformance Vector Suite (normative format, non-normative runner)

### 6.1 Layout

```text
vectors/
  README.md                 # points at this section as the format authority
  CHANGELOG.md              # one section per suite version
  suite-version             # exactly: suite-version: <integer>\n
  v<N>/                     # N equals suite-version; absent for N = 0
    contract-model/
      <vector-id>.json
    gate-decision/
      <vector-id>.json
    trace-roundtrip/
      <vector-id>.json
```

- The three category directory names are exact and closed:
  `contract-model`, `gate-decision`, `trace-roundtrip`.
- `v0/` is the empty suite and is not created. Version `0` means "no vectors";
  a runner pinned to `0` passes trivially with `total: 0`. The first non-empty
  suite is version `1`.
- A vector file MUST be named `<id>.json`, where `id` is the envelope's `id`.
- A vector file MUST NOT be nested deeper than the category directory.
- The suite MUST NOT contain symlinks. A runner MUST refuse a symlinked
  `vectors/` root or category directory, consistent with T14.
- The suite MUST be self-contained: no imports, no network, no reference to
  files outside `vectors/` except the RFC for documentation. A vector's
  `input.contract` is inline, not a path.

### 6.2 `suite-version`

`vectors/suite-version` is the single source of truth for the corpus version.

- Encoding: UTF-8, no BOM, LF line endings, exactly one line:
  `suite-version: <integer>\n`.
- The integer is `0` or a positive decimal with no leading zeros.
- No comments, blank lines, trailing spaces, or extra keys.
- The regex is `^suite-version: (0|[1-9][0-9]*)\n$`.
- The current file is exactly `suite-version: 0\n`.
- A runner MUST parse the file and fail closed (exit `2`) if it is missing,
  malformed, or names a version whose `v<N>/` directory is missing when `N > 0`.
- A runtime MUST pin the integer it implements, in its own CI configuration,
  as `pinned_suite_version = N`. The CI MUST fail if
  `vectors/suite-version != pinned_suite_version`. This is the mechanism for
  anchor A6.

The normative anchor is:

> A6. Every runtime MUST pass the same pinned conformance-vector suite version.

### 6.3 Envelope

Every vector is one JSON object with exactly these keys:

| Key | Type | Rule |
|---|---|---|
| `vector_version` | integer | MUST be `1`. A future incompatible envelope increments it. |
| `suite_version` | integer | MUST equal the directory version and `suite-version`. |
| `category` | string | One of the three category names. MUST equal the directory name. |
| `id` | string | `^(cm|gd|tr)-[0-9]{4}-[a-z0-9]+(-[a-z0-9]+)*$`; unique in the suite; stable forever. |
| `description` | string | Non-empty, one sentence, no trailing newline. |
| `input` | object | Category-specific shape below. |
| `expect` | object | Category-specific shape below. |
| `notes` | string | OPTIONAL. Reviewer-facing context; the runner MUST NOT interpret it. |

- Unknown keys MUST be rejected. This is the same fail-closed convention as
  `scyvera.evals.case` and `TraceEntry.from_dict()`.
- ID prefixes are fixed: `cm-` for `contract-model`, `gd-` for
  `gate-decision`, `tr-` for `trace-roundtrip`.
- IDs are never reused or renumbered. Deleting a vector does not free its ID.
- File encoding: UTF-8, no BOM, LF, sorted keys, two-space indent, one trailing
  newline. The canonical form is:
  `json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=True) + "\n"`.
  A runner SHOULD verify the canonical form; a non-canonical file is a suite
  defect, not a runtime failure.

### 6.4 Category: `contract-model`

Purpose: validate the contract model and the load-mode transition.

`input`:

```json
{
  "operation": "validate" | "load",
  "mode": "full" | "draft",
  "filename": "contract.yaml",
  "contract": { "...": "inline YAML-equivalent JSON object" }
}
```

- `operation` is required. `mode` is required only for `load`; it MUST be
  absent for `validate`. `filename` defaults to `contract.yaml` and MUST end
  in `.yaml`.
- `contract` is the inline mapping that would be written to `filename`. It is
  not a path.

`expect`:

```json
{
  "result": "valid" | "invalid" | "loaded" | "rejected",
  "errors": [
    {"path": "/permissions/0" | null, "message_contains": "wildcard"}
  ],
  "error_code": "ProvisionalContractError",
  "message_contains": "promotion"
}
```

- `result` is required.
- `errors` is required for `invalid` and MUST be `[]` otherwise. Matching is a
  set comparison: every expected `{path, message_contains}` MUST match at
  least one actual error; `path: null` means "any path". Extra actual errors
  are allowed unless `errors` is `[]`, in which case there MUST be no errors.
- `error_code` and `message_contains` are required for `rejected` and absent
  otherwise. `error_code` is the canonical cross-runtime code from §6.7.
- A `load` with `mode: "draft"` on a provisional contract expects
  `result: "loaded"`. A `load` with `mode: "full"` on the same contract expects
  `result: "rejected"`, `error_code: "ProvisionalContractError"`, and a
  `message_contains` of `"promotion"`.

Minimum v1 coverage (GE-3):

- `provisional: true` validates on v1.1.
- `provisional: false` validates on v1.1.
- absent validates on v1.1.
- non-boolean `provisional` is invalid.
- `provisional: true` on v1 is invalid.
- draft-mode load succeeds.
- full-mode load is rejected with `ProvisionalContractError`.
- draft-mode load of a non-provisional contract is rejected.
- promoted full contract loads in full mode.
- full-mode load with a registry whose latest entry is a draft is rejected.

### 6.5 Category: `gate-decision`

Purpose: pin the gate pipeline and the draft/full decision matrix.

`input`:

```json
{
  "mode": "full" | "draft",
  "contract": { "...": "inline contract" },
  "scenario": [
    {"action": "github:issues:write", "action_type": "permission"},
    {"action": "file_delete", "action_type": "side_effect"},
    {"action": "file_delete", "action_type": "side_effect", "approve": true}
  ],
  "tamper_before": false
}
```

- `mode` is required. `contract` is required.
- `scenario` is a non-empty array. Each step has `action` (non-empty string)
  and `action_type` (`"permission"`, `"side_effect"`, or `"read"`). `approve`
  is optional boolean; when `true`, the runner calls `enforcer.approve(action)`
  before evaluating the step. `read` is an alias for `permission`, matching
  the existing enforcer.
- `tamper_before` is optional boolean. When `true`, the runner mutates the
  contract file after load and before the first step, to exercise the
  integrity gate. The mutation is implementation-defined (the vector only
  asserts the denial).

`expect`:

```json
{
  "decisions": ["ALLOWED", "PENDING", "ALLOWED"],
  "errors": [
    {"index": 1, "error_code": "ApprovalPendingError", "message_contains": "approval"}
  ]
}
```

- `decisions` is required and MUST have exactly one entry per scenario step.
  Values are the canonical decisions `"ALLOWED"`, `"DENIED"`, `"PENDING"`.
- A step that raises still records its decision; the error is captured in
  `errors`. `errors` is required when any step raises and MUST be `[]`
  otherwise. `index` is the zero-based scenario index. `error_code` is the
  canonical code. `message_contains` is a case-sensitive substring.
- The runner MUST assert that every expected error occurred at the expected
  index and that no unexpected error occurred.
- Timestamps are ignored. The vector MUST NOT depend on a wall clock.

Minimum v1 coverage (GE-3):

- declared permission allowed;
- undeclared permission denied;
- declared side effect allowed;
- declared approval point pending, then allowed after `approve`;
- undeclared side effect denied;
- tampered contract denied with a tamper/integrity error;
- draft mode: declared permission allowed;
- draft mode: undeclared permission denied;
- draft mode: irreversible side effect with empty approvals pending;
- draft mode: irreversible side effect allowed after `approve`;
- draft mode: reversible side effect allowed without approval;
- full mode: identical contract decisions except the provisional load cases
  (which live in `contract-model`).

### 6.6 Category: `trace-roundtrip`

Purpose: pin the trace bytes, including the additive `provisional` field.

`input`:

```json
{
  "jsonl": "{\"action_name\":\"...\",...}\n",
  "operation": "roundtrip" | "parse"
}
```

- `jsonl` is the exact input string, including newlines. It is a JSON string,
  so embedded quotes are escaped in the vector file.
- `operation` is `roundtrip` for parse-then-serialize, or `parse` for
  parse-only (used for rejection vectors).

`expect`:

```json
{
  "result": "roundtrip" | "parsed" | "rejected",
  "canonical_jsonl": "{\"action_name\":\"...\",\"provisional\":true,...}\n",
  "error_code": "TraceError",
  "message_contains": "unknown field"
}
```

- `result` is required.
- `canonical_jsonl` is required for `roundtrip` and MUST be byte-exact,
  including the trailing newline. It is the expected output of
  `TraceLog.from_jsonl(input).to_jsonl()`.
- `result: "parsed"` asserts parse success without asserting output bytes.
- `rejected` requires `error_code` and `message_contains`; it asserts
  `TraceError`.
- Canonical output uses sorted keys, compact separators, UTF-8, one object per
  line, newline-terminated, exactly as the current `TraceLog.to_jsonl()`.

Minimum v1 coverage (GE-3):

- full-mode entry without `provisional` round-trips byte-identically;
- draft-mode entry with `"provisional": true` round-trips byte-identically;
- absent `provisional` is accepted as full;
- `"provisional": null` is rejected;
- `"provisional": "true"` is rejected;
- an unknown field is rejected;
- a bad `hash_of_contract` is rejected;
- a non-ISO-8601 `timestamp` is rejected;
- an unknown `result` is rejected.

### 6.7 Canonical codes and matching

Cross-runtime vectors cannot compare host-language class names. They compare
canonical `error_code` strings:

| Canonical code | Meaning |
|---|---|
| `ContractViolationError` | undeclared action, load-time violation |
| `ApprovalPendingError` | approval boundary hit |
| `ProvisionalContractError` | full-mode load of a provisional contract, or draft-mode load of a non-provisional contract |
| `ContractValidationError` | schema/validation failure, including v1 + provisional |
| `TraceError` | malformed trace |
| `GuardrailViolationError` | rate/budget/fail-closed denial |

A runtime maps its native error type to the canonical code at the runner
boundary. The mapping is part of the runtime's conformance, not an excuse to
skip a vector.

Matching rules are deliberately substring-based for messages and exact for
results:

- `decisions` and `canonical_jsonl`: exact.
- `result`: exact.
- `errors`: every expected entry must find a match; `path: null` matches any
  path; `message_contains` is a case-sensitive substring.
- No vector may assert a host-language exception class, a stack trace, an
  absolute path, a timestamp, a PID, or a memory address.

### 6.8 Determinism, versioning, and changelog

**Determinism.** A runner MUST produce byte-identical output for two runs over
the same suite:

```json
{"suite_version": 1, "total": 12, "passed": 12, "failed": 0, "failures": []}
```

- Canonical JSON: sorted keys, compact separators, UTF-8, one trailing newline.
- `failures` is sorted by `id`. Each failure is
  `{"id": "<vector-id>", "reason": "<stable sentence>"}`.
- `reason` MUST NOT contain an absolute path, a timestamp, a PID, or a memory
  address. It SHOULD identify the vector and the first mismatching field.
- Exit codes: `0` all pass, `1` at least one failure, `2` suite configuration
  error (missing/malformed `suite-version`, version/directory mismatch,
  duplicate ID, unknown category, non-canonical envelope).

**Versioning.**

- `suite-version` is a single monotonic integer. Any addition, removal, or
  change to a vector increments it by 1.
- Version `0` is the empty skeleton. A non-empty suite MUST be `>= 1`.
- The bump and the `CHANGELOG.md` entry MUST land in the same commit.
- `CHANGELOG.md` has one section per version:

  ```markdown
  ## [1] - 2026-11-20

  ### Added
  - `cm-0001-provisional-flag-valid` ...
  ```

  A semantic change to an existing vector is labelled `### Breaking` and MUST
  state which runtimes must change. Renaming or renumbering an ID is a
  breaking change and is discouraged; add a new ID and deprecate the old one
  in the changelog instead.

**Pinning.** Each runtime's CI MUST read `vectors/suite-version` and compare
it to its own `pinned_suite_version`. A mismatch fails the job with a message
naming both numbers and the required action ("update the runtime or revert the
suite bump; do not run a subset"). A runtime MUST NOT:

- skip a category because it is "not implemented yet";
- run a subset of vectors;
- accept a different suite version from another runtime;
- report a percentage pass as conformance.

Conformance at a version is all-or-nothing. If a runtime cannot implement a
category, it is not conformant at that version.

### 6.9 Runner obligations (non-normative)

The RFC does not require a specific runner language or package. It does
require any runner to:

1. Read `vectors/suite-version` first and fail closed on configuration errors.
2. Discover vectors by sorted ID, not by filesystem order.
3. Reject unknown envelope keys, wrong categories, wrong version numbers, and
   duplicate IDs.
4. Execute every vector; do not stop at the first failure.
5. Compare with the §6.7 rules.
6. Emit the canonical result object and exit code above.
7. Never write to `vectors/` or to the target contract.
8. Never import or execute the target implementation under test.

The Python runner ships first (GE-3). `scyvera-ts` and `scyvera-rs` implement
their own runners against the same bytes; the Python runner is the reference
semantics, not a dependency.

### 6.10 What is not in the v0/v1 suite

- **Promotion orchestration vectors.** Promotion is a human, registry, and
  re-seal flow. It is Python-orchestration only in v0/v1 because `scyvera-ts`
  and `scyvera-rs` do not own the audit CLI or the promotion command. The
  cross-runtime contract is the *artifact* (contract bytes, trace bytes, gate
  decisions), not the registry CLI. §8 Q5 records whether a future version adds
  a `promotion` category.
- **Audit rule vectors.** Audit stays a Python-tool capability per the GEP
  non-goals. The vector suite does not test AUxxx rules.
- **Skill vectors.** A skill is a distribution artifact, not a runtime. A5 is
  enforced by review and by the absence of a promotion tool, not by a vector.
- **Performance vectors.** No timing assertions; they are not deterministic
  across machines.

---

## 7. Threat Model Deltas

### 7.1 T1-T14 under provisional contracts

The table records the delta, not a restatement of the existing mitigation. The
existing threat documents remain authoritative for the base description.

| Threat | Existing status | Delta under RFC 0005 |
|---|---|---|
| **T1** Lifecycle downgrade | Planned (M4.1); T1 detection is not shipped | Draft mode MUST NOT claim T1 detection. A provisional contract still declares `lifecycle` and is validated the same way. The absence of sliding-window throttling is unchanged; §9.1 records the RFC 0002 conflict. |
| **T2** Idle behavior inflation | Enforced via AC301 | Unchanged. Draft mode does not relax `lifecycle.idle_behavior` validation or lint. |
| **T3** Mode enum expansion | Enforced by closed enum | Unchanged. `provisional` is not a lifecycle mode. |
| **T4** Gate bypass | Known limitation + `assert_gated` + gateway isolation | Unchanged. Draft mode is still a Python call-site gate. A5 prevents a skill from claiming otherwise. |
| **T5** File replacement | Enforced (hash + freeze) | Unchanged. `provisional: true` is inside the hashed bytes; flipping it on disk after load trips `verify_integrity()`. |
| **T6** Permission spoofing | Known limitation + review | Unchanged. Generation MUST NOT invent authority (§3.4), which reduces the review surface but does not eliminate spoofing inside a declared action. |
| **T7** Wildcard injection | Enforced | Unchanged and explicitly not relaxed in draft mode. |
| **T8** Empty approval points | Enforced as a load-time warning | **Strengthened in draft mode**: an irreversible action is PENDING even when `approval_points`/`approvals` is empty. Full mode retains the warning behavior; §8 Q2 records whether full mode should adopt the same gate. |
| **T9** Audit tampering | Enforced (frozen, deep copy) | Unchanged. The additive `provisional` field is inside the frozen record; stripping it from a returned copy does not affect the internal log. |
| **T10** Schema version confusion | Enforced | Unchanged, plus a new rule: `provisional` is not a version and is rejected on v1. |
| **T11** Dependency confusion | Planned (attestation) | Unchanged. Vectors reduce semantic drift, not supply-chain risk. The suite version SHOULD be recorded in the release manifest (§8 Q7). |
| **T12** Contract substitution | Re-seal ritual + identity pinning | **Strengthened**: draft -> full requires a `PromotionIntent`; full-mode load with a draft registry history fails closed. The residual is a registry-less load of a hand-edited former draft (§7.3). |
| **T13** Registry rewrite | Enforced by hash chain | **Extended**: `draft` and `promotion` participate in the conditional canonical bytes. Removing or editing them breaks the chain. Old entries remain byte-identical. |
| **T14** Symlink/path abuse | Enforced | Unchanged. The vector suite also refuses symlinked roots/categories. |

### 7.2 New threat T15: permanent draft / draft-mode abuse

**Description.** An adversary, or an inattentive operator, keeps an agent in
draft mode indefinitely. The draft becomes the permanent production mode, so
the human promotion gate is never exercised, the contract is never reviewed at
the full bar, and downstream consumers see a "governed" environment that is
actually permanently provisional. A related variant generates many drafts and
promotes none, using the provisional state as cover for capability sprawl.

**Why the existing threats do not cover it.** T12 covers *substitution* (a
contract changed without re-seal). T15 covers *stasis* (a contract that is
honestly provisional and stays that way). The contract is not tampered with; it
is simply never promoted.

**Mitigations (normative where stated):**

1. **Visible marking.** Every report, audit entry, trace entry, and governance
   status MUST mark a provisional contract as provisional (§4.4, §4.5). There
   is no silent draft.
2. **Registry flag.** The draft entry carries `draft: true` in the chain
   (§3.3). Deleting the flag breaks the chain; adding it to a full entry is a
   consistency failure.
3. **Age and count surfacing.** `scyvera audit` and `scyvera check` SHOULD
   report the number of provisional contracts and the age of the oldest draft
   (derived from `registered_at`). They MUST NOT auto-promote on age. Expiry
   may warn or refuse a release; it may never promote (§8 Q3).
4. **Release boundary.** A release artifact MUST NOT ship a provisional
   contract as its governing contract. A release check SHOULD fail closed when
   the packaged contract is provisional. A provisional contract is a working
   state, not a shipped state.
5. **No relaxed irreversible gate.** The one thing an operator might want from
   permanent draft - fewer approvals - is explicitly not available: A2 applies
   even in draft mode. Permanent draft buys no destructive authority.
6. **Promotion is not automatic.** A4 forbids time-based, event-based, and
   agent-executed promotion. The only exit from T15 is a human.

**Residual risk.** A registry-less full-mode load of a file whose
`provisional` line was manually removed is indistinguishable from a new full
contract. The enforcement of T12/T15 therefore depends on production flows
passing `registry=` (the existing M1.3 identity cross-check). §8 Q9 asks
whether to make the registry mandatory for full-mode loads.

### 7.3 Residual risks

- **Human identity is procedural.** The engine records a reviewer string and
  an intent string, not a cryptographic identity. A dishonest human can enter
  any name. §8 Q10 asks whether to bind the intent to a signature.
- **Registry-less loads.** See T15 residual above.
- **Closed verb set is a floor.** An irreversible action outside the set and
  not declared `irreversible: true` is not caught by A2. The mitigation is
  review and the finding-backed generation rule.
- **Generation is static.** It sees files, not runtime behavior. A target that
  hides a capability from static analysis produces an incomplete draft. Draft
  mode's declaration gate still denies the hidden action at runtime, but the
  draft will not predict it.
- **Cross-runtime error text.** Vectors use `message_contains`, not exact
  messages, to tolerate wording differences. This weakens the pin slightly;
  the canonical `error_code` carries the semantic weight.

---

## 8. Open Questions

These are explicit and unresolved. GE-2/GE-3 may implement the candidate
resolution, but the question stays recorded until a follow-up RFC or an
accepted amendment closes it.

| # | Question | Candidate resolution / owner |
|---|---|---|
| **Q1** | Does draft mode rate-limit or budget *above* full mode? A draft is more likely to be exploratory, so a conservative cap could reduce blast radius, but it could also make draft mode unusable and pressure premature promotion. | Candidate: draft mode defaults to RFC 0003 §C5 `rate_limit` and `budgets` with conservative values when the contract omits them; the caps are not normative in v1. Owner: GE-2. |
| **Q2** | Should full mode adopt the same irreversible default-deny as draft mode, closing the T8 "warning only" gap? | Candidate: yes in a follow-up RFC, because "even in draft mode" implies full mode is at least as strict. This RFC deliberately does not change full-mode T8 behavior to avoid an unannounced break. Owner: a future RFC, not GE-2. |
| **Q3** | Does the registry draft flag need an expiry or maximum age? | Candidate: no automatic expiry and no automatic promotion. `audit`/`check` warn after a configurable threshold (for example 14 days) and a release check refuses provisional contracts. Expiry may only warn or demote, never promote. Owner: GE-2/GE-3. |
| **Q4** | Is a second reviewer required for high-risk promotions (for example, a diff that adds an irreversible side effect or removes an approval)? | Candidate: yes, `--second-reviewer` becomes required when the diff touches `side_effects` `irreversible`, `approvals`, or `permissions`. Owner: GE-2. |
| **Q5** | Does promotion orchestration join the cross-runtime vector suite? | Candidate: not in v1. Promotion is a registry/CLI flow; `scyvera-ts` and `scyvera-rs` consume its artifacts. If a shared promotion library ships, add a `promotion` category in v2. Owner: GE-3. |
| **Q6** | May draft mode allow only finding-backed actions (actions with audit/Tier 1 provenance), refusing hand-added authority until promotion? | Candidate: yes as a SHOULD for generated drafts; a hand-authored draft may add actions because a human wrote them. Enforcing provenance would require storing finding IDs in the contract. Owner: GE-2/GE-3. |
| **Q7** | Should the release attestation bind the vector suite version and suite digest? | Candidate: yes. The release manifest gains `vector_suite_version` and `vector_suite_sha256` so consumers can prove which acceptance corpus a wheel was tested against. Owner: a future release-pipeline task. |
| **Q8** | Should `scyvera check` warn or fail on a provisional contract? | Candidate: warn at Tier 0/1, fail at Tier 2 (a runtime-trace claim on a draft is not a production conformance claim). Owner: GE-3. |
| **Q9** | Should full-mode load require `registry=` so the draft history check cannot be skipped? | Candidate: deprecate registry-less production loads; keep the optional argument for backward compatibility and for synthetic tests. A hard requirement is a breaking API change and needs a separate RFC. Owner: a future RFC. |
| **Q10** | How is the reviewer's identity bound to the promotion (beyond a self-asserted string)? | Candidate: a signed `PromotionIntent` (Sigstore keyless or a commit signature) and a `reviewer_identity` field in the receipt. Owner: a future security RFC. |
| **Q11** | What happens when two promotions race on the same draft entry? | Candidate: compare-and-swap on `from_entry_id`; the second promotion fails with `ResealError("promotion", "stale from_entry_id")`. The registry is append-only, so the loser does not corrupt the chain. Owner: GE-2. |
| **Q12** | Are approvals granted in draft mode carried across promotion? | Candidate: no. Approvals are per-enforcer session (existing behavior); promotion starts a fresh enforcer. A human must approve again in full mode. Owner: GE-2. |
| **Q13** | Does a no-op promotion (same content, only the flag removed) need an explicit diff entry? | Yes by §5.2: the `/provisional` removal is the diff. A promotion with no changes at all fails. No open semantic question remains; listed to pin the answer. Owner: GE-2. |
| **Q14** | Should `provisional` be allowed on v1.2 guardrail contracts? | Candidate: yes, v1.1 and v1.2. v1 is excluded. The field is version-agnostic above 1.1. Owner: GE-2. |

---

## 9. Conflicts Considered

The GEP rule is: conflicts are raised, never silently reworded. Each subsection
quotes the existing text verbatim and states the resolution. If a future edit
to the quoted RFC changes the quote, this section must be revisited.

### 9.1 RFC 0002 §4 claims T1 detection that is not shipped

RFC 0002 §4, item 1 says:

> **Runtime Enforcement**: The `ContractEnforcer` can detect lifecycle downgrade attacks (T1) by validating invocation frequencies against declared lifecycle modes.

RFC 0002's status note also says:

> Sliding-window invocation tracking (Threat T1 mitigation) is planned on the roadmap.

Roadmap M4.1 is still open ("Sliding-window invocation throttling ... real
burst detection"). The first sentence overstates what ships today. **Resolution:**
RFC 0005 does not repeat the claim. A provisional contract is validated for
lifecycle structure, not for invocation frequency. Draft mode MUST NOT be
described as T1 detection. The M4.1 gap remains visible; this RFC does not close
it and does not depend on it. GE-2's acceptance tests MUST NOT assert T1
detection.

### 9.2 RFC 0003 §C1 chain serialization vs additive fields

RFC 0003 §C1 says:

> Extend `ContractRegistry` so every appended `RegistryEntry` carries a `prev_hash` field - the SHA-256 of the immediately preceding serialized entry (or a fixed genesis value `"0" * 64` for the first entry).

and:

> The chain is recomputable from the file alone: given a valid `registry.jsonl`, `verify_chain()` must succeed if and only if every entry in sequence has `prev_hash == SHA-256(serialized previous entry)`.

The shipped `canonical_entry_bytes()` uses `json.dumps(asdict(entry), separators=(",", ":"))`. Adding `draft` and `promotion` as dataclass fields would add keys to *every* serialized entry, changing the hash of historical entries and breaking every existing chain. **Resolution:** conditional serialization (§3.3): `draft` only when `True`, `promotion` only when not `None`. When both are absent, the bytes are identical to the pre-RFC-0005 encoding, so historical chains verify unchanged. New entries with the fields include them in the hash input, preserving the "recomputable from the file alone" invariant. This is an additive extension of the serialization rule, not a redefinition of the chain.

### 9.3 RFC 0003 §C4 exact trace shape vs additive `provisional`

RFC 0003 §C4 says:

> **Trace entry** (flat, JSON-serializable): `{node_id, action_name, action_type, declared, result: {allowed | pending_approval | violation}, hash_of_contract, timestamp}`.

The shipped `TraceEntry` already adds `reason` and `contract_field_reference`
beyond that shape (roadmap M1.2), so the RFC's shape was already a floor, not a
closed set. RFC 0005 adds one more optional field, `provisional`. **Resolution:**
`provisional` is additive and optional. It is emitted only when `true`; a
full-mode trace omits it and is byte-identical to the pre-RFC-0005 output.
`from_dict()` accepts absence as `false` and rejects non-boolean values. The
RFC 0003 §C4 core fields and result vocabulary are unchanged. The roadmap
glossary's shorthand `contract_hash` is not the serialized field name; the
serialized name remains `hash_of_contract`, and this RFC uses the serialized
name.

### 9.4 RFC 0003 §C6 skill instruction vs agent-side authority

RFC 0003 §C6 says the harness skill should:

> refuse to regenerate contracts that violate T12 re-seal ritual rules.

That is a *refusal* instruction, which is compatible with A5 but insufficient
by itself: a skill that refuses to regenerate still might be asked to promote.
**Resolution:** A5 extends the refusal to promotion. A skill MUST NOT run
`scyvera promote`, MUST NOT construct a `PromotionIntent`, and MUST NOT edit
`provisional` in an automated flow. The skill's job is to teach the human the
command and show the diff, not to exercise authority. This is a strengthening
of RFC 0003 §C6's intent, not a contradiction.

### 9.5 RFC 0004 §1 "generated from the repo" vs inference authority

RFC 0004 §1 says:

> **the contract is generated from the repo as a byproduct of analysis**

Read alone, that sounds like the repo's analysis becomes the authority. It does
not: RFC 0004 generates a *draft artifact* for a human to adopt. **Resolution:**
RFC 0005 makes the lifecycle explicit. Generation produces a provisional
contract on disk; it never produces a loadable full contract; a full-mode
enforcer refuses it until human promotion. "Generated from the repo" is
preserved as the adoption mechanism, but the generated artifact is explicitly
non-authoritative until promoted. This is the GEP's "inference-derived
authority is a trap" non-negotiable made structural.

### 9.6 RFC 0004 §5 zero-warning bar vs zero-error bar

RFC 0004 §5 says:

> **Hard QA rule**: every generated draft must PASS `validate_contract()` on v1.1 and `lint_contract()` with zero warnings.

RFC 0005 §3.4 requires zero errors at generation time and treats zero warnings
as the stronger target. The difference matters because a warning can be a true
statement about the target (for example, an unused declaration) and blocking
generation on it would make the draft lie or fail. **Resolution:** the
generated draft MUST pass validation and MUST have zero error-severity lint
warnings, matching the reseal bar. It SHOULD have zero warnings, matching RFC
0004 §5. GE-2's generation test MUST assert validation and zero errors; it
SHOULD assert zero warnings for the fixture corpus where the target does not
legitimately produce one. If a future decision wants the strict zero-warning
bar, it must be raised as an amendment to RFC 0004 or RFC 0005, not silently
tightened in code.

### 9.7 RFC 0004 §10 critical-only irreversibility vs draft-mode floor

RFC 0004 §10 says:

> **Resolution**: Yes for critical severity, and only those - an audit-drafted contract should never mark a `medium` finding as irreversible; that level of constraint belongs to a pack or to the user editing the one line.

RFC 0005 adopts this for generation (§3.4) and adds an independent runtime
floor: the closed verb set (§4.3) can make an action irreversible in draft mode
even if generation did not mark it. Is that a contradiction? **Resolution:** no.
RFC 0004 §10 governs *what the generator writes into the draft*: only critical
findings get `irreversible: true`. RFC 0005 §4.3 governs *how draft mode
decides at runtime*: an action whose text matches the closed verb set is
treated as irreversible for the approval gate even if the declaration is
silent. The generator remains conservative; the runtime remains fail-closed.
The two rules operate at different layers and are both required.

### 9.8 Roadmap M4.1 vs draft-mode scope

Roadmap M4.1 says:

> **Sliding-window invocation throttling** (from `threat-model-lifecycle.md` T1 and RFC 0002) - real burst detection inside `ContractEnforcer` for `lifecycle.busy`/downgrade attacks

Draft mode could be mistaken for a lifecycle mode and therefore for an M4.1
dependency. **Resolution:** draft mode is a contract-status mode, not a
lifecycle mode. It does not track invocation frequency, does not implement T1,
and does not change `lifecycle.mode`. M4.1 remains an independent, optional
post-release upgrade. A provisional contract still carries a normal lifecycle
block and is validated for it.

### 9.9 Summary of resolutions

| Conflict | Resolution |
|---|---|
| RFC 0002 §4 T1 claim | Do not repeat; M4.1 remains open; draft mode is not T1 detection. |
| RFC 0003 §C1 chain bytes | Conditional serialization preserves old bytes; new fields hash when present. |
| RFC 0003 §C4 trace shape | `provisional` is optional and omitted when false; core shape unchanged. |
| RFC 0003 §C6 skill | Extend refusal to promotion; skills hold no authority. |
| RFC 0004 §1 generated authority | Generation yields a provisional on-disk contract, never full authority. |
| RFC 0004 §5 zero warnings | Zero errors mandatory, zero warnings targeted. |
| RFC 0004 §10 critical-only | Generator stays critical-only; runtime adds the closed-verb floor. |
| Roadmap M4.1 | Draft mode is not a lifecycle mode and does not implement T1. |

---

## Appendix A. Normative anchor index

For GE-2/GE-3 acceptance tests, the six anchors are reproduced here as plain
sentences. They are normative in their owning sections; this appendix is an
index, not a second source.

1. A runtime MUST NOT perform inference-time enforcement without a provisional contract on disk. (§3.4)
2. Irreversible actions MUST default-deny with an approval gate even in draft mode. (§4.2)
3. Promotion MUST be human-only and MUST use the existing re-seal machinery. (§5.1)
4. Promotion MUST NOT be silent or automatic. (§5.3)
5. Agent-side skills MUST hold no authority over contracts. (§5.6)
6. Every runtime MUST pass the same pinned conformance-vector suite version. (§6.2)

## Appendix B. References

- [RFC 0002: Lifecycle Field for Agent Contracts v1.1](0002-lifecycle-field.md)
- [RFC 0003: Harness Distribution, Conformance Evaluation & Integrity Layer](0003-harness-distribution-eval-and-integrity.md)
- [RFC 0004: `scyvera audit` - Auto-Contracts, Blast Radius Reports & Policy Packs](0004-audit-cli-blast-radius-and-policy-packs.md)
- [`docs/roadmap.md`](../docs/roadmap.md) - GEP non-negotiables, GE-1/GE-2/GE-3 rows
- [`docs/threat-model-enforcer.md`](../docs/threat-model-enforcer.md) - T4-T10
- [`docs/threat-model-lifecycle.md`](../docs/threat-model-lifecycle.md) - T1-T3
- [`docs/threat-model-distribution.md`](../docs/threat-model-distribution.md) - T11-T14
- [`src/scyvera/reseal.py`](../src/scyvera/reseal.py) - re-seal ritual
- [`src/scyvera/registry.py`](../src/scyvera/registry.py) - registry entries and versioning
- [`src/scyvera/chain.py`](../src/scyvera/chain.py) - canonical entry bytes
- [`src/scyvera/enforcer.py`](../src/scyvera/enforcer.py) - gate pipeline
- [`src/scyvera/trace.py`](../src/scyvera/trace.py) - trace schema
- [`src/scyvera/evals/case.py`](../src/scyvera/evals/case.py) - fail-closed YAML conventions
- [`src/scyvera/generate.py`](../src/scyvera/generate.py) - draft generation
