"""AMPLab Big Data Benchmark schema definitions.

The AMPLab benchmark is designed to test big data processing systems
using web analytics workloads. It consists of three main tables based
on web crawl and user interaction data.

The benchmark tests:
- Scan queries (filtering and aggregation)
- Join queries (across multiple tables)
- Complex analytical queries

Tables:
- rankings: Web page rankings (similar to PageRank)
- uservisits: User visit logs with source/destination URLs
- documents: Web page content and metadata

For more information, see:
- https://amplab.cs.berkeley.edu/benchmark/

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from typing import cast

from benchbox.core.tuning import BenchmarkTunings, TableTuning, TuningColumn

# Rankings table - web page rankings
RANKINGS = {
    "name": "rankings",
    "columns": [
        {"name": "pageURL", "type": "VARCHAR(300)", "primary_key": True},
        {"name": "pageRank", "type": "INTEGER"},
        {"name": "avgDuration", "type": "INTEGER"},
    ],
}

# UserVisits table - user visit logs
USERVISITS = {
    "name": "uservisits",
    "columns": [
        {"name": "sourceIP", "type": "VARCHAR(15)"},
        {"name": "destURL", "type": "VARCHAR(100)"},
        {"name": "visitDate", "type": "DATE"},
        {"name": "adRevenue", "type": "DECIMAL(8,2)"},
        {"name": "userAgent", "type": "VARCHAR(256)"},
        {"name": "countryCode", "type": "VARCHAR(3)"},
        {"name": "languageCode", "type": "VARCHAR(6)"},
        {"name": "searchWord", "type": "VARCHAR(32)"},
        {"name": "duration", "type": "INTEGER"},
    ],
}

# Documents table - web page content and metadata
DOCUMENTS = {
    "name": "documents",
    "columns": [
        {"name": "url", "type": "VARCHAR(300)", "primary_key": True},
        {"name": "contents", "type": "TEXT"},
    ],
}

# All tables in the AMPLab schema
TABLES = {"rankings": RANKINGS, "uservisits": USERVISITS, "documents": DOCUMENTS}


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

    for col in table["columns"]:
        col_def = f"{cast(str, col['name'])} {cast(str, col['type'])}"
        if col.get("primary_key") and enable_primary_keys:
            col_def += " PRIMARY KEY"
        columns.append(col_def)

    sql = f"CREATE TABLE {cast(str, table['name'])} (\n"
    sql += ",\n".join(f"  {col}" for col in columns)
    sql += "\n);"

    return sql


def get_all_create_table_sql(
    dialect: str = "standard",
    enable_primary_keys: bool = True,
    enable_foreign_keys: bool = True,
) -> str:
    """Generate CREATE TABLE SQL for all AMPLab tables.

    Args:
        dialect: SQL dialect to use
        enable_primary_keys: Whether to include primary key constraints
        enable_foreign_keys: Whether to include foreign key constraints

    Returns:
        Complete SQL schema creation script
    """
    from benchbox.core.schema_utils import collect_create_table_sql

    return collect_create_table_sql(
        ["rankings", "documents", "uservisits"],
        get_create_table_sql,
        dialect,
        enable_primary_keys=enable_primary_keys,
        enable_foreign_keys=enable_foreign_keys,
    )


def get_tunings() -> BenchmarkTunings:
    """Get the default tuning configurations for AMPLab tables.

    These tunings are optimized for the big data analytics workloads
    typical in the AMPLab benchmark, focusing on scan and join performance.

    Returns:
        BenchmarkTunings containing tuning configurations for AMPLab tables
    """
    tunings = BenchmarkTunings("amplab")

    # Rankings table - distribute by page URL, sort by page rank for analytics
    rankings_tuning = TableTuning(
        table_name="rankings",
        distribution=[TuningColumn("pageURL", "VARCHAR(300)", 1)],
        sorting=[
            TuningColumn("pageRank", "INTEGER", 1),
            TuningColumn("avgDuration", "INTEGER", 2),
        ],
    )
    tunings.add_table_tuning(rankings_tuning)

    # UserVisits table - partition by visit date, cluster by country and source
    uservisits_tuning = TableTuning(
        table_name="uservisits",
        partitioning=[TuningColumn("visitDate", "DATE", 1)],
        clustering=[
            TuningColumn("countryCode", "VARCHAR(3)", 1),
            TuningColumn("sourceIP", "VARCHAR(15)", 2),
        ],
        sorting=[
            TuningColumn("adRevenue", "DECIMAL(8,2)", 1),
            TuningColumn("duration", "INTEGER", 2),
        ],
    )
    tunings.add_table_tuning(uservisits_tuning)

    # Documents table - distribute by URL for join performance
    documents_tuning = TableTuning(table_name="documents", distribution=[TuningColumn("url", "VARCHAR(300)", 1)])
    tunings.add_table_tuning(documents_tuning)

    return tunings
