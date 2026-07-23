# Contributing to n8n_workflows

Thanks for considering a contribution — this repo grows through community-submitted workflows, so every addition genuinely helps. This guide covers how to submit one properly.

---

## 📌 Ground Rules

- **Never push directly to `main`.** All changes — new workflows, fixes, doc updates — go through a feature branch and a pull request. `main` only receives merges after review.
- Every workflow must be self-contained in its own folder under `workflows/`.
- Every workflow must include a `workflow.json` **and** its own `README.md`.
- No real credentials, tokens, chat IDs, webhook URLs, or personal data in anything you commit — see [Security Note](#-security-note) below.

---

## 🧭 Contribution Workflow

### 1. Fork the repository
Click **Fork** on GitHub, then clone your fork locally:
```bash
git clone https://github.com/<your-username>/n8n_workflows.git
cd n8n_workflows
```

### 2. Create a feature branch
Never commit to `main` — always branch off it first:
```bash
git checkout -b feature-<short-description>
```
Examples:
```bash
git checkout -b feature-slack-standup-bot
git checkout -b feature-fix-debugger-agent-readme
```

### 3. Add your workflow
Structure it like this:
```
workflows/
└── your-workflow-name/
    ├── workflow.json
    └── README.md
```

Your workflow's `README.md` should cover:
- **What it does** — one or two sentences
- **Prerequisites** — n8n version, any credentials/API keys needed, external services used
- **Setup steps** — how to import and configure it
- **Placeholders used** — list every `REPLACE_ME`-style value someone needs to fill in before running it

### 4. Scrub secrets before committing
Open your exported `workflow.json` and check for:
- API keys, tokens, or webhook secrets
- Real chat IDs, user IDs, or email addresses
- Real repo names or file paths that reveal private info

Replace anything sensitive with a clear placeholder (`REPLACE_ME`, `YOUR_CHAT_ID`, `YOUR_REPO_NAME`, etc.) before it ever reaches a commit.

### 5. Commit your changes
Write clear, specific commit messages:
```bash
git add .
git commit -m "Add Slack standup reminder workflow"
```

### 6. Push your branch
```bash
git push origin feature-<short-description>
```
**Do not push to `main`** — pushing your feature branch is the correct and only path.

### 7. Open a Pull Request
On GitHub, open a PR from your feature branch into `main`. In the PR description, include:
- What the workflow does
- What you tested it against
- Any known limitations

The PR will be reviewed before merging — nothing lands on `main` without review, including changes from maintainers.

---

## ✅ PR Review Checklist

Before requesting review, confirm:
- [ ] Workflow lives in its own folder under `workflows/`
- [ ] `workflow.json` imports cleanly into a fresh n8n instance
- [ ] `README.md` included and covers setup, prerequisites, and placeholders
- [ ] No real credentials, tokens, or personal data anywhere in the diff
- [ ] Commit messages are clear and descriptive
- [ ] Branch is up to date with `main` (rebase or merge `main` in if it's drifted)

---

## 🐛 Reporting Issues

Found a bug in an existing workflow, or have an idea for a new one? Open an [Issue](../../issues) describing:
- Which workflow is affected (or the new workflow you're proposing)
- What's wrong / what you'd like to see
- Steps to reproduce, if reporting a bug

---

## 🔒 Security Note

If you discover a workflow accidentally published with a real credential or secret, please **do not open a public issue** — instead, contact the maintainer directly so it can be scrubbed and, if needed, the exposed credential rotated before it's discussed publicly.

---

## 🙌 Code of Conduct

Be respectful, be constructive, and assume good faith. This is a community resource — treat it like one.

---

Thanks again for contributing — every workflow added makes this a more useful resource for the next person who finds it.
