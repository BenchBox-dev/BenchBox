"""Tests for side-effect-free platform readiness diagnostics."""

from __future__ import annotations

import pytest

from benchbox.cli import platform_readiness as readiness

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_dataframe_aliases_normalize_to_registry_platforms():
    assert readiness.normalize_readiness_platform("lakesail-df") == "lakesail"
    assert readiness.normalize_readiness_platform("modin-df") == "modin"
    assert readiness.normalize_readiness_platform("datafusion-df") == "datafusion"


def test_unknown_platform_has_no_readiness_checks():
    assert readiness.check_platform_readiness("duckdb") == ()


def test_local_tcp_endpoint_ready_when_socket_connects(monkeypatch):
    monkeypatch.setattr(readiness, "_tcp_reachable", lambda host, port, timeout: True)

    result = readiness.check_platform_readiness("trino")[0]

    assert result.ready is True
    assert result.status == "ready"
    assert result.endpoint == "localhost:18080"
    assert "reachable" in result.summary


def test_local_tcp_endpoint_unreachable_is_environment_skip(monkeypatch):
    monkeypatch.setattr(readiness, "_tcp_reachable", lambda host, port, timeout: False)

    result = readiness.check_platform_readiness("clickhouse-server")[0]

    assert result.ready is False
    assert result.status == "environment_skip"
    assert result.check == "local_tcp_endpoint"
    assert result.endpoint == "localhost:9000"
    assert "Benchmarks for this platform should be skipped" in result.detail


def test_lakesail_unreachable_endpoint_reports_environment_skip_without_starting_sail(monkeypatch):
    module_checks: list[str] = []

    def module_available(name: str) -> bool:
        module_checks.append(name)
        return name in {"pyspark", "pysail"}

    monkeypatch.setattr(readiness, "_module_available", module_available)
    monkeypatch.setattr(
        readiness,
        "_configured_lakesail_config",
        lambda: readiness.LakeSailReadinessConfig(endpoint="sc://localhost:50051", sail_mode="local"),
    )
    monkeypatch.setattr(readiness, "_tcp_reachable", lambda host, port, timeout: False)

    results = readiness.check_platform_readiness("lakesail-df")

    assert [result.check for result in results] == ["pyspark_client", "spark_connect_endpoint"]
    assert results[0].ready is True
    assert results[1].status == "environment_skip"
    assert results[1].endpoint == "sc://localhost:50051"
    assert "does not start" in results[1].detail
    assert module_checks == ["pyspark", "pysail"]


def test_lakesail_sql_unreachable_endpoint_is_ready_when_pysail_importable(monkeypatch):
    """w23 regression: when the Spark Connect endpoint is unreachable but
    pysail is importable, the SQL adapter (`lakesail`) can auto-start a local
    Sail server at run time, so readiness must report ``ready`` rather than
    ``environment_skip`` (which would fail ``benchbox platforms check`` for a
    legitimately runnable adapter)."""
    module_checks: list[str] = []

    def module_available(name: str) -> bool:
        module_checks.append(name)
        return name in {"pyspark", "pysail"}

    monkeypatch.setattr(readiness, "_module_available", module_available)
    monkeypatch.setattr(
        readiness,
        "_configured_lakesail_config",
        lambda: readiness.LakeSailReadinessConfig(endpoint="sc://localhost:50051", sail_mode="local"),
    )
    monkeypatch.setattr(readiness, "_tcp_reachable", lambda host, port, timeout: False)

    results = readiness.check_platform_readiness("lakesail")

    assert [result.check for result in results] == ["pyspark_client", "spark_connect_endpoint"]
    assert all(result.ready for result in results), [(r.check, r.status, r.summary) for r in results]
    assert results[1].status == "ready"
    assert "auto-start" in results[1].summary or "auto-start" in (results[1].detail or "")


def test_lakesail_sql_unreachable_distributed_endpoint_is_environment_skip_when_pysail_importable(monkeypatch):
    """Remote/distributed LakeSail endpoints cannot be auto-started."""
    monkeypatch.setattr(readiness, "_module_available", lambda name: name in {"pyspark", "pysail"})
    monkeypatch.setattr(
        readiness,
        "_configured_lakesail_config",
        lambda: readiness.LakeSailReadinessConfig(endpoint="sc://remote-sail:50051", sail_mode="distributed"),
    )
    monkeypatch.setattr(readiness, "_tcp_reachable", lambda host, port, timeout: False)

    results = readiness.check_platform_readiness("lakesail")

    assert results[1].check == "spark_connect_endpoint"
    assert results[1].status == "environment_skip"
    assert "sail_mode='distributed'" in results[1].detail


def test_lakesail_dataframe_mode_still_requires_running_endpoint(monkeypatch):
    """w23 regression (negative side): the DataFrame adapter (`lakesail-df`)
    cannot auto-start; pysail being importable does NOT make it ready when
    the endpoint is unreachable."""
    monkeypatch.setattr(readiness, "_module_available", lambda name: name in {"pyspark", "pysail"})
    monkeypatch.setattr(
        readiness,
        "_configured_lakesail_config",
        lambda: readiness.LakeSailReadinessConfig(endpoint="sc://localhost:50051", sail_mode="local"),
    )
    monkeypatch.setattr(readiness, "_tcp_reachable", lambda host, port, timeout: False)

    results = readiness.check_platform_readiness("lakesail-df")

    assert results[1].check == "spark_connect_endpoint"
    assert results[1].status == "environment_skip"


def test_lakesail_reachable_endpoint_is_ready(monkeypatch):
    monkeypatch.setattr(readiness, "_module_available", lambda name: name == "pyspark")
    monkeypatch.setattr(
        readiness,
        "_configured_lakesail_config",
        lambda: readiness.LakeSailReadinessConfig(endpoint="sc://sail-host:50052", sail_mode="distributed"),
    )
    monkeypatch.setattr(readiness, "_tcp_reachable", lambda host, port, timeout: (host, port) == ("sail-host", 50052))

    results = readiness.check_platform_readiness("lakesail")

    assert all(result.ready for result in results)
    assert results[1].check == "spark_connect_endpoint"
    assert results[1].endpoint == "sc://sail-host:50052"


def test_modin_missing_package_is_environment_skip(monkeypatch):
    monkeypatch.setattr(readiness, "_module_available", lambda name: False)

    result = readiness.check_platform_readiness("modin-df")[0]

    assert result.status == "environment_skip"
    assert result.check == "modin_package"
    assert "uv add benchbox --extra modin" in result.remediation


def test_modin_missing_selected_backend_is_environment_skip(monkeypatch):
    monkeypatch.setenv("MODIN_ENGINE", "ray")
    monkeypatch.setattr(readiness, "_module_available", lambda name: name == "modin")

    results = readiness.check_platform_readiness("modin-df")

    assert results[0].ready is True
    assert results[1].status == "environment_skip"
    assert results[1].check == "modin_backend"
    assert '"modin[ray]"' in results[1].remediation
    assert "does not import modin.pandas" in results[1].detail


def test_modin_dask_backend_ready_when_backend_package_is_importable(monkeypatch):
    monkeypatch.setenv("MODIN_ENGINE", "dask")
    monkeypatch.setattr(readiness, "_module_available", lambda name: name in {"modin", "dask"})

    results = readiness.check_platform_readiness("modin")

    assert [result.status for result in results] == ["ready", "ready"]
    assert "MODIN_ENGINE=dask" in results[1].summary


def test_modin_unsupported_backend_is_environment_skip(monkeypatch):
    monkeypatch.setenv("MODIN_ENGINE", "unsupported")
    monkeypatch.setattr(readiness, "_module_available", lambda name: name == "modin")

    results = readiness.check_platform_readiness("modin")

    assert results[1].status == "environment_skip"
    assert "MODIN_ENGINE='unsupported'" in results[1].summary
    assert "ray, dask, or unidist" in results[1].remediation
