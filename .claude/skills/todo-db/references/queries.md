# TODO Queries And Lifecycle

- Create: `todo create --title ... --worktree ... --priority ...`, or
  `--from -` with JSON. Code items need scope, must-preserve, anti-pattern,
  and verification guardrails.
- Update (todo-db >= 0.3.0): `todo update <id>` corrects items after
  creation — `--title/--description/--priority/--worktree`, `--add-work`,
  `--edit-work` (pending units only; done units carry evidence and are
  immutable), `--add-verify`, `--drop-verify SEQ --reason ...`. Every update
  is one chained audit event with from/to diffs; edits to done/dropped items
  require `--reason`. Id, state, and identity are immutable — state moves
  only through lifecycle verbs. Prefer `update` over drop-and-recreate: it
  preserves history and links.
- Inspect: `todo list [filters]`, `todo show <id> [--json]`, `todo stats`,
  `todo deps <id>`, and `todo export`.
- Block/release/drop: use `todo block <id> --reason ...`, `todo unblock <id>`,
  `todo release <id>`, `todo sweep-stale`, or `todo drop <id> --reason ...`.
