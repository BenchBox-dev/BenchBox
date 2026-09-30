"""Test utilities with lazy public helpers.

Path and state utilities must be usable before optional native probes. Preserve
existing package-level helper imports without loading DuckDB on package import.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "_benchmark_query_performance",
    "assert_valid_sql",
    "assert_benchmark_compliance",
    "generate_test_data",
    "load_tpch_data_to_duckdb",
    "setup_duckdb_extensions",
    "create_test_database",
    "validate_query_result",
    "assert_olap_features_supported",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    helper = getattr(import_module(".test_helpers", __name__), name)
    globals()[name] = helper
    return helper
