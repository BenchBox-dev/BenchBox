# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from benchbox.core.tpch.schema import (
    TABLES as TPCH_TABLES,
    get_create_all_tables_sql as get_tpch_schema_sql,
)

if TYPE_CHECKING:
    from benchbox.core.tuning import UnifiedTuningConfiguration

logger = logging.getLogger(__name__)


def get_table_names() -> list[str]:
    return [table.name for table in TPCH_TABLES]


def get_schema() -> dict[str, dict[str, Any]]:
    schema = {}
    for table in TPCH_TABLES:
        schema[table.name] = {
            "name": table.name,
            "columns": [
                {
                    "name": col.name,
                    "type": col.get_sql_type(),
                    "nullable": col.nullable,
                    "primary_key": col.primary_key,
                }
                for col in table.columns
            ],
        }
    return schema


def get_create_tables_sql(
    dialect: str = "standard",
    tuning_config: UnifiedTuningConfiguration | None = None,
) -> str:
    enable_primary_keys = True
    enable_foreign_keys = False

    if tuning_config is not None:
        if hasattr(tuning_config, "primary_keys"):
            enable_primary_keys = tuning_config.primary_keys.enabled
        if hasattr(tuning_config, "foreign_keys"):
            enable_foreign_keys = tuning_config.foreign_keys.enabled

    logger.debug(f"Generating metadata schema SQL: pk={enable_primary_keys}, fk={enable_foreign_keys}")

    sql_parts = []

    sql_parts.append("-- Metadata Primitives Benchmark Schema")
    sql_parts.append("-- Creates TPC-H tables for metadata introspection testing")
    sql_parts.append("-- Tables: region, nation, supplier, part, partsupp, customer, orders, lineitem")
    sql_parts.append("")

    tpch_sql = get_tpch_schema_sql(
        enable_primary_keys=enable_primary_keys,
        enable_foreign_keys=enable_foreign_keys,
    )
    sql_parts.append(tpch_sql)

    return "\n".join(sql_parts)


def get_table_count() -> int:
    return len(TPCH_TABLES)


def get_total_column_count() -> int:
    return sum(len(table.columns) for table in TPCH_TABLES)


__all__ = [
    "get_create_tables_sql",
    "get_schema",
    "get_table_names",
    "get_table_count",
    "get_total_column_count",
]
