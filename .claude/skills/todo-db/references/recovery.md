# Recovery

## A gate is not a failure

`kind: "gate"` results are the tracker working. Read `recovery`, act on it,
and continue. Do not retry the same call unchanged.

## Lost claim or restarted session

`take` the same item again: re-adopting your own claim is allowed, mints a
fresh generation, and refreshes the lease. An earlier process image still
holding the old generation goes stale — that is the protection working.
If someone else holds the claim, you get `E_CONFLICT`; report that rather
than forcing it.

`E_MULTIPLE_CLAIMS` means you already hold a live claim on another task.
Finish or `release` it first — one live claim per worker.

## Conflicts

`E_CONFLICT` means a competing writer changed the task first. Re-read with
`show_item`, re-evaluate whether your operation still applies, and only
then retry. Retries re-apply the logical operation; they never merge or
overwrite the newer state.

## Offline and unknown outcomes

- `E_OFFLINE`: the remote is unreachable. List/show may serve a cached
  revision marked `stale`; mutations fail rather than succeeding locally.
  Retry when reachable.
- `E_UNKNOWN`: a push reply was lost and the outcome is undetermined. The
  `recovery` carries the operation ID. A human reconciles with
  `todo-db recover --op-id <id>` before anyone re-applies the work.

## Schema and state errors

`E_SCHEMA` means the state format is newer than the installed package; a
human upgrades. `E_STATE` explains itself in the message — a malformed
request, an unknown task, or a rejected transition. `E_CURSOR_STALE`
means restart listing from the first page.
