"""Shared fixtures and helpers for PySpark platform tests.

This module provides pytest fixtures and skip conditions for PySpark tests.
It uses the centralized Java version detection from benchbox.platforms.pyspark.

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import signal
from collections.abc import Generator

import pytest

from benchbox.platforms.pyspark import SparkSessionManager
from tests.utilities.optional_engines import pyspark_skip_reason, pyspark_usable

# Skip unless a local Spark session can start: PySpark installed, supported JDK
# (JAVA_HOME is switched at import time when the default is unsupported) and a
# matching Python worker. Windows is skipped because Hadoop requires winutils.exe.
PYSPARK_SQL_TESTS_SKIPPED = not pyspark_usable()
PYSPARK_SQL_SKIP_REASON = pyspark_skip_reason() or "PySpark is usable"


@pytest.fixture(autouse=True)
def reset_spark_session_manager() -> Generator[None, None, None]:
    """Ensure SparkSessionManager is reset between tests."""
    SparkSessionManager.close()
    yield
    SparkSessionManager.close()
    # PySpark installs a SIGINT handler on SparkContext creation. When running under
    # pytest-xdist, that handler can fire after _jsc is set to None during worker
    # shutdown, causing `AttributeError: 'NoneType' object has no attribute 'sc'`
    # and hanging the worker process. Restore the default handler after teardown.
    try:
        signal.signal(signal.SIGINT, signal.default_int_handler)
    except (ValueError, OSError):
        pass  # No-op in non-main threads
