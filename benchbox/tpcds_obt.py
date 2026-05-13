"""TPC-DS One Big Table benchmark wrapper."""

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.tpcds_obt.benchmark import TPCDSOBTBenchmark


class TPCDSOBT(BaseBenchmark):
    """Public API wrapper for the TPC-DS OBT benchmark."""

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> None:
        if scale_factor < 1.0:
            raise ValueError("TPC-DS-OBT requires scale_factor >= 1.0 to align with TPC-DS generation.")
        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)
        self._initialize_benchmark_implementation(
            TPCDSOBTBenchmark,
            scale_factor,
            output_dir,
            **kwargs,
        )

    def generate_data(self) -> dict[str, Any]:
        """Generate the single OBT table and manifest."""
        return self._impl.generate_data()

    def get_queries(self, dialect: Optional[str] = None, base_dialect: Optional[str] = None) -> dict[str, str]:
        """Return all OBT queries (translation hook reserved for future dialect support)."""
        return self._impl.get_queries(dialect=dialect)

    def get_query(self, query_id: Union[int, str], **kwargs: Any) -> str:
        """Return a single OBT query."""
        return self._impl.get_query(query_id, **kwargs)

    def get_schema(self) -> dict[str, Any]:
        """Return schema metadata for the single OBT table."""
        return self._impl.get_schema()

    def get_create_tables_sql(self, dialect: Optional[str] = None) -> str:
        """Return DDL for the OBT table."""
        return self._impl.get_create_tables_sql(dialect=dialect or "duckdb")
