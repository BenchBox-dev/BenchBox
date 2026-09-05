# Batch implementation

Implement a named set of TODO items in dependency order. A batch coordinates
work across clean, bounded contexts instead of one long conversation. The
tracker, Git, and CI remain authoritative.

## Before you start

1. Call `get_instructions` and `doctor` to confirm principal and database health.
2. Verify the requested item set, dependency relationships, and target branches.
3. Keep one local ledger at an untracked path outside disposable worktrees, such
   as `.todo-batch/<slug>.txt`. Verify it with `git check-ignore`.

## Local ledger format

Store one entry per item, separated by `---`. Atomically update the file before
and after each item:

```text
TODO: <id>
STATUS: pending|in_progress|pr_open|waiting|done|blocked
TRACKER_STATE: <state from tracker>
CLAIM_TOKEN: <token or none>
BRANCH: <branch name or none>
WORKTREE: <path or none>
PR: <number or none>
HEAD: <git commit sha or none>
VERIFICATION: <result summary or none>
BLOCKER: <owner or reason or none>
NEXT_ACTION: <tool call or floor verb>
---
```

These entries cache observations. Always re-verify live facts before running a
mutation.

## Execution loop

Run items serially:

1. **Select eligible item**: Read the ledger. Choose the next item whose
   dependencies are satisfied and whose tracker state allows a claim.
2. **Start work**:
   - Create or switch to an isolated worktree from the integration branch.
   - Call `take(id=...)` to claim the item and record the returned `claim_token`.
   - Call `context(id=...)` to review work units, scope rules, and verifications.
3. **Implement**:
   - Follow `references/implement.md` for editing within scope.
   - Record progress on each unit with
     `progress(id=..., wid=..., evidence=..., claim_token=...)`.
4. **Verify and finish**:
   - Call `check_scope(id=...)` before committing.
   - Request human verification via `todo-db verify-run` when hitting `E_VERIFY_GATE`.
   - Call `finish(id=..., claim_token=...)` to close the item.
5. **Rotate context**:
   - Update the ledger status.
   - Between substantial items, discard the worker context or compact history.
   - Resume in a fresh context by reading the ledger and confirming live Git and tracker state.

## Waiting and external gates

Do not poll in a loop when waiting for CI or code review:

1. Record `STATUS: waiting` in the ledger with the pending gate name.
2. If your lease might expire while waiting, call `release(id=..., claim_token=...)`
   so other processes are not blocked.
3. Stop execution and report the exact resumption action to the user.
