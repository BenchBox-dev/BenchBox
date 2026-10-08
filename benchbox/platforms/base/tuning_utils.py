from __future__ import annotations

from logging import Logger
from typing import Any


def log_partition_tunings(
    table_tuning: Any,
    logger: Logger,
    platform_name: str,
) -> None:
    if not table_tuning or not table_tuning.has_any_tuning():
        return

    table_name = table_tuning.table_name
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
