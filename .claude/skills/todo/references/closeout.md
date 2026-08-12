# Batch Close-out

Use `closeout` only after a review has reported findings and a later user
message authorizes remediation and tracker closure. Name the batch, the review
report, and the exact revisions reviewed. If those inputs are missing, collect
them without editing and ask for the required authorization.

One authorized `closeout` call covers fixes for the reported findings,
follow-up PRs, deferral decisions, and tracker closure for the named batch. It
does not authorize unrelated work or a new review scope.

## Phase 1 — refresh evidence

Before editing, confirm that the reviewed revisions and tracker items still
match the report:

- the commit and PR exist and target the expected branch;
- the merge and required checks have the reported state;
- the reviewed findings still apply to the current code;
- `todo show <id> --json` matches the expected tracker state.

Record changed or superseded findings. Do not silently apply a stale review.

## Phase 2 — remediate

1. Fix every Critical and Required finding that still applies, or record the
   evidence that disproves it.
2. Follow `references/batch.md` for worktrees, verification, explicit staging,
   commits, and PRs.
3. Re-run the checks that prove each fix. This is implementation verification,
   not a new review scope.
4. Turn unfixed Nit or Consider items into deferrals or documented skips.

## Phase 3 — close tracker state

1. Resolve open deferrals with `promote` or `dismiss`.
2. Use `complete` with merged PR evidence when the work landed.
3. Use `drop` with evidence when the work proved unnecessary. "Already fixed"
   is valid only when the fixing revision is identified.
4. Leave blocked items open and record the exact unblock condition.

## Report

Report `TODO | finding | disposition | evidence | PR` for each item. Include
remaining blockers and state whether the named batch is fully closed.
