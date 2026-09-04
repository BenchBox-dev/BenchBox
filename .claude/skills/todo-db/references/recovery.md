# Recovery

## A gate is not a failure

`kind: "gate"` results are the tracker working. Read `recovery`, act on it, and
continue. Do not retry the same call unchanged, and do not route around a gate
by widening scope or skipping verification.

## Lost claim or restarted session

`context` on the item id returns the current `claim_token` and `next_action`.
If the claim expired, `take` the item again — re-adopting your own claim is
allowed and is not a conflict. If someone else holds it, `next` will not offer
it; report that rather than forcing it.

`claims` lists everything you hold. It is the recovery path for
`E_MULTIPLE_CLAIMS`: finish or `release` the stale claim, then take the one you
want.

## Scope violations

`check_scope` takes the list of files you changed and reports which fall
outside the item's scope rules. It is read-only, so run it before `progress`
rather than discovering the problem at `finish`.

Two legitimate resolutions:

1. The change does not belong to this item. Move it out.
2. The scope was drawn too narrowly. Amend it with `update_item` and say why.

Widening scope to make a gate pass, without a reason that survives review, is
the failure mode this gate exists to catch.

## The verification gate

`finish` requires a current workspace-fingerprint attestation. Agents cannot
produce one: `verify-run` is a human step, deliberately, because the stored
commands are arbitrary code and on a shared tracker they were written by
another actor.

When `finish` returns `E_VERIFY_GATE`, the `recovery` list contains the exact
invocation. Surface it verbatim and stop. After the human runs it, call
`finish` again — the attestation binds to the workspace state, so any further
edit invalidates it and the ladder must run again.

## Hosted credential failures

`E_AUTH_MISSING` means no credential resolved; `E_AUTH_REJECTED` means the
server refused the one supplied. Neither is something to retry into. Stop
writing and report it. Credentials are provisioned outside the agent, and a
rejected credential needs a fresh process after replacement.

Ambiguous failures — quota, suspension, network, TLS — stay generic rather than
being reported as auth problems, so that a caller never mistakes them for a
reason to mint a new credential.

## Schema and identity

`E_SCHEMA_BEHIND` means the database predates the installed `todo-db`; a human
runs `todo-db migrate`. `E_IDENTITY` means the database belongs to a different
project — that is the isolation guarantee working, and it is never resolved by
forcing the write. `doctor` reports both without mutating anything.
