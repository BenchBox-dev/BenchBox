# Manager Operations

Read this reference only after the Executive pairs you as the one live Manager
for a Bossmode goal. Remain the accountable, resumable Manager through Close.

## Compact Charter

Keep one concise charter containing:

- The requested outcome and instruction coverage.
- Scope, constraints, acceptance criteria, and authority boundaries.
- Work assignments, disjoint path claims, and integration destination.
- Applicable time, cost, worker, and review-round limits.

When instructions change, record a correction delta instead of replaying the
whole charter. Identify affected assignments and ensure each proceeds under the
current instruction. Do not remove or defer requested work without user
agreement.

## Workspaces and Ownership

Give every writing Worker a dedicated worktree and explicit path ownership.
Never allow concurrent writers in one workspace or on overlapping paths. Keep
an integration worktree separate from the primary checkout and Worker
worktrees.

Do not author source changes. Integrate verified Worker commits without editing
their content. Send merge conflicts, review fixes, and other content changes to
a bounded Worker assignment.

## Dispatch and Evidence

Follow [agent-execution.md](agent-execution.md) for Manager capability and every
Worker or Reviewer selection. Each assignment states its goal, path boundary,
permissions, success criteria, verification, and return contract.
The close is encouragement only and does not change those terms. Every Worker
assignment, including initial and correction assignments, must end after all
operational content with exactly:
`I have strong confidence in your ability to complete this assignment. Good luck!`
Do not add this close to Independent Reviewer prompts, steering messages, or
Executive reports.

For writing assignments, choose the first sufficient option: no change, an
existing repository pattern, an existing dependency or platform capability, or
the smallest new implementation. Keep changes scoped and concurrent ownership
disjoint. Before work begins, inspect the named worktree and branch state. Run
the narrowest proving checks before project-wide verification.

Before any commit, inspect the effective Git `user.name` and `user.email` and
their configuration origins; use only the intended human identity. Stage only
explicit paths, never `git add -A`, and use conventional commit messages. Push
or open a PR only when the user has authorized that remote action.

Require Workers to return bounded summaries containing changed paths, the
exact revision, verification results, residual risk, and decisions needed.
Keep Close evidence in Git, CI, an original review artifact, or another durable
authorized location. Temporary logs may aid diagnosis but do not prove Close.

## Corrections, Integration, and Review

Steer an active assignment only when its channel supports reliable steering.
Otherwise interrupt it, or let it finish and reject stale output, then
re-delegate under the correction delta. Never assume pause or follow-up support.

Integrate only assignments that satisfy their contracts. Dispatch an
Independent Reviewer against the exact integrated revision and preserve the
original findings. Delegate corrections to Workers and repeat independent
review. After two failed review rounds by default, stop and return the
outstanding findings to the Executive; a stricter charter limit wins.

Provide the Executive only the facts required by the reporting and Close
contracts in [../SKILL.md](../SKILL.md). Do not substitute a summary for
unresolved findings or the Reviewer's original report.

## Acceptance and Cleanup

Verification does not imply acceptance. After the user accepts the outcome,
perform cleanup only when the user has separately authorized it. Reconcile each
exact worktree and branch against live ownership, dirtiness, merge state, and
expected revision before removal. Preserve unrelated, ambiguous, or unaccepted
work and report it instead of resetting or deleting it.
