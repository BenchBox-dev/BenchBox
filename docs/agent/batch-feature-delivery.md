# Feature-batch branch integration

One shared integration branch per batch, one recorded base, one integrator.

## Protocol

1. **Start** (`scripts/batch_integration.py start`): record the shared base
   ref + OID, batch id, member list, and start timestamp in per-worktree git
   config. All later timestamps and ancestry evaluate against the recorded
   base, never the moving ref. The helper never refreshes the base; a moved
   base is reported for operator action.
2. **Local-first**: members prepare in the shared integration worktree (or
   hand verified commits to the integrator); only the integrator updates the
   shared branch. Publication order follows dependency order, never commit
   order. Concurrent-writer conflicts resolve with the loser rebasing onto
   the winner's integration head; the integrator's conflicts escalate to a
   maintainer.
3. **Starting ref**: `worktree-create` builds from fetched
   `origin/develop`; no separate starting-ref option exists. A member that
   genuinely needs a different start records its own base the same way and
   reconciles at integration time. This batch uses one shared base.
4. **Verify** (`... verify`): base currency, single-integrator authorship
   since the base, and member-head ancestry in the integration head. Any
   failure blocks the delivery receipt.
5. **Receipt** (`... receipt`): binds tracker-side per-item acceptance to
   the exact integration head it was evaluated against, with first-prepare /
   first-integration timestamps from branch history. Late members, content
   edits, a moved head, or a moved base invalidate the binding. Member
   preparation evidence never certifies the integrated tree.

## This batch

- Batch `pr-batch-process-improvements`, base `origin/develop`
  `b221e852dba0ec2aa4bce79f15100fb909ff5599` (branch creation base; the
  current tip has since advanced — recorded base stands until a deliberate
  rebase, which re-records).
- Integrator: single agent session; member commits and integration commits
  share authorship (serial preparation under one integrator).
- Correction (2026-09-08): the first `start` recorded the then-current tip
  instead of the branch base; removed and re-recorded against the frozen
  base SHA. The tool refuses overwrite; operator corrections are documented,
  never silent.
