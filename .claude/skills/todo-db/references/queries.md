# TODO Queries And Lifecycle

- Create: `todo create --title ... --worktree ... --priority ...`, or
  `--from -` with JSON. Code items need scope, must-preserve, anti-pattern,
  and verification guardrails.
- Inspect: `todo list [filters]`, `todo show <id> [--json]`, `todo stats`,
  `todo deps <id>`, and `todo export`.
- Block/release/drop: use `todo block <id> --reason ...`, `todo unblock <id>`,
  `todo release <id>`, `todo sweep-stale`, or `todo drop <id> --reason ...`.
