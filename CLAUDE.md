# CLAUDE.md - Quick Reference

→ **See AGENTS.md for full guidance.** Claude Code-specific shortcuts only.

**Critical rules**: Always `uv run` (never bare `python`/`pytest`/`ruff`). Never `git add -A`. TPC-DS SF<1 requires the patched dsdgen bundled with BenchBox (stock dsdgen crashes at SF<1; see `patch-and-redistribute-tpcds-dsdgen-subscale-support`). No `-o "addopts="` with pytest.

## Git workflow

Single repo, single remote (`origin` → `joeharris76/BenchBox`). Working
clone: `~/Developer/benchbox-public` (canonical path
`/Users/joe/Developer/BenchBox` is a symlink).

- **Branches**: `develop` is the long-lived dev branch; `main` is
  release-only.
- **Dev PRs**: feature branch off `develop` → PR → squash-merge to
  `develop`. Required CI: `lint` + `test (ubuntu-latest, 3.12)`.
- **Releases** (version-branch flow): on `develop`, run `make bump
  VERSION=X.Y.Z` and `make changelog-draft VERSION=X.Y.Z`, then `make
  release-prepare VERSION=X.Y.Z` cuts the `vX.Y.Z` branch with curated
  tree → PR → squash-merge to `main` → tag `main` → `release.yml`
  publishes to PyPI → `make release-rebase-develop VERSION=X.Y.Z`
  rebases develop. Full runbook: `docs/operations/release-guide.md`.

## Commands

| Task | Command |
|------|---------|
| pytest | `uv run -- python -m pytest {test}` |
| smoke | `uv run -- python -m pytest -m fast -q` |
| format | `uv run ruff format .` |
| lint | `uv run ruff check .` |
| lint+fix | `uv run ruff check --fix .` |
| typecheck | `uv run ty check` |

### CLI
```bash
benchbox run --platform duckdb --benchmark tpch --scale 0.01        # basic
benchbox run --platform duckdb --benchmark tpch --queries Q1,Q6,Q17 # subset
benchbox run --dry-run ./preview --platform snowflake --benchmark tpcds
benchbox run --platform duckdb --benchmark tpch --force datagen
benchbox run --platform duckdb --benchmark tpch --compression zstd:9
benchbox run --platform duckdb --benchmark tpch --validation full
benchbox run --platform polars-df --benchmark tpch --scale 0.1      # dataframe
benchbox run --platform duckdb --benchmark tpch --platform-option driver_version=1.2.0
benchbox run --platform duckdb --benchmark nyctaxi --benchmark-option taxi_types=yellow,green
benchbox run --help | --help-topic all | --help-topic examples | --help-topic benchmarks
```

| Option | Values |
|--------|--------|
| `--platform` | duckdb, sqlite, snowflake, databricks, clickhouse-cloud, motherduck, polars-df, pandas-df, etc. |
| `--benchmark` | tpch, tpcds, ssb, clickbench, nyctaxi, tsbs-devops, h2odb, datavault, etc. |
| `--scale` | Scale factor [default: 0.01] |
| `--phases` | generate,load,warmup,power,throughput,maintenance |
| `--queries` | Subset e.g. Q1,Q6,Q17 - max 100; alphanumeric+dash/underscore, ≤64 chars; power/standard only; breaks TPC-H compliance. Ranges: TPC-H 1-22, TPC-DS 1-99, SSB 1-13 |
| `--table-mode` | native (default), external |
| `--tuning` | tuned, notuning, auto, YAML path |
| `--dry-run` | Preview without execution |
| `--force` | all, datagen, upload |
| `--compression` | zstd, zstd:9, gzip:6, none |
| `--validation` | exact, loose, range, disabled, full |
| `--platform-option K=V` | Repeatable. Keys: driver_version (pin driver pkg), driver_auto_install (true/false, auto-install via uv), engine_version (Athena Spark engine) |
| `--benchmark-option K=V` | Repeatable. Benchmark-specific params (e.g. taxi_types=yellow,green for nyctaxi, skew_preset=heavy for tpch_skew). Run `--help-topic benchmarks` for full list. |

## Pre-approved Commands
- **Dev/Test**: `make test-*`, `make coverage*`, `make lint`, `make format`, `make typecheck`, `uv run -- python -m pytest *`
- **Files**: `ls*`, `find*`, `cat*`, `head*`, `tail*`, `wc*`, `file*`, `stat*`, `du*`, `tree*`, `which*`
- **Git**: `git status`, `git diff*`, `git log*`, `git show*`, `git branch*`, `git remote*`, `git config --list`
- **Python**: `uv tree`, `uv pip list`, `uv pip show*`, `uv export`, `uv run -- python -c*`, `uv run -- python -m*`
- **TPC**: `timeout 30s _binaries/tpc-{h,ds}/<platform>/dsdgen*`, `timeout 60s _binaries/tpc-{h,ds}/<platform>/dsqgen*`
- **TODO**: `uv run --project _project/scripts -- python _project/scripts/todo_cli.py list*|show*|stats|ready|next*|done*|check-graph`, `uv run --project _project/scripts -- python _project/scripts/validate_todo.py*`, `uv run _project/scripts/generate_indexes.py`, `uv run _project/scripts/migrate_todo_format.py*`
- **System**: `ps*`, `uname*`, `whoami`, `pwd`, `env | grep*`
