# BenchBox Quality Reference

Run the local gate closest to CI.

## Checks

- Lint/format/typecheck via project Makefile or configured commands.
- Fast tests with `uv run -- python -m pytest -m fast -q` or `make test-fast`.
- Timing policy when touching measured durations.
- DDL drift lint when touching platform CREATE TABLE rewrites.

## Output

Summarize pass/fail per check, failures with file/line when available, skipped checks and why, and recommended fix order.
