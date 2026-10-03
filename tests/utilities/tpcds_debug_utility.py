#!/usr/bin/env python3
# Copyright 2026 Joe Harris / BenchBox Project

# TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
# This implementation is based on the TPC-DS specification.

# Licensed under the MIT License. See LICENSE file in the project root for details.

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from benchbox.core.tpcds.c_tools import DSQGenBinary  # noqa: E402
from benchbox.core.tpcds.queries import TPCDSQueryManager  # noqa: E402


def test_dsqgen_binary():
    print("=" * 60)
    print("Testing DSQGenBinary directly")
    print("=" * 60)

    dsqgen = DSQGenBinary()

    print(f"Templates dir: {dsqgen.templates_dir}")
    print(f"Tools dir: {dsqgen.tools_dir}")
    print(f"DSQGen path: {dsqgen.dsqgen_path}")
    print()

    print("Query ID parsing:")
    test_cases = [1, "14a", "23b", "99", "15a"]
    for case in test_cases:
        try:
            result = dsqgen._parse_query_id(case)
            print(f"  {case} -> {result}")
        except Exception as e:
            print(f"  {case} -> ERROR: {e}")
    print()

    print("Query variations:")
    for query_id in [1, 14, 23, 24, 39, 50]:
        variations = dsqgen.get_query_variations(query_id)
        print(f"  Query {query_id}: {variations}")
    print()

    print("Query validation:")
    test_ids = [1, "14a", "15a", 99, 100, "invalid"]
    for test_id in test_ids:
        valid = dsqgen.validate_query_id(test_id)
        print(f"  {test_id}: {valid}")
    print()

    print("Query generation:")
    try:
        sql1 = dsqgen.generate(1, seed=42)
        print(f"  Query 1 (seed 42): {len(sql1)} chars")
        print(f"  First 100 chars: {sql1[:100]}...")

        sql2 = dsqgen.generate(1, seed=100)
        print(f"  Query 1 (seed 100): {len(sql2)} chars")
        print(f"  Queries different: {sql1 != sql2}")

        sql_14a = dsqgen.generate("14a", seed=42)
        print(f"  Query 14a (seed 42): {len(sql_14a)} chars")

    except Exception as e:
        print(f"  ERROR: {e}")
    print()


def test_query_manager():
    print("=" * 60)
    print("Testing TPCDSQueryManager")
    print("=" * 60)

    manager = TPCDSQueryManager()
    print("TPCDSQueryManager initialized successfully")

    try:
        sql = manager.get_query(1, seed=42)
        print(f"Query 1: {len(sql)} characters")

        sql_sf2 = manager.get_query(1, seed=42, scale_factor=2.0)
        print(f"Query 1 (SF=2): {len(sql_sf2)} characters")

        sql_stream = manager.get_query(1, seed=42, stream_id=1)
        print(f"Query 1 (stream=1): {len(sql_stream)} characters")

    except Exception as e:
        print(f"ERROR in basic query retrieval: {e}")

    try:
        variations = manager.get_query_variations(14)
        print(f"Query 14 variations: {variations}")

        for var in variations:
            sql = manager.get_query(var, seed=42)
            print(f"  {var}: {len(sql)} characters")

    except Exception as e:
        print(f"ERROR in variations: {e}")

    try:
        params = {"year": 2001, "state": "CA", "category": "Electronics"}
        sql_params = manager.generate_with_parameters(1, params)
        print(f"Query 1 with custom params: {len(sql_params)} characters")

    except Exception as e:
        print(f"ERROR in parameter generation: {e}")


if __name__ == "__main__":
    try:
        test_dsqgen_binary()
        test_query_manager()
        print("=" * 60)
        print("All tests completed successfully!")
        print("=" * 60)

    except Exception as e:
        print(f"FATAL ERROR: {e}")
        import traceback

        traceback.print_exc()
