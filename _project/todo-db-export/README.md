# TODO tracker export snapshot

**Auto-generated — do not hand-edit.**

Deterministic weekly snapshot of the hosted TODO tracker database
(`_project/specs/todo-db-tracker.md`), written by
`.github/workflows/todo-db-export.yml` with a read-only token.

The committed snapshot is the **items domain only** — exactly the tables in
`todo_db.py`'s `EXPORT_TABLE_ALLOWLIST`. Findings-domain tables are excluded
by construction: their review prose is deliberately not version-controlled and
travels via the workflow's 90-day CI artifact channel only, never this
directory (see `_project/specs/findings-domain.md`, "Export boundary").

- `items.jsonl` — one JSON object per item, keys sorted, ordered by `id`,
  timestamps from row data (not wall-clock). Items-domain vendor-lock escape
  hatch: the tracker reconstructs from it.
- `events.jsonl` — the append-only provenance trail, one event per line,
  ordered by `seq`. A plain audit log (not hash-chained).
- `index.md` — rendered `id / state / priority / worktree / title`.

When the optional standalone package export is enabled it additionally writes
a lossless `todo-db.json` envelope (project identity, metadata, migrations,
and a hash-chained audit trail) that restore validation replays into a clean
database before the snapshot PR is opened.

This directory's git history is the tracker's provenance trail — the single
sanctioned exception to the repo's DB-free-CI rule.
