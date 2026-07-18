# BenchBox TODO Items

This directory contains TODO items organized in a distributed structure.

## Structure

```
TODO/
├── _indexes/                    # Auto-generated index files (gitignored, rebuilt on demand)
│   ├── master.yaml             # Complete listing with metadata
│   ├── by-category.yaml        # Grouped by category
│   ├── by-priority.yaml        # Grouped by priority
│   └── by-status.yaml          # Grouped by status
├── {worktree}/                 # Git branch/worktree
│   ├── planning/               # Not Started, Identified
│   │   └── {item-slug}.yaml
│   └── active/                 # In Progress, Blocked, Under Review
│       └── {item-slug}.yaml
└── README.md                   # This file
```

## Navigation

Use the index files in `_indexes/` for quick local lookups. Fresh clones and GitHub blob/raw views do not
contain these generated files until they are rebuilt locally:

- `master.yaml` - All items with full metadata
- `by-category.yaml` - Items grouped by category (Core Functionality, Platform Expansion, etc.)
- `by-priority.yaml` - Items grouped by priority (Critical, High, Medium, Low)
- `by-status.yaml` - Items grouped by status (Not Started, In Progress, etc.)

## CLI Tool

Use the TODO CLI for querying and management:

```bash
# List items
uv run _project/scripts/todo_cli.py list --priority=high
uv run _project/scripts/todo_cli.py list --status="in-progress"
uv run _project/scripts/todo_cli.py list --worktree=platform-expansion

# Show specific item
uv run _project/scripts/todo_cli.py show TODO/{worktree}/{phase}/{item}.yaml

# Validate items
uv run _project/scripts/todo_cli.py validate TODO/

# Regenerate indexes
make todo-reindex
```

## Adding New Items

1. Use the template: `_project/TODO_ENTRY_TEMPLATE.yaml`
2. Create file in appropriate location: `TODO/{worktree}/{phase}/{slug}.yaml`
3. Validate: `uv run _project/scripts/validate_todo.py <file>`
4. Regenerate indexes: `make todo-reindex` (or let `todo_cli.py` regen on next read — indexes are gitignored)

## Claude Skills

The `project-todo-sync` skill in `.claude/skills/` helps manage TODO items:

- Add new items with proper structure
- Update existing items
- Move items between phases
- Mark items complete
- Regenerate indexes

## Blind-spot remediation lifecycle

A blind-spot remediation TODO links one or more findings from
`_project/blind-spots/`. Each linked finding ends the remediation in exactly
one **terminal state**, and a remediation TODO's completion gate accepts any
of them:

- `merged-to-todo` — the finding described work that became one or more
  w-units of this (or another) TODO; the code/doc change lands there.
- `dismissed` — the finding was judged not-a-defect or not-worth-acting-on;
  the dismissal reason is recorded on the finding.
- `actioned` — the finding was resolved by a **convention or policy
  decision** rather than a code change: the reconciliation is a
  documentation edit, a one-line policy note, or an accepted status quo.
  Stamp it with
  `_project/scripts/sweep_blind_spots.py triage <id> --action actioned
  [--reason "…"]`, citing the resolving TODO id in the reason.

`actioned` is a first-class terminal state, not a loose end: the
`pr-review-sweep-template.md` "Closing the loop" step already closes
cross-linked blind-spots with `--action actioned` citing the sweep TODO.
A remediation TODO must therefore **not** fail its own completion gate when
a linked finding ends as `actioned` — treat `merged-to-todo`, `dismissed`,
and `actioned` as the three accepted terminal states. Reserve `actioned`
for convention-only remediations; when a code change is the fix, prefer
`merged-to-todo` so the change is traceable to a w-unit.

## Migration

This structure was created by migrating from monolithic `PROJECT_TODO.yaml` and `PROJECT_DONE.yaml` files on 2025-11-23.

Original files are preserved in `_project/_archive/`.
