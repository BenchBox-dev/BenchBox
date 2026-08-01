---
develop_sha: 253e6a810307ba169f331986420d70c38db6a244
measured_at_sha: 253e6a810307ba169f331986420d70c38db6a244
replay_sha: 9ccb704eac45efece6ccde39207bde69f16c7516
replay_scope: 80 hosted-backend and hardening unit regressions
---
# Evidence record: hosted TODO tracker acceptance (2026-07-18)

Replayable harness backing the "Hosted backend" round and the G1/G3 closures
in `_project/specs/todo-db-tracker.md` (landed in PR #1219, hardened in the
follow-up PR that adds this file). The spec carries the observed numbers;
this file carries the exact commands to reproduce them.

## Prerequisites

- Turso database `benchbox-todo`
  (`libsql://benchbox-todo-joeharris76.aws-us-east-1.turso.io`).
- Credentials: `TODO_DB_URL` + `TODO_DB_AUTH_TOKEN` in the environment.
  Remote sessions get them from the environment config; local sessions can
  mint a short-lived token inline via the maintainer's authenticated CLI:
  `TODO_DB_AUTH_TOKEN=$(turso db tokens create benchbox-todo)`. Never store
  or echo the token.
- All commands below run through the shim `_project/scripts/todo`. Global
  flags (`--db`, `--actor`) go before the subcommand.

## A. Reachability (G1)

```bash
DB=https://benchbox-todo-joeharris76.aws-us-east-1.turso.io/v2/pipeline
# unauthenticated control -> HTTP 401 (auth required, not policy-blocked)
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$DB" \
  -H 'Content-Type: application/json' \
  -d '{"requests":[{"type":"execute","stmt":{"sql":"SELECT 1"}},{"type":"close"}]}'
# authenticated -> HTTP 200; observed 0.15-0.16s per fresh connection.
# The auth header goes through curl's stdin config (-K-), NOT argv: argv is
# world-readable via ps on shared hosts. printf is a shell builtin, so the
# token never appears in any process's argv.
printf 'header = "Authorization: Bearer %s"\n' "$TODO_DB_AUTH_TOKEN" | \
  curl -s -K- -o /dev/null -w '%{http_code} %{time_total}s\n' -X POST "$DB" \
  -H 'Content-Type: application/json' \
  -d '{"requests":[{"type":"execute","stmt":{"sql":"SELECT 1"}},{"type":"close"}]}'
```

## B. Two-process shared-visibility proof

Two shells, distinct replicas and actors (replicas are per-worktree by
default; `TODO_DB_REPLICA` forces distinct paths when replaying from one
worktree). Expected exit codes in comments.

```bash
# Repo-local replica dirs (never world-writable /tmp: the lock/replica
# paths would be symlink-attackable there).
A() { TODO_DB_REPLICA="$PWD/.todo-db/replay-A/replica.db" TODO_ACTOR=actor-a _project/scripts/todo "$@"; }
B() { TODO_DB_REPLICA="$PWD/.todo-db/replay-B/replica.db" TODO_ACTOR=actor-b _project/scripts/todo "$@"; }
A create vis-probe-$(date +%s) --title "Cross-process visibility probe" \
  --worktree spike --priority low --description "Two-replica proof." \
  --work "w1:probe unit"                                   # rc=0
B ready | grep vis-probe                                   # visible cross-replica
A claim <id>                                               # rc=0, prints work order
B claim <id>                                               # rc=2 "claimed by 'actor-a'"
A done <id> w1 --evidence "live probe"                     # rc=0
A defer <id> --summary "gate probe" --reason "proof"       # rc=0
B complete <id>                                            # rc=2 "unresolved deferrals"
B dismiss <deferral-id> --reason "probe complete"          # rc=0 (cross-process resolution)
A complete <id>                                            # rc=0
```

## C. Import (G3)

Non-destructive replay: `todo import-yaml --dry-run` prints the same
imported/skipped/warnings counts without writing. Full replay
(`--replace`) clears the tracker tables and re-imports; it refuses a
non-empty target without `--replace`, atomically (the emptiness guard runs
inside the transfer's `BEGIN IMMEDIATE` transaction).

Recorded result (drifts as TODO/DONE files land):
`imported: 1364  skipped: 0  warnings: 18`,
`deps_resolved 539, deps_dangling 1`, stats `open` deferrals 629 — these
reproduce exactly at this file's pinned SHA. The historical PR #1219 live
measurement is separately bound to that exact head tree in
[`todo-db-hosted-live-measurement-2026-07-18.md`](todo-db-hosted-live-measurement-2026-07-18.md).
A replay at the pinned SHA yields 32,621
rows (intervening TODO/DONE edits), and the hardened CLI reports pipeline
requests (data batches + guard + commit), so a replay prints 84. Verify hosted == local by
running the same import into a scratch local file
(`TODO_DB_PATH=/tmp/ctl.sqlite`) and diffing the report lines and `stats`.

## D. Shim UAT lifecycle

The `TestWrapperUatLifecycle` sequence executed live against the hosted
database (create → ready → claim → out-of-order done rc=2 → start/done with
evidence → verify --run pass → defer → complete rc=2 → promote → complete →
export ×2 byte-identical → late defer rc=2). Cleanup: `todo drop` the
promoted follow-up with reason "UAT artifact". Recorded run: deferral #630,
export over 1,366 items identical, final stats coherent (open 629 /
promoted 1). Command latency observed: reads 0.7–0.8s warm; writes
1.5–3.3s; first connect per worktree pays a cold replica sync (~3.4s at
12.8MB).

## E. Hardening regressions (post-merge review)

Failure paths are pinned by `tests/unit/scripts/test_todo_db_hosted.py`
(fake libsql client + fake Hrana primary): plaintext `http://` refusal
(scheme-normalized: `HTTP://`/whitespace variants are caught too),
COMMIT isolated from data batches and withheld on any statement error,
stream close (rollback) on mid-transfer failure, `base_url` carried across
baton-chained requests, atomic emptiness guard, network/JSON error mapping
to exit 2, replica setup flock. Second wave: redirect refusal (urllib
carries Authorization across redirects), transactional `promote` with a
concurrent-connection lock probe, degraded-mode fresh-replica refusal,
atomic schema bootstrap, broadened busy/network error mapping with
redaction at the CLI boundary, whole-tracker import guard, conditional
`sweep-stale`, migrate re-check under lock, `O_NOFOLLOW` on the lock.
Replay: `uv run -- python -m pytest
tests/unit/scripts/test_todo_db_hosted.py
tests/unit/scripts/test_todo_db_hardening.py -q`. Live counterpart (needs
`TODO_TEST_DB_URL` + `TODO_DB_AUTH_TOKEN`, a dedicated test database):
`uv run -- python -m pytest tests/integration/test_todo_db_hosted_live.py
-m live_integration -q`.

Spot replay on 2026-08-01 at `9ccb704eac45efece6ccde39207bde69f16c7516`
ran the documented hosted-backend and hardening unit files single-process:
80 passed. The credentialed live counterpart and historical latency/import
totals were deliberately not replayed, so `replay_scope` does not corroborate
those claims.
