# BenchBox todo-db extraction: staged integration and acceptance handoff

Status: historical 0.4.2 migration and compatibility evidence complete. This
handoff records the 0.4.2 rollout as evidence; the current locked runtime is the
vendored todo-db 0.6.0 wheel (`_project/scripts/vendor/`). Agents drive the
tracker through the `todo-db-mcp` server registered in `.mcp.json`; scripts and
humans use the floor CLI:

```sh
uv run --project _project/scripts --locked -- todo-db <verb>
```

where `<verb>` is one of the surviving CLI verbs (`init`, `init-project`,
`doctor`, `export`, `restore`, `restore-legacy`, `audit verify`, `import-yaml`,
`verify-run`, `rebaseline`, `complete`, `sweep-stale`, `migrate`, `config`,
`finding sync`). The 0.6.0 cutover is recorded in
`_project/decisions/todo-db-upgrade-0-6-0-mcp-2026-09-03.md`. Use
`_project/specs/todo-db-tracker.md` and `_project/scripts/pyproject.toml` for the
current runtime and credential contract.

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
- `todo-db` 0.4.2 is published as GitHub release tag `v0.4.2` from commit
  `7ae9fda4aab9aeb9d265b403c8bb9ecda844b3a5`; Pi adapter 0.1.1 is unchanged.
  BenchBox vendors the checksum-verified wheel under
  `_project/scripts/vendor/`; consumers resolve that artifact through the
  locked scripts environment, never a sibling checkout, private Git fetch, or
  registry install.
- During that historical read-only snapshot rehearsal, no hosted write credential
  was used and the hosted primary was not modified.

## Runtime boundary

Agents call the tracker through the `todo-db-mcp` stdio server (registered in
`.mcp.json`), which exposes the item and lease lifecycle verbs that 0.6.0 moved
off the top-level CLI (`create`, `show`, `ready`, `take`, `next`, `finish`,
`done`, `start`, `update`, `stats`, `release`, `defer`, `promote`, `dismiss`,
and the rest). Scripts and humans call the surviving CLI verbs directly through
the locked scripts environment:

```sh
uv run --project _project/scripts --locked -- todo-db <verb>
```

The runtime is the checksum-verified wheel vendored under
`_project/scripts/vendor/` and pinned by `_project/scripts/uv.lock`; it is never
resolved from a sibling checkout, private Git fetch, or registry install. The v2
external-credential contract is unchanged: set the non-secret
`TODO_DB_AUTH_CONTRACT=v2` marker for hosted calls, and inject credentials
externally with bounded lifetime. The runtime never calls Turso to mint, parse,
cache, log, print, refresh, or retry credentials, and it redacts credential
environment values in output. Export writes a single lossless JSON envelope; the
committed `items.jsonl` / `events.jsonl` / `index.md` views are rendered from it
by `_project/scripts/todo_db_export_views.py`.

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

`.github/workflows/todo-db-export.yml` syncs the locked scripts project and runs
the floor CLI (`uv run --project _project/scripts --locked -- todo-db export`)
when the two database secrets are available:

- `TODO_DB_URL` repository secret for the dedicated BenchBox Turso/libSQL DB.
- `TODO_DB_RO_AUTH_TOKEN` repository secret carrying read-only authority.

### Local auth provisioning

CI supplies `TODO_DB_URL` and `TODO_DB_RO_AUTH_TOKEN` as secrets. Local commands
must select a database with `--db`, `TODO_DB_PATH`, `TODO_DB_URL`, or
`.todo-db/config.json`; the CLI refuses to create an implicit fork database. For
a selected hosted database, inject credentials externally with bounded lifetime
via `TODO_DB_AUTH_TOKEN` or `TODO_DB_RO_AUTH_TOKEN` (or a
`TODO_DB_CREDENTIAL_COMMAND`), and set `TODO_DB_AUTH_CONTRACT=v2`. The v2
contract never mints or refreshes them. It does not fall back to a sibling
checkout, embedded runtime, or local database. The sole database-free
exceptions are `doctor`, help/version output, and finding commands that operate
only on local drafts.

The verified 0.6.0 wheel is committed under `_project/scripts/vendor/` and
resolved by `_project/scripts/uv.lock`. The workflow does not download or select
a runtime through repository variables.

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

The live BenchBox database uses the package schema. Export it through the floor
CLI with explicit read-only credentials, then prove the lossless envelope on a
new local database. This mirrors the restore-validation block in
`.github/workflows/todo-db-export.yml`:

```sh
set -eu
test -n "$TODO_DB_URL"
test -n "$TODO_DB_RO_AUTH_TOKEN"
export TODO_DB_AUTH_CONTRACT=v2

SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/todo-db-live-restore.XXXXXX")"
IDENTITY="--project-id benchbox --repository https://github.com/joeharris76/BenchBox"
RUN="uv run --project _project/scripts --locked -- todo-db"

$RUN $IDENTITY export --output "$SCRATCH/todo-db.json"

$RUN --db "$SCRATCH/roundtrip.sqlite" $IDENTITY init
$RUN --db "$SCRATCH/roundtrip.sqlite" $IDENTITY \
  restore --input "$SCRATCH/todo-db.json" --replace
$RUN --db "$SCRATCH/roundtrip.sqlite" $IDENTITY audit verify
$RUN --db "$SCRATCH/roundtrip.sqlite" $IDENTITY \
  export --output "$SCRATCH/roundtrip.json"

cmp "$SCRATCH/todo-db.json" "$SCRATCH/roundtrip.json"
```

## Testing, CI, release, and operations gate

The BenchBox-side tests from the adapter era covered adapter argument and
identity forwarding, database and version pinning, exit fidelity, deterministic
lossless and compatibility export views, explicit YAML paths, empty-source
rejection, export-fidelity reporting, freeze and renew extensions, and
failed-import rollback. The released package suite covers local lifecycle,
identity,
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
| 10 | Package supply chain | BenchBox vendors the wheel downloaded from immutable release `v0.4.2`, pins it in `uv.lock`, and verifies published SHA-256 `c9f1b97f04f1bc9bd92647abbeb1b2ef1ef8665d6b0db8dc1dfda9f1a06731b7` in wrapper tests. |
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

## 0.3.2-to-0.4.2 rollout / migration 007

Download only the official GitHub release assets and verify the published
checksums before vendoring:

```sh
gh release download v0.4.2 \
  --repo joeharris76/todo-db \
  --pattern 'todo_db-0.4.2-py3-none-any.whl' \
  --pattern 'todo_db-0.4.2.tar.gz' \
  --pattern 'todo-db-pi-adapter-0.1.1.tgz' \
  --pattern 'SHA256SUMS'
shasum -a 256 -c SHA256SUMS
uv run --isolated --with ./todo_db-0.4.2-py3-none-any.whl -- todo-db --version
```

Expected version: `todo-db 0.4.2`. The wheel digest is
`c9f1b97f04f1bc9bd92647abbeb1b2ef1ef8665d6b0db8dc1dfda9f1a06731b7`,
and Pi adapter remains 0.1.1.

BenchBox's rollout from 0.3.2 crosses additive migration 007, which adds
`verifications.workspace_fingerprint`. The verified pre-upgrade backup was
taken read-only and rehearsed locally before the staged 0.4.1 runtime migrated
the hosted tracker from schema 6 to schema 7. Version 0.4.2 itself introduces
no migration; it remains schema-7 compatible and adds hosted auth contract
unification, safe v2 exit negotiation, and expanded endpoint redaction. The
external-credential contract from that rollout survives the 0.6.0 cutover
unchanged: credentials stay external, `TODO_DB_AUTH_CONTRACT=v2` is set by the
caller, and the runtime never mints, parses, caches, logs, prints, refreshes, or
retries them. Hosted calls without the v2 marker return legacy exit code 2.

Rollback remains the retained pre-upgrade lossless envelope plus its verified
scratch restore rehearsal. Replay that artifact only through an explicitly
approved recovery procedure. Hosted agent mutations remain experimental because
commit-outcome fault injection is not yet certified.

Claim-coordinated clients must preserve the current claim token/generation on
progress, finish, and release paths after migration 006/007; do not expose
verification execution, environment passthrough, takeover, rebaseline, restore,
migration, or destructive administration through model-facing tools.

## Historical hosted schema migration (v3 -> v4)

The CLI refuses any database whose `schema_version` is below its own
`SCHEMA_VERSION`, and migrations never auto-apply. Landing v4 code therefore
makes every collaborator's CLI inert against the live v3 database until the
hosted migration runs: **land the code and run `todo-db migrate` together.**

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
