"""Optional dependencies for ClickHouse platform support."""

from __future__ import annotations

import importlib
import os
from types import ModuleType

try:
    from clickhouse_driver import Client as ClickHouseClient
    from clickhouse_driver.errors import Error as ClickHouseError
except ImportError:  # pragma: no cover - optional dependency
    ClickHouseClient = None
    ClickHouseError = Exception

try:
    import clickhouse_connect
except ImportError:  # pragma: no cover - optional dependency
    clickhouse_connect = None

chdb: ModuleType | None = None


def _import_with_cwd_restore(module_name: str) -> ModuleType:
    """Import an optional module without leaking a temporary working directory."""
    original_cwd = os.getcwd()
    try:
        return importlib.import_module(module_name)
    finally:
        os.chdir(original_cwd)


def import_chdb() -> ModuleType:
    """Import chDB and restore the caller's cwd even when native loading fails."""
    global chdb
    chdb = _import_with_cwd_restore("chdb")
    return chdb


def import_chdb_session() -> ModuleType:
    """Import chDB's session module through the cwd-safe package import."""
    import_chdb()
    return _import_with_cwd_restore("chdb.session")


__all__ = [
    "ClickHouseClient",
    "ClickHouseError",
    "clickhouse_connect",
    "chdb",
    "import_chdb",
    "import_chdb_session",
]
