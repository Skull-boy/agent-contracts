# Agent Contracts Terminology
Status: Draft
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
version: 1