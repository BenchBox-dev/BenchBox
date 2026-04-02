"""TPC-DI data loading system.

Provides comprehensive data loading capabilities for TPC-DI benchmarks, including optimized bulk loading, index management, and data preprocessing.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DI (TPC-DI) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DI specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Union, cast

import pandas as pd
import sqlglot

from benchbox.utils.clock import elapsed_seconds, mono_time

logger = logging.getLogger(__name__)


@dataclass
class LoadResult:
    """Result of a data loading operation."""

    table_name: str
    records_loaded: int = 0
    load_time: float = 0.0
    success: bool = False
    error_message: Optional[str] = None
    pre_load_count: int = 0
    post_load_count: int = 0


class TPCDIDataLoader:
    """High-performance data loader for TPC-DI with database-agnostic support."""

    def __init__(self, connection: Any, dialect: str = "duckdb", batch_size: int = 10000):
        self.connection = connection
        self.dialect = dialect
        self.batch_size = batch_size

    def _load_data(
        self,
        table_name: str,
        data: Union[list[dict], pd.DataFrame, Any],
        table_kind: str,
        insert_fn: Callable[[str, list[dict]], int],
    ) -> LoadResult:
        """Load normalized data into a table using the provided insert strategy."""
        logger.info(f"Loading data into {table_kind} table {table_name}")

        result = LoadResult(table_name=table_name)
        start_time = mono_time()

        try:
            result.pre_load_count = self._get_table_count(table_name)
            records = self._normalize_data_format(data)

            if not records:
                logger.warning(f"No data to load for table {table_name}")
                result.success = True
                return result

            loaded_count = insert_fn(table_name, records)
            result.post_load_count = self._get_table_count(table_name)
            result.records_loaded = loaded_count
            result.load_time = elapsed_seconds(start_time)
            result.success = True

            logger.info(f"Successfully loaded {loaded_count:,} records into {table_name} in {result.load_time:.2f}s")
        except Exception as e:
            result.error_message = str(e)
            result.load_time = elapsed_seconds(start_time)
            logger.error(f"Failed to load data into {table_name}: {e}")

        return result

    def load_dimension_data(self, table_name: str, data: Union[list[dict], pd.DataFrame, Any]) -> LoadResult:
        """Load data into dimension table.

        Args:
            table_name: Target dimension table name
            data: Data to load (list of dicts, DataFrame, etc.)

        Returns:
            LoadResult with loading statistics
        """
        return self._load_data(
            table_name=table_name,
            data=data,
            table_kind="dimension",
            insert_fn=self._bulk_insert,
        )

    def load_fact_data(self, table_name: str, data: Union[list[dict], pd.DataFrame, Any]) -> LoadResult:
        """Load data into fact table.

        Args:
            table_name: Target fact table name
            data: Data to load

        Returns:
            LoadResult with loading statistics
        """
        return self._load_data(
            table_name=table_name,
            data=data,
            table_kind="fact",
            insert_fn=self._batch_insert_fact_data,
        )

    def load_csv_file(self, table_name: str, file_path: Path, delimiter: str = ",") -> LoadResult:
        """Load data from CSV file into table.

        Args:
            table_name: Target table name
            file_path: Path to CSV file
            delimiter: CSV delimiter

        Returns:
            LoadResult with loading statistics
        """
        logger.info(f"Loading CSV file {file_path} into {table_name}")

        result = LoadResult(table_name=table_name)
        start_time = mono_time()

        try:
            if not file_path.exists():
                raise FileNotFoundError(f"CSV file not found: {file_path}")

            # Read CSV data
            data = []
            with open(file_path, newline="", encoding="utf-8") as csvfile:
                reader = csv.DictReader(csvfile, delimiter=delimiter)
                for row in reader:
                    data.append(row)

            if not data:
                logger.warning(f"No data found in CSV file {file_path}")
                result.success = True
                return result

            # Load the data
            load_result = self.load_dimension_data(table_name, data)

            # Copy results
            result.records_loaded = load_result.records_loaded
            result.success = load_result.success
            result.error_message = load_result.error_message
            result.pre_load_count = load_result.pre_load_count
            result.post_load_count = load_result.post_load_count
            result.load_time = elapsed_seconds(start_time)

        except Exception as e:
            result.error_message = str(e)
            result.load_time = elapsed_seconds(start_time)
            logger.error(f"Failed to load CSV file {file_path}: {e}")

        return result

    def create_indexes(self, connection: Any) -> dict[str, bool]:
        """Create performance indexes on TPC-DI tables.

        Args:
            connection: Database connection

        Returns:
            Dict mapping index names to success status
        """
        logger.info("Creating performance indexes for TPC-DI tables")

        # Define indexes for query performance
        indexes = {
            # Customer dimension indexes
            "idx_dimcustomer_customerid": "CREATE INDEX IF NOT EXISTS idx_dimcustomer_customerid ON DimCustomer(CustomerID)",
            "idx_dimcustomer_current": "CREATE INDEX IF NOT EXISTS idx_dimcustomer_current ON DimCustomer(IsCurrent)",
            "idx_dimcustomer_batch": "CREATE INDEX IF NOT EXISTS idx_dimcustomer_batch ON DimCustomer(BatchID)",
            # Account dimension indexes
            "idx_dimaccount_accountid": "CREATE INDEX IF NOT EXISTS idx_dimaccount_accountid ON DimAccount(AccountID)",
            "idx_dimaccount_customer": "CREATE INDEX IF NOT EXISTS idx_dimaccount_customer ON DimAccount(SK_CustomerID)",
            "idx_dimaccount_current": "CREATE INDEX IF NOT EXISTS idx_dimaccount_current ON DimAccount(IsCurrent)",
            # Security dimension indexes
            "idx_dimsecurity_symbol": "CREATE INDEX IF NOT EXISTS idx_dimsecurity_symbol ON DimSecurity(Symbol)",
            "idx_dimsecurity_company": "CREATE INDEX IF NOT EXISTS idx_dimsecurity_company ON DimSecurity(SK_CompanyID)",
            "idx_dimsecurity_current": "CREATE INDEX IF NOT EXISTS idx_dimsecurity_current ON DimSecurity(IsCurrent)",
            # Company dimension indexes
            "idx_dimcompany_companyid": "CREATE INDEX IF NOT EXISTS idx_dimcompany_companyid ON DimCompany(CompanyID)",
            "idx_dimcompany_current": "CREATE INDEX IF NOT EXISTS idx_dimcompany_current ON DimCompany(IsCurrent)",
            # Date dimension indexes
            "idx_dimdate_date": "CREATE INDEX IF NOT EXISTS idx_dimdate_date ON DimDate(DateValue)",
            "idx_dimdate_year": "CREATE INDEX IF NOT EXISTS idx_dimdate_year ON DimDate(CalendarYearID)",
            # Time dimension indexes
            "idx_dimtime_time": "CREATE INDEX IF NOT EXISTS idx_dimtime_time ON DimTime(TimeValue)",
            "idx_dimtime_hour": "CREATE INDEX IF NOT EXISTS idx_dimtime_hour ON DimTime(HourID)",
            # Fact table indexes (most important for query performance)
            "idx_facttrade_customer": "CREATE INDEX IF NOT EXISTS idx_facttrade_customer ON FactTrade(SK_CustomerID)",
            "idx_facttrade_account": "CREATE INDEX IF NOT EXISTS idx_facttrade_account ON FactTrade(SK_AccountID)",
            "idx_facttrade_security": "CREATE INDEX IF NOT EXISTS idx_facttrade_security ON FactTrade(SK_SecurityID)",
            "idx_facttrade_company": "CREATE INDEX IF NOT EXISTS idx_facttrade_company ON FactTrade(SK_CompanyID)",
            "idx_facttrade_createdate": "CREATE INDEX IF NOT EXISTS idx_facttrade_createdate ON FactTrade(SK_CreateDateID)",
            "idx_facttrade_createtime": "CREATE INDEX IF NOT EXISTS idx_facttrade_createtime ON FactTrade(SK_CreateTimeID)",
            "idx_facttrade_batch": "CREATE INDEX IF NOT EXISTS idx_facttrade_batch ON FactTrade(BatchID)",
            "idx_facttrade_status": "CREATE INDEX IF NOT EXISTS idx_facttrade_status ON FactTrade(Status)",
        }

        results = {}

        for index_name, sql in indexes.items():
            try:
                # Translate SQL if needed
                if self.dialect != "standard":
                    try:
                        sql = sqlglot.transpile(sql, read="postgres", write=self.dialect)[0]
                    except Exception as e:
                        logger.warning(f"SQL translation failed for index {index_name}: {e}")

                # Execute index creation
                if hasattr(connection, "execute"):
                    connection.execute(sql)
                elif hasattr(connection, "query"):
                    connection.query(sql)
                else:
                    raise ValueError(f"Unsupported connection type: {type(connection)}")

                results[index_name] = True
                logger.debug(f"Created index: {index_name}")

            except Exception as e:
                results[index_name] = False
                logger.warning(f"Failed to create index {index_name}: {e}")

        successful = sum(results.values())
        total = len(results)
        logger.info(f"Created {successful}/{total} indexes successfully")

        return results

    def optimize_tables(self, connection: Any) -> dict[str, bool]:
        """Optimize table performance with ANALYZE/VACUUM operations.

        Args:
            connection: Database connection

        Returns:
            Dict mapping table names to optimization success status
        """
        logger.info("Optimizing TPC-DI tables for performance")

        tables = [
            "DimCustomer",
            "DimAccount",
            "DimSecurity",
            "DimCompany",
            "DimDate",
            "DimTime",
            "FactTrade",
        ]
        results = {}

        for table_name in tables:
            try:
                # Database-specific optimization commands
                if self.dialect.lower() == "duckdb":
                    # DuckDB: ANALYZE for statistics
                    optimize_sql = f"ANALYZE {table_name}"
                elif self.dialect.lower() in ["postgres", "postgresql"]:
                    # PostgreSQL: ANALYZE and VACUUM
                    connection.execute(f"ANALYZE {table_name}")
                    connection.execute(f"VACUUM {table_name}")
                    optimize_sql = None  # Already executed above
                elif self.dialect.lower() == "mysql":
                    # MySQL: ANALYZE TABLE
                    optimize_sql = f"ANALYZE TABLE {table_name}"
                else:
                    # Generic: just analyze
                    optimize_sql = f"ANALYZE {table_name}"

                if optimize_sql:
                    if hasattr(connection, "execute"):
                        connection.execute(optimize_sql)
                    elif hasattr(connection, "query"):
                        connection.query(optimize_sql)
                    else:
                        raise ValueError(f"Unsupported connection type: {type(connection)}")

                results[table_name] = True
                logger.debug(f"Optimized table: {table_name}")

            except Exception as e:
                results[table_name] = False
                logger.warning(f"Failed to optimize table {table_name}: {e}")

        successful = sum(results.values())
        total = len(results)
        logger.info(f"Optimized {successful}/{total} tables successfully")

        return results

    def truncate_table(self, table_name: str) -> bool:
        """Truncate a table (remove all data).

        Args:
            table_name: Name of table to truncate

        Returns:
            True if successful, False otherwise
        """
        try:
            sql = f"DELETE FROM {table_name}"

            if hasattr(self.connection, "execute"):
                self.connection.execute(sql)
            elif hasattr(self.connection, "query"):
                self.connection.query(sql)
            else:
                raise ValueError(f"Unsupported connection type: {type(self.connection)}")

            logger.info(f"Truncated table {table_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to truncate table {table_name}: {e}")
            return False

    def get_table_info(self, table_name: str) -> dict[str, Any]:
        """Get information about a table.

        Args:
            table_name: Name of table

        Returns:
            Dict with table information
        """
        try:
            count_sql = f"SELECT COUNT(*) as record_count FROM {table_name}"
            count_result = self.connection.execute(count_sql).fetchone()
            record_count = count_result[0] if count_result else 0

            info = {
                "table_name": table_name,
                "record_count": record_count,
                "exists": True,
            }

            # Try to get table size info (database-specific)
            try:
                if self.dialect.lower() == "duckdb":
                    size_sql = f"SELECT * FROM duckdb_tables() WHERE table_name = '{table_name}'"
                    size_result = self.connection.execute(size_sql).fetchone()
                    if size_result:
                        info["estimated_size_bytes"] = size_result[3] if len(size_result) > 3 else None
            except Exception:
                pass  # Size info not available

            return info

        except Exception as e:
            logger.error(f"Failed to get table info for {table_name}: {e}")
            return {"table_name": table_name, "exists": False, "error": str(e)}

    def _normalize_data_format(self, data: Union[list[dict], pd.DataFrame, Any]) -> list[dict]:
        """Convert various data formats to standard list of dictionaries."""
        if isinstance(data, list):
            return cast(list[dict], data)
        elif isinstance(data, pd.DataFrame) or hasattr(data, "to_dict"):
            return cast(list[dict], data.to_dict("records"))
        elif hasattr(data, "__iter__"):
            return list(data)
        else:
            logger.warning(f"Unknown data format: {type(data)}")
            return []

    def _bulk_insert(self, table_name: str, records: list[dict]) -> int:
        """Perform bulk insert of records."""
        if not records:
            return 0

        total_inserted = 0

        # Process in batches for better performance
        for i in range(0, len(records), self.batch_size):
            batch = records[i : i + self.batch_size]

            try:
                # Build INSERT statement
                if batch:
                    columns = list(batch[0].keys())
                    placeholders = ", ".join(["?" for _ in columns])
                    column_names = ", ".join(columns)

                    insert_sql = f"INSERT INTO {table_name} ({column_names}) VALUES ({placeholders})"

                    # Convert records to tuples
                    values = [tuple(record.get(col) for col in columns) for record in batch]

                    # Execute batch insert
                    if hasattr(self.connection, "executemany"):
                        self.connection.executemany(insert_sql, values)
                    else:
                        # Fallback: individual inserts
                        for value_tuple in values:
                            self.connection.execute(insert_sql, value_tuple)

                    total_inserted += len(batch)

            except Exception as e:
                logger.error(f"Batch insert failed for {table_name}: {e}")
                raise

        return total_inserted

    def _batch_insert_fact_data(self, table_name: str, records: list[dict]) -> int:
        """Optimized batch insert for fact table data."""
        # For fact tables, we can use larger batch sizes and optimizations
        min(50000, len(records))  # Larger batches for fact tables

        return self._bulk_insert(table_name, records)

    def _get_table_count(self, table_name: str) -> int:
        """Get the number of records in a table."""
        try:
            sql = f"SELECT COUNT(*) FROM {table_name}"
            result = self.connection.execute(sql).fetchone()
            return result[0] if result else 0
        except Exception as e:
            logger.warning(f"Failed to get count for table {table_name}: {e}")
            return 0
