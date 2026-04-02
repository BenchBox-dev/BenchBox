"""Tests for UnifiedLazyFrame string, date, subquery, and set operations.

Covers remaining gaps:
- String operations: to_uppercase, to_lowercase, len_chars, split, slice
- Date operations: weekday, truncate, total_seconds, total_days, hour, minute
- CASE/WHEN with multiple branches
- Set operations: vstack (UNION ALL)
- DISTINCT and LIMIT/OFFSET
- HAVING clause filtering (group_by + agg + filter)
- Type coercion: cast_string, floor, std, var, quantile
- Misc: melt, explode, scalar, wrap_expr, wrap_dataframe, desc
- List operations: UnifiedListExpr methods
- Module-level helpers: _is_polars_expr, _is_pyspark_column, _is_datafusion_expr

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _get_unified_expr():
    from benchbox.platforms.dataframe.unified_frame import UnifiedExpr

    return UnifiedExpr


def _get_unified_lazy_frame():
    from benchbox.platforms.dataframe.unified_frame import UnifiedLazyFrame

    return UnifiedLazyFrame


def _create_mock_adapter():
    mock_adapter = MagicMock()
    mock_adapter.platform_name = "Polars"
    return mock_adapter


@pytest.fixture
def pl():
    return pytest.importorskip("polars")


@pytest.fixture
def ulf(pl):
    """Create a basic string/numeric UnifiedLazyFrame."""
    ULF = _get_unified_lazy_frame()
    adapter = _create_mock_adapter()
    df = pl.DataFrame(
        {
            "name": ["Alice", "Bob", "Charlie", "David", "Eve"],
            "city": ["New York", "Boston", "New York", "Chicago", "Boston"],
            "age": [25, 30, 35, 40, 45],
            "score": [88.5, 92.3, 75.0, 88.5, 95.1],
        }
    ).lazy()
    return ULF(df, adapter)


@pytest.fixture
def date_ulf(pl):
    """Create a UnifiedLazyFrame with date/datetime columns."""
    ULF = _get_unified_lazy_frame()
    adapter = _create_mock_adapter()
    df = pl.DataFrame(
        {
            "event": ["A", "B", "C", "D"],
            "event_date": [
                datetime.date(2024, 1, 15),
                datetime.date(2024, 3, 20),
                datetime.date(2024, 6, 5),
                datetime.date(2024, 12, 31),
            ],
            "amount": [100, 200, 300, 400],
        }
    ).lazy()
    return ULF(df, adapter)


# =========================================================================
# String Operations: to_uppercase, to_lowercase
# =========================================================================


class TestStrToUppercase:
    """Tests for UnifiedStrExpr.to_uppercase()."""

    def test_to_uppercase_converts_all_chars(self, pl, ulf):
        """to_uppercase converts lowercase strings to uppercase."""
        expr_factory = _get_unified_expr()
        expr = expr_factory(pl.col("name")).str.to_uppercase()
        result = ulf.with_columns(expr.alias("upper_name")).collect()
        assert result["upper_name"].to_list() == [
            "ALICE",
            "BOB",
            "CHARLIE",
            "DAVID",
            "EVE",
        ]

    def test_to_uppercase_mixed_case(self, pl, ulf):
        """to_uppercase handles strings with spaces and mixed case."""
        expr_factory = _get_unified_expr()
        expr = expr_factory(pl.col("city")).str.to_uppercase()
        result = ulf.with_columns(expr.alias("upper_city")).collect()
        assert result["upper_city"].to_list() == [
            "NEW YORK",
            "BOSTON",
            "NEW YORK",
            "CHICAGO",
            "BOSTON",
        ]


class TestStrToLowercase:
    """Tests for UnifiedStrExpr.to_lowercase()."""

    def test_to_lowercase_converts_all_chars(self, pl):
        """to_lowercase converts mixed-case strings to lowercase."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"text": ["HELLO", "World", "FoObAr"]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("text")).str.to_lowercase()
        result = frame.with_columns(expr.alias("lower")).collect()
        assert result["lower"].to_list() == ["hello", "world", "foobar"]


# =========================================================================
# String Operations: len_chars
# =========================================================================


class TestStrLenChars:
    """Tests for UnifiedStrExpr.len_chars()."""

    def test_len_chars_returns_character_count(self, pl, ulf):
        """len_chars returns the character count of each string."""
        expr_factory = _get_unified_expr()
        expr = expr_factory(pl.col("name")).str.len_chars()
        result = ulf.with_columns(expr.alias("name_len")).collect()
        assert result["name_len"].to_list() == [5, 3, 7, 5, 3]

    def test_len_chars_with_spaces(self, pl, ulf):
        """len_chars counts spaces in the character length."""
        expr_factory = _get_unified_expr()
        expr = expr_factory(pl.col("city")).str.len_chars()
        result = ulf.with_columns(expr.alias("city_len")).collect()
        assert result["city_len"].to_list() == [8, 6, 8, 7, 6]


# =========================================================================
# String Operations: split + list accessor
# =========================================================================


class TestStrSplit:
    """Tests for UnifiedStrExpr.split()."""

    def test_split_and_get_first_element(self, pl):
        """split returns a list; .list.get(0) gets the first element."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"full_name": ["Alice Smith", "Bob Jones"]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("full_name")).str.split(" ").list.get(0)
        result = frame.with_columns(expr.alias("first_name")).collect()
        assert result["first_name"].to_list() == ["Alice", "Bob"]

    def test_split_and_get_last_element(self, pl):
        """split with .list.get(1) gets the second element (last name)."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"full_name": ["Alice Smith", "Bob Jones"]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("full_name")).str.split(" ").list.get(1)
        result = frame.with_columns(expr.alias("last_name")).collect()
        assert result["last_name"].to_list() == ["Smith", "Jones"]


# =========================================================================
# String Operations: slice
# =========================================================================


class TestStrSlice:
    """Tests for UnifiedStrExpr.slice()."""

    def test_slice_with_offset_and_length(self, pl, ulf):
        """slice extracts a substring given offset and length."""
        expr_factory = _get_unified_expr()
        expr = expr_factory(pl.col("name")).str.slice(0, 3)
        result = ulf.with_columns(expr.alias("prefix")).collect()
        assert result["prefix"].to_list() == ["Ali", "Bob", "Cha", "Dav", "Eve"]

    def test_slice_with_offset_only(self, pl):
        """slice with offset only returns from offset to end."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"text": ["Hello"]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("text")).str.slice(2)
        result = frame.with_columns(expr.alias("sub")).collect()
        assert result["sub"].to_list() == ["llo"]


# =========================================================================
# Date Operations: hour, minute
# =========================================================================


class TestDtHourMinute:
    """Tests for UnifiedDtExpr.hour() and .minute()."""

    def test_hour_extraction(self, pl):
        """hour() extracts the hour component from datetime."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame(
            {
                "ts": [
                    datetime.datetime(2024, 1, 15, 10, 30),
                    datetime.datetime(2024, 1, 15, 23, 45),
                ]
            }
        ).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("ts")).dt.hour()
        result = frame.with_columns(expr.alias("hr")).collect()
        assert result["hr"].to_list() == [10, 23]

    def test_minute_extraction(self, pl):
        """minute() extracts the minute component from datetime."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame(
            {
                "ts": [
                    datetime.datetime(2024, 1, 15, 10, 30),
                    datetime.datetime(2024, 1, 15, 23, 45),
                ]
            }
        ).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("ts")).dt.minute()
        result = frame.with_columns(expr.alias("mn")).collect()
        assert result["mn"].to_list() == [30, 45]


# =========================================================================
# Date Operations: weekday
# =========================================================================


class TestDtWeekday:
    """Tests for UnifiedDtExpr.weekday()."""

    def test_weekday_returns_iso_weekday(self, pl):
        """weekday() returns ISO 8601 weekday (1=Monday .. 7=Sunday)."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        # 2024-01-15 is a Monday
        df = pl.DataFrame(
            {
                "d": [
                    datetime.date(2024, 1, 15),  # Monday
                    datetime.date(2024, 1, 20),  # Saturday
                    datetime.date(2024, 1, 21),  # Sunday
                ]
            }
        ).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("d")).dt.weekday()
        result = frame.with_columns(expr.alias("wd")).collect()
        weekdays = result["wd"].to_list()
        assert weekdays[0] == 1  # Monday
        assert weekdays[1] == 6  # Saturday
        assert weekdays[2] == 7  # Sunday


# =========================================================================
# Date Operations: truncate
# =========================================================================


class TestDtTruncate:
    """Tests for UnifiedDtExpr.truncate()."""

    def test_truncate_to_day(self, pl):
        """truncate('1d') truncates datetime to the start of day."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame(
            {
                "ts": [
                    datetime.datetime(2024, 3, 15, 10, 30, 45),
                    datetime.datetime(2024, 3, 15, 23, 59, 59),
                ]
            }
        ).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("ts")).dt.truncate("1d")
        result = frame.with_columns(expr.alias("day")).collect()
        days = result["day"].to_list()
        # Both truncate to the same start-of-day
        assert days[0] == days[1]

    def test_truncate_to_hour(self, pl):
        """truncate('1h') truncates datetime to the start of hour."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame(
            {
                "ts": [
                    datetime.datetime(2024, 3, 15, 10, 30, 45),
                    datetime.datetime(2024, 3, 15, 10, 0, 0),
                ]
            }
        ).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("ts")).dt.truncate("1h")
        result = frame.with_columns(expr.alias("hr")).collect()
        hours = result["hr"].to_list()
        # Both are in the same hour, so they truncate to the same value
        assert hours[0] == hours[1]


# =========================================================================
# Date Operations: total_seconds, total_days
# =========================================================================


class TestDtDuration:
    """Tests for UnifiedDtExpr.total_seconds() and total_days()."""

    def test_total_seconds_from_duration(self, pl):
        """total_seconds() extracts seconds from a duration."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame(
            {
                "start": [datetime.datetime(2024, 1, 1, 0, 0, 0)],
                "end": [datetime.datetime(2024, 1, 1, 1, 30, 0)],
            }
        ).lazy()
        frame = ULF(df, adapter)
        # Build duration column via subtraction, then extract seconds
        diff = expr_factory(pl.col("end") - pl.col("start"))
        seconds = diff.dt.total_seconds()
        result = frame.with_columns(seconds.alias("secs")).collect()
        assert result["secs"].to_list() == [5400]  # 1.5 hours = 5400 seconds

    def test_total_days_from_duration(self, pl):
        """total_days() extracts days from a duration."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame(
            {
                "start": [datetime.date(2024, 1, 1)],
                "end": [datetime.date(2024, 1, 11)],
            }
        ).lazy()
        frame = ULF(df, adapter)
        diff = expr_factory(pl.col("end") - pl.col("start"))
        days = diff.dt.total_days()
        result = frame.with_columns(days.alias("d")).collect()
        assert result["d"].to_list() == [10]


# =========================================================================
# CASE/WHEN with multiple branches and else
# =========================================================================


class TestWhenThenOtherwise:
    """Tests for when/then/otherwise chaining (CASE expression)."""

    def test_single_when_then_otherwise(self, pl, ulf):
        """Single when/then/otherwise produces correct CASE output."""
        from benchbox.platforms.dataframe.unified_frame import UnifiedExpr

        cond = UnifiedExpr(pl.col("age") < 35)
        result_expr = pl.when(cond.native).then(pl.lit("young")).otherwise(pl.lit("mature"))
        result = ulf.with_columns(UnifiedExpr(result_expr).alias("category")).collect()
        assert result["category"].to_list() == [
            "young",
            "young",
            "mature",
            "mature",
            "mature",
        ]

    def test_multi_branch_when_then(self, pl, ulf):
        """Chained when/then produces multi-branch CASE expression."""
        from benchbox.platforms.dataframe.unified_frame import (
            UnifiedExpr,
            UnifiedWhen,
        )

        # Build: CASE WHEN age < 30 THEN 'young'
        #             WHEN age < 40 THEN 'middle'
        #             ELSE 'senior'
        when_builder = UnifiedWhen(pl.when(pl.col("age") < 30), platform="Polars")
        when_then = when_builder.then(pl.lit("young"))
        when2 = when_then.when(UnifiedExpr(pl.col("age") < 40))
        when_then2 = when2.then(pl.lit("middle"))
        final = when_then2.otherwise(pl.lit("senior"))

        result = ulf.with_columns(final.alias("bracket")).collect()
        assert result["bracket"].to_list() == [
            "young",
            "middle",
            "middle",
            "senior",
            "senior",
        ]

    def test_when_then_with_unified_expr_value(self, pl, ulf):
        """when/then accepts UnifiedExpr as value."""
        from benchbox.platforms.dataframe.unified_frame import (
            UnifiedExpr,
            UnifiedWhen,
        )

        when_builder = UnifiedWhen(pl.when(pl.col("age") >= 35), platform="Polars")
        # Use UnifiedExpr as the then() value
        doubled_age = UnifiedExpr(pl.col("age") * 2)
        when_then = when_builder.then(doubled_age)
        final = when_then.otherwise(UnifiedExpr(pl.col("age")))
        result = ulf.with_columns(final.alias("adjusted")).collect()
        assert result["adjusted"].to_list() == [25, 30, 70, 80, 90]


# =========================================================================
# Set Operations: vstack (UNION ALL)
# =========================================================================


class TestVstack:
    """Tests for UnifiedLazyFrame.vstack() (UNION ALL)."""

    def test_vstack_combines_rows(self, pl):
        """vstack concatenates rows from two frames."""
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df1 = pl.DataFrame({"x": [1, 2], "y": ["a", "b"]}).lazy()
        df2 = pl.DataFrame({"x": [3, 4], "y": ["c", "d"]}).lazy()
        f1 = ULF(df1, adapter)
        f2 = ULF(df2, adapter)
        result = f1.vstack(f2).collect()
        assert result["x"].to_list() == [1, 2, 3, 4]
        assert result["y"].to_list() == ["a", "b", "c", "d"]

    def test_vstack_preserves_column_count(self, pl):
        """vstack result has same number of columns as inputs."""
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df1 = pl.DataFrame({"a": [1], "b": [2], "c": [3]}).lazy()
        df2 = pl.DataFrame({"a": [4], "b": [5], "c": [6]}).lazy()
        f1 = ULF(df1, adapter)
        f2 = ULF(df2, adapter)
        result = f1.vstack(f2).collect()
        assert len(result.columns) == 3
        assert len(result) == 2


# =========================================================================
# DISTINCT and LIMIT/OFFSET
# =========================================================================


class TestDistinct:
    """Tests for UnifiedLazyFrame.distinct() alias."""

    def test_distinct_removes_duplicates(self, pl):
        """distinct() removes duplicate rows."""
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"x": [1, 1, 2, 2, 3], "y": ["a", "a", "b", "b", "c"]}).lazy()
        frame = ULF(df, adapter)
        result = frame.distinct().collect()
        assert len(result) == 3
        assert sorted(result["x"].to_list()) == [1, 2, 3]


class TestLimitHead:
    """Tests for UnifiedLazyFrame.limit() and .head()."""

    def test_limit_returns_n_rows(self, pl, ulf):
        """limit(n) returns exactly n rows."""
        result = ulf.limit(3).collect()
        assert len(result) == 3

    def test_limit_preserves_order(self, pl, ulf):
        """limit(n) returns first n rows in original order."""
        result = ulf.limit(2).collect()
        assert result["name"].to_list() == ["Alice", "Bob"]

    def test_head_default_10(self, pl, ulf):
        """head() defaults to 10 rows (or fewer if frame is smaller)."""
        result = ulf.head().collect()
        assert len(result) == 5  # only 5 rows in fixture

    def test_head_with_arg(self, pl, ulf):
        """head(n) returns exactly n rows."""
        result = ulf.head(2).collect()
        assert len(result) == 2
        assert result["name"].to_list() == ["Alice", "Bob"]


# =========================================================================
# HAVING clause: group_by + agg + filter
# =========================================================================


class TestHavingClause:
    """Tests for HAVING-style filtering: group_by().agg() + .filter()."""

    def test_having_filters_groups(self, pl):
        """group_by + agg + filter simulates HAVING clause."""
        ULF = _get_unified_lazy_frame()
        expr_factory = _get_unified_expr()
        adapter = _create_mock_adapter()
        df = pl.DataFrame(
            {
                "dept": ["A", "A", "B", "B", "B", "C"],
                "salary": [50, 60, 40, 45, 55, 100],
            }
        ).lazy()
        frame = ULF(df, adapter)

        agg_result = frame.group_by("dept").agg(
            expr_factory(pl.col("salary").sum()).alias("total"),
            expr_factory(pl.col("salary").count()).alias("cnt"),
        )
        # HAVING cnt >= 2
        filtered = agg_result.filter(expr_factory(pl.col("cnt") >= 2))
        result = filtered.collect()
        depts = sorted(result["dept"].to_list())
        assert depts == ["A", "B"]

    def test_having_on_aggregated_value(self, pl):
        """HAVING can filter on aggregated values (e.g., total > 100)."""
        ULF = _get_unified_lazy_frame()
        expr_factory = _get_unified_expr()
        adapter = _create_mock_adapter()
        df = pl.DataFrame(
            {
                "dept": ["A", "A", "B", "B", "B"],
                "salary": [50, 60, 40, 45, 55],
            }
        ).lazy()
        frame = ULF(df, adapter)

        agg_result = frame.group_by("dept").agg(
            expr_factory(pl.col("salary").sum()).alias("total"),
        )
        # HAVING total > 115
        filtered = agg_result.filter(expr_factory(pl.col("total") > 115))
        result = filtered.collect()
        assert result["dept"].to_list() == ["B"]
        assert result["total"].to_list() == [140]


# =========================================================================
# Type Coercion
# =========================================================================


class TestTypeCasting:
    """Tests for type coercion edge cases."""

    def test_cast_int_to_float(self, pl, ulf):
        """cast_float64 converts integers to float."""
        expr_factory = _get_unified_expr()
        expr = expr_factory(pl.col("age")).cast_float64()
        result = ulf.with_columns(expr.alias("age_f")).collect()
        assert result["age_f"].dtype == pl.Float64
        assert result["age_f"].to_list() == [25.0, 30.0, 35.0, 40.0, 45.0]

    def test_cast_float_to_string(self, pl, ulf):
        """cast_string converts float to string representation."""
        expr_factory = _get_unified_expr()
        expr = expr_factory(pl.col("score")).cast_string()
        result = ulf.with_columns(expr.alias("score_s")).collect()
        assert result["score_s"].dtype == pl.Utf8
        assert result["score_s"].to_list()[0] == "88.5"

    def test_cast_float_alias(self, pl, ulf):
        """cast_float is an alias for cast_float64."""
        expr_factory = _get_unified_expr()
        expr = expr_factory(pl.col("age")).cast_float()
        result = ulf.with_columns(expr.alias("f")).collect()
        assert result["f"].dtype == pl.Float64

    def test_cast_int_alias(self, pl, ulf):
        """cast_int is an alias for cast_int32."""
        expr_factory = _get_unified_expr()
        expr = expr_factory(pl.col("score")).cast_int()
        result = ulf.with_columns(expr.alias("i")).collect()
        assert result["i"].dtype == pl.Int32


# =========================================================================
# Floor
# =========================================================================


class TestFloor:
    """Tests for UnifiedExpr.floor()."""

    def test_floor_rounds_down(self, pl, ulf):
        """floor() rounds floating point values down."""
        expr_factory = _get_unified_expr()
        expr = expr_factory(pl.col("score")).floor()
        result = ulf.with_columns(expr.alias("fl")).collect()
        assert result["fl"].to_list() == [88.0, 92.0, 75.0, 88.0, 95.0]


# =========================================================================
# Aggregation: std, var, quantile
# =========================================================================


class TestStatisticalAggregations:
    """Tests for std, var, quantile aggregations."""

    def test_std_on_column(self, pl):
        """std() computes standard deviation."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"v": [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("v")).std()
        result = frame.select(expr.alias("s")).collect()
        std_val = result["s"].to_list()[0]
        assert std_val == pytest.approx(2.138089935299395)

    def test_var_on_column(self, pl):
        """var() computes variance."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"v": [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("v")).var()
        result = frame.select(expr.alias("variance")).collect()
        var_val = result["variance"].to_list()[0]
        assert var_val == pytest.approx(4.571428571428571)

    def test_quantile_median(self, pl):
        """quantile(0.5) computes median."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"v": [1.0, 2.0, 3.0, 4.0, 5.0]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("v")).quantile(0.5)
        result = frame.select(expr.alias("median")).collect()
        median_val = result["median"].to_list()[0]
        assert median_val == 3.0


# =========================================================================
# Desc sort expression
# =========================================================================


class TestDescExpr:
    """Tests for UnifiedExpr.desc() sort marking."""

    def test_desc_sort_order(self, pl, ulf):
        """desc() used in sort produces descending order."""
        expr_factory = _get_unified_expr()
        desc_expr = expr_factory(pl.col("age")).desc()
        result = ulf.sort(desc_expr).collect()
        assert result["age"].to_list() == [45, 40, 35, 30, 25]


# =========================================================================
# Melt / Unpivot
# =========================================================================


class TestMelt:
    """Tests for UnifiedLazyFrame.melt()."""

    def test_melt_unpivots_columns(self, pl):
        """melt converts wide format to long format."""
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame(
            {
                "id": [1, 2],
                "q1": [10.0, 20.0],
                "q2": [30.0, 40.0],
            }
        ).lazy()
        frame = ULF(df, adapter)
        result = frame.melt(
            id_vars=["id"],
            value_vars=["q1", "q2"],
            variable_name="quarter",
            value_name="revenue",
        ).collect()
        assert len(result) == 4
        assert sorted(result["quarter"].unique().to_list()) == ["q1", "q2"]
        assert sorted(result["revenue"].to_list()) == [10.0, 20.0, 30.0, 40.0]


# =========================================================================
# Explode
# =========================================================================


class TestExplode:
    """Tests for UnifiedLazyFrame.explode()."""

    def test_explode_list_column(self, pl):
        """explode flattens list column into individual rows."""
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame(
            {
                "id": [1, 2],
                "items": [["a", "b"], ["c", "d", "e"]],
            }
        ).lazy()
        frame = ULF(df, adapter)
        result = frame.explode("items").collect()
        assert len(result) == 5
        assert result["items"].to_list() == ["a", "b", "c", "d", "e"]
        assert result["id"].to_list() == [1, 1, 2, 2, 2]


# =========================================================================
# Scalar
# =========================================================================


class TestScalar:
    """Tests for UnifiedLazyFrame.scalar()."""

    def test_scalar_extracts_single_value(self, pl):
        """scalar() extracts a single value from a one-row result."""
        ULF = _get_unified_lazy_frame()
        expr_factory = _get_unified_expr()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"x": [10, 20, 30]}).lazy()
        frame = ULF(df, adapter)
        result = frame.select(expr_factory(pl.col("x").sum()).alias("total"))
        val = result.scalar()
        assert val == 60

    def test_scalar_with_row_col_indices(self, pl):
        """scalar(row, col) extracts value at specified indices."""
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"a": [10, 20], "b": [30, 40]}).lazy()
        frame = ULF(df, adapter)
        assert frame.scalar(0, 0) == 10
        assert frame.scalar(0, 1) == 30
        assert frame.scalar(1, 0) == 20
        assert frame.scalar(1, 1) == 40


# =========================================================================
# Rename
# =========================================================================


class TestRename:
    """Tests for UnifiedLazyFrame.rename()."""

    def test_rename_single_column(self, pl, ulf):
        """rename() changes a column name."""
        result = ulf.rename({"name": "person"}).collect()
        assert "person" in result.columns
        assert "name" not in result.columns
        assert result["person"].to_list() == [
            "Alice",
            "Bob",
            "Charlie",
            "David",
            "Eve",
        ]

    def test_rename_multiple_columns(self, pl, ulf):
        """rename() changes multiple column names at once."""
        result = ulf.rename({"name": "person", "age": "years"}).collect()
        assert "person" in result.columns
        assert "years" in result.columns
        assert "name" not in result.columns
        assert "age" not in result.columns


# =========================================================================
# wrap_expr and wrap_dataframe helpers
# =========================================================================


class TestWrapHelpers:
    """Tests for wrap_expr() and wrap_dataframe() module functions."""

    def test_wrap_expr_wraps_native(self, pl):
        """wrap_expr wraps a native Polars expression."""
        from benchbox.platforms.dataframe.unified_frame import UnifiedExpr, wrap_expr

        native = pl.col("x")
        wrapped = wrap_expr(native)
        assert isinstance(wrapped, UnifiedExpr)
        assert wrapped.native is native

    def test_wrap_expr_passthrough_already_wrapped(self, pl):
        """wrap_expr returns same UnifiedExpr if already wrapped."""
        from benchbox.platforms.dataframe.unified_frame import UnifiedExpr, wrap_expr

        expr = UnifiedExpr(pl.col("x"))
        result = wrap_expr(expr)
        assert result is expr

    def test_wrap_dataframe_wraps_native(self, pl):
        """wrap_dataframe wraps a native Polars LazyFrame."""
        from benchbox.platforms.dataframe.unified_frame import (
            UnifiedLazyFrame,
            wrap_dataframe,
        )

        adapter = _create_mock_adapter()
        df = pl.DataFrame({"a": [1]}).lazy()
        wrapped = wrap_dataframe(df, adapter)
        assert isinstance(wrapped, UnifiedLazyFrame)
        assert wrapped.native is df


# =========================================================================
# Module-level type detection helpers
# =========================================================================


class TestTypeDetectionHelpers:
    """Tests for _is_polars_expr, _is_pyspark_column, etc."""

    def test_is_polars_expr_true(self, pl):
        """_is_polars_expr returns True for Polars expressions."""
        from benchbox.platforms.dataframe.unified_frame import _is_polars_expr

        expr = pl.col("x")
        assert _is_polars_expr(expr) is True

    def test_is_polars_expr_false_for_int(self):
        """_is_polars_expr returns False for non-Polars objects."""
        from benchbox.platforms.dataframe.unified_frame import _is_polars_expr

        assert _is_polars_expr(42) is False

    def test_is_pyspark_column_false_for_int(self):
        """_is_pyspark_column returns False for non-PySpark objects."""
        from benchbox.platforms.dataframe.unified_frame import _is_pyspark_column

        assert _is_pyspark_column(42) is False

    def test_is_polars_df_true(self, pl):
        """_is_polars_df returns True for Polars DataFrames."""
        from benchbox.platforms.dataframe.unified_frame import _is_polars_df

        df = pl.DataFrame({"a": [1]}).lazy()
        assert _is_polars_df(df) is True

    def test_is_polars_df_false_for_dict(self):
        """_is_polars_df returns False for non-DataFrame objects."""
        from benchbox.platforms.dataframe.unified_frame import _is_polars_df

        assert _is_polars_df({"a": 1}) is False

    def test_is_pyspark_df_false_for_dict(self):
        """_is_pyspark_df returns False for non-PySpark objects."""
        from benchbox.platforms.dataframe.unified_frame import _is_pyspark_df

        assert _is_pyspark_df({"a": 1}) is False

    def test_is_datafusion_df_false_for_dict(self):
        """_is_datafusion_df returns False for non-DataFusion objects."""
        from benchbox.platforms.dataframe.unified_frame import _is_datafusion_df

        assert _is_datafusion_df({"a": 1}) is False


# =========================================================================
# Cumulative operations
# =========================================================================


class TestCumulativeOps:
    """Tests for cum_sum, cum_max, cum_min on Polars."""

    def test_cum_sum(self, pl):
        """cum_sum() computes running sum."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"v": [1, 2, 3, 4, 5]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("v")).cum_sum()
        result = frame.with_columns(expr.alias("cs")).collect()
        assert result["cs"].to_list() == [1, 3, 6, 10, 15]

    def test_cum_max(self, pl):
        """cum_max() computes running maximum."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"v": [3, 1, 4, 1, 5]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("v")).cum_max()
        result = frame.with_columns(expr.alias("cm")).collect()
        assert result["cm"].to_list() == [3, 3, 4, 4, 5]

    def test_cum_min(self, pl):
        """cum_min() computes running minimum."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"v": [3, 1, 4, 1, 5]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("v")).cum_min()
        result = frame.with_columns(expr.alias("cm")).collect()
        assert result["cm"].to_list() == [3, 1, 1, 1, 1]


# =========================================================================
# UnifiedExpr.unique() in aggregation context
# =========================================================================


class TestExprUnique:
    """Tests for UnifiedExpr.unique() in aggregation context."""

    def test_unique_collects_distinct_values(self, pl):
        """unique() in agg context collects distinct values."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame(
            {
                "grp": ["A", "A", "A", "B", "B"],
                "val": [1, 2, 1, 3, 3],
            }
        ).lazy()
        frame = ULF(df, adapter)
        result = frame.group_by("grp").agg(expr_factory(pl.col("val")).unique().alias("uniques")).sort("grp").collect()
        uniques_a = sorted(result["uniques"].to_list()[0])
        uniques_b = sorted(result["uniques"].to_list()[1])
        assert uniques_a == [1, 2]
        assert uniques_b == [3]


# =========================================================================
# UnifiedExpr.sort() in aggregation context
# =========================================================================


class TestExprSort:
    """Tests for UnifiedExpr.sort() in aggregation context."""

    def test_sort_values_in_agg(self, pl):
        """sort() in agg context sorts collected values."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame(
            {
                "grp": ["A", "A", "A"],
                "val": [3, 1, 2],
            }
        ).lazy()
        frame = ULF(df, adapter)
        result = frame.group_by("grp").agg(expr_factory(pl.col("val")).sort().alias("sorted_vals")).collect()
        assert result["sorted_vals"].to_list()[0] == [1, 2, 3]


# =========================================================================
# UnifiedExpr.is_in() membership
# =========================================================================


class TestIsIn:
    """Tests for UnifiedExpr.is_in()."""

    def test_is_in_filters_matching_values(self, pl, ulf):
        """is_in() checks membership in a list of values."""
        expr_factory = _get_unified_expr()
        cond = expr_factory(pl.col("city")).is_in(["Boston", "Chicago"])
        result = ulf.filter(cond).collect()
        cities = sorted(result["city"].to_list())
        assert cities == ["Boston", "Boston", "Chicago"]


# =========================================================================
# UnifiedExpr.is_between()
# =========================================================================


class TestIsBetween:
    """Tests for UnifiedExpr.is_between()."""

    def test_is_between_inclusive(self, pl, ulf):
        """is_between checks inclusive range."""
        expr_factory = _get_unified_expr()
        cond = expr_factory(pl.col("age")).is_between(30, 40)
        result = ulf.filter(cond).collect()
        ages = result["age"].to_list()
        assert all(30 <= a <= 40 for a in ages)
        assert sorted(ages) == [30, 35, 40]


# =========================================================================
# Null handling
# =========================================================================


class TestNullHandling:
    """Tests for is_null, is_not_null, fill_null."""

    def test_fill_null_replaces_nulls(self, pl):
        """fill_null replaces null values with a default."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"x": [1, None, 3, None, 5]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("x")).fill_null(0)
        result = frame.with_columns(expr.alias("filled")).collect()
        assert result["filled"].to_list() == [1, 0, 3, 0, 5]

    def test_is_null_detection(self, pl):
        """is_null returns True for null values."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"x": [1, None, 3]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("x")).is_null()
        result = frame.with_columns(expr.alias("nulls")).collect()
        assert result["nulls"].to_list() == [False, True, False]

    def test_is_not_null_detection(self, pl):
        """is_not_null returns True for non-null values."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"x": [1, None, 3]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("x")).is_not_null()
        result = frame.with_columns(expr.alias("ok")).collect()
        assert result["ok"].to_list() == [True, False, True]


# =========================================================================
# UnifiedExpr.n_unique() count distinct
# =========================================================================


class TestNUnique:
    """Tests for UnifiedExpr.n_unique()."""

    def test_n_unique_counts_distinct(self, pl, ulf):
        """n_unique() counts distinct values in a column."""
        expr_factory = _get_unified_expr()
        expr = expr_factory(pl.col("city")).n_unique()
        result = ulf.select(expr.alias("cnt")).collect()
        assert result["cnt"].to_list() == [3]


# =========================================================================
# UnifiedExpr.first() and .last()
# =========================================================================


class TestFirstLast:
    """Tests for UnifiedExpr.first() and .last()."""

    def test_first_returns_first_value(self, pl, ulf):
        """first() returns the first value in the column."""
        expr_factory = _get_unified_expr()
        expr = expr_factory(pl.col("name")).first()
        result = ulf.select(expr.alias("f")).collect()
        assert result["f"].to_list() == ["Alice"]

    def test_last_returns_last_value(self, pl, ulf):
        """last() returns the last value in the column."""
        expr_factory = _get_unified_expr()
        expr = expr_factory(pl.col("name")).last()
        result = ulf.select(expr.alias("l")).collect()
        assert result["l"].to_list() == ["Eve"]


# =========================================================================
# UnifiedExpr repr
# =========================================================================


class TestUnifiedExprRepr:
    """Tests for UnifiedExpr.__repr__."""

    def test_repr_includes_class_name(self, pl):
        """__repr__ includes UnifiedExpr prefix."""
        expr_factory = _get_unified_expr()
        expr = expr_factory(pl.col("x"))
        r = repr(expr)
        assert r.startswith("UnifiedExpr(")

    def test_native_property(self, pl):
        """native property returns the underlying expression."""
        expr_factory = _get_unified_expr()
        native = pl.col("x")
        expr = expr_factory(native)
        assert expr.native is native


# =========================================================================
# Columns property
# =========================================================================


class TestColumnsProperty:
    """Tests for UnifiedLazyFrame.columns property."""

    def test_columns_returns_list(self, pl, ulf):
        """columns property returns list of column names."""
        cols = ulf.columns
        assert isinstance(cols, list)
        assert sorted(cols) == ["age", "city", "name", "score"]


# =========================================================================
# Group-by with list argument
# =========================================================================


class TestGroupByListArg:
    """Tests for group_by accepting a list argument."""

    def test_group_by_with_list(self, pl, ulf):
        """group_by accepts a list of column names."""
        expr_factory = _get_unified_expr()
        result = ulf.group_by(["city"]).agg(expr_factory(pl.col("age").mean()).alias("avg_age")).sort("city").collect()
        cities = result["city"].to_list()
        assert sorted(cities) == ["Boston", "Chicago", "New York"]


# =========================================================================
# Agg with list argument
# =========================================================================


class TestAggListArg:
    """Tests for agg() accepting a list of expressions."""

    def test_agg_with_list(self, pl, ulf):
        """agg accepts a list of expressions instead of *args."""
        expr_factory = _get_unified_expr()
        exprs = [
            expr_factory(pl.col("age").sum()).alias("total_age"),
            expr_factory(pl.col("age").count()).alias("cnt"),
        ]
        result = ulf.group_by("city").agg(exprs).sort("city").collect()
        assert "total_age" in result.columns
        assert "cnt" in result.columns


# =========================================================================
# Select with list argument
# =========================================================================


class TestSelectListArg:
    """Tests for select() accepting a list of columns."""

    def test_select_with_list(self, pl, ulf):
        """select accepts a list of column names."""
        result = ulf.select(["name", "age"]).collect()
        assert sorted(result.columns) == ["age", "name"]
        assert len(result) == 5


# =========================================================================
# With_columns with list argument
# =========================================================================


class TestWithColumnsListArg:
    """Tests for with_columns() accepting a list."""

    def test_with_columns_list(self, pl, ulf):
        """with_columns accepts a list of expressions."""
        expr_factory = _get_unified_expr()
        exprs = [
            expr_factory(pl.col("age") * 2).alias("double_age"),
            expr_factory(pl.col("score") + 1).alias("score_plus"),
        ]
        result = ulf.with_columns(exprs).collect()
        assert result["double_age"].to_list() == [50, 60, 70, 80, 90]
        assert result["score_plus"].to_list()[0] == 89.5


# =========================================================================
# Arithmetic operations completeness
# =========================================================================


class TestArithmeticOps:
    """Tests for arithmetic operations: mod, neg, comparison chaining."""

    def test_modulo_via_native(self, pl, ulf):
        """Modulo works via native expression wrapping."""
        expr_factory = _get_unified_expr()
        expr = expr_factory(pl.col("age") % 10)
        result = ulf.with_columns(expr.alias("mod10")).collect()
        assert result["mod10"].to_list() == [5, 0, 5, 0, 5]

    def test_or_operator(self, pl, ulf):
        """OR operator combines boolean conditions."""
        expr_factory = _get_unified_expr()
        cond = expr_factory(pl.col("age") < 30) | expr_factory(pl.col("age") > 40)
        result = ulf.filter(cond).collect()
        ages = sorted(result["age"].to_list())
        assert ages == [25, 45]

    def test_invert_operator(self, pl, ulf):
        """Invert (~) negates boolean expressions."""
        expr_factory = _get_unified_expr()
        cond = ~expr_factory(pl.col("age") < 35)
        result = ulf.filter(cond).collect()
        ages = sorted(result["age"].to_list())
        assert ages == [35, 40, 45]

    def test_ne_operator(self, pl, ulf):
        """Not-equal operator filters correctly."""
        expr_factory = _get_unified_expr()
        cond = expr_factory(pl.col("city")) != "Boston"
        result = ulf.filter(cond).collect()
        assert "Boston" not in result["city"].to_list()


# =========================================================================
# UnifiedListExpr methods
# =========================================================================


class TestUnifiedListExpr:
    """Tests for UnifiedListExpr methods on Polars."""

    def test_list_len(self, pl):
        """list.len() returns the length of each list."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"items": [[1, 2, 3], [4, 5], [6]]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("items")).list.len()
        result = frame.with_columns(expr.alias("n")).collect()
        assert result["n"].to_list() == [3, 2, 1]

    def test_list_sum(self, pl):
        """list.sum() sums all elements in each list."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"items": [[1, 2, 3], [4, 5], [6]]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("items")).list.sum()
        result = frame.with_columns(expr.alias("s")).collect()
        assert result["s"].to_list() == [6, 9, 6]

    def test_list_min(self, pl):
        """list.min() returns minimum from each list."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"items": [[3, 1, 2], [5, 4], [6]]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("items")).list.min()
        result = frame.with_columns(expr.alias("mn")).collect()
        assert result["mn"].to_list() == [1, 4, 6]

    def test_list_max(self, pl):
        """list.max() returns maximum from each list."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"items": [[3, 1, 2], [5, 4], [6]]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("items")).list.max()
        result = frame.with_columns(expr.alias("mx")).collect()
        assert result["mx"].to_list() == [3, 5, 6]

    def test_list_contains(self, pl):
        """list.contains() checks if element exists in list."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"items": [[1, 2, 3], [4, 5], [6, 1]]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("items")).list.contains(1)
        result = frame.with_columns(expr.alias("has1")).collect()
        assert result["has1"].to_list() == [True, False, True]

    def test_list_unique(self, pl):
        """list.unique() returns distinct elements from each list."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"items": [[1, 2, 1, 3], [4, 4, 5]]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("items")).list.unique()
        result = frame.with_columns(expr.alias("u")).collect()
        assert sorted(result["u"].to_list()[0]) == [1, 2, 3]
        assert sorted(result["u"].to_list()[1]) == [4, 5]

    def test_list_sort(self, pl):
        """list.sort() sorts elements in each list."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"items": [[3, 1, 2], [5, 4]]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("items")).list.sort()
        result = frame.with_columns(expr.alias("sorted")).collect()
        assert result["sorted"].to_list()[0] == [1, 2, 3]
        assert result["sorted"].to_list()[1] == [4, 5]

    def test_list_sort_descending(self, pl):
        """list.sort(descending=True) sorts in descending order."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"items": [[3, 1, 2]]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("items")).list.sort(descending=True)
        result = frame.with_columns(expr.alias("sorted")).collect()
        assert result["sorted"].to_list()[0] == [3, 2, 1]

    def test_list_slice(self, pl):
        """list.slice() extracts a sub-list."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"items": [[10, 20, 30, 40, 50]]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("items")).list.slice(1, 3)
        result = frame.with_columns(expr.alias("sliced")).collect()
        assert result["sliced"].to_list()[0] == [20, 30, 40]

    def test_list_get(self, pl):
        """list.get() returns element at index."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"items": [[10, 20, 30]]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("items")).list.get(1)
        result = frame.with_columns(expr.alias("second")).collect()
        assert result["second"].to_list() == [20]

    def test_list_eval(self, pl):
        """list.eval() evaluates an expression on each list element."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"items": [[1, 2, 3]]}).lazy()
        frame = ULF(df, adapter)
        # Double each element
        expr = expr_factory(pl.col("items")).list.eval(pl.element() * 2)
        result = frame.with_columns(expr.alias("doubled")).collect()
        assert result["doubled"].to_list()[0] == [2, 4, 6]

    def test_list_alias(self, pl):
        """UnifiedListExpr.alias() works for naming."""
        from benchbox.platforms.dataframe.unified_frame import UnifiedListExpr

        list_expr = UnifiedListExpr(pl.col("items").implode(), is_polars=True)
        aliased = list_expr.alias("result")
        # Should return a UnifiedExpr
        from benchbox.platforms.dataframe.unified_frame import UnifiedExpr

        assert isinstance(aliased, UnifiedExpr)

    def test_list_list_property_returns_self(self, pl):
        """UnifiedListExpr.list property returns self for chaining."""
        from benchbox.platforms.dataframe.unified_frame import UnifiedListExpr

        list_expr = UnifiedListExpr(pl.col("items"), is_polars=True)
        assert list_expr.list is list_expr


# =========================================================================
# UnifiedListExpr callable (list aggregation)
# =========================================================================


class TestUnifiedListExprCallable:
    """Tests for UnifiedListExpr.__call__() for list aggregation."""

    def test_list_aggregation(self, pl):
        """Calling UnifiedListExpr() collects values into a list."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame(
            {
                "grp": ["A", "A", "B", "B"],
                "val": [1, 2, 3, 4],
            }
        ).lazy()
        frame = ULF(df, adapter)
        result = frame.group_by("grp").agg(expr_factory(pl.col("val")).list().alias("vals")).sort("grp").collect()
        assert sorted(result["vals"].to_list()[0]) == [1, 2]
        assert sorted(result["vals"].to_list()[1]) == [3, 4]


# =========================================================================
# UnifiedExpr.rank() on Polars
# =========================================================================


class TestRank:
    """Tests for UnifiedExpr.rank() on Polars."""

    def test_rank_default(self, pl):
        """rank() assigns ranks within a column."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"v": [30, 10, 20]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("v")).rank(method="ordinal")
        result = frame.with_columns(expr.alias("rnk")).collect()
        # ordinal rank: 10=1, 20=2, 30=3
        ranks = result["rnk"].to_list()
        assert ranks == [3, 1, 2]

    def test_rank_descending(self, pl):
        """rank(descending=True) ranks in descending order."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"v": [30, 10, 20]}).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("v")).rank(method="ordinal", descending=True)
        result = frame.with_columns(expr.alias("rnk")).collect()
        ranks = result["rnk"].to_list()
        # descending ordinal: 30=1, 20=2, 10=3
        assert ranks == [1, 3, 2]


# =========================================================================
# UnifiedExpr.over() window
# =========================================================================


class TestOver:
    """Tests for UnifiedExpr.over() window partition."""

    def test_sum_over_partition(self, pl, ulf):
        """sum().over() computes partition sum."""
        expr_factory = _get_unified_expr()
        expr = expr_factory(pl.col("age")).sum().over("city")
        result = ulf.with_columns(expr.alias("city_total")).collect()
        # New York: 25+35=60, Boston: 30+45=75, Chicago: 40
        ny_idx = [i for i, c in enumerate(result["city"].to_list()) if c == "New York"]
        for i in ny_idx:
            assert result["city_total"].to_list()[i] == 60

    def test_over_with_list_partition(self, pl, ulf):
        """over() accepts a list of partition columns."""
        expr_factory = _get_unified_expr()
        expr = expr_factory(pl.col("score")).mean().over(["city"])
        result = ulf.with_columns(expr.alias("avg_score")).collect()
        # Boston average: (92.3+95.1)/2 = 93.7
        boston_idx = [i for i, c in enumerate(result["city"].to_list()) if c == "Boston"]
        for i in boston_idx:
            assert abs(result["avg_score"].to_list()[i] - 93.7) < 0.1


# =========================================================================
# UnifiedExpr.filter() for conditional aggregation
# =========================================================================


class TestConditionalAggregation:
    """Tests for UnifiedExpr.filter() + aggregation on Polars."""

    def test_filter_sum(self, pl):
        """filter() + sum() computes conditional sum."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame(
            {
                "type": ["A", "B", "A", "B", "A"],
                "amount": [10, 20, 30, 40, 50],
            }
        ).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("amount")).filter(expr_factory(pl.col("type") == "A")).sum()
        result = frame.select(expr.alias("a_total")).collect()
        assert result["a_total"].to_list() == [90]

    def test_filter_count(self, pl):
        """filter() + count() computes conditional count."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame(
            {
                "type": ["A", "B", "A", "B", "A"],
                "amount": [10, 20, 30, 40, 50],
            }
        ).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("amount")).filter(expr_factory(pl.col("type") == "B")).count()
        result = frame.select(expr.alias("b_cnt")).collect()
        assert result["b_cnt"].to_list() == [2]


# =========================================================================
# Struct operations
# =========================================================================


class TestStructExpr:
    """Tests for UnifiedStructExpr on Polars."""

    def test_struct_field_access(self, pl):
        """struct.field() accesses named field from struct column."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame(
            {
                "data": [
                    {"name": "Alice", "age": 25},
                    {"name": "Bob", "age": 30},
                ]
            }
        ).lazy()
        frame = ULF(df, adapter)
        expr = expr_factory(pl.col("data")).struct.field("name")
        result = frame.with_columns(expr.alias("person")).collect()
        assert result["person"].to_list() == ["Alice", "Bob"]


# =========================================================================
# UnifiedExpr.sort_by() in agg context
# =========================================================================


class TestSortBy:
    """Tests for UnifiedExpr.sort_by() in aggregation context."""

    def test_sort_by_column(self, pl):
        """sort_by sorts expression values by another column in agg."""
        expr_factory = _get_unified_expr()
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame(
            {
                "grp": ["A", "A", "A"],
                "rank": [3, 1, 2],
                "name": ["C", "A", "B"],
            }
        ).lazy()
        frame = ULF(df, adapter)
        result = frame.group_by("grp").agg(expr_factory(pl.col("name")).sort_by("rank").alias("sorted_names")).collect()
        assert result["sorted_names"].to_list()[0] == ["A", "B", "C"]


# =========================================================================
# DataFrame-level sum and mean
# =========================================================================


class TestFrameLevelAggregation:
    """Tests for UnifiedLazyFrame.sum() and .mean()."""

    def test_frame_sum_all_columns(self, pl):
        """Frame-level sum() sums all numeric columns."""
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]}).lazy()
        frame = ULF(df, adapter)
        result = frame.sum().collect()
        assert result["a"].to_list() == [6]
        assert result["b"].to_list() == [15]

    def test_frame_mean_all_columns(self, pl):
        """Frame-level mean() averages all numeric columns."""
        ULF = _get_unified_lazy_frame()
        adapter = _create_mock_adapter()
        df = pl.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]}).lazy()
        frame = ULF(df, adapter)
        result = frame.mean().collect()
        assert result["a"].to_list() == [2.0]
        assert result["b"].to_list() == [5.0]
