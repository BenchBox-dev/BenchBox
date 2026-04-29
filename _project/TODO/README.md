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

Use the index files in `_indexes/` for quick lookups:

- `master.yaml` - All items with full metadata
- `by-category.yaml` - Items grouped by category (Core Functionality, Platform Expansion, etc.)
- `by-priority.yaml` - Items grouped by priority (Critical, High, Medium, Low)
- `by-status.yaml` - Items grouped by status (Not Started, In Progress, etc.)

## CLI Tool

Use the TODO CLI for querying and management:

```bash
# List items
uv run scripts/todo_cli.py list --priority=high
uv run scripts/todo_cli.py list --status="in-progress"
uv run scripts/todo_cli.py list --worktree=platform-expansion

# Show specific item
uv run scripts/todo_cli.py show TODO/{worktree}/{phase}/{item}.yaml

# Validate items
uv run scripts/todo_cli.py validate TODO/

# Regenerate indexes
uv run scripts/todo_cli.py reindex
```

## Adding New Items

1. Use the template: `_project/TODO_ENTRY_TEMPLATE.yaml`
2. Create file in appropriate location: `TODO/{worktree}/{phase}/{slug}.yaml`
3. Validate: `uv run scripts/validate_todo.py <file>`
4. Regenerate indexes: `make todo-reindex` (or let `todo_cli.py` regen on next read — indexes are gitignored)

## Claude Skills

The `project-todo-sync` skill in `.claude/skills/` helps manage TODO items:

- Add new items with proper structure
- Update existing items
- Move items between phases
- Mark items complete
- Regenerate indexes

## Migration

This structure was created by migrating from monolithic `PROJECT_TODO.yaml` and `PROJECT_DONE.yaml` files on 2025-11-23.

Original files are preserved in `_project/_archive/`.
