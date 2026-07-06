"""Timing contract: plan capture must not inflate DataFrame execution_time_ms.

qpc-09 regression tests. Enabling ``--capture-plans`` on DataFrame platforms must
NOT change the reported per-query ``execution_time_ms``: the capture phase is timed
as its own segment and excluded from execution time (mirroring the SQL platforms,
which capture after the timed block). The capture cost is surfaced separately as
``plan_capture_time_ms``.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from benchbox.core.dataframe.profiling import (
    QueryExecutionProfile,
    QueryPlan,
    QueryProfileContext,
    profile_query_execution,
)
from benchbox.core.dataframe.query import DataFrameQuery
from benchbox.platforms.dataframe import expression_family
from benchbox.platforms.dataframe.expression_family import ExpressionFamilyAdapter
from benchbox.platforms.dataframe.unified_frame import UnifiedExpr

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# Capture-phase sleep, chosen large relative to the trivial fake query so the
# "excluded from execution time" contract is unambiguous even with clock noise.
_CAPTURE_SLEEP_MS = 40.0


class _TimingAdapter(ExpressionFamilyAdapter[dict, dict, str]):
    """Minimal expression-family adapter with a trivial (near-zero-time) query."""

    table_mode = "native"
    config = None

    @property
    def platform_name(self) -> str:
        return "Polars"

    def col(self, name: str) -> str:
        return f"col({name})"

    def lit(self, value: Any) -> str:
        return f"lit({value})"

    def date_sub(self, column: str, days: int) -> str:
        return f"date_sub({column},{days})"

    def date_add(self, column: str, days: int) -> str:
        return f"date_add({column},{days})"

    def cast_date(self, column: str) -> str:
        return f"cast_date({column})"

    def cast_string(self, column: str) -> str:
        return f"cast_string({column})"

    def read_csv(
        self,
        path: Path,
        *,
        delimiter: str = ",",
        has_header: bool = True,
        column_names: list[str] | None = None,
        null_marker: str | None = None,
    ) -> dict:
        return {"kind": "csv", "path": str(path)}

    def read_parquet(self, path: Path) -> dict:
        return {"kind": "parquet", "path": str(path)}

    def collect(self, df: dict) -> dict:
        return df

    def get_row_count(self, df: dict) -> int:
        return int(df.get("rows", 1))

    def scalar(self, df: dict, column: str | None = None) -> Any:
        return df.get("value", 1)

    def scalar_to_df(self, data: dict[str, Any]) -> dict:
        return {"rows": 1, "first": tuple(data.values())}

    def window_rank(self, order_by, partition_by=None):
        return "window_rank"

    def window_row_number(self, order_by, partition_by=None):
        return "window_row_number"

    def window_dense_rank(self, order_by, partition_by=None):
        return "window_dense_rank"

    def window_sum(self, column, partition_by=None, order_by=None):
        return "window_sum"

    def window_avg(self, column, partition_by=None, order_by=None):
        return "window_avg"

    def window_count(self, column=None, partition_by=None, order_by=None):
        return "window_count"

    def window_min(self, column, partition_by=None):
        return "window_min"

    def window_max(self, column, partition_by=None):
        return "window_max"

    def union_all(self, *dataframes):
        return {"union": list(dataframes)}

    def rename_columns(self, df, mapping):
        return {"df": df, "mapping": mapping}


def _slow_capture(_lazy: Any, _platform: str) -> QueryPlan:
    """Stand-in plan capture that costs a measurable, fixed amount of time."""
    time.sleep(_CAPTURE_SLEEP_MS / 1000.0)
    return QueryPlan(platform="polars", plan_type="optimized", plan_text="PLAN")


class TestQueryProfileContextTiming:
    def test_execution_time_excludes_measured_plan_capture(self) -> None:
        ctx = QueryProfileContext("Q1", "polars")
        ctx._start_time = time.perf_counter()

        # A measurable "capture" phase inside the profiling window.
        ctx.start_plan_capture()
        time.sleep(_CAPTURE_SLEEP_MS / 1000.0)
        ctx.end_plan_capture()

        profile = ctx.get_profile()

        # Capture time is recorded, and execution_time_ms excludes it.
        assert profile.plan_capture_time_ms >= _CAPTURE_SLEEP_MS * 0.5
        assert profile.execution_time_ms < profile.plan_capture_time_ms, (
            "execution_time_ms must exclude the measured plan-capture phase"
        )

    def test_no_capture_leaves_zero_capture_time(self) -> None:
        ctx = QueryProfileContext("Q2", "polars")
        ctx._start_time = time.perf_counter()
        time.sleep(0.005)
        profile = ctx.get_profile()

        assert profile.plan_capture_time_ms == 0.0
        # With no capture phase, execution_time_ms is the full window.
        assert profile.execution_time_ms >= 5.0 * 0.5

    def test_profile_default_capture_time_is_zero(self) -> None:
        # Field default keeps existing callers / serialized rows unchanged.
        profile = QueryExecutionProfile(query_id="Q", execution_time_ms=1.0)
        assert profile.plan_capture_time_ms == 0.0


class TestProfileQueryExecutionTiming:
    def test_helper_excludes_capture_from_execution_time(self) -> None:
        _, profile = profile_query_execution(
            query_id="Q1",
            platform="polars",
            query_fn=lambda: {"rows": 3},
            collect_fn=lambda df: df,
            row_count_fn=lambda df: 3,
            plan_capture_fn=lambda _df: _slow_capture(_df, "polars"),
            track_memory=False,
        )

        assert profile.query_plan is not None
        assert profile.plan_capture_time_ms >= _CAPTURE_SLEEP_MS * 0.5
        # The capture sleep must not appear in execution time.
        assert profile.execution_time_ms < _CAPTURE_SLEEP_MS * 0.5


class TestExpressionFamilyCaptureTimingContract:
    def test_capture_on_off_report_equal_execution_time(self, monkeypatch) -> None:
        """Same query profiled with capture on/off reports equal execution_time.

        With capture ON the (slow) capture phase must be excluded, so the two runs'
        execution_time_ms agree within tolerance while capture ON reports a
        non-trivial plan_capture_time_ms.
        """
        monkeypatch.setattr(expression_family, "capture_query_plan", _slow_capture)

        adapter = _TimingAdapter()
        ctx = adapter.create_context()
        ctx.register_table("orders", {"rows": 3, "first": (1,)})
        query = DataFrameQuery(
            query_id="Q1",
            query_name="q",
            description="q",
            expression_impl=lambda c: {"rows": 3},
        )

        result_off, profile_off = adapter.execute_query_profiled(ctx, query, track_memory=False, capture_plan=False)
        result_on, profile_on = adapter.execute_query_profiled(ctx, query, track_memory=False, capture_plan=True)

        assert profile_on.query_plan is not None
        assert profile_on.plan_capture_time_ms >= _CAPTURE_SLEEP_MS * 0.5
        assert profile_off.plan_capture_time_ms == 0.0

        # The capture sleep (>=20ms of a 40ms budget) must not leak into the timed
        # query; if it did, capture-on would exceed capture-off by ~the sleep.
        assert profile_on.execution_time_ms < _CAPTURE_SLEEP_MS * 0.5, "plan capture time leaked into execution_time_ms"
        # execution_time_seconds in the result row mirrors the excluded value.
        assert result_on["execution_time_seconds"] < _CAPTURE_SLEEP_MS * 0.5 / 1000.0
        assert result_off["status"] == "SUCCESS" and result_on["status"] == "SUCCESS"
