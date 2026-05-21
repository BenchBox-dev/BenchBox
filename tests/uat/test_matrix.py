"""Fast-test coverage for tests/uat/matrix.py."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from benchbox.core.benchmark_registry import CATEGORY_ORDER
from benchbox.core.platform_registry import PlatformRegistry
from tests.uat import matrix

pytestmark = pytest.mark.fast


# ---------------------------------------------------------------------------
# resolve_platforms / resolve_benchmarks.
# ---------------------------------------------------------------------------


def test_resolve_platforms_groups_dedupe():
    out = matrix.resolve_platforms(groups=["fast", "sql"])
    assert "duckdb" in out
    # `sql` is a superset; make sure dedupe by-first-occurrence held.
    assert out.count("duckdb") == 1


def test_resolve_platforms_include_then_exclude():
    out = matrix.resolve_platforms(
        groups=["fast"],
        include=["sqlite"],
        exclude=["duckdb"],
    )
    assert "duckdb" not in out
    assert "sqlite" in out
    assert "datafusion" in out


def test_resolve_platforms_unknown_group():
    with pytest.raises(ValueError, match="Unknown platform group"):
        matrix.resolve_platforms(groups=["nope"])


def test_platform_groups_are_registry_backed():
    assert matrix.PLATFORM_GROUPS["sql"] == matrix.SQL_PLATFORMS
    assert matrix.PLATFORM_GROUPS["docker"] == matrix.DOCKER_PLATFORMS
    assert matrix.PLATFORM_GROUPS["dataframe"] == matrix.DATAFRAME_PLATFORMS
    assert set(matrix.SQL_PLATFORMS).issubset(PlatformRegistry.get_sql_platforms())
    assert set(matrix.DOCKER_PLATFORMS).issubset(PlatformRegistry.get_self_hosted_platforms())
    assert tuple(f"{platform}-df" for platform in matrix.UAT_DATAFRAME_PLATFORM_BASES) == matrix.DATAFRAME_PLATFORMS


def test_resolve_benchmarks_categories():
    out = matrix.resolve_benchmarks(groups=["tpc"])
    assert "tpch" in out
    assert "tpcds" in out


def test_resolve_benchmarks_unknown_group():
    with pytest.raises(ValueError, match="Unknown benchmark group"):
        matrix.resolve_benchmarks(groups=["nope"])


def test_category_groups_are_derived_from_registry_order():
    expected = {matrix.category_group_slug(category): (category,) for category in CATEGORY_ORDER}
    expected["all"] = tuple(CATEGORY_ORDER)

    assert expected == matrix.CATEGORY_GROUPS


# ---------------------------------------------------------------------------
# Reachability / TCP probe.
# ---------------------------------------------------------------------------


def test_platform_is_reachable_no_port_assumes_reachable():
    assert matrix.platform_is_reachable("duckdb") is True


def test_platform_is_reachable_uses_cache():
    with patch.object(matrix, "tcp_probe", return_value=False) as probe:
        assert matrix.platform_is_reachable("postgresql") is False
        assert matrix.platform_is_reachable("postgresql") is False
    assert probe.call_count == 1


def test_tcp_probe_unreachable():
    # Reserved-style high port that should be closed locally.
    assert matrix.tcp_probe("127.0.0.1", 1, timeout_s=0.5) is False


# ---------------------------------------------------------------------------
# Scale resolution.
# ---------------------------------------------------------------------------


def test_smoke_scale_for_tpch_uses_min():
    assert matrix.smoke_scale_for("tpch") == 0.01


def test_smoke_scale_for_tpcds_overrides_to_subscale():
    assert matrix.smoke_scale_for("tpcds") == 0.01


def test_filter_scales_by_registry_drops_above_max():
    info = matrix.BenchmarkInfo(
        benchmark_id="x",
        category="X",
        default_scale=1.0,
        min_scale=0.01,
        scale_options=(0.01, 0.1, 1.0),
        supports_dataframe=True,
    )
    out = matrix.filter_scales_by_registry("x", [0.01, 0.1, 1.0, 10.0], info=info)
    assert out == [0.01, 0.1, 1.0]


def test_filter_scales_by_registry_drops_below_min():
    info = matrix.BenchmarkInfo(
        benchmark_id="x",
        category="X",
        default_scale=1.0,
        min_scale=1.0,
        scale_options=(1.0,),
        supports_dataframe=True,
    )
    out = matrix.filter_scales_by_registry("x", [0.01, 0.1, 1.0], info=info)
    assert out == [1.0]


def test_filter_scales_by_registry_empty_options_passes_through():
    info = matrix.BenchmarkInfo(
        benchmark_id="x",
        category="X",
        default_scale=1.0,
        min_scale=None,
        scale_options=(),
        supports_dataframe=True,
    )
    out = matrix.filter_scales_by_registry("x", [0.5, 2.0], info=info)
    assert out == [0.5, 2.0]


# ---------------------------------------------------------------------------
# argv builders.
# ---------------------------------------------------------------------------


def test_uv_run_argv_native_uses_no_sync():
    assert matrix.uv_run_argv("duckdb") == ["uv", "run", "--no-sync", "--"]


def test_uv_run_argv_extra_uses_extra_flag():
    assert matrix.uv_run_argv("singlestore") == [
        "uv",
        "run",
        "--extra",
        "singlestore",
        "--",
    ]


def test_benchbox_run_argv_includes_platform_extras():
    argv = matrix.benchbox_run_argv("starrocks", "tpch", 0.01)
    assert "--quiet" in argv
    assert "--platform" in argv and "starrocks" in argv
    assert "--platform-option" in argv
    # The starrocks-specific port=19030 must be there.
    assert "port=19030" in argv


@pytest.mark.parametrize(
    "platform",
    ["pg-duckdb", "pg-mooncake", "timescaledb", "postgresql"],
)
def test_benchbox_run_argv_defaults_to_external_postgres_credentials(platform):
    argv = matrix.benchbox_run_argv(platform, "tpch", 0.01)
    assert "password=benchbox" not in argv


@pytest.mark.parametrize(
    "platform",
    ["pg-duckdb", "pg-mooncake", "timescaledb", "postgresql"],
)
def test_benchbox_run_argv_includes_local_managed_postgres_password_when_requested(platform):
    argv = matrix.benchbox_run_argv(platform, "tpch", 0.01, local_managed_platform=True)
    assert "--platform-option" in argv
    assert "password=benchbox" in argv


def test_benchbox_run_argv_appends_extra_args():
    argv = matrix.benchbox_run_argv("duckdb", "tpch", 0.01, extra_args=["--tuning", "tuned"])
    assert argv[-2:] == ["--tuning", "tuned"]


def test_benchbox_run_argv_velox_iterations_one():
    argv = matrix.benchbox_run_argv("velox", "tpch", 0.01)
    # CLI flags before --platform-option per the bash ordering.
    iter_idx = argv.index("--iterations")
    opt_idx = argv.index("--platform-option")
    assert iter_idx < opt_idx
