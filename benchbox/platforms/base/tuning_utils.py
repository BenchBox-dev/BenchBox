"""Shared tuning utilities for SQL platform adapters."""

from __future__ import annotations

from logging import Logger
from typing import Any


def log_partition_tunings(
    table_tuning: Any,
    logger: Logger,
    platform_name: str,
) -> None:
    """Log partition tuning configuration for a table.

    Shared implementation for platforms where tuning is primarily handled at
    table creation time and post-creation optimization is limited (Firebolt,
    LakeSail, Presto).

    Args:
        table_tuning: Table tuning configuration object.
        logger: Logger instance from the platform adapter.
        platform_name: Display name for log messages (e.g. "Firebolt").
    """
    if not table_tuning or not table_tuning.has_any_tuning():
        return

    table_name = table_tuning.table_name.lower()
    logger.info(f"Applying {platform_name} tunings for table: {table_name}")

    try:
        from benchbox.core.tuning.interface import TuningType

        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda col: col.order)
            column_names = [col.name for col in sorted_cols]
            logger.info(f"Partitioning for {table_name}: {', '.join(column_names)}")

    except ImportError:
        logger.warning("Tuning interface not available - skipping tuning application")
