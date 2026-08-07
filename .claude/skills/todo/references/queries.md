# TODO Queries and Updates

## Create and update

* Create: `todo create --title ... --worktree ... --priority ...`, or `--from -` with JSON. Items that involve code need scope rules, must-preserve notes, anti-patterns, and verification steps.
* Update: `todo update <id>` changes an item after you create it. You can change `--title`, `--description`, `--priority`, `--worktree`, `--add-work`, `--edit-work` (only for work units that are still pending; done units are immutable because they carry evidence), `--add-verify`, and `--drop-verify SEQ --reason ...`. Each update creates one audit event with before/after diffs. You must give `--reason` when you edit items that are done or dropped. The id, state, and identity never change through `update` — use lifecycle commands to change state. Prefer `update` over dropping and recreating. It keeps history and links.

## Inspect

* `todo list [filters]` — list items
* `todo show <id> [--json]` — show one item
* `todo stats` — counts by state, priority, worktree, and deferral
* `todo deps <id>` — show dependencies
* `todo export` — write a deterministic snapshot (JSONL plus a markdown index). This is the CLI command. It is different from the committed snapshot at `_project/todo-db-export/` (written by `write_export`). Prefer live commands (`list`, `show`, `stats`) for day-to-day work. Use the committed snapshot only for offline review.

## Rank and group

Ranking and grouping open work is a skill-only analysis. It has no CLI command. Follow `references/prioritize.md`. Do not invent a `prioritize` command.

## Block, release, and drop

* `todo block <id> --reason ...` — mark blocked
* `todo unblock <id>` — clear the blocked flag
* `todo release <id>` — release a claim
* `todo sweep-stale` — release expired claims
* `todo drop <id> --reason ...` — drop an item
