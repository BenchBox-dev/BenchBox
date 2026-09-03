# todo-db 0.4.3-to-0.6.0 packaging bump for the MCP interface (2026-09-03)

## Scope

Move BenchBox's vendored `todo-db` runtime from the checksum-verified 0.4.3
wheel to the 0.6.0 wheel to adopt the packaged MCP server. This is a
packaging-only bump: no hosted-database migration, no backup or rehearsal.

## Release provenance

- Canonical release: `v0.6.0` in `joeharris76/todo-db`.
- Wheel: `todo_db-0.6.0-py3-none-any.whl`.
- Wheel SHA-256:
  `664d19825bc9ebd614bbc8580ae7d128c6340210ed28b714221e510367b2fd46`.
- The downloaded wheel digest matched the release `SHA256SUMS` entry
  (`shasum -a 256 -c SHA256SUMS` reported the wheel and sdist `OK`).
- The wheel embeds `SCHEMA_VERSION = 7` in `todo_db/database.py`.

## Schema compatibility

Both 0.4.3 and 0.6.0 ship schema version 7 with migrations 1..7 unchanged.
The hosted tracker is already at schema 7, so there is no migration to apply,
no schema-sensitive read path, and no backup, export rehearsal, or audit-chain
re-verification required. `_project/todo-schema-migrations.json` is unchanged.

## What changed

- `todo_db/mcp/` is now present in the runtime (stdio MCP server, exposed as
  the `todo-db-mcp` console script).
- `_project/scripts/pyproject.toml` requests `todo-db[hosted,mcp]`; the `mcp`
  extra pulls `mcp>=1.10.0,<2`. `uv.lock` regenerated against the new wheel
  filename and digest.

## What did not change

- `TODO_SCHEMA_VERSION=7` in the `_project/scripts/todo` shim.
- Hosted authentication contract v2: credentials stay external; the adapter
  never mints, parses, logs, stores, refreshes, or retries them.
- Project identity and the hosted database (schema 7).
- `_project/todo-schema-migrations.json`.

## Rollback

Revert the vendored wheel, `_project/scripts/pyproject.toml`, and `uv.lock` to
the 0.4.3 pin and re-lock. No data implications: the hosted schema is untouched
by this change, so a downgrade to 0.4.3 is safe.
