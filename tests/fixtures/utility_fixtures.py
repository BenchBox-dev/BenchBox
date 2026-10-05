"""General-purpose test utility fixtures.

Provides temp directories, compression helpers, scale factors, and SQL dialect
parameterization. Registered as a pytest plugin in root conftest.py.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

# zstandard is a runtime dependency (always available)
ZSTD_AVAILABLE = True


@pytest.fixture(scope="module")
def pyspark_test_environment() -> Generator[None, None, None]:
    """Configure real Spark sessions and restore the caller's environment."""
    from benchbox.platforms.pyspark import get_java_skip_reason
    from tests.utilities.optional_engines import require_pyspark

    keys = ("JAVA_HOME", "PYSPARK_PYTHON")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        require_pyspark()
        reason = get_java_skip_reason()
        if reason:
            pytest.skip(reason)
        os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


SPARK_RUNTIME_ENV_KEYS = ("JAVA_HOME", "PYSPARK_PYTHON", "SPARK_AUTH_SOCKET_TIMEOUT", "SPARK_BUFFER_SIZE")


@pytest.fixture
def spark_runtime_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Own the variables that Java discovery and the PySpark gateway write while a test runs.

    ``get_java_skip_reason`` and ``ensure_compatible_java`` set ``JAVA_HOME``, and starting a real
    Spark gateway sets the two ``SPARK_*`` socket variables. They are runtime outputs of the code
    under test, so each test restores them rather than leaving them in the process.
    """
    from tests.utilities.session_isolation import own_environment

    own_environment(monkeypatch, SPARK_RUNTIME_ENV_KEYS)


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def available_compression_type() -> str:
    """Return a compression type that is available on this system.

    Returns 'zstd' if zstandard is installed, otherwise 'gzip'.
    This is useful for tests that need compression but don't specifically
    require zstd.
    """
    return "zstd" if ZSTD_AVAILABLE else "gzip"


@pytest.fixture
def zstd_available() -> bool:
    """Return whether zstandard library is available."""
    return ZSTD_AVAILABLE


# Scale factor fixtures are now consolidated in benchmark_fixtures.py
# These are kept for backward compatibility but deprecated
@pytest.fixture
def small_scale_factor() -> float:
    """Return a small scale factor for quick testing.

    DEPRECATED: Use scale_factor fixture from benchmark_fixtures.py instead.
    """
    return 1.0


@pytest.fixture
def medium_scale_factor() -> float:
    """Return a medium scale factor for more thorough testing.

    DEPRECATED: Use scale_factor fixture from benchmark_fixtures.py instead.
    """
    return 1.0


@pytest.fixture(params=["sqlite", "postgres", "mysql", "bigquery", "snowflake"])
def sql_dialect(request) -> str:
    """Parameterized fixture for testing different SQL dialects."""
    return request.param
