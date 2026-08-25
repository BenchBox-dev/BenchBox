"""Shared data-loading logic for DataFrame platform families."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Protocol, runtime_checkable

from benchbox.core.dataframe.schema_utils import (
    column_name,
    column_sql_type,
    get_benchmark_schema_columns,
    iter_schema_columns,
)


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


def resolve_dataframe_csv_dialect(
    *,
    data_source: Any | None,
    table_name: str,
    first_file: Path,
    benchmark: Any | None,
    format_type: str,
    default_has_header: bool,
) -> tuple[str | None, bool]:
    """Resolve CSV null/header semantics for DataFrame direct CSV loads.

    This mirrors the SQL loader's dialect resolver whenever a manifest or
    benchmark instance is available. Only ad-hoc loads with neither input fall
    back to the historical file-extension heuristic.
    """
    if data_source is not None:
        from benchbox.platforms.base.data_loading import NO_BENCHMARK, resolve_csv_dialect

        bm = benchmark if benchmark is not None else NO_BENCHMARK
        dialect = resolve_csv_dialect(data_source, table_name, first_file, bm)
        return dialect.null_marker, dialect.has_header

    if benchmark is not None:
        from benchbox.platforms.base.data_loading import DataSource, resolve_csv_dialect

        dialect = resolve_csv_dialect(
            DataSource(source_type="benchmark_instance", tables={}),
            table_name,
            first_file,
            benchmark,
        )
        return dialect.null_marker, dialect.has_header

    return ("" if format_type == "tbl" else None), default_has_header


def _declared_column_types(
    benchmark: Any | None,
    table_name: str,
    column_names: list[str] | None,
) -> dict[str, str]:
    """Return declared SQL types keyed by the requested column names."""
    if benchmark is None or not column_names:
        return {}

    try:
        schema = get_benchmark_schema_columns(benchmark)
    except Exception:  # noqa: BLE001 - schema hooks are heterogeneous across benchmarks
        return {}

    table_schema = schema.get(table_name.lower()) or schema.get(table_name)
    if not table_schema:
        return {}

    types_by_name: dict[str, str] = {}
    columns = list(table_schema) if isinstance(table_schema, (list, tuple)) else iter_schema_columns(table_schema)
    for column in columns:
        name = column_name(column)
        if name:
            types_by_name[name.lower()] = column_sql_type(column, default="")
    return {name: sql_type for name in column_names if (sql_type := types_by_name.get(name.lower()))}


def declared_string_columns(
    benchmark: Any | None,
    table_name: str,
    column_names: list[str] | None,
) -> list[str]:
    """Return declared string/text columns for a benchmark table."""
    from benchbox.core.dataframe.data_loader import SchemaMapper

    return [
        name
        for name, sql_type in _declared_column_types(benchmark, table_name, column_names).items()
        if SchemaMapper.sql_type_to_pyarrow(sql_type) == "string"
    ]


def declared_temporal_columns(
    benchmark: Any | None,
    table_name: str,
    column_names: list[str] | None,
) -> dict[str, str]:
    """Return declared date/timestamp columns and their normalized Arrow types."""
    from benchbox.core.dataframe.data_loader import SchemaMapper

    temporal_columns: dict[str, str] = {}
    for name, sql_type in _declared_column_types(benchmark, table_name, column_names).items():
        normalized_type = SchemaMapper.sql_type_to_pyarrow(sql_type)
        if normalized_type in {"date32", "timestamp[us]"}:
            temporal_columns[name] = normalized_type
    return temporal_columns


def resolve_empty_string_restore_columns(
    string_columns: list[str] | None,
    null_marker: str | None,
    available_columns: Iterable[str],
) -> list[str]:
    """Return declared string columns whose empty CSV fields must be restored to ``""``.

    This is the single shared decision step behind every DataFrame adapter's
    empty-string/null CSV coercion: ``null_marker is None`` means the resolved
    CSV dialect keeps empty fields as empty strings (e.g. ClickBench), but many
    reader libraries still surface an empty text field as null/NaN regardless
    of dialect. Declared string columns need ``""`` restored post-read so the
    DataFrame surface matches the SQL reference (e.g. DuckDB, which keeps
    ``""``).

    Returns an empty list -- meaning "no coercion needed" -- when ``null_marker``
    is not ``None`` (the dialect already treats empty as SQL NULL, e.g. the
    TPC-style ``""`` marker / JoinOrder, so existing NULLs must be preserved) or
    when there are no declared string columns for this table.

    Args:
        string_columns: Declared string/text columns for this table (from
            :func:`declared_string_columns` or an equivalent per-family lookup).
        null_marker: The resolved CSV dialect's null marker.
        available_columns: The columns actually present in the loaded frame
            (membership is re-checked here because a declared column can be
            absent, e.g. when column_names was not supplied).

    Returns:
        The subset of ``string_columns`` that are present in
        ``available_columns`` and need empty-field restoration, or ``[]``.
    """
    if null_marker is not None or not string_columns:
        return []
    available = set(available_columns)
    return [column for column in string_columns if column in available]


def coerce_empty_string_columns(
    df: Any,
    string_columns: list[str] | None,
    null_marker: str | None,
) -> Any:
    """Restore ``""`` for empty CSV fields in declared string columns.

    Shared coercion step for DataFrame libraries whose column objects share
    Pandas' ``.fillna()`` and per-column assignment semantics (Pandas, cuDF,
    Dask, Modin). Delegates the empty-vs-null decision to
    :func:`resolve_empty_string_restore_columns` so all four adapters apply
    the identical guard and the identical restore action instead of each
    carrying its own copy.

    Column-by-column assignment (not a single ``df[cols] = ...`` batch
    assignment) is used because multi-column assignment support differs
    across dask/modin/cudf/pandas; looping is the common denominator that
    behaves identically -- and produces the same final values -- on all four.

    Args:
        df: The loaded DataFrame (Pandas/cuDF/Dask/Modin).
        string_columns: Declared string/text columns for this table.
        null_marker: The resolved CSV dialect's null marker.

    Returns:
        ``df``, mutated in place for the restored columns.
    """
    for column in resolve_empty_string_restore_columns(string_columns, null_marker, df.columns):
        df[column] = df[column].fillna("")
    return df


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
