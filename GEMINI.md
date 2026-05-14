# GEMINI.md

This file provides guidance to Gemini when working with BenchBox.

## Git Workflow
- **Single repo, single remote**: `origin` → `joeharris76/BenchBox`. Canonical clone: `/Users/joe/Developer/BenchBox`. There is no `private` / `public` remote; the pre-migration two-remote setup is retired (see `_project/decisions/single-repo-migration.md` for history).
- **Branches**: `develop` is the long-lived dev branch; `main` is release-only. Dev PRs target `develop`, squash-merge.
- **One-shot PR flow**: from a feature branch, `make pr-preflight && make pr-open`. Opens the PR vs `develop` with `gh pr create --fill` and enables auto-merge once CI is green. Walk away — don't poll.
- **Default write-task close-out**: implement → `code review` (fix every finding, incl. nits) → `make pr-open`. Skip only if the user explicitly opts out (typo fix, already-reviewed change).
- **Review protocol**: review, audit, research, compare, to-spec, security
  review, and L2 blind-spot audit actions are read-only plus local capture per
  the synced `SHARED/review-protocol` skill. Local capture does not authorize
  commit, push, PR creation, or auto-merge.
- **Worktrees**: `~/Developer/BenchBox/` stays on `develop`, always. `make worktree-add BRANCH=fix/foo` creates `../BenchBox.fix-foo/` off `origin/develop`. `cd` in, `uv sync --group dev`, work, `make pr-open` from inside. **Agents must not `git checkout`/`switch`/`branch -m` in the main clone without explicit user approval; create a worktree first.**
- **Releases**: 2-command flow on `develop` — `make release-cut VERSION=X.Y.Z` then `make release-finalize VERSION=X.Y.Z`. See `docs/operations/release-guide.md`.

## Quick Commands
- **pytest**: `uv run -- python -m pytest {test}`
- **smoke**: `uv run -- python -m pytest -m fast -q`
- **scripts**: `uv run -- python script.py`
- **add dependency**: `uv add library_name`
- **add with extras**: `uv add benchbox --extra cloud`
- **dev setup**: `uv sync --group dev`
- **format**: `uv run ruff format .`
- **lint**: `uv run ruff check .`
- **lint+fix**: `uv run ruff check --fix .`
- **type check**: `uv run ty check`

## Key Points
- OLAP/analytics benchmark library
- Python 3.10+, 120 chars, ruff formatting, type hints required
- `uv` exclusively for package management
- TPC binaries auto-detected from `_binaries/`
- SQL dialect translation via sqlglot
- Working files go in `_project/`
- Research before coding; review every find-replace in context
- Coverage ≥80% required
- **Constraints**: TPC-DS SF<1 requires the patched dsdgen bundled with BenchBox (stock dsdgen crashes at SF<1); No `-o "addopts="` with pytest
- **Timing**: Use `benchbox.utils.clock.mono_time()` / `elapsed_seconds()` for durations
- **Non-interactive**: Use `--non-interactive` or `BENCHBOX_NON_INTERACTIVE=true` for scripts

## Test Organization
- `tests/unit/`: Fast component tests
- `tests/integration/`: Database integration
- Markers: `fast`, `unit`, `integration`, `tpch`, `tpcds`, `platform_smoke`, `docker_integration`, `live_integration`
- Run by category: `make test-unit`, `make test-fast`

## Benchmark Structure
- Core: `benchbox/core/{benchmark}/`
- Pattern: `benchmark.py`, `generator.py`, `queries.py`, `schema.py`
- Runners: `runner.py` for simplified usage

## Pre-approved Commands
Gemini can run these without permission:

### Development and Testing
- `make test-*`, `make coverage*`, `make lint`, `make format`
- `make typecheck`, `make develop`, `make install`
- `uv run -- python -m pytest *`

### File Operations (read-only)
- `ls*`, `find*`, `cat*`, `head*`, `tail*`, `wc*`
- `file*`, `stat*`, `du*`, `tree*`, `which*`

### Git Operations (read-only)
- `git status`, `git diff*`, `git log*`, `git show*`
- `git branch*`, `git remote*`, `git config --list`

### Python Development
- `uv add*`, `uv sync*`, `uv tree`, `uv export`
- `uv pip list`, `uv pip show*`
- `uv run -- python -c*`, `uv run -- python -m*`

### TPC Binary Operations
- `_binaries/tpc-{h,ds}/<platform>/dsdgen --help`, `_binaries/tpc-{h,ds}/<platform>/dsqgen --help`
- `timeout 30s _binaries/tpc-{h,ds}/<platform>/dsdgen*`
- `timeout 60s _binaries/tpc-{h,ds}/<platform>/dsqgen*`

### TODO Management
- `uv run _project/scripts/todo_cli.py list|show|stats|ready|next|done|check-graph`
- `uv run _project/scripts/validate_todo.py*`
- `uv run _project/scripts/generate_indexes.py` (or `make todo-reindex`)
- `uv run _project/scripts/migrate_todo_format.py*`

### Timing & Audit
- `uv run _project/scripts/timing_audit.py --report`
- `uv run _project/scripts/timing_policy_check.py --strict`

### System Information (read-only)
- `ps*`, `uname*`, `whoami`, `pwd`, `env | grep*`

## TODO Workflow
- Layout: `_project/TODO/{worktree}/{phase}/{item}.yaml`; completed -> `_project/DONE/`.
- Stable `id` = filename slug.
- Flat `work[]` with `needs` edges. Inter-item deps: `deps.needs: [slug-ids]`.
- CLI: `uv run _project/scripts/todo_cli.py list|show|stats|ready|next|done|check-graph`.
- Indexes are gitignored; `make todo-reindex` to rebuild (also auto-runs on first read).
- Refer to `TODO_ENTRY_TEMPLATE.yaml` and `TODO_SCHEMA.yaml` for format.
- Standard format in files: Priority/Status/Description/Files/Solution/Impact.

## CLI Options & Phases
- **Basic Run**: `benchbox run --platform {plat} --benchmark {bm} --scale {sf}`
- **Phases**: `generate`, `load`, `warmup`, `power`, `throughput`, `maintenance` (Default: `generate,load,execute`)
- **Queries**: Subset e.g. `--queries Q1,Q6,Q17` (TPC-H 1-22, TPC-DS 1-99, SSB 1-13)
- **Validation**: `exact`, `loose`, `range`, `disabled`, `full`
- **Tuning**: `tuned`, `notuning`, `auto`, or YAML path
- **Compression**: `zstd` (default), `none`, `gzip:6`
- **Dry-run**: `benchbox run --dry-run ./preview ...`
- **Force**: `--force all|datagen|upload`

## DataFrame Support
- 15/19 benchmarks supported via `--platform {polars|pandas|datafusion|pyspark|modin|cudf|dask}-df`
- Expressions (Lazy): Polars, DataFusion, PySpark
- Eager: Pandas, Modin, cuDF, Dask
- Queries in `dataframe_queries/` beside SQL `queries.py`

## Recipes
```bash
# TPC-H smoke run
benchbox run --platform duckdb --benchmark tpch --scale 0.01 --phases power --non-interactive

# Data generation only
benchbox run --benchmark tpcds --scale 0.1 --phases generate --output ./tpcds_sf01 --non-interactive

# Polars-df run
benchbox run --platform polars-df --benchmark tpch --scale 0.01 --non-interactive
```

## Commit Guidelines
- Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`
- CI must pass: ruff, typecheck, tests
