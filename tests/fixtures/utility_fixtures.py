# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

ZSTD_AVAILABLE = True


@pytest.fixture(scope="module")
def pyspark_test_environment() -> Generator[None, None, None]:
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
    from tests.utilities.session_isolation import own_environment

    own_environment(monkeypatch, SPARK_RUNTIME_ENV_KEYS)


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def available_compression_type() -> str:
    return "zstd" if ZSTD_AVAILABLE else "gzip"


@pytest.fixture
def zstd_available() -> bool:
    return ZSTD_AVAILABLE


@pytest.fixture
def small_scale_factor() -> float:
    return 1.0


@pytest.fixture
def medium_scale_factor() -> float:
    return 1.0


@pytest.fixture(params=["sqlite", "postgres", "mysql", "bigquery", "snowflake"])
def sql_dialect(request) -> str:
    return request.param
