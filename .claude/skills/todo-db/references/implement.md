# Implement TODOs

1. `todo ready` picks the top ready item; `todo claim <id>` prints the work
   order: scope, must-preserves, anti-patterns, verification ladder, ready
   units, and deferrals. Treat it as the whole briefing. If `ready` prints an
   untriaged-findings banner on stderr, run `todo finding candidates` and
   `todo finding triage <id> ...` to dispose of them (a review blind spot, not
   a claimable item) before picking up new work.
2. Per unit, optionally `todo start <id> <wid>`, implement, then
   `todo done <id> <wid> --evidence "<command run / commit / PR>"`.
3. Defer skipped work immediately with `todo defer <id> --summary "..."
   --reason "..."`.
4. Before commit, run `todo check-scope <id>` and
   `todo verify <id> --run [seq]`. Complete with `todo complete <id> --pr <n>` only after units and
   deferrals resolve via `todo promote <deferral-id> --to-item <slug>` or
   `todo dismiss <deferral-id> --reason "..."`.

## Task briefs for large decomposable work

When a TODO decomposes into 3+ independent tasks, write a short per-task brief
before implementation rather than diving straight into code:

- **Goal** — the one-sentence outcome for this task.
- **Files in scope** — the paths this task is expected to touch.
- **Spec/acceptance** — what "done" looks like, drawn from the TODO/spec.
- **Out-of-scope** — adjacent work explicitly deferred, so it doesn't leak in.

After finishing each task, run a per-task spec-compliance review against its
brief before moving to the next task — catching drift early is cheaper than a
single review at the end. This is advisory scaffolding for sequencing large
work; it does not change unit sequencing (`todo start`/`todo done`), the
verification ladder, or commit/authorization rules above.
