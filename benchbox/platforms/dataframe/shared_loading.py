"""Shared data-loading logic for DataFrame platform families."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_tables_from_data_source_impl(
    adapter: Any,
    ctx: Any,
    data_dir: Path,
    schema_info: dict[str, dict] | None = None,
) -> dict[str, int]:
    """Shared implementation for ``load_tables_from_data_source``.

    Both :class:`ExpressionFamilyAdapter` and :class:`PandasFamilyAdapter`
    have identical loading logic. This function centralises it so that each
    adapter delegates with a single call.

    Args:
        adapter: The adapter instance (must expose ``load_table`` and
            ``_log_verbose``).
        ctx: The family-specific context with registered tables.
        data_dir: Directory containing data files.
        schema_info: Optional schema information with column names.

    Returns:
        Dictionary mapping table name to row count.
    """
    from benchbox.platforms.base.data_loading import DataSourceResolver

    resolver = DataSourceResolver()

    class MinimalBenchmark:
        tables: dict = {}

    benchmark = MinimalBenchmark()
    data_source = resolver.resolve(benchmark, data_dir)

    if not data_source or not data_source.tables:
        raise ValueError(f"No data files found in {data_dir}")

    table_stats: dict[str, int] = {}
    for table_name, file_paths in data_source.tables.items():
        valid_files = [Path(f) if not isinstance(f, Path) else f for f in file_paths]
        valid_files = [f for f in valid_files if f.exists()]

        if not valid_files:
            adapter._log_verbose(f"Skipping {table_name} - no valid data files")
            continue

        column_names = None
        if schema_info and table_name.lower() in schema_info:
            columns = schema_info[table_name.lower()].get("columns", [])
            column_names = [col["name"] for col in columns if "name" in col]

        row_count = adapter.load_table(ctx, table_name.lower(), valid_files, column_names)
        table_stats[table_name.lower()] = row_count

    return table_stats
