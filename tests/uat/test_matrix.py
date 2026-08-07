"""Fast-test coverage for tests/uat/matrix.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

from benchbox.core.benchmark_registry import CATEGORY_ORDER
from benchbox.core.platform_registry import PlatformRegistry
from tests.uat import compatibility, matrix
from tests.uat.config import load_config, validate_config
from tests.uat.phases import enumerate as enum_phase

pytestmark = pytest.mark.fast

_RELEASE_GATE_CONFIGS_DIR = Path(__file__).parent / "configs"


def _release_gate_config_names() -> tuple[str, ...]:
    """Discover `release-gate-*.yaml` configs by glob rather than a hardcoded
    list, so a future `release-gate-04-*.yaml` stage is automatically probed
    by `test_release_gate_platforms_resolve_from_dev_venv_or_have_uv_extra`
    (uat-operator-provisioning review response, 2026-07-19)."""
    return tuple(sorted(path.name for path in _RELEASE_GATE_CONFIGS_DIR.glob("release-gate-*.yaml")))


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
    assert matrix.PLATFORM_GROUPS["native-sql"] == matrix.FAST_NATIVE_PLATFORMS + matrix.SLOW_NATIVE_PLATFORMS
    assert matrix.PLATFORM_GROUPS["docker"] == matrix.DOCKER_PLATFORMS
    assert matrix.PLATFORM_GROUPS["dataframe"] == matrix.DATAFRAME_PLATFORMS
    assert set(matrix.SQL_PLATFORMS).issubset(PlatformRegistry.get_sql_platforms())
    assert set(matrix.PLATFORM_GROUPS["native-sql"]).issubset(PlatformRegistry.get_sql_platforms())
    assert set(matrix.PLATFORM_GROUPS["native-sql"]).isdisjoint(matrix.DOCKER_PLATFORMS)
    assert set(matrix.DOCKER_PLATFORMS).issubset(PlatformRegistry.get_self_hosted_platforms())
    assert tuple(f"{platform}-df" for platform in matrix.UAT_DATAFRAME_PLATFORM_BASES) == matrix.DATAFRAME_PLATFORMS


def test_dataframe_mutation_compatibility_rules_cover_dataframe_group():
    benchmarks = matrix.load_benchmarks()

    for platform in matrix.DATAFRAME_PLATFORMS:
        for benchmark in ("transaction_primitives", "tpcdi"):
            rule = compatibility.compatibility_rule_for(platform, benchmark, benchmarks[benchmark])
            assert rule is not None
            assert rule.rule_id == f"uat.compat.{platform}.{benchmark}.benchmark_gate"


def test_native_model_compatibility_rules_cover_fast_native_targets():
    benchmarks = matrix.load_benchmarks()

    for platform in ("datafusion", "clickhouse-local"):
        assert platform in matrix.PLATFORM_GROUPS["fast"]
        for benchmark in ("write_primitives", "transaction_primitives", "ai_primitives"):
            rule = compatibility.compatibility_rule_for(platform, benchmark, benchmarks[benchmark])
            assert rule is not None
            assert rule.rule_id == f"uat.compat.{platform}.{benchmark}.benchmark_gate"


def test_postgresql_write_primitives_is_a_supported_uat_cell():
    """postgresql x write_primitives must stay an enumerable (un-pruned) UAT cell.

    The three SCD2 ops run green on live PostgreSQL (see
    tests/integration/platforms/test_write_primitives_scd2_postgresql_live.py),
    so the pair must not be compatibility-pruned. This guards audit finding C: the
    ops were correct-but-unexecuted, and a future benchmark gate must not silently
    drop the cell without also removing the live coverage.
    """
    benchmarks = matrix.load_benchmarks()
    assert "postgresql" in matrix.DOCKER_PLATFORMS
    rule = compatibility.compatibility_rule_for("postgresql", "write_primitives", benchmarks["write_primitives"])
    assert rule is None, f"postgresql x write_primitives unexpectedly pruned: {rule}"


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
# missing_benchmarks_from_include (uat-accounting-hardening w2).
# ---------------------------------------------------------------------------


def test_missing_benchmarks_from_include_flags_unknown_ids():
    benchmarks = matrix.load_benchmarks()
    out = matrix.missing_benchmarks_from_include(["tpch", "totally_bogus_benchmark_xyz"], benchmarks)
    assert out == ["totally_bogus_benchmark_xyz"]


def test_missing_benchmarks_from_include_dedupes_and_preserves_order():
    benchmarks = matrix.load_benchmarks()
    out = matrix.missing_benchmarks_from_include(["bogus_a", "tpch", "bogus_b", "bogus_a"], benchmarks)
    assert out == ["bogus_a", "bogus_b"]


def test_missing_benchmarks_from_include_empty_when_all_known():
    benchmarks = matrix.load_benchmarks()
    assert matrix.missing_benchmarks_from_include(["tpch", "tpcds"], benchmarks) == []


def test_missing_benchmarks_from_include_matches_resolve_benchmarks_drop():
    """`resolve_benchmarks` silently drops unknown `include` ids; this helper
    must flag exactly the ids that drop causes, so accounting stays honest."""
    benchmarks = matrix.load_benchmarks()
    include = ["tpch", "totally_bogus_benchmark_xyz"]
    resolved = matrix.resolve_benchmarks(include=include, benchmarks=benchmarks)
    missing = matrix.missing_benchmarks_from_include(include, benchmarks)
    assert set(include) == set(resolved) | set(missing)
    assert set(resolved) & set(missing) == set()


# ---------------------------------------------------------------------------
# known_platform_ids / missing_platforms_from_include
# (uat-config-schema-spec-realignment w2 -- mirrors missing_benchmarks_from_include).
# ---------------------------------------------------------------------------


def test_known_platform_ids_covers_curated_groups():
    known = matrix.known_platform_ids()
    assert set(matrix.SQL_PLATFORMS).issubset(known)
    assert set(matrix.DATAFRAME_PLATFORMS).issubset(known)
    assert "duckdb" in known
    assert "polars-df" in known


def test_missing_platforms_from_include_flags_unknown_ids():
    out = matrix.missing_platforms_from_include(["duckdb", "totally_bogus_platform_xyz"])
    assert out == ["totally_bogus_platform_xyz"]


def test_missing_platforms_from_include_dedupes_and_preserves_order():
    out = matrix.missing_platforms_from_include(["bogus_a", "duckdb", "bogus_b", "bogus_a"])
    assert out == ["bogus_a", "bogus_b"]


def test_missing_platforms_from_include_empty_when_all_known():
    assert matrix.missing_platforms_from_include(["duckdb", "polars-df"]) == []


def test_missing_platforms_from_include_matches_resolve_platforms_drop():
    """`resolve_platforms` silently drops unknown `include` ids (mirrors
    `resolve_benchmarks`); this helper must flag exactly the ids that drop
    causes, so accounting stays honest."""
    include = ["duckdb", "totally_bogus_platform_xyz"]
    resolved = matrix.resolve_platforms(include=include)
    missing = matrix.missing_platforms_from_include(include)
    assert set(include) == set(resolved) | set(missing)
    assert set(resolved) & set(missing) == set()


# ---------------------------------------------------------------------------
# enumerate_cells_with_pruning registry/ladder accounting
# (uat-accounting-hardening w2/w3): a typo'd benchmark id or a scale outside
# the registry's declared scale_options must produce a visible accounting
# row instead of a silent drop.
# ---------------------------------------------------------------------------


def _registry_cfg(payload: dict):
    return validate_config({"name": "matrix-registry-test", **payload})


def test_enumerate_with_pruning_records_registry_missing_benchmark():
    raw = {
        "platforms": {"include": ["duckdb", "sqlite"]},
        "benchmarks": {"include": ["tpch", "totally_bogus_benchmark_xyz"]},
        "scales": {"rungs": [0.01, 0.1]},
    }

    result = enum_phase.enumerate_cells_with_pruning(_registry_cfg(raw))

    assert {c.benchmark for c in result.cells} == {"tpch"}
    missing_rows = [c for c in result.compatibility_pruned if c.rule_id == "benchmark-not-in-registry"]
    # One row per platform x requested scale for the missing benchmark - it
    # must be visible in accounting output, not silently absent.
    assert {(c.platform, c.benchmark, c.scale) for c in missing_rows} == {
        ("duckdb", "totally_bogus_benchmark_xyz", 0.01),
        ("duckdb", "totally_bogus_benchmark_xyz", 0.1),
        ("sqlite", "totally_bogus_benchmark_xyz", 0.01),
        ("sqlite", "totally_bogus_benchmark_xyz", 0.1),
    }
    assert all(c.status == enum_phase.REGISTRY_PRUNE_STATUS for c in missing_rows)
    assert result.candidate_count == len(result.cells) + len(result.compatibility_pruned)


def test_enumerate_with_pruning_records_registry_missing_platform():
    raw = {
        "platforms": {"include": ["duckdb", "totally_bogus_platform_xyz"]},
        "benchmarks": {"include": ["tpch", "tpcds"]},
        "scales": {"rungs": [0.01, 0.1]},
    }

    result = enum_phase.enumerate_cells_with_pruning(_registry_cfg(raw))

    assert {c.platform for c in result.cells} == {"duckdb"}
    missing_rows = [c for c in result.compatibility_pruned if c.rule_id == "platform-not-in-registry"]
    # One row per missing platform x resolved benchmark x requested scale -
    # it must be visible in accounting output, not silently absent.
    assert {(c.platform, c.benchmark, c.scale) for c in missing_rows} == {
        ("totally_bogus_platform_xyz", "tpch", 0.01),
        ("totally_bogus_platform_xyz", "tpch", 0.1),
        ("totally_bogus_platform_xyz", "tpcds", 0.01),
        ("totally_bogus_platform_xyz", "tpcds", 0.1),
    }
    assert all(c.status == enum_phase.REGISTRY_PRUNE_STATUS for c in missing_rows)
    assert result.candidate_count == len(result.cells) + len(result.compatibility_pruned)


def test_enumerate_with_pruning_records_both_unknown_include_dimensions():
    raw = {
        "platforms": {"include": ["totally_bogus_platform_xyz"]},
        "benchmarks": {"include": ["totally_bogus_benchmark_xyz"]},
        "scales": {"rungs": [0.01]},
    }

    result = enum_phase.enumerate_cells_with_pruning(_registry_cfg(raw))

    assert result.cells == ()
    assert {(row.rule_id, row.platform, row.benchmark, row.scale) for row in result.compatibility_pruned} == {
        ("platform-not-in-registry", "totally_bogus_platform_xyz", "totally_bogus_benchmark_xyz", 0.01),
        ("benchmark-not-in-registry", "totally_bogus_platform_xyz", "totally_bogus_benchmark_xyz", 0.01),
    }


def test_enumerate_with_pruning_records_ladder_pruned_scales():
    raw = {
        "platforms": {"include": ["duckdb"]},
        "benchmarks": {"include": ["tpch"]},
        # 50.0 is not one of tpch's declared scale_options (0.01, 0.1, 1.0,
        # 10.0, 30.0, 100.0, 300.0, ...); it must be dropped AND recorded
        # instead of vanishing from the denominator (PR #332 follow-up).
        "scales": {"rungs": [0.01, 50.0]},
    }

    result = enum_phase.enumerate_cells_with_pruning(_registry_cfg(raw))

    assert {c.scale for c in result.cells} == {0.01}
    ladder_rows = [c for c in result.compatibility_pruned if c.rule_id.startswith("uat.ladder.")]
    assert len(ladder_rows) == 1
    row = ladder_rows[0]
    assert (row.platform, row.benchmark, row.scale) == ("duckdb", "tpch", 50.0)
    assert row.status == enum_phase.REGISTRY_PRUNE_STATUS
    assert result.candidate_count == len(result.cells) + len(result.compatibility_pruned)


def test_enumerate_with_pruning_ladder_scale_survives_when_in_registry():
    """Sanity check: no spurious ladder-pruned row for an in-registry scale."""
    raw = {
        "platforms": {"include": ["duckdb"]},
        "benchmarks": {"include": ["tpch"]},
        "scales": {"rungs": [0.01, 0.1]},
    }

    result = enum_phase.enumerate_cells_with_pruning(_registry_cfg(raw))

    assert {c.scale for c in result.cells} == {0.01, 0.1}
    assert result.compatibility_pruned == ()


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


def test_uv_run_argv_clickhouse_server_uses_canonical_extra():
    assert matrix.uv_run_argv("clickhouse-server") == [
        "uv",
        "run",
        "--extra",
        "clickhouse-server",
        "--",
    ]


def test_benchbox_run_argv_includes_platform_extras():
    argv = matrix.benchbox_run_argv("starrocks", "tpch", 0.01)
    assert "--quiet" in argv
    assert "--platform" in argv and "starrocks" in argv
    assert "--platform-option" in argv
    # The starrocks-specific port=19030 must be there.
    assert "port=19030" in argv


def test_benchbox_run_argv_can_omit_quiet_for_diagnostics():
    argv = matrix.benchbox_run_argv("duckdb", "tpch", 0.01, quiet=False)
    assert "--quiet" not in argv
    assert argv[argv.index("--phases") + 1] == "load,power"


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


# ---------------------------------------------------------------------------
# w1 (uat-operator-provisioning): every release-gate platform must resolve
# from the persistent dev venv (`uv sync` dev group) OR have a
# PLATFORM_UV_EXTRA entry -- otherwise a second operator's sweep records
# ModuleNotFoundError cells as FAILED with no doc pointing at the cause.
# No network: probes importlib.util.find_spec on the registry-declared
# driver module. Conservative by construction -- platforms with no
# registry `libraries` entry (native/stdlib platforms with nothing to
# probe) are skipped rather than guessed at.
# ---------------------------------------------------------------------------


def _release_gate_platforms() -> set[str]:
    platforms: set[str] = set()
    for name in _release_gate_config_names():
        cfg = load_config(_RELEASE_GATE_CONFIGS_DIR / name)
        platforms.update(matrix.resolve_platforms(groups=cfg.platforms.groups or ()))
    return platforms


def _registry_driver_module(platform: str) -> str | None:
    """Conservative import-module name for `platform`'s primary required
    driver library, sourced from PlatformRegistry metadata (the same
    `libraries[].import_name`/`name` precedence `_detect_library` uses) --
    not a hand-maintained platform->module table that can drift. Returns
    None when the registry has no required library (nothing to probe)."""
    base = platform[:-3] if platform.endswith("-df") else platform
    meta = PlatformRegistry.get_all_platform_metadata().get(base)
    if not meta:
        return None
    required = [lib for lib in meta.get("libraries", []) if lib.get("required", True)]
    if not required:
        return None
    lib = required[0]
    return lib.get("import_name", lib["name"])


def test_release_gate_platforms_resolve_from_dev_venv_or_have_uv_extra():
    platforms = _release_gate_platforms()
    assert platforms, "release-gate configs resolved to zero platforms; test fixture is broken"

    unresolved = []
    for platform in sorted(platforms):
        if platform in matrix.PLATFORM_UV_EXTRA:
            continue  # `uv run --extra` installs it per cell; dev-venv probe not applicable.
        module = _registry_driver_module(platform)
        if module is None:
            continue  # no registry-declared driver (native/stdlib platform); nothing to probe.
        if importlib.util.find_spec(module) is None:
            unresolved.append((platform, module))

    assert not unresolved, (
        f"platform(s) have no PLATFORM_UV_EXTRA entry and their driver module is not "
        f"importable from the dev venv: {unresolved} -- add a PLATFORM_UV_EXTRA entry "
        f"(tests/uat/matrix.py) or a dev dependency-group requirement (pyproject.toml)"
    )


def test_probe_platform_reachability_never_touches_the_cache():
    """The no-cache probe must neither read nor write `_REACHABILITY_CACHE`.

    Writing would let one caller silently satisfy the next caller's check --
    the defect that made the post-start readiness check disable the
    skip_unreachable check downstream of it. Reading would defeat the
    liveness probe, whose entire job is to notice that a previously
    reachable stack has died.
    """
    matrix._REACHABILITY_CACHE["postgresql"] = True
    with patch.object(matrix, "tcp_probe", return_value=False) as probe:
        assert matrix.probe_platform_reachability("postgresql") is False
    assert probe.called
    # Untouched: the stale True is still there, unread and unmodified.
    assert matrix._REACHABILITY_CACHE == {"postgresql": True}


def test_platform_is_reachable_still_caches():
    with patch.object(matrix, "tcp_probe", return_value=False) as probe:
        assert matrix.platform_is_reachable("postgresql") is False
        assert matrix.platform_is_reachable("postgresql") is False
    assert probe.call_count == 1
