"""TPC-DI (Data Integration) benchmark schema definitions.

TPC-DI benchmark tests data integration and ETL processes
used in data warehousing scenarios. Simulates a financial services
environment with customer data, account information, and trading activities.

The benchmark includes:
- Source system data files (CSV, XML, text)
- Target data warehouse tables
- Historical data tracking (Slowly Changing Dimensions)
- Data quality and transformation rules

For more information, see:
- http://www.tpc.org/tpcdi/
- TPC-DI Specification

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DI (TPC-DI) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DI specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import logging
from typing import Any, Optional, cast

import sqlglot

from .schema_extensions import (
    EXTENSION_TABLES,
    get_extended_table_order,
    get_foreign_key_constraints,
)

logger = logging.getLogger(__name__)


# DimCustomer - Customer dimension with SCD Type 2
DIMCUSTOMER = {
    "name": "DimCustomer",
    "columns": [
        {"name": "SK_CustomerID", "type": "BIGINT", "primary_key": True},
        {"name": "CustomerID", "type": "BIGINT"},
        {"name": "TaxID", "type": "VARCHAR(20)"},
        {"name": "Status", "type": "VARCHAR(10)"},
        {"name": "LastName", "type": "VARCHAR(30)"},
        {"name": "FirstName", "type": "VARCHAR(30)"},
        {"name": "MiddleInitial", "type": "VARCHAR(1)"},
        {"name": "Gender", "type": "VARCHAR(1)"},
        {"name": "Tier", "type": "TINYINT"},
        {"name": "DOB", "type": "DATE"},
        {"name": "AddressLine1", "type": "VARCHAR(80)"},
        {"name": "AddressLine2", "type": "VARCHAR(80)"},
        {"name": "PostalCode", "type": "VARCHAR(12)"},
        {"name": "City", "type": "VARCHAR(25)"},
        {"name": "StateProv", "type": "VARCHAR(20)"},
        {"name": "Country", "type": "VARCHAR(24)"},
        {"name": "Phone1", "type": "VARCHAR(30)"},
        {"name": "Phone2", "type": "VARCHAR(30)"},
        {"name": "Phone3", "type": "VARCHAR(30)"},
        {"name": "Email1", "type": "VARCHAR(50)"},
        {"name": "Email2", "type": "VARCHAR(50)"},
        {"name": "NationalTaxRateDesc", "type": "VARCHAR(50)"},
        {"name": "NationalTaxRate", "type": "DECIMAL(6,5)"},
        {"name": "LocalTaxRateDesc", "type": "VARCHAR(50)"},
        {"name": "LocalTaxRate", "type": "DECIMAL(6,5)"},
        {"name": "AgencyID", "type": "VARCHAR(30)"},
        {"name": "CreditRating", "type": "BIGINT"},
        {"name": "NetWorth", "type": "BIGINT"},
        {"name": "MarketingNameplate", "type": "VARCHAR(100)"},
        {"name": "IsCurrent", "type": "BOOLEAN"},
        {"name": "BatchID", "type": "BIGINT"},
        {"name": "EffectiveDate", "type": "DATE"},
        {"name": "EndDate", "type": "DATE"},
    ],
}

# DimAccount - Account dimension
DIMACCOUNT = {
    "name": "DimAccount",
    "columns": [
        {"name": "SK_AccountID", "type": "BIGINT", "primary_key": True},
        {"name": "AccountID", "type": "BIGINT"},
        {"name": "SK_BrokerID", "type": "BIGINT"},
        {"name": "SK_CustomerID", "type": "BIGINT"},
        {"name": "Status", "type": "VARCHAR(10)"},
        {"name": "AccountDesc", "type": "VARCHAR(50)"},
        {"name": "TaxStatus", "type": "TINYINT"},
        {"name": "IsCurrent", "type": "BOOLEAN"},
        {"name": "BatchID", "type": "BIGINT"},
        {"name": "EffectiveDate", "type": "DATE"},
        {"name": "EndDate", "type": "DATE"},
    ],
}

# DimSecurity - Security/stock dimension
DIMSECURITY = {
    "name": "DimSecurity",
    "columns": [
        {"name": "SK_SecurityID", "type": "BIGINT", "primary_key": True},
        {"name": "Symbol", "type": "VARCHAR(15)"},
        {"name": "Issue", "type": "VARCHAR(6)"},
        {"name": "Status", "type": "VARCHAR(10)"},
        {"name": "Name", "type": "VARCHAR(70)"},
        {"name": "ExchangeID", "type": "VARCHAR(6)"},
        {"name": "SK_CompanyID", "type": "BIGINT"},
        {"name": "SharesOutstanding", "type": "BIGINT"},
        {"name": "FirstTrade", "type": "DATE"},
        {"name": "FirstTradeOnExchange", "type": "DATE"},
        {"name": "Dividend", "type": "DECIMAL(10,2)"},
        {"name": "IsCurrent", "type": "BOOLEAN"},
        {"name": "BatchID", "type": "BIGINT"},
        {"name": "EffectiveDate", "type": "DATE"},
        {"name": "EndDate", "type": "DATE"},
    ],
}

# DimCompany - Company dimension
DIMCOMPANY = {
    "name": "DimCompany",
    "columns": [
        {"name": "SK_CompanyID", "type": "BIGINT", "primary_key": True},
        {"name": "CompanyID", "type": "BIGINT"},
        {"name": "Status", "type": "VARCHAR(10)"},
        {"name": "Name", "type": "VARCHAR(60)"},
        {"name": "Industry", "type": "VARCHAR(50)"},
        {"name": "SPrating", "type": "VARCHAR(4)"},
        {"name": "isLowGrade", "type": "BOOLEAN"},
        {"name": "MarketCap", "type": "DECIMAL(15,2)"},
        {"name": "CEO", "type": "VARCHAR(100)"},
        {"name": "AddressLine1", "type": "VARCHAR(80)"},
        {"name": "AddressLine2", "type": "VARCHAR(80)"},
        {"name": "PostalCode", "type": "VARCHAR(12)"},
        {"name": "City", "type": "VARCHAR(25)"},
        {"name": "StateProv", "type": "VARCHAR(20)"},
        {"name": "Country", "type": "VARCHAR(24)"},
        {"name": "Description", "type": "VARCHAR(150)"},
        {"name": "FoundingDate", "type": "DATE"},
        {"name": "IsCurrent", "type": "BOOLEAN"},
        {"name": "BatchID", "type": "BIGINT"},
        {"name": "EffectiveDate", "type": "DATE"},
        {"name": "EndDate", "type": "DATE"},
    ],
}

# FactTrade - Trade fact table
FACTTRADE = {
    "name": "FactTrade",
    "columns": [
        {"name": "TradeID", "type": "BIGINT", "primary_key": True},
        {"name": "SK_BrokerID", "type": "BIGINT"},
        {"name": "SK_CreateDateID", "type": "BIGINT"},
        {"name": "SK_CreateTimeID", "type": "BIGINT"},
        {"name": "SK_CloseDateID", "type": "BIGINT"},
        {"name": "SK_CloseTimeID", "type": "BIGINT"},
        {"name": "Status", "type": "VARCHAR(10)"},
        {"name": "Type", "type": "VARCHAR(12)"},
        {"name": "CashFlag", "type": "BOOLEAN"},
        {"name": "SK_SecurityID", "type": "BIGINT"},
        {"name": "SK_CompanyID", "type": "BIGINT"},
        {"name": "Quantity", "type": "BIGINT"},
        {"name": "BidPrice", "type": "DECIMAL(8,2)"},
        {"name": "SK_CustomerID", "type": "BIGINT"},
        {"name": "SK_AccountID", "type": "BIGINT"},
        {"name": "ExecutedBy", "type": "VARCHAR(64)"},
        {"name": "TradePrice", "type": "DECIMAL(8,2)"},
        {"name": "Fee", "type": "DECIMAL(10,2)"},
        {"name": "Commission", "type": "DECIMAL(10,2)"},
        {"name": "Tax", "type": "DECIMAL(10,2)"},
        {"name": "BatchID", "type": "BIGINT"},
    ],
}

# DimDate - Date dimension
DIMDATE = {
    "name": "DimDate",
    "columns": [
        {"name": "SK_DateID", "type": "BIGINT", "primary_key": True},
        {"name": "DateValue", "type": "DATE"},
        {"name": "DateDesc", "type": "VARCHAR(20)"},
        {"name": "CalendarYearID", "type": "BIGINT"},
        {"name": "CalendarYearDesc", "type": "VARCHAR(20)"},
        {"name": "CalendarQtrID", "type": "BIGINT"},
        {"name": "CalendarQtrDesc", "type": "VARCHAR(20)"},
        {"name": "CalendarMonthID", "type": "BIGINT"},
        {"name": "CalendarMonthDesc", "type": "VARCHAR(20)"},
        {"name": "CalendarWeekID", "type": "BIGINT"},
        {"name": "CalendarWeekDesc", "type": "VARCHAR(20)"},
        {"name": "DayOfWeekNum", "type": "BIGINT"},
        {"name": "DayOfWeekDesc", "type": "VARCHAR(10)"},
        {"name": "FiscalYearID", "type": "BIGINT"},
        {"name": "FiscalYearDesc", "type": "VARCHAR(20)"},
        {"name": "FiscalQtrID", "type": "BIGINT"},
        {"name": "FiscalQtrDesc", "type": "VARCHAR(20)"},
        {"name": "HolidayFlag", "type": "BOOLEAN"},
    ],
}

# DimTime - Time dimension
DIMTIME = {
    "name": "DimTime",
    "columns": [
        {"name": "SK_TimeID", "type": "BIGINT", "primary_key": True},
        {"name": "TimeValue", "type": "TIME"},
        {"name": "HourID", "type": "BIGINT"},
        {"name": "HourDesc", "type": "VARCHAR(20)"},
        {"name": "MinuteID", "type": "BIGINT"},
        {"name": "MinuteDesc", "type": "VARCHAR(20)"},
        {"name": "SecondID", "type": "BIGINT"},
        {"name": "SecondDesc", "type": "VARCHAR(20)"},
        {"name": "MarketHoursFlag", "type": "BOOLEAN"},
        {"name": "OfficeHoursFlag", "type": "BOOLEAN"},
    ],
}

# Extended tables imported at top of file

# All tables in the TPC-DI schema (core + extensions)
TABLES = {
    "DimCustomer": DIMCUSTOMER,
    "DimAccount": DIMACCOUNT,
    "DimSecurity": DIMSECURITY,
    "DimCompany": DIMCOMPANY,
    "FactTrade": FACTTRADE,
    "DimDate": DIMDATE,
    "DimTime": DIMTIME,
    **EXTENSION_TABLES,  # Include extended tables
}

_SPARK_FAMILY_DIALECTS = {"spark", "lakesail", "pyspark", "velox", "databricks"}


def _column_type_for_dialect(column: dict[str, Any], dialect: str) -> str:
    column_type = cast(str, column["type"])
    if column_type == "TIME" and dialect.lower() in _SPARK_FAMILY_DIALECTS:
        return "STRING"
    return column_type


def get_create_table_sql(
    table_name: str,
    dialect: str = "standard",
    enable_primary_keys: bool = True,
    enable_foreign_keys: bool = True,
) -> str:
    """Generate CREATE TABLE SQL for a given table.

    Args:
        table_name: Name of the table to create
        dialect: SQL dialect to use (standard, postgres, mysql, etc.)
        enable_primary_keys: Whether to include primary key constraints
        enable_foreign_keys: Whether to include foreign key constraints

    Returns:
        CREATE TABLE SQL statement

    Raises:
        ValueError: If table_name is not valid
    """
    if table_name not in TABLES:
        raise ValueError(f"Unknown table: {table_name}")

    table = TABLES[table_name]
    columns = []

    for col in cast(list, table["columns"]):
        col_def = f"{cast(str, col['name'])} {_column_type_for_dialect(col, dialect)}"
        if col.get("primary_key") and enable_primary_keys:
            col_def += " PRIMARY KEY"
        columns.append(col_def)

    sql = f"CREATE TABLE IF NOT EXISTS {table['name']} (\n"
    sql += ",\n".join(f"  {col}" for col in columns)
    sql += "\n);"

    return sql


def get_all_create_table_sql(
    dialect: str = "standard",
    enable_primary_keys: bool = True,
    enable_foreign_keys: bool = True,
) -> str:
    """Generate CREATE TABLE SQL for all TPC-DI tables.

    Args:
        dialect: SQL dialect to use
        enable_primary_keys: Whether to include primary key constraints
        enable_foreign_keys: Whether to include foreign key constraints

    Returns:
        Complete SQL schema creation script
    """
    # Create tables in dependency order (core tables first, then extensions)
    core_table_order = [
        "DimDate",
        "DimTime",
        "DimCompany",
        "DimSecurity",
        "DimCustomer",
        "DimAccount",
        "FactTrade",
    ]

    # Combine core and extended table orders
    extended_order = get_extended_table_order()
    full_table_order = core_table_order + extended_order

    sql_statements = []
    for table_name in full_table_order:
        sql_statements.append(get_create_table_sql(table_name, dialect, enable_primary_keys, enable_foreign_keys))

    return "\n\n".join(sql_statements)


class TPCDISchemaManager:
    """Database-agnostic TPC-DI schema management with SQLGlot translation."""

    def __init__(self, include_extensions: bool = True):
        """Initialize schema manager.

        Args:
            include_extensions: Whether to include extended TPC-DI tables
        """
        self.include_extensions = include_extensions
        self.tables = TABLES

        # Core table order
        self.core_table_order = [
            "DimDate",
            "DimTime",
            "DimCompany",
            "DimSecurity",
            "DimCustomer",
            "DimAccount",
            "FactTrade",
        ]

        # Full table order including extensions
        if include_extensions:
            extended_order = get_extended_table_order()
            self.table_order = self.core_table_order + extended_order
        else:
            self.table_order = self.core_table_order

    def create_schema(self, connection: Any, dialect: str = "duckdb") -> None:
        """Create the complete TPC-DI schema in the target database.

        Args:
            connection: Database connection object
            dialect: Target SQL dialect for translation
        """
        logger.info(f"Creating TPC-DI schema for {dialect} dialect")

        ddl_statements = self.get_create_table_ddl(dialect)

        for statement in ddl_statements:
            try:
                if hasattr(connection, "execute"):
                    connection.execute(statement)
                elif hasattr(connection, "exec_driver_sql"):
                    connection.exec_driver_sql(statement)
                else:
                    connection.query(statement)

            except Exception as e:
                logger.error(f"Failed to execute DDL: {statement}")
                logger.error(f"Error: {e}")
                raise

        logger.info(f"Successfully created {len(ddl_statements)} tables")

    def get_create_table_ddl(self, dialect: str = "standard") -> list[str]:
        """Generate CREATE TABLE DDL statements for all tables.

        Args:
            dialect: Target SQL dialect

        Returns:
            List of CREATE TABLE statements
        """
        statements = []

        for table_name in self.table_order:
            sql = get_create_table_sql(table_name, "standard")

            if dialect != "standard":
                try:
                    # Translate SQL using SQLGlot
                    translated = sqlglot.transpile(sql, read="postgres", write=dialect)[0]
                    statements.append(translated)
                except Exception as e:
                    logger.warning(f"SQLGlot translation failed for {table_name}: {e}")
                    statements.append(sql)
            else:
                statements.append(sql)

        return statements

    def translate_schema(self, from_dialect: str, to_dialect: str) -> list[str]:
        """Translate schema from one SQL dialect to another.

        Args:
            from_dialect: Source SQL dialect
            to_dialect: Target SQL dialect

        Returns:
            List of translated CREATE TABLE statements
        """
        source_statements = self.get_create_table_ddl(from_dialect)
        translated = []

        for sql in source_statements:
            try:
                translated_sql = sqlglot.transpile(sql, read=from_dialect, write=to_dialect)[0]
                translated.append(translated_sql)
            except Exception as e:
                logger.error(f"Translation failed from {from_dialect} to {to_dialect}: {e}")
                translated.append(sql)

        return translated

    def get_table_schema(self, table_name: str) -> dict[str, Any]:
        """Get schema definition for a specific table.

        Args:
            table_name: Name of the table

        Returns:
            Table schema dictionary
        """
        if table_name not in self.tables:
            raise ValueError(f"Unknown table: {table_name}")

        return self.tables[table_name]

    def get_column_names(self, table_name: str) -> list[str]:
        """Get column names for a table.

        Args:
            table_name: Name of the table

        Returns:
            List of column names
        """
        schema = self.get_table_schema(table_name)
        return [col["name"] for col in schema["columns"]]

    def get_primary_key(self, table_name: str) -> Optional[str]:
        """Get primary key column for a table.

        Args:
            table_name: Name of the table

        Returns:
            Primary key column name or None
        """
        schema = self.get_table_schema(table_name)
        for col in schema["columns"]:
            if col.get("primary_key"):
                return col["name"]
        return None

    def create_foreign_key_constraints(self, connection: Any, dialect: str = "duckdb") -> None:
        """Create foreign key constraints for TPC-DI tables.

        Args:
            connection: Database connection
            dialect: Target SQL dialect
        """
        if not self.include_extensions:
            logger.info("Skipping foreign key constraints - extensions not included")
            return

        logger.info("Creating foreign key constraints...")

        constraints = get_foreign_key_constraints()
        constraint_count = 0

        for table_name, fk_list in constraints.items():
            if table_name not in self.table_order:
                continue

            for fk in fk_list:
                constraint_sql = (
                    f"ALTER TABLE {table_name} "
                    f"ADD CONSTRAINT {fk['constraint_name']} "
                    f"FOREIGN KEY ({fk['column']}) "
                    f"REFERENCES {fk['references_table']}({fk['references_column']})"
                )

                try:
                    if hasattr(connection, "execute"):
                        connection.execute(constraint_sql)
                    elif hasattr(connection, "exec_driver_sql"):
                        connection.exec_driver_sql(constraint_sql)
                    else:
                        connection.query(constraint_sql)
                    constraint_count += 1

                except Exception as e:
                    logger.warning(f"Failed to create constraint {fk['constraint_name']}: {e}")
                    # Continue with other constraints

        logger.info(f"Successfully created {constraint_count} foreign key constraints")

    def get_table_count(self) -> int:
        """Get the total number of tables in the schema.

        Returns:
            Number of tables
        """
        return len(self.table_order)

    def get_core_tables(self) -> list[str]:
        """Get list of core TPC-DI table names.

        Returns:
            List of core table names
        """
        return self.core_table_order.copy()

    def get_extended_tables(self) -> list[str]:
        """Get list of extended TPC-DI table names.

        Returns:
            List of extended table names
        """
        if self.include_extensions:
            return get_extended_table_order()
        return []

    def drop_schema(self, connection: Any, if_exists: bool = True) -> None:
        """Drop all TPC-DI tables from the database.

        Args:
            connection: Database connection
            if_exists: Use IF EXISTS clause
        """
        # Drop in reverse order to handle dependencies
        for table_name in reversed(self.table_order):
            if_exists_clause = "IF EXISTS " if if_exists else ""
            drop_sql = f"DROP TABLE {if_exists_clause}{table_name}"

            try:
                if hasattr(connection, "execute"):
                    connection.execute(drop_sql)
                elif hasattr(connection, "exec_driver_sql"):
                    connection.exec_driver_sql(drop_sql)
                else:
                    connection.query(drop_sql)
            except Exception as e:
                if not if_exists:
                    logger.error(f"Failed to drop table {table_name}: {e}")
                    raise
