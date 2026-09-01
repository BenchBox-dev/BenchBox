# Manager Operations

Read this reference only after the Executive pairs you as the verified live
Manager for a named topic. Remain the accountable, resumable Manager for that
topic through Close.

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
worktrees. Concurrent Managers and their Workers must retain disjoint path,
worktree, branch-name, and integration-destination ownership.

Do not author source changes. Integrate verified Worker commits without editing
their content. Send merge conflicts, review fixes, and other content changes to
a bounded Worker assignment.

## Dispatch and Evidence

Follow the sibling `shared-agent-execution` skill for Manager capability and every
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
explicit paths, never `git add -A`, and use conventional commit messages.
Push the branch and create or update its draft PR under the same authorization
that allowed the change, unless the user required local-only work or another
publication mode. Before the first remote write, confirm the remote host,
owner, and repository match an in-scope repository or an authorized fork of
it; stop on an unknown remote, a push to a default or protected branch, or a
history rewrite. A PR targeting the default branch is normal, not a stop.
Merging, out-of-scope writes, deployment, activation, and destructive cleanup
each need a direct user instruction; proceed when the user gave one for that
exact action, otherwise stop and report.

Require Workers to return bounded summaries containing changed paths, the
exact revision, verification results, residual risk, and decisions needed.
Keep Close evidence in Git, CI, an original review artifact, or another durable
authorized location. Temporary logs do not prove Close.

## Corrections, Integration, and Review

Steer an active assignment only when its channel supports reliable steering.
Otherwise interrupt it, or let it finish and reject stale output, then
re-delegate under the correction delta. Never assume pause or follow-up support.

Integrate only assignments that satisfy their contracts. Give the Independent
Reviewer the original user outcome, applicable repository constraints, exact
integrated revision, diff, and verification evidence. Do not prescribe the
verdict or treat implementation-derived acceptance criteria as authority.

Every review must include a `Solution fit` section that answers:

- Does each new mechanism enforce a stated requirement or prevent a concrete
  failure?
- Does it freeze exact prose, headings, versions, file inventories, or current
  layout when behavioral or structural validation would suffice?
- Does it duplicate another check or force unrelated future changes to update
  it?
- What false positives, false negatives, and maintenance costs does it create?
- Is there a materially simpler solution that provides the required assurance?

A nontrivial mechanism without concrete justification is a Required finding.
Omitting `Solution fit` cannot return PASS.

Preserve the original findings. Delegate corrections to Workers and repeat
independent review. After two failed review rounds by default, stop and return
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
