# TODO tracker export snapshot

**Auto-generated — do not hand-edit.**

Deterministic weekly snapshot of the hosted TODO tracker database
(`_project/specs/todo-db-tracker.md`), written by
`.github/workflows/todo-db-export.yml` with a read-only token.

- `items.jsonl` — one JSON object per item, keys sorted, ordered by
  `id`, timestamps from row data (not wall-clock). Full-state
  vendor-lock escape hatch: the tracker reconstructs from it.
- `index.md` — rendered `id / state / priority / worktree / title`.

This directory's git history is the tracker's provenance trail — the
single sanctioned exception to the repo's DB-free-CI rule.
