"""Tests for the shared staged-load template used by cloud adapters.

Redshift and Snowflake independently implemented the same per-table
staged-load loop with behavioral drift: Snowflake keyed stats uppercase
while Redshift keyed lowercase, and Snowflake truncated failure text to 100
characters while Redshift logged it in full. ``run_staged_table_loads``
owns the mechanics; these tests pin the preserved per-platform behavior
(casing, fail-fast, timings) and the unified full-text error reporting.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from benchbox.platforms.base.data_loading import run_staged_table_loads

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.logger = logging.getLogger("test-staged-load")
    return adapter


class TestStagedLoadTemplate:
    """Shared mechanics with caller-owned platform behavior."""

    def test_records_stats_with_caller_key_folding(self):
        """Redshift folds lower, Snowflake folds upper; the template honors both."""
        adapter = _adapter()
        tables = {"LineItem": [Path("/tmp/a.tbl")], "Orders": [Path("/tmp/b.tbl")]}

        lower_stats, _, _ = run_staged_table_loads(
            adapter,
            tables=tables,
            stat_key=str.lower,
            filter_files=lambda paths: [Path(p) for p in paths],
            load_one=lambda table, files: 10,
            record_timings=False,
            fail_fast=False,
        )
        upper_stats, _, _ = run_staged_table_loads(
            adapter,
            tables=tables,
            stat_key=str.upper,
            filter_files=lambda paths: [Path(p) for p in paths],
            load_one=lambda table, files: 10,
            record_timings=False,
            fail_fast=False,
        )
        assert set(lower_stats) == {"lineitem", "orders"}
        assert set(upper_stats) == {"LINEITEM", "ORDERS"}

    def test_skipped_tables_record_zero_without_timings_by_default(self):
        """Empty tables record zero; Redshift callers get no timings payload."""
        adapter = _adapter()
        stats, total, timings = run_staged_table_loads(
            adapter,
            tables={"ghost": []},
            stat_key=str.lower,
            filter_files=lambda paths: [],
            load_one=lambda table, files: 99,
            record_timings=False,
            fail_fast=False,
        )
        assert stats == {"ghost": 0}
        assert timings is None
        assert total >= 0

    def test_skipped_tables_record_zero_timings_when_requested(self):
        """Snowflake shape: skips carry the same key with a zero timing entry."""
        adapter = _adapter()
        stats, _, timings = run_staged_table_loads(
            adapter,
            tables={"ghost": []},
            stat_key=str.upper,
            filter_files=lambda paths: [],
            load_one=lambda table, files: 99,
            record_timings=True,
            fail_fast=True,
        )
        assert stats == {"GHOST": 0}
        assert timings == {"GHOST": {"total_ms": 0}}

    def test_failure_logs_full_error_text(self):
        """The drift fix: no truncation of the failure cause."""
        adapter = _adapter()
        adapter.logger = MagicMock()
        long_cause = "x" * 500
        stats, _, timings = run_staged_table_loads(
            adapter,
            tables={"orders": [Path("/tmp/o.tbl")]},
            stat_key=str.upper,
            filter_files=lambda paths: [Path(p) for p in paths],
            load_one=_fail_with(long_cause),
            record_timings=True,
            fail_fast=False,
        )
        assert stats == {"ORDERS": 0}
        assert timings == {"ORDERS": {"total_ms": 0}}
        (message,) = adapter.logger.error.call_args.args
        assert long_cause in message
        assert "..." not in message

    def test_continue_on_failure_by_default(self):
        """Redshift semantics: a failed table does not abort later tables."""
        adapter = _adapter()
        calls: list[str] = []

        def load_one(table: str, files: list[Path]) -> int:
            calls.append(table)
            if table == "bad":
                raise RuntimeError("boom")
            return 7

        stats, _, _ = run_staged_table_loads(
            adapter,
            tables={"bad": [Path("/tmp/b.tbl")], "good": [Path("/tmp/g.tbl")]},
            stat_key=str.lower,
            filter_files=lambda paths: [Path(p) for p in paths],
            load_one=load_one,
            record_timings=False,
            fail_fast=False,
        )
        assert calls == ["bad", "good"]
        assert stats == {"bad": 0, "good": 7}

    def test_fail_fast_reraises_after_recording_zeros(self):
        """Snowflake semantics: full refreshes abort on a failed table."""
        adapter = _adapter()
        with pytest.raises(RuntimeError, match="boom"):
            run_staged_table_loads(
                adapter,
                tables={"bad": [Path("/tmp/b.tbl")]},
                stat_key=str.upper,
                filter_files=lambda paths: [Path(p) for p in paths],
                load_one=_fail_with("boom"),
                record_timings=True,
                fail_fast=True,
            )

    def test_on_table_loaded_hook_runs_after_success(self):
        """CTAS sorting and similar post-load work run inside the loop."""
        adapter = _adapter()
        seen: list[tuple[str, str, int]] = []
        stats, _, timings = run_staged_table_loads(
            adapter,
            tables={"orders": [Path("/tmp/o.tbl")]},
            stat_key=str.upper,
            filter_files=lambda paths: [Path(p) for p in paths],
            load_one=lambda table, files: 42,
            on_table_loaded=lambda table, key, count: seen.append((table, key, count)),
            record_timings=True,
            fail_fast=True,
        )
        assert seen == [("orders", "ORDERS", 42)]
        assert stats == {"ORDERS": 42}
        assert set(timings or {}) == {"ORDERS"}

    def test_custom_log_sinks_preserve_verbose_gating(self):
        """Snowflake keeps verbose-gated success lines through the hooks."""
        adapter = _adapter()
        adapter.logger = MagicMock()
        success_lines: list[str] = []
        summary_lines: list[str] = []
        run_staged_table_loads(
            adapter,
            tables={"orders": [Path("/tmp/o.tbl")]},
            stat_key=str.upper,
            filter_files=lambda paths: [Path(p) for p in paths],
            load_one=lambda table, files: 5,
            record_timings=True,
            fail_fast=True,
            success_log=success_lines.append,
            summary_log=summary_lines.append,
        )
        adapter.logger.info.assert_not_called()
        assert len(success_lines) == 1
        assert len(summary_lines) == 1

    def test_custom_start_description(self):
        """Redshift's direct branch keeps its distinct start wording."""
        adapter = _adapter()
        adapter.log_verbose = MagicMock()
        run_staged_table_loads(
            adapter,
            tables={"orders": [Path("/tmp/o.tbl")]},
            stat_key=str.lower,
            filter_files=lambda paths: [Path(p) for p in paths],
            load_one=lambda table, files: 5,
            record_timings=False,
            fail_fast=False,
            describe_start=lambda table, chunk: f"Direct loading data for table: {table}",
        )
        (line,) = adapter.log_verbose.call_args.args
        assert line == "Direct loading data for table: orders"


def _fail_with(message: str) -> Any:
    def load_one(table: str, files: list[Path]) -> int:
        raise RuntimeError(message)

    return load_one
