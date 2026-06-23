"""Shared data-loading logic for DataFrame platform families."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from benchbox.core.dataframe.schema_utils import column_name, iter_schema_columns


def schema_column_types(
    benchmark: Any,
    table_name: str,
    column_names: list[str] | None,
) -> list[str | None] | None:
    """Return the SQL types parallel to ``column_names`` from the benchmark schema.

    Returns ``None`` (so the caller falls back to name-only heuristics) when the
    benchmark, its schema, or this table's columns are unavailable. Per-column
    entries are ``None`` when a type is unknown; only columns with a known type
    are acted on downstream (date-vs-numeric disambiguation, declared-string
    empty-field handling). Shared by every DataFrame family so the pandas-family
    and expression-family (polars) CSV loaders derive identical column types.
    """
    if benchmark is None or not column_names:
        return None
    try:
        from benchbox.core.dataframe.schema_utils import get_benchmark_schema_columns

        schema = get_benchmark_schema_columns(benchmark)
    except Exception:  # noqa: BLE001 - a schema lookup must never break data loading
        return None
    if not schema:
        return None
    columns = schema.get(table_name)
    if columns is None:
        lowered = {key.lower(): value for key, value in schema.items()}
        columns = lowered.get(table_name.lower())
    if not columns:
        return None
    type_by_name = {column.get("name", "").lower(): column.get("type") for column in columns}
    return [type_by_name.get(name.lower()) for name in column_names]


def declared_string_columns(
    names: list[str] | None,
    column_types: list[str] | None,
    exclude: set[str] | None = None,
) -> list[str]:
    """Return the columns (parallel ``names``/``column_types``) declared as text.

    A column whose declared SQL type maps to the Arrow ``string`` family
    (VARCHAR, CHAR, TEXT, ...) must be read as text and have empty CSV fields
    preserved as ``""`` rather than coerced to null - matching the DuckDB SQL
    reference and the Parquet load path (``strings_can_be_null=False``). This is
    the single source of truth for the w1 empty-string contract shared by every
    raw-CSV adapter (pandas, modin, dask, cuDF, polars); the classification reuses
    :meth:`SchemaMapper.sql_type_to_pyarrow` so every surface agrees on what a
    string column is. Columns in ``exclude`` (e.g. already handled as dates) are
    skipped; returns ``[]`` when types are absent or misaligned (so the caller
    falls back to inference, keeping behavior additive).
    """
    if not names or not column_types or len(column_types) != len(names):
        return []
    from benchbox.core.dataframe.data_loader import SchemaMapper

    skip = exclude or set()
    string_columns: list[str] = []
    for name, sql_type in zip(names, column_types):
        if name in skip or not sql_type:
            continue
        if SchemaMapper.sql_type_to_pyarrow(str(sql_type)) == "string":
            string_columns.append(name)
    return string_columns


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
    schema_info: dict[str, Any] | None = None,
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
            columns = iter_schema_columns(schema_info[table_name.lower()])
            column_names = [name for column in columns if (name := column_name(column))]

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
