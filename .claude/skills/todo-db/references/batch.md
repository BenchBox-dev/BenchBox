# Batch implementation

Implement a named set of TODO items in dependency order. A batch coordinates
work across clean, bounded contexts instead of one long conversation. The
tracker, Git, and CI remain authoritative.

## Before you start

1. Call `get_instructions` and `list_items(ready_only=true)` to confirm
   identity and live state.
2. Verify the requested item set, dependency relationships, and target branches.
3. Keep one local ledger at an untracked path outside disposable worktrees, such
   as `.todo-batch/<slug>.txt`. Verify it with `git check-ignore`.

## Local ledger format

Store one entry per item, separated by `---`. Update the file before and
after each item:

```text
TODO: <id>
STATUS: pending|active|pr_open|waiting|done|blocked
GENERATION: <claim generation or none>
BRANCH: <branch name or none>
WORKTREE: <path or none>
PR: <number or none>
HEAD: <git commit sha or none>
BLOCKER: <owner or reason or none>
NEXT_ACTION: <tool call or floor verb>
---
```

These entries cache observations. Always re-verify live facts before running
a mutation.

## Execution loop

Run items serially:

1. **Select eligible item**: Read the ledger. Choose the next item whose
   dependencies are satisfied (`show_item` lists `unmet_needs`).
2. **Start work**:
   - Create or switch to an isolated worktree from the integration branch.
   - Call `take(id=...)` and record the returned `generation`.
3. **Implement**: follow `references/implement.md`.
4. **Finish**: `finish(id=..., generation=...)`, then update the ledger.
5. **Rotate context**: between substantial items, discard the worker
   context or compact history. Resume in a fresh context by reading the
   ledger and confirming live Git and tracker state.

## Waiting on external gates

Do not poll in a loop when waiting for CI or code review:

1. Record `STATUS: waiting` in the ledger with the pending gate name.
2. If your lease might expire while waiting, call `renew` to extend it,
   or `release` so other workers are not blocked.
3. Stop execution and report the exact resumption action to the user.
