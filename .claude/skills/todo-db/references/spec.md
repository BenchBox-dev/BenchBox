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
   - `title`: Short imperative sentence, 1–200 characters.
   - `priority`: `critical`, `high`, `medium-high`, `medium`, or `low`.
   - `description`: Context, rationale, and non-obvious constraints.
   - `needs`: IDs of prerequisite tasks, if any.
   - `acceptance`: Observable outcomes that prove the change works.
   - `links`: Related URLs or file paths.
   - `context`: Retained background the implementer will need.

Split work so each item is independently implementable and closable; use
`needs` for ordering, not a work breakdown inside one item.
