"""Natural Language to SQL Testing Framework.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.

This module provides a framework for testing NL2SQL capabilities of platforms
with AI query generation features. Measures accuracy, latency, and cost of
natural language query interfaces.

Supported platforms:
- Snowflake Cortex (using COMPLETE for SQL generation)
- BigQuery (Gemini for natural language queries)
- Databricks (AI Functions for text-to-SQL)

Example usage:
    >>> from benchbox.experimental.nl2sql import NL2SQLBenchmark
    >>> benchmark = NL2SQLBenchmark()
    >>> result = benchmark.evaluate_nl2sql(conn, "Show total sales by region", platform="snowflake")
"""

from .benchmark import NL2SQLBenchmark, NL2SQLBenchmarkResults, NL2SQLQueryResult
from .evaluator import (
    AccuracyMetrics,
    NL2SQLEvaluator,
    SQLComparisonResult,
)
from .queries import (
    NL2SQLQuery,
    NL2SQLQueryCategory,
    NL2SQLQueryManager,
    QueryDifficulty,
)

__all__ = [
    # Benchmark
    "NL2SQLBenchmark",
    "NL2SQLBenchmarkResults",
    "NL2SQLQueryResult",
    # Evaluator
    "NL2SQLEvaluator",
    "SQLComparisonResult",
    "AccuracyMetrics",
    # Query Management
    "NL2SQLQuery",
    "NL2SQLQueryCategory",
    "NL2SQLQueryManager",
    "QueryDifficulty",
]
