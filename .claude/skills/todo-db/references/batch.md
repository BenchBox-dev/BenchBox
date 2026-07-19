# Batch Implementation

`batch` implements a related TODO set in sequence: implement -> verify ->
complete -> code review -> fix findings -> commit -> PR. Keep one TODO per PR.
Use the `code` skill `review` action when available; otherwise perform the
equivalent five-axis review locally.

One `batch` invocation over a named TODO set is a single authorization for the
per-item implement/commit/PR/auto-merge cycle: the TODOs already carry their
guardrails (the CLI prints them as the work order), so you do not re-ask per
item.

## The database is the record

Tracker state lives in the DB, reachable through `_project/scripts/todo`:
claim/lease (`claim`), per-unit worktree+branch (`start`/`done`), completion
and PR (`complete --pr`). Never write tracker state to files. Reconstruct
progress from `todo list`, `todo stats`, and `todo deps <id>` — not a parallel
YAML tree.

## Local scratch ledger (batch bookkeeping only)

`batch` still spans multiple TODOs, PRs, and CI/merge waits, so keep one small
local scratch ledger for the orchestration facts the tracker DB does not model:

- normalized batch membership + order after dedupe/dependency sorting;
- each item's batch-local status (`pending`, `waiting`, `in_progress`,
  `in_review`, `pr_open`, `done`, `blocked`) — a lowercase set local to the
  ledger, distinct from the tracker's own item state;
- the exact blocker/wait reason.

Per-item worktree, branch, and PR already live in the DB (`start`/`complete`);
don't duplicate them. Put the ledger on an already-ignored local path (e.g. an
existing scratch dir, or `.todo-batch/<slug>.yaml`); if that path is visible to
git, add `.todo-batch/` to `.git/info/exclude` — not the committed
`.gitignore` — and never stage it. On resume, read it first.

```yaml
batch: <slug>
order: [todo-a, todo-b]
items:
  todo-a: {status: pending, note: ""}
```

Without that ledger, context compaction or a stalled PR can make the agent
repeat a TODO, skip one, or hand control back instead of monitoring. `/goal`
or `/loop` may wrap the action, but the ledger + DB remain the source of truth.

## Setup

1. Dedupe exact-duplicate TODO ids. Confirm each resolves with `todo show <id>`.
2. Read each item's work order (`todo claim` prints scope globs, must-preserves,
   anti-patterns, verification ladder, ready units, deferrals), or preview with
   `todo show <id> --json` and `todo deps <id>`.
3. Topologically sort in-batch `deps.needs`. Cycle members are `blocked`;
   continue any acyclic TODOs.

## Scheduler

Loop until every item is `done` or `blocked`:

1. Re-read the ledger; refresh readiness with `todo ready` and `todo deps`.
2. Classify each non-terminal item (`ready` is derived, not stored):
   - `ready`: batch-local `pending`, every in-batch dep `done` (its PR merged
     into the integration branch — unless a stacked-branch exception is
     recorded), and external deps clear per `todo ready`;
   - `waiting`: a dependency PR, external dep, CI check, or merge is pending
     **and** has a path to resolution this session;
   - `blocked`: missing/malformed item, dependency cycle, repeated failure, or
     a wait with no resolution path this session — record the reason and, if
     it is a hard tracker blocker, `todo block <id> --reason ...`.
3. If a TODO is ready, implement it.
4. If none are ready: record ordinary pending CI as `waiting` and move on; use
   bounded, announced monitoring (command, max runtime, log path, stop
   condition — `gh pr checks`, `gh pr view`, or the project PR-status target)
   only for a batch-owned dependency gate that must resolve before another TODO
   can proceed. Deterministic gate runs are delegatable to a low-effort
   subagent for run-and-report — see SHARED/verify-framework/SKILL.md. Fix red
   batch-owned PRs while still in scope; mark `blocked` only after one failed
   recovery.

Simple not-readiness is `waiting`, not `blocked`.

## Per TODO

For each ready TODO:

1. Mark `in_progress` in the ledger.
2. Use a fresh pool worktree off the integration branch when available; if a
   dependency PR merged since the worktree was claimed, refresh onto the
   updated integration branch first.
3. `todo claim <id>`; follow the printed work order. Per unit: `todo start`
   (records worktree/branch), implement, `todo done <id> <wid> --evidence ...`.
   Defer out-of-scope work the moment you hit it (`todo defer`).
4. `todo check-scope <id>`; run the ladder with `todo verify <id> --run`.
5. Mark `in_review`; run the `code` skill `review` action on the diff (or the
   equivalent five-axis review). Fix every Critical/Required finding unless
   proven invalid with cited evidence; apply Nit/Consider only within scope and
   record every skipped one in the PR body. Re-verify/re-review after
   non-trivial fixes.
6. Commit explicit paths only (never `git add -A`) via SHARED/commit-framework,
   then run the project's PR-open equivalent.
7. `todo complete <id> --pr <n>` (resolve deferrals first via `promote` /
   `dismiss`, or it refuses).
8. If a later batch TODO needs this PR merged: mark `pr_open`; enable
   auto-merge **only when the integration branch's gate is CI/checks, not
   mandatory human approval**; monitor until merged, then mark `done`.
   Otherwise mark `done` after PR open and `todo complete`.

Retry a failed TODO once with the failure notes. A second failure becomes
`blocked`; continue other TODOs.

## Workers

Default is sequential — parallel workers multiply usage-limit pressure and PR
churn for little gain. Use one worker per TODO only when worker sessions are
available; the orchestrator still owns ordering, ledger, monitors, and final
reporting. Require this exact return block from a worker: `TODO`,
`STATUS: done|pr_open|blocked`, `PR`, `WORKTREE`, `BRANCH`, `NOTES`.

## Final Report

Report `TODO | PR # | status | note`, list blockers with unblock steps, and
include the ledger path. If the session ends before every item is terminal,
the closing message must state the ledger path and the resume command
(re-invoke `batch` with the same inputs — the ledger + DB resume progress).
