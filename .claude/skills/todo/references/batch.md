# Batch Implementation

Use `batch` to implement an explicit named TODO set in dependency order. It
authorizes implementation, branches, commits, and PRs only for that set;
auto-merge is allowed only when CI, not human approval, is the integration gate.
It does not bypass repository, tracker, review, or publication gates.

A batch coordinates bounded contexts, not one long conversation. The tracker,
Git, PR service, CI, artifacts, and human decisions remain authoritative.

## Before you start

1. Read repository instructions, `references/implement.md`,
   `shared-change-framework/SKILL.md`, and `shared-review-protocol/SKILL.md` as
   required for the next action; do not copy their rules into the ledger.
2. Run required tracker `--help` checks and `todo doctor`, using the wrapper and
   global-flag ordering from `SKILL.md`. Fix or report any failure and stop
   before claiming or editing; follow that contract on authentication failure.
3. Confirm the exact TODO set, dependencies, integration branch, and existing
   claims, branches, worktrees, and PRs. Reconcile rather than duplicate work.
4. Run any required repository write preflight; fix or report failure and stop.

## Local handoff ledger

Keep one ledger at a stable ignored path outside disposable worktrees, such as
`.todo-batch/<slug>.txt` in the orchestration worktree. Verify it once with
`git check-ignore`; use `.git/info/exclude`, not a committed rule. Never commit it.

Before the first claim or source mutation, initialize the exact named TODO IDs.
Store one latest envelope per item, separated by `---`, and atomically replace
the complete file. Only the serial controller writes it; concurrency is unsupported.

```text
TODO: <id>
STATUS: pending|in_progress|pr_open|waiting|done|blocked
TRACKER_STATE: <observed state>
BRANCH: <branch or none>
WORKTREE: <path or none>
PR: <number or none>
PR_STATE: <open|merged|closed|none>
HEAD: <sha or none>
VERIFICATION: <concise result>
GATE_SNAPSHOT: <gate, concise result/link, or none>
BLOCKER: <owner/reason or none>
NEXT_ACTION: <exact action>
---
```

These are cached observations, not authority for a mutation. Before acting,
revalidate the facts required by `NEXT_ACTION` under the implementation guide,
change framework, and repository policy.

## Schedule bounded work

Run serially. A substantial TODO needs its own implementation, verification,
and review cycle; give it a fresh worker context when supported. Tightly coupled
trivial items may share a context while their combined history remains small.

At each scheduler boundary:

1. Read the ledger once and refresh only state needed to select the next item.
2. Mark missing, malformed, or cyclic items `blocked` with a reason. Record a
   hard tracker blocker through the documented tracker command.
3. Select an item only when its dependencies, including required integration
   merges, are satisfied, tracker state permits claim or resume, and no existing
   branch, worktree, or PR must be reconciled first.
4. Start or resume it with `references/implement.md` in a fresh isolated linked
   worktree from the current integration branch. Refresh after dependency merges
   and remove that clean worktree after merge under repository policy.
5. After one focused retry, classify externally resolvable failures as waiting
   and non-resolvable failures as blocked; record the owner and next action.

If no item is eligible and the remainder waits on external gates, checkpoint,
report, and end the batch invocation. Resumption is a new invocation; do not
turn repeated invocations into an implicit polling loop.

## Worker closeout

Follow implementation, verification, commit, PR, deferral, and completion
contracts by reference. Before commit or PR, run the required internal review,
resolve Critical and Required findings, disposition optional findings under
repository policy, and re-verify substantive fixes.

Do not return full work orders, diffs, logs, or source dumps. Keep long output
in a temporary artifact and return only its result, short tail, link, or digest.
Return the envelope above:

- after successful item closeout;
- before intentionally ending or compacting a worker context; or
- after a failure that requires later resumption.

Store the envelope before selecting more work; add no per-operation
acknowledgements. After an unexpected end, inspect authoritative live state
before retrying an operation with an unknown outcome.

When another item depends on the PR, leave it `pr_open` or `waiting` until
verified merged. Otherwise use the terminal tracker state after PR creation and
completion. An open or green PR is not proof of merge.

## CI and external waits

Before querying a gate, reuse its snapshot from this invocation. Take at most
one concise snapshot per gate, store it in the item envelope, and do not query it
again before the invocation ends. Use bounded fields; keep verbose output
outside context and retain only pending/failing names, links, and next action.

If a gate remains pending, record `waiting`, follow the documented claim
lifecycle, checkpoint, and end the worker. Continue independent eligible work
without retaining that history; if all work waits, end the invocation. Never
sleep or poll in an implementation context.

## Context rotation and resume

At every substantial-item boundary, persist the envelope and discard the worker
transcript. Rotate or compact the controller too; its handoff preserves the
exact TODO set and ledger path, not logs, readiness output, or discussion.

If fresh contexts are unavailable, checkpoint and compact at a safe item or
work-unit boundary. Do not measure occupancy or compact uncheckpointed work. If
neither option exists and history grows large, stop with the ledger and resume action.

A resumed context must:

1. confirm that the requested TODO set exactly matches the ledger;
2. read the ledger once and select its current item and `NEXT_ACTION`;
3. revalidate only the live facts required by that action; and
4. continue without replaying completed work orders, logs, or discussion.

## Final report

Report one concise row per item:

```text
TODO | tracker state | PR/state | head | verification | blocker | next action
```

Include the ledger path and distinguish open, merged, tracker-complete, waiting,
and blocked work. If anything remains non-terminal, provide the exact resume
action rather than waiting in the current context.
