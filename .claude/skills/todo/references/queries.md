# TODO Queries and Updates

## Create and update

- Create with `todo create --title ... --worktree ... --priority ...` or JSON
  through `--from -`. Code items need scope rules, must-preserve notes,
  anti-patterns, and verification steps.
- Update with `todo update <id>`. It accepts `--title`, `--description`,
  `--priority`, `--worktree`, `--add-work`, `--edit-work`, `--add-verify`, and
  `--drop-verify SEQ --reason ...`.
- Edit work units only while pending. Done units are immutable because they
  carry evidence.
- Each update records one audit event with before-and-after differences. Give
  `--reason` when editing done or dropped items.
- `update` cannot change an item's id, state, or identity. Use lifecycle
  commands for state and prefer updates over dropping and recreating items.

## Inspect

* `todo list [filters]` — list items
* `todo show <id> [--json]` — show one item
* `todo stats` — counts by state, priority, worktree, and deferral
* `todo deps <id>` — show dependencies
- `todo export` — write a deterministic JSONL snapshot and Markdown index. This
  CLI output differs from `_project/todo-db-export/`, which `write_export`
  commits. Prefer live `list`, `show`, and `stats`; use the committed snapshot
  only for offline review.

## Rank and group

Follow `references/prioritize.md`; there is no `prioritize` CLI command.

## Block, release, and drop

* `todo block <id> --reason ...` — mark blocked
* `todo unblock <id>` — clear the blocked flag
- `todo release <id>` — release your claim. It does nothing when unclaimed and
  exits 2 for another actor's claim. `todo show --json` can race. For another
  actor's expired claim, use `todo claim` to take it over or `todo sweep-stale`.
* `todo sweep-stale` — release expired claims
* `todo drop <id> --reason ...` — drop an item
