# Batch Implementation

Use `batch` to implement a related set of TODOs in order. For each item,
implement, verify, complete, review, fix findings, commit, and open one PR. Use
the `code` skill review when available. Otherwise, apply the same five-axis
review by hand.

One `batch` call over an explicit named set authorizes implementation, commits,
PRs, and conditional auto-merge only for those TODOs. It does not authorize
work outside their work orders or bypass repository approval gates. Do not ask
again for the same authority per item.

## Before you start

Run `todo doctor` through `_project/scripts/todo`. If the wrapper does not support `doctor`, report that you skipped the preflight. Fix any failure before you claim the first item.

If a command that documents the exit-code contract returns exit code 4, stop
the batch. The wrapper may already have tried to refresh the token once.

1. Record each stale tracker item and its blocker in the local ledger.
2. Show the authentication error and its documented recovery command.
3. Do not implement more work or open PRs while tracker writes fail.
4. After authentication is restored, replay missed tracker writes before
   taking another item.

## Tracker commands

Use `_project/scripts/todo` for claims and leases (`claim`), per-unit worktrees
and branches (`start`/`done`), and completion and PRs (`complete --pr`). Rebuild
progress with `todo list`, `todo stats`, and `todo deps <id>`.

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

The ledger preserves only the temporary orchestration state needed to resume
this batch.

## Setup

1. Remove exact duplicate ids. Confirm each one with `todo show <id>`.
2. Read each item's work order (`todo claim` shows scope, must-preserve, anti-patterns, verification steps, ready units, and deferrals) or preview with `todo show <id> --json` and `todo deps <id>`.
3. Sort by in-batch dependencies (`deps.needs`). Items in a cycle are `blocked`. Continue with the rest.

## Scheduler

After a failed attempt, make one focused retry. If the retry fails, mark the
item `blocked` and continue with other TODOs.

Repeat until every item is `done` or `blocked`:

1. Re-read the ledger. Refresh readiness with `todo ready` and `todo deps`. `ready`/`stats` may print a warning on stderr about untriaged findings — triage with `todo finding candidates`. Findings are not batch items and never enter the ready queue.
2. Classify each non-terminal item (`ready` is derived, not stored):
   * `ready`: ledger status is `pending`, every in-batch dependency is `done` (its PR is merged into the integration branch), and external deps are clear per `todo ready`.
   * `waiting`: a dependency PR, external dep, CI check, or merge is pending and can still resolve this session.
   * `blocked`: missing or malformed item, dependency cycle, the failed-retry rule above, or a wait with no resolution path this session. Record the reason. If it is a hard tracker blocker, run `todo block <id> --reason ...`.
3. If a TODO is ready, implement it (see below).
4. If none are ready: mark ordinary pending CI as `waiting`. Use bounded, announced monitoring (command, max time, log path, stop condition — for example, `gh pr checks` or the project PR-status target) only for a dependency gate that blocks another TODO. You can delegate a deterministic gate check to a subagent for run-and-report. Apply the failed-retry rule to red batch-owned PRs. Being not-ready is `waiting`, not `blocked`.

## For each ready TODO

1. Mark `in_progress` in the ledger.
2. For implementation work, create and use a fresh linked worktree off the integration branch before editing. Keep the work isolated there, and after the PR or PRs merge, verify the tree is clean and remove that exact linked worktree according to repository policy. Do not assume a retained slot or worktree pool. If a dependency PR merged since you created the worktree, refresh onto the updated branch first.
3. Run `todo claim <id>` and follow the work order. For each work unit, run
   `todo start`, apply `SHARED/change-framework/SKILL.md` Section 1 before
   source-code edits, implement, then record evidence with `todo done`. Defer
   out-of-scope work with `todo defer`.
4. Run `todo check-scope <id>` and `todo verify <id> --run`.
5. Mark `in_review`. As internal implementation verification under
   `SHARED/review-protocol/SKILL.md` [REVIEW-AUTH-001], run the `code` skill
   review on the diff or apply the same five-axis review. Fix every Critical or
   Required finding unless you can prove it is invalid. Apply Nit or Consider
   only when it is in scope. List every skipped finding in the PR body.
   Re-verify and re-review after non-trivial fixes.
6. Commit only explicit paths (never `git add -A`) through `SHARED/change-framework`, then open the PR.
7. Run `todo complete <id> --pr <n>` — but first resolve deferrals with `promote` or `dismiss`, or it will refuse.
8. If a later TODO in the batch needs this PR merged: mark `pr_open`, enable auto-merge only when the integration branch gate is CI checks (not required human approval), then monitor until merged and mark `done`. Else mark `done` after you open the PR and complete the item.

## Workers

Run one item at a time by default. Parallel workers increase churn for little gain. Use one worker per TODO only when you have worker sessions. The orchestrator still owns order, ledger, monitors, and the final report. Each worker must return: `TODO`, `STATUS: done|pr_open|blocked`, `PR`, `WORKTREE`, `BRANCH`, `NOTES`.

## Final report

Report `TODO | PR # | status | note`. List blockers with unblock steps and the ledger path. If the session ends before every item is terminal, state the ledger path and the resume command (run `batch` again with the same inputs — the ledger plus the database resumes progress).
