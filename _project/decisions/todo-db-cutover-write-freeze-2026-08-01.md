# Hosted tracker cutover: write freeze, quiescence, and rollback

**Date**: 2026-08-01
**Status**: decisions D1–D6 recorded; **cutover NOT authorized** (see "Current
verdict"). Supersedes the claim-check precondition on
`migrate-hosted-tracker-db-to-todo-db-0-3-schema`.
**Related**: PR #1377 (freeze landed), PR #1386 (freeze hardening),
`todo-cli-schema-bump-must-ship-with-db-migration-v2`.

## Context

`migrate-hosted-tracker-db-to-todo-db-0-3-schema` restores the hosted
`benchbox-todo` database from a snapshot using `restore-legacy --replace`. That
rebuilds every table. **Any write landing between snapshot and restore is
destroyed silently**, and the destruction is invisible afterwards because the
audit chain is rehashed from the same snapshot it was rebuilt from — a corrupted
cutover still verifies.

The original precondition was a **claim check**: refuse the restore while another
actor holds a live claim. That is not a gate. Claims cover
`claim`/`start`/`done`/`complete` on *existing* items; `create`, `defer`,
`promote`, `block`, `drop` and every config write take no claim at all. On
2026-08-01 the tracker took 21 unclaimed `create`/`drop` events from a single
actor in under four minutes. A claim check would have permitted the restore
throughout.

PR #1377 replaced it with a **leased write freeze**: `todo freeze` refuses every
mutating command from any other actor, reads are untouched, the holder keeps
writing so it can run the cutover and lift its own freeze, and the lease expires
on its own so a holder that dies mid-cutover cannot wedge the tracker.

## Decisions

| ID | Decision | Choice | Reason |
|---|---|---|---|
| D1 | What gates the destructive restore | The **leased write freeze**, never a claim check. | Claims do not cover unclaimed writes, which are the majority of tracker mutation. Empirically the dominant write mode. |
| D2 | Enforce the freeze by bumping `SCHEMA_VERSION` so stale clones hard-fail? | **No.** `SCHEMA_VERSION` stays 4; the freeze remains **advisory** against clones running a pre-#1377 CLI. | See "D2 rationale" below. This is the change's known, accepted weakness. |
| D3 | Consequence of D2 for the runbook | The freeze is **necessary but not sufficient**. The runbook MUST pair it with independently verified quiescence. Neither gate alone authorizes the restore. | A stale clone writes straight through a live freeze. Quiescence alone was never a gate. Both, together, or not at all. |
| D4 | How quiescence is measured | The `stats["events"]` fingerprint (`count`, `last_seq`, `latest`) compared across a window, by a probe that **fails when it cannot read the fingerprint**. | The previous probe shelled out to `todo stats --json`, which does not exist; it compared two empty strings and passed unconditionally. See "The vacuous rung". |
| D5 | Freeze TTL bounds | Finite, positive, `<= MAX_FREEZE_TTL_HOURS` (168h); default 2h. Malformed/torn freeze state reads as **live** (fails closed); `freeze` itself stays exempt from the gate so a torn freeze is always liftable. | A freeze is a maintenance window, not a standing state. A safety gate whose degraded state is "unlocked" is the wrong default; one that cannot be lifted is the other wrong default. Both were real defects (PR #1386). |
| D7 | Fixing create-time-only fields with todo-db 0.3's audited `update` verb, before the cutover | **Not available.** todo-db 0.3 is `SCHEMA_VERSION = 5` and refuses a v4 database outright: *"database contains a different tracker schema (item_deps, items, meta, work_units); use a dedicated todo-db path"*. It fails **safe** — detects the foreign schema, refuses, does not corrupt. | The verb only becomes usable *after* the cutover, and the cutover is gated on a probe that `update` would have fixed. Circular. Verified 2026-08-01 against a local v4 database, never production. |
| D8 | The vacuous rung on the freeze item | **Superseded, not edited.** The operative quiescence gate is the probe on `cutover-record-corrections-and-quiescence-probe`. Rung 1 of `tracker-cutover-needs-a-write-freeze-not-a-claim-check` is void and MUST NOT be used to certify quiescence. | Ladders are create-time-only and D7 rules out an in-place edit. The freeze item has **zero** dependents, so drop+recreate would be cheap — but its work is already done and merged, and its ladder only matters at completion time. Superseding is proportionate; dropping a live-claimed item to correct a rung is not. |
| D6 | Rollback storage | A durable local backup **outside** the repo (`~/todo-db-backups/`) plus a 17-table snapshot, both taken immediately before the restore and retained until an audit verify passes against the hosted DB post-cutover. | The prior attempt ran in an ephemeral container that restarted mid-session. Ephemeral disk is not a rollback path. |

### D2 rationale — why `SCHEMA_VERSION` is not bumped

Enforcement lives only in the new `main()`. A session running a pre-#1377
`todo_db.py` has no gate and writes through a live freeze. Bumping
`SCHEMA_VERSION` would force those clones to upgrade — genuine enforcement —
but the cost is disqualifying:

- The version check runs **before every subcommand, including read-only ones**.
  A bump makes `list`/`stats`/`show` fail for every session until someone runs
  `todo migrate` manually. This is not hypothetical: PR #1347 did exactly this
  on 2026-07-30 and caused a **total tracker outage**, which is why
  `todo-cli-schema-bump-must-ship-with-db-migration-v2` exists.
- The coercion is permanent and borne by every session forever, to close a
  transient ~2h window that occurs once.
- It interacts badly with the freeze itself. Since PR #1386, `migrate` is gated
  by the freeze. A bump landing during a cutover would leave a stale session
  unable to read (schema mismatch) *and* unable to migrate (frozen) until the
  holder lifts the freeze. Correct, but a hard lockout.

**Accepted residual risk**: a stale clone can corrupt a cutover. D3 is the
mitigation — quiescence is verified independently, so a stale writer is
*detected* even though it is not *blocked*. If enforcement is ever wanted, the
right vehicle is `-v2`'s "graceful read-only degradation" option (reads keep
working across a version gap, writes refuse), not a bare bump.

### The vacuous rung

Rung 1 of the freeze item's verification ladder read:

```
g=lambda: subprocess.run(['_project/scripts/todo','stats','--json'],
                         capture_output=True, text=True).stdout
a=g(); time.sleep(60); sys.exit(0 if a==g() else 1)
```

`todo stats` has no `--json` flag. Both calls exit 2 with empty stdout, `"" ==
""`, and the rung passes **unconditionally**. Executed verbatim against
production on 2026-08-01 it exited 0 ("no writer is active") while the event
count moved **4534 → 4538 during the very 60 seconds it was measuring**.

`stats["events"]` (added by #1377) makes a correct probe writable. Rung text is
create-time-only, so the replacement ships on a successor item.

## Cutover runbook

Each step is a gate. A failure at any step aborts; do not continue and do not
"verify by success message".

1. **Preconditions.** `todo-db >= 0.3` CLI reachable and at `origin/main`.
   Durable backup dir exists outside the repo. No other session active.
2. **Backup.** `~/todo-db-backups/benchbox-todo-<UTC>.db` **plus**
   `todo export --snapshot <file>` outside the repo.
3. **Assert the snapshot is complete.** Per-table row counts, not a success
   message: **17 tables**, `findings=65`, `finding_sections=8`,
   `finding_links=36`. A 12-table snapshot with `findings=0` is the known silent
   failure — the findings tables are deliberately excluded from
   `TRANSFER_TABLES` and `EXPORT_TABLE_ALLOWLIST`, so any path iterating those
   constants moves zero findings rows **and reports success**.
4. **Freeze.** `todo freeze --reason "0.3 cutover" --ttl 2`. Confirm
   `freeze --status` shows you as holder.
5. **Verify quiescence independently (D3/D4).** Compare the `events` fingerprint
   across a window with a probe that fails on unreadable output. The freeze does
   not substitute for this; a stale clone is invisible to it.
6. **Rehearse** into a scratch SQLite DB **seeded from the real snapshot**, never
   an empty one — an empty target hides PK-collision bugs (this is exactly how
   the `finding_events.seq=1` collision reached production). Use a dedicated
   `TODO_DB_REPLICA`.
7. **Verify the rehearsal by counting rows per table**, not by trusting
   `restored legacy snapshot`. A prior attempt printed success, returned a valid
   4,187-event chain, and had `finding_sections` empty.
8. **Re-verify quiescence** (step 5 again). The window between rehearsal and the
   hosted run is itself exposure.
9. **Hosted restore.**
10. **Sync or reopen before verifying anything you just wrote.** Hosted reads go
    through an embedded replica; a connection opened earlier sees stale data.
    This produced a false `PARITY FAILED` on a fully correct import.
11. **Post-cutover verify**: per-table counts again, audit verify, `todo stats`.
12. **Credential rotation** (below).
13. **Lift the freeze**; retain backup + snapshot until step 11 has passed.

### Credential change: `TODO_DB_RO_AUTH_TOKEN`

`.github/workflows/todo-db-export.yml` reads the hosted DB with a **read-only**
token supplied as the repo secret `TODO_DB_RO_AUTH_TOKEN`. If the cutover
replaces or re-creates the database, that token stops resolving and the nightly
export silently loses its source. Re-mint the read-only token against the
post-cutover database and update the GitHub secret **as part of the cutover**,
not afterwards. Tokens must always be minted with `--expiration`; they never
expire by default. Never write a token to a file in the repo.

Also confirm `hosted_db_name` still parses the post-cutover URL: it strips the
last hyphenated component assuming `<db>-<org>`. A wrong parse makes
`--confirm-target` unmatchable — it fails *safe* (refuses), but the bulk path
becomes unusable until corrected.

### Rollback

Trigger rollback on any per-table count mismatch, any audit-verify failure, or
any unexplained event-chain discrepancy — **not** on the absence of an error
message, which the known failure mode does not produce.

Restore `~/todo-db-backups/benchbox-todo-<UTC>.db` to the hosted primary, then
re-run step 11's counts against the restored state. The freeze stays held across
the rollback; lift it only once counts match. `_project/blind-spots/` is frozen
(2026-07-30) and **is** the findings rollback window — do not delete the corpus
until after a successful cutover is verified.

## Current verdict — the cutover is NOT authorized

As of 2026-08-01, **one** condition still blocks it.

1. **The tracker is provably not quiescent.** `root@vm` wrote 21 events between
   12:29Z and 12:33Z and 4 more during a 60s probe window. Items moved
   1726 → 1758 and events 4440 → 4538 inside a single session. That session is
   live; its claim on the freeze item is **not** stale and must not be swept.

Cleared since this ADR was first written:

- ~~The quiescence probe is vacuous~~ — still true of the freeze item's rung 1,
  but D8 supersedes it and a working probe now exists on
  `cutover-record-corrections-and-quiescence-probe`. Use that one.
- ~~Two findings-domain fixes are unmerged~~ — **#1359 and #1373 both merged.**
  The `replace_evidence` guard and `_reconcile_capture_owned` are on `develop`.
- Freeze hardening (#1386) is merged: fail-closed torn state, bounded `--ttl`,
  and a freeze gate for `migrate`.

D3 remains the standing rule: the freeze **plus** verified quiescence, or no
cutover. With the code blockers cleared, quiescence is now the only gate — and
it is currently failing for a real reason, which is the gate working.
