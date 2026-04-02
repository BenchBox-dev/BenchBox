"""Shared helpers for Presto-family adapters."""

from __future__ import annotations

from collections.abc import Callable
from logging import Logger
from typing import Any

from benchbox.core.exceptions import ConfigurationError


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
