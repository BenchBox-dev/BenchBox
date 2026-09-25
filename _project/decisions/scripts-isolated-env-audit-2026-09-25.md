# Top-level scripts/ isolated-env audit

Date: 2026-09-25
Status: Audited. Migration not pursued; reasoning below.

## Audit results (62 top-level scripts, 28 nested)

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
- **47 scripts are decoupled** from benchbox. Of those, seven need
  third-party packages: `aws_cost_limits` (top-level `boto3`/`botocore`),
  `duckdb_datasketches_smoke` (top-level `duckdb`),
  `generate_pricing_data` (top-level `yaml`),
  `check_dependency_bounds` (top-level `packaging`),
  `capture_chart_images` (function-local `ansi2html` plus `PIL`: presence
  check at lines 127-132, use at lines 172 and 213),
  `capture_release_heroes` (function-local `ansi2html` at line 70 and
  `PIL` at line 119), and `probe_mooncake_types` (function-local
  `psycopg` at line 444; the top-level docstring only documents the
  requirement). `yaml` and `packaging` are root dependencies; `duckdb`,
  `boto3`, `psycopg`, `ansi2html`, and `pillow` are covered by the dev
  group or platform extras with purpose comments (the `ansi2html`/`pillow`
  comments name `capture_chart_images.py`). `_render_blog_charts.py` has
  no third-party import of its own (docstring mention only) and reaches
  `ansi2html`/`PIL` transitively through `capture_chart_images` helpers;
  nothing imports it.
- **Wheel coupling resolved**: `pyproject.toml` ships `include =
  ["benchbox*"]` only. `scripts/` never ships, so no script dependency can
  leak into the public install. The deferral's stated risk does not exist.

### Nested scripts (28 files)

The census above covers the 62 immediate `scripts/*.py` files. A further
28 nested files fall under the same migration question: 27 under
`scripts/publication/` plus `scripts/uat-bring-up/uat_bring_up.py`. None
imports `benchbox` at top level (grep for `^import benchbox` and
`^from benchbox` across both directories returns nothing); coupling is
stdlib plus intra-package `scripts.publication.*` references, with two
exceptions. `scripts/publication/validator_parity.py` first tries
`from benchbox.validation.bundle import ...` (line 50) and falls back to
loading `benchbox/validation/bundle.py` from its file path via `importlib`,
so it still executes benchbox code. And
`scripts/publication/check_control_plane.py` uses a function-local
`import jwt` (line 131) on its live-check path. (Three publication
checkers also import `yaml` at top level, three use function-local
`duckdb`, and `uat_bring_up.py` reaches into `tests.uat`; all are
already-covered patterns.) Isolating the nested tree would drag the same
coupling along -- the `validator_parity` fallback still needs the checkout
on disk -- so the nested census strengthens the no-migration case.

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
