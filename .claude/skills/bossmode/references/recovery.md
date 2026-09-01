# Manager Recovery

Read this reference only when a paired Manager is lost, unresponsive, or must
be replaced. Do not use it during ordinary execution. Scope every step below
to that Manager's own topic.

## Authority and Containment

Live runtime state is authoritative. Stored handles are hints only; reconcile a
session against its live identity and state before acting on it.

The Executive may interrupt the failed Manager's verified live descendants
only to contain that Manager's work. The Executive must not redirect those
agents or adopt, integrate, evaluate, or accept their work. Never act on a
stale name, pane, or stored session handle alone.

## Resume or Replace

Resume the same Manager when its live identity, continuation channel, and
ownership can be verified. Otherwise, before pairing a replacement:

1. Reconcile the failed Manager's live descendants and contain its active
   writers; leave other Managers' sessions, worktrees, and branches
   untouched.
2. Inspect that topic's worktrees, branches, path claims, current
   instructions, correction deltas, integrated revisions, and durable
   evidence.
3. Preserve ambiguous or unverified work. Do not reset, clean, merge, or delete
   it automatically.
4. Give the replacement Manager a bounded handoff of verified state and route
   it to [manager.md](manager.md).
5. Report the replacement through the Executive reporting contract.

No replacement may begin dispatch, implementation, integration, or review
until it is verified live and owns the reconciled charter and work boundaries.

Recovery is event-driven. Do not invent generations, clocks, background health
polling, a scheduler, or a registry to simulate runtime authority. Use live
sessions, Git, and durable authorized artifacts as evidence.
