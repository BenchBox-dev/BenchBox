# BenchBox todo-db extraction: staged integration and acceptance handoff

Status: migration and compatibility evidence complete. BenchBox now uses the
locked `todo-db` 0.3.2 package exclusively, while `_project/scripts/todo`
remains the stable repository entry point.

## Live evidence at this handoff

- BenchBox compatibility hardening merged in PR #1239 (`8ad8e007d`).
- The historical corpus at `6fde4cd36^` contains 1,364 YAML mappings plus seven
  Markdown files. Dual import produced 1,364 items on both sides, zero skips,
  zero semantic diffs, and equal counts for every tracker table.
- A read-only live snapshot of the BenchBox Turso database contained 1,510
  items and 2,862 events. It restored into standalone schema v3 with every
  tracker/meta table equal, event provenance equal, a verified
  `sha256-chain-v2` audit chain, and an exactly equal second clean export
  including all three migration records.
- `todo-db` 0.3.2 is published as the private GitHub release tag `v0.3.2`,
  built from merged commit `389a3592cb92a8afde47d6d3b807ba3930f98316`. BenchBox vendors the verified wheel
  under `_project/scripts/vendor/`; consumers resolve that artifact through the
  locked scripts environment, never a sibling checkout or private Git fetch.
- No hosted write credential was used and the hosted primary was not modified.

## Compatibility boundary

`_project/scripts/todo` remains the stable entry point and always runs the
package-backed BenchBox adapter:

```sh
_project/scripts/todo --db PATH_OR_URL <command>
```

The adapter passes an argv list to the canonical `todo-db` executable, verifies
its `--version` handshake (and an exact expected version when configured), pins
an explicit BenchBox database path, adds the BenchBox project identity, and
preserves actor/worktree context and exit statuses. It has no shell interpolation and
redacts both `TODO_DB_AUTH_TOKEN` and `TODO_DB_RO_AUTH_TOKEN` in delegated
output. Export keeps the old `items.jsonl` and `index.md` views while adding a
lossless `todo-db.json` envelope containing metadata/config, all tracker tables,
schema migrations, and hash-chained events.

| Command family | Generic operation | BenchBox adapter responsibility |
|---|---|---|
| `init`, `migrate`, `config` | schema, migration, and database settings | add BenchBox identity; require an explicit configured database |
| `create`, `show`, `claim`, `release`, `deps`, `unblock` | item and lease lifecycle | preserve actor and work-order invocation |
| `start`, `done` | work-unit lifecycle | delegate worktree/branch capture from the BenchBox cwd |
| `defer`, `promote`, `dismiss` | deferral lifecycle | preserve legacy arguments and output |
| `complete`, `drop`, `block` | terminal/block transitions | preserve policy errors and exit behavior |
| `list`, `ready`, `stats` | read-only views | preserve command names and legacy output mode |
| `check-scope`, `verify`, `lint` | policy gates | preserve the standalone compatibility exit contract |
| `export` | lossless envelope | render legacy JSONL/Markdown compatibility views |

The standalone YAML and legacy-snapshot bridges preserve BenchBox policy rows,
terminal deferrals, metadata, and ordered event provenance. Legacy events are
re-hashed under the standalone audit contract during restore; the original
timestamp, actor, action, item identity, and detail remain unchanged.

## Package-only shadow import and export check

The repeatable path is `_project/scripts/todo_db_shadow.py`. It requires a new
explicit target and refuses protected databases, existing targets, and an empty
YAML source. It imports into the locked package's scratch target, reads the raw
package tables, exports the lossless envelope, and writes one canonical JSON
report that proves the export preserves the imported database:

```sh
SHADOW_DB="${TMPDIR:-/tmp}/benchbox-todo-shadow.sqlite"
REPORT="${TMPDIR:-/tmp}/benchbox-todo-shadow.json"
rm -f "$SHADOW_DB" "$REPORT"  # only these explicitly named temp files

uv run --project _project/scripts -- python _project/scripts/todo_db_shadow.py \
  --todo-dir _project/TODO \
  --done-dir _project/DONE \
  --db "$SHADOW_DB" \
  --report "$REPORT"
```

The shadow tool invokes `todo-db` only as `uv run --project
_project/scripts --locked -- todo-db`. The package must be present in the locked
BenchBox scripts environment; an absent or incompatible package is an error,
with no PATH or sibling-checkout fallback.

The report compares raw database and exported item counts and IDs, titles,
states, priorities, worktrees, descriptions, categories, approaches, work
units, prerequisites, dependencies, scope rules, verification rows, preserves,
anti-patterns, prior art, deferrals, metadata, and audit event provenance.
Ordering is canonical. On any failed import after the dedicated target is
created, the tool removes only that new target and its adjacent export file; it
never deletes a protected or pre-existing database. The legacy-to-package
parity gate was completed before the embedded runtime was removed. To repeat
that historical evidence, extract `_project/TODO`, `_project/DONE`, and the
embedded importer from `6fde4cd36^` into an isolated scratch checkout; do not
modify a live clone.

Failure recovery is to discard only the isolated target/report and diagnose the
locked package. BenchBox has no embedded-runtime feature flag or fallback after
the package-only cutover.

## Export workflow and restore validation

### Item prose is published

The tracker database is hosted, but `todo export` writes
`_project/todo-db-export/` (`README.md`, `index.md`, `events.jsonl`,
`items.jsonl`) and those files are tracked in Git. Item titles, descriptions,
approaches, work-unit summaries, verification rungs, and drop reasons therefore
reach the public repository on the next snapshot PR.

Treat every tracker write as publication. When logging a privacy or security
finding, reference the token or the field name, never the recovered plaintext or
the mapping between them: writing "pseudonym X decodes to /Users/<name>/..."
into an item description publishes exactly the deanonymization that the item
exists to close. This is separate from the secret redaction described above,
which covers credentials in transport and logs, not prose an author types.

`.github/workflows/todo-db-export.yml` syncs the locked scripts project and runs
the package-only wrapper when the two database secrets are available:

- `TODO_DB_URL` repository secret for the dedicated BenchBox Turso/libSQL DB.
- `TODO_DB_RO_AUTH_TOKEN` repository secret carrying read-only authority.

### Local auth provisioning

CI supplies `TODO_DB_URL` and `TODO_DB_RO_AUTH_TOKEN` as secrets. Local commands
must select a database with `--db`, `TODO_DB_PATH`, `TODO_DB_URL`, or
`.todo-db/config.json`; the wrapper refuses to create an implicit fork database.
For a selected hosted database with no supplied token, the wrapper preserves
the maintainer convenience path: it asks the logged-in `turso` CLI for a
one-day token without printing or persisting it. It does not fall back to a
sibling checkout, embedded runtime, or local database. The sole database-free
exceptions are `doctor`, help/version output, and finding commands that operate
only on local drafts.

The verified wheel is committed under `_project/scripts/vendor/` and resolved
by `_project/scripts/uv.lock`. The wrapper enforces version 0.3.2. The workflow
does not download or select a runtime through repository variables.

The job remains weekly, deterministic, path-scoped, and outage-alerting. Each
successful run uploads a uniquely named recovery artifact with 90-day automatic
retention in addition to the versioned snapshot PR. GitHub owns expiry; the
workflow owner responds to the existing incident issue and performs a clean-DB
restore before any recovery is accepted. It refreshes compatibility views from
one lossless package envelope, restores that envelope into a clean SQLite
database, verifies the audit chain, and compares the complete restored
envelope, including `schema_migrations` and `audit_head`, before opening the
snapshot PR. Missing database secrets, an unavailable locked package, an
unreachable database, or a schema mismatch open or reuse the incident issue;
they do not claim production readiness.

The live BenchBox database uses the package schema. Export it through the stable
wrapper with explicit read-only credentials, then prove the lossless envelope
on a new local database:

```sh
set -eu
test -n "$TODO_DB_URL"
test -n "$TODO_DB_RO_AUTH_TOKEN"

SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/todo-db-live-restore.XXXXXX")"
IDENTITY="--project-id benchbox --repository https://github.com/joeharris76/BenchBox"

_project/scripts/todo export --out "$SCRATCH/views" \
  --lossless-out "$SCRATCH/lossless"

uv run --project _project/scripts --locked -- todo-db \
  --db "$SCRATCH/roundtrip.sqlite" $IDENTITY init
uv run --project _project/scripts --locked -- todo-db \
  --db "$SCRATCH/roundtrip.sqlite" $IDENTITY \
  restore --input "$SCRATCH/lossless/todo-db.json" --replace
uv run --project _project/scripts --locked -- todo-db \
  --db "$SCRATCH/roundtrip.sqlite" $IDENTITY audit verify
uv run --project _project/scripts --locked -- todo-db \
  --db "$SCRATCH/roundtrip.sqlite" $IDENTITY \
  export --output "$SCRATCH/roundtrip.json"

cmp "$SCRATCH/lossless/todo-db.json" "$SCRATCH/roundtrip.json"
```

## Testing, CI, release, and operations gate

The BenchBox-side tests cover adapter argument and identity forwarding,
database and version pinning, exit fidelity, deterministic lossless and
compatibility export views, explicit YAML paths, empty-source rejection,
export-fidelity reporting, freeze and renew extensions, and failed-import
rollback. The released package suite covers local lifecycle, identity,
migrations/checksums, audit/export/restore, concurrency/claim contention,
secure hosted transport, token redaction, and credential-gated live coverage.

The operational acceptance implementation covers all 11 required gates. Hosted
mutation remains credential-gated and must use only a dedicated test database;
without those credentials the live lane skips cleanly.

| # | Gate | Durable evidence |
|---:|---|---|
| 1 | Real package and CLI smoke | `uv build` creates wheel and sdist; isolated installs of both artifacts run `todo-db --help` and `todo --help`. |
| 2 | Concurrent claims | Two real processes contend on scratch SQLite; exactly one claimant wins and persisted ownership matches it. |
| 3 | Secure hosted transport | Hosted configuration refuses insecure remote transport. |
| 4 | Connection outage and secret redaction | Connection failures surface a bounded `TodoDBError` without URL or token material. |
| 5 | Replica-sync failure closes stale access | A failed hosted sync closes the replica instead of allowing stale reads. |
| 6 | Credential-gated hosted lifecycle | The dedicated hosted live lane exercises real writes and cross-replica contention only when its isolated test credentials are present, and skips otherwise. |
| 7 | Migration checksum rollback guard | A tampered recorded migration is rejected before use. |
| 8 | Prior-package/schema rollback guard | The current package refuses a database containing an unknown future migration. |
| 9 | Lossless clean restore | Restore, audit verification, and a second export require exact full-envelope equality, including migrations and audit head. |
| 10 | Package supply chain | BenchBox vendors the wheel downloaded from the immutable v0.3.2 release, pins it in `uv.lock`, and verifies its published SHA-256 digest in wrapper tests. |
| 11 | Versioned recovery and rotation | Weekly snapshot PRs are supplemented by run/attempt-versioned artifacts retained for 90 days; failures reuse the operational incident. |

Before any package release, require a changelog entry describing public CLI/API
changes, migration compatibility, export format version, restore procedure, and
rollback. Keep the prior-package/schema refusal and clean-restore recipe green
through the compatibility window.

Operational defaults remain one physical database per project,
separate read-write/read-only credentials, weekly exports, clean-DB restore
drills, and SHA-256 chained events with optional signed export manifests. This
work does not provision hosted infrastructure; the package-only cutover reuses
the existing hosted database and credentials.

## Oxbow, textcharts, and future consumers

Neither repository is modified by this work. Each maintainer must approve the
following sequence independently:

1. Record a stable project identity (`project_id` plus canonical repository
   identity) and choose a local `.todo-db/standalone.sqlite` path.
2. Bootstrap local SQLite with `todo-db init`; verify identity before use.
3. Optionally provision one Turso/libSQL physical database and separate RW/RO
   credentials; never reuse BenchBox's database or planning database.
4. Run a dry-run YAML import, then a fresh shadow import and full semantic/event
   comparison. Keep YAML authoritative during this period.
5. Operate a compatibility period with the existing YAML command available and
   deterministic read-only exports/restore drills.
6. Obtain maintainer approval for cutover, export the final YAML/DB evidence,
   switch the project-specific adapter route, and retain rollback to YAML and
   the previous package/schema.

Oxbow's existing `todo_cli.py` and `_project/TODO` workflow must be migrated as
one project. textcharts' `todo.config.yaml` workflow must remain active until
its own field/status/template mapping is proven. Future consumers receive the
same bootstrap, identity, shadow, compatibility, export/restore, cutover, and
rollback recipe. `skill-sync` distributes text only; it does not provision
databases, credentials, migrations, or project identity.

## Human acceptance decisions

The maintainer approved the recommended decisions on 2026-07-21:

1. Public package/repository name `todo-db`, import package `todo_db`, canonical
   command `todo-db`, and compatibility alias `todo`.
2. Reserve the PyPI name before setting the first release version.
3. One physical Turso/libSQL database per project with separate read-write and
   read-only credentials.
4. Versioned backups and a tested compatibility/rollback window.
5. Preserve the documented lint exit semantics at each consumer boundary.
6. SHA-256 chained audit events, with signed export manifests where key custody
   and verification ownership are configured.
7. Version the `todo-db` skill text with the package; `skill-sync` remains a
   text distributor rather than a database provisioner.
8. Retain the legacy fallback through the compatibility and warning window.

These decisions authorize the operational work but do not themselves publish
the package, reserve PyPI, provision or rotate credentials, or cut over a
consumer. Those actions remain gated by the operational and adoption TODOs.

## Hosted schema migration (v3 -> v4)

The CLI refuses any database whose `schema_version` is below its own
`SCHEMA_VERSION`, and migrations never auto-apply. Landing v4 code therefore
makes every collaborator's CLI inert against the live v3 database until the
hosted migration runs: **land the code and run `todo migrate` together.**

Rehearse first on a scratch database, never against production:

```bash
turso db create benchbox-todo-v4-rehearsal
```

Use a **dedicated** `TODO_DB_REPLICA` per database — reusing the default replica
across two databases silently mixes snapshots, producing stale reads and failed
writes. Seed at v3, run the new CLI's `migrate`, then verify tables and row
counts and exercise every findings write path before destroying the scratch
database.

What v4 changes:

| Change | Note |
| --- | --- |
| `findings.related_paths` | additive column, NULL pre-v4 |
| `findings.suggested_sweep` | additive column, NULL pre-v4 |
| `finding_sections` | new table, `ON DELETE CASCADE` |
| `finding_links` rebuilt | `target_item` now deferrable |

The `finding_links` rebuild is the only non-additive step. It exists because a
hosted `--replace` reload DELETEs every items-domain table and reinserts it in one
transaction while findings tables stay out of `TRANSFER_TABLES`: with an immediate
FK the DELETE aborts even though the same transaction restores the item, and with
`foreign_keys` OFF it leaves a stale link. Deferring the check to COMMIT fixes both
without `ON DELETE SET NULL`, which would destroy promote provenance on every
reload.

Importing legacy records requires a **restored snapshot**, not an empty scratch
database: `todo_id` targets resolve against `items`, so an empty database reports
every legacy link as dangling (36 false positives over the current corpus).
