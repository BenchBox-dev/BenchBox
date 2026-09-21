"""Polars Maintenance Operations Implementation.

This module implements DataFrame maintenance operations for Polars,
enabling TPC-H RF1/RF2 and TPC-DS maintenance testing.

Polars supports all maintenance operations via read-modify-write pattern:
- INSERT: Append new data to Parquet files
- DELETE: Read-filter-write pattern (rewrites table)
- UPDATE: Read-modify-write pattern (rewrites table)
- MERGE: Read-join-write pattern (rewrites table)

Implementation Note:
    Polars operates entirely in RAM, so the full table rewrite approach is
    acceptable and matches Polars' standard data processing patterns. For
    very large datasets that exceed available RAM, use Delta Lake or Iceberg
    which support incremental operations with transaction logs.

    The read-modify-write pattern provides:
    - Full TPC-H and TPC-DS maintenance compliance
    - Atomic operations via backup-and-swap
    - Consistent behavior with Polars' immutable data model

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    import polars as pl

    POLARS_AVAILABLE = True
except ImportError:
    pl = None  # type: ignore[assignment]
    POLARS_AVAILABLE = False

from benchbox.core.dataframe.maintenance_interface import (
    POLARS_CAPABILITIES,
    BaseDataFrameMaintenanceOperations,
    DataFrameMaintenanceCapabilities,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class PolarsMaintenanceOperations(BaseDataFrameMaintenanceOperations):
    """Polars maintenance operations implementation.

    Implements all TPC maintenance operations via read-modify-write patterns:
    - INSERT: Append new Parquet files
    - DELETE: Read-filter-write (rewrites table without matching rows)
    - UPDATE: Read-modify-write (rewrites table with modified values)
    - MERGE: Read-join-write (rewrites table with merged data)

    All operations use atomic backup-and-swap to ensure data integrity.

    Note:
        Polars operates entirely in RAM, so the full table rewrite approach
        is standard. For datasets exceeding available RAM, use Delta Lake
        or Iceberg which support incremental operations.

    Example:
        ops = PolarsMaintenanceOperations()

        # Insert new rows
        result = ops.insert_rows(
            table_path="/data/orders",
            dataframe=new_orders_df,
            mode="append"
        )

        # Delete old rows (rewrites table)
        result = ops.delete_rows(
            table_path="/data/orders",
            condition="order_date < '2020-01-01'"
        )

        # Update rows (rewrites table)
        result = ops.update_rows(
            table_path="/data/orders",
            condition="status = 'pending'",
            updates={"status": "'cancelled'"}
        )

        # Merge/upsert (rewrites table)
        result = ops.merge_rows(
            table_path="/data/orders",
            source_dataframe=new_orders,
            merge_condition="target.id = source.id",
            when_matched={"status": "source.status"},
            when_not_matched={"id": "source.id", "status": "source.status"}
        )
    """

    def __init__(self, working_dir: str | Path | None = None) -> None:
        """Initialize Polars maintenance operations.

        Args:
            working_dir: Optional working directory for temporary files

        Raises:
            ImportError: If Polars is not installed
        """
        super().__init__()

        if not POLARS_AVAILABLE:
            raise ImportError(
                "Polars is not installed. Install with: pip install polars\n"
                "For TPC-H/TPC-DS maintenance tests, install the full package:\n"
                "pip install 'benchbox[dataframe]'"
            )

        self.working_dir = Path(working_dir) if working_dir else None
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _get_capabilities(self) -> DataFrameMaintenanceCapabilities:
        """Return Polars maintenance capabilities.

        Returns:
            POLARS_CAPABILITIES (insert + partition delete only)
        """
        return POLARS_CAPABILITIES

    def _do_insert(
        self,
        table_path: Path | str,
        dataframe: Any,
        partition_columns: list[str] | None,
        mode: str,
    ) -> int:
        """Insert rows by writing to Parquet files.

        Args:
            table_path: Path to the table directory
            dataframe: Polars DataFrame to insert
            partition_columns: Columns to partition by (creates subdirectories)
            mode: Write mode ("append" or "overwrite")

        Returns:
            Number of rows inserted

        Raises:
            ValueError: If mode is invalid
            TypeError: If dataframe is not a Polars DataFrame
        """
        table_path = Path(table_path)

        # Validate and convert dataframe
        if isinstance(dataframe, pl.LazyFrame):
            df = dataframe.collect()
        elif isinstance(dataframe, pl.DataFrame):
            df = dataframe
        elif hasattr(dataframe, "to_parquet") and hasattr(dataframe, "columns"):
            # Pandas DataFrame (e.g. TPC-DI ETL stages pandas frames)
            df = pl.from_pandas(dataframe)
        else:
            raise TypeError(f"Expected Polars DataFrame, LazyFrame, or Pandas DataFrame, got {type(dataframe)}")

        row_count = df.height

        if row_count == 0:
            self.logger.info("No rows to insert")
            return 0

        # Ensure directory exists
        table_path.mkdir(parents=True, exist_ok=True)

        if mode == "overwrite":
            # Remove existing files
            for f in table_path.glob("*.parquet"):
                f.unlink()

        if partition_columns:
            # Write partitioned data
            self._write_partitioned(df, table_path, partition_columns, mode)
        else:
            # Write to a single file or append
            self._write_single(df, table_path, mode)

        self.logger.info(f"Inserted {row_count} rows to {table_path}")
        return row_count

    def _write_single(self, df: Any, table_path: Path, mode: str) -> None:
        """Write DataFrame to a single Parquet file.

        Args:
            df: Polars DataFrame
            table_path: Directory path
            mode: "append" or "overwrite"
        """
        if mode == "append":
            # Generate unique filename
            existing = list(table_path.glob("part-*.parquet"))
            part_num = len(existing)
            file_path = table_path / f"part-{part_num:05d}.parquet"
        else:
            file_path = table_path / "part-00000.parquet"

        df.write_parquet(file_path)
        self.logger.debug(f"Wrote {df.height} rows to {file_path}")

    def _write_partitioned(
        self,
        df: Any,
        table_path: Path,
        partition_columns: list[str],
        mode: str,
    ) -> None:
        """Write DataFrame with Hive-style partitioning.

        Args:
            df: Polars DataFrame
            table_path: Base directory path
            partition_columns: Columns to partition by
            mode: Write mode
        """
        # Group by partition columns
        for partition_vals, partition_df in df.group_by(partition_columns):
            # Build partition path
            if isinstance(partition_vals, tuple):
                parts = zip(partition_columns, partition_vals)
            else:
                parts = [(partition_columns[0], partition_vals)]

            partition_path = table_path
            for col, val in parts:
                partition_path = partition_path / f"{col}={val}"

            partition_path.mkdir(parents=True, exist_ok=True)

            # Write partition data
            self._write_single(partition_df, partition_path, mode)

    def _do_delete(
        self,
        table_path: Path | str,
        condition: str | Any,
    ) -> int:
        """Delete rows using read-filter-write pattern.

        Since Polars doesn't support row-level deletes, we:
        1. Read all existing data
        2. Filter out rows matching the condition
        3. Write the remaining data back

        This is expensive for large datasets. For better performance,
        use Delta Lake or Iceberg which support row-level deletes.

        Args:
            table_path: Path to the table directory
            condition: SQL-like condition string (e.g., "id > 100")

        Returns:
            Number of rows deleted

        Note:
            The condition is parsed using Polars SQL syntax.
            Example conditions:
            - "order_date < '2020-01-01'"
            - "status = 'cancelled'"
            - "amount > 1000 AND region = 'US'"
        """
        table_path = Path(table_path)

        if not table_path.exists():
            self.logger.warning(f"Table path does not exist: {table_path}")
            return 0

        # Read all existing data
        parquet_files = list(table_path.glob("**/*.parquet"))
        if not parquet_files:
            self.logger.warning(f"No Parquet files found in {table_path}")
            return 0

        # Read all data
        self.logger.debug(f"Reading {len(parquet_files)} files from {table_path}")
        df = pl.scan_parquet(parquet_files).collect()
        original_count = df.height

        if original_count == 0:
            return 0

        # Apply filter to keep rows NOT matching the delete condition
        # We need to negate the condition
        try:
            # Use Polars SQL to evaluate the condition
            df_with_ctx = pl.SQLContext(register_globals=True)
            df_with_ctx.register("__table__", df)

            # Query to find rows TO DELETE (matching condition)
            delete_query = f"SELECT COUNT(*) as cnt FROM __table__ WHERE {condition}"
            delete_count_df = df_with_ctx.execute(delete_query).collect()
            delete_count = delete_count_df["cnt"][0]

            if delete_count == 0:
                self.logger.info("No rows match delete condition")
                return 0

            # Query to keep rows NOT matching condition
            keep_query = f"SELECT * FROM __table__ WHERE NOT ({condition})"
            remaining_df = df_with_ctx.execute(keep_query).collect()

        except Exception as e:
            # Fallback: try to parse condition as Polars expression
            self.logger.warning(f"SQL condition parsing failed: {e}. Trying expression parse.")
            raise ValueError(
                f"Failed to parse delete condition: {condition}\n"
                f'Use SQL-like syntax: "column > value" or "column = \'value\'"\n'
                f"Error: {e}"
            ) from e

        rows_deleted = original_count - remaining_df.height

        if rows_deleted > 0:
            # Backup and rewrite
            backup_path = table_path.parent / f"{table_path.name}_backup_{os.getpid()}"
            try:
                # Move existing files to backup
                shutil.move(str(table_path), str(backup_path))

                # Write remaining data
                table_path.mkdir(parents=True, exist_ok=True)
                if remaining_df.height > 0:
                    remaining_df.write_parquet(table_path / "part-00000.parquet")

                # Remove backup on success
                shutil.rmtree(backup_path)

            except Exception as e:
                # Restore from backup on failure
                if backup_path.exists():
                    shutil.rmtree(table_path, ignore_errors=True)
                    shutil.move(str(backup_path), str(table_path))
                raise RuntimeError(f"Delete failed, restored from backup: {e}") from e

        self.logger.info(f"Deleted {rows_deleted} rows from {table_path}")
        return rows_deleted

    def _do_update(
        self,
        table_path: Path | str,
        condition: str | Any,
        updates: dict[str, Any],
    ) -> int:
        """Update rows using read-modify-write pattern.

        Since Polars uses immutable DataFrames, we:
        1. Read all existing data
        2. Apply updates to rows matching the condition
        3. Write the modified data back

        This is Polars' standard approach for data modification. For datasets
        exceeding available RAM, use Delta Lake or Iceberg.

        Args:
            table_path: Path to the table directory
            condition: SQL-like condition string (e.g., "status = 'pending'")
            updates: Dict mapping column names to new values or expressions

        Returns:
            Number of rows updated

        Example:
            result = ops.update_rows(
                table_path="/data/orders",
                condition="status = 'pending'",
                updates={"status": "'cancelled'", "updated_at": "CURRENT_DATE"}
            )
        """
        table_path = Path(table_path)

        if not table_path.exists():
            self.logger.warning(f"Table path does not exist: {table_path}")
            return 0

        # Read all existing data
        parquet_files = list(table_path.glob("**/*.parquet"))
        if not parquet_files:
            self.logger.warning(f"No Parquet files found in {table_path}")
            return 0

        df = pl.scan_parquet(parquet_files).collect()
        original_count = df.height

        if original_count == 0:
            return 0

        try:
            # Use Polars SQL to identify rows to update and apply changes
            df_with_ctx = pl.SQLContext(register_globals=True)
            df_with_ctx.register("__table__", df)

            # Count matching rows
            count_query = f"SELECT COUNT(*) as cnt FROM __table__ WHERE {condition}"
            match_count = df_with_ctx.execute(count_query).collect()["cnt"][0]

            if match_count == 0:
                self.logger.info("No rows match update condition")
                return 0

            # Polars SQL doesn't support UPDATE directly, so we use CASE expressions
            # Build a SELECT that applies updates via CASE WHEN
            select_cols = []
            for col_name in df.columns:
                if col_name in updates:
                    value = updates[col_name]
                    select_cols.append(f"CASE WHEN ({condition}) THEN {value} ELSE {col_name} END AS {col_name}")
                else:
                    select_cols.append(col_name)

            update_query = f"SELECT {', '.join(select_cols)} FROM __table__"
            updated_df = df_with_ctx.execute(update_query).collect()

        except Exception as e:
            raise ValueError(
                f"Failed to parse update condition or values: {condition}\n"
                f"Updates: {updates}\n"
                f"Use SQL-like syntax for conditions and values.\n"
                f"Error: {e}"
            ) from e

        # Atomic write with backup
        self._atomic_rewrite(table_path, updated_df)

        self.logger.info(f"Updated {match_count} rows in {table_path}")
        return match_count

    def _do_merge(
        self,
        table_path: Path | str,
        source_dataframe: Any,
        merge_condition: str | Any,
        when_matched: dict[str, Any] | None,
        when_not_matched: dict[str, Any] | None,
    ) -> int:
        """Merge (upsert) rows using read-join-write pattern.

        Since Polars uses immutable DataFrames, we:
        1. Read target table
        2. Join with source on merge key
        3. Apply when_matched updates to matching rows
        4. Insert when_not_matched rows
        5. Write the merged data back

        This is Polars' standard approach for upsert operations.

        Args:
            table_path: Path to the table directory
            source_dataframe: Polars DataFrame with source data
            merge_condition: Join condition (e.g., "target.id = source.id")
            when_matched: Dict of column updates for matched rows
            when_not_matched: Dict of column values for inserted rows

        Returns:
            Number of rows affected (updated + inserted)

        Example:
            result = ops.merge_rows(
                table_path="/data/dim_customer",
                source_dataframe=updated_customers,
                merge_condition="target.c_custkey = source.c_custkey",
                when_matched={"c_name": "source.c_name", "c_address": "source.c_address"},
                when_not_matched={"c_custkey": "source.c_custkey", "c_name": "source.c_name"}
            )
        """
        table_path = Path(table_path)

        # Convert source to Polars DataFrame
        if isinstance(source_dataframe, pl.LazyFrame):
            source_df = source_dataframe.collect()
        elif isinstance(source_dataframe, pl.DataFrame):
            source_df = source_dataframe
        elif hasattr(source_dataframe, "to_parquet") and hasattr(source_dataframe, "columns"):
            # Pandas DataFrame (e.g. TPC-DI ETL stages pandas frames)
            source_df = pl.from_pandas(source_dataframe)
        else:
            raise TypeError(f"Expected Polars DataFrame, LazyFrame, or Pandas DataFrame, got {type(source_dataframe)}")

        source_count = source_df.height
        if source_count == 0:
            self.logger.info("Source DataFrame is empty, nothing to merge")
            return 0

        # Read target table
        if not table_path.exists():
            # No target table - just insert all source rows
            self.logger.info(f"Target table doesn't exist, inserting {source_count} rows")
            return self._do_insert(table_path, source_df, None, "append")

        parquet_files = list(table_path.glob("**/*.parquet"))
        if not parquet_files:
            return self._do_insert(table_path, source_df, None, "append")

        target_df = pl.scan_parquet(parquet_files).collect()

        # Parse merge condition to extract key column(s)
        # Expected format: "target.col = source.col" or just "col"
        merge_key = self._parse_merge_key(str(merge_condition))

        rows_updated = 0
        rows_inserted = 0

        # Identify matching and non-matching rows
        source_keys = set(source_df[merge_key].to_list())
        target_keys = set(target_df[merge_key].to_list())

        matching_keys = source_keys & target_keys
        new_keys = source_keys - target_keys

        # Apply when_matched updates
        if when_matched and matching_keys:
            # Update matching rows in target with values from source
            for key_val in matching_keys:
                # Get source row for this key
                source_row = source_df.filter(pl.col(merge_key) == key_val)

                # Build update expressions
                for col, expr in when_matched.items():
                    if isinstance(expr, str) and expr.startswith("source."):
                        source_col = expr[7:]  # Remove "source." prefix
                        new_value = source_row[source_col][0]
                        target_df = target_df.with_columns(
                            pl.when(pl.col(merge_key) == key_val)
                            .then(pl.lit(new_value))
                            .otherwise(pl.col(col))
                            .alias(col)
                        )
                rows_updated += 1

        # Insert when_not_matched rows
        if when_not_matched and new_keys:
            new_rows_df = source_df.filter(pl.col(merge_key).is_in(list(new_keys)))
            rows_inserted = new_rows_df.height

            # Ensure columns match target schema
            for col in target_df.columns:
                if col not in new_rows_df.columns:
                    # Add missing column with null
                    new_rows_df = new_rows_df.with_columns(pl.lit(None).alias(col))

            # Select only target columns in correct order
            new_rows_df = new_rows_df.select(target_df.columns)

            # Append new rows
            target_df = pl.concat([target_df, new_rows_df])

        # Atomic write
        self._atomic_rewrite(table_path, target_df)

        total_affected = rows_updated + rows_inserted
        self.logger.info(f"Merged {total_affected} rows ({rows_updated} updated, {rows_inserted} inserted)")
        return total_affected

    def _parse_merge_key(self, merge_condition: str) -> str:
        """Extract merge key column from condition string.

        Args:
            merge_condition: Condition like "target.id = source.id" or "id"

        Returns:
            Column name to use as merge key
        """
        condition = merge_condition.strip()

        # Handle "target.col = source.col" format
        if "=" in condition:
            left, right = condition.split("=", 1)
            left = left.strip()
            right = right.strip()

            # Extract column name from "target.col" or "source.col"
            if "." in left:
                return left.split(".", 1)[1]
            return left

        # Handle simple column name
        return condition

    def _atomic_rewrite(self, table_path: Path, df: Any) -> None:
        """Atomically rewrite table using backup-and-swap.

        Args:
            table_path: Path to table directory
            df: New DataFrame to write

        Raises:
            RuntimeError: If write fails (original data is restored)
        """
        backup_path = table_path.parent / f"{table_path.name}_backup_{os.getpid()}"

        try:
            # Move existing files to backup
            if table_path.exists():
                shutil.move(str(table_path), str(backup_path))

            # Write new data
            table_path.mkdir(parents=True, exist_ok=True)
            if df.height > 0:
                df.write_parquet(table_path / "part-00000.parquet")

            # Remove backup on success
            if backup_path.exists():
                shutil.rmtree(backup_path)

        except Exception as e:
            # Restore from backup on failure
            if backup_path.exists():
                shutil.rmtree(table_path, ignore_errors=True)
                shutil.move(str(backup_path), str(table_path))
            raise RuntimeError(f"Atomic rewrite failed, restored from backup: {e}") from e


def get_polars_maintenance_operations(working_dir: str | Path | None = None) -> PolarsMaintenanceOperations | None:
    """Get Polars maintenance operations if Polars is available.

    Args:
        working_dir: Optional working directory

    Returns:
        PolarsMaintenanceOperations if Polars is available, None otherwise
    """
    if not POLARS_AVAILABLE:
        logger.debug("Polars not available, cannot create maintenance operations")
        return None

    return PolarsMaintenanceOperations(working_dir=working_dir)
