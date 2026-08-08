# Agent Contracts v1.1 — Design Specification

Status: Draft
Specification Version: 1.1
Project: Agent Contracts

---

## 1. Problem Statement

AI agents increasingly interact with external systems rather than only generating text. An agent may read repositories, modify files, call APIs, execute tools, maintain persistent state, trigger external side effects, or perform actions that require human oversight.

The operational behavior of these systems is often described through implementation-specific configuration, source code, workflow definitions, prompts, or informal documentation. This makes it difficult to answer basic operational questions consistently across different agent frameworks:

- What resources can the agent access?
- What actions can it perform on those resources?
- What external side effects can it cause?
- Which actions require human approval?
- What state persists between executions?
- What happens when an execution is repeated?
- Which external systems does the agent depend on?
- How does the agent behave when those dependencies fail?
- What evidence exists for observing what the agent did?

Agent Contracts defines a framework-independent, machine-readable representation of these operational properties.

A Contract is not intended to describe the internal reasoning process of an agent. It describes the operational boundary within which the agent is expected to execute.

---

## 2. Limitation of Contract v1

Contract v1 established a common document structure for describing agent behavior, including:

- inputs
- outputs
- permissions
- side effects
- approval points
- recovery strategy
- replay semantics
- dependencies
- state
- observability

This provides a useful documentation and structural-validation layer.

However, several v1 fields allow operational behavior to be expressed primarily as free-form strings.

For example:

```yaml
permissions:
  - "github: contents:write"
```

or:

```yaml
recovery_strategy: >
  If GitHub fails, the workflow stops without pushing.
```

These declarations are understandable to humans but provide limited semantic information to automated tooling.

A validator can determine whether the fields exist and whether their YAML/JSON types are valid, but it cannot reliably determine relationships such as:

- whether a write capability has a corresponding declared side effect;
- whether a high-impact operation is protected by an approval boundary;
- whether persistent state is compatible with the declared replay behavior;
- whether a side effect requires a capability that was never declared;
- whether an external dependency has defined failure behavior.

Contract v1.1 introduces structured operational semantics so that Agent Contracts tooling can reason about these relationships.

---

## 3. Design Goal

The primary goal of Contract v1.1 is to make agent operational declarations machine-interpretable while remaining independent of the framework used to implement the agent.

The specification should support the following progression.

### Level 1 — Structural Validation

Determine whether a Contract conforms to the Agent Contract specification.

```text
contract.yaml
      |
      v
   validate
      |
   PASS / FAIL
```

Structural validation answers:

> Is this document a valid Agent Contract according to the declared specification version?

It does not determine whether the declarations are sensible or whether the implementation actually behaves as declared.

### Level 2 — Semantic Analysis

Determine whether individually valid declarations are operationally consistent with one another.

```text
contract.yaml
      |
      v
     lint
      |
 warnings / errors
```

Semantic analysis should eventually detect conditions such as:

- write capability without a corresponding side effect;
- side effect without a corresponding capability;
- high-impact operation without an approval boundary;
- persistent state without meaningful replay semantics;
- external dependency without defined failure behavior;
- side effect without sufficient observability.

### Level 3 — Implementation Inspection

Analyze an agent implementation and infer operational characteristics using framework-specific adapters.

```text
implementation
      |
      v
    inspect
      |
      v
observed capabilities
      +
    evidence
```

Inspection should map framework-specific implementation details into a common, framework-independent capability representation.

### Level 4 — Implementation Verification

Compare declared operational behavior with capabilities and effects observed or inferred from an implementation.

```text
contract.yaml --------+
                      |
                      v
                    verify
                      ^
                      |
implementation -------+
```

Verification should identify relationships such as:

- declared and observed capabilities that match;
- observed capabilities that were not declared;
- declared capabilities for which no implementation evidence was found;
- conflicting evidence;
- behavior that cannot be determined reliably.

### Level 5 — Runtime Assurance

Future runtime integrations may collect execution evidence and evaluate attempted actions against Contract declarations.

```text
agent execution
      |
      v
runtime evidence
      |
      v
contract policy evaluation
      |
      +---- allowed
      |
      +---- violation
```

Where supported, runtime integrations may also cooperate with existing authorization or isolation systems to prevent actions outside declared policy.

Contract v1.1 primarily establishes the semantic foundation required for these later assurance levels.

---

## 4. Design Principles

### 4.1 Framework Independence

The Contract MUST describe operational behavior without depending on concepts unique to a specific agent framework.

The same semantic model should be usable for implementations based on systems such as:

- plain Python;
- LangGraph;
- n8n;
- other agent or workflow frameworks.

Framework adapters may interpret implementations differently, but they should map observed behavior into the same Contract vocabulary.

For example:

```text
n8n workflow --------+
                     |
LangGraph graph -----+----> Capability Representation
                     |
Python agent --------+
```

The Contract itself should not need to change simply because the implementation framework changes.

### 4.2 Declarative Rather Than Implementation-Specific

Contracts describe what an agent is permitted or expected to do, not how its internal implementation performs those actions.

For example:

```yaml
resource: filesystem
actions:
  - write
```

is preferred over describing a particular Python function, n8n node, or LangGraph tool.

Implementation-specific details belong in adapters and evidence, not in the core Contract vocabulary.

### 4.3 Machine-Interpretable Semantics

Operationally significant concepts SHOULD use structured representations rather than unrestricted natural-language strings whenever reliable automated reasoning is required.

Human-readable descriptions may supplement structured declarations but should not be the sole representation of semantics required by validation, linting, inspection, or verification.

For example, this:

```yaml
capabilities:
  - resource: github.issues
    actions:
      - read
      - comment
```

provides stronger machine-readable semantics than:

```yaml
permissions:
  - "Can read issues and post comments to GitHub."
```

### 4.4 Explicit Operational Boundaries

The specification should make important boundaries visible, including:

- resource access;
- allowed actions;
- external side effects;
- approval requirements;
- persistent state;
- external dependencies;
- failure behavior;
- replay behavior;
- observability.

Absence of a declaration MUST NOT automatically be interpreted as permission.

A Contract should describe the declared operational boundary rather than rely on implicit assumptions.

### 4.5 Verifiability

Structured declarations SHOULD be designed so that future implementation adapters can map observed implementation behavior to the same semantic representation.

For example, a Contract declaration:

```text
resource = system.shell
action   = execute
```

and an implementation adapter detecting a subprocess invocation should be capable of producing an equivalent observed capability.

This common representation enables comparison between declared and observed behavior.

Conceptually:

```text
Declared Capability
        |
        v
  Common Semantic Model
        ^
        |
Observed Capability
```

### 4.6 Evidence Over Assumption

Future inspection and verification tooling should distinguish between behavior that is:

- confirmed;
- inferred;
- unknown;
- conflicting.

An implementation characteristic that cannot be determined reliably should be reported as unknown rather than assumed safe or compliant.

For example:

```text
filesystem.read       CONFIRMED
github.issues.write   INFERRED
dynamic_plugin.call   UNKNOWN
shell.execute         CONFLICTING
```

Evidence should be retained wherever practical so that conclusions can be traced back to their source.

### 4.7 Backward Compatibility

Contract v1 remains a valid historical specification.

Contract v1.1 MUST NOT silently change the interpretation of existing v1 Contracts.

Migration between specification versions should be explicit.

Tooling should be capable of determining which Contract specification version a document targets and selecting the corresponding validation behavior.

### 4.8 Progressive Assurance

Agent Contracts should provide increasing levels of operational assurance without representing weaker forms of analysis as stronger guarantees.

For example:

```text
VALID
  does not imply
SEMANTICALLY CONSISTENT

SEMANTICALLY CONSISTENT
  does not imply
IMPLEMENTATION VERIFIED

IMPLEMENTATION VERIFIED
  does not imply
ALL FUTURE EXECUTIONS ARE SAFE
```

Each assurance level should communicate precisely what was evaluated.

---

## 5. Scope of Contract v1.1

Contract v1.1 establishes the structured semantic foundation required for machine-readable declarations and semantic analysis.

The following capabilities are outside the immediate implementation scope of v1.1 but are explicit future directions of Agent Contracts:

- semantic linting over structured declarations;
- automatic Contract generation and initialization;
- framework-specific implementation adapters;
- static inspection of agent implementations;
- inference of observed capabilities and side effects;
- comparison of declared and observed behavior;
- detection of undeclared capabilities and Contract violations;
- evidence and confidence reporting;
- runtime behavioral observation and tracing;
- policy generation from Contract declarations;
- integration with runtime enforcement mechanisms.

These capabilities should build on the semantic model introduced by Contract v1.1 rather than requiring framework-specific Contract formats.

The intended long-term progression is:

```text
DECLARE
   |
   v
VALIDATE
   |
   v
LINT
   |
   v
INSPECT
   |
   v
VERIFY
   |
   v
RUNTIME ASSURANCE
```

The purpose of introducing structured semantics in v1.1 is therefore not limited to improving YAML validation.

It establishes a common operational vocabulary that future Agent Contracts tooling can use across declaration, analysis, implementation inspection, verification, and runtime evidence.

---

## 6. Permanent Non-Goals and Assurance Boundaries

Agent Contracts is not intended to:

- expose or depend on an agent's private chain-of-thought;
- replace operating-system, container, API, cloud IAM, or other authorization and isolation mechanisms;
- claim that structural Contract validity implies agent safety;
- guarantee that every possible execution of a nondeterministic agent will conform to its Contract;
- prove that an underlying AI model is universally safe;
- assume that static analysis can determine every possible runtime behavior.

Agent Contracts may inspect implementations, collect runtime evidence, detect Contract violations, and integrate with enforcement mechanisms.

These capabilities provide increasing levels of operational assurance, but they do not constitute proof of all possible future behavior.

The assurance levels are therefore distinct:

1. **Validation** — the Contract conforms to the specification.
2. **Semantic Analysis** — declarations are internally consistent according to defined rules.
3. **Inspection** — operational capabilities are inferred from implementation evidence.
4. **Verification** — declared behavior is compared with observed or inferred behavior.
5. **Runtime Assurance** — execution evidence is evaluated against the Contract and policy violations may be intercepted through supported enforcement integrations.

A successful result at one assurance level MUST NOT be represented as proof of a stronger assurance level.

For example:

```text
Contract validation:

PASS
```

means:

> The Contract conforms to the relevant Agent Contract specification.

It does NOT mean:

> The agent has been proven safe.

Likewise:

```text
Implementation verification:

No violations observed.
```

means that no violations were identified from the available implementation or execution evidence.

It does NOT establish that every possible future execution will conform to the Contract.

---

## 7. Planned Semantic Model

Contract v1.1 will define a structured operational model around the following concepts:

```text
Agent Contract
|
+-- Identity
|
+-- Capabilities
|   |
|   +-- Resource
|   +-- Action
|   +-- Scope
|
+-- Effects
|   |
|   +-- Type
|   +-- Target
|   +-- Reversibility
|
+-- Controls
|   |
|   +-- Approval Boundary
|
+-- State
|
+-- Replay Semantics
|
+-- Dependencies
|
+-- Failure Policy
|
+-- Observability
```

These concepts will form the semantic vocabulary used by future validation, linting, inspection, and verification tooling.

The exact schema and semantics of these concepts remain under design and are intentionally not finalized in this draft section.

In particular, the specification must clearly distinguish between:

- what an agent **can access or invoke**;
- what an agent is **declared to be allowed to do**;
- what externally observable **effects** an action can cause;
- which operations are subject to **control or approval boundaries**;
- what behavior is **observed from an implementation**.

These distinctions must be resolved before the Contract v1.1 JSON Schema is implemented.

---

## 8. Planned Semantic Rule System

Contract v1.1 is intended to support a semantic rule engine in addition to JSON Schema validation.

Rules will use stable identifiers grouped by operational concern.

The initial taxonomy is expected to follow this structure:

```text
AC1xx — Capabilities and Permissions
AC2xx — Human Control and Approval
AC3xx — State and Replay
AC4xx — Dependencies and Failure
AC5xx — Observability
AC6xx — Side Effects
AC7xx — Security Boundaries
```

Example candidate rules include:

```text
AC101
Write capability without a corresponding declared side effect.

AC102
Declared side effect without a corresponding capability.

AC201
High-impact operation without an approval boundary.

AC301
Persistent state without defined replay semantics.

AC302
Non-idempotent behavior without an explicit replay strategy.

AC401
Required external dependency without defined failure behavior.

AC501
Externally visible side effect without corresponding observability.
```

These identifiers and rules are provisional.

Before implementation, each semantic rule SHOULD define:

- rule ID;
- title;
- category;
- severity;
- rationale;
- detection conditions;
- expected evidence;
- remediation guidance;
- examples;
- known false-positive conditions.

This allows the semantic rule system to serve as both executable tooling and a formally documented part of the Agent Contracts specification.

---

## 9. Research Direction

The long-term research objective of Agent Contracts is to investigate whether a framework-independent machine-readable Contract can provide useful operational assurance for heterogeneous AI agent implementations.

A candidate research question is:

> Can a framework-independent machine-readable contract accurately describe and support verification of the operational boundaries of heterogeneous tool-using AI agents?

Potential technical contributions include:

1. a framework-independent Agent Contract model;
2. a structured capability and effect vocabulary;
3. formal semantic consistency rules for agent declarations;
4. a framework-independent intermediate representation for observed capabilities;
5. implementation-to-contract verification;
6. evidence and confidence models for behavioral inspection;
7. runtime evidence collection and policy evaluation;
8. an empirical benchmark for Contract violation detection.

Future evaluation should measure properties such as:

- capability detection precision;
- capability detection recall;
- Contract violation detection precision;
- Contract violation detection recall;
- F1 score;
- false-positive rate;
- false-negative rate;
- analysis runtime;
- framework portability;
- coverage of known operational violations.

A future benchmark may contain intentionally constructed or injected violations across implementations using multiple frameworks.

For example:

```text
Agent A
Declared: github.issues.read
Observed: github.issues.read
Expected: compliant

Agent B
Declared: github.issues.read
Observed: github.issues.write
Expected: undeclared capability violation

Agent C
Declared: no shell execution
Observed: system.shell.execute
Expected: undeclared capability violation

Agent D
Declared: human approval before external write
Observed: write path bypasses approval
Expected: control-boundary violation

Agent E
Declared: stateless
Observed: persistent state
Expected: state declaration violation
```

This evaluation layer is intentionally separate from the Contract specification itself.

---

## 10. Current Status

Agent Contracts v0.1 established the initial implementation foundation:

- Contract v1 JSON Schema;
- YAML-based Agent Contracts;
- Python validation API;
- `scyvera` command-line interface;
- repository-wide Contract validation;
- automated validator and CLI tests;
- installable Python distribution;
- bundled Contract schema;
- example Contracts across multiple implementation frameworks.

Contract v1.1 is currently in the design phase.

No v1.1 schema should be considered stable until the semantic model, versioning strategy, capability representation, and initial semantic invariants have been reviewed.

The immediate design work is:

1. define Contract version representation;
2. define Capability, Resource, Action, and Scope;
3. distinguish capability from permission;
4. define Effect semantics;
5. define Approval Boundary semantics;
6. structure State and Replay semantics;
7. structure Dependency and Failure semantics;
8. define Observability semantics;
9. formalize the initial ACxxx rule taxonomy;
10. define migration behavior from Contract v1.

Only after these decisions are made should implementation of the Contract v1.1 schema and semantic linter begin.