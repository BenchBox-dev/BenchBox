# BenchBox Test Reference

Use `uv run --` for Python and prefer Makefile targets.

## Targets

- Fast smoke: `uv run -- python -m pytest -m fast -q`
- Standards: `uv run -- python -m pytest -m "tpch or tpcds" --tb=short`
- TPC-H/TPC-DS/SSB/ClickBench: use matching Makefile or focused pytest target.
- DataFrame platforms: compare against DuckDB SQL at smoke scale when validating behavior.

## Rules

Report command, benchmark/platform/scale/query subset, result, failures, artifacts, and narrow next command. Avoid live/cloud/docker tests without the required approval/environment.
