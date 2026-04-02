import types

import pytest

from benchbox.cli.execution_pipeline import ExecutionContext, ExecutionEngine
from benchbox.core.schemas import BenchmarkConfig, DatabaseConfig
from tests.fixtures.result_dict_fixtures import make_benchmark_results

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _make_benchmark_config() -> BenchmarkConfig:
    return BenchmarkConfig(name="tpch", display_name="TPC-H")


def _make_database_config() -> DatabaseConfig:
    return DatabaseConfig(
        type="duckdb",
        name="DuckDB",
        driver_package="duckdb",
        driver_version="1.0.0",
        driver_auto_install=True,
    )


def _make_result():
    result = make_benchmark_results(
        benchmark_id="tpch",
        benchmark_name="TPC-H",
        execution_id="test",
    )
    result.summary_metrics = {}
    return result


def test_execution_engine_enrich_driver_metadata_prefers_adapter(monkeypatch):
    engine = ExecutionEngine()
    adapter = types.SimpleNamespace(
        driver_package="duckdb",
        driver_version_requested="1.1.0",
        driver_version_resolved="1.1.0",
        driver_version_actual="1.1.0",
        driver_runtime_strategy="isolated-site-packages",
        driver_runtime_path="/tmp/driver-runtime",
        driver_runtime_python_executable="/tmp/driver-runtime/bin/python",
        driver_auto_install_used=True,
    )
    result = _make_result()
    result.execution_metadata = {}

    context = ExecutionContext(
        benchmark_config=_make_benchmark_config(),
        database_config=_make_database_config(),
        platform_adapter=adapter,
        result=result,
    )

    engine._enrich_driver_metadata(context)

    assert result.driver_package == "duckdb"
    assert result.driver_version_requested == "1.1.0"
    assert result.driver_version_resolved == "1.1.0"
    assert result.driver_version_actual == "1.1.0"
    assert result.driver_runtime_strategy == "isolated-site-packages"
    assert result.driver_runtime_path == "/tmp/driver-runtime"
    assert result.driver_runtime_python_executable == "/tmp/driver-runtime/bin/python"
    assert result.driver_auto_install is True
    assert result.execution_metadata["driver_version_resolved"] == "1.1.0"
    assert result.execution_metadata["driver_version_actual"] == "1.1.0"
    assert result.execution_metadata["driver_runtime_strategy"] == "isolated-site-packages"
    assert result.execution_metadata["driver_runtime_path"] == "/tmp/driver-runtime"
    assert result.execution_metadata["driver_runtime_python_executable"] == "/tmp/driver-runtime/bin/python"
    assert result.execution_metadata["driver_auto_install_used"] is True


def test_execution_engine_enrich_driver_metadata_falls_back_to_config(monkeypatch):
    engine = ExecutionEngine()
    adapter = types.SimpleNamespace()
    result = _make_result()
    result.execution_metadata = {}

    db_config = _make_database_config()
    db_config.driver_version_resolved = "1.0.0"
    db_config.driver_version_actual = "1.0.0"
    db_config.driver_runtime_strategy = "current-process"
    db_config.driver_runtime_python_executable = "/tmp/python"

    context = ExecutionContext(
        benchmark_config=_make_benchmark_config(),
        database_config=db_config,
        platform_adapter=adapter,
        result=result,
    )

    engine._enrich_driver_metadata(context)

    assert result.driver_package == "duckdb"
    assert result.driver_version_requested == "1.0.0"
    assert result.driver_version_resolved == "1.0.0"
    assert result.driver_version_actual == "1.0.0"
    assert result.driver_runtime_strategy == "current-process"
    assert result.driver_runtime_python_executable == "/tmp/python"
    assert result.driver_auto_install is True
