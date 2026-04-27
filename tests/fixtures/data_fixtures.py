"""Data-related fixtures for BenchBox tests.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import csv
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from .database_fixtures import setup_duckdb_extensions


@pytest.fixture
def small_tpch_data(tmp_path: Path) -> Generator[dict[str, Path], None, None]:
    """Create small TPC-H dataset for testing.

    This fixture creates minimal TPC-H data files with just enough
    records to test functionality without performance overhead.

    Args:
        tmp_path: Pytest temporary directory fixture

    Returns:
        Dict[str, Path]: Mapping of table names to data file paths
    """
    data_dir = tmp_path / "small_tpch_data"
    data_dir.mkdir(exist_ok=True)

    # Create minimal data files
    files = {}

    # Region data (5 rows)
    region_file = data_dir / "region.csv"
    with open(region_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerow(["r_regionkey", "r_name", "r_comment"])
        writer.writerows(
            [
                [
                    0,
                    "AFRICA",
                    "lar deposits. blithely final packages cajole. regular waters are final requests.",
                ],
                [1, "AMERICA", "hs use ironic, even requests. s"],
                [2, "ASIA", "ges. thinly even pinto beans ca"],
                [3, "EUROPE", "ly final courts cajole furiously final excuse"],
                [
                    4,
                    "MIDDLE EAST",
                    "uickly special accounts cajole carefully blithely close requests.",
                ],
            ]
        )
    files["region"] = region_file

    # Nation data (25 rows - first 10 for testing)
    nation_file = data_dir / "nation.csv"
    with open(nation_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerow(["n_nationkey", "n_name", "n_regionkey", "n_comment"])
        writer.writerows(
            [
                [0, "ALGERIA", 0, "haggle. carefully final deposits detect slyly agai"],
                [
                    1,
                    "ARGENTINA",
                    1,
                    "al foxes promise slyly according to the regular accounts.",
                ],
                [2, "BRAZIL", 1, "y alongside of the pending deposits."],
                [3, "CANADA", 1, "eas hang ironic, silent packages."],
                [4, "EGYPT", 4, "y above the carefully unusual theodolites."],
                [5, "ETHIOPIA", 0, "ven packages wake quickly."],
                [6, "FRANCE", 3, "refully final requests."],
                [7, "GERMANY", 3, "l platelets."],
                [8, "INDIA", 2, "ss excuses cajole slyly across the packages."],
                [9, "INDONESIA", 2, "slyly express asymptotes."],
            ]
        )
    files["nation"] = nation_file

    # Customer data (minimal)
    customer_file = data_dir / "customer.csv"
    with open(customer_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerow(
            [
                "c_custkey",
                "c_name",
                "c_address",
                "c_nationkey",
                "c_phone",
                "c_acctbal",
                "c_mktsegment",
                "c_comment",
            ]
        )
        writer.writerows(
            [
                [
                    1,
                    "Customer#000000001",
                    "IVhzIApeRb ot,c,E",
                    15,
                    "25-989-741-2988",
                    711.56,
                    "BUILDING",
                    "to the even, regular platelets.",
                ],
                [
                    2,
                    "Customer#000000002",
                    "XSTf4,NCwDVaWNe6tEgvwfmRchLXak",
                    13,
                    "23-768-687-3665",
                    121.65,
                    "AUTOMOBILE",
                    "l accounts.",
                ],
                [
                    3,
                    "Customer#000000003",
                    "MG9kdTD2WBHm",
                    1,
                    "11-719-748-3364",
                    7498.12,
                    "AUTOMOBILE",
                    "deposits eat slyly ironic, even instructions.",
                ],
            ]
        )
    files["customer"] = customer_file

    # Supplier data (minimal)
    supplier_file = data_dir / "supplier.csv"
    with open(supplier_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerow(
            [
                "s_suppkey",
                "s_name",
                "s_address",
                "s_nationkey",
                "s_phone",
                "s_acctbal",
                "s_comment",
            ]
        )
        writer.writerows(
            [
                [
                    1,
                    "Supplier#000000001",
                    "N kD4on9OM Ipw3,gf0JBoQDd7tgrzrddZ",
                    17,
                    "27-918-335-1736",
                    5755.94,
                    "each slyly above the careful",
                ],
                [
                    2,
                    "Supplier#000000002",
                    "89eJ5ksX3ImxJQBvxObC,",
                    5,
                    "15-679-861-2259",
                    4032.68,
                    "furiously stealthy frays",
                ],
                [
                    3,
                    "Supplier#000000003",
                    "q1,G3Pj6OjIuUYfUoH18BFTKP5aU9bEV3",
                    1,
                    "11-383-516-1199",
                    4192.40,
                    "blithely silent requests after the express dependencies",
                ],
            ]
        )
    files["supplier"] = supplier_file

    # Part data (minimal)
    part_file = data_dir / "part.csv"
    with open(part_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerow(
            [
                "p_partkey",
                "p_name",
                "p_mfgr",
                "p_brand",
                "p_type",
                "p_size",
                "p_container",
                "p_retailprice",
                "p_comment",
            ]
        )
        writer.writerows(
            [
                [
                    1,
                    "goldenrod lavender spring chocolate lace",
                    "Manufacturer#1",
                    "Brand#13",
                    "PROMO BURNISHED COPPER",
                    7,
                    "JUMBO PKG",
                    901.00,
                    "ly. slyly ironic, even instructions.",
                ],
                [
                    2,
                    "blush thistle blue yellow saddle",
                    "Manufacturer#1",
                    "Brand#13",
                    "LARGE BRUSHED BRASS",
                    1,
                    "LG CASE",
                    902.00,
                    "lar accounts hang fluffily ar",
                ],
                [
                    3,
                    "spring green yellow purple cornsilk",
                    "Manufacturer#4",
                    "Brand#42",
                    "STANDARD POLISHED BRASS",
                    21,
                    "WRAP CASE",
                    903.00,
                    "egular deposits hag",
                ],
            ]
        )
    files["part"] = part_file

    # Partsupp data (minimal)
    partsupp_file = data_dir / "partsupp.csv"
    with open(partsupp_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerow(["ps_partkey", "ps_suppkey", "ps_availqty", "ps_supplycost", "ps_comment"])
        writer.writerows(
            [
                [1, 1, 3325, 771.64, "finally ironic packages are."],
                [1, 2, 8076, 993.49, "ven ideas. quickly even packages print."],
                [2, 1, 3956, 337.09, "after the fluffily ironic deposits"],
            ]
        )
    files["partsupp"] = partsupp_file

    # Orders data (minimal)
    orders_file = data_dir / "orders.csv"
    with open(orders_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerow(
            [
                "o_orderkey",
                "o_custkey",
                "o_orderstatus",
                "o_totalprice",
                "o_orderdate",
                "o_orderpriority",
                "o_clerk",
                "o_shippriority",
                "o_comment",
            ]
        )
        writer.writerows(
            [
                [
                    1,
                    1,
                    "O",
                    173665.47,
                    "1996-01-02",
                    "5-LOW",
                    "Clerk#000000951",
                    0,
                    "nstructions sleep furiously among",
                ],
                [
                    2,
                    1,
                    "O",
                    46929.18,
                    "1996-12-01",
                    "1-URGENT",
                    "Clerk#000000880",
                    0,
                    "foxes. pending accounts at the pending, silent asymptot",
                ],
                [
                    3,
                    3,
                    "F",
                    205654.30,
                    "1993-10-14",
                    "5-LOW",
                    "Clerk#000000955",
                    0,
                    "sly final accounts boost.",
                ],
            ]
        )
    files["orders"] = orders_file

    # Lineitem data (minimal)
    lineitem_file = data_dir / "lineitem.csv"
    with open(lineitem_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerow(
            [
                "l_orderkey",
                "l_partkey",
                "l_suppkey",
                "l_linenumber",
                "l_quantity",
                "l_extendedprice",
                "l_discount",
                "l_tax",
                "l_returnflag",
                "l_linestatus",
                "l_shipdate",
                "l_commitdate",
                "l_receiptdate",
                "l_shipinstruct",
                "l_shipmode",
                "l_comment",
            ]
        )
        writer.writerows(
            [
                [
                    1,
                    1,
                    1,
                    1,
                    17,
                    21168.23,
                    0.04,
                    0.02,
                    "N",
                    "O",
                    "1996-03-13",
                    "1996-02-12",
                    "1996-03-22",
                    "DELIVER IN PERSON",
                    "TRUCK",
                    "egular courts above the",
                ],
                [
                    1,
                    2,
                    2,
                    2,
                    36,
                    45983.16,
                    0.09,
                    0.06,
                    "N",
                    "O",
                    "1996-04-12",
                    "1996-02-28",
                    "1996-04-20",
                    "TAKE BACK RETURN",
                    "MAIL",
                    "ly final dependencies: slyly bold",
                ],
                [
                    2,
                    2,
                    1,
                    1,
                    38,
                    44694.46,
                    0.00,
                    0.05,
                    "N",
                    "O",
                    "1997-01-28",
                    "1997-01-14",
                    "1997-02-02",
                    "TAKE BACK RETURN",
                    "RAIL",
                    "ven requests. deposits breach a",
                ],
            ]
        )
    files["lineitem"] = lineitem_file

    yield files


@pytest.fixture
def sample_queries() -> dict[str, str]:
    """Provide sample queries for testing.

    Returns:
        Dict[str, str]: Sample queries by category
    """
    return {
        "aggregation_simple": "SELECT COUNT(*) FROM lineitem;",
        "aggregation_groupby": """
            SELECT
                l_returnflag,
                l_linestatus,
                COUNT(*) as count_order,
                SUM(l_quantity) as sum_qty
            FROM lineitem
            GROUP BY l_returnflag, l_linestatus;
        """,
        "join_simple": """
            SELECT r.r_name, n.n_name
            FROM region r
            JOIN nation n ON r.r_regionkey = n.n_regionkey;
        """,
        "join_complex": """
            SELECT
                c.c_name,
                n.n_name,
                r.r_name,
                o.o_orderdate
            FROM customer c
            JOIN nation n ON c.c_nationkey = n.n_nationkey
            JOIN region r ON n.n_regionkey = r.r_regionkey
            JOIN orders o ON c.c_custkey = o.o_custkey;
        """,
        "window_function": """
            SELECT
                l_orderkey,
                l_linenumber,
                l_quantity,
                ROW_NUMBER() OVER (PARTITION BY l_orderkey ORDER BY l_linenumber) as rn,
                SUM(l_quantity) OVER (PARTITION BY l_orderkey) as total_qty
            FROM lineitem;
        """,
        "filter_simple": """
            SELECT * FROM lineitem
            WHERE l_shipdate >= '1996-01-01'
            AND l_shipdate < '1997-01-01';
        """,
        "filter_complex": """
            SELECT
                l_orderkey,
                l_partkey,
                l_suppkey,
                l_quantity,
                l_extendedprice
            FROM lineitem
            WHERE l_discount BETWEEN 0.05 AND 0.07
            AND l_quantity < 24;
        """,
        "subquery": """
            SELECT c_name, c_acctbal
            FROM customer
            WHERE c_custkey IN (
                SELECT o_custkey
                FROM orders
                WHERE o_orderdate >= '1996-01-01'
            );
        """,
    }


@pytest.fixture
def duckdb_with_tpch_data(duckdb_memory_db: Mock, small_tpch_data: dict[str, Path]) -> Generator[Mock, None, None]:
    """Create a DuckDB database with TPC-H data loaded.

    This fixture creates a DuckDB database and loads the small TPC-H
    dataset for testing queries and benchmarks.

    Args:
        duckdb_memory_db: DuckDB memory database fixture
        small_tpch_data: Small TPC-H dataset fixture

    Returns:
        Mock: DuckDB database with TPC-H data loaded
    """
    # Setup extensions
    setup_duckdb_extensions(duckdb_memory_db)

    # Skip loading data for mock connections
    if hasattr(duckdb_memory_db, "_mock_name"):
        yield duckdb_memory_db
        return

    try:
        # Create tables and load data
        table_schemas = {
            "region": """
                CREATE TABLE region (
                    r_regionkey INTEGER PRIMARY KEY,
                    r_name VARCHAR(25),
                    r_comment VARCHAR(152)
                );
            """,
            "nation": """
                CREATE TABLE nation (
                    n_nationkey INTEGER PRIMARY KEY,
                    n_name VARCHAR(25),
                    n_regionkey INTEGER,
                    n_comment VARCHAR(152)
                );
            """,
            "customer": """
                CREATE TABLE customer (
                    c_custkey INTEGER PRIMARY KEY,
                    c_name VARCHAR(25),
                    c_address VARCHAR(40),
                    c_nationkey INTEGER,
                    c_phone VARCHAR(15),
                    c_acctbal DECIMAL(15,2),
                    c_mktsegment VARCHAR(10),
                    c_comment VARCHAR(117)
                );
            """,
            "supplier": """
                CREATE TABLE supplier (
                    s_suppkey INTEGER PRIMARY KEY,
                    s_name VARCHAR(25),
                    s_address VARCHAR(40),
                    s_nationkey INTEGER,
                    s_phone VARCHAR(15),
                    s_acctbal DECIMAL(15,2),
                    s_comment VARCHAR(101)
                );
            """,
            "part": """
                CREATE TABLE part (
                    p_partkey INTEGER PRIMARY KEY,
                    p_name VARCHAR(55),
                    p_mfgr VARCHAR(25),
                    p_brand VARCHAR(10),
                    p_type VARCHAR(25),
                    p_size INTEGER,
                    p_container VARCHAR(10),
                    p_retailprice DECIMAL(15,2),
                    p_comment VARCHAR(23)
                );
            """,
            "partsupp": """
                CREATE TABLE partsupp (
                    ps_partkey INTEGER,
                    ps_suppkey INTEGER,
                    ps_availqty INTEGER,
                    ps_supplycost DECIMAL(15,2),
                    ps_comment VARCHAR(199),
                    PRIMARY KEY (ps_partkey, ps_suppkey)
                );
            """,
            "orders": """
                CREATE TABLE orders (
                    o_orderkey INTEGER PRIMARY KEY,
                    o_custkey INTEGER,
                    o_orderstatus VARCHAR(1),
                    o_totalprice DECIMAL(15,2),
                    o_orderdate DATE,
                    o_orderpriority VARCHAR(15),
                    o_clerk VARCHAR(15),
                    o_shippriority INTEGER,
                    o_comment VARCHAR(79)
                );
            """,
            "lineitem": """
                CREATE TABLE lineitem (
                    l_orderkey INTEGER,
                    l_partkey INTEGER,
                    l_suppkey INTEGER,
                    l_linenumber INTEGER,
                    l_quantity DECIMAL(15,2),
                    l_extendedprice DECIMAL(15,2),
                    l_discount DECIMAL(15,2),
                    l_tax DECIMAL(15,2),
                    l_returnflag VARCHAR(1),
                    l_linestatus VARCHAR(1),
                    l_shipdate DATE,
                    l_commitdate DATE,
                    l_receiptdate DATE,
                    l_shipinstruct VARCHAR(25),
                    l_shipmode VARCHAR(10),
                    l_comment VARCHAR(44),
                    PRIMARY KEY (l_orderkey, l_linenumber)
                );
            """,
        }

        # Create tables
        for table_name, schema in table_schemas.items():
            duckdb_memory_db.execute(schema)

        # Load data from CSV files
        for table_name, file_path in small_tpch_data.items():
            if table_name in table_schemas:
                duckdb_memory_db.execute(f"COPY {table_name} FROM '{file_path}' (DELIMITER '|', HEADER);")

    except Exception:
        # Continue with empty database if loading fails
        pass

    yield duckdb_memory_db


@pytest.fixture
def performance_test_data() -> dict[str, Any]:
    """Provide performance testing data and thresholds.

    Returns:
        Dict[str, Any]: Performance test configuration
    """
    return {
        "query_timeout": 30,  # seconds
        "memory_limit": 512,  # MB
        "expected_row_counts": {
            "region": 5,
            "nation": 10,
            "customer": 3,
            "supplier": 3,
            "part": 3,
            "partsupp": 3,
            "orders": 3,
            "lineitem": 3,
        },
        "performance_thresholds": {
            "aggregation_simple": 1.0,
            "join_simple": 2.0,
            "window_function": 3.0,
            "filter_simple": 1.0,
            "subquery": 5.0,
        },
    }


@pytest.fixture
def data_validation_rules() -> dict[str, dict[str, Any]]:
    """Provide data validation rules for testing.

    Returns:
        Dict[str, Dict[str, Any]]: Validation rules by table
    """
    return {
        "region": {
            "required_columns": ["r_regionkey", "r_name", "r_comment"],
            "primary_key": ["r_regionkey"],
            "min_rows": 5,
            "max_rows": 5,
        },
        "nation": {
            "required_columns": ["n_nationkey", "n_name", "n_regionkey", "n_comment"],
            "primary_key": ["n_nationkey"],
            "foreign_keys": [("n_regionkey", "region", "r_regionkey")],
            "min_rows": 10,
            "max_rows": 25,
        },
        "customer": {
            "required_columns": [
                "c_custkey",
                "c_name",
                "c_address",
                "c_nationkey",
                "c_phone",
                "c_acctbal",
                "c_mktsegment",
                "c_comment",
            ],
            "primary_key": ["c_custkey"],
            "foreign_keys": [("c_nationkey", "nation", "n_nationkey")],
            "min_rows": 1,
            "max_rows": 1000,
        },
        "lineitem": {
            "required_columns": [
                "l_orderkey",
                "l_partkey",
                "l_suppkey",
                "l_linenumber",
                "l_quantity",
                "l_extendedprice",
                "l_discount",
                "l_tax",
                "l_returnflag",
                "l_linestatus",
                "l_shipdate",
                "l_commitdate",
                "l_receiptdate",
                "l_shipinstruct",
                "l_shipmode",
                "l_comment",
            ],
            "primary_key": ["l_orderkey", "l_linenumber"],
            "foreign_keys": [
                ("l_orderkey", "orders", "o_orderkey"),
                ("l_partkey", "part", "p_partkey"),
                ("l_suppkey", "supplier", "s_suppkey"),
            ],
            "min_rows": 1,
            "max_rows": 10000,
        },
    }
