"""Apache Hudi Maintenance Operations Implementation.

This module implements DataFrame maintenance operations for Apache Hudi,
providing full ACID compliance for TPC-H RF1/RF2 and TPC-DS maintenance testing.

Hudi supports:
- INSERT: Append new data with transaction guarantees
- DELETE: Row-level deletes with predicate pushdown
- UPDATE: Row-level updates
- MERGE: Upsert operations (insert or update)

Hudi provides:
- ACID transactions with snapshot isolation
- Time travel (query historical commits)
- Schema evolution
- Copy-on-Write (COW) and Merge-on-Read (MOR) table types
- Record-level change tracking via record key

IMPORTANT: Unlike Delta Lake (delta-rs) and Iceberg (pyiceberg), Hudi has NO pure
Python maintenance library. All maintenance operations MUST use PySpark SQL,
which requires an active SparkSession with the hudi-spark-bundle.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

# Check for PySpark availability
try:
    from pyspark.sql import SparkSession

    PYSPARK_AVAILABLE = True
except ImportError:
    SparkSession = None  # type: ignore[assignment, misc]
    PYSPARK_AVAILABLE = False

from benchbox.core.dataframe.maintenance_interface import (
    HUDI_CAPABILITIES,
    BaseDataFrameMaintenanceOperations,
    DataFrameMaintenanceCapabilities,
    MaintenanceOperationType,
    MaintenanceResult,
)

logger = logging.getLogger(__name__)


class HudiMaintenanceOperations(BaseDataFrameMaintenanceOperations):
    """Apache Hudi maintenance operations implementation.

    Implements full ACID maintenance operations using PySpark SQL with Hudi:
    - INSERT: INSERT INTO table SELECT ... or DataFrameWriter
    - DELETE: DELETE FROM table WHERE condition
    - UPDATE: UPDATE table SET ... WHERE condition
    - MERGE: MERGE INTO table USING source ON condition WHEN MATCHED/NOT MATCHED

    Hudi provides snapshot isolation and ACID guarantees with record-level
    change tracking, making it suitable for TPC-H and TPC-DS maintenance tests.

    Key Hudi Concepts:
    - Record Key: Unique identifier for each record (required)
    - Precombine Field: Ordering field to resolve duplicates (typically timestamp)
    - Table Type: COPY_ON_WRITE (faster reads) or MERGE_ON_READ (faster writes)

    Example:
        from pyspark.sql import SparkSession

        spark = SparkSession.builder \\
            .appName("benchbox") \\
            .config("spark.jars.packages", "org.apache.hudi:hudi-spark3.5-bundle_2.12:0.14.0") \\
            .getOrCreate()

        ops = HudiMaintenanceOperations(
            spark_session=spark,
            record_key="order_key",
            precombine_field="order_date",
        )

        # Insert new rows (transactional)
        result = ops.insert_rows(
            table_path="hudi_db.orders",
            dataframe=new_orders_df,
            mode="append"
        )

        # Delete rows (row-level)
        result = ops.delete_rows(
            table_path="hudi_db.orders",
            condition="order_date < '2020-01-01'"
        )

    Note:
        Requires PySpark with hudi-spark-bundle:
        pip install pyspark
        Add to Spark config: spark.jars.packages=org.apache.hudi:hudi-spark3.5-bundle_2.12:0.14.0
    """

    def __init__(
        self,
        spark_session: Any,
        record_key: str | None = None,
        precombine_field: str | None = None,
        table_type: str = "COPY_ON_WRITE",
        working_dir: str | Path | None = None,
    ) -> None:
        """Initialize Hudi maintenance operations.

        Args:
            spark_session: Active SparkSession with Hudi bundle loaded
            record_key: Field name for record key (required for writes).
                If not provided, must be set per-table via table properties.
            precombine_field: Field name for ordering during updates.
                If not provided, uses a default constant.
            table_type: Hudi table type - "COPY_ON_WRITE" (default) or "MERGE_ON_READ".
                COW is better for analytics (faster reads), MOR for streaming (faster writes).
            working_dir: Optional working directory for temporary files

        Raises:
            ImportError: If PySpark is not installed
            ValueError: If spark_session is None
        """
        super().__init__()

        if not PYSPARK_AVAILABLE:
            raise ImportError(
                "PySpark is not installed. Install with: pip install pyspark\n"
                "For Hudi support, also configure Spark with:\n"
                "  spark.jars.packages=org.apache.hudi:hudi-spark3.5-bundle_2.12:0.14.0"
            )

        if spark_session is None:
            raise ValueError(
                "spark_session is required. Create one with:\n"
                "  spark = SparkSession.builder \\\n"
                "      .appName('benchbox') \\\n"
                "      .config('spark.jars.packages', 'org.apache.hudi:hudi-spark3.5-bundle_2.12:0.14.0') \\\n"
                "      .getOrCreate()"
            )

        self.spark = spark_session
        self.record_key = record_key
        self.precombine_field = precombine_field
        self.table_type = table_type
        self.working_dir = Path(working_dir) if working_dir else None
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_capabilities(self) -> DataFrameMaintenanceCapabilities:
        """Return Hudi maintenance capabilities.

        Returns:
            HUDI_CAPABILITIES (full ACID support via PySpark SQL)
        """
        return HUDI_CAPABILITIES

    def _convert_to_spark_df(self, dataframe: Any) -> Any:
        """Convert various DataFrame types to Spark DataFrame.

        Args:
            dataframe: Input DataFrame (PySpark, Pandas, Polars, or PyArrow)

        Returns:
            Spark DataFrame

        Raises:
            TypeError: If dataframe type is not supported
        """
        from pyspark.sql import DataFrame as SparkDataFrame

        # Already a Spark DataFrame
        if isinstance(dataframe, SparkDataFrame):
            return dataframe

        # PyArrow Table - convert via Pandas
        try:
            import pyarrow as pa

            if isinstance(dataframe, pa.Table):
                return self.spark.createDataFrame(dataframe.to_pandas())
        except ImportError:
            pass

        # Pandas DataFrame - convert using spark.createDataFrame
        if hasattr(dataframe, "to_dict") and hasattr(dataframe, "columns"):
            return self.spark.createDataFrame(dataframe)

        # Polars DataFrame - convert via Pandas
        if hasattr(dataframe, "to_pandas"):
            return self.spark.createDataFrame(dataframe.to_pandas())

        # List of dicts or tuples
        if isinstance(dataframe, list):
            return self.spark.createDataFrame(dataframe)

        raise TypeError(
            f"Unsupported DataFrame type: {type(dataframe)}. "
            f"Expected Spark DataFrame, Pandas DataFrame, Polars DataFrame, PyArrow Table, or list."
        )

    def _normalize_table_identifier(self, table_path: str | Path) -> str:
        """Normalize table path to Hudi table identifier.

        Hudi tables in Spark can be referenced by:
        - Catalog path: database.table_name
        - File path: /path/to/hudi/table

        Args:
            table_path: Table path or identifier

        Returns:
            Normalized identifier for SQL operations
        """
        path_str = str(table_path)

        # If it looks like a catalog path (database.table), use as-is
        if "." in path_str and "/" not in path_str and "\\" not in path_str:
            return path_str

        # For file paths, use backtick quoting for Spark SQL
        if path_str.startswith("/") or path_str.startswith("s3://") or path_str.startswith("gs://"):
            return f"`hudi`.`{path_str}`"

        return path_str

    def _do_insert(
        self,
        table_path: Path | str,
        dataframe: Any,
        partition_columns: list[str] | None,
        mode: str,
    ) -> int:
        """Insert rows using Hudi INSERT statement.

        Uses Spark SQL INSERT INTO for compatibility across all Hudi table types.

        Args:
            table_path: Path to the Hudi table
            dataframe: DataFrame containing rows to insert
            partition_columns: Columns to partition by (used for new tables)
            mode: Write mode ("append" or "overwrite")

        Returns:
            Number of rows inserted
        """
        table_id = self._normalize_table_identifier(str(table_path))

        # Convert to Spark DataFrame
        spark_df = self._convert_to_spark_df(dataframe)
        row_count = spark_df.count()

        if row_count == 0:
            self.logger.info("No rows to insert")
            return 0

        # Register as temp view for SQL INSERT
        temp_view = f"_hudi_insert_source_{id(spark_df)}"
        spark_df.createOrReplaceTempView(temp_view)

        try:
            if mode == "overwrite":
                # Use INSERT OVERWRITE for full table replacement
                self.spark.sql(f"INSERT OVERWRITE TABLE {table_id} SELECT * FROM {temp_view}")
            else:
                # Use INSERT INTO for append
                self.spark.sql(f"INSERT INTO {table_id} SELECT * FROM {temp_view}")

            self.logger.info(f"Inserted {row_count} rows to Hudi table {table_id}")
            return row_count

        finally:
            # Clean up temp view
            self.spark.catalog.dropTempView(temp_view)

    def _do_delete(
        self,
        table_path: Path | str,
        condition: str | Any,
    ) -> int:
        """Delete rows using Hudi DELETE statement.

        Args:
            table_path: Path to the Hudi table
            condition: SQL-like delete predicate (e.g., "order_date < '2020-01-01'")

        Returns:
            Number of rows deleted
        """
        table_id = self._normalize_table_identifier(str(table_path))

        # Get row count before delete
        count_before = self.spark.sql(f"SELECT COUNT(*) as cnt FROM {table_id}").collect()[0]["cnt"]

        # Execute DELETE
        self.spark.sql(f"DELETE FROM {table_id} WHERE {condition}")

        # Get row count after delete
        count_after = self.spark.sql(f"SELECT COUNT(*) as cnt FROM {table_id}").collect()[0]["cnt"]

        rows_deleted = count_before - count_after
        self.logger.info(f"Deleted {rows_deleted} rows from Hudi table {table_id}")
        return rows_deleted

    def _do_update(
        self,
        table_path: Path | str,
        condition: str | Any,
        updates: dict[str, Any],
    ) -> int:
        """Update rows using Hudi UPDATE statement.

        Args:
            table_path: Path to the Hudi table
            condition: SQL-like update predicate
            updates: Column name to new value expression mapping

        Returns:
            Estimated number of rows updated
        """
        table_id = self._normalize_table_identifier(str(table_path))

        # Count matching rows before update
        matching_count = self.spark.sql(f"SELECT COUNT(*) as cnt FROM {table_id} WHERE {condition}").collect()[0]["cnt"]

        if matching_count == 0:
            self.logger.info("No rows match update condition")
            return 0

        # Build SET clause
        set_clauses = ", ".join([f"{col} = {val}" for col, val in updates.items()])

        # Execute UPDATE
        self.spark.sql(f"UPDATE {table_id} SET {set_clauses} WHERE {condition}")

        self.logger.info(f"Updated {matching_count} rows in Hudi table {table_id}")
        return matching_count

    def _do_merge(
        self,
        table_path: Path | str,
        source_dataframe: Any,
        merge_condition: str | Any,
        when_matched: dict[str, Any] | None,
        when_not_matched: dict[str, Any] | None,
    ) -> int:
        """Merge rows using Hudi MERGE INTO statement.

        Args:
            table_path: Path to the Hudi table
            source_dataframe: Source DataFrame
            merge_condition: Join condition for matching rows
            when_matched: Updates to apply when matched
            when_not_matched: Inserts when not matched

        Returns:
            Number of rows affected (estimated from source size)
        """
        table_id = self._normalize_table_identifier(str(table_path))

        # Convert source to Spark DataFrame
        source_df = self._convert_to_spark_df(source_dataframe)
        source_count = source_df.count()

        # Register source as temp view
        source_view = f"_hudi_merge_source_{id(source_df)}"
        source_df.createOrReplaceTempView(source_view)

        try:
            # Build MERGE statement
            merge_sql = f"MERGE INTO {table_id} AS target\n"
            merge_sql += f"USING {source_view} AS source\n"
            merge_sql += f"ON {merge_condition}\n"

            if when_matched:
                set_clauses = ", ".join([f"target.{col} = {val}" for col, val in when_matched.items()])
                merge_sql += f"WHEN MATCHED THEN UPDATE SET {set_clauses}\n"

            if when_not_matched:
                columns = ", ".join(when_not_matched.keys())
                values = ", ".join([str(v) for v in when_not_matched.values()])
                merge_sql += f"WHEN NOT MATCHED THEN INSERT ({columns}) VALUES ({values})"

            # Execute MERGE
            self.spark.sql(merge_sql)

            self.logger.info(f"Merged {source_count} source rows into Hudi table {table_id}")
            return source_count

        finally:
            # Clean up temp view
            self.spark.catalog.dropTempView(source_view)

    def _call_target(self, table_path: Path | str) -> str:
        """Render the CALL target clause for a catalog name or table path.

        Hudi procedures accept either ``table => '<db.tbl>'`` or
        ``path => '<location>'``; paths are detected by the presence of a
        slash. Single quotes inside the value are doubled.
        """
        value = str(table_path).replace("'", "''")
        if "/" in value or "\\" in value:
            return f"path => '{value}'"
        return f"table => '{value}'"

    def _run_procedure(self, operation: MaintenanceOperationType, sql: str, start_time: float) -> MaintenanceResult:
        """Execute a CALL procedure and wrap its result rows."""
        try:
            result_frame = self.spark.sql(sql)
            rows = result_frame.collect() if hasattr(result_frame, "collect") else []
            row_dicts = [dict(row.asDict()) if hasattr(row, "asDict") else dict(row) for row in rows]
            deleted = 0
            for row_dict in row_dicts:
                for key, value in row_dict.items():
                    if "deleted" in str(key).lower() and isinstance(value, int):
                        deleted += value
            end_time = time.time()
            self.logger.info(f"Hudi procedure succeeded: {sql}")
            return MaintenanceResult(
                operation_type=operation,
                success=True,
                start_time=start_time,
                end_time=end_time,
                duration=end_time - start_time,
                rows_affected=deleted,
                metrics={"statement": sql, "result_rows": row_dicts},
            )
        except Exception as e:
            self.logger.error(f"Hudi procedure failed: {e}")
            return MaintenanceResult.failure(operation, str(e), start_time)

    def optimize_table(
        self,
        table_path: Path | str,
        *,
        strategy: str = "compact",
        columns: list[str] | None = None,
        partition_filter: Any | None = None,
    ) -> MaintenanceResult:
        """Run Hudi compaction or clustering via Spark SQL CALL procedures.

        "compact" maps to run_compaction (MOR tables); "cluster" maps to
        run_clustering (COW and MOR). columns/partition_filter are accepted
        for protocol conformance and ignored: the procedures take no
        column or partition arguments.
        """
        _ = (columns, partition_filter)
        operation = MaintenanceOperationType.OPTIMIZE
        start_time = time.time()
        try:
            self._check_capability(operation)
            normalized = strategy.lower()
            target = self._call_target(table_path)
            if normalized == "compact":
                sql = f"CALL run_compaction(op => 'run', {target})"
            elif normalized == "cluster":
                sql = f"CALL run_clustering({target})"
            else:
                raise NotImplementedError(f"Unknown Hudi optimize strategy '{strategy}'. Use 'compact' or 'cluster'.")
            return self._run_procedure(operation, sql, start_time)
        except NotImplementedError:
            raise
        except Exception as e:
            self.logger.error(f"OPTIMIZE failed: {e}")
            return MaintenanceResult.failure(operation, str(e), start_time)

    def vacuum_table(
        self,
        table_path: Path | str,
        *,
        retention_hours: int | None = None,
        dry_run: bool = True,
        enforce_retention: bool = True,
    ) -> MaintenanceResult:
        """Run Hudi cleaner via the run_clean CALL procedure.

        retention_hours maps to hours_retained with a KEEP_LATEST_BY_HOURS
        policy. run_clean has no dry-run mode, so dry_run=True raises
        NotImplementedError instead of pretending to preview.
        """
        _ = enforce_retention
        operation = MaintenanceOperationType.VACUUM
        start_time = time.time()
        try:
            self._check_capability(operation)
            if dry_run:
                raise NotImplementedError("Hudi run_clean has no dry-run mode. Re-run with dry_run=False to clean.")
            target = self._call_target(table_path)
            if retention_hours is not None:
                sql = (
                    f"CALL run_clean({target}, clean_policy => 'KEEP_LATEST_BY_HOURS', "
                    f"hours_retained => {int(retention_hours)})"
                )
            else:
                sql = f"CALL run_clean({target})"
            return self._run_procedure(operation, sql, start_time)
        except NotImplementedError:
            raise
        except Exception as e:
            self.logger.error(f"VACUUM failed: {e}")
            return MaintenanceResult.failure(operation, str(e), start_time)


def get_hudi_maintenance_operations(
    spark_session: Any = None,
    record_key: str | None = None,
    precombine_field: str | None = None,
    table_type: str = "COPY_ON_WRITE",
    working_dir: str | Path | None = None,
) -> HudiMaintenanceOperations | None:
    """Get Hudi maintenance operations if PySpark is available.

    Args:
        spark_session: Active SparkSession with Hudi bundle (required)
        record_key: Field name for record key
        precombine_field: Field name for ordering during updates
        table_type: Hudi table type ("COPY_ON_WRITE" or "MERGE_ON_READ")
        working_dir: Optional working directory

    Returns:
        HudiMaintenanceOperations if PySpark is available and spark_session
        is provided, None otherwise
    """
    if not PYSPARK_AVAILABLE:
        logger.debug("Hudi maintenance not available (pyspark not installed)")
        return None

    if spark_session is None:
        logger.debug("No SparkSession provided, cannot create Hudi maintenance operations")
        return None

    return HudiMaintenanceOperations(
        spark_session=spark_session,
        record_key=record_key,
        precombine_field=precombine_field,
        table_type=table_type,
        working_dir=working_dir,
    )


__all__ = [
    "HudiMaintenanceOperations",
    "get_hudi_maintenance_operations",
    "PYSPARK_AVAILABLE",
]
