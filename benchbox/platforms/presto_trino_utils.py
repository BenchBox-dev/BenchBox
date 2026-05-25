"""Shared helpers for Presto-family adapters."""

from __future__ import annotations

import re
from collections.abc import Callable
from logging import Logger
from pathlib import Path
from typing import Any

from benchbox.core.exceptions import ConfigurationError

_DATE_LITERAL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_date_value(value: str) -> bool:
    """Return True for strings that match the TPC-H YYYY-MM-DD date format.

    Presto and Trino memory catalogs require ``DATE 'YYYY-MM-DD'`` literal
    syntax rather than string auto-casting, so INSERT VALUES rendering needs
    to detect the date shape explicitly.
    """
    return bool(_DATE_LITERAL_RE.match(value))


def escape_insert_value(value: str) -> str:
    """Format a CSV field as a Presto/Trino literal for INSERT VALUES."""
    if value == "" or value.lower() == "null":
        return "NULL"
    if is_date_value(value):
        return f"DATE '{value}'"
    try:
        float(value)
        return value
    except ValueError:
        return "'" + str(value).replace("'", "''") + "'"


def resolve_data_files(
    benchmark: Any,
    data_dir: Path,
    *,
    platform_name: str,
    table_mode: str,
    platform_config: Any,
    requested_format: Any,
) -> dict[str, Any]:
    """Resolve benchmark data files via DataSourceResolver.

    Raises ``ValueError`` when no data files are resolved - consistent
    with the per-adapter message both Presto and Trino used.
    """
    from benchbox.platforms.base.data_loading import DataSourceResolver

    resolver = DataSourceResolver(
        platform_name=platform_name,
        table_mode=table_mode,
        platform_config=platform_config,
        requested_format=requested_format,
    )
    data_source = resolver.resolve(benchmark, data_dir)
    if not data_source or not data_source.tables:
        raise ValueError("No data files found. Ensure benchmark.generate_data() was called first.")
    return data_source.tables


def load_file_batches(cursor: Any, file_path: Path, qualified_table: str) -> int:
    """Load one file into a Presto/Trino table using batched INSERT VALUES."""
    from benchbox.platforms.base.data_loading import FileFormatRegistry
    from benchbox.utils.file_format import get_delimiter_for_file

    delimiter = get_delimiter_for_file(file_path)
    compression_handler = FileFormatRegistry.get_compression_handler(file_path)
    rows_loaded = 0

    with compression_handler.open(file_path) as file_handle:
        batch_size = 500
        batch_data: list[str] = []

        for line in file_handle:
            line = line.strip()
            if line and line.endswith(delimiter):
                line = line[:-1]
            if not line:
                continue

            escaped_values = [escape_insert_value(value) for value in line.split(delimiter)]
            batch_data.append(f"({', '.join(escaped_values)})")

            if len(batch_data) >= batch_size:
                cursor.execute(f"INSERT INTO {qualified_table} VALUES " + ", ".join(batch_data))
                rows_loaded += len(batch_data)
                batch_data = []

        if batch_data:
            cursor.execute(f"INSERT INTO {qualified_table} VALUES " + ", ".join(batch_data))
            rows_loaded += len(batch_data)

    return rows_loaded


def normalize_existing_files(file_paths: Any) -> list[Path]:
    """Normalize file inputs to existing, non-empty local paths."""
    normalized_paths = file_paths if isinstance(file_paths, list) else [file_paths]
    valid_files: list[Path] = []
    for file_path in normalized_paths:
        path = Path(file_path)
        if path.exists() and path.stat().st_size > 0:
            valid_files.append(path)
    return valid_files


def show_tables_lower(connection: Any) -> list[str]:
    """Return lower-cased table names from a cursor-based SHOW TABLES result."""
    cursor = connection.cursor()
    try:
        cursor.execute("SHOW TABLES")
        return [row[0].lower() for row in cursor.fetchall()]
    except Exception:
        return []
    finally:
        cursor.close()


def validate_catalog_exists(
    catalog: str | None,
    *,
    platform_name: str,
    auto_select_catalog: Callable[[], str | None],
    get_available_catalogs: Callable[[], list[str]],
    logger: Logger,
) -> tuple[str, bool]:
    """Validate a requested catalog or auto-select one for Presto-family adapters."""
    auto_selected = False

    if not catalog:
        catalog = auto_select_catalog()
        if catalog:
            auto_selected = True
            logger.info(f"Auto-selected catalog '{catalog}' for benchmarking")
        else:
            available = get_available_catalogs()
            if available:
                catalog_list = ", ".join(sorted(available))
                raise ConfigurationError(
                    f"No usable data catalogs found on {platform_name} server.\n"
                    f"Available catalogs ({catalog_list}) are system-only and cannot store data.\n"
                    f"Configure a data catalog (hive, iceberg, delta, or memory) on your {platform_name} server,\n"
                    "or specify a catalog explicitly with --platform-option catalog=<name>"
                )
            raise ConfigurationError(
                f"{platform_name} requires a catalog but server is unreachable.\n"
                "Ensure the server is running, then either:\n"
                "  1. Run again (catalog will be auto-selected)\n"
                "  2. Specify explicitly: --platform-option catalog=<name>\n"
                "  3. Configure default: benchbox platforms setup"
            )

    available_catalogs = get_available_catalogs()
    if not available_catalogs:
        logger.debug("Could not query available catalogs - proceeding with specified catalog")
        return catalog, auto_selected

    if catalog in available_catalogs:
        return catalog, auto_selected

    catalog_list = ", ".join(sorted(available_catalogs))
    raise ConfigurationError(
        f"Catalog '{catalog}' does not exist on the {platform_name} server.\n"
        f"Available catalogs: {catalog_list}\n"
        "Specify a valid catalog with --platform-option catalog=<name> (e.g., --platform-option catalog=hive)"
    )


def execute_schema_statements(
    schema_sql: str,
    connection: Any,
    logger: Logger,
    normalize_table_name_in_sql: Callable[[str], str],
    optimize_table_definition: Callable[[str], str],
    extract_table_name: Callable[[str], str | None],
    log_notice: Callable[[str], None],
) -> None:
    """Execute schema DDL statements with drop-and-recreate error recovery.

    Shared implementation for Presto and Trino create_schema methods.

    Args:
        schema_sql: Semicolon-delimited DDL statements.
        connection: DBAPI connection.
        logger: Logger instance.
        normalize_table_name_in_sql: Callable to normalize table names.
        optimize_table_definition: Callable to apply platform-specific DDL tweaks.
        extract_table_name: Callable to extract table name from a DDL statement.
        log_notice: Default-visible logging wrapper that respects quiet mode.
    """
    cursor = connection.cursor()

    try:
        statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]

        for statement in statements:
            if not statement:
                continue

            statement = normalize_table_name_in_sql(statement)
            statement = optimize_table_definition(statement)

            try:
                cursor.execute(statement)
                logger.debug(f"Executed schema statement: {statement[:100]}...")
            except Exception as e:
                if "already exists" in str(e).lower():
                    table_name = extract_table_name(statement)
                    if table_name:
                        log_notice(f"Dropping existing table before recreate: {table_name}")
                        cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
                        cursor.execute(statement)
                else:
                    raise

        logger.info("Schema created")

    except Exception as e:
        logger.error(f"Schema creation failed: {e}")
        raise
    finally:
        cursor.close()
