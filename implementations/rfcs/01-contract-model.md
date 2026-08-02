## What

Proposing a restructure of this repository's internal layout to match the direction laid out in [`docs/workflow-engineering.md`](./docs/workflow-engineering.md) and [`WORKFLOW-CONTRACT-SPEC.md`](./WORKFLOW-CONTRACT-SPEC.md). Note: the repo has already been renamed from `n8n_workflows` to `agent-contracts` to reflect this direction — this RFC is about the *internal folder structure* underneath that new name, a separate decision from the rename itself.

**Proposed structure:**

```
agent-contracts/
├── docs/
│   └── workflow-engineering.md
├── patterns/
│   └── detect-judge-approve-act.md
├── implementations/
│   └── n8n/
│       ├── github-debugger-agent/
│       ├── telegram-github-antigravity-pipeline/
│       ├── duplicate-issue-detector/
│       │   ├── workflow.json
│       │   ├── contract.yaml
│       │   └── README.md
│       ├── competitor-feature-parity-watcher/
│       ├── job-application-silent-rejection-detector/
│       └── telegram-structured-solver-pdf/
├── WORKFLOW-CONTRACT-SPEC.md
├── LICENSE
├── CONTRIBUTING.md
├── CONTRIBUTORS.md
└── README.md
```

`workflows/` becomes `implementations/n8n/` — the same content, renamed to leave room for `implementations/langgraph/` or others once a second framework implementation actually exists (see the pattern doc for why that's not being pre-created empty).

## Why this is an RFC, not a merged PR

This breaks every existing link into `workflows/<name>` — issues, external references, anything anyone has bookmarked. It also directly touches the area two of you have already offered to help shape.

u/Bino5150 u/Responsible-Beat2137 — tagging you both directly, since this is exactly the territory you each raised independently (portability across frameworks, workflow contracts and interface boundaries). Before anything gets moved, I'd like your read on:

1. Does `implementations/<framework>/` make sense as the container for future non-n8n work, or would you structure that differently?
2. Anything in the proposed tree that doesn't hold up once a second framework implementation actually exists?

## Migration plan, if this is approved

1. `git mv workflows implementations/n8n` — preserves file history, doesn't break git blame
2. Add redirect notes in the old locations is not possible via git mv alone — instead, the root README's Repository Structure section gets updated in the same PR, and a note gets added to this issue once merged so anyone with an old link can find the new path
3. Each workflow's Contract migration (tracked separately in #<link the existing "Migrate existing workflow Contracts to v1 spec" issue>) continues independently of this move — moving folders and upgrading Contract format are separate concerns

## Not in scope for this RFC

- `research/` and `community-discussions/` folders — mentioned in the original vision for this direction, but not proposed here until there's actual content to put in them. An empty folder with a README saying "coming soon" doesn't earn its place yet.
