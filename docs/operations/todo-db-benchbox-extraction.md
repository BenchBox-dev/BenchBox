# BenchBox todo-db extraction: staged integration and acceptance handoff

Status: staged BenchBox integration only. This is not a production cutover.
The standalone repository is still unpublished and has no approved owner,
release, hosted account, or production database target. The legacy BenchBox
tracker remains the default and the existing `_project/scripts/todo` wrapper is
unchanged.

## Live evidence at this handoff

- BenchBox pool branch: `feat/todo-db-benchbox-extraction`, based on
  `origin/develop` `9f69c53c69009ff09874b64e011d876e10fa0960`.
- The primary clone remains on `develop`, two commits behind `origin/develop`,
  with one unrelated untracked blind-spot file. It was not edited.
- BenchBox has no tracked YAML item records under `_project/TODO` or
  `_project/DONE`; only ignored index snapshots and empty directory structure
  are present. The current BenchBox database has one active item and 36 audit
  events. An empty import would therefore be data loss, not a successful
  migration.
- `/Users/joe/Developer/todo-db` remains physically separate, uncommitted, and
  unpublished. Its current validation is 28 tests passed, Ruff check passed,
  format check passed, and wheel/sdist build passed.
- No hosted credentials, dedicated hosted test database, package release, or
  production infrastructure was used.

## Compatibility boundary

`_project/scripts/todo` remains the stable entry point. The new adapter is
selected only with `BENCHBOX_TODO_DB_STANDALONE=1`, so a normal checkout cannot
silently switch databases:

```sh
BENCHBOX_TODO_DB_STANDALONE=1 \
  uv run --project _project/scripts -- \
  python _project/scripts/todo_db.py --db PATH_OR_URL <command>
```

The adapter passes an argv list to the canonical `todo-db` executable, adds the
BenchBox project identity, preserves actor/worktree context, and maps policy
failure statuses back to the legacy contract. It has no shell interpolation and
redacts both `TODO_DB_AUTH_TOKEN` and `TODO_DB_RO_AUTH_TOKEN` in delegated
output. Export keeps the old `items.jsonl` and `index.md` views while adding a
lossless `todo-db.json` envelope containing metadata/config, all tracker tables,
schema migrations, and hash-chained events.

| Command family | Generic operation | BenchBox adapter responsibility |
|---|---|---|
| `init`, `migrate`, `config` | schema, migration, and database settings | add BenchBox identity; retain explicit opt-in routing |
| `create`, `show`, `claim`, `release`, `deps`, `unblock` | item and lease lifecycle | preserve actor and work-order invocation |
| `start`, `done` | work-unit lifecycle | delegate worktree/branch capture from the BenchBox cwd |
| `defer`, `promote`, `dismiss` | deferral lifecycle | preserve legacy arguments and output |
| `complete`, `drop`, `block` | terminal/block transitions | preserve policy errors and exit behavior |
| `list`, `ready`, `stats` | read-only views | preserve command names and legacy output mode |
| `check-scope`, `verify`, `lint` | policy gates | map standalone failure `2` to legacy failure `1` |
| `export` | lossless envelope | render legacy JSONL/Markdown compatibility views |

The standalone YAML bridge currently omits BenchBox `anti_patterns`, `prior_art`,
and terminal-item deferrals. This is a concrete cross-repository dependency:
the standalone repository must either expose a lossless import API or the
BenchBox adapter must explicitly stage those policy rows. This handoff does not
silently patch the standalone repository.

## Shadow migration and comparison

The repeatable path is `_project/scripts/todo_db_shadow.py`. It requires a new
explicit target and refuses protected databases, existing targets, and an empty
YAML source. It creates a temporary legacy import for comparison, imports into a
separate standalone target, exports the lossless envelope, and writes one
canonical JSON report:

```sh
SHADOW_DB="${TMPDIR:-/tmp}/benchbox-todo-shadow.sqlite"
REPORT="${TMPDIR:-/tmp}/benchbox-todo-shadow.json"
rm -f "$SHADOW_DB" "$REPORT"  # only these explicitly named temp files

uv run -- python _project/scripts/todo_db_shadow.py \
  --todo-dir _project/TODO \
  --done-dir _project/DONE \
  --db "$SHADOW_DB" \
  --report "$REPORT" \
  --standalone-project /Users/joe/Developer/todo-db
```

The report compares item counts and IDs, titles, states, priorities, worktrees,
descriptions, categories, approaches, work units, prerequisites, dependencies,
scope rules, verification rows, preserves, anti-patterns, prior art, deferrals,
metadata, and normalized audit event provenance. Ordering is canonical. On any
failed import after the dedicated target is created, the tool removes only that
new target and its adjacent export file; it never deletes a protected or
pre-existing database. The current repository intentionally fails at the
empty-source guard until the YAML source-of-truth is restored or a maintainer
provides an approved source snapshot.

Rollback is therefore: keep the existing BenchBox DB/YAML workflow active,
discard the isolated target/report, and unset `BENCHBOX_TODO_DB_STANDALONE`.
There is no production cutover or destructive replacement step in this branch.

## Export workflow and restore validation

`.github/workflows/todo-db-export.yml` now fails closed unless all of these are
available:

- `TODO_DB_URL` repository secret for the dedicated BenchBox Turso/libSQL DB.
- `TODO_DB_RO_AUTH_TOKEN` repository secret, used only as
  `TODO_DB_RO_AUTH_TOKEN` by export; it is never assigned to the read-write
  variable.
- `TODO_DB_PACKAGE_VERSION` repository variable naming an exact published
  `todo-db[hosted]` release.

The job remains weekly, deterministic, path-scoped, and outage-alerting. It
uses the adapter to write the lossless envelope plus compatibility views, then
restores the envelope into a clean SQLite database, verifies the audit chain,
and compares restored tracker data, metadata, and events before opening the
snapshot PR. Missing secrets, an unpublished package, an unreachable database,
or a schema mismatch open/reuse the incident issue; they do not claim
production readiness.

Restore recipe for a maintainer-approved package release:

```sh
uv run --with "todo-db[hosted]==${TODO_DB_PACKAGE_VERSION}" -- \
  todo-db --db ./restore.sqlite --project-id benchbox \
  --repository https://github.com/joeharris76/BenchBox init
uv run --with "todo-db[hosted]==${TODO_DB_PACKAGE_VERSION}" -- \
  todo-db --db ./restore.sqlite --project-id benchbox \
  --repository https://github.com/joeharris76/BenchBox \
  restore --input _project/todo-db-export/todo-db.json --replace
uv run --with "todo-db[hosted]==${TODO_DB_PACKAGE_VERSION}" -- \
  todo-db --db ./restore.sqlite --project-id benchbox \
  --repository https://github.com/joeharris76/BenchBox audit verify
```

## Testing, CI, release, and operations gate

The BenchBox-side tests cover adapter argument/identity forwarding, legacy
status mapping, deterministic lossless/legacy export views, explicit YAML path
defaults, empty-source rejection, semantic loss reporting, and failed-import
rollback. Existing BenchBox tracker tests remain the regression suite for the
default path. The standalone baseline covers local lifecycle, identity,
migrations/checksums, audit/export/restore, concurrency/claim contention,
secure hosted transport, token redaction, and credential-gated live coverage.

Before package release and cutover, maintainers must add or run these gates:

1. Build wheel and sdist, install each into a clean environment, and run the
   CLI contract matrix against both `todo-db` and `todo`.
2. Test migration checksum drift, missing/reordered migrations, transactional
   rollback, and restore into an empty database.
3. Exercise two concurrent claimers and a failed import against isolated local
   databases; run hosted live tests only with a dedicated test URL and tokens.
4. Test TLS/secure-transport refusal, read-only credential write refusal, DSN
   and token redaction, and no credential leakage in workflow/CLI failures.
5. Define backup frequency, location, retention, rotation ownership, and the
   package/schema compatibility window. Keep one prior package/schema rollback
   recipe tested before every cutover.
6. Require a changelog entry describing public CLI/API changes, migration
   compatibility, export format version, restore procedure, and rollback.

Recommended operational defaults remain one physical database per project,
separate read-write/read-only credentials, weekly exports, clean-DB restore
drills, and SHA-256 chained events with optional signed export manifests. These
are recommendations, not provisioned infrastructure.

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

The following decisions remain explicitly unresolved and block production
cutover or parent TODO completion:

1. Repository/PyPI ownership and release authority.
2. Final repository, distribution, import, and CLI names (`todo-db`/`todo_db`,
   canonical `todo-db`, alias `todo` are only recommended defaults).
3. Turso/libSQL provider account, region, database target, and provisioning
   owner for BenchBox.
4. Backup location, retention, frequency, rotation owner, and compatibility
   window.
5. Whether lint findings are warnings or a required gate in each consumer.
6. Audit integrity mechanism: chained SHA-256 only or signed export manifests,
   including key custody and verification owner.
7. Canonical ownership and versioning of the `todo-db` skill text; skill-sync
   should remain text-only.

Acceptance cannot be recorded as complete until the missing YAML/source
question and standalone importer dependency above are resolved, a real
shadow comparison passes, the package/release and hosted gates are approved,
and maintainers approve the consumer cutovers. No commit, push, PR, package
publication, credential rotation, or hosted provisioning was performed here.
