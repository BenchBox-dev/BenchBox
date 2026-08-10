# todo-db shadow tooling: portable command and safety boundary

Date: 2026-08-10

Status: accepted for the shadow/rehearsal phase; this decision does not
authorize hosted mutation or the production cutover.

## Decision

`_project/scripts/todo_db_shadow.py` invokes the canonical tracker only through
the BenchBox scripts project:

```text
uv run --project _project/scripts --locked -- todo-db
```

The command is resolved from the BenchBox project environment and its lock
state. The shadow tool has no PATH fallback, sibling checkout fallback, local
absolute checkout path, or embedded lifecycle implementation. If the locked
project cannot resolve a compatible `todo-db` command, the shadow run fails
closed before it can report a successful migration.

The released holder-only package is `todo-db` 0.3.1, published from merged
commit `75cf990094dea33a151d99192ffc57df0dba7682` as GitHub release `v0.3.1`.
The release artifacts and their SHA-256 hashes are recorded in the tracker
release TODO and must be pinned by the subsequent BenchBox package-cutover
TODO before this command is used by CI or a clean clone.

## Sources of truth

- During shadow and rehearsal work, the existing BenchBox YAML tracker and its
  read-only hosted snapshot remain authoritative.
- The standalone database is a newly-created scratch target only. It is a
  comparison artifact, never the live BenchBox database and never a source of
  tracker truth during the compatibility window.
- The canonical `todo-db` package owns schema, lifecycle, identity, audit,
  export, and restore semantics. BenchBox owns only repository paths,
  invocation policy, and comparison/reporting orchestration.
- The required project identity is `project_id=benchbox` and repository
  `https://github.com/joeharris76/BenchBox`; both are passed explicitly to
  canonical commands.

## Safety gates

The shadow tool must fail closed when any of these conditions is true:

1. The YAML source contains no records.
2. The target database or adjacent export sidecar already exists.
3. The target resolves to BenchBox's protected `.todo-db/todo.sqlite`.
4. Legacy or canonical import produces zero items from a non-empty YAML source.
5. The canonical command is missing, incompatible, or exits non-zero.
6. Any item field, supported table count, metadata value, or normalized event
   provenance differs outside the explicitly documented dependency-event
   normalization.

The target and report are scratch artifacts outside the repository. On failure,
cleanup may remove only a target and sidecar created by that invocation; it may
not delete a pre-existing path or any protected database. Credentials remain
environment-only and are redacted from captured command output.

## Freeze and rollback boundary

A local YAML shadow does not authorize a hosted write freeze. The separate
hosted migration TODO must acquire and retain a leased maintenance freeze for
the entire snapshot-to-restore interval, verify event quiescence, and retain a
durable off-repository backup plus the lossless source snapshot until post-
restore audit verification and full parity pass.

If a rehearsal or migration gate fails, keep the legacy YAML/BenchBox command
active, discard only the isolated scratch artifacts, and do not enable the
standalone compatibility route. A production rollback restores the retained
off-repository backup while the freeze remains held; it never relies on a
developer checkout or an unverified item-count comparison.
