"""Tests for the shared optional-engine usability helpers."""

from __future__ import annotations

import os
import sys
import types

import pytest

from benchbox.platforms.clickhouse import _dependencies as clickhouse_dependencies
from tests.utilities import optional_engines

# medium keeps the fast-lane count unchanged; these tests do not need the fast tier.
pytestmark = [pytest.mark.unit, pytest.mark.medium]


@pytest.fixture(autouse=True)
def _fresh_caches():
    optional_engines.chdb_skip_reason.cache_clear()
    optional_engines.pyspark_skip_reason.cache_clear()
    yield
    optional_engines.chdb_skip_reason.cache_clear()
    optional_engines.pyspark_skip_reason.cache_clear()


def _patch_import_chdb(monkeypatch: pytest.MonkeyPatch, result: object) -> None:
    def fake() -> object:
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(clickhouse_dependencies, "import_chdb", fake)


# --------------------------------------------------------------------------- #
# chDB                                                                         #
# --------------------------------------------------------------------------- #
def test_chdb_usable_when_the_module_has_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_import_chdb(monkeypatch, types.SimpleNamespace(connect=lambda: None))
    assert optional_engines.chdb_skip_reason() is None
    assert optional_engines.chdb_usable()


def test_chdb_missing_package_reports_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_import_chdb(monkeypatch, ModuleNotFoundError("No module named 'chdb'", name="chdb"))
    assert optional_engines.chdb_skip_reason() == "chDB not installed"


def test_chdb_native_load_failure_is_reported_as_unusable(monkeypatch: pytest.MonkeyPatch) -> None:
    error = ImportError("dlopen(/x/chdb/_chdb.abi3.so, 0x0002): mis-aligned LINKEDIT string pool\nmore detail")
    _patch_import_chdb(monkeypatch, error)
    reason = optional_engines.chdb_skip_reason()
    assert reason is not None
    assert "installed but its native library cannot be loaded" in reason
    assert "mis-aligned LINKEDIT string pool" in reason
    assert "more detail" not in reason


def test_chdb_os_error_from_the_loader_is_unusable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_import_chdb(monkeypatch, OSError("cannot open shared object file"))
    assert "native library cannot be loaded" in (optional_engines.chdb_skip_reason() or "")


def test_chdb_missing_transitive_dependency_is_not_reported_as_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_import_chdb(monkeypatch, ModuleNotFoundError("No module named 'pyarrow'", name="pyarrow"))
    reason = optional_engines.chdb_skip_reason() or ""
    assert "dependency is missing" in reason
    assert reason != "chDB not installed"


def test_chdb_partial_import_without_connect_is_unusable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_import_chdb(monkeypatch, types.SimpleNamespace())
    assert "import is incomplete" in (optional_engines.chdb_skip_reason() or "")


def test_require_chdb_skips_with_the_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_import_chdb(monkeypatch, ImportError("dlopen failed"))
    with pytest.raises(pytest.skip.Exception, match="native library cannot be loaded"):
        optional_engines.require_chdb()


def test_long_reasons_are_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_import_chdb(monkeypatch, ImportError("x" * 1000))
    reason = optional_engines.chdb_skip_reason() or ""
    assert len(reason) < 400
    assert reason.endswith("...")


# --------------------------------------------------------------------------- #
# PySpark                                                                      #
# --------------------------------------------------------------------------- #
def _patch_pyspark(monkeypatch: pytest.MonkeyPatch, *, available: bool = True, java_reason: str = "") -> None:
    import benchbox.platforms.pyspark as pyspark_platform

    monkeypatch.setattr(pyspark_platform, "PYSPARK_AVAILABLE", available)
    monkeypatch.setattr(pyspark_platform, "get_java_skip_reason", lambda: java_reason)
    monkeypatch.setattr(sys, "platform", "linux")


def test_pyspark_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pyspark(monkeypatch, available=False)
    assert optional_engines.pyspark_skip_reason() == "PySpark not installed"


def test_pyspark_unsupported_java_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pyspark(monkeypatch, java_reason="PySpark 4.x not compatible with Java 26")
    monkeypatch.setenv("PYSPARK_PYTHON", sys.executable)
    assert optional_engines.pyspark_skip_reason() == "PySpark 4.x not compatible with Java 26"
    assert not optional_engines.pyspark_usable()


def test_pyspark_usable_with_supported_java(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pyspark(monkeypatch)
    monkeypatch.setenv("PYSPARK_PYTHON", sys.executable)
    assert optional_engines.pyspark_skip_reason() is None


def test_pyspark_windows_is_skipped_with_a_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pyspark(monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    assert "Windows" in (optional_engines.pyspark_skip_reason() or "")


def test_pyspark_worker_defaults_to_the_driver_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pyspark(monkeypatch)
    monkeypatch.setenv("PYSPARK_PYTHON", "placeholder")  # records the original so teardown restores it
    monkeypatch.delenv("PYSPARK_PYTHON")
    optional_engines.pyspark_skip_reason()
    assert os.environ["PYSPARK_PYTHON"] == sys.executable


def test_pyspark_worker_setting_is_not_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pyspark(monkeypatch)
    monkeypatch.setenv("PYSPARK_PYTHON", "/custom/python")
    optional_engines.pyspark_skip_reason()
    assert os.environ["PYSPARK_PYTHON"] == "/custom/python"


def test_require_pyspark_skips_with_the_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pyspark(monkeypatch, java_reason="Java not found")
    with pytest.raises(pytest.skip.Exception, match="Java not found"):
        optional_engines.require_pyspark()
