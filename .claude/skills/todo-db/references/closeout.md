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

1. Fix all critical and required findings.
2. Run local tests to prove each fix.
3. Record fixes with git commits using explicit paths (`git add <file>`).
4. If a finding uncovers necessary work outside the batch scope,
   `create_item` a follow-up with `needs` pointing at the current item
   rather than widening scope silently.

## Phase 3 — close tracker items

1. If you hold the claim, call `finish(id=..., generation=...)`.
2. If closing externally merged work without an active claim, `take` the
   item first (or tell the human to close it if it is claimed by someone
   else).
