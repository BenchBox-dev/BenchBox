# Batch Implementation

Use `batch` to implement a related set of TODOs in order: implement, verify, complete, review, fix findings, commit, and open a PR. Keep one TODO per PR. Use the `code` skill review when it is available. Else do the same five-axis review by hand.

One `batch` call over a named set is a single authorization for the per-item implement, commit, PR, and auto-merge cycle. The TODOs already hold their guardrails (the `todo claim` output shows them), so you do not ask again per item.

## Before you start

Run `todo doctor` through `_project/scripts/todo`. If the wrapper does not support `doctor`, report that you skipped the preflight. Fix any failure before you claim the first item.

If a command that documents the exit-code contract returns exit code 4 (hosted auth failure) during the batch, stop at once. The wrapper may have already tried to refresh the token once. Record every item whose tracker state is behind reality in the local ledger (see below) with the blocker reason. Show the alert and the fix: `turso auth login` or `export TODO_DB_AUTH_TOKEN=$(turso db tokens create <db>)`. Do not keep implementing or opening PRs while tracker writes fail. When auth is restored, replay the missed tracker writes from the ledger before you take new items.

## The database is the record

Tracker state lives in the database. Use `_project/scripts/todo` for it: claim and lease (`claim`), per-unit worktree and branch (`start`/`done`), completion and PR (`complete --pr`). Never write tracker state to files. Rebuild progress from `todo list`, `todo stats`, and `todo deps <id>` — not from a parallel file tree.

## Local ledger — batch bookkeeping only

`batch` spans many TODOs, PRs, and CI waits. Keep one small local ledger for the facts the database does not track:

* the batch set and order after you remove duplicates and sort by dependencies;
* each item's batch-local status (`pending`, `waiting`, `in_progress`, `in_review`, `pr_open`, `done`, `blocked`) — this is local to the ledger, not the tracker's own state;
* the blocker or wait reason.

Per-item worktree, branch, and PR already live in the database (`start`/`complete`). Do not duplicate them. Put the ledger on an ignored local path (for example, an existing scratch dir or `.todo-batch/<slug>.yaml`). If that path is visible to git, add `.todo-batch/` to `.git/info/exclude` — not to the committed `.gitignore`. Never commit the ledger. On resume, read it first.

```yaml
batch: <slug>
order: [todo-a, todo-b]
items:
  todo-a: {status: pending, note: ""}
```

Without the ledger, context compaction or a stalled PR can cause you to repeat or skip a TODO. The ledger plus the database are the source of truth.

## Setup

1. Remove exact duplicate ids. Confirm each one with `todo show <id>`.
2. Read each item's work order (`todo claim` shows scope, must-preserve, anti-patterns, verification steps, ready units, and deferrals) or preview with `todo show <id> --json` and `todo deps <id>`.
3. Sort by in-batch dependencies (`deps.needs`). Items in a cycle are `blocked`. Continue with the rest.

## Scheduler

Repeat until every item is `done` or `blocked`:

1. Re-read the ledger. Refresh readiness with `todo ready` and `todo deps`. `ready`/`stats` may print a warning on stderr about untriaged findings — triage with `todo finding candidates`. Findings are not batch items and never enter the ready queue.
2. Classify each non-terminal item (`ready` is derived, not stored):
   * `ready`: ledger status is `pending`, every in-batch dependency is `done` (its PR is merged into the integration branch), and external deps are clear per `todo ready`.
   * `waiting`: a dependency PR, external dep, CI check, or merge is pending and can still resolve this session.
   * `blocked`: missing or malformed item, dependency cycle, repeated failure, or a wait with no resolution path this session. Record the reason. If it is a hard tracker blocker, run `todo block <id> --reason ...`.
3. If a TODO is ready, implement it (see below).
4. If none are ready: mark ordinary pending CI as `waiting`. Use bounded, announced monitoring (command, max time, log path, stop condition — for example, `gh pr checks` or the project PR-status target) only for a dependency gate that blocks another TODO. You can delegate a deterministic gate check to a subagent for run-and-report. Fix red batch-owned PRs while you are still in scope. Mark `blocked` only after one failed fix. Being not-ready is `waiting`, not `blocked`.

## For each ready TODO

1. Mark `in_progress` in the ledger.
2. Use a fresh pool worktree off the integration branch when you can. If a dependency PR merged since you claimed the worktree, refresh onto the updated branch first.
3. Run `todo claim <id>` and follow the work order. For each work unit: `todo start` (records worktree and branch), implement, then `todo done <id> <wid> --evidence "<command or commit or PR>"`. Defer out-of-scope work at once with `todo defer`.
4. Run `todo check-scope <id>` and `todo verify <id> --run`.
5. Mark `in_review`. Run the `code` skill review on the diff (or the same five-axis review by hand). Fix every Critical or Required finding unless you can prove it is invalid. Apply Nit or Consider only when it is in scope. List every skipped finding in the PR body. Re-verify and re-review after non-trivial fixes.
6. Commit only explicit paths (never `git add -A`) through `SHARED/change-framework`, then open the PR.
7. Run `todo complete <id> --pr <n>` — but first resolve deferrals with `promote` or `dismiss`, or it will refuse.
8. If a later TODO in the batch needs this PR merged: mark `pr_open`, enable auto-merge only when the integration branch gate is CI checks (not required human approval), then monitor until merged and mark `done`. Else mark `done` after you open the PR and complete the item.

If a TODO fails, retry once with the failure notes. A second failure becomes `blocked`. Continue with other TODOs.

## Workers

Run one item at a time by default. Parallel workers increase churn for little gain. Use one worker per TODO only when you have worker sessions. The orchestrator still owns order, ledger, monitors, and the final report. Each worker must return: `TODO`, `STATUS: done|pr_open|blocked`, `PR`, `WORKTREE`, `BRANCH`, `NOTES`.

## Final report

Report `TODO | PR # | status | note`. List blockers with unblock steps and the ledger path. If the session ends before every item is terminal, state the ledger path and the resume command (run `batch` again with the same inputs — the ledger plus the database resumes progress).
