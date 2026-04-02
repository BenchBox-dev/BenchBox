"""General-purpose test utility fixtures.

Provides temp directories, compression helpers, scale factors, and SQL dialect
parameterization. Registered as a pytest plugin in root conftest.py.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

# zstandard is a runtime dependency (always available)
ZSTD_AVAILABLE = True


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
