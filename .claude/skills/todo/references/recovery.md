# Recovery

## A gate is not a failure

`kind: "gate"` results are the tracker working. Read `recovery`, act on it, and
continue. Do not retry the same call unchanged.

## Lost claim or restarted session

`take` the same item again: re-adopting your own claim is allowed, mints a
fresh `generation`, and refreshes the lease. An earlier process image still
holding the old generation goes stale — that is the protection working. If
someone else holds the claim, you get `E_CONFLICT`; report that rather than
forcing it.

`E_MULTIPLE_CLAIMS` means you already hold a live claim on another task. Finish
or `release` it first — one live claim per worker.

## Conflicts

`E_CONFLICT` means a competing writer changed the task first. Re-read with
`show_item`, re-evaluate whether your operation still applies, and only then
retry. Retries re-apply the logical operation; they never merge or overwrite
the newer state.

## Offline and unknown outcomes

- `E_OFFLINE`: the remote is unreachable. `list_items` / `show_item` may serve a
  cached revision marked `stale`; mutations fail rather than succeeding locally.
  Retry when reachable.
- `E_UNKNOWN`: a push reply was lost and the outcome is undetermined. The
  `recovery` list carries the operation ID. A human reconciles with
  `todo-db recover --op-id <id>` before anyone re-applies the work.

## Schema and state errors

`E_SCHEMA` means the state format is newer than the installed package; a human
upgrades. `E_STATE` explains itself in the message — a malformed request, an
unknown task, or a rejected transition. `E_CURSOR_STALE` means restart listing
from the first page.

## Prepared receipt recovery

Prepared mode is unavailable on an older server or schema: stop and use the
serial claim/finish loop. Do not migrate a legacy per-item receipt into a
registered batch by assertion.

If a prepared batch is abandoned, release every live member claim and have the
registered owner call `abort_batch` with the batch owner generation. Abort
refuses with `E_ACTIVE_CLAIMS` while a claim is live, refuses if any member is
already `done`, clears prepared/final member evidence, retains an already-bound
final PR receipt, detaches recoverable non-terminal members from the archived
batch, and returns them to the ordinary claim/finish lifecycle. Expired active
claims return to `open`; live claims must be released first. It is safe to retry
after an unknown publication result. An aborted or completed batch
cannot be reopened by a member or a stale owner.

If `prepare` rejects the source checkout, inspect the exact recorded revision
and clean the isolated worktree before retrying with the current claim
generation. A moved HEAD, dirty checkout, changed member scope, conflict
resolution, or late member invalidates the receipt; do not reset the baseline
or mark the member done. Re-take the member and prepare again after the
integrator records the new exact range. If closeout is interrupted, re-read the
member and final integration evidence before retrying `finish`; stale
generations fail closed. A retry must use the registered integration worktree
and branch, and the tracker rechecks the current tree, every accepted member
head, the frozen scope union, and the one bound final PR before committing each
member's terminal transition.
