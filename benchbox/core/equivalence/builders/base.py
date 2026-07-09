"""Shared helpers for cross-surface gate builders."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CrossSurfaceData:
    """Everything the gate needs to compare a benchmark's two surfaces.

    Returned by a benchmark's ``build`` function on a freshly generated, loaded
    DuckDB cell. ``reference_sql`` and ``dataframe_query`` are keyed by the SAME
    query id (the two surfaces are confirmed to correspond 1:1).
    """

    connection: Any
    query_ids: Sequence[Any]
    reference_sql: Callable[[Any], str]
    dataframe_query: Callable[[Any], Any]
    # The benchmark instance + the directory its data was generated into. The
    # DataFrame surface is loaded from these via the real production loader,
    # reading the SAME generated files the DuckDB SQL reference loaded, so the
    # comparison stays a single bounded cell.
    benchmark: Any
    data_dir: Path


def _load_duckdb_cell(benchmark: Any, output_dir: Path, table_names: Sequence[str], *, label: str) -> Any:
    """Create an in-memory DuckDB, build the schema, load the data, and verify it."""
    import duckdb

    from benchbox.platforms.duckdb import DuckDBAdapter

    connection = duckdb.connect(":memory:")
    try:
        for statement in benchmark.get_create_tables_sql(dialect="duckdb").strip().split(";"):
            if statement.strip():
                connection.execute(statement.strip())
        table_stats, _, _ = DuckDBAdapter(database=":memory:").load_data(benchmark, connection, Path(output_dir))

        stats_lower = {str(name).lower(): rows for name, rows in table_stats.items()}
        empty = [name for name in table_names if stats_lower.get(name.lower(), 0) <= 0]
        if empty:
            raise RuntimeError(f"{label} load failed - no rows in {empty} (stats={table_stats})")
    except Exception:
        connection.close()
        raise
    return connection
