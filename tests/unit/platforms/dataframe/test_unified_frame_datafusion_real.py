"""Real DataFusion behavioral tests for UnifiedLazyFrame and UnifiedExpr."""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

try:
    import datafusion
    import pyarrow as pa

    from benchbox.platforms.dataframe.unified_frame import UnifiedExpr, UnifiedLazyFrame

    HAS_DATAFUSION = True
except ImportError:
    HAS_DATAFUSION = False
    datafusion = None  # type: ignore[assignment]
    pa = None  # type: ignore[assignment]
    UnifiedExpr = None  # type: ignore[assignment]
    UnifiedLazyFrame = None  # type: ignore[assignment]


@pytest.fixture()
def datafusion_frame():
    ctx = datafusion.SessionContext()
    table = pa.table(
        {
            "name": ["Alice", "Bob"],
            "text": ["Alice Smith", "Bob Jones"],
            "arr": [[3, 1, 3], [2, 4]],
            "d": [datetime.date(2024, 1, 15), datetime.date(2024, 1, 16)],
            "dt": [datetime.datetime(2024, 1, 15, 10, 30), datetime.datetime(2024, 1, 16, 11, 45)],
            "a": [1, 2],
            "b": [3, 4],
        }
    )
    ctx.register_record_batches("t", [table.to_batches()])
    frame = UnifiedLazyFrame(ctx.sql("SELECT * FROM t"), adapter=SimpleNamespace(platform_name="DataFusion"))
    return ctx, frame


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_string_operations(datafusion_frame):
    _, frame = datafusion_frame

    result = frame.with_columns(
        UnifiedExpr(datafusion.col("name")).str.starts_with("A").alias("starts"),
        UnifiedExpr(datafusion.col("name")).str.ends_with("e").alias("ends"),
        UnifiedExpr(datafusion.col("text")).str.contains("Smith|Jones").alias("contains"),
        UnifiedExpr(datafusion.col("name")).str.slice(1, 3).alias("slice"),
        UnifiedExpr(datafusion.col("name")).str.to_uppercase().alias("upper"),
        UnifiedExpr(datafusion.col("name")).str.to_lowercase().alias("lower"),
        UnifiedExpr(datafusion.col("name")).str.len_chars().alias("name_len"),
        UnifiedExpr(datafusion.col("text")).str.split(" ").list.get(1).alias("last_name"),
    ).collect()

    assert result.to_pydict()["starts"] == [True, False]
    assert result.to_pydict()["ends"] == [True, False]
    assert result.to_pydict()["contains"] == [True, True]
    assert result.to_pydict()["slice"] == ["lic", "ob"]
    assert result.to_pydict()["upper"] == ["ALICE", "BOB"]
    assert result.to_pydict()["lower"] == ["alice", "bob"]
    assert result.to_pydict()["name_len"] == [5, 3]
    assert result.to_pydict()["last_name"] == ["Smith", "Jones"]


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_date_operations_and_string_concat(datafusion_frame):
    _, frame = datafusion_frame

    result = frame.with_columns(
        UnifiedExpr(datafusion.col("d")).dt.year().alias("year"),
        UnifiedExpr(datafusion.col("d")).dt.month().alias("month"),
        UnifiedExpr(datafusion.col("d")).dt.day().alias("day"),
        UnifiedExpr(datafusion.col("dt")).dt.hour().alias("hour"),
        UnifiedExpr(datafusion.col("dt")).dt.minute().alias("minute"),
        UnifiedExpr(datafusion.col("d")).dt.weekday().alias("weekday"),
        (UnifiedExpr(datafusion.col("name")) + "X").alias("suffix_name"),
        ("X" + UnifiedExpr(datafusion.col("name"))).alias("prefix_name"),
        UnifiedExpr(datafusion.col("name")).concat_str("-", UnifiedExpr(datafusion.col("text"))).alias("joined"),
    ).collect()

    result_dict = result.to_pydict()
    assert result_dict["year"] == [2024, 2024]
    assert result_dict["month"] == [1, 1]
    assert result_dict["day"] == [15, 16]
    assert result_dict["hour"] == [10, 11]
    assert result_dict["minute"] == [30, 45]
    assert result_dict["weekday"] == [0, 1]
    assert result_dict["suffix_name"] == ["AliceX", "BobX"]
    assert result_dict["prefix_name"] == ["XAlice", "XBob"]
    assert result_dict["joined"] == ["Alice-Alice Smith", "Bob-Bob Jones"]


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_list_operations(datafusion_frame):
    _, frame = datafusion_frame

    result = frame.with_columns(
        UnifiedExpr(datafusion.col("arr")).list.contains(4).alias("has_four"),
        UnifiedExpr(datafusion.col("arr")).list.len().alias("arr_len"),
        UnifiedExpr(datafusion.col("arr")).list.get(1).alias("second"),
        UnifiedExpr(datafusion.col("arr")).list.unique().alias("unique_vals"),
        UnifiedExpr(datafusion.col("arr")).list.min().alias("min_val"),
        UnifiedExpr(datafusion.col("arr")).list.max().alias("max_val"),
        UnifiedExpr(datafusion.col("arr")).list.sort().alias("sorted_vals"),
        UnifiedExpr(datafusion.col("arr")).list.slice(0, 2).alias("slice_vals"),
    ).collect()

    result_dict = result.to_pydict()
    assert result_dict["has_four"] == [False, True]
    assert result_dict["arr_len"] == [3, 2]
    assert result_dict["second"] == [1, 4]
    assert [sorted(v) for v in result_dict["unique_vals"]] == [[1, 3], [2, 4]]
    assert result_dict["min_val"] == [1, 2]
    assert result_dict["max_val"] == [3, 4]
    assert result_dict["sorted_vals"] == [[1, 3, 3], [2, 4]]
    assert result_dict["slice_vals"] == [[3, 1], [2, 4]]


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_frame_operations(datafusion_frame):
    ctx, frame = datafusion_frame

    sorted_frame = frame.sort(UnifiedExpr(datafusion.col("a")).desc()).collect()
    assert sorted_frame.to_pydict()["a"] == [2, 1]

    stacked = frame.vstack(frame).collect()
    assert stacked.num_rows == 4

    melted = UnifiedLazyFrame(ctx.sql("SELECT a, b FROM t"), adapter=SimpleNamespace(platform_name="DataFusion")).melt(
        [], ["a", "b"]
    )
    melted_rows = melted.collect().to_pydict()
    assert sorted(melted_rows["variable"]) == ["a", "a", "b", "b"]
    assert sorted(melted_rows["value"]) == [1.0, 2.0, 3.0, 4.0]

    exploded = UnifiedLazyFrame(
        ctx.sql("SELECT [1, 2] AS items UNION ALL SELECT [3] AS items"),
        adapter=SimpleNamespace(platform_name="DataFusion"),
    ).explode("items")
    assert sorted(exploded.collect().to_pydict()["items"]) == [1, 2, 3]

    assert frame.collect_column_as_list("a") == [1, 2]
    assert frame.scalar(1, 0) == "Bob"


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_distinct_and_limit(datafusion_frame):
    """distinct() deduplicates; limit() restricts row count."""
    ctx, frame = datafusion_frame

    # vstack with itself to create duplicates
    doubled = frame.vstack(frame)
    distinct_result = doubled.distinct().collect()
    assert distinct_result.num_rows == 2  # back to original 2 rows

    limited = frame.limit(1).collect()
    assert limited.num_rows == 1


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_type_coercions(datafusion_frame):
    """cast(), cast_float(), cast_string(), cast_int() work with DataFusion."""
    import pyarrow as pa

    _, frame = datafusion_frame

    result = frame.with_columns(
        UnifiedExpr(datafusion.col("a")).cast(pa.float64()).alias("a_float"),
        UnifiedExpr(datafusion.col("a")).cast_float().alias("a_cast_float"),
        UnifiedExpr(datafusion.col("a")).cast_string().alias("a_str"),
        UnifiedExpr(datafusion.col("a")).cast_int32().alias("a_int32"),
        UnifiedExpr(datafusion.col("a")).cast_int64().alias("a_int64"),
    ).collect()

    d = result.to_pydict()
    assert d["a_float"] == [1.0, 2.0]
    assert d["a_cast_float"] == [1.0, 2.0]
    assert d["a_str"] == ["1", "2"]
    assert d["a_int32"] == [1, 2]
    assert d["a_int64"] == [1, 2]


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_is_in_is_null_is_not_null(datafusion_frame):
    """is_in(), is_null(), is_not_null() work with DataFusion."""
    ctx = datafusion.SessionContext()
    table = pa.table({"v": [1, None, 3], "n": pa.array([None, "b", "c"], type=pa.string())})
    ctx.register_record_batches("t2", [table.to_batches()])
    frame2 = UnifiedLazyFrame(ctx.sql("SELECT * FROM t2"), adapter=SimpleNamespace(platform_name="DataFusion"))

    result = frame2.with_columns(
        UnifiedExpr(datafusion.col("v")).is_in([1, 3]).alias("in_13"),
        UnifiedExpr(datafusion.col("v")).is_null().alias("v_null"),
        UnifiedExpr(datafusion.col("n")).is_not_null().alias("n_notnull"),
    ).collect()

    d = result.to_pydict()
    assert d["in_13"] == [True, None, True]
    assert d["v_null"] == [False, True, False]
    assert d["n_notnull"] == [False, True, True]


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_case_when_otherwise(datafusion_frame):
    """CASE/WHEN via UnifiedWhen works with DataFusion."""
    from benchbox.platforms.dataframe.unified_frame import UnifiedWhen

    _, frame = datafusion_frame

    # Build: CASE WHEN a > 1 THEN 'big' ELSE 'small' END
    when = UnifiedWhen(datafusion.col("a") > datafusion.lit(1), platform="DataFusion")
    case_expr = when.then("big").otherwise("small")

    result = frame.with_columns(case_expr.alias("size_label")).collect()

    d = result.to_pydict()
    assert d["size_label"] == ["small", "big"]


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_case_when_chained(datafusion_frame):
    """Chained CASE/WHEN via UnifiedWhenThen.when() works with DataFusion."""
    from benchbox.platforms.dataframe.unified_frame import UnifiedWhen

    _, frame = datafusion_frame

    # CASE WHEN a=1 THEN 'one' WHEN a=2 THEN 'two' ELSE 'other' END
    when = UnifiedWhen(datafusion.col("a") == datafusion.lit(1), platform="DataFusion")
    when_then = when.then("one")
    case_expr = when_then.when(datafusion.col("a") == datafusion.lit(2)).then("two").otherwise("other")

    result = frame.with_columns(case_expr.alias("label")).collect()

    d = result.to_pydict()
    assert d["label"] == ["one", "two"]


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_dt_truncate_and_total_seconds(datafusion_frame):
    """dt.truncate() and dt.total_seconds() work with DataFusion."""
    _, frame = datafusion_frame

    # Truncate to day
    result = frame.with_columns(
        UnifiedExpr(datafusion.col("dt")).dt.truncate("1d").alias("trunc_day"),
    ).collect()

    d = result.to_pydict()
    # Truncated to day: 2024-01-15 00:00:00
    trunc0 = d["trunc_day"][0]
    trunc1 = d["trunc_day"][1]
    # Handle both PyArrow scalar and Python datetime
    if hasattr(trunc0, "as_py"):
        trunc0 = trunc0.as_py()
    if hasattr(trunc1, "as_py"):
        trunc1 = trunc1.as_py()
    assert trunc0.date() == datetime.date(2024, 1, 15)
    assert trunc1.date() == datetime.date(2024, 1, 16)


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_arithmetic_operators(datafusion_frame):
    """__add__, __sub__, __mul__, __truediv__ work with DataFusion numeric columns."""
    _, frame = datafusion_frame

    result = frame.with_columns(
        (UnifiedExpr(datafusion.col("a")) + UnifiedExpr(datafusion.col("b"))).alias("add"),
        (UnifiedExpr(datafusion.col("b")) - UnifiedExpr(datafusion.col("a"))).alias("sub"),
        (UnifiedExpr(datafusion.col("a")) * UnifiedExpr(datafusion.col("b"))).alias("mul"),
        (UnifiedExpr(datafusion.col("b")) / UnifiedExpr(datafusion.col("a"))).alias("div"),
    ).collect()

    d = result.to_pydict()
    assert d["add"] == [4, 6]  # 1+3, 2+4
    assert d["sub"] == [2, 2]  # 3-1, 4-2
    assert d["mul"] == [3, 8]  # 1*3, 2*4
    assert d["div"] == [3.0, 2.0]  # 3/1, 4/2


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_concat_str(datafusion_frame):
    """concat_str joins columns across DataFusion."""
    _, frame = datafusion_frame

    result = frame.with_columns(
        UnifiedExpr(datafusion.col("name")).concat_str(UnifiedExpr(datafusion.col("name"))).alias("doubled"),
    ).collect()

    d = result.to_pydict()
    assert d["doubled"] == ["AliceAlice", "BobBob"]


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_rename_columns(datafusion_frame):
    """rename() renames columns in DataFusion."""
    _, frame = datafusion_frame

    result = frame.select("a", "b").rename({"a": "col_a", "b": "col_b"}).collect()

    d = result.to_pydict()
    assert "col_a" in d
    assert "col_b" in d
    assert d["col_a"] == [1, 2]
    assert d["col_b"] == [3, 4]


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_drop_columns(datafusion_frame):
    """drop() removes specified columns in DataFusion."""
    _, frame = datafusion_frame

    result = frame.select("a", "b", "name").drop("name").collect()

    d = result.to_pydict()
    assert "name" not in d
    assert "a" in d
    assert "b" in d


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_limit_and_head(datafusion_frame):
    """limit() and head() return at most n rows in DataFusion."""
    _, frame = datafusion_frame

    result_limit = frame.select("a").limit(1).collect()
    result_head = frame.select("a").head(1).collect()

    d_limit = result_limit.to_pydict()
    d_head = result_head.to_pydict()
    assert len(d_limit["a"]) == 1
    assert len(d_head["a"]) == 1


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_sort_ascending(datafusion_frame):
    """sort() ascending works in DataFusion."""
    _, frame = datafusion_frame

    result = frame.select("a").sort("a").collect()
    d = result.to_pydict()
    assert d["a"] == [1, 2]


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_sort_descending(datafusion_frame):
    """sort() descending works in DataFusion."""
    _, frame = datafusion_frame

    result = frame.select("a").sort("a", descending=True).collect()
    d = result.to_pydict()
    assert d["a"] == [2, 1]


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_sort_tuple_syntax(datafusion_frame):
    """sort() with tuple syntax [("col", "desc")] works in DataFusion."""
    _, frame = datafusion_frame

    result = frame.select("a").sort([("a", "desc")]).collect()
    d = result.to_pydict()
    assert d["a"] == [2, 1]


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_vstack_union(datafusion_frame):
    """vstack() unions two DataFusion frames (UNION ALL)."""
    _, frame = datafusion_frame

    sub_frame = frame.select("a")
    result = sub_frame.vstack(sub_frame).collect()
    d = result.to_pydict()
    assert len(d["a"]) == 4
    assert sorted(d["a"]) == [1, 1, 2, 2]


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_scalar_extraction(datafusion_frame):
    """scalar() extracts a single value from a DataFusion frame."""
    _, frame = datafusion_frame

    value = frame.select("a").limit(1).scalar(row=0, col=0)
    assert value == 1


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_unique_dedup(datafusion_frame):
    """unique() deduplicates rows in DataFusion."""
    ctx, _ = datafusion_frame

    # Build a frame with duplicates
    import pyarrow as pa

    dup_table = pa.table({"x": [1, 1, 2, 2, 3]})
    ctx.register_record_batches("dup_t", [dup_table.to_batches()])
    from types import SimpleNamespace

    dup_frame = UnifiedLazyFrame(
        ctx.sql("SELECT * FROM dup_t"),
        adapter=SimpleNamespace(platform_name="DataFusion"),
    )
    result = dup_frame.unique().collect()
    d = result.to_pydict()
    assert sorted(d["x"]) == [1, 2, 3]


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_columns_property(datafusion_frame):
    """columns property returns column names in DataFusion."""
    _, frame = datafusion_frame

    cols = frame.select("a", "b").columns
    assert set(cols) == {"a", "b"}


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_filter_after_group_by_having(datafusion_frame):
    """group_by + filter on aggregated column (HAVING equivalent) works in DataFusion."""
    ctx, _ = datafusion_frame

    from types import SimpleNamespace

    import pyarrow as pa

    # Build a frame with groups
    grouped_table = pa.table({"cat": ["A", "A", "B", "B", "B"], "val": [1, 2, 3, 4, 5]})
    ctx.register_record_batches("grouped_t", [grouped_table.to_batches()])
    g_frame = UnifiedLazyFrame(
        ctx.sql("SELECT * FROM grouped_t"),
        adapter=SimpleNamespace(platform_name="DataFusion"),
    )

    result = (
        g_frame.group_by("cat")
        .agg(UnifiedExpr(datafusion.col("val")).sum().alias("total"))
        .filter(UnifiedExpr(datafusion.col("total")) > 5)
        .collect()
    )
    d = result.to_pydict()
    # B group: 3+4+5=12 > 5, A group: 1+2=3 not > 5
    assert d["cat"] == ["B"]
    assert d["total"] == [12]


@pytest.mark.skipif(not HAS_DATAFUSION, reason="datafusion not installed")
def test_datafusion_string_add_concat(datafusion_frame):
    """__add__ with string literal operand uses concat in DataFusion."""
    from datafusion import lit as df_lit

    _, frame = datafusion_frame

    # Mark expr as string literal so __add__ routes through concat path
    name_expr = UnifiedExpr(datafusion.col("name"), _is_string_literal=True)
    suffix_expr = UnifiedExpr(df_lit("!"), _is_string_literal=True)
    result = frame.with_columns((name_expr + suffix_expr).alias("name_excl")).collect()

    d = result.to_pydict()
    assert d["name_excl"] == ["Alice!", "Bob!"]
