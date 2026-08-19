# BenchBox Test Reference

Use `uv run --` for Python and prefer Makefile targets.

## Targets

- Fast smoke: `uv run -- python -m pytest -m fast -q`
- Standards: `uv run -- python -m pytest -m "tpch or tpcds" --tb=short`
- TPC-H/TPC-DS/SSB/ClickBench: use matching Makefile or focused pytest target.
- DataFrame platforms: compare against DuckDB SQL at smoke scale when validating behavior.

## Rules

Report the command, benchmark, platform, scale, query subset, result, failures,
artifacts, and narrow next command. Run live, cloud, or Docker tests only with
the required approval and environment.
