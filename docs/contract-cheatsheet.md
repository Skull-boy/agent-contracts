# contract.yaml Field Reference Cheatsheet

A quick-reference guide to every field in the Agent Contract v1.1 schema.
Copy the minimal example below, then add fields as your workflow needs them.

## Minimal Valid Contract

The smallest contract that passes schema validation:

```yaml
version: 1.1

system:
  name: My Agent
```

`version` is always required. You must also provide at least one of
`system`, `agent`, or `workflow` to identify the system.

## Full Field Reference

### version *(required)*

Schema version. Must be `1.1` (number or string).

```yaml
version: 1.1
```

### system *(one of system/agent/workflow required)*

Identifies the system this contract governs.

```yaml
system:
  name: Invoice Processor          # required, non-empty string
  purpose: Processes incoming PDF  # optional description
  version: "1.0.0"                 # optional semver
```

### agent

Legacy alias for `system`. Same shape. Prefer `system` for new contracts.

### workflow

Legacy v1 alias - a plain string for the system name. Use `system` instead.

### domain

Operational application domain.

```yaml
domain: finance     # free-form string (e.g. healthcare, education, software)
```

### capabilities

What the system can do. Each entry is a string or an object with `name`
and `description`.

```yaml
capabilities:
  - name: parse_invoice
    description: Extracts line items from PDF invoices
  - name: reconcile_payments
    description: Matches payments to open invoices
```

### resources

External resources the system touches. Each entry is a string or an object
with `name`, `type`, `access`, and `scope`.

```yaml
resources:
  - name: invoice_db
    type: postgres
    access: read
    scope: finance_schema
```

### inputs

What the system accepts as input. Each entry is a string or an object
with `name`, `type`, `required`, and `description`.

```yaml
inputs:
  - name: pdf_file
    type: file
    required: true
  - name: vendor_id
    type: string
    required: false
```

### outputs

What the system produces. Each entry is a string or an object with
`name`, `type`, and `description`.

```yaml
outputs:
  - name: reconciled_report
    type: json
  - name: audit_log
    type: text
```

### permissions

Scoped action grants. Each entry is a string matching
`resource:action` or an object. Wildcards (`*`, `all`, `any`) are
not allowed.

```yaml
permissions:
  - "invoice_db:read"
  - "payment_gateway:charge"
```

### constraints

Operational limits. Each entry is an object with a `type` and limit
fields.

```yaml
constraints:
  - type: rate_limit
    maximum: 60
    unit: requests_per_minute
  - type: cost
    maximum: 5
    currency: USD
```

### side_effects

External changes the system makes. Each entry is a string or an object
with `type`, `resource`, `description`, and `irreversible`.

```yaml
side_effects:
  - type: write
    resource: invoice_db
    description: Updates invoice status to paid
    irreversible: false
```

When `irreversible: true` and `approvals` is empty, the linter emits
a warning.

### approvals

Human-in-the-loop gates. Each entry is a string or an object with
`action`, `required`, `approver`, and `condition`.

```yaml
approvals:
  - action: process_refund
    required: true
    approver: finance_manager
    condition: amount > 500
```

### dependencies

Other systems or services this contract relies on. Each entry is a
string or an object with `name`, `type`, and `required`.

```yaml
dependencies:
  - name: postgres
    type: database
    required: true
  - name: redis
    type: cache
    required: false
```

### state

How the system stores state. A string or an object with `persistence`,
`scope`, and `storage`.

```yaml
state:
  persistence: session    # none | session | persistent | ephemeral
  scope: per_user
  storage: redis
```

### recovery

What happens on failure. A string or an object with `strategy`
and `details`.

```yaml
recovery:
  strategy: retry    # stop | retry | rollback | human_escalation | fallback
  details: Retry up to 3 times with exponential backoff
```

### replay

Whether the system can be safely replayed. A string or an object
with `mode` and `details`.

```yaml
replay:
  mode: idempotent    # idempotent | non_idempotent | conditional | prohibited
```

### observability

Logging and tracing level. A string, array of strings, or an object
with `level` and `sinks`.

```yaml
observability:
  level: audit    # none | basic | audit | verbose
  sinks:
    - stdout
    - elasticsearch
```

### artifacts

Produced artifacts with provenance metadata. Each entry is an object
with `name`, `type`, `source`, `integrity_required`, and
`provenance_required`.

```yaml
artifacts:
  - name: trained_model
    type: model    # model | dataset | document | package | executable | configuration | tool | dependency
    source: s3://bucket/model.pkl
    integrity_required: true
    provenance_required: true
```

### security

Transport and sandbox requirements.

```yaml
security:
  transport_security: tls_required
  sandbox_required: true
  auth_required: true
```

### risk

Risk classification for the system.

```yaml
risk:
  level: medium    # low | medium | high | critical
  category: financial_loss
```

### implementation

Runtime and framework metadata.

```yaml
implementation:
  framework: langgraph
  runtime: python
  language: python
  repository: https://github.com/org/repo
```

### lifecycle

Execution model and behavioral constraints. When `mode` is
`persistent`, `idle_behavior` is required.

```yaml
lifecycle:
  mode: request-response    # request-response | persistent | scheduled
  idle_behavior: Polls queue every 30s   # required if mode=persistent
  initiation: human-only    # human-only | schedule | self | agent
  resumability: stateless   # stateless | context-snapshot | replay-from-log
```

## Common Patterns

### Stateless Request-Response (simplest)

```yaml
version: 1.1
system:
  name: Q&A Bot
  purpose: Answers user questions
domain: education
lifecycle:
  mode: request-response
state:
  persistence: none
recovery:
  strategy: stop
replay:
  mode: idempotent
```

### Persistent Worker with Side Effects

```yaml
version: 1.1
system:
  name: File Processor
  purpose: Watches and processes uploaded files
lifecycle:
  mode: persistent
  idle_behavior: Polls upload directory every 60 seconds
  initiation: schedule
  resumability: replay-from-log
side_effects:
  - type: write
    resource: file_system
    description: Moves processed files to archive
    irreversible: true
approvals:
  - action: delete_original
    required: true
    approver: admin
recovery:
  strategy: rollback
observability:
  level: audit
risk:
  level: medium
  category: data_loss
```

### Scheduled Task with Cost Constraint

```yaml
version: 1.1
system:
  name: Nightly Reporter
  purpose: Generates and emails daily summary report
lifecycle:
  mode: scheduled
  initiation: schedule
  resumability: stateless
constraints:
  - type: cost
    maximum: 1
    currency: USD
  - type: rate_limit
    maximum: 100
    unit: requests_per_hour
outputs:
  - name: report
    type: email
recovery:
  strategy: retry
replay:
  mode: idempotent
risk:
  level: low
```

## Validation

Validate your contract before committing:

```bash
python scripts/validate_contracts.py
```

Or use the CLI:

```bash
scyvera validate contract.yaml
```

See [`schemas/v1.1/contract.schema.json`](../schemas/v1.1/contract.schema.json)
for the normative JSON Schema definition.
