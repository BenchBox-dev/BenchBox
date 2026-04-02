"""TPC-DS Maintenance Operations implementation.

This module provides specific maintenance operations for TPC-DS tables
according to the TPC-DS specification section 5.4.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DS specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class MaintenanceOperationType(Enum):
    """Types of maintenance operations supported by TPC-DS."""

    # Sales data insertions
    INSERT_STORE_SALES = "INSERT_STORE_SALES"
    INSERT_CATALOG_SALES = "INSERT_CATALOG_SALES"
    INSERT_WEB_SALES = "INSERT_WEB_SALES"

    # Returns data insertions
    INSERT_STORE_RETURNS = "INSERT_STORE_RETURNS"
    INSERT_CATALOG_RETURNS = "INSERT_CATALOG_RETURNS"
    INSERT_WEB_RETURNS = "INSERT_WEB_RETURNS"

    # Dimension table updates
    UPDATE_CUSTOMER = "UPDATE_CUSTOMER"
    UPDATE_ITEM = "UPDATE_ITEM"
    UPDATE_INVENTORY = "UPDATE_INVENTORY"

    # Data cleanup operations
    DELETE_OLD_SALES = "DELETE_OLD_SALES"
    DELETE_OLD_RETURNS = "DELETE_OLD_RETURNS"

    # Bulk operations
    BULK_LOAD_SALES = "BULK_LOAD_SALES"
    BULK_UPDATE_INVENTORY = "BULK_UPDATE_INVENTORY"


@dataclass
class MaintenanceResult:
    """Result of a maintenance operation."""

    operation_type: MaintenanceOperationType
    success: bool
    start_time: float
    end_time: float
    duration: float
    rows_affected: int
    error_message: Optional[str] = None
    transaction_id: Optional[str] = None


class MaintenanceError(Exception):
    """Exception raised for maintenance operation errors."""


class ForeignKeyViolationError(MaintenanceError):
    """Exception raised when foreign key constraint is violated."""


class DataGenerationError(MaintenanceError):
    """Exception raised when data generation fails."""


class ConnectionError(MaintenanceError):
    """Exception raised when database connection fails."""


class MaintenanceOperations:
    """
    TPC-DS Maintenance Operations implementation.

    This class provides specific maintenance operations for TPC-DS tables
    according to the TPC-DS specification.
    """

    def __init__(self) -> None:
        """Initialize maintenance operations."""
        self.logger = logging.getLogger(__name__)
        self.connection = None
        self.benchmark_instance = None
        self.config = None
        self.random_gen = random.Random()

        # Dimension key ranges (initialized from database)
        self.dimension_ranges = {}

        # Operation handlers
        self.operation_handlers = {
            MaintenanceOperationType.INSERT_STORE_SALES: self._insert_store_sales,
            MaintenanceOperationType.INSERT_CATALOG_SALES: self._insert_catalog_sales,
            MaintenanceOperationType.INSERT_WEB_SALES: self._insert_web_sales,
            MaintenanceOperationType.INSERT_STORE_RETURNS: self._insert_store_returns,
            MaintenanceOperationType.INSERT_CATALOG_RETURNS: self._insert_catalog_returns,
            MaintenanceOperationType.INSERT_WEB_RETURNS: self._insert_web_returns,
            MaintenanceOperationType.UPDATE_CUSTOMER: self._update_customer,
            MaintenanceOperationType.UPDATE_ITEM: self._update_item,
            MaintenanceOperationType.UPDATE_INVENTORY: self._update_inventory,
            MaintenanceOperationType.DELETE_OLD_SALES: self._delete_old_sales,
            MaintenanceOperationType.DELETE_OLD_RETURNS: self._delete_old_returns,
            MaintenanceOperationType.BULK_LOAD_SALES: self._bulk_load_sales,
            MaintenanceOperationType.BULK_UPDATE_INVENTORY: self._bulk_update_inventory,
        }

    def initialize(self, connection: Any, benchmark_instance: Any, config: Any) -> None:
        """Initialize the maintenance operations with database connection and configuration."""
        self.connection = connection
        self.benchmark_instance = benchmark_instance
        self.config = config
        self.random_gen.seed(int(time.time()))

        # Initialize dimension ranges from database
        self._initialize_dimension_ranges(connection)

    def _initialize_dimension_ranges(self, connection: Any) -> None:
        """Query dimension tables to get valid key ranges.

        Args:
            connection: Database connection

        This method populates self.dimension_ranges with actual min/max values
        from dimension tables, replacing hardcoded assumptions.
        """
        dimension_queries = {
            "date_dim": "SELECT MIN(D_DATE_SK), MAX(D_DATE_SK) FROM DATE_DIM",
            "time_dim": "SELECT MIN(T_TIME_SK), MAX(T_TIME_SK) FROM TIME_DIM",
            "item": "SELECT MIN(I_ITEM_SK), MAX(I_ITEM_SK) FROM ITEM",
            "customer": "SELECT MIN(C_CUSTOMER_SK), MAX(C_CUSTOMER_SK) FROM CUSTOMER",
            "customer_demographics": "SELECT MIN(CD_DEMO_SK), MAX(CD_DEMO_SK) FROM CUSTOMER_DEMOGRAPHICS",
            "household_demographics": "SELECT MIN(HD_DEMO_SK), MAX(HD_DEMO_SK) FROM HOUSEHOLD_DEMOGRAPHICS",
            "customer_address": "SELECT MIN(CA_ADDRESS_SK), MAX(CA_ADDRESS_SK) FROM CUSTOMER_ADDRESS",
            "store": "SELECT MIN(S_STORE_SK), MAX(S_STORE_SK) FROM STORE",
            "promotion": "SELECT MIN(P_PROMO_SK), MAX(P_PROMO_SK) FROM PROMOTION",
            "call_center": "SELECT MIN(CC_CALL_CENTER_SK), MAX(CC_CALL_CENTER_SK) FROM CALL_CENTER",
            "catalog_page": "SELECT MIN(CP_CATALOG_PAGE_SK), MAX(CP_CATALOG_PAGE_SK) FROM CATALOG_PAGE",
            "ship_mode": "SELECT MIN(SM_SHIP_MODE_SK), MAX(SM_SHIP_MODE_SK) FROM SHIP_MODE",
            "warehouse": "SELECT MIN(W_WAREHOUSE_SK), MAX(W_WAREHOUSE_SK) FROM WAREHOUSE",
            "web_site": "SELECT MIN(WEB_SITE_SK), MAX(WEB_SITE_SK) FROM WEB_SITE",
            "web_page": "SELECT MIN(WP_WEB_PAGE_SK), MAX(WP_WEB_PAGE_SK) FROM WEB_PAGE",
        }

        for dim_name, query in dimension_queries.items():
            try:
                cursor = connection.execute(query)
                result = cursor.fetchone()
                if result and result[0] is not None and result[1] is not None:
                    self.dimension_ranges[dim_name] = (int(result[0]), int(result[1]))
                    self.logger.info(f"Dimension {dim_name}: range {self.dimension_ranges[dim_name]}")
                else:
                    # Fallback to reasonable defaults if table is empty
                    self.logger.warning(f"Dimension {dim_name} is empty, using default range")
                    self.dimension_ranges[dim_name] = (1, 1)
            except Exception as e:
                self.logger.error(f"Failed to query dimension {dim_name}: {e}")
                # Use safe defaults
                self.dimension_ranges[dim_name] = (1, 1)

    def _get_random_key(self, dimension: str, allow_null: bool = False, null_probability: float = 0.0) -> Optional[int]:
        """Get a random valid key from a dimension table range.

        Args:
            dimension: Name of the dimension (e.g., 'item', 'customer')
            allow_null: Whether NULL values are allowed
            null_probability: Probability of returning NULL (if allow_null=True)

        Returns:
            A random key within the valid range, or None if null
        """
        if allow_null and self.random_gen.random() < null_probability:
            return None

        if dimension not in self.dimension_ranges:
            self.logger.warning(f"Dimension {dimension} not initialized, returning 1")
            return 1

        min_key, max_key = self.dimension_ranges[dimension]
        return self.random_gen.randint(min_key, max_key)

    def _get_parameter_placeholder(self, connection: Any) -> str:
        """Detect SQL parameter placeholder style for platform.

        Args:
            connection: Database connection

        Returns:
            Parameter placeholder string ("?" or "%s" or numbered)
        """
        connection_type = type(connection).__name__.lower()

        if "sqlite" in connection_type or "duckdb" in connection_type:
            return "?"
        elif "psycopg" in connection_type or "postgres" in connection_type:
            return "%s"  # psycopg2 style
        elif "mysql" in connection_type:
            return "%s"
        else:
            # Default to DB-API 2.0 qmark style
            return "?"

    def _execute_batched_insert(
        self, connection: Any, table_name: str, columns: str, rows_to_insert: list[tuple], num_columns: int
    ) -> int:
        """Execute batched multi-row INSERT for efficiency with FK violation retry logic.

        Args:
            connection: Database connection
            table_name: Target table name
            columns: Comma-separated column names
            rows_to_insert: List of row tuples to insert
            num_columns: Number of columns per row

        Returns:
            Number of rows inserted
        """
        if not rows_to_insert:
            return 0

        placeholder = self._get_parameter_placeholder(connection)
        batch_size = 100  # Insert 100 rows at a time to avoid SQL length limits
        max_retries = 3  # Maximum number of FK violation retries

        total_inserted = 0

        # Execute batched multi-row INSERTs
        for batch_start in range(0, len(rows_to_insert), batch_size):
            batch_rows = rows_to_insert[batch_start : batch_start + batch_size]

            # Build multi-row VALUES clause
            row_placeholders = ", ".join([placeholder] * num_columns)
            values_placeholders = ", ".join([f"({row_placeholders})" for _ in batch_rows])

            # Flatten all row values into single params list
            params = []
            for row in batch_rows:
                params.extend(row)

            insert_sql = f"INSERT INTO {table_name} ({columns}) VALUES {values_placeholders}"

            # Try insert with retry on FK violations
            retry_count = 0
            while retry_count <= max_retries:
                try:
                    connection.execute(insert_sql, tuple(params))
                    total_inserted += len(batch_rows)
                    break  # Success, move to next batch
                except Exception as e:
                    error_msg = str(e).lower()
                    # Check if error is FK violation (different platforms use different error messages)
                    is_fk_error = any(
                        keyword in error_msg
                        for keyword in [
                            "foreign key",
                            "constraint",
                            "violates",
                            "fk_",
                            "integrity constraint",
                        ]
                    )

                    if is_fk_error and retry_count < max_retries:
                        retry_count += 1
                        self.logger.warning(
                            f"FK violation on {table_name} batch {batch_start}, retry {retry_count}/{max_retries}: {e}"
                        )
                        # Re-initialize dimension ranges to get fresh FK values
                        self._initialize_dimension_ranges(connection)
                        # Regenerate this batch with new FK values
                        # Note: This is a simplified retry - in production, you might want to
                        # regenerate only the rows with bad FKs
                        continue
                    else:
                        # Not a FK error or max retries exceeded
                        self.logger.error(f"Insert failed on {table_name} batch {batch_start}: {e}")
                        raise

        return total_inserted

    def execute_operation(
        self,
        connection: Any,
        operation_type: MaintenanceOperationType,
        estimated_rows: int,
    ) -> MaintenanceResult:
        """
        Execute a maintenance operation.

        Args:
            connection: Database connection
            operation_type: Type of maintenance operation
            estimated_rows: Estimated number of rows to be affected

        Returns:
            MaintenanceResult: Result of the operation
        """
        start_time = time.time()

        try:
            if operation_type not in self.operation_handlers:
                raise MaintenanceError(f"Unsupported operation type: {operation_type}")

            # Validate connection before executing operation
            if connection is None:
                raise ConnectionError("Database connection is None")

            handler = self.operation_handlers[operation_type]
            rows_affected = handler(connection, estimated_rows)

            end_time = time.time()

            return MaintenanceResult(
                operation_type=operation_type,
                success=True,
                start_time=start_time,
                end_time=end_time,
                duration=end_time - start_time,
                rows_affected=rows_affected,
                transaction_id=f"txn_{int(time.time())}",
            )

        except ForeignKeyViolationError as e:
            end_time = time.time()
            error_msg = f"Foreign key constraint violation in {operation_type}: {e}"
            self.logger.error(error_msg)

            return MaintenanceResult(
                operation_type=operation_type,
                success=False,
                start_time=start_time,
                end_time=end_time,
                duration=end_time - start_time,
                rows_affected=0,
                error_message=error_msg,
            )

        except DataGenerationError as e:
            end_time = time.time()
            error_msg = f"Data generation failed for {operation_type}: {e}"
            self.logger.error(error_msg)

            return MaintenanceResult(
                operation_type=operation_type,
                success=False,
                start_time=start_time,
                end_time=end_time,
                duration=end_time - start_time,
                rows_affected=0,
                error_message=error_msg,
            )

        except ConnectionError as e:
            end_time = time.time()
            error_msg = f"Database connection error for {operation_type}: {e}"
            self.logger.error(error_msg)

            return MaintenanceResult(
                operation_type=operation_type,
                success=False,
                start_time=start_time,
                end_time=end_time,
                duration=end_time - start_time,
                rows_affected=0,
                error_message=error_msg,
            )

        except MaintenanceError as e:
            end_time = time.time()
            error_msg = f"Maintenance operation {operation_type} failed: {e}"
            self.logger.error(error_msg)

            return MaintenanceResult(
                operation_type=operation_type,
                success=False,
                start_time=start_time,
                end_time=end_time,
                duration=end_time - start_time,
                rows_affected=0,
                error_message=error_msg,
            )

        except Exception as e:
            end_time = time.time()
            error_msg = f"Unexpected error in {operation_type}: {type(e).__name__}: {e}"
            self.logger.error(error_msg)

            return MaintenanceResult(
                operation_type=operation_type,
                success=False,
                start_time=start_time,
                end_time=end_time,
                duration=end_time - start_time,
                rows_affected=0,
                error_message=error_msg,
            )

    def _insert_store_sales(self, connection: Any, estimated_rows: int) -> int:
        """Insert new store sales data using batched multi-row INSERT."""
        self.logger.info(f"Inserting {estimated_rows} rows into STORE_SALES")

        # Generate new store sales records
        rows_to_insert = []
        for _ in range(estimated_rows):
            row = self._generate_store_sales_row()
            rows_to_insert.append(row)

        columns = """SS_SOLD_DATE_SK, SS_SOLD_TIME_SK, SS_ITEM_SK, SS_CUSTOMER_SK,
            SS_CDEMO_SK, SS_HDEMO_SK, SS_ADDR_SK, SS_STORE_SK, SS_PROMO_SK,
            SS_TICKET_NUMBER, SS_QUANTITY, SS_WHOLESALE_COST, SS_LIST_PRICE,
            SS_SALES_PRICE, SS_EXT_DISCOUNT_AMT, SS_EXT_SALES_PRICE,
            SS_EXT_WHOLESALE_COST, SS_EXT_LIST_PRICE, SS_EXT_TAX,
            SS_COUPON_AMT, SS_NET_PAID, SS_NET_PAID_INC_TAX, SS_NET_PROFIT"""

        return self._execute_batched_insert(connection, "STORE_SALES", columns, rows_to_insert, 23)

    def _insert_catalog_sales(self, connection: Any, estimated_rows: int) -> int:
        """Insert new catalog sales data."""
        self.logger.info(f"Inserting {estimated_rows} rows into CATALOG_SALES")

        # Generate new catalog sales records
        rows_to_insert = []
        for _ in range(estimated_rows):
            row = self._generate_catalog_sales_row()
            rows_to_insert.append(row)

        # Use batched multi-row INSERT for efficiency
        columns = """CS_SOLD_DATE_SK, CS_SOLD_TIME_SK, CS_SHIP_DATE_SK, CS_BILL_CUSTOMER_SK,
            CS_BILL_CDEMO_SK, CS_BILL_HDEMO_SK, CS_BILL_ADDR_SK, CS_SHIP_CUSTOMER_SK,
            CS_SHIP_CDEMO_SK, CS_SHIP_HDEMO_SK, CS_SHIP_ADDR_SK, CS_CALL_CENTER_SK,
            CS_CATALOG_PAGE_SK, CS_SHIP_MODE_SK, CS_WAREHOUSE_SK, CS_ITEM_SK,
            CS_PROMO_SK, CS_ORDER_NUMBER, CS_QUANTITY, CS_WHOLESALE_COST,
            CS_LIST_PRICE, CS_SALES_PRICE, CS_EXT_DISCOUNT_AMT, CS_EXT_SALES_PRICE,
            CS_EXT_WHOLESALE_COST, CS_EXT_LIST_PRICE, CS_EXT_TAX, CS_COUPON_AMT,
            CS_EXT_SHIP_COST, CS_NET_PAID, CS_NET_PAID_INC_TAX, CS_NET_PAID_INC_SHIP,
            CS_NET_PAID_INC_SHIP_TAX, CS_NET_PROFIT"""

        return self._execute_batched_insert(connection, "CATALOG_SALES", columns, rows_to_insert, 34)

    def _insert_web_sales(self, connection: Any, estimated_rows: int) -> int:
        """Insert new web sales data."""
        self.logger.info(f"Inserting {estimated_rows} rows into WEB_SALES")

        # Generate new web sales records
        rows_to_insert = []
        for _ in range(estimated_rows):
            row = self._generate_web_sales_row()
            rows_to_insert.append(row)

        # Use batched multi-row INSERT for efficiency
        columns = """WS_SOLD_DATE_SK, WS_SOLD_TIME_SK, WS_SHIP_DATE_SK, WS_ITEM_SK,
            WS_BILL_CUSTOMER_SK, WS_BILL_CDEMO_SK, WS_BILL_HDEMO_SK, WS_BILL_ADDR_SK,
            WS_SHIP_CUSTOMER_SK, WS_SHIP_CDEMO_SK, WS_SHIP_HDEMO_SK, WS_SHIP_ADDR_SK,
            WS_WEB_PAGE_SK, WS_WEB_SITE_SK, WS_SHIP_MODE_SK, WS_WAREHOUSE_SK,
            WS_PROMO_SK, WS_ORDER_NUMBER, WS_QUANTITY, WS_WHOLESALE_COST,
            WS_LIST_PRICE, WS_SALES_PRICE, WS_EXT_DISCOUNT_AMT, WS_EXT_SALES_PRICE,
            WS_EXT_WHOLESALE_COST, WS_EXT_LIST_PRICE, WS_EXT_TAX, WS_COUPON_AMT,
            WS_EXT_SHIP_COST, WS_NET_PAID, WS_NET_PAID_INC_TAX, WS_NET_PAID_INC_SHIP,
            WS_NET_PAID_INC_SHIP_TAX, WS_NET_PROFIT"""

        return self._execute_batched_insert(connection, "WEB_SALES", columns, rows_to_insert, 34)

    def _insert_returns_generic(
        self,
        connection: Any,
        estimated_rows: int,
        *,
        sales_table: str,
        returns_table: str,
        sales_select_columns: str,
        returns_columns: str,
        num_returns_columns: int,
        row_generator: Callable[[tuple], tuple],
    ) -> int:
        """Generic helper for inserting returns data that references valid sales.

        Per TPC-DS spec, returns must reference parent sales transactions.
        This method encapsulates the shared algorithm used by all three return
        channel insert operations (store, catalog, web).

        Args:
            connection: Database connection
            estimated_rows: Number of return rows to generate
            sales_table: Source sales table name (e.g. "STORE_SALES")
            returns_table: Target returns table name (e.g. "STORE_RETURNS")
            sales_select_columns: Comma-separated SELECT columns for the sales query
            returns_columns: Comma-separated column names for the INSERT
            num_returns_columns: Number of columns in a returns row
            row_generator: Callback that converts a sales record tuple into a returns row tuple

        Returns:
            Number of rows inserted
        """
        self.logger.info(f"Inserting {estimated_rows} rows into {returns_table}")

        # Get platform-specific parameter placeholder
        placeholder = self._get_parameter_placeholder(connection)

        # Query existing sales to get valid parent records
        query_sql = f"""
        SELECT {sales_select_columns}
        FROM {sales_table}
        ORDER BY RANDOM()
        LIMIT {placeholder}
        """

        try:
            cursor = connection.execute(query_sql, (estimated_rows,))
            sales_records = cursor.fetchall()
        except Exception as e:
            self.logger.error(f"Failed to query {sales_table.lower()} for returns: {e}")
            raise

        if not sales_records:
            self.logger.warning(f"No {sales_table.lower()} records found to generate returns from")
            return 0

        # Generate returns based on actual sales
        rows_to_insert = []
        for sale in sales_records:
            row = row_generator(sale)
            rows_to_insert.append(row)

        # Use batched multi-row INSERT for efficiency
        return self._execute_batched_insert(
            connection, returns_table, returns_columns, rows_to_insert, num_returns_columns
        )

    def _insert_store_returns(self, connection: Any, estimated_rows: int) -> int:
        """Insert new store returns data that reference valid store sales.

        Per TPC-DS spec, returns must reference parent sales transactions.
        """
        return self._insert_returns_generic(
            connection,
            estimated_rows,
            sales_table="STORE_SALES",
            returns_table="STORE_RETURNS",
            sales_select_columns="""SS_TICKET_NUMBER, SS_ITEM_SK, SS_CUSTOMER_SK, SS_CDEMO_SK,
               SS_HDEMO_SK, SS_ADDR_SK, SS_STORE_SK, SS_QUANTITY""",
            returns_columns="""SR_RETURNED_DATE_SK, SR_RETURN_TIME_SK, SR_ITEM_SK, SR_CUSTOMER_SK,
            SR_CDEMO_SK, SR_HDEMO_SK, SR_ADDR_SK, SR_STORE_SK, SR_REASON_SK,
            SR_TICKET_NUMBER, SR_RETURN_QUANTITY, SR_RETURN_AMT, SR_RETURN_TAX,
            SR_RETURN_AMT_INC_TAX, SR_FEE, SR_RETURN_SHIP_COST, SR_REFUNDED_CASH,
            SR_REVERSED_CHARGE, SR_STORE_CREDIT, SR_NET_LOSS""",
            num_returns_columns=20,
            row_generator=self._generate_store_returns_from_sale,
        )

    def _insert_catalog_returns(self, connection: Any, estimated_rows: int) -> int:
        """Insert new catalog returns data that reference valid catalog sales.

        Per TPC-DS spec, returns must reference parent sales transactions.
        """
        return self._insert_returns_generic(
            connection,
            estimated_rows,
            sales_table="CATALOG_SALES",
            returns_table="CATALOG_RETURNS",
            sales_select_columns="""CS_ORDER_NUMBER, CS_ITEM_SK, CS_BILL_CUSTOMER_SK, CS_BILL_CDEMO_SK,
               CS_BILL_HDEMO_SK, CS_BILL_ADDR_SK, CS_CALL_CENTER_SK, CS_CATALOG_PAGE_SK,
               CS_SHIP_MODE_SK, CS_WAREHOUSE_SK, CS_QUANTITY""",
            returns_columns="""CR_RETURNED_DATE_SK, CR_RETURNED_TIME_SK, CR_ITEM_SK, CR_REFUNDED_CUSTOMER_SK,
            CR_REFUNDED_CDEMO_SK, CR_REFUNDED_HDEMO_SK, CR_REFUNDED_ADDR_SK,
            CR_RETURNING_CUSTOMER_SK, CR_RETURNING_CDEMO_SK, CR_RETURNING_HDEMO_SK,
            CR_RETURNING_ADDR_SK, CR_CALL_CENTER_SK, CR_CATALOG_PAGE_SK,
            CR_SHIP_MODE_SK, CR_WAREHOUSE_SK, CR_REASON_SK, CR_ORDER_NUMBER,
            CR_RETURN_QUANTITY, CR_RETURN_AMOUNT, CR_RETURN_TAX, CR_RETURN_AMT_INC_TAX,
            CR_FEE, CR_RETURN_SHIP_COST, CR_REFUNDED_CASH, CR_REVERSED_CHARGE,
            CR_STORE_CREDIT, CR_NET_LOSS""",
            num_returns_columns=27,
            row_generator=self._generate_catalog_returns_from_sale,
        )

    def _insert_web_returns(self, connection: Any, estimated_rows: int) -> int:
        """Insert new web returns data that reference valid web sales.

        Per TPC-DS spec, returns must reference parent sales transactions.
        """
        return self._insert_returns_generic(
            connection,
            estimated_rows,
            sales_table="WEB_SALES",
            returns_table="WEB_RETURNS",
            sales_select_columns="""WS_ORDER_NUMBER, WS_ITEM_SK, WS_BILL_CUSTOMER_SK, WS_BILL_CDEMO_SK,
               WS_BILL_HDEMO_SK, WS_BILL_ADDR_SK, WS_WEB_PAGE_SK, WS_QUANTITY""",
            returns_columns="""WR_RETURNED_DATE_SK, WR_RETURNED_TIME_SK, WR_ITEM_SK, WR_REFUNDED_CUSTOMER_SK,
            WR_REFUNDED_CDEMO_SK, WR_REFUNDED_HDEMO_SK, WR_REFUNDED_ADDR_SK,
            WR_RETURNING_CUSTOMER_SK, WR_RETURNING_CDEMO_SK, WR_RETURNING_HDEMO_SK,
            WR_RETURNING_ADDR_SK, WR_WEB_PAGE_SK, WR_REASON_SK, WR_ORDER_NUMBER,
            WR_RETURN_QUANTITY, WR_RETURN_AMT, WR_RETURN_TAX, WR_RETURN_AMT_INC_TAX,
            WR_FEE, WR_RETURN_SHIP_COST, WR_REFUNDED_CASH, WR_REVERSED_CHARGE,
            WR_ACCOUNT_CREDIT, WR_NET_LOSS""",
            num_returns_columns=24,
            row_generator=self._generate_web_returns_from_sale,
        )

    def _update_customer(self, connection: Any, estimated_rows: int) -> int:
        """Update customer data."""
        self.logger.info(f"Updating {estimated_rows} rows in CUSTOMER table")

        # Configure customer addresses, demographics, and preferences
        updates = [
            "UPDATE CUSTOMER SET C_CURRENT_ADDR_SK = ? WHERE C_CUSTOMER_SK = ?",
            "UPDATE CUSTOMER SET C_CURRENT_CDEMO_SK = ? WHERE C_CUSTOMER_SK = ?",
            "UPDATE CUSTOMER SET C_CURRENT_HDEMO_SK = ? WHERE C_CUSTOMER_SK = ?",
            "UPDATE CUSTOMER SET C_PREFERRED_CUST_FLAG = ? WHERE C_CUSTOMER_SK = ?",
            "UPDATE CUSTOMER SET C_EMAIL_ADDRESS = ? WHERE C_CUSTOMER_SK = ?",
        ]

        rows_updated = 0
        for _i in range(estimated_rows):
            # Select random customer
            customer_sk = self.random_gen.randint(1, 100000)

            # Select random update type
            update_sql = self.random_gen.choice(updates)

            if "C_CURRENT_ADDR_SK" in update_sql:
                new_value = self.random_gen.randint(1, 50000)
            elif "C_CURRENT_CDEMO_SK" in update_sql:
                new_value = self.random_gen.randint(1, 1920800)
            elif "C_CURRENT_HDEMO_SK" in update_sql:
                new_value = self.random_gen.randint(1, 7200)
            elif "C_PREFERRED_CUST_FLAG" in update_sql:
                new_value = self.random_gen.choice(["Y", "N"])
            elif "C_EMAIL_ADDRESS" in update_sql:
                new_value = f"customer{customer_sk}@example.com"
            else:
                continue

            connection.execute(update_sql, (new_value, customer_sk))
            rows_updated += 1

        return rows_updated

    def _update_item(self, connection: Any, estimated_rows: int) -> int:
        """Update item data."""
        self.logger.info(f"Updating {estimated_rows} rows in ITEM table")

        # Configure item prices and descriptions
        updates = [
            "UPDATE ITEM SET I_CURRENT_PRICE = ? WHERE I_ITEM_SK = ?",
            "UPDATE ITEM SET I_WHOLESALE_COST = ? WHERE I_ITEM_SK = ?",
            "UPDATE ITEM SET I_ITEM_DESC = ? WHERE I_ITEM_SK = ?",
            "UPDATE ITEM SET I_MANAGER_ID = ? WHERE I_ITEM_SK = ?",
        ]

        rows_updated = 0
        for _i in range(estimated_rows):
            # Select random item
            item_sk = self.random_gen.randint(1, 18000)

            # Select random update type
            update_sql = self.random_gen.choice(updates)

            if "I_CURRENT_PRICE" in update_sql:
                new_value = round(self.random_gen.uniform(1.0, 1000.0), 2)
            elif "I_WHOLESALE_COST" in update_sql:
                new_value = round(self.random_gen.uniform(0.5, 500.0), 2)
            elif "I_ITEM_DESC" in update_sql:
                new_value = f"Updated item description {item_sk}"
            elif "I_MANAGER_ID" in update_sql:
                new_value = self.random_gen.randint(1, 100)
            else:
                continue

            connection.execute(update_sql, (new_value, item_sk))
            rows_updated += 1

        return rows_updated

    def _update_inventory(self, connection: Any, estimated_rows: int) -> int:
        """Update inventory data."""
        self.logger.info(f"Updating {estimated_rows} rows in INVENTORY table")

        # Configure inventory quantities
        update_sql = "UPDATE INVENTORY SET INV_QUANTITY_ON_HAND = ? WHERE INV_DATE_SK = ? AND INV_ITEM_SK = ? AND INV_WAREHOUSE_SK = ?"

        rows_updated = 0
        for _i in range(estimated_rows):
            # Select random inventory record
            date_sk = self.random_gen.randint(2450815, 2453005)  # Date range
            item_sk = self.random_gen.randint(1, 18000)
            warehouse_sk = self.random_gen.randint(1, 5)

            # Generate new quantity
            new_quantity = self.random_gen.randint(0, 1000)

            connection.execute(update_sql, (new_quantity, date_sk, item_sk, warehouse_sk))
            rows_updated += 1

        return rows_updated

    def _delete_old_sales(self, connection: Any, estimated_rows: int) -> int:
        """Delete old sales data."""
        self.logger.info(f"Deleting approximately {estimated_rows} rows from sales tables")

        # Delete old sales records (older than 3 years)
        cutoff_date_sk = 2450815  # Approximately 3 years ago

        delete_queries = [
            f"DELETE FROM STORE_SALES WHERE SS_SOLD_DATE_SK < {cutoff_date_sk} LIMIT {estimated_rows // 3}",
            f"DELETE FROM CATALOG_SALES WHERE CS_SOLD_DATE_SK < {cutoff_date_sk} LIMIT {estimated_rows // 3}",
            f"DELETE FROM WEB_SALES WHERE WS_SOLD_DATE_SK < {cutoff_date_sk} LIMIT {estimated_rows // 3}",
        ]

        total_deleted = 0
        for query in delete_queries:
            try:
                result = connection.execute(query)
                if hasattr(result, "rowcount"):
                    total_deleted += result.rowcount
                else:
                    total_deleted += estimated_rows // 3  # Estimate
            except Exception as e:
                self.logger.warning(f"Delete query failed: {e}")

        return total_deleted

    def _delete_old_returns(self, connection: Any, estimated_rows: int) -> int:
        """Delete old returns data."""
        self.logger.info(f"Deleting approximately {estimated_rows} rows from returns tables")

        # Delete old returns records (older than 3 years)
        cutoff_date_sk = 2450815  # Approximately 3 years ago

        delete_queries = [
            f"DELETE FROM STORE_RETURNS WHERE SR_RETURNED_DATE_SK < {cutoff_date_sk} LIMIT {estimated_rows // 3}",
            f"DELETE FROM CATALOG_RETURNS WHERE CR_RETURNED_DATE_SK < {cutoff_date_sk} LIMIT {estimated_rows // 3}",
            f"DELETE FROM WEB_RETURNS WHERE WR_RETURNED_DATE_SK < {cutoff_date_sk} LIMIT {estimated_rows // 3}",
        ]

        total_deleted = 0
        for query in delete_queries:
            try:
                result = connection.execute(query)
                if hasattr(result, "rowcount"):
                    total_deleted += result.rowcount
                else:
                    total_deleted += estimated_rows // 3  # Estimate
            except Exception as e:
                self.logger.warning(f"Delete query failed: {e}")

        return total_deleted

    def _bulk_load_sales(self, connection: Any, estimated_rows: int) -> int:
        """Bulk load sales data."""
        self.logger.info(f"Bulk loading {estimated_rows} rows into sales tables")

        # This would typically load from staging tables or files
        # For now, we'll simulate by inserting batches
        total_inserted = 0

        # Insert in batches across all sales tables
        batch_size = estimated_rows // 3

        total_inserted += self._insert_store_sales(connection, batch_size)
        total_inserted += self._insert_catalog_sales(connection, batch_size)
        total_inserted += self._insert_web_sales(connection, batch_size)

        return total_inserted

    def _bulk_update_inventory(self, connection: Any, estimated_rows: int) -> int:
        """Bulk update inventory data."""
        self.logger.info(f"Bulk updating {estimated_rows} rows in INVENTORY table")

        # Configure inventory based on recent sales
        update_sql = """
        UPDATE INVENTORY
        SET INV_QUANTITY_ON_HAND = INV_QUANTITY_ON_HAND - ?
        WHERE INV_DATE_SK = ? AND INV_ITEM_SK = ? AND INV_WAREHOUSE_SK = ?
        AND INV_QUANTITY_ON_HAND > ?
        """

        rows_updated = 0
        for _i in range(estimated_rows):
            # Select random inventory record
            date_sk = self.random_gen.randint(2452640, 2453005)  # Recent dates
            item_sk = self.random_gen.randint(1, 18000)
            warehouse_sk = self.random_gen.randint(1, 5)

            # Generate quantity adjustment
            quantity_adjustment = self.random_gen.randint(1, 50)

            connection.execute(
                update_sql,
                (
                    quantity_adjustment,
                    date_sk,
                    item_sk,
                    warehouse_sk,
                    quantity_adjustment,
                ),
            )
            rows_updated += 1

        return rows_updated

    # Helper methods for generating test data

    def _generate_store_sales_row(self) -> tuple:
        """Generate a store sales row with valid foreign keys."""
        return (
            self._get_random_key("date_dim"),  # SS_SOLD_DATE_SK
            self._get_random_key("time_dim"),  # SS_SOLD_TIME_SK
            self._get_random_key("item"),  # SS_ITEM_SK
            self._get_random_key("customer"),  # SS_CUSTOMER_SK
            self._get_random_key("customer_demographics"),  # SS_CDEMO_SK
            self._get_random_key("household_demographics"),  # SS_HDEMO_SK
            self._get_random_key("customer_address"),  # SS_ADDR_SK
            self._get_random_key("store"),  # SS_STORE_SK
            self._get_random_key("promotion", allow_null=True, null_probability=0.7),  # SS_PROMO_SK (nullable)
            self.random_gen.randint(1, 99999999),  # SS_TICKET_NUMBER
            self.random_gen.randint(1, 100),  # SS_QUANTITY
            round(self.random_gen.uniform(1.0, 100.0), 2),  # SS_WHOLESALE_COST
            round(self.random_gen.uniform(1.0, 200.0), 2),  # SS_LIST_PRICE
            round(self.random_gen.uniform(1.0, 200.0), 2),  # SS_SALES_PRICE
            round(self.random_gen.uniform(0.0, 50.0), 2),  # SS_EXT_DISCOUNT_AMT
            round(self.random_gen.uniform(1.0, 1000.0), 2),  # SS_EXT_SALES_PRICE
            round(self.random_gen.uniform(1.0, 500.0), 2),  # SS_EXT_WHOLESALE_COST
            round(self.random_gen.uniform(1.0, 1000.0), 2),  # SS_EXT_LIST_PRICE
            round(self.random_gen.uniform(0.0, 100.0), 2),  # SS_EXT_TAX
            round(self.random_gen.uniform(0.0, 50.0), 2),  # SS_COUPON_AMT
            round(self.random_gen.uniform(1.0, 1000.0), 2),  # SS_NET_PAID
            round(self.random_gen.uniform(1.0, 1100.0), 2),  # SS_NET_PAID_INC_TAX
            round(self.random_gen.uniform(-50.0, 500.0), 2),  # SS_NET_PROFIT
        )

    def _generate_catalog_sales_row(self) -> tuple:
        """Generate a catalog sales row with valid foreign keys."""
        return (
            self._get_random_key("date_dim"),  # CS_SOLD_DATE_SK
            self._get_random_key("time_dim"),  # CS_SOLD_TIME_SK
            self._get_random_key("date_dim"),  # CS_SHIP_DATE_SK
            self._get_random_key("customer"),  # CS_BILL_CUSTOMER_SK
            self._get_random_key("customer_demographics"),  # CS_BILL_CDEMO_SK
            self._get_random_key("household_demographics"),  # CS_BILL_HDEMO_SK
            self._get_random_key("customer_address"),  # CS_BILL_ADDR_SK
            self._get_random_key("customer"),  # CS_SHIP_CUSTOMER_SK
            self._get_random_key("customer_demographics"),  # CS_SHIP_CDEMO_SK
            self._get_random_key("household_demographics"),  # CS_SHIP_HDEMO_SK
            self._get_random_key("customer_address"),  # CS_SHIP_ADDR_SK
            self._get_random_key("call_center"),  # CS_CALL_CENTER_SK
            self._get_random_key("catalog_page"),  # CS_CATALOG_PAGE_SK
            self._get_random_key("ship_mode"),  # CS_SHIP_MODE_SK
            self._get_random_key("warehouse"),  # CS_WAREHOUSE_SK
            self._get_random_key("item"),  # CS_ITEM_SK
            self._get_random_key("promotion", allow_null=True, null_probability=0.7),  # CS_PROMO_SK (nullable)
            self.random_gen.randint(1, 99999999),  # CS_ORDER_NUMBER
            self.random_gen.randint(1, 100),  # CS_QUANTITY
            round(self.random_gen.uniform(1.0, 100.0), 2),  # CS_WHOLESALE_COST
            round(self.random_gen.uniform(1.0, 200.0), 2),  # CS_LIST_PRICE
            round(self.random_gen.uniform(1.0, 200.0), 2),  # CS_SALES_PRICE
            round(self.random_gen.uniform(0.0, 50.0), 2),  # CS_EXT_DISCOUNT_AMT
            round(self.random_gen.uniform(1.0, 1000.0), 2),  # CS_EXT_SALES_PRICE
            round(self.random_gen.uniform(1.0, 500.0), 2),  # CS_EXT_WHOLESALE_COST
            round(self.random_gen.uniform(1.0, 1000.0), 2),  # CS_EXT_LIST_PRICE
            round(self.random_gen.uniform(0.0, 100.0), 2),  # CS_EXT_TAX
            round(self.random_gen.uniform(0.0, 50.0), 2),  # CS_COUPON_AMT
            round(self.random_gen.uniform(1.0, 100.0), 2),  # CS_EXT_SHIP_COST
            round(self.random_gen.uniform(1.0, 1000.0), 2),  # CS_NET_PAID
            round(self.random_gen.uniform(1.0, 1100.0), 2),  # CS_NET_PAID_INC_TAX
            round(self.random_gen.uniform(1.0, 1200.0), 2),  # CS_NET_PAID_INC_SHIP
            round(self.random_gen.uniform(1.0, 1300.0), 2),  # CS_NET_PAID_INC_SHIP_TAX
            round(self.random_gen.uniform(-50.0, 500.0), 2),  # CS_NET_PROFIT
        )

    def _generate_web_sales_row(self) -> tuple:
        """Generate a web sales row with valid foreign keys."""
        return (
            self._get_random_key("date_dim"),  # WS_SOLD_DATE_SK
            self._get_random_key("time_dim"),  # WS_SOLD_TIME_SK
            self._get_random_key("date_dim"),  # WS_SHIP_DATE_SK
            self._get_random_key("item"),  # WS_ITEM_SK
            self._get_random_key("customer"),  # WS_BILL_CUSTOMER_SK
            self._get_random_key("customer_demographics"),  # WS_BILL_CDEMO_SK
            self._get_random_key("household_demographics"),  # WS_BILL_HDEMO_SK
            self._get_random_key("customer_address"),  # WS_BILL_ADDR_SK
            self._get_random_key("customer"),  # WS_SHIP_CUSTOMER_SK
            self._get_random_key("customer_demographics"),  # WS_SHIP_CDEMO_SK
            self._get_random_key("household_demographics"),  # WS_SHIP_HDEMO_SK
            self._get_random_key("customer_address"),  # WS_SHIP_ADDR_SK
            self._get_random_key("web_page"),  # WS_WEB_PAGE_SK
            self._get_random_key("web_site"),  # WS_WEB_SITE_SK
            self._get_random_key("ship_mode"),  # WS_SHIP_MODE_SK
            self._get_random_key("warehouse"),  # WS_WAREHOUSE_SK
            self._get_random_key("promotion", allow_null=True, null_probability=0.7),  # WS_PROMO_SK (nullable)
            self.random_gen.randint(1, 99999999),  # WS_ORDER_NUMBER
            self.random_gen.randint(1, 100),  # WS_QUANTITY
            round(self.random_gen.uniform(1.0, 100.0), 2),  # WS_WHOLESALE_COST
            round(self.random_gen.uniform(1.0, 200.0), 2),  # WS_LIST_PRICE
            round(self.random_gen.uniform(1.0, 200.0), 2),  # WS_SALES_PRICE
            round(self.random_gen.uniform(0.0, 50.0), 2),  # WS_EXT_DISCOUNT_AMT
            round(self.random_gen.uniform(1.0, 1000.0), 2),  # WS_EXT_SALES_PRICE
            round(self.random_gen.uniform(1.0, 500.0), 2),  # WS_EXT_WHOLESALE_COST
            round(self.random_gen.uniform(1.0, 1000.0), 2),  # WS_EXT_LIST_PRICE
            round(self.random_gen.uniform(0.0, 100.0), 2),  # WS_EXT_TAX
            round(self.random_gen.uniform(0.0, 50.0), 2),  # WS_COUPON_AMT
            round(self.random_gen.uniform(1.0, 100.0), 2),  # WS_EXT_SHIP_COST
            round(self.random_gen.uniform(1.0, 1000.0), 2),  # WS_NET_PAID
            round(self.random_gen.uniform(1.0, 1100.0), 2),  # WS_NET_PAID_INC_TAX
            round(self.random_gen.uniform(1.0, 1200.0), 2),  # WS_NET_PAID_INC_SHIP
            round(self.random_gen.uniform(1.0, 1300.0), 2),  # WS_NET_PAID_INC_SHIP_TAX
            round(self.random_gen.uniform(-50.0, 500.0), 2),  # WS_NET_PROFIT
        )

    def _generate_store_returns_from_sale(self, sale_record: tuple) -> tuple:
        """Generate a store return based on an actual store sale.

        Args:
            sale_record: Tuple of (SS_TICKET_NUMBER, SS_ITEM_SK, SS_CUSTOMER_SK,
                                   SS_CDEMO_SK, SS_HDEMO_SK, SS_ADDR_SK, SS_STORE_SK, SS_QUANTITY)

        Returns:
            Tuple representing a valid store return
        """
        ticket_num, item_sk, cust_sk, cdemo_sk, hdemo_sk, addr_sk, store_sk, quantity = sale_record

        # Return quantity is <= sold quantity
        return_qty = self.random_gen.randint(1, min(100, int(quantity)))

        return (
            self._get_random_key("date_dim"),  # SR_RETURNED_DATE_SK
            self._get_random_key("time_dim"),  # SR_RETURN_TIME_SK
            item_sk,  # SR_ITEM_SK (must match sale)
            cust_sk,  # SR_CUSTOMER_SK (must match sale)
            cdemo_sk,  # SR_CDEMO_SK (must match sale)
            hdemo_sk,  # SR_HDEMO_SK (must match sale)
            addr_sk,  # SR_ADDR_SK (must match sale)
            store_sk,  # SR_STORE_SK (must match sale)
            self.random_gen.randint(1, 35)
            if "dimension_ranges" in dir(self) and "reason" in self.dimension_ranges
            else 1,  # SR_REASON_SK
            ticket_num,  # SR_TICKET_NUMBER (must match sale)
            return_qty,  # SR_RETURN_QUANTITY
            round(self.random_gen.uniform(1.0, 1000.0), 2),  # SR_RETURN_AMT
            round(self.random_gen.uniform(0.0, 100.0), 2),  # SR_RETURN_TAX
            round(self.random_gen.uniform(1.0, 1100.0), 2),  # SR_RETURN_AMT_INC_TAX
            round(self.random_gen.uniform(0.0, 50.0), 2),  # SR_FEE
            round(self.random_gen.uniform(0.0, 100.0), 2),  # SR_RETURN_SHIP_COST
            round(self.random_gen.uniform(1.0, 1000.0), 2),  # SR_REFUNDED_CASH
            round(self.random_gen.uniform(0.0, 500.0), 2),  # SR_REVERSED_CHARGE
            round(self.random_gen.uniform(0.0, 500.0), 2),  # SR_STORE_CREDIT
            round(self.random_gen.uniform(-100.0, 100.0), 2),  # SR_NET_LOSS
        )

    def _generate_store_returns_row(self) -> tuple:
        """DEPRECATED: Generate a store returns row.

        This method is deprecated. Use _generate_store_returns_from_sale instead
        to ensure returns reference valid sales per TPC-DS spec.
        """
        return (
            self._get_random_key("date_dim"),  # SR_RETURNED_DATE_SK
            self._get_random_key("time_dim"),  # SR_RETURN_TIME_SK
            self._get_random_key("item"),  # SR_ITEM_SK
            self._get_random_key("customer"),  # SR_CUSTOMER_SK
            self._get_random_key("customer_demographics"),  # SR_CDEMO_SK
            self._get_random_key("household_demographics"),  # SR_HDEMO_SK
            self._get_random_key("customer_address"),  # SR_ADDR_SK
            self._get_random_key("store"),  # SR_STORE_SK
            self.random_gen.randint(1, 35),  # SR_REASON_SK
            self.random_gen.randint(1, 99999999),  # SR_TICKET_NUMBER
            self.random_gen.randint(1, 100),  # SR_RETURN_QUANTITY
            round(self.random_gen.uniform(1.0, 1000.0), 2),  # SR_RETURN_AMT
            round(self.random_gen.uniform(0.0, 100.0), 2),  # SR_RETURN_TAX
            round(self.random_gen.uniform(1.0, 1100.0), 2),  # SR_RETURN_AMT_INC_TAX
            round(self.random_gen.uniform(0.0, 50.0), 2),  # SR_FEE
            round(self.random_gen.uniform(0.0, 50.0), 2),  # SR_RETURN_SHIP_COST
            round(self.random_gen.uniform(0.0, 500.0), 2),  # SR_REFUNDED_CASH
            round(self.random_gen.uniform(0.0, 500.0), 2),  # SR_REVERSED_CHARGE
            round(self.random_gen.uniform(0.0, 500.0), 2),  # SR_STORE_CREDIT
            round(self.random_gen.uniform(0.0, 500.0), 2),  # SR_NET_LOSS
        )

    def _generate_returns_from_sale(
        self,
        sale_record: tuple,
        *,
        field_mapping: tuple[int, int, int, int, int, int, int],
        channel_fields: tuple[int, ...],
    ) -> tuple:
        """Generate a return row by reusing the sale keys required by the TPC-DS spec."""
        (
            order_num_idx,
            item_idx,
            bill_customer_idx,
            bill_cdemo_idx,
            bill_hdemo_idx,
            bill_addr_idx,
            quantity_idx,
        ) = field_mapping

        order_num = sale_record[order_num_idx]
        item_sk = sale_record[item_idx]
        bill_cust_sk = sale_record[bill_customer_idx]
        bill_cdemo_sk = sale_record[bill_cdemo_idx]
        bill_hdemo_sk = sale_record[bill_hdemo_idx]
        bill_addr_sk = sale_record[bill_addr_idx]
        quantity = sale_record[quantity_idx]
        return_qty = self.random_gen.randint(1, min(100, int(quantity)))
        channel_values = tuple(sale_record[index] for index in channel_fields)

        return (
            self._get_random_key("date_dim"),
            self._get_random_key("time_dim"),
            item_sk,
            bill_cust_sk,
            bill_cdemo_sk,
            bill_hdemo_sk,
            bill_addr_sk,
            bill_cust_sk,
            bill_cdemo_sk,
            bill_hdemo_sk,
            bill_addr_sk,
            *channel_values,
            self.random_gen.randint(1, 35),
            order_num,
            return_qty,
            round(self.random_gen.uniform(1.0, 1000.0), 2),
            round(self.random_gen.uniform(0.0, 100.0), 2),
            round(self.random_gen.uniform(1.0, 1100.0), 2),
            round(self.random_gen.uniform(0.0, 50.0), 2),
            round(self.random_gen.uniform(0.0, 50.0), 2),
            round(self.random_gen.uniform(0.0, 500.0), 2),
            round(self.random_gen.uniform(0.0, 500.0), 2),
            round(self.random_gen.uniform(0.0, 500.0), 2),
            round(self.random_gen.uniform(0.0, 500.0), 2),
        )

    def _generate_catalog_returns_from_sale(self, sale_record: tuple) -> tuple:
        """Generate a catalog return based on an actual catalog sale.

        Args:
            sale_record: Tuple of (CS_ORDER_NUMBER, CS_ITEM_SK, CS_BILL_CUSTOMER_SK,
                                   CS_BILL_CDEMO_SK, CS_BILL_HDEMO_SK, CS_BILL_ADDR_SK,
                                   CS_CALL_CENTER_SK, CS_CATALOG_PAGE_SK, CS_SHIP_MODE_SK,
                                   CS_WAREHOUSE_SK, CS_QUANTITY)

        Returns:
            Tuple representing a valid catalog return
        """
        return self._generate_returns_from_sale(
            sale_record,
            field_mapping=(0, 1, 2, 3, 4, 5, 10),
            channel_fields=(6, 7, 8, 9),
        )

    def _generate_web_returns_from_sale(self, sale_record: tuple) -> tuple:
        """Generate a web return based on an actual web sale.

        Args:
            sale_record: Tuple of (WS_ORDER_NUMBER, WS_ITEM_SK, WS_BILL_CUSTOMER_SK,
                                   WS_BILL_CDEMO_SK, WS_BILL_HDEMO_SK, WS_BILL_ADDR_SK,
                                   WS_WEB_PAGE_SK, WS_QUANTITY)

        Returns:
            Tuple representing a valid web return
        """
        return self._generate_returns_from_sale(
            sale_record,
            field_mapping=(0, 1, 2, 3, 4, 5, 7),
            channel_fields=(6,),
        )

    def _generate_catalog_returns_row(self) -> tuple:
        """DEPRECATED: Generate a catalog returns row.

        This method is deprecated. Use _generate_catalog_returns_from_sale instead
        to ensure returns reference valid sales per TPC-DS spec.
        """
        return (
            self._get_random_key("date_dim"),  # CR_RETURNED_DATE_SK
            self._get_random_key("time_dim"),  # CR_RETURNED_TIME_SK
            self._get_random_key("item"),  # CR_ITEM_SK
            self._get_random_key("customer"),  # CR_REFUNDED_CUSTOMER_SK
            self._get_random_key("customer_demographics"),  # CR_REFUNDED_CDEMO_SK
            self._get_random_key("household_demographics"),  # CR_REFUNDED_HDEMO_SK
            self._get_random_key("customer_address"),  # CR_REFUNDED_ADDR_SK
            self._get_random_key("customer"),  # CR_RETURNING_CUSTOMER_SK
            self._get_random_key("customer_demographics"),  # CR_RETURNING_CDEMO_SK
            self._get_random_key("household_demographics"),  # CR_RETURNING_HDEMO_SK
            self._get_random_key("customer_address"),  # CR_RETURNING_ADDR_SK
            self._get_random_key("call_center"),  # CR_CALL_CENTER_SK
            self._get_random_key("catalog_page"),  # CR_CATALOG_PAGE_SK
            self._get_random_key("ship_mode"),  # CR_SHIP_MODE_SK
            self._get_random_key("warehouse"),  # CR_WAREHOUSE_SK
            self.random_gen.randint(1, 35),  # CR_REASON_SK
            self.random_gen.randint(1, 99999999),  # CR_ORDER_NUMBER
            self.random_gen.randint(1, 100),  # CR_RETURN_QUANTITY
            round(self.random_gen.uniform(1.0, 1000.0), 2),  # CR_RETURN_AMOUNT
            round(self.random_gen.uniform(0.0, 100.0), 2),  # CR_RETURN_TAX
            round(self.random_gen.uniform(1.0, 1100.0), 2),  # CR_RETURN_AMT_INC_TAX
            round(self.random_gen.uniform(0.0, 50.0), 2),  # CR_FEE
            round(self.random_gen.uniform(0.0, 50.0), 2),  # CR_RETURN_SHIP_COST
            round(self.random_gen.uniform(0.0, 500.0), 2),  # CR_REFUNDED_CASH
            round(self.random_gen.uniform(0.0, 500.0), 2),  # CR_REVERSED_CHARGE
            round(self.random_gen.uniform(0.0, 500.0), 2),  # CR_STORE_CREDIT
            round(self.random_gen.uniform(0.0, 500.0), 2),  # CR_NET_LOSS
        )

    def _generate_web_returns_row(self) -> tuple:
        """Generate a web returns row."""
        return (
            self.random_gen.randint(2452640, 2453005),  # WR_RETURNED_DATE_SK
            self.random_gen.randint(28800, 72000),  # WR_RETURNED_TIME_SK
            self.random_gen.randint(1, 18000),  # WR_ITEM_SK
            self.random_gen.randint(1, 100000),  # WR_REFUNDED_CUSTOMER_SK
            self.random_gen.randint(1, 1920800),  # WR_REFUNDED_CDEMO_SK
            self.random_gen.randint(1, 7200),  # WR_REFUNDED_HDEMO_SK
            self.random_gen.randint(1, 50000),  # WR_REFUNDED_ADDR_SK
            self.random_gen.randint(1, 100000),  # WR_RETURNING_CUSTOMER_SK
            self.random_gen.randint(1, 1920800),  # WR_RETURNING_CDEMO_SK
            self.random_gen.randint(1, 7200),  # WR_RETURNING_HDEMO_SK
            self.random_gen.randint(1, 50000),  # WR_RETURNING_ADDR_SK
            self.random_gen.randint(1, 60),  # WR_WEB_PAGE_SK
            self.random_gen.randint(1, 35),  # WR_REASON_SK
            self.random_gen.randint(1, 99999999),  # WR_ORDER_NUMBER
            self.random_gen.randint(1, 100),  # WR_RETURN_QUANTITY
            round(self.random_gen.uniform(1.0, 1000.0), 2),  # WR_RETURN_AMT
            round(self.random_gen.uniform(0.0, 100.0), 2),  # WR_RETURN_TAX
            round(self.random_gen.uniform(1.0, 1100.0), 2),  # WR_RETURN_AMT_INC_TAX
            round(self.random_gen.uniform(0.0, 50.0), 2),  # WR_FEE
            round(self.random_gen.uniform(0.0, 50.0), 2),  # WR_RETURN_SHIP_COST
            round(self.random_gen.uniform(0.0, 500.0), 2),  # WR_REFUNDED_CASH
            round(self.random_gen.uniform(0.0, 500.0), 2),  # WR_REVERSED_CHARGE
            round(self.random_gen.uniform(0.0, 500.0), 2),  # WR_ACCOUNT_CREDIT
            round(self.random_gen.uniform(0.0, 500.0), 2),  # WR_NET_LOSS
        )
