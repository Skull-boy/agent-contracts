# Agent Contracts Terminology
Status: Active (Normative Glossary)
Specification: Agent Contracts v1.1

---

## 1. Purpose

This document defines the terminology used by the Agent Contracts specification.

The purpose of this document is to ensure that core terms have consistent meanings across:

- contract authors,
- validators,
- governance systems,
- policy engines,
- runtime integrations,
- documentation,
- and independent implementations.

A term defined here SHOULD be interpreted according to this document unless a specification version explicitly defines a more specific meaning.

Terminology is part of the semantic foundation of Agent Contracts. Changes to the meaning of a core term SHOULD therefore be treated as specification-level changes rather than ordinary documentation edits.

---

## 2. Autonomous System

An **Autonomous System** is a software or computational system that can perform one or more actions on behalf of a user, organization, or another system with some degree of independent operation.

An autonomous system may:

- receive information,
- make decisions,
- invoke tools,
- access resources,
- modify state,
- communicate with external systems,
- or produce external side effects.

An autonomous system does not need to use a particular AI model, agent framework, workflow engine, or implementation architecture.

Examples may include:

- an AI research assistant,
- an educational tutoring system,
- a financial analysis agent,
- a customer-support agent,
- a software-development agent,
- a business automation system,
- a data-analysis system,
- or a multi-step system containing autonomous decision-making.

The term is intentionally broader than any particular definition of "AI agent."

---

## 3. Agent

An **Agent** is an autonomous system that performs actions or makes decisions on behalf of a user, organization, or another system within a defined operational context.

An Agent may use:

- language models,
- machine-learning models,
- deterministic logic,
- external tools,
- workflows,
- APIs,
- databases,
- browsers,
- physical devices,
- or combinations of these.

The term **Agent** is used by Agent Contracts as a practical shorthand for an autonomous system that is subject to a contract.

Agent Contracts does not require an Agent to use a particular architecture, model, framework, or implementation technique.

---

## 4. Agent Contract

An **Agent Contract** is a machine-readable declarative specification describing the declared operational characteristics and boundaries of an Agent or autonomous system.

A Contract may describe properties such as:

- capabilities,
- resources,
- actions,
- permissions,
- constraints,
- side effects,
- approvals,
- dependencies,
- state,
- recovery behavior,
- replay characteristics,
- and observability.

A Contract describes the operational boundary of a system.

It does not define:

- the system's internal reasoning,
- its implementation code,
- its private prompts,
- its model weights,
- its execution algorithm,
- or its internal architecture unless explicitly represented as an applicable extension.

A Contract is therefore a specification of operational properties rather than an implementation of the Agent itself.

---

## 5. Contract Version

A **Contract Version** identifies the version of the Agent Contracts specification against which a contract is intended to be interpreted and validated.

A Contract Version MUST be explicitly identifiable.

For example:

```yaml
version: "1.1"
contract_version: "1.1"
```

---

## 6. Runtime Enforcement

**Runtime Enforcement** is the active interception and gating of an agent's code execution, tool invocations, and external side effects against its declared contract.

Unlike passive documentation, runtime enforcement operates on **default-deny**: any action not explicitly declared in the contract is rejected with a `ContractViolationError`, and any action requiring human confirmation is halted with an `ApprovalPendingError`.

---

## 7. Contract Enforcer

A **Contract Enforcer** (`ContractEnforcer`) is the execution gatekeeper that loads, validates, cryptographically seals, and enforces an Agent Contract in memory at runtime.

It provides function gating decorators (`@enforcer.gate`), post-load integrity verification (`verify_integrity()`), and tamper-proof audit trail logging (`get_audit_log()`).

---

## 8. Gateway

A **Gateway** (`BaseGateway`, `GitHubGateway`, `QdrantGateway`) is an architectural enforcement boundary that isolates third-party API clients and credentials from agent logic.

By ensuring that external API tokens and client instances are held privately within the gateway class, and that every method is gated by an injected `ContractEnforcer`, gate bypass is structurally prevented at the integration layer.

---

## 9. Contract Registry

A **Contract Registry** (`ContractRegistry`) is a versioned, append-only, persistent record of every contract that has governed an agent in a deployment environment.

It records contract hashes, source declarations, registration timestamps, and version histories, enabling point-in-time time-travel queries (`get_at_time()`) to establish cryptographic provenance for governance and compliance.

---

## 10. Integrity Hash

An **Integrity Hash** is the SHA-256 cryptographic digest computed over the canonical representation of a contract file or dynamic runtime declaration at the moment of loading or creation.

It serves as a tamper detection seal against post-load tampering or disk modification.

---

## 11. Audit Log

An **Audit Log** is an immutable, chronological sequence of structured records (`AuditEntry`) produced by a Contract Enforcer, documenting every enforcement decision (allowed, denied, or pending human approval) along with timestamps, action names, and contract field references.