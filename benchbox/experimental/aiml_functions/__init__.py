"""AI/ML SQL Function Performance Testing benchmark.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.

This module benchmarks AI/ML SQL functions across cloud data platforms including:
- Snowflake Cortex (sentiment analysis, classification, summarization, completion)
- BigQuery ML (ML.GENERATE_TEXT, ML.PREDICT, ML.UNDERSTAND_TEXT)
- Databricks ML (ai_query, ai_generate_text, ai_classify)

Example usage:
    >>> from benchbox.experimental.aiml_functions import AIMLFunctionsBenchmark
    >>> benchmark = AIMLFunctionsBenchmark()
    >>> queries = benchmark.get_queries_for_platform("snowflake")
    >>> result = benchmark.execute_query(conn, "sentiment_analysis")
"""

from .benchmark import AIMLFunctionsBenchmark
from .functions import (
    AIMLFunction,
    AIMLFunctionCategory,
    AIMLFunctionRegistry,
    PlatformSupport,
)
from .queries import AIMLQueryManager

__all__ = [
    "AIMLFunctionsBenchmark",
    "AIMLFunction",
    "AIMLFunctionCategory",
    "AIMLFunctionRegistry",
    "AIMLQueryManager",
    "PlatformSupport",
]
