# Copyright 2026 Joe Harris / BenchBox Project

from __future__ import annotations

import signal
from collections.abc import Generator

import pytest

from benchbox.platforms.pyspark import SparkSessionManager
from tests.utilities.optional_engines import pyspark_skip_reason, pyspark_usable

PYSPARK_SQL_TESTS_SKIPPED = not pyspark_usable()
PYSPARK_SQL_SKIP_REASON = pyspark_skip_reason() or "PySpark is usable"


@pytest.fixture(autouse=True)
def reset_spark_session_manager() -> Generator[None, None, None]:
    SparkSessionManager.close()
    yield
    SparkSessionManager.close()
    try:
        signal.signal(signal.SIGINT, signal.default_int_handler)
    except (ValueError, OSError):
        pass
