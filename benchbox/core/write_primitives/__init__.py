# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from benchbox.core.write_primitives.benchmark import (
    OperationResult,
    WritePrimitivesBenchmark,
)
from benchbox.core.write_primitives.dataframe_operations import (
    DataFrameWriteCapabilities,
    DataFrameWriteOperationsManager,
    DataFrameWriteResult,
    WriteOperationType,
    get_dataframe_write_manager,
)
from benchbox.core.write_primitives.generator import WritePrimitivesDataGenerator
from benchbox.core.write_primitives.operations import WriteOperationsManager
from benchbox.core.write_primitives.schema import (
    BATCH_METADATA,
    BULK_LOAD_OPS_TARGET,
    DDL_TRUNCATE_TARGET,
    DELETE_OPS_LINEITEM,
    DELETE_OPS_ORDERS,
    DELETE_OPS_SUPPLIER,
    INSERT_OPS_LINEITEM,
    INSERT_OPS_LINEITEM_ENRICHED,
    INSERT_OPS_ORDERS,
    INSERT_OPS_ORDERS_SUMMARY,
    MERGE_OPS_LINEITEM_TARGET,
    MERGE_OPS_SOURCE,
    MERGE_OPS_SUMMARY_TARGET,
    MERGE_OPS_TARGET,
    STAGING_TABLES,
    TABLES,
    UPDATE_OPS_ORDERS,
    WRITE_OPS_LOG,
    get_all_staging_tables_sql,
    get_create_table_sql,
    get_table_schema,
)

__all__ = [
    "WritePrimitivesBenchmark",
    "OperationResult",
    "WritePrimitivesDataGenerator",
    "WriteOperationsManager",
    "WriteOperationType",
    "DataFrameWriteCapabilities",
    "DataFrameWriteResult",
    "DataFrameWriteOperationsManager",
    "get_dataframe_write_manager",
    "TABLES",
    "STAGING_TABLES",
    "INSERT_OPS_LINEITEM",
    "INSERT_OPS_ORDERS",
    "INSERT_OPS_ORDERS_SUMMARY",
    "INSERT_OPS_LINEITEM_ENRICHED",
    "UPDATE_OPS_ORDERS",
    "DELETE_OPS_ORDERS",
    "DELETE_OPS_LINEITEM",
    "DELETE_OPS_SUPPLIER",
    "MERGE_OPS_TARGET",
    "MERGE_OPS_SOURCE",
    "MERGE_OPS_LINEITEM_TARGET",
    "MERGE_OPS_SUMMARY_TARGET",
    "BULK_LOAD_OPS_TARGET",
    "DDL_TRUNCATE_TARGET",
    "WRITE_OPS_LOG",
    "BATCH_METADATA",
    "get_create_table_sql",
    "get_all_staging_tables_sql",
    "get_table_schema",
]
