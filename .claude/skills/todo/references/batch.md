# Batch Implementation

`batch` implements a related TODO set in sequence: implement -> verify ->
complete -> code review -> fix findings -> commit -> PR. Keep one TODO per PR.
Use the `code` skill `review` action when available; otherwise perform the
equivalent five-axis review locally.

One `batch` invocation over a named TODO set is a single authorization for the
per-item implement/commit/PR/auto-merge cycle: the TODOs have already been
reviewed and carry their guardrails, so you do not re-ask per item.

## Why A YAML State File

The state file is justified only because `batch` spans multiple TODOs, PRs,
and possible CI/merge waits. It is not new project infrastructure: no schema,
no CLI, no index, and do not commit it. It is a local scratch ledger that lets
the next agent turn recover the only facts chat cannot reliably preserve:

- normalized TODO order after dedupe/dependency sorting;
- each item status (`pending`, `waiting`, `in_progress`, `in_review`,
  `pr_open`, `done`, `blocked`) — a lowercase set local to the ledger,
  distinct from the TODO `status:` field;
- PR/branch/worktree for active or opened work;
- exact blocker/wait reason.

Without that ledger, context compaction or a stalled PR can make the agent
repeat a TODO, skip one, or hand control back instead of monitoring. `/goal`
or `/loop` may wrap the action, but the file remains the source of truth.

## Setup

1. Dedupe exact duplicate TODO slugs/paths. Resolve each to a file.
2. Read each TODO's `description`, `work`, `deps.needs`, `scope_limit`,
   `must_preserve`, `anti_patterns`, and `verification`.
3. Topologically sort in-batch `deps.needs`. Cycle members are `blocked`;
   continue any acyclic TODOs.
4. Put the ledger on an already-ignored local path (e.g. an existing scratch
   dir, or `.todo-batch/<slug>.yaml`). If that fallback is visible to git, add
   `.todo-batch/` to `.git/info/exclude` — not the committed `.gitignore` —
   and never stage it.

Minimal state:

```yaml
batch: <slug>
order: [todo-a, todo-b]
items:
  todo-a: {path: <path>, status: pending, pr: null, branch: null, worktree: null, note: ""}
```

Update this file after every status change. On resume, read it first.

## Scheduler

Loop until every item is `done` or `blocked`:

1. Re-read the state file and TODO files.
2. Classify each non-terminal item (`ready` is a derived condition, not a
   stored status):
   - `ready`: `status: pending`, every in-batch dep is `done` (i.e. its PR
     merged into the integration branch — unless a stacked-branch exception is
     recorded in the ledger), and external deps are ready by
     `todo-cli ready`/`todo-cli next`;
   - `waiting`: a dependency PR, external dep, CI check, or merge is still
     pending **and** has a path to resolution this session;
   - `blocked`: missing/malformed TODO, dependency cycle, repeated failure, or
     a wait with no resolution path this session — record the reason.
3. If a TODO is ready, implement it.
4. If none are ready: record ordinary pending CI as `waiting` and move on; use
   bounded monitoring only for a batch-owned dependency gate that must resolve
   before another TODO can proceed. When you do monitor, announce command, max
   runtime, log path, and stop condition (`gh pr checks`, `gh pr view`, the
   project PR-status target, or equivalent). Fix red batch-owned PRs when still
   in scope; mark `blocked` only after one failed recovery. A `waiting` item
   that cannot resolve this session becomes `blocked` with its reason.

Simple not-readiness is `waiting`, not `blocked`.

## Per TODO

For each ready TODO:

1. Mark `in_progress`; write state.
2. Use a fresh pool worktree off the integration branch when available. If a
   dependency PR has merged since the worktree was claimed, refresh it onto
   the updated integration branch first.
3. Use the `todo` skill `implement` action for exactly this TODO.
4. Run the TODO verification block and complete/move the TODO to DONE.
5. Mark `in_review`; write state.
6. Run the `code` skill `review` action on the completed diff before PR (or
   the equivalent five-axis review if that skill is unavailable).
7. Fix every Critical and Required finding unless proven invalid with cited
   evidence. Apply Nit/Consider findings when they fall within `scope_limit`;
   record every skipped Nit/Consider finding in the PR body (or a follow-up
   TODO). Re-run affected verification and re-review after non-trivial fixes.
8. Commit explicit paths only; never `git add -A`.
9. Commit via SHARED/commit-framework, then run the project's PR-open
   equivalent (`pr-preflight` / `pr-open` or the local analogue); capture
   PR/branch/worktree.
10. If a later batch TODO needs this PR merged: mark `pr_open`; enable
    auto-merge **only when the integration branch's gate is CI/checks, not
    mandatory human approval**; monitor until merged, then mark `done`.
    Otherwise mark `done` after PR open.
11. Release the worktree when project policy allows; if the pool requires
    merged PRs, record the worktree as releasable-after-merge instead.

Retry a failed TODO once with the failure notes. A second failure becomes
`blocked`; continue other TODOs.

## Workers

Default is sequential — parallel workers multiply usage-limit pressure and PR
churn for little gain. Use one worker per TODO only when worker sessions are
available; the orchestrator still owns ordering, state, monitors, and final
reporting. Give the worker the Per TODO workflow above and require this exact
return block: `TODO`, `STATUS: done|pr_open|blocked`, `PR`, `WORKTREE`,
`BRANCH`, `NOTES`.

## Final Report

Report `TODO | PR # | status | note`, list blockers with unblock steps, and
include the ledger path. If the session ends before every item is terminal,
the closing message must state the ledger path and the resume command
(re-invoke `batch` with the same inputs — the ledger resumes progress).
