# todo-db 0.4.3-to-0.6.0 packaging bump for the MCP interface (2026-09-03)

## Scope

Move BenchBox's vendored `todo-db` runtime from the checksum-verified 0.4.3
wheel to the 0.6.0 wheel to adopt the packaged MCP server. No hosted-database
migration, backup, or rehearsal: the hosted schema is untouched. The runtime is
schema-compatible with 0.4.3 but not behaviour-compatible — 0.6.0 removes most
of the top-level CLI verb surface (see "What changed").

## Release provenance

- Canonical release: `v0.6.0` at todo-db commit
  `185c028962a49870877f9fab45ce4f014e9fb35b`.
- Wheel: `todo_db-0.6.0-py3-none-any.whl`.
- Wheel SHA-256:
  `664d19825bc9ebd614bbc8580ae7d128c6340210ed28b714221e510367b2fd46`.
- The downloaded wheel digest matched the release `SHA256SUMS` entry for the
  wheel and the sdist.
- The wheel embeds `SCHEMA_VERSION = 7` in `todo_db/database.py`.

## Schema compatibility

Both 0.4.3 and 0.6.0 ship schema version 7. The seven migration SQL files
(`todo_db/migrations/001_initial.sql` .. `007_verification_attestation.sql`)
are byte-identical between the two wheels (`diff -r` over the extracted
`todo_db/migrations/` trees reports no differences). The hosted tracker is
already at schema 7, so there is no migration to apply, no schema-sensitive
read path, and no backup, export rehearsal, or audit-chain re-verification
required. `_project/todo-schema-migrations.json` is unchanged.

## What changed

- 0.6.0 removes most of the top-level `todo-db` CLI verb surface. The agent
  verbs — `create`, `list`, `show`, `ready`, `take`, `next`, `finish`,
  `done`, `start`, `update`, `stats`, `release`, `agent`, `context`,
  `progress`, `defer`, `promote`, `dismiss`, `check-scope`, and the rest —
  move into the `todo-db-mcp` server. The surviving CLI verbs are `init`,
  `init-project`, `doctor`, `export`, `restore`, `restore-legacy`, `audit`,
  `import-yaml`, `verify-run`, `rebaseline`, `complete`, `sweep-stale`,
  `migrate`, `config`, and `finding`. This is why the `_project/scripts/todo`
  shim, which fronts the removed verbs, must be retired.
- `todo_db/mcp/` is now present in the runtime (stdio MCP server, exposed as
  the `todo-db-mcp` console script).
- `_project/scripts/pyproject.toml` requests `todo-db[hosted,mcp]` (was
  `todo-db[hosted]`); the `mcp` extra pulls `mcp>=1.10.0,<2`, resolved to
  `mcp 1.29.1`. `uv.lock` regenerated against the new wheel filename and
  digest.

## Dependency-footprint cost

The `mcp` extra adds roughly 31 packages to the locked `_project/scripts`
environment: the locked set goes from 8 to 39 distinct packages (`uv.lock`
holds 40 `[[package]]` entries; `rpds-py` is locked for two platforms). The
new transitives are `mcp` itself plus pydantic / pydantic-core /
pydantic-settings, starlette / sse-starlette / uvicorn, anyio, httpx /
httpcore / httpx-sse / h11, cryptography / cffi / pycparser, jsonschema /
jsonschema-specifications / referencing / rpds-py / attrs, click, pyjwt,
python-dotenv, python-multipart, and supporting packages. These land only in
the internal `_project/scripts` environment and are not shipped in the
BenchBox wheel.

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

## Follow-up: 0.6.0 to 0.6.1 (2026-09-03)

The `todo` skill v1.0.0 expects the MCP additions from todo-db PR #21
(`doctor` tool, agent-profile deferral tools), which the 0.6.0 wheel predates.
So the runtime moves to the 0.6.1 wheel: `todo_db-0.6.1-py3-none-any.whl`,
SHA-256 `e692629fe34ba1fc76e99880b3de65020bbe11786955d4ad284691095f0e8030`
(matched against the release `SHA256SUMS`; canonical release `v0.6.1` at
todo-db merge `671c45b`).

- Still `SCHEMA_VERSION = 7`; the seven migration SQL files are byte-identical
  to the 0.6.0 wheel, so again no hosted migration, backup, or rehearsal.
- `uv.lock` re-resolved with the same 40 packages; only the wheel filename and
  digest change.
- Paired with the skill-sync re-pin to `d22ea7f` (skill-sync-skills PR #71:
  `prioritize.md` MCP rewrite plus lock regen), so the vendored runtime and
  the mirrored skill agree on the MCP interface.

## Follow-up: current main rebuild (2026-09-04)

The GitHub `v0.6.1` wheel still registers `create_item` only behind
`--profile full`. todo-db `main` at
`b8dda65c53f4a8fa443ec09a7419576ea8362e90` (PR #25) loads planning tools on
every profile, and ships the repo-owned `todo-db` skill. There is no newer
tagged release, so the vendored wheel is rebuilt from that commit.

- Wheel filename stays `todo_db-0.6.1-py3-none-any.whl` because
  `pyproject.toml` version is still 0.6.1.
- Wheel SHA-256:
  `264a32b0af71bb8eb27fc6dfe04d01a30516ac7ba6352170a94bcab6354d3894`.
- Still `SCHEMA_VERSION = 7`; the seven migration SQL files are byte-identical
  to the previous 0.6.1 wheel, so no hosted migration, backup, or rehearsal.
- Floor CLI verbs used by CI (`export`, `restore`, `audit verify`) remain.
- Skill-sync now sources `todo-db` from `https://github.com/joeharris76/todo-db.git`
  at the same commit, replacing the catalog `todo` skill. The duplicate
  `todo-context-efficiency` source is gone.
