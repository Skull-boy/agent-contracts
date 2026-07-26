# Contributors

This project grows through real conversation, not just solo commits. This file credits everyone whose code, ideas, or feedback have shaped it — because a suggestion that gets implemented deserves the same recognition as a merged PR.

---

## 🛠️ Maintainer

- **[Shinjan Das](https://github.com/Skull-boy)** — creator and maintainer

---

## 💡 Community Ideas & Feedback

Some of the most valuable contributions to this project didn't arrive as pull requests — they arrived as pushback, questions, and suggestions in public discussion. Where a community suggestion has been implemented, it's credited here alongside the change it led to.

- **jake_that_dude** (r/n8n) — proposed adding structured `reasonCode` values alongside the relevance score in the Competitor Feature-Parity Watcher, so LLM-based scoring could be debugged and tuned systematically instead of argued over as raw numbers. Implemented in the workflow's relevance-judging step.
- **[Bino5150](https://github.com/Bino5150)** (r/AI_Agents, r/n8n) — raised the security risk of importing third-party automation workflows without review, which shaped the "Before You Import Any Workflow" checklist in the root README. Also maintains [lumina](https://github.com/Bino5150/lumina), a local-first agentic harness — a good reference point if this repo ever adds a natural-language-driven workflow interface alongside the explicit graph approach.
- **przemarzec, ebwaked, FirstThoroughfare, BP041, Responsible-Beat2137** (r/AI_Agents) — independently converged on the idea that reusable automation needs a declared contract — not just documentation — covering permissions, side effects, and recovery behavior. This directly shaped the Contract framework now required in every workflow's README.

---

## 🤝 Code Contributors

*(This section grows as pull requests are merged.)*

Contributions in progress:
- **Responsible-Beat2137** — planning a contribution around workflow contracts, context packets, execution records, and interface boundaries, extending the Contract framework toward a more complete automation architecture. Scope being finalized in [issue link].

---

## 🙌 Want to Be Listed Here?

Every merged PR gets a line in this file. See [CONTRIBUTING.md](./CONTRIBUTING.md) for the branch → PR → review process — and if you've influenced this project through discussion rather than code, that counts too. Open an issue or mention it in a PR and it'll be added here.
