# Agent Contracts v1.1 — Contract Model
Status: Draft
Specification Version: 1.1
Project: Agent Contracts

---

# 1. Purpose

This document defines the conceptual and structural model for Agent Contracts v1.1.

The Contract Model translates the terminology defined by the Agent Contracts project into a practical machine-readable representation.

The purpose of the model is to describe the operational boundary of an intelligent or automated system in a way that can be:

- understood by humans,
- validated by software,
- evaluated by policy systems,
- consumed by governance tooling,
- extended across domains,
- and represented consistently across different implementations.

The model is intentionally independent of:

- programming language,
- Agent framework,
- workflow engine,
- model provider,
- deployment environment,
- industry,
- and implementation architecture.

The model is therefore not restricted to a particular category of Agent or automation system.

It is intended to support systems including, but not limited to:

- autonomous Agents,
- AI assistants,
- research systems,
- educational systems,
- business automation,
- financial automation,
- healthcare systems,
- customer-support systems,
- browser and data systems,
- enterprise automation,
- model-driven applications,
- multi-agent systems,
- and conventional automated workflows with meaningful operational boundaries.

---

# 2. Design Goals

The v1.1 Contract Model has the following goals.

## 2.1 Domain Independence

The core model MUST NOT assume that a system is:

- a coding Agent,
- a GitHub Agent,
- an n8n workflow,
- a chatbot,
- a research Agent,
- an educational Agent,
- or any other particular domain-specific system.

Different systems SHOULD be representable using the same core concepts.

For example, a research assistant, financial automation system, educational tutor, and software-development Agent may all use the same concepts of:

- capabilities,
- resources,
- permissions,
- constraints,
- side effects,
- dependencies,
- state,
- recovery,
- replay,
- and observability.

The domain-specific meaning of a resource or action MAY vary, but the underlying governance model remains consistent.

---

## 2.2 Framework and Implementation Independence

The model MUST NOT require a specific:

- framework,
- orchestration platform,
- programming language,
- model provider,
- runtime,
- deployment architecture,
- or implementation technology.

Agent Contracts is not designed exclusively for:

- n8n,
- LangGraph,
- coding Agents,
- GitHub systems,
- chatbot systems,
- or any other single implementation category.

Implementation details MAY be represented as optional metadata when useful.

For example:

```yaml
implementation:
  framework: n8n
```

---

# 3. Machine-Readable Semantics

The Contract Model SHOULD represent governance-relevant properties structurally rather than relying exclusively on free-form text.

For example, a permission SHOULD identify the resource and action separately where those properties need to be evaluated by software.

Natural-language descriptions MAY supplement structured fields but SHOULD NOT replace them when reliable machine evaluation is required.

---

# 4. Progressive Complexity

The model MUST support Contracts of different levels of complexity.

A simple system SHOULD be describable with a small Contract, while a sophisticated system MAY declare capabilities, resources, inputs, outputs, permissions, constraints, side effects, approvals, dependencies, state, recovery, replay, and observability.

Users MUST NOT be required to understand every advanced governance concept merely to describe a simple system.

---

# 5. System Identity

The `system` section provides identity and high-level context for the system being described.

In specification version 1.1, `system:` is the preferred identity representation, reflecting that Agent Contracts applies to all intelligent and automated systems (including workflows, decision support engines, data pipelines, and AI assistants). An "Agent" is one possible type of system.

For backward compatibility:
- `system:` is the preferred v1.1 identity representation.
- `agent:` remains fully supported as a backward-compatible alias.
- `workflow:` remains supported as a legacy alias for identity name.

Example (Preferred v1.1):

```yaml
version: 1.1

system:
  name: Clinical Information Assistant
  purpose: Summarizes patient electronic health records for treating physicians
  version: "1.0.0"

domain: healthcare
```

---

# 5.1 Domain Classification vs. Risk Nature

The top-level `domain` field identifies the operational/application domain of the system (e.g. `healthcare`, `finance`, `education`, `research`, `software`, `business`).

The `domain` field is distinct from `risk.category`.
- `domain` describes the **operational domain** (e.g., `domain: healthcare`).
- `risk.category` describes the **nature of the potential failure or impact** (e.g., `category: privacy_breach` or `category: financial_loss`).

---

# 6. Specification Version

The top-level `version` field identifies the Agent Contracts specification version to which the Contract conforms.

Example:

```yaml
version: 1.1
```

The specification version is distinct from the system version, model version, framework version, and implementation version.

A Contract MUST NOT silently combine incompatible specification semantics.

---

# 7. Capabilities

The `capabilities` section describes classes of operations the system is capable of performing.

Example:

```yaml
capabilities:
  - analyze_documents
  - generate_summaries
```

A capability describes potential ability. It does not by itself grant authorization.

For example, a system may have the capability to initiate a transaction while being permitted to do so only below a defined limit and only after approval.

---

# 8. Resources

The `resources` section describes entities with which the system may interact.

Resources may include:

- documents,
- datasets,
- files,
- databases,
- APIs,
- websites,
- financial accounts,
- communication systems,
- external services,
- devices,
- or other domain-specific entities.

Example:

```yaml
resources:
  - type: research_documents
    access: read
```

Resource declaration does not itself establish authorization.

---

# 9. Inputs

The `inputs` section describes information, requests, or resources entering the system's operational context.

Examples include user questions, documents, datasets, images, records, API requests, and sensor data.

Example:

```yaml
inputs:
  - name: document
    type: file
  - name: question
    type: text
```

Input declaration does not automatically establish trust, provenance, confidentiality, or redistribution rights.

---

# 10. Outputs

The `outputs` section describes information or artifacts produced by the system.

Examples include summaries, recommendations, classifications, reports, generated documents, API responses, and status information.

Example:

```yaml
outputs:
  - name: research_summary
    type: document
```

An output is not necessarily a side effect. Producing a report and publishing that report to an external system are distinct concepts.

---

# 11. Permissions

The `permissions` section describes actions the system is authorized to perform against declared resources.

Example:

```yaml
permissions:
  - resource: research_documents
    actions:
      - read
```

A permission answers:

> What is the system authorized to do?

Permissions SHOULD be represented structurally so that a validator or policy engine can inspect resource, action, and scope independently.

---

# 12. Constraints

The `constraints` section describes limits placed on otherwise authorized behavior.

Examples include transaction limits, approved recipients, allowed data sources, geographic restrictions, time restrictions, rate limits, and environment restrictions.

Example:

```yaml
constraints:
  - type: transaction_limit
    maximum: 1000
    currency: USD
```

A constraint answers:

> What limits apply to the authorized operation?

---

# 13. Actions

An action is an operation performed against a resource or within the system's operational environment.

Actions SHOULD be represented using stable, implementation-independent terminology.

Examples include:

```text
read
write
create
update
delete
execute
publish
send
transfer
analyze
```

The vocabulary MAY be extended for domain-specific operations, provided that extensions do not redefine the meaning of the core model.

---

# 14. Side Effects

The `side_effects` section describes externally observable changes caused by system operations.

Examples include sending a message, modifying a record, publishing information, creating a transaction, changing a file, triggering another system, or changing a physical device.

Example:

```yaml
side_effects:
  - type: database_write
    resource: customer_records
```

Side effects SHOULD be declared when they are relevant to safety, security, privacy, financial risk, governance, compliance, or operational control.

---

# 15. Approvals

The `approvals` section describes operations that require explicit authorization before execution.

Example:

```yaml
approvals:
  - action: publish
    required: true
    approver: human
```

Approval requirements MAY depend on an action, resource, side effect, risk level, or condition.

An approval declaration describes a governance requirement; it does not prove that the implementation enforces it.

---

# 16. Dependencies

The `dependencies` section describes external systems, services, models, data sources, or components required by the system.

Examples include model providers, databases, APIs, authentication services, cloud services, and external tools.

Example:

```yaml
dependencies:
  - type: language_model
    name: model-provider
    required: true
```

Dependencies SHOULD be identifiable as required or optional when that distinction affects behavior.

---

# 17. State

The `state` section describes information that persists or influences behavior across execution boundaries.

Example:

```yaml
state:
  persistence: session
```

A Contract MAY describe persistence, storage, scope, and retention where these properties matter to governance.

The model SHOULD distinguish transient execution data from persistent state where that distinction affects privacy, security, or operational behavior.

---

# 18. Recovery

The `recovery` section describes intended behavior when an operation or dependency fails.

Example:

```yaml
recovery:
  strategy: human_escalation
```

Possible strategies include stopping, retrying, falling back, rolling back, escalating to a human, or resuming from a known state.

Recovery is declarative and does not prove that the implementation follows the declaration.

---

# 19. Replay

The `replay` section describes the expected behavior and safety of repeating an operation or execution.

Example:

```yaml
replay:
  mode: idempotent
```

Conceptual replay modes include:

- idempotent,
- non_idempotent,
- conditional,
- prohibited.

Replay semantics are particularly important when operations create external side effects.

---

# 20. Observability

The `observability` section describes what evidence about system activity is available.

Example:

```yaml
observability:
  level: audit
```

Observability MAY include logs, events, execution traces, audit records, metrics, and other evidence.

Observability describes available evidence; it does not itself establish that the system behaved correctly.

---

# 21. Human Readability

Although the Contract is machine-readable, it SHOULD remain understandable to humans.

The model SHOULD avoid unnecessary technical complexity and SHOULD use descriptive names and clear structures.

Contracts should be reasonably understandable by developers, researchers, technical operators, governance teams, and non-specialist stakeholders where practical.

---

# 22. Structured Data and Free-Form Text

Free-form descriptions MAY provide useful context.

For example:

```yaml
purpose: >
  Helps researchers compare scientific literature.
```

However, free-form text SHOULD NOT be the only representation of an operational property when reliable machine evaluation is required.

For example, a sentence describing a transaction limit is less suitable for automated evaluation than a structured numeric constraint.

---

# 23. Domain Independence

The same Contract concepts MUST be usable across different domains.

The project MUST NOT make GitHub, software development, coding, or issue tracking assumptions part of the core model.

The following are valid application domains, among others:

- education,
- research,
- finance,
- business,
- healthcare,
- enterprise automation,
- customer support,
- browser automation,
- data analysis,
- software engineering,
- and personal productivity.

Domain-specific semantics SHOULD be expressed through resource and action values or future extensions rather than by redefining the core Contract.

---

# 24. Framework Metadata

Framework-specific information MAY be represented as optional implementation metadata.

For example:

```yaml
implementation:
  framework: n8n
```

or:

```yaml
implementation:
  framework: langgraph
```

Framework metadata MUST NOT determine the meaning of the core Contract.

A Contract should remain semantically meaningful when implementation metadata is absent.

---

# 25. Core and Extensions

The v1.1 Contract Model defines a domain-independent core.

Domain-specific requirements SHOULD NOT automatically become core fields.

Potential future extensions may include healthcare controls, financial compliance controls, education metadata, browser permissions, cloud deployment controls, framework adapters, organization-specific policies, security controls, provenance, and evidence.

Extensions SHOULD build on the core rather than redefine it.

---

# 26. Contract Semantics

The following distinctions are normative design principles:

```text
Identity
    = system (preferred), agent (alias), workflow (legacy alias).

Domain
    = Operational application domain (e.g. healthcare, finance, education).

Capability
    = What the system can potentially do (semantic intent).

Permission
    = What the system is authorized to do against a declared resource.

Action
    = Recommended operation verb (e.g. read, write, execute, query, transfer).

Constraint
    = What limits apply.

Approval
    = What requires explicit authorization.

Side Effect
    = What external change may occur.
```

Likewise:

```text
Contract Declaration
    = What is required or claimed (e.g. integrity_required: true).

Security Verification
    = External checking of hashes, signatures, certificates, or attestations.

Runtime Enforcement
    = Active interception by proxies, API gateways, or sandbox runtimes.

Implementation
    = What is deployed or executed.

Observation
    = What was observed.

Evidence
    = What supports a claim.

Policy
    = What is acceptable.
```

These concepts MUST NOT be treated as interchangeable.

---

# 27. Validation Boundary

The v1.1 validator is responsible for determining whether a Contract conforms to the structural and semantic requirements defined by the specification.

Validation SHOULD cover:

- required structure,
- data types,
- allowed values,
- structural relationships,
- specification version compatibility,
- and specification-defined constraints.

Validation MUST NOT claim to prove that:

- a system is safe,
- a system is secure,
- an implementation behaves exactly as declared,
- a dependency is trustworthy,
- a model is malware-free,
- or a Contract is legally compliant.

Those are separate verification or governance concerns. Declared security requirements (e.g. `artifacts[].integrity_required: true` or `security.sandbox_required: true`) declare governance policies for external tools to verify, but validation does not execute security scans or compute hashes.

---

# 28. Governance Boundary

The Contract Model is designed to provide structured information for future governance systems.

A governance layer MAY evaluate questions such as:

```text
Is this capability permitted?
Can this resource be accessed?
Does this action exceed its constraint?
Does this side effect require approval?
Is this dependency allowed?
Is replay acceptable?
Is sufficient observability available?
```

The Contract enables such evaluation but does not itself constitute a complete runtime governance engine.

---

# 29. Security Boundary

An Agent Contract describes an intended operational boundary. It is not itself a sandbox, security scanner, or execution isolation mechanism.

For example:

```yaml
permissions:
  - resource: database
    actions:
      - read
```

does not technically prevent an implementation from attempting an unauthorized operation.

Enforcement requires an implementation capable of interpreting and enforcing the Contract or an associated policy.

Therefore:

```text
Contract != Sandbox
Contract != Security Scanner
Contract != Runtime Enforcement
```

The Contract provides a machine-readable basis upon which such systems may operate.

---

# 30. Models, Data, and External Artifacts

The Contract Model does not assume that a model file, dataset, binary, document, package, or other external artifact is trustworthy merely because it is referenced by a valid Contract.

Artifact integrity, provenance, malware detection, supply-chain security, model-file inspection, and artifact trust are separate concerns.

This distinction is important because intelligent systems may depend on external artifacts that can themselves become part of a security or supply-chain threat.

Future governance or security extensions MAY describe requirements for:

- artifact provenance,
- integrity verification,
- trusted sources,
- artifact scanning,
- model validation,
- deployment controls,
- or approved artifact policies.

These capabilities SHOULD NOT be silently conflated with basic Contract structural validation.

---

# 31. Simplicity Principle

The Contract Model SHOULD remain as small as possible while preserving meaningful operational semantics.

A field SHOULD be added to the core only when it provides a broadly useful concept that cannot be adequately represented through existing concepts or extensions.

The project SHOULD prefer:

```text
Small core
    +
Structured semantics
    +
Extensions
    +
External policies
```

over a large universal schema containing every possible domain-specific requirement.

---

# 32. Extensibility Principle

The model MUST allow future evolution.

Future versions MAY introduce richer policy relationships, evidence references, provenance, runtime observations, security controls, compliance mappings, domain-specific extensions, framework adapters, and additional operational semantics.

Such functionality SHOULD be introduced without unnecessarily destabilizing the core concepts.

---

# 33. Compatibility Principle

Future implementations SHOULD preserve the semantic meaning of existing concepts wherever possible.

Breaking changes SHOULD result in an explicit specification version change.

The project MUST NOT silently change the meaning of an existing field while retaining the same specification version.

Compatibility rules SHOULD be defined alongside future normative schemas.

---

# 34. Example Contracts Across Domains

## 34.1 Educational System

```yaml
version: 1.1

agent:
  name: Study Tutor
  purpose: Helps students understand course material.

capabilities:
  - explain_concepts
  - generate_practice_questions

resources:
  - type: learning_material
    access: read

inputs:
  - student_question

outputs:
  - explanation
  - practice_questions

permissions:
  - resource: learning_material
    actions:
      - read

side_effects: []

approvals: []

state:
  persistence: session

observability:
  level: basic
```

## 34.2 Research System

```yaml
version: 1.1

agent:
  name: Literature Research Assistant
  purpose: Helps researchers compare scientific literature.

capabilities:
  - search_documents
  - analyze_documents
  - generate_summaries

resources:
  - type: research_documents
    access: read

permissions:
  - resource: research_documents
    actions:
      - read

side_effects: []

state:
  persistence: session

observability:
  level: basic
```

## 34.3 Business Automation

```yaml
version: 1.1

agent:
  name: Invoice Processing System
  purpose: Processes incoming invoices and updates business records.

capabilities:
  - read_invoices
  - extract_invoice_data
  - update_records

resources:
  - type: invoice
    access: read
  - type: business_database
    access: write

permissions:
  - resource: invoice
    actions:
      - read
  - resource: business_database
    actions:
      - write

side_effects:
  - type: database_write
    resource: business_database

approvals: []

state:
  persistence: persistent

recovery:
  strategy: stop

observability:
  level: audit
```

## 34.4 Healthcare System

```yaml
version: 1.1

agent:
  name: Clinical Information Assistant
  purpose: Organizes approved clinical information for professional review.

capabilities:
  - retrieve_records
  - summarize_records

resources:
  - type: clinical_records
    access: read

permissions:
  - resource: clinical_records
    actions:
      - read

constraints:
  - type: human_review_required
    actions:
      - clinical_recommendation

side_effects: []

approvals:
  - action: clinical_recommendation
    required: true
    approver: qualified_professional

observability:
  level: audit
```

This example demonstrates the model's domain independence. It does not establish clinical policy or medical compliance requirements.

## 34.5 Financial System

```yaml
version: 1.1

agent:
  name: Financial Operations Assistant
  purpose: Performs approved financial operations.

capabilities:
  - analyze_accounts
  - initiate_transactions

resources:
  - type: financial_account
    name: corporate_account

permissions:
  - resource: corporate_account
    actions:
      - initiate_transaction

constraints:
  - type: transaction_limit
    maximum: 1000
    currency: USD

side_effects:
  - type: financial_transaction
    resource: corporate_account

approvals:
  - action: initiate_transaction
    required: true
    approver: human

replay:
  mode: prohibited

observability:
  level: audit
```

---

# 35. Conceptual Architecture

The v1.1 Contract Model can be understood as the following relationship:

```text
                  INTELLIGENT / AUTOMATED SYSTEM
                               |
                               v
                        AGENT CONTRACT
                               |
       +-----------------------+-----------------------+
       |                       |                       |
       v                       v                       v
  Capabilities             Resources                Inputs
       |                       |                       |
       +-----------+-----------+                       |
                   v                                   |
                Actions                                |
                   |                                   |
             +-----+-----+                             |
             |           |                             |
             v           v                             |
        Permissions  Constraints                       |
             |           |                             |
             +-----+-----+                             |
                   v                                   |
               Approvals                               |
                   |                                   |
                   v                                   |
              Side Effects                             |
                                                       |
       +-----------------------------------------------+
       |
       +-- Outputs
       +-- Dependencies
       +-- State
       +-- Recovery
       +-- Replay
       +-- Observability
```

The broader governance relationship is:

```text
                         CONTRACT
                            |
              +-------------+-------------+
              |             |             |
              v             v             v
          Validation      Policy        Evidence
              |             |             |
              +-------------+-------------+
                            |
                            v
                       Governance
                            |
                            v
                   Runtime Observation
```

This separation allows Agent Contracts to evolve from structural validation into a broader governance interoperability layer without making the core model dependent on a particular framework, industry, or implementation.

---

# 36. Current Scope and Status

Version 1.1 focuses on establishing a strong, domain-independent Contract Model.

The immediate implementation priorities are:

1. Define the normative v1.1 JSON Schema.
2. Implement structural validation.
3. Add semantic validation where appropriate.
4. Update the test suite.
5. Create domain-neutral example Contracts.
6. Preserve framework and implementation independence.
7. Maintain a simple authoring experience.
8. Prepare the model for future policy, evidence, security, and runtime-governance layers.

Runtime enforcement, artifact security, provenance, advanced policy evaluation, and domain-specific governance are future capabilities unless explicitly incorporated into a later specification.

This document defines the **draft v1.1 Contract Model**. It is a design artifact and is not itself the normative JSON Schema.

The next implementation stage is to translate this model into:

```text
schemas/v1.1/contract.schema.json
```

and then update:

```text
validator
tests
CLI
example contracts
```

The JSON Schema MUST follow the semantics established by this Contract Model rather than independently introducing new concepts.
