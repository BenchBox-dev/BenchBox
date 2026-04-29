# BenchBox - Agent And Contributor Guide

Consistent tooling, safe defaults, minimal surprises.

## Workflow
- Research before coding: read files, run tests, understand first
- Run test suite after multi-file edits; review every find-replace in context
- Stop on user interrupt/redirect

## Tooling
Use `rg`; read files in ≤250-line chunks. Always `uv run --` for Python tools. `make` wrappers OK. Run `benchbox --help` after dev install.
Common: `uv run -- python -m pytest {test}`, `pytest -m fast -q`, `ruff format .`, `ruff check .`, `ruff check --fix .`, `ty check` (all via `uv run`).

## Code Style
Python 3.10+, 4 spaces, 120 cols. Ruff only. Type hints on public APIs.

## Package Management
`uv` exclusively - no pip/pip-tools/poetry/conda, no `requirements.txt`, no manual pyproject.toml edits, no manual venvs.
Commands: `uv add pkg`, `uv add --dev pkg`, `uv add benchbox --extra cloud --extra clickhouse`, `uv sync --group dev`, `uv lock`, `uv tool install tool_name`, `uv tree`, `uv pip list`, `uv export`.
Avoid: bare `python`/`pytest`/`ruff`; `git add -A`; `-o "addopts="` with pytest; running TPC-DS SF<1 with stock dsdgen (it crashes; BenchBox bundles patched binaries - see `patch-and-redistribute-tpcds-dsdgen-subscale-support`).

## Tests
Markers: fast, unit, integration, tpch, tpcds, platform_smoke, docker_integration, live_integration. Coverage ≥80%.
- Smoke: `uv run -- python -m pytest -m fast -q`
- Standards: `uv run -- python -m pytest -m "tpch or tpcds" --tb=short`
- Docker: `make test-docker-<platform>` (clickhouse, trino, presto, postgresql, starrocks, doris, databend, influxdb)
- Cloud: `make test-live-<platform>` (databricks, snowflake, bigquery, redshift, athena) - approval required
- Coverage: `make coverage-fast` (fast only) or `make coverage-all` (full suite). Avoid `live_*` without approval.

## Sandbox & Security
FS: workspace-write. Network: restricted. Pre-approved: `rg`, `uv run -- python -m pytest`.
Needs approval: network, installs, writes outside workspace, live cloud tests.
No credentials in repo; use env vars or `.env` (gitignored); redact secrets in logs.

## CLI Modes & Phases
- Non-interactive: `--non-interactive` (or `BENCHBOX_NON_INTERACTIVE=true`) with `--platform --benchmark --scale --phases`
- Dry-run: `benchbox run --dry-run <DIR> --platform <plat> --benchmark <bm> --scale <sf> [--phases ...]`
- Phases: generate (data), load (tables), power|throughput|maintenance (queries). Default: generate+load+execute. Always propagate `--phases`.
- `--seed <int>` for deterministic runs. Scale ≥1 must be whole integers; default smoke: 0.01.

## DataFrame Support
20/22 benchmarks support DataFrame execution: `benchbox run --platform polars-df --benchmark <id>`.

**Platforms**: polars-df (expression, production), pandas-df (pandas, production), pyspark-df (expression, needs Spark), datafusion-df (expression, production), modin-df (pandas, needs Ray/Dask), cudf-df (pandas, needs CUDA), dask-df (pandas, production), databricks-df (expression, cloud), lakesail-df (expression, cloud).

**Benchmarks**: tpch (22), tpcds (99), ssb (13), clickbench (43), nyctaxi (25), flightdata (20), tsbs_devops (18), h2odb (10), amplab (8), coffeeshop (11), joinorder (113), tpch_skew (22), tpchavoc (220), datavault (22), tpcdi (38), tpcds_obt (17), write_primitives (12), read_primitives (136), metadata_primitives (62), transaction_primitives (12). Not supported: ai_primitives, vector_search.

**Options**: polars-df: streaming, rechunk, n_rows. pandas-df: dtype_backend (numpy|numpy_nullable|pyarrow). datafusion-df: none.
**Install**: Polars is core; Pandas: `--extra pandas`; all: `--extra dataframe-all`.
**Architecture**: `dataframe_queries/` beside SQL `queries.py`; expression-family uses lazy ctx, pandas-family uses eager; validated against DuckDB SQL at SF=0.01.

### Advanced DataFrame Usage
- Query subset: `benchbox run --platform polars-df --benchmark tpch --scale 0.01 --queries Q1,Q6,Q14`
- Streaming: `benchbox run --platform polars-df --benchmark tpcds --scale 1 --platform-option streaming=true`

## Data, Reporting, Logging, Timing
- TPC binaries: `_binaries/tpc-{h,ds}/<os-arch>/`; avoid compiling in CI.
- Output: `benchmark_runs/`; manifests enable reuse; normalize cloud `--output` paths. Compression default: zstd (fall back to none).
- Validation toggles: preflight, postgen-manifest, postload.
- CLI summaries: query breakdowns, top failures, recommendations. JSON artifacts to `benchmark_runs/results/` with execution ID + timestamp.
- Logging: respect `--quiet`; use `-v/-vv` for diagnostics; don't change third-party logger levels globally.
- Elapsed time: `benchbox.utils.clock.mono_time()` / `elapsed_seconds()`. Wall-clock only for event/audit timestamps and OS metadata.
- Canonical key: `execution_time_seconds`; compat boundary also accepts `execution_time_ms`.
- Audit: `timing_audit.py --report`, `timing_policy_check.py --strict`. Allowlist: `_project/config/timing_wall_clock_allowlist.json`.
- Quick restart: `~/.benchbox/last_run.yaml` (database type, phases, scale, tuning mode).

## Commits & PRs
Conventional Commits (feat:, fix:, docs:, test:). PRs link issues, include tests + docs. CI: ruff + typecheck + tests via `make test-ci`.
Single repo (`origin` → `joeharris76/BenchBox`); two long-lived branches: `develop` (dev work) and `main` (release-only). Dev PRs target `develop`, squash-merge. Releases use a 2-command flow: `make release-cut VERSION=X.Y.Z` (cuts `vX.Y.Z` from develop, bumps version, generates changelog, curates dev-only paths, opens PR vs main) → `make release-finalize VERSION=X.Y.Z` (squash-merges, tags `main`, pushes the tag → `release.yml` publishes to PyPI). `develop` is intentionally not modified post-release. Full runbook: `docs/operations/release-guide.md`.

**`develop` is PR-gated** (no direct push). Required checks: `lint` + `test (ubuntu-latest, 3.12)`. Linear history; squash-only; 0 reviewer approvals required (self-merge is fine).

**One-shot flow**: from a feature branch run `make pr-preflight && make pr-open`. Preflight runs ruff + fast tests (mirrors CI). `pr-open` pushes, opens the PR vs `develop`, and enables `gh pr merge --auto --squash` so the PR lands the moment CI goes green. Don't poll. The pre-push hook `pr-preflight-fast-tests` (in `.pre-commit-config.yaml`) re-runs the fast lane automatically — activate once with `pre-commit install`.

**Worktrees for parallel branches**: keep `~/Developer/BenchBox/` on `develop` permanently; `make worktree-add BRANCH=fix/foo` creates `../BenchBox.fix-foo/` off `origin/develop`. `cd` in, `uv sync --group dev`, work, run `make pr-open` from inside. After auto-merge, `make worktree-prune` sweeps the worktree (looks for branches gone on origin). Three branches in flight = three worktrees, no stash thrash.

**In Claude Code**: the project-local `/pr` slash command (`.claude/commands/pr.md`) is the canonical wrapper — it commits, preflights, pushes, opens, and enables auto-merge in one shot. Prefer it over the user-global `/commit-push-pr` plugin; that one targets `main` by default and doesn't enable auto-merge.

## Planning & TODOs
Layout: `_project/TODO/{worktree}/{phase}/{item}.yaml`; completed → `_project/DONE/`. Stable `id` = filename slug.
Flat `work[]` with `needs` edges (not nested tasks.phases). Inter-item deps: `deps.needs: [slug-ids]`. Deferred work in separate `deferred[]`.
CLI: `uv run --project _project/scripts -- python _project/scripts/todo_cli.py list|show|stats|ready|next|done|check-graph|validate|reindex|cleanup`.
- `ready`: deps-satisfied by priority. `next <slug>`: ready/blocked/done/deferred within item.
- `done <slug> <work-id>`: marks complete, reports unblocked. `check-graph`: no cycles/dangling refs.
Indexes: `_project/{TODO|DONE}/_indexes/` (gitignored — auto-regenerated by `todo_cli.py` on first read; `make todo-reindex` to rebuild explicitly). Template: `TODO_ENTRY_TEMPLATE.yaml`. Schema: `TODO_SCHEMA.yaml`.
Guardrails: must_preserve, approach, anti_patterns, verification, scope_limit.
Scripts: `generate_indexes.py`, `validate_todo.py` (needs `--project _project/scripts`), `migrate_todo_format.py` in `_project/scripts/`.
After changes: `make todo-reindex` (or just let `todo_cli.py` regen on next read). See `~/.claude/skills/todo/SKILL.md`.

## Skills & Workflow
Workflows: benchmark-test, quick-quality-check, tpc-compliance-check, compare-implementations, binary-wrapper-check, dialect-translation-test, live-platform-test, architecture-review, benchmark-plan-and-execute, project-todo-sync.
Auto-detect runner, honor non-interactive, output human + JSON. Plans: one step in_progress. Preambles: short, grouped. Patches: surgical.

## Recipes
```bash
benchbox run --platform duckdb --benchmark tpch --scale 0.01 --phases power --non-interactive     # TPC-H smoke
benchbox run --benchmark tpcds --scale 0.1 --phases generate --output ./tpcds_sf01 --non-interactive  # data only
benchbox run --platform duckdb --benchmark tpch --scale 0.1 --dry-run ./preview --phases power --seed 3
benchbox run --platform polars-df --benchmark tpch --scale 0.01 --non-interactive                  # DataFrame Polars
benchbox run --platform pandas-df --benchmark tpch --scale 0.01 --non-interactive                  # DataFrame Pandas
benchbox run --platform polars-df --benchmark nyctaxi --scale 0.01 --non-interactive               # NYC Taxi
benchbox run --platform polars-df --benchmark clickbench --scale 0.01 --non-interactive            # ClickBench
# SSB comparison: run DuckDB + polars-df at same scale, then benchbox compare <f1> <f2>
```

## Structure
`benchbox/` (core+CLI), `tests/`, `examples/`, `docs/`, `_project/` (working files, experiments; `_trash/` for discards), configs (pyproject.toml, pytest.ini, Makefile), outputs in `benchmark_runs/`.

## Timing Policy
Benchmark timings use `mono_time()` / `elapsed_seconds()` from `benchbox.utils.clock`. Wall-clock is allowed only for event/audit timestamps and OS metadata - never for measured durations. Any wall-clock site measuring elapsed time is a policy violation.
Canonical result key: `execution_time_seconds`; legacy `execution_time_ms` is accepted at compat boundaries only.
Audit: `uv run _project/scripts/timing_audit.py --report` lists every wall-clock site with rationale; `timing_policy_check.py --strict` fails on any unallowlisted call. Allowlist lives at `_project/config/timing_wall_clock_allowlist.json` and requires a reason per entry.
Deep dive: `docs/development/run-lifecycle-map.md`.

## Result Validation
Every phase that produces data feeds the validation pipeline. Validation modes: `exact` (default for power/throughput), `loose` (numeric tolerance), `range` (min/max bounds), `full` (exact + schema + row counts + checksums), `disabled` (opt-out, CI-blocked).
Toggles: `--validation <mode>` at the CLI, or `--preflight`/`--postgen-manifest`/`--postload` for per-stage controls.
Cross-platform validation (when enabled) replays the same query set across DuckDB and the target platform, comparing row-by-row under the chosen tolerance mode. Failures report diff samples, not summary counts.
Deep dive: `docs/development/result-integrity-validation.md`.

## Adapter Authoring
To add a new platform: subclass `PlatformAdapter` (`benchbox/platforms/base/adapter.py`), implement the abstract hooks (connection, execute, load), register via `@register_platform`, and drop config in `benchbox/platforms/<name>/`. Keep SDK imports lazy so optional dependencies don't break base installs.
Refactor status: the base class is being split into cohesive modules (connection / execution / data_loading / result_capture / dialect_translation / tuning). See `docs/development/adapter-refactor-map.md` for the target module layout before introducing new adapter responsibilities.
**DDL transforms**: every CREATE TABLE rewrite an adapter performs must be registered in `benchbox/sql_compat/rules/ddl_optimize/<platform>_ddl_rewrites.py` under `Phase.DDL_OPTIMIZE`. Adapters inherit `BaseDdlOptimizer` (`benchbox/platforms/base/ddl_optimizer.py`) for automatic rule dispatch. `compat_lint --check-ddl-drift` enforces this at CI time. Full pattern and checklist: `benchbox/sql_compat/README.md`.
Deep dive: `docs/development/adding-new-platforms.md` (SQL), `docs/development/adding-dataframe-platform.md` (DataFrame), `docs/development/platform-development.rst`.

## Dependency Upper Bounds
**Policy**: cap only the highest-risk deps - those with history of breaking minor/major releases, or whose API is deeply integrated into BenchBox internals. Unbounded is the default for everything else.
**Currently capped** (see `pyproject.toml` comments for rationale): `sqlglot<31`, `click<9`, `pydantic<3`, `pyarrow<24`, `duckdb<2`. These five drive translation, CLI, validation, columnar IO, and the SQL runner respectively.
**When to add a bound**: a dep ships a breaking change in a non-major release, OR BenchBox integrates deeply enough that a major bump would require non-trivial migration.
**When to bump**: only after explicitly validating on the new major - never reactively when CI breaks (that's the signal we wanted). Run the full fast suite + standards suite on the new major before bumping.
**Review cadence**: see `_project/TODO/main/planning/review-dependency-upper-bounds-quarterly.yaml`. Open issue links in pyproject comments when available.
**Release gate**: `.github/workflows/release.yml` runs `scripts/check_dependency_bounds.py --fail-on=cap-reached` before build. This blocks only on a genuine bounds violation (locked major ≥ cap major); ceiling-minus-one (e.g. `sqlglot 30.x` under `<31`) is surfaced in the markdown artifact but not blocking, because current caps intentionally sit at `current_major + 1`. Same script serves the quarterly review - single source of truth.
**Bump procedure**: (1) validate the new major on fast + standards suites; (2) edit `pyproject.toml` cap and rationale comment; (3) refresh `uv.lock`; (4) if bumping because the release gate has fired, link the failing run in the commit message.
Audit with `uv tree` / `uv pip list`. Deep dives: `docs/development/dependency-compatibility.md` (version caps on kept deps), `docs/development/dependency-inventory.md` (per-dep import sites, owner module, and elimination candidates).

## Test Markers Cheat Sheet
| Marker | Meaning | Typical runtime |
|--------|---------|-----------------|
| `fast` | Isolated unit; no network, no docker, no data gen | < 1s each |
| `unit` | Unit-level, may touch disk/cache | < 5s each |
| `integration` | Multi-module, local-only | seconds |
| `tpch` / `tpcds` / `ssb` | Standards compliance at tiny scale | seconds |
| `platform_smoke` | Per-platform connectivity + trivial query | seconds |
| `docker_integration` | Requires local container (clickhouse/trino/…) | tens of seconds |
| `live_integration` | Hits real cloud account - **approval required** | variable |
| `slow` / `resource_heavy` / `stress` | Excluded from fast/CI profiles | minutes |
Short form works for agents: `uv run -- python -m pytest -m fast -q`. `tests/conftest.py` enforces the slow/stress/live_integration/resource_heavy exclusion when those markers aren't in the `-m` expression. Full taxonomy: `tests/README.md`.

Parallel-run safety: `pytest -n auto` acquires an inter-process lock at `~/.benchbox/test.lock`; concurrent runs fail fast. Details: `tests/README.md` → "Parallel Run Mutual Exclusion".

## Further Reading
| Topic | Deep-dive doc |
|-------|---------------|
| Run lifecycle | `docs/development/run-lifecycle-map.md` |
| Result validation | `docs/development/result-integrity-validation.md` |
| Adding SQL platforms | `docs/development/adding-new-platforms.md` |
| Adding DataFrame platforms | `docs/development/adding-dataframe-platform.md` |
| Adapter refactor map | `docs/development/adapter-refactor-map.md` |
| DDL transform governance | `benchbox/sql_compat/README.md` |
| Dependency compatibility | `docs/development/dependency-compatibility.md` |
| Dependency inventory & ownership | `docs/development/dependency-inventory.md` |
| Parallel test lock | `tests/README.md` |
| Read primitives | `docs/development/read-primitives-catalog.md` |
