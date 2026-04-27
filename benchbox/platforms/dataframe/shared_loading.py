"""Shared data-loading logic for DataFrame platform families."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LoadableAdapter(Protocol):
    """Contract required by :func:`load_tables_from_data_source_impl`.

    Both DataFrame family base classes and the SQL
    :class:`~benchbox.platforms.base.adapter.PlatformAdapter` satisfy this
    protocol.
    """

    platform_name: str
    table_mode: str
    platform_config: dict[str, Any]

    def load_table(
        self,
        ctx: Any,
        table_name: str,
        files: list[Path],
        column_names: list[str] | None = None,
        *,
        format_hint: str | None = None,
    ) -> int: ...
    def _log_verbose(self, msg: str) -> None: ...


def load_tables_from_data_source_impl(
    adapter: LoadableAdapter,
    ctx: Any,
    data_dir: Path,
    schema_info: dict[str, dict] | None = None,
) -> dict[str, int]:
    """Shared implementation for ``load_tables_from_data_source``.

    Both :class:`ExpressionFamilyAdapter` and :class:`PandasFamilyAdapter`
    have identical loading logic. This function centralises it so that each
    adapter delegates with a single call.

    Args:
        adapter: The adapter instance (must satisfy :class:`LoadableAdapter`).
        ctx: The family-specific context with registered tables.
        data_dir: Directory containing data files.
        schema_info: Optional schema information with column names.

    Returns:
        Dictionary mapping table name to row count.
    """
    from benchbox.platforms.base.data_loading import DataSource, DataSourceResolver

    resolver = DataSourceResolver(
        platform_name=adapter.platform_name,
        table_mode=adapter.table_mode,
        platform_config=adapter.platform_config,
        requested_format=getattr(adapter, "requested_table_format", None),
    )

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

        table_formats = getattr(data_source, "table_formats", {}) or {}
        format_hint = table_formats.get(table_name) or table_formats.get(table_name.lower())
        # Only pass a proper DataSource so load_table can call resolve_csv_dialect safely.
        # No real benchmark is available here; NO_BENCHMARK is used inside load_table() as a
        # fallback.  That is intentional: when table_metadata is absent, resolve_csv_dialect()
        # falls through to path (c) which derives the correct null_marker from the file extension
        # (.tbl/.dat → null_marker="", everything else → None).
        typed_ds = data_source if isinstance(data_source, DataSource) else None
        row_count = adapter.load_table(
            ctx,
            table_name.lower(),
            valid_files,
            column_names,
            format_hint=format_hint,
            data_source=typed_ds,
        )
        table_stats[table_name.lower()] = row_count

    return table_stats
