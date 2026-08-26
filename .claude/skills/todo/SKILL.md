---
name: todo
description: Use when the user asks to "ideate on an idea", "refine an idea", "brainstorm", "write a spec", "create a specification", "create a TODO", "show TODO items", "manage TODOs", "prioritize TODOs", "top N most important todos", "rank the backlog", "what should we work on", "implement a TODO", "implement a batch of TODOs", "complete a TODO", "cleanup TODOs", "review TODO quality", "claim a TODO", "what's ready" / "ready queue", "defer this work", "promote a deferral", "dismiss a deferral", "block"/"unblock a TODO", "create TODOs from a spec", "create a batch handoff", "close out a reviewed batch", or "todo stats". Covers the lifecycle from idea to specification, implementation, and completion.
version: 0.9.0
tools: Bash, Read, Edit, Write, Task
---

# Todo — Idea to Done

## Critical rules

After bootstrap, use `_project/scripts/todo` for every tracker command.

- Run `_project/scripts/todo --help`; treat the chosen subcommand's help as its full contract.
- If the subcommand is missing, report the gap and stop.
- Put global flags before it: `todo --db <path> --actor <name> <command>`.

Skill-only actions: `prioritize`, `batch`, `handoff`, and `closeout`; follow their guides, not the CLI.

If one request combines review or validation with close-out, perform the read-only review and stop at findings under
`shared-review-protocol/SKILL.md`. A later user message may authorize `closeout`.

### Failures and claims

- Exit code 2 means a general failure.
- Exit code 4 means the hosted database rejected the credentials (missing or rejected). Stop writes, run `todo doctor`,
  and follow the remediation in `docs/operations/hosted-credentials.md` (provision or rotate the credential via `TODO_DB_CREDENTIAL_COMMAND`).
- Only the holder can run `todo release`; it exits 2 for another actor's claim, and checking `claimed_by` can race.
  `complete` and `drop` may clear any claim. `--actor` prevents mistakes, not impersonation.

### Lifecycle rules

- Read the selected action guide before acting.
- After specification approval, track it with `todo create` or the supported create-from-spec command.
- Store tracker state only in the database; do not create tracker files by hand.
- Commit through `shared-change-framework/SKILL.md`.
- `TODO_DB_URL` may select the hosted database; the CLI never prints its connection string.

## Actions

| Action | When to use it | Guide |
|---|---|---|
| `ideate` | You need to refine or brainstorm an idea | `references/ideate.md` |
| `spec` | You need to write a specification | `references/spec.md` |
| `bootstrap`, `init`, `doctor` | You set up or check the tracker | `references/bootstrap.md` |
| `ready`, `claim`, `start`, `done`, `defer`, `check-scope`, `verify`, `complete`, `promote`, `dismiss` | You implement a TODO | `references/implement.md` |
| `create`, `update`, `list`, `show`, `stats`, `deps`, `export`, `block`, `unblock`, `release`, `sweep-stale`, `drop` | You query or change items | `references/queries.md` |
| `prioritize` — skill-only, no CLI command | You rank open items and group by topic | `references/prioritize.md` |
| `lint` | You review an item | `references/review.md` |
| `finding candidates`, `finding triage`, `finding import`, `finding sync`, `finding promote` | You triage findings | `references/implement.md` |
| `batch` — skill-only, no CLI command | You implement several TODOs in order | `references/batch.md` |
| `handoff` — skill-only, no CLI command | You create a self-contained batch handoff | `references/handoff.md` |
| `closeout` — skill-only, no CLI command | You remediate a separately reviewed batch and close its items | `references/closeout.md` |
| `help` | You need the action list | This table |

`todo ready` and `todo stats` may warn on stderr about open findings or unsynced drafts without changing stdout. Run
`todo finding candidates` when warned; no warning appears when there are no findings.
