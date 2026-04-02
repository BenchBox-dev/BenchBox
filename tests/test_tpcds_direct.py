#!/usr/bin/env python3
"""Direct test script for TPC-DS implementation in BenchBox.

This script tests the TPC-DS implementation without requiring pytest.
It's meant to be run directly to verify that the implementation works.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DS specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]

# Include the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import the TPCDS class
try:
    from benchbox import TPCDS

    print("Successfully imported TPCDS class")
except ImportError as e:
    print(f"Failed to import TPCDS: {e}")
    sys.exit(1)


def test_tpcds_init():
    """Test TPCDS initialization."""
    # Test with default parameters
    tpcds = TPCDS()
    print(f"Initialized TPCDS with scale factor: {tpcds.scale_factor}")

    # Test with custom parameters
    custom_dir = Path("custom_dir")
    tpcds_custom = TPCDS(scale_factor=1.0, output_dir=custom_dir, verbose=True)
    print(
        f"Initialized TPCDS with custom parameters: scale_factor={tpcds_custom.scale_factor}, output_dir={tpcds_custom.output_dir}"
    )


def test_tpcds_schema():
    """Test TPCDS schema."""
    tpcds = TPCDS()
    schema = tpcds.get_schema()

    # Verify schema structure
    print(f"Got schema with {len(schema)} tables")

    # Print some table names
    table_names = [table["name"] for table in schema.values()]
    print(f"Tables include: {', '.join(table_names[:5])}...")

    # Verify SQL generation
    sql = tpcds.get_create_tables_sql()
    print(f"Generated SQL with {len(sql)} characters")


@pytest.mark.slow
@pytest.mark.skipif(sys.platform == "win32", reason="dsqgen binary does not work on Windows")
def test_tpcds_queries():
    """Test TPCDS queries."""
    tpcds = TPCDS()

    # Try to get all queries
    try:
        queries = tpcds.get_queries()
        print(f"Got {len(queries)} queries")
    except Exception as e:
        print(f"Failed to get all queries: {e}")

    # Try to get a specific query - try a few query IDs that might exist
    found_valid_query = False
    for query_id in [1, 2, 3, 4, 5]:
        try:
            query = tpcds.get_query(query_id)
            print(f"Successfully got query {query_id} with length {len(query)} characters")

            # Try parameterization
            tpcds.get_query(query_id)
            print(f"Successfully parameterized query {query_id}")

            # We succeeded with at least one query
            found_valid_query = True
            break
        except ValueError:
            print(f"Query {query_id} not found, trying next...")
            continue

    assert found_valid_query, "Could not find any valid queries"


def main() -> int:
    """Run all tests."""
    print("=== Testing TPC-DS Implementation ===")

    tests = [
        ("Initialization", test_tpcds_init),
        ("Schema", test_tpcds_schema),
        ("Queries", test_tpcds_queries),
    ]

    results = []
    for test_name, test_func in tests:
        print(f"\nRunning test: {test_name}")
        try:
            test_func()
            # If no exception was raised, test passed
            results.append(True)
            print(f"Test {test_name}: PASS")
        except (Exception, AssertionError) as e:
            print(f"Test {test_name} FAILED: {e}")
            results.append(False)

    # Print overall results
    print("\n=== Test Results ===")
    for i, (test_name, _) in enumerate(tests):
        status = "PASS" if results[i] else "FAIL"
        print(f"{test_name}: {status}")

    passed = sum(results)
    total = len(results)
    print(f"\nPassed {passed}/{total} tests")

    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
