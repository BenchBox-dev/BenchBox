# Batch close-out and remediation

Remediate findings from a code review and close tracker items for a completed
batch.

## Prerequisites

Start this workflow only when:
1. A code review has reported specific findings.
2. The user has explicitly authorized remediation and tracker closure.

## Phase 1 — verify live state

Before modifying code, confirm that the review report matches reality:

1. Check that the branch, commits, and PR exist and target the expected branch.
2. Call `show_item(id=...)` to confirm current item state and active claims.
3. Confirm which reported findings still apply to the current code. Discard
   findings that are obsolete.

## Phase 2 — remediate findings

1. Fix all critical and required findings within the item's scope rules.
2. Run local tests to prove each fix.
3. Record fixes with git commits using explicit paths (`git add <file>`).
4. If a finding uncovers necessary work outside the batch scope, call
   `defer(id=..., summary=..., reason=...)` rather than widening scope.

## Phase 3 — close tracker items

1. **Resolve deferrals**:
   - Call `promote_deferral(deferral_id=...)` to generate a follow-up item
     (the new item ID is returned in `new_item`).
   - Call `dismiss_deferral(deferral_id=..., reason=...)` for rejected items.
2. **Complete items**:
   - If the agent holds the claim, call `finish(id=..., claim_token=...)`.
   - If closing externally merged work without an active claim, tell the human
     to run the floor verb:
     `todo-db complete <id> --pr <pr-number>`
3. **Drop unneeded items**:
   - If work proved unnecessary, call `drop(id=..., reason=...)` (requires `--profile full`).

## Close-out report

Provide a final summary table:

| TODO | Finding | Action Taken | Verification | PR / Commit |
|---|---|---|---|---|
| `ITEM-1` | Scope leak in auth | Refactored into helper | `pytest tests/test_auth.py` | `abc1234` |

State whether the batch is completely closed or what blockers remain.
