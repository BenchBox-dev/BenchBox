# Top-level scripts/ isolated-env audit

Date: 2026-09-25
Status: Audited. Migration not pursued; reasoning below.

## Audit results (62 scripts)

- **15 scripts import benchbox** and cannot run without the wheel built or
  installed: `benchmark_mooncake_migration`, `check_public_contract_drift`,
  `compare_pg_duckdb`, `compat_lint`, `generate_compat_docs`,
  `generate_corpus_inventory`, `generate_landing_quickstarts`,
  `generate_query_docs`, `post_merge_signature` (docstring ref only),
  `pr_refresh_replay`, `run_duckdb_version_matrix`, `update_version`,
  `validate_submission`, `verify_mcp_conformance`, plus
  `check_example_syntax` (string match, not an import). These are code
  generators, lints, and validators *over the package*: the coupling is
  inherent to their purpose, not accidental leakage.
- **47 scripts are decoupled** from benchbox. Of those, only 5 need
  third-party packages at all (`yaml`, `boto3`, `duckdb`, `packaging`),
  and every one is already a root dependency.
- **Wheel coupling resolved**: `pyproject.toml` ships `include =
  ["benchbox*"]` only. `scripts/` never ships, so no script dependency can
  leak into the public install. The deferral's stated risk does not exist.

## Why not migrate

The `_project/scripts` precedent works because that tooling is fully
decoupled (own pyproject, `uv run --project`, no package imports). Applying
it to `scripts/` would either (a) carry benchbox as a path dependency,
pulling the entire root tree into the "isolated" env and isolating nothing,
or (b) split scripts across two invocation conventions (`uv run` vs `uv run
--project scripts`) at 60+ Makefile/workflow call sites for zero
shipped-artifact benefit. Both are worse than the status quo.

## Recommendation

Keep `scripts/` in the root env. If a future script gains a heavy,
script-only dependency (the `ansi2html`/`pillow` comments in pyproject.toml
show the pattern), declare it at root with a purpose comment as today.
Revisit only if `scripts/` starts shipping in the wheel or a script-only
dependency conflicts with the package floor.
