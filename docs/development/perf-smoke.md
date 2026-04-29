# Per-PR Performance Smoke

BenchBox runs a small perf-smoke job on every PR to catch orchestration-
overhead regressions early. It's deliberately narrow: one platform
(DuckDB), one benchmark (TPC-H), one scale (SF=0.01), one phase (power).
The goal is to surface regressions in the result builder, dialect
translation, validation passes, and lazy-loading machinery - not to
benchmark DuckDB itself.

## How it works

1. CI runs `benchbox run --platform duckdb --benchmark tpch --scale 0.01 --phases power`.
2. CI calls `benchbox compare` against the checked-in baseline at
   `_project/baselines/perf_smoke_duckdb_tpch_001.json` with
   `--fail-on-regression 10%`.
3. Result JSON (baseline + current) is uploaded as a 14-day artifact.

Workflow lives at `.github/workflows/perf-smoke.yml`.

## Skipping the check

Attach the `skip-perf-smoke` label to the PR. Use it only for:

- Intentional performance shifts where the baseline needs refresh.
- GH-runner flake that you've confirmed by re-running the workflow.

Don't use it to merge code you know regresses perf. The baseline refresh
below is the right move.

## Refreshing the baseline

Refresh after:

- An intentional perf-improving change has landed and you want to lock
  in the new floor.
- A genuine hardware change on GH runners that shifts the noise floor
  broadly (rare - coordinate with maintainers).

Procedure:

```
# 1. Run locally on a quiet machine (or trigger the workflow and grab
#    the uploaded artifact from the green run on main after merge).
uv run -- benchbox run \
  --platform duckdb \
  --benchmark tpch \
  --scale 0.01 \
  --phases power \
  --non-interactive

# 2. Copy the produced JSON over the baseline.
cp benchmark_runs/results/tpch_sf001_duckdb_sql_*.json \
   _project/baselines/perf_smoke_duckdb_tpch_001.json

# 3. Commit with a message that links the PR driving the refresh:
#    chore(perf-smoke): refresh baseline after <PR-ref>
```

## Troubleshooting

- **Flake on GH runners**: re-run the workflow once. If it persists,
  attach `skip-perf-smoke` and open an issue so the baseline or threshold
  can be reviewed; don't chase the flake under PR pressure.
- **Compare command errors**: validate the baseline with
  `uv run -- python -c 'import json; json.load(open("_project/baselines/perf_smoke_duckdb_tpch_001.json"))'`.
- **Baseline drift over time**: if the noise floor creeps but no single
  PR regressed, refresh via the procedure above rather than raising the
  threshold.
