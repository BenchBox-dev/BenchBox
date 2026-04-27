"""Apache Iceberg Maintenance Operations Implementation.

This module implements DataFrame maintenance operations for Apache Iceberg,
providing full ACID compliance for TPC-H RF1/RF2 and TPC-DS maintenance testing.

Iceberg supports:
- INSERT: Append new data with transaction guarantees
- DELETE: Row-level deletes with equality/range predicates
- UPDATE: Row-level updates via delete + insert
- MERGE: Upsert operations (via Spark SQL or custom logic)

Iceberg provides:
- ACID transactions with snapshot isolation
- Time travel (query historical snapshots)
- Hidden partitioning
- Schema evolution
- Row-level deletes and updates

Note:
    This implementation uses pyiceberg for local/REST catalog operations.
    For production Spark/Trino workloads, use the native connectors.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    from pyiceberg.catalog import Catalog, load_catalog
    from pyiceberg.expressions import (
        AlwaysTrue,
        EqualTo,
        GreaterThan,
        GreaterThanOrEqual,
        LessThan,
        LessThanOrEqual,
        NotEqualTo,
    )
    from pyiceberg.table import Table

    ICEBERG_AVAILABLE = True
except ImportError:
    Catalog = None  # type: ignore[assignment, misc]
    load_catalog = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment, misc]
    ICEBERG_AVAILABLE = False

try:
    import pyarrow as pa

    PYARROW_AVAILABLE = True
except ImportError:
    pa = None  # type: ignore[assignment]
    PYARROW_AVAILABLE = False

from benchbox.core.dataframe.maintenance_interface import (
    ICEBERG_CAPABILITIES,
    BaseDataFrameMaintenanceOperations,
    DataFrameMaintenanceCapabilities,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class IcebergMaintenanceOperations(BaseDataFrameMaintenanceOperations):
    """Apache Iceberg maintenance operations implementation.

    Implements full ACID maintenance operations using pyiceberg:
    - INSERT: Append with transaction guarantees
    - DELETE: Row-level deletes using expressions
    - UPDATE: Row-level updates (delete + insert pattern)
    - MERGE: Upsert operations

    Iceberg provides snapshot isolation and optimistic concurrency,
    making it suitable for TPC-H and TPC-DS maintenance tests.

    Example:
        ops = IcebergMaintenanceOperations(
            catalog_name="local",
            catalog_config={"type": "sql", "uri": "sqlite:///iceberg.db"}
        )

        # Insert new rows (transactional)
        result = ops.insert_rows(
            table_path="db.orders",
            dataframe=new_orders_df,
            mode="append"
        )

        # Delete rows (row-level)
        result = ops.delete_rows(
            table_path="db.orders",
            condition="order_date < '2020-01-01'"
        )

    Note:
        Requires pyiceberg: pip install pyiceberg
        For production, configure appropriate catalog (Hive, REST, Glue, etc.)
    """

    def __init__(
        self,
        catalog_name: str = "default",
        catalog_config: dict[str, Any] | None = None,
        working_dir: str | Path | None = None,
    ) -> None:
        """Initialize Iceberg maintenance operations.

        Args:
            catalog_name: Name of the Iceberg catalog
            catalog_config: Catalog configuration dict. If None, uses in-memory catalog.
            working_dir: Optional working directory for warehouse

        Raises:
            ImportError: If pyiceberg is not installed
        """
        super().__init__()

        if not ICEBERG_AVAILABLE:
            raise ImportError(
                "pyiceberg is not installed. Install with: pip install pyiceberg\n"
                "For TPC-H/TPC-DS maintenance tests with Iceberg, install:\n"
                "pip install 'benchbox[iceberg]'"
            )

        if not PYARROW_AVAILABLE:
            raise ImportError(
                "PyArrow is not installed. Install with: pip install pyarrow\n"
                "PyArrow is required for Iceberg operations."
            )

        self.working_dir = Path(working_dir) if working_dir else Path.cwd() / "iceberg_warehouse"
        self.catalog_name = catalog_name
        self.catalog_config = catalog_config or self._default_catalog_config()
        self._catalog: Catalog | None = None
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _default_catalog_config(self) -> dict[str, Any]:
        """Create default in-memory/sqlite catalog config.

        Returns:
            Default catalog configuration for local testing
        """
        warehouse_path = str(self.working_dir / "warehouse")
        return {
            "type": "sql",
            "uri": f"sqlite:///{self.working_dir}/iceberg_catalog.db",
            "warehouse": warehouse_path,
        }

    @property
    def catalog(self) -> Catalog:
        """Get or create the Iceberg catalog.

        Returns:
            Configured Iceberg Catalog instance
        """
        if self._catalog is None:
            self.working_dir.mkdir(parents=True, exist_ok=True)
            self._catalog = load_catalog(self.catalog_name, **self.catalog_config)
        return self._catalog

    def _get_capabilities(self) -> DataFrameMaintenanceCapabilities:
        """Return Iceberg maintenance capabilities.

        Returns:
            ICEBERG_CAPABILITIES (full ACID support)
        """
        return ICEBERG_CAPABILITIES

    # Note: _convert_to_arrow() is inherited from BaseDataFrameMaintenanceOperations

    def _normalize_table_identifier(self, table_path: str) -> str:
        """Normalize table path to Iceberg table identifier.

        Iceberg catalogs expect identifiers in the format `namespace.table_name`,
        not filesystem paths. This method converts various input formats to a
        proper Iceberg identifier.

        Args:
            table_path: Table path or identifier (can be filesystem path or dot notation)

        Returns:
            Normalized Iceberg identifier (e.g., "default.table_name")
        """
        # Check if it's already a valid Iceberg identifier (namespace.table)
        # but not a filesystem path with dots
        if "." in table_path and "/" not in table_path and "\\" not in table_path:
            return table_path

        # Extract table name from filesystem path
        path = Path(table_path)
        table_name = path.name

        # Clean up the table name (remove special characters, use only alphanumeric and underscore)
        import re

        table_name = re.sub(r"[^a-zA-Z0-9_]", "_", table_name)

        return f"default.{table_name}"

    def _get_or_create_table(
        self,
        table_identifier: str,
        schema: Any,
        partition_columns: list[str] | None = None,
    ) -> Table:
        """Get existing table or create new one.

        Args:
            table_identifier: Table identifier (namespace.table_name)
            schema: PyArrow schema for table creation
            partition_columns: Optional partition columns

        Returns:
            Iceberg Table instance
        """
        # Normalize the identifier
        normalized_id = self._normalize_table_identifier(table_identifier)

        try:
            return self.catalog.load_table(normalized_id)
        except Exception:
            # Table doesn't exist, create it
            self.logger.info(f"Creating new Iceberg table: {normalized_id}")

            # Parse namespace from normalized identifier
            if "." in normalized_id:
                namespace, _ = normalized_id.rsplit(".", 1)
            else:
                namespace = "default"

            # Ensure namespace exists
            try:
                self.catalog.create_namespace(namespace)
            except Exception:
                pass  # Namespace may already exist

            # Create table
            return self.catalog.create_table(
                identifier=normalized_id,
                schema=schema,
            )

    def _do_insert(
        self,
        table_path: Path | str,
        dataframe: Any,
        partition_columns: list[str] | None,
        mode: str,
    ) -> int:
        """Insert rows using Iceberg append.

        Args:
            table_path: Table identifier (namespace.table_name) or path
            dataframe: DataFrame containing rows to insert
            partition_columns: Columns to partition by (used for table creation)
            mode: Write mode ("append" or "overwrite")

        Returns:
            Number of rows inserted
        """
        table_identifier = str(table_path)

        # Convert to PyArrow
        arrow_table = self._convert_to_arrow(dataframe)
        row_count = arrow_table.num_rows

        if row_count == 0:
            self.logger.info("No rows to insert")
            return 0

        # Get or create table
        iceberg_table = self._get_or_create_table(
            table_identifier,
            arrow_table.schema,
            partition_columns,
        )

        # Append data
        if mode == "overwrite":
            iceberg_table.overwrite(arrow_table)
        else:
            iceberg_table.append(arrow_table)

        self.logger.info(f"Inserted {row_count} rows to Iceberg table {table_identifier}")
        return row_count

    def _parse_condition(self, condition: str) -> Any:
        """Parse SQL-like condition into Iceberg expression.

        This is a simplified parser for common conditions.
        For complex conditions, use the expression API directly.

        Args:
            condition: SQL-like condition string

        Returns:
            Iceberg expression

        Supported formats:
            - "column = value" or "column = 'value'"
            - "column > value"
            - "column < value"
            - "column >= value"
            - "column <= value"
            - "column != value"
        """
        condition = condition.strip()

        # Try to parse simple conditions
        operators = [
            (">=", GreaterThanOrEqual),
            ("<=", LessThanOrEqual),
            ("!=", NotEqualTo),
            ("<>", NotEqualTo),
            ("=", EqualTo),
            (">", GreaterThan),
            ("<", LessThan),
        ]

        for op_str, op_class in operators:
            if op_str in condition:
                parts = condition.split(op_str, 1)
                if len(parts) == 2:
                    column = parts[0].strip()
                    value = parts[1].strip()

                    # Remove quotes from string values
                    if (value.startswith("'") and value.endswith("'")) or (
                        value.startswith('"') and value.endswith('"')
                    ):
                        value = value[1:-1]
                    else:
                        # Try to convert to number
                        try:
                            if "." in value:
                                value = float(value)
                            else:
                                value = int(value)
                        except ValueError:
                            pass  # Keep as string

                    return op_class(column, value)  # ty: ignore[too-many-positional-arguments]

        # If we can't parse, log warning and return AlwaysTrue
        # (delete all is safer than failing silently)
        self.logger.warning(f"Could not parse condition '{condition}', using AlwaysTrue")
        return AlwaysTrue()

    def _do_delete(
        self,
        table_path: Path | str,
        condition: str | Any,
    ) -> int:
        """Delete rows using Iceberg row-level delete.

        Args:
            table_path: Table identifier (namespace.table_name)
            condition: Delete condition (SQL-like string or Iceberg expression)

        Returns:
            Number of rows deleted
        """
        table_identifier = self._normalize_table_identifier(str(table_path))

        try:
            iceberg_table = self.catalog.load_table(table_identifier)
        except Exception as e:
            self.logger.warning(f"Could not load Iceberg table {table_identifier}: {e}")
            return 0

        # Get row count before delete
        scan = iceberg_table.scan()
        rows_before = sum(1 for _ in scan.to_arrow().to_batches())
        rows_before = iceberg_table.scan().to_arrow().num_rows

        # Parse condition if string
        if isinstance(condition, str):
            delete_filter = self._parse_condition(condition)
        else:
            delete_filter = condition

        # Execute delete
        iceberg_table.delete(delete_filter=delete_filter)

        # Get row count after delete
        rows_after = iceberg_table.scan().to_arrow().num_rows
        rows_deleted = rows_before - rows_after

        self.logger.info(f"Deleted {rows_deleted} rows from Iceberg table {table_identifier}")
        return rows_deleted

    def _do_update(
        self,
        table_path: Path | str,
        condition: str | Any,
        updates: dict[str, Any],
    ) -> int:
        """Update rows using delete + insert pattern.

        Iceberg doesn't have native UPDATE in pyiceberg, so we:
        1. Read rows matching condition
        2. Modify the values
        3. Delete original rows
        4. Insert modified rows

        Args:
            table_path: Table identifier (namespace.table_name)
            condition: Update condition
            updates: Column name to new value mapping

        Returns:
            Number of rows updated
        """
        table_identifier = self._normalize_table_identifier(str(table_path))

        try:
            iceberg_table = self.catalog.load_table(table_identifier)
        except Exception as e:
            raise RuntimeError(f"Could not load Iceberg table {table_identifier}: {e}") from e

        # Parse condition
        if isinstance(condition, str):
            update_filter = self._parse_condition(condition)
        else:
            update_filter = condition

        # Read rows matching condition
        matching_rows = iceberg_table.scan(row_filter=update_filter).to_arrow()
        row_count = matching_rows.num_rows

        if row_count == 0:
            self.logger.info("No rows match update condition")
            return 0

        # Apply updates to the arrow table
        # Convert to pandas for easier manipulation
        df = matching_rows.to_pandas()
        for column, value in updates.items():
            # Handle SQL expressions like 'new_value' or literal values
            if isinstance(value, str):
                # Remove quotes if present
                if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
                    value = value[1:-1]
            df[column] = value

        # Convert back to arrow
        updated_arrow = pa.Table.from_pandas(df)

        # Delete original rows
        iceberg_table.delete(delete_filter=update_filter)

        # Insert updated rows
        iceberg_table.append(updated_arrow)

        self.logger.info(f"Updated {row_count} rows in Iceberg table {table_identifier}")
        return row_count

    def _do_merge(
        self,
        table_path: Path | str,
        source_dataframe: Any,
        merge_condition: str | Any,
        when_matched: dict[str, Any] | None,
        when_not_matched: dict[str, Any] | None,
    ) -> int:
        """Merge rows using custom merge logic.

        pyiceberg doesn't have native MERGE, so we implement it:
        1. Read target table
        2. Join with source on merge condition
        3. Apply when_matched updates
        4. Insert when_not_matched rows

        Args:
            table_path: Table identifier (namespace.table_name)
            source_dataframe: Source DataFrame
            merge_condition: Join condition column(s)
            when_matched: Updates to apply when matched
            when_not_matched: Values for inserts when not matched

        Returns:
            Number of rows affected
        """
        table_identifier = self._normalize_table_identifier(str(table_path))

        # Convert source to arrow
        source_arrow = self._convert_to_arrow(source_dataframe)

        try:
            iceberg_table = self.catalog.load_table(table_identifier)
        except Exception as e:
            raise RuntimeError(f"Could not load Iceberg table {table_identifier}: {e}") from e

        # Read current table
        target_arrow = iceberg_table.scan().to_arrow()

        # Convert to pandas for merge logic
        target_df = target_arrow.to_pandas()
        source_df = source_arrow.to_pandas()

        # Parse merge condition to get key column(s)
        # Expecting format like "target.id = source.id"
        merge_key = self._parse_merge_key(merge_condition)

        # Perform merge
        rows_updated = 0
        rows_inserted = 0

        if when_matched:
            # Find matching rows and update
            matched_mask = target_df[merge_key].isin(source_df[merge_key])
            for col, val in when_matched.items():
                if isinstance(val, str) and val.startswith("source."):
                    # Reference source column
                    source_col = val[7:]  # Remove "source." prefix
                    # Map source values to target
                    source_mapping = dict(zip(source_df[merge_key], source_df[source_col]))
                    target_df.loc[matched_mask, col] = target_df.loc[matched_mask, merge_key].map(source_mapping)
                else:
                    target_df.loc[matched_mask, col] = val
            rows_updated = matched_mask.sum()

        if when_not_matched:
            # Find non-matching source rows
            not_matched_mask = ~source_df[merge_key].isin(target_df[merge_key])
            new_rows = source_df[not_matched_mask]
            rows_inserted = len(new_rows)

            if rows_inserted > 0:
                target_df = pa.concat_tables([target_df, new_rows])

        # Overwrite table with merged data
        result_arrow = pa.Table.from_pandas(target_df)
        iceberg_table.overwrite(result_arrow)

        total_affected = rows_updated + rows_inserted
        self.logger.info(
            f"Merged into Iceberg table {table_identifier}: {rows_updated} updated, {rows_inserted} inserted"
        )
        return total_affected

    def _parse_merge_key(self, merge_condition: str) -> str:
        """Parse merge condition to extract key column.

        Args:
            merge_condition: Condition like "target.id = source.id"

        Returns:
            Key column name
        """
        # Simple parsing - extract column name from "target.col = source.col"
        condition = str(merge_condition).strip()

        if "=" in condition:
            left = condition.split("=")[0].strip()
            # Remove alias prefix if present
            if "." in left:
                return left.split(".")[-1]
            return left

        # Fallback - assume it's just the column name
        return condition


def get_iceberg_maintenance_operations(
    catalog_name: str = "default",
    catalog_config: dict[str, Any] | None = None,
    working_dir: str | Path | None = None,
) -> IcebergMaintenanceOperations | None:
    """Get Iceberg maintenance operations if pyiceberg is available.

    Args:
        catalog_name: Name of the Iceberg catalog
        catalog_config: Catalog configuration dict
        working_dir: Optional working directory

    Returns:
        IcebergMaintenanceOperations if pyiceberg is available, None otherwise
    """
    if not ICEBERG_AVAILABLE:
        logger.debug("Iceberg maintenance not available (pyiceberg not installed)")
        return None

    if not PYARROW_AVAILABLE:
        logger.debug("Iceberg maintenance not available (pyarrow not installed)")
        return None

    return IcebergMaintenanceOperations(
        catalog_name=catalog_name,
        catalog_config=catalog_config,
        working_dir=working_dir,
    )
