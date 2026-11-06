# Security Policy

Scyvera is a security boundary: it parses agent contracts, enforces permissions
and approvals at runtime, and audits repositories for risky capabilities. We
take reports about that boundary seriously, and we prefer private disclosure so
a fix can ship before users are exposed.

## Supported versions

| Version | Supported |
|---|---|
| 1.x | Yes — latest release only |
<!-- | 2.x | Yes, once released | -->

Only the latest published 1.x release on PyPI receives security fixes. Older
1.x releases, pre-release tags, and forks are not supported. If you are on an
older version, upgrading to the latest 1.x release is the first remediation
step.

## Reporting a vulnerability

**Use GitHub Security Advisories — do not open a public issue.**

1. Go to the repository's **Security** tab and choose **Report a vulnerability**:
   <https://github.com/Skull-boy/agent-contracts/security/advisories/new>
2. Describe the affected version, the impact, and a minimal reproduction or
   proof of concept.
3. Include any suggested fix or mitigation if you have one.

Please do **not** open public issues, discussions, or pull requests for a
suspected vulnerability. A public report before a fix is available puts every
user of the package at risk. If you are unsure whether something is a security
issue, report it privately and let the maintainer triage it.

## Response expectations

This is a bus-factor-1 project, and the response times below are honest targets,
not contractual SLAs:

- **Acknowledgment:** within **7 days** of a private report.
- **Triage and severity assessment:** as soon as the report can be reproduced.
- **Fix and advisory:** depends on severity and complexity; the maintainer will
  keep you informed in the advisory thread and coordinate disclosure timing
  with you.

There is no paid bug-bounty program. Reports are handled on a best-effort basis
by the maintainer.

## Scope

### In scope

- Contract parsing and deserialization: YAML loading, version detection, schema
  validation, and the `contract.yaml` loading path.
- Contract enforcement: permission and approval checks, gate integrity,
  lifecycle handling, and the gateway wrappers (`BaseGateway`,
  `GitHubGateway`, `QdrantGateway`).
- Registry integrity and audit behavior: entry hashing, registry reads/writes,
  `scyvera audit` scanning, symlink refusal, and fixture quarantine.
- CLI parsing and exit codes where a bug weakens a security decision (for
  example, a failed check exiting `0`).
- Tier 1 static adapters where a missed or mis-mapped capability produces a
  false-negative conformance result.

### Out of scope

- Vulnerabilities in user agent code or in contracts that users write. Scyvera
  validates and enforces declarations; it does not make an unsafe workflow safe.
- Security of an n8n instance, LangGraph runtime, or any other host platform,
  including its authentication, network configuration, and installed plugins.
- Vulnerabilities in the dependencies of the reference implementations (for
  example `httpx`, `openai`, `langgraph`, `qdrant-client`, or `PyGithub`).
  Report those upstream; if Scyvera's own handling of them is affected, that
  part is in scope.
- Reports that require an already-compromised host, local administrator access,
  or physical access to the machine running Scyvera.
- Missing hardening headers or best-practice suggestions with no demonstrated
  security impact.

## Credit

Reporters are credited by name in the published GitHub Security Advisory by
default. If you prefer to remain anonymous, say so in the report and we will
omit your name. Please tell us if you plan to publish your own write-up so the
advisory can link to it after disclosure.
