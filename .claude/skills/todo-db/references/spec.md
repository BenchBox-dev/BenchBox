# Write a specification

Structure a feature or refactoring plan so it can be ingested directly into the
tracker via `create_item`.

## Structure

A complete specification defines:

1. **Objective**: A clear statement of what the change accomplishes.
2. **Prior art**:
   Examine existing patterns in the codebase by file path. State whether this
   work extends an existing pattern, supersedes it, or introduces a new pattern.
3. **Item breakdown**:
   Define fields matching the `create_item` schema:
   - `id`: Kebab-case identifier (for example, `mcp-logging-refactor`).
   - `title`: Short imperative sentence.
   - `worktree`: Relative directory or component root.
   - `priority`: `critical`, `high`, `medium-high`, `medium`, or `low`.
   - `description`: Context, rationale, and non-obvious constraints (must be at
     least 10 characters).
   - `work`: Ordered list of units (`id` or `wid`, and `summary`). Each unit
     must be independently implementable and verifiable.
   - `scope`: Path rules (`only_modify` and optional `do_not_modify`). Keep
     scope tight to protect against accidental edits.
   - `preserves`: Critical invariants, interfaces, or behaviors that must not change.
   - `verifications`: Deterministic commands with `description` and `command`
     (and optional `expected`) that prove the change works.

## Example ingestion payload

Once the user approves the specification, call `create_item`:

```json
{
  "id": "audit-retention-policy",
  "title": "Enforce 90-day audit log retention",
  "worktree": "src/todo_db",
  "priority": "high",
  "description": "Prune audit rows older than 90 days during maintenance.",
  "work": [
    {"wid": "w1", "summary": "Add retention pruning query in audit.py"},
    {"wid": "w2", "summary": "Add CLI maintenance flag in cli.py"},
    {"wid": "w3", "summary": "Add unit tests in tests/test_audit.py"}
  ],
  "scope": {
    "only_modify": ["src/todo_db/audit.py", "src/todo_db/cli.py", "tests/test_audit.py"]
  },
  "preserves": [
    "Preserve hash-chain continuity for retained audit records."
  ],
  "verifications": [
    {"description": "Run audit test suite", "command": "uv run pytest tests/test_audit.py"},
    {"description": "Check audit lint", "command": "uv run ruff check src/todo_db/audit.py"}
  ]
}
```

If the new item depends on existing work, call `add_dependency(id=..., needs=...)`.
