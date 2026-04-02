from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from benchbox.experimental.gpu.capabilities import GPUInfo
from benchbox.platforms import cudf as cudf_module

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _FakeArrowTable:
    def __init__(self, rows):
        self._rows = rows

    def to_pylist(self):
        return self._rows


class _FakePartialResult:
    def __init__(self, rows):
        self._rows = rows

    def to_arrow(self):
        return _FakeArrowTable(self._rows)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def __len__(self):
        return len(self._rows)

    def head(self, size):
        return _FakePartialResult(self._rows[:size])


def test_connection_execute_uses_sql_context_and_fallbacks():
    adapter = MagicMock()
    adapter.dry_run_mode = False
    wrapper = cudf_module.CuDFConnectionWrapper(adapter)

    computed = object()
    dask_result = MagicMock()
    dask_result.compute.return_value = computed
    wrapper._sql_context = MagicMock()
    wrapper._sql_context.sql.return_value = dask_result

    result = wrapper.execute("SELECT 1")

    assert isinstance(result, cudf_module.CuDFResultWrapper)
    assert wrapper._last_result is computed

    wrapper._sql_context.sql.side_effect = RuntimeError("sql failed")
    fallback = wrapper.execute("SELECT 2")
    assert isinstance(fallback, cudf_module.CuDFResultWrapper)
    assert fallback._result is None


def test_result_wrapper_fetchmany_uses_arrow_path():
    result = _FakeResult([{"a": 1}, {"a": 2}, {"a": 3}])
    wrapper = cudf_module.CuDFResultWrapper(result, MagicMock())

    rows = wrapper.fetchmany(2)

    assert rows == [(1,), (2,)]


def test_adapter_misc_methods_and_gpu_cache(monkeypatch):
    monkeypatch.setattr(cudf_module, "CUDF_AVAILABLE", True)
    monkeypatch.setattr(cudf_module, "cudf", SimpleNamespace(__version__="24.08"))
    detect = MagicMock(return_value=GPUInfo(available=False, device_count=0))
    monkeypatch.setattr(cudf_module, "detect_gpu", detect)

    adapter = cudf_module.CuDFAdapter(device_id=0)
    adapter._metrics_collector = MagicMock()

    adapter.apply_constraint_configuration(
        SimpleNamespace(enabled=True),
        SimpleNamespace(enabled=True),
        connection=None,
    )
    adapter.apply_platform_optimizations(platform_config={"x": 1}, connection=None)
    adapter.cleanup()

    assert adapter.get_gpu_metrics() == []
    first = adapter.get_gpu_info()
    second = adapter.get_gpu_info()
    assert first is second
    assert detect.call_count == 1


def test_parse_memory_limit_includes_kb_and_raw(monkeypatch):
    monkeypatch.setattr(cudf_module, "CUDF_AVAILABLE", True)
    monkeypatch.setattr(cudf_module, "cudf", SimpleNamespace(__version__="24.08"))

    adapter = cudf_module.CuDFAdapter()

    assert adapter._parse_memory_limit("8KB") == 8 * 1024
    assert adapter._parse_memory_limit("1024") == 1024
