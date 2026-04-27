"""Unit tests for PlatformAdapter query skip filtering.

Ensures that:
1. SQL mode (PlatformAdapter) only consumes get_platform_skip_queries.
2. DataFusion SQL keeps variants that were previously dropped by a conflated skip list.
3. LakeSail SQL skip remains effective.
4. DataFrame mode consumes both get_platform_skip_queries and get_df_platform_skip_queries.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from benchbox.core.read_primitives.benchmark import ReadPrimitivesBenchmark
from benchbox.platforms.base.adapter import PlatformAdapter
from benchbox.platforms.dataframe.benchmark_mixin import BenchmarkExecutionMixin

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class MinimalAdapter(PlatformAdapter):
    """Minimal concrete implementation of PlatformAdapter for testing."""

    def __init__(self, platform_name: str) -> None:
        self._platform_name = platform_name
        super().__init__()

    @property
    def platform_name(self) -> str:
        return self._platform_name

    def get_target_dialect(self) -> str | None:
        return self._platform_name.lower()

    @staticmethod
    def add_cli_arguments(parser: Any) -> None:
        pass

    @classmethod
    def from_config(cls, config: Any) -> MinimalAdapter:
        return cls("test")

    def create_connection(self, **kwargs: Any) -> Any:
        return None

    def create_schema(self, benchmark: Any, connection: Any) -> float:
        return 0.0

    def load_data(self, benchmark: Any, connection: Any, data_dir: str) -> tuple[dict, float, Any]:
        return {}, 0.0, None

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        pass

    def apply_platform_optimizations(self, platform_config: Any, connection: Any) -> None:
        pass

    def apply_constraint_configuration(
        self,
        primary_key_config: Any,
        foreign_key_config: Any,
        connection: Any,
    ) -> None:
        pass

    def execute_query(
        self,
        connection: Any,
        query: str,
        query_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {"query_id": query_id, "status": "SUCCESS", "execution_time_seconds": 0.0, "rows_returned": 0}


class MinimalDFAdapter(BenchmarkExecutionMixin):
    """Minimal concrete implementation of BenchmarkExecutionMixin for testing."""

    def __init__(self, platform_name: str, family: str = "expression") -> None:
        self.platform_name = platform_name
        self.family = family

    def create_context(self) -> Any:
        return SimpleNamespace()

    def load_table(self, ctx: Any, table_name: str, file_paths: list, **kwargs: Any) -> int:
        return 0

    def execute_query(self, ctx: Any, query: Any, query_id: str | None = None) -> dict[str, Any]:
        return {"query_id": query_id, "status": "SUCCESS"}

    def get_platform_info(self) -> dict[str, Any]:
        return {"platform": self.platform_name}


def test_datafusion_sql_keeps_variants():
    """Regression test: DataFusion SQL must NOT skip its catalog variants."""
    adapter = MinimalAdapter("DataFusion")
    benchmark = ReadPrimitivesBenchmark()

    # The four query IDs that were previously incorrectly skipped in SQL mode
    target_ids = ["list_filter", "list_transform", "list_reduce", "array_distinct"]

    # Mock queries dict as it would come from benchmark.get_queries(dialect='datafusion')
    queries = {qid: f"SELECT * FROM {qid}" for qid in target_ids}
    queries["q1"] = "SELECT 1"

    # Filter through the adapter
    filtered = adapter._filter_queries(queries, benchmark, "read_primitives", {})

    # All target IDs must survive in SQL mode
    for qid in target_ids:
        assert qid in filtered, f"{qid} should NOT be skipped in DataFusion SQL mode"
    assert "q1" in filtered


def test_lakesail_sql_skip_remains_active():
    """LakeSail SQL skip (empty_build_join) must still work in generic hook."""
    adapter = MinimalAdapter("LakeSail")
    benchmark = ReadPrimitivesBenchmark()

    queries = {"empty_build_join": "SELECT *", "q1": "SELECT 1"}
    filtered = adapter._filter_queries(queries, benchmark, "read_primitives", {})

    assert "empty_build_join" not in filtered, "LakeSail must still skip empty_build_join in SQL mode"
    assert "q1" in filtered


def test_datafusion_df_skips_continue_to_work():
    """DataFusion DataFrame mode must still skip its unsupported queries."""
    adapter = MinimalDFAdapter("DataFusion")
    benchmark = ReadPrimitivesBenchmark()

    # In DF mode, these ARE skipped via get_df_platform_skip_queries
    target_ids = ["list_filter", "list_transform", "list_reduce", "array_distinct"]

    skip_ids = adapter._collect_skip_query_ids(benchmark)
    # _collect_skip_query_ids returns uppercase
    upper_targets = {qid.upper() for qid in target_ids}

    for qid in upper_targets:
        assert qid in skip_ids, f"{qid} should be skipped in DataFusion DataFrame mode"


def test_polars_df_skips_maps():
    """Polars DataFrame mode must skip map queries."""
    adapter = MinimalDFAdapter("Polars")
    benchmark = ReadPrimitivesBenchmark()

    target_ids = ["map_construction", "map_access", "map_keys_values"]
    skip_ids = adapter._collect_skip_query_ids(benchmark)

    for qid in target_ids:
        assert qid.upper() in skip_ids, f"{qid} should be skipped in Polars DataFrame mode"


def test_pyspark_df_skips_list_hofs():
    """PySpark DataFrame mode must skip list higher-order functions."""
    adapter = MinimalDFAdapter("PySpark")
    benchmark = ReadPrimitivesBenchmark()

    target_ids = ["list_filter", "list_transform"]
    skip_ids = adapter._collect_skip_query_ids(benchmark)

    for qid in target_ids:
        assert qid.upper() in skip_ids, f"{qid} should be skipped in PySpark DataFrame mode"

    # PySpark should NOT skip maps anymore as they were moved to Polars bucket
    assert "MAP_CONSTRUCTION" not in skip_ids, "PySpark should support map_construction"


def test_datafusion_df_does_not_skip_maps():
    """DataFusion DataFrame mode should support maps."""
    adapter = MinimalDFAdapter("DataFusion")
    benchmark = ReadPrimitivesBenchmark()

    skip_ids = adapter._collect_skip_query_ids(benchmark)
    assert "MAP_CONSTRUCTION" not in skip_ids, "DataFusion should support map_construction"
