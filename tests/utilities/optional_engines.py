"""Availability checks for optional engines that can be installed yet unusable.

``pytest.importorskip`` and ``find_spec`` only prove that a package is present.
Two engines can be present and still fail every test that touches them:

* chDB ships a native library that can fail to load (for example an unsupported
  macOS release), which raises ``ImportError``/``OSError`` from the import.
* PySpark needs a supported JDK for its JVM gateway and a Python worker that
  matches the driver's minor version.

The helpers here test usability rather than presence and return a human-readable
reason, so a test module skips with an explicit cause instead of failing. They
never affect required engines (DuckDB, DataFusion, Polars).

Each result is computed once per process, on first use, so importing this
module never loads a native library. Usage::

    from tests.utilities.optional_engines import require_chdb

    chdb = require_chdb()  # at module level: skips the whole module with the reason
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from types import ModuleType

import pytest

_MAX_REASON_CHARS = 240


def _first_line(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return text if len(text) <= _MAX_REASON_CHARS else text[: _MAX_REASON_CHARS - 3] + "..."


@lru_cache(maxsize=1)
def chdb_skip_reason() -> str | None:
    """Return why chDB cannot be used here, or ``None`` when it is usable.

    Goes through the cwd-safe import helper because chDB leaves the process in
    its package directory when the native library fails to load.
    """
    from benchbox.platforms.clickhouse._dependencies import import_chdb

    try:
        module = import_chdb()
    except ModuleNotFoundError as exc:
        if exc.name == "chdb":
            return "chDB not installed"
        return f"chDB is installed but a dependency is missing: {_first_line(exc)}"
    except (ImportError, OSError) as exc:
        return f"chDB is installed but its native library cannot be loaded: {_first_line(exc)}"

    if not hasattr(module, "connect"):
        return "chDB is installed but its import is incomplete (no connect attribute)"
    try:
        connection = module.connect(":memory:")
        try:
            if str(connection.query("SELECT 1", "CSV")).strip() != "1":
                return "chDB is installed but its SQL probe returned an unexpected result"
            connection.query("CREATE TABLE benchbox_usability_probe (value UInt8) ENGINE=Memory", "CSV")
            connection.query("INSERT INTO benchbox_usability_probe VALUES (1)", "CSV")
            if str(connection.query("SELECT value FROM benchbox_usability_probe", "CSV")).strip() != "1":
                return "chDB is installed but its table probe returned an unexpected result"
        finally:
            connection.close()
    except (ImportError, OSError, RuntimeError, getattr(module, "ChdbError", RuntimeError)) as exc:
        return f"chDB is installed but its connection or SQL runtime is unusable: {_first_line(exc)}"
    return None


def chdb_usable() -> bool:
    return chdb_skip_reason() is None


def require_chdb() -> ModuleType:
    """Return the chDB module, or skip the calling test (or module) with the reason."""
    from benchbox.platforms.clickhouse._dependencies import import_chdb

    reason = chdb_skip_reason()
    if reason is not None:
        pytest.skip(reason, allow_module_level=True)
    return import_chdb()


@lru_cache(maxsize=1)
def pyspark_skip_reason() -> str | None:
    """Return why a local Spark session cannot run here, or ``None`` when it can.

    Checks platform support, installation, and a supported JDK without
    retaining environment changes. Real sessions configure Java and their
    Python worker through the scoped ``pyspark_test_environment`` fixture.
    """
    if sys.platform == "win32":
        return "PySpark tests skipped on Windows - Hadoop requires winutils.exe setup"

    from benchbox.platforms.pyspark import PYSPARK_AVAILABLE, get_java_skip_reason

    if not PYSPARK_AVAILABLE:
        return "PySpark not installed"

    java_home = os.environ.get("JAVA_HOME")
    try:
        java_reason = get_java_skip_reason()
    finally:
        if java_home is None:
            os.environ.pop("JAVA_HOME", None)
        else:
            os.environ["JAVA_HOME"] = java_home
    if java_reason:
        return java_reason
    return None


def pyspark_usable() -> bool:
    return pyspark_skip_reason() is None


def require_pyspark() -> None:
    """Skip the calling test (or fixture) with the reason PySpark is unusable."""
    reason = pyspark_skip_reason()
    if reason is not None:
        pytest.skip(reason)
