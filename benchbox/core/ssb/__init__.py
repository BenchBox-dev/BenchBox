"""Star Schema Benchmark (SSB) package.

This package provides a complete implementation of the Star Schema Benchmark,
a simplified OLAP benchmark based on TPC-H. The SSB features:

Copyright 2026 Joe Harris / BenchBox Project

This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.

1. A denormalized star schema with 1 fact table and 4 dimension tables
2. 13 standard queries organized into 4 flights
3. Data generation based on TPC-H but simplified for OLAP workloads
4. Query execution and performance measurement

The Star Schema Benchmark was originally designed by Patrick O'Neil and others
to provide a more focused benchmark for data warehouse and OLAP systems.

For more information, see:
- "Star Schema Benchmark" by O'Neil et al.
- https://www.cs.umb.edu/~poneil/StarSchemaB.PDF
"""

from .benchmark import SSBBenchmark
from .family import SSBFamily
from .generator import SSBDataGenerator
from .queries import SSBQueryManager
from .schema import (
    CUSTOMER,
    DATE,
    LINEORDER,
    PART,
    SUPPLIER,
    TABLES,
    get_all_create_table_sql,
    get_create_table_sql,
)

__all__ = [
    "SSBBenchmark",
    "SSBFamily",
    "SSBDataGenerator",
    "SSBQueryManager",
    "DATE",
    "CUSTOMER",
    "SUPPLIER",
    "PART",
    "LINEORDER",
    "TABLES",
    "get_create_table_sql",
    "get_all_create_table_sql",
]
