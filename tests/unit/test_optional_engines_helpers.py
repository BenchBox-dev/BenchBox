from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import types

import pytest

from benchbox.platforms.clickhouse import _dependencies as clickhouse_dependencies
from tests.fixtures.utility_fixtures import pyspark_test_environment
from tests.utilities import optional_engines

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


class ProbeConnection:
    def __init__(self, *, fail_on: str = "", result: str = "1\n", close_error: bool = False):
        self.fail_on = fail_on
        self.result = result
        self.close_error = close_error
        self.statements: list[str] = []
        self.closed = False

    def query(self, sql: str, output_format: str) -> str:
        assert output_format == "CSV"
        self.statements.append(sql)
        if self.fail_on and sql.startswith(self.fail_on):
            raise RuntimeError("native runtime rejected the statement\ninternal detail")
        return self.result if sql.startswith("SELECT") else ""

    def close(self) -> None:
        self.closed = True
        if self.close_error:
            raise RuntimeError("native connection cleanup failed")


def _patch_chdb_connection(monkeypatch: pytest.MonkeyPatch, connection: ProbeConnection) -> list[str]:
    calls: list[str] = []

    def connect(path: str) -> ProbeConnection:
        calls.append(path)
        return connection

    _patch_import_chdb(monkeypatch, types.SimpleNamespace(connect=connect))
    return calls


def test_chdb_usable_when_the_connection_can_execute_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = ProbeConnection()
    calls = _patch_chdb_connection(monkeypatch, connection)
    assert optional_engines.chdb_skip_reason() is None
    assert optional_engines.chdb_usable()
    assert calls == [":memory:"]
    assert connection.closed
    assert connection.statements == [
        "SELECT 1",
        "CREATE TABLE benchbox_usability_probe (value UInt8) ENGINE=Memory",
        "INSERT INTO benchbox_usability_probe VALUES (1)",
        "SELECT value FROM benchbox_usability_probe",
    ]


@pytest.mark.parametrize("statement", ["SELECT 1", "CREATE TABLE", "INSERT INTO", "SELECT value"])
def test_chdb_runtime_failure_is_cached_and_closes_connection(monkeypatch, statement):
    connection = ProbeConnection(fail_on=statement)
    calls = _patch_chdb_connection(monkeypatch, connection)
    reason = optional_engines.chdb_skip_reason()
    assert "SQL runtime is unusable" in reason
    assert "internal detail" not in reason
    assert optional_engines.chdb_skip_reason() == reason
    assert calls == [":memory:"]
    assert connection.closed


def test_chdb_connection_failure_is_unusable(monkeypatch):
    def connect(path):
        raise OSError("native connection cannot start")

    _patch_import_chdb(monkeypatch, types.SimpleNamespace(connect=connect))
    assert "native connection cannot start" in optional_engines.chdb_skip_reason()


def test_chdb_unexpected_sql_result_closes_connection(monkeypatch):
    connection = ProbeConnection(result="0\n")
    _patch_chdb_connection(monkeypatch, connection)
    assert "unexpected result" in optional_engines.chdb_skip_reason()
    assert connection.closed


def test_chdb_connection_cleanup_failure_is_unusable(monkeypatch):
    connection = ProbeConnection(close_error=True)
    _patch_chdb_connection(monkeypatch, connection)
    assert "cleanup failed" in optional_engines.chdb_skip_reason()
    assert connection.closed


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


def test_pyspark_probe_does_not_set_the_worker_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pyspark(monkeypatch)
    monkeypatch.delenv("PYSPARK_PYTHON", raising=False)
    optional_engines.pyspark_skip_reason()
    assert "PYSPARK_PYTHON" not in os.environ


def test_pyspark_worker_setting_is_not_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pyspark(monkeypatch)
    monkeypatch.setenv("PYSPARK_PYTHON", "/custom/python")
    optional_engines.pyspark_skip_reason()
    assert os.environ["PYSPARK_PYTHON"] == "/custom/python"


def test_require_pyspark_skips_with_the_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pyspark(monkeypatch, java_reason="Java not found")
    with pytest.raises(pytest.skip.Exception, match="Java not found"):
        optional_engines.require_pyspark()


def _set_environment(monkeypatch, key, value):
    if value is None:
        monkeypatch.delenv(key, raising=False)
    else:
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize("original", [None, "", "/original/java"])
@pytest.mark.parametrize("failure", [False, True])
def test_pyspark_probe_restores_java_even_when_selection_fails(monkeypatch, original, failure):
    import benchbox.platforms.pyspark as platform

    _patch_pyspark(monkeypatch)
    _set_environment(monkeypatch, "JAVA_HOME", original)
    calls = []

    def select_java():
        calls.append(True)
        os.environ["JAVA_HOME"] = "/compatible/java"
        if failure:
            raise RuntimeError("Java inspection failed")
        return ""

    monkeypatch.setattr(platform, "get_java_skip_reason", select_java)
    if failure:
        with pytest.raises(RuntimeError, match="inspection failed"):
            optional_engines.pyspark_skip_reason()
    else:
        assert optional_engines.pyspark_skip_reason() is None
        assert optional_engines.pyspark_skip_reason() is None
        assert len(calls) == 1
    assert os.environ.get("JAVA_HOME") == original


@pytest.mark.parametrize("java_home", [None, "", "/original/java"])
@pytest.mark.parametrize("worker", [None, "", "/custom/python"])
def test_spark_fixture_scopes_java_and_worker_settings(monkeypatch, java_home, worker):
    import benchbox.platforms.pyspark as platform

    _patch_pyspark(monkeypatch)
    _set_environment(monkeypatch, "JAVA_HOME", java_home)
    _set_environment(monkeypatch, "PYSPARK_PYTHON", worker)

    def select_java():
        os.environ["JAVA_HOME"] = "/compatible/java"
        return ""

    monkeypatch.setattr(platform, "get_java_skip_reason", select_java)
    fixture = pyspark_test_environment.__wrapped__()
    try:
        next(fixture)
        assert os.environ["JAVA_HOME"] == "/compatible/java"
        assert os.environ["PYSPARK_PYTHON"] == (sys.executable if worker is None else worker)
    finally:
        fixture.close()
    assert os.environ.get("JAVA_HOME") == java_home
    assert os.environ.get("PYSPARK_PYTHON") == worker


@pytest.mark.parametrize("failure", ["unsupported", "exception", "test-body"])
def test_spark_fixture_restores_environment_on_skip_or_failure(monkeypatch, failure):
    import benchbox.platforms.pyspark as platform

    _patch_pyspark(monkeypatch)
    monkeypatch.delenv("JAVA_HOME", raising=False)
    monkeypatch.delenv("PYSPARK_PYTHON", raising=False)

    assert optional_engines.pyspark_skip_reason() is None

    def select_java():
        os.environ["JAVA_HOME"] = "/selected/java"
        if failure == "exception":
            raise RuntimeError("selector failed")
        return "Java not found" if failure == "unsupported" else ""

    monkeypatch.setattr(platform, "get_java_skip_reason", select_java)
    fixture = pyspark_test_environment.__wrapped__()
    try:
        if failure == "unsupported":
            with pytest.raises(pytest.skip.Exception, match="Java not found"):
                next(fixture)
        elif failure == "exception":
            with pytest.raises(RuntimeError, match="selector failed"):
                next(fixture)
        else:
            next(fixture)
            with pytest.raises(RuntimeError, match="test failed"):
                fixture.throw(RuntimeError("test failed"))
    finally:
        fixture.close()
    assert "JAVA_HOME" not in os.environ
    assert "PYSPARK_PYTHON" not in os.environ


def test_importing_optional_helpers_does_not_load_engines_or_change_environment():
    code = textwrap.dedent("""
        import importlib.abc
        import os
        import sys

        class BlockEngines(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split('.')[0] in {'chdb', 'pyspark'}:
                    raise AssertionError('engine imported: ' + fullname)

        sys.meta_path.insert(0, BlockEngines())
        before = dict(os.environ)
        cwd = os.getcwd()
        import tests.utilities.optional_engines
        import tests.fixtures.utility_fixtures
        assert dict(os.environ) == before
        assert os.getcwd() == cwd
        assert 'chdb' not in sys.modules
        assert 'pyspark' not in sys.modules
    """)
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
