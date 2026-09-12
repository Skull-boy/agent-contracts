# Contract Validator Agent

An automated governed agent that validates Agent Contracts in pull requests using `scyvera.validate_contract()`.

## Purpose

The Contract Validator ensures that any Agent Contract YAML modified or added in pull requests conforms to the normative Agent Contract specifications (v1 and v1.1).

It operates as a governed agent inside the repository itself, subject to its own contract declared at `.github/agents/contract-validator/contract.yaml`.

## Contract Specification

- **Identity**: `contract-validator`
- **Domain**: `software`
- **Lifecycle**: `request-response` (triggered per PR event, stateless execution)
- **Permissions**: Read PR diffs, post PR comments (`github:pull-requests:read`, `github:pull-requests:write`)
- **Side Effects**: PR commentary only
- **Approval Points**: None (read-only validation feedback does not perform state modification or deployment)
- **Recovery**: Stops on unrecoverable validation runtime failure and logs diagnostics to GitHub Actions summary.
- **Replay Semantics**: Idempotent.

## How to Run Locally

You can run validation against any contract file or across the repository using `scyvera`:

```bash
# Install scyvera
pip install .

# Validate this agent's contract
scyvera validate .github/agents/contract-validator/contract.yaml

# Lint this agent's contract
scyvera lint .github/agents/contract-validator/contract.yaml
```

To run the full validation script used by CI locally:

```bash
python scripts/validate_pr_contracts.py --files .github/agents/contract-validator/contract.yaml
```
