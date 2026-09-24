"""Session-backed branch tests for PySparkDataFrameAdapter miss clusters.

Exercises the paths that mocked fast tests cannot reach against a real
local Spark session: the TPC-style trailing-delimiter CSV branch with
empty-string restore, COUNT(*) windows, to_polars conversion, and the
version-reporting branch of get_platform_info.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import sys

import pytest

from benchbox.platforms.pyspark import (
    PYSPARK_AVAILABLE,
    ensure_compatible_java,
    get_java_skip_reason,
    is_java_compatible,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
    pytest.mark.skipif(
        sys.platform == "win32",
        reason="PySpark tests skipped on Windows - Hadoop requires winutils.exe setup",
    ),
]

_java_version, _java_home = ensure_compatible_java()
_SKIP_PYSPARK = not PYSPARK_AVAILABLE or not is_java_compatible(_java_version)
_SKIP_REASON = get_java_skip_reason() or "PySpark tests enabled"

if PYSPARK_AVAILABLE:
    from benchbox.platforms.dataframe.pyspark_df import PySparkDataFrameAdapter
else:
    PySparkDataFrameAdapter = None  # type: ignore[assignment,misc]


@pytest.mark.skipif(_SKIP_PYSPARK, reason=_SKIP_REASON)
class TestPySparkSessionBranches:
    """Real-session coverage for trailing-delimiter CSV, COUNT(*), to_polars."""

    @pytest.fixture(scope="class")
    def adapter(self):
        adapter = PySparkDataFrameAdapter(
            master="local[2]",
            app_name="BenchBox-Branch-Tests",
            driver_memory="1g",
            shuffle_partitions=2,
            verbose=False,
        )
        yield adapter
        adapter.close()

    def test_read_csv_trailing_delimiter_drops_dummy(self, adapter, tmp_path):
        """TPC-style rows ending with a spurious delimiter lose the dummy column."""
        csv_path = tmp_path / "region.tbl"
        csv_path.write_text("r_regionkey|r_name|\n1|AFRICA|\n2|AMERICA|\n")

        df = adapter.read_csv(
            csv_path,
            delimiter="|",
            has_header=True,
            column_names=["r_regionkey", "r_name"],
            null_marker="NULL",
        )

        assert df.columns == ["r_regionkey", "r_name"]
        assert adapter.get_row_count(df) == 2

    def test_read_csv_restores_empty_strings(self, adapter, tmp_path):
        """Empty fields in declared string columns come back as ''."""
        csv_path = tmp_path / "strings.tbl"
        csv_path.write_text("a|b|\n1|x|\n2||\n")

        df = adapter.read_csv(
            csv_path,
            delimiter="|",
            has_header=True,
            column_names=["a", "b"],
            null_marker="NULL",
            string_columns=["b"],
        )

        rows = sorted((r["a"], r["b"]) for r in df.collect())
        assert rows == [("1", "x"), ("2", "")]

    def test_window_count_star(self, adapter):
        """COUNT(*) windows count every row in the partition."""
        df = adapter.spark.createDataFrame([(1, "x"), (1, "y"), (2, "z")], ["g", "v"])
        expr = adapter.window_count(None, partition_by=["g"])
        out = sorted(r["n"] for r in df.withColumn("n", expr).collect())
        assert out == [1, 2, 2]

    def test_to_polars_via_arrow(self, adapter):
        """Spark 4 toArrow() path converts without touching pandas."""
        pl = pytest.importorskip("polars")
        df = adapter.spark.createDataFrame([(1, "a"), (2, "b")], ["id", "name"])
        out = adapter.to_polars(df)
        assert isinstance(out, pl.DataFrame)
        assert out.sort("id").to_dicts() == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]

    def test_get_platform_info_reports_version(self, adapter):
        """Version branch reports the module-level PySpark version."""
        from benchbox.platforms.pyspark import PYSPARK_VERSION

        assert adapter.get_platform_info()["version"] == PYSPARK_VERSION
