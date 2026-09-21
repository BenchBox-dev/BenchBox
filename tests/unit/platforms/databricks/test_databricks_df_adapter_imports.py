"""Import-branch tests for the Databricks DataFrame adapter miss clusters.

Covers the module-level availability probes that only run at import time:
a working databricks.connect, a crashing one (defensive guard), and a
missing pyspark. Each case reloads the module with a staged sys.modules
entry and restores the real environment in a finally block (manual
save/restore, since the restore reload must observe the real tree).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock

import pytest

from benchbox.platforms.databricks import dataframe_adapter as mod

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.cloud_import,
]


def _reload_adapter():
    return importlib.reload(mod)


def _stage(entries: dict[str, object]) -> dict[str, object]:
    saved = {name: sys.modules[name] for name in entries if name in sys.modules}
    sys.modules.update(entries)
    return saved


def _unstage(entries: dict[str, object], saved: dict[str, object]) -> None:
    for name in entries:
        if name in saved:
            sys.modules[name] = saved[name]
        else:
            sys.modules.pop(name, None)


def test_reload_with_working_databricks_connect():
    """A working databricks.connect marks the extra available."""
    initial_available = mod.DATABRICKS_CONNECT_AVAILABLE
    initial_error = mod._databricks_connect_error
    pkg = types.ModuleType("databricks")
    pkg.__path__ = []
    connect = types.ModuleType("databricks.connect")
    connect.DatabricksSession = MagicMock(name="DatabricksSession")
    staged = {"databricks": pkg, "databricks.connect": connect}
    saved = _stage(staged)
    try:
        _reload_adapter()
        assert mod.DATABRICKS_CONNECT_AVAILABLE is True
        assert mod._databricks_connect_error is None
    finally:
        _unstage(staged, saved)
        _reload_adapter()
    assert initial_available == mod.DATABRICKS_CONNECT_AVAILABLE
    assert mod._databricks_connect_error == initial_error


def test_reload_with_crashing_databricks_connect():
    """A databricks.connect that explodes on import stays unavailable with cause."""

    def _raise(_name):
        raise RuntimeError("shim boom")

    pkg = types.ModuleType("databricks")
    pkg.__path__ = []
    connect = types.ModuleType("databricks.connect")
    connect.__getattr__ = _raise
    staged = {"databricks": pkg, "databricks.connect": connect}
    saved = _stage(staged)
    try:
        _reload_adapter()
        assert mod.DATABRICKS_CONNECT_AVAILABLE is False
        assert mod._databricks_connect_error == "shim boom"
    finally:
        _unstage(staged, saved)
        _reload_adapter()


def test_reload_without_pyspark():
    """Missing pyspark degrades the adapter module to Any aliases."""
    import typing

    staged = {"pyspark.sql": None}
    saved = _stage(staged)
    try:
        _reload_adapter()
        assert mod.PYSPARK_AVAILABLE is False
        assert mod.SparkDataFrame is typing.Any
        assert mod.F is None
    finally:
        _unstage(staged, saved)
        _reload_adapter()
    assert mod.PYSPARK_AVAILABLE is True
