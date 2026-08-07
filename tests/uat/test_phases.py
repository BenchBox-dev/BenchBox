"""Fast-test coverage for tests/uat/phases/*.py (preflight, enumerate, execute)."""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.uat import docker_assets, matrix
from tests.uat.config import ExecuteConfig, UATConfig, validate_config
from tests.uat.conftest import docker_verb as _docker_verb, healthy_ps_stdout, platform_reachability
from tests.uat.docker_path_helpers import compose_path_ends_with
from tests.uat.phases import (
    enumerate as enum_phase,
    execute as exec_phase,
    package as package_phase,
    preflight as preflight_phase,
    report as report_phase,
)
from tests.uat.preflight_budget import (
    MemorySnapshot,
    check_memory_headroom,
    format_memory_headroom_failure,
)
from tests.uat.runner import CellResult, classify_for_submit, submit_state_is_cell_failure

pytestmark = pytest.mark.fast


def _write_submit_result(path: Path, *, failed: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "2.1",
        "run": {
            "id": "uat-test",
            "timestamp": "2026-01-01T00:00:00",
            "total_duration_ms": 1,
            "query_time_ms": 1,
            "iterations": 1,
            "streams": 1,
        },
        "benchmark": {"id": "tpch", "name": "TPC-H", "scale_factor": 0.01, "test_type": "power"},
        "platform": {"name": "DuckDB"},
        "summary": {
            "queries": {"total": 1, "passed": 0 if failed else 1, "failed": failed},
            "validation": {"status": "failed" if failed else "passed"},
        },
        "queries": [{"id": "Q1", "status": "ERROR" if failed else "SUCCESS", "execution_time_ms": 1}],
        "phases": {},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _cfg(payload: dict) -> UATConfig:
    return validate_config({"name": "phase-test", **payload})


# ---------------------------------------------------------------------------
# Preflight.
# ---------------------------------------------------------------------------


def test_preflight_aborts_below_min_free_space(tmp_path):
    with patch.object(preflight_phase, "free_space_gib", return_value=1.0):
        result = preflight_phase.run_preflight(
            free_space_path=tmp_path,
            free_space_min_gib=5.0,
        )
    assert result.aborted is True
    assert "free space" in (result.abort_reason or "")


def test_preflight_warns_on_high_load(tmp_path):
    with (
        patch.object(preflight_phase, "free_space_gib", return_value=100.0),
        patch.object(preflight_phase, "host_load_1m", return_value=20.0),
        patch.object(preflight_phase, "docker_reachable", return_value=True),
    ):
        result = preflight_phase.run_preflight(
            free_space_path=tmp_path,
            noisy_neighbor_warn_load=8.0,
        )
    assert result.aborted is False
    assert any("host load" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Enumerate.
# ---------------------------------------------------------------------------


def test_enumerate_filters_dataframe_against_sql_only():
    raw = {
        "platforms": {"include": ["polars-df"]},
        "benchmarks": {"include": ["vector_search", "tpch"]},
        "scales": {"rungs": [0.01]},
    }
    cells = enum_phase.enumerate_cells(_cfg(raw))
    benches = {c.benchmark for c in cells}
    assert "vector_search" not in benches  # sql-only
    assert "tpch" in benches


def test_enumerate_records_compatibility_pruned_cells():
    raw = {
        "platforms": {"include": ["polars-df"]},
        "benchmarks": {"include": ["vector_search", "tpch"]},
        "scales": {"rungs": [0.01, 0.1]},
    }

    result = enum_phase.enumerate_cells_with_pruning(_cfg(raw))

    assert {c.benchmark for c in result.cells} == {"tpch"}
    assert len(result.compatibility_pruned) == 2
    pruned = result.compatibility_pruned[0]
    assert pruned.platform == "polars-df"
    assert pruned.benchmark == "vector_search"
    assert pruned.rule_id == "uat.compat.dataframe.sql_only_benchmark"
    assert result.candidate_count == len(result.cells) + len(result.compatibility_pruned)


def test_enumerate_uses_registry_supports_dataframe_without_name_fallback():
    raw = {
        "platforms": {"include": ["polars-df"]},
        "benchmarks": {"include": ["vector_search"]},
        "scales": {"rungs": [0.01]},
    }
    benchmarks = {
        "vector_search": matrix.BenchmarkInfo(
            benchmark_id="vector_search",
            category="AI/ML",
            default_scale=0.01,
            min_scale=0.01,
            scale_options=(0.01,),
            supports_dataframe=True,
        )
    }

    result = enum_phase.enumerate_cells_with_pruning(_cfg(raw), benchmarks=benchmarks)

    assert [(c.platform, c.benchmark, c.scale) for c in result.cells] == [("polars-df", "vector_search", 0.01)]
    assert result.compatibility_pruned == ()


def test_enumerate_records_registry_benchmark_gates():
    raw = {
        "platforms": {"include": ["lakesail"]},
        "benchmarks": {"include": ["ai_primitives", "metadata_primitives", "vector_search", "tpch"]},
        "scales": {"rungs": [0.01]},
    }

    result = enum_phase.enumerate_cells_with_pruning(_cfg(raw))

    assert {c.benchmark for c in result.cells} == {"tpch"}
    assert len(result.compatibility_pruned) == 3
    pruned_by_benchmark = {c.benchmark: c for c in result.compatibility_pruned}
    assert pruned_by_benchmark["ai_primitives"].platform == "lakesail"
    assert pruned_by_benchmark["ai_primitives"].rule_id == "uat.compat.lakesail.ai_primitives.benchmark_gate"
    assert pruned_by_benchmark["metadata_primitives"].rule_id == (
        "uat.compat.lakesail.metadata_primitives.benchmark_gate"
    )
    assert pruned_by_benchmark["vector_search"].rule_id == "uat.compat.lakesail.vector_search.benchmark_gate"
    assert pruned_by_benchmark["metadata_primitives"].evidence.startswith("benchbox.sql_compat benchmark_gate")


def test_enumerate_records_datafusion_clickhouse_pruned_benchmark_gates():
    raw = {
        "platforms": {"include": ["datafusion", "clickhouse-local"]},
        "benchmarks": {
            "include": ["write_primitives", "transaction_primitives", "ai_primitives", "vector_search", "tpch"]
        },
        "scales": {"rungs": [0.01]},
    }

    result = enum_phase.enumerate_cells_with_pruning(_cfg(raw))

    assert {(c.platform, c.benchmark) for c in result.cells} == {
        ("clickhouse-local", "vector_search"),
        ("clickhouse-local", "tpch"),
        ("datafusion", "tpch"),
    }
    pruned = {(c.platform, c.benchmark): c for c in result.compatibility_pruned}
    expected_pruned = {
        ("datafusion", "write_primitives"),
        ("datafusion", "transaction_primitives"),
        ("datafusion", "ai_primitives"),
        ("datafusion", "vector_search"),
        ("clickhouse-local", "write_primitives"),
        ("clickhouse-local", "transaction_primitives"),
        ("clickhouse-local", "ai_primitives"),
    }
    assert set(pruned) == expected_pruned
    for platform, benchmark in expected_pruned:
        assert pruned[(platform, benchmark)].rule_id == f"uat.compat.{platform}.{benchmark}.benchmark_gate"
        assert pruned[(platform, benchmark)].status == "blocked"
    assert "DataFusion" in pruned[("datafusion", "transaction_primitives")].reason
    assert "AI primitives" in pruned[("clickhouse-local", "ai_primitives")].reason
    assert result.candidate_count == len(result.cells) + len(result.compatibility_pruned)


def test_enumerate_records_dataframe_pruned_mutation_and_maintenance_gates():
    raw = {
        "platforms": {"include": ["polars-df", "pandas-df", "pyspark-df", "dask-df", "datafusion-df", "modin-df"]},
        "benchmarks": {"include": ["write_primitives", "transaction_primitives", "tpcdi", "tpch"]},
        "scales": {"rungs": [0.01]},
    }

    result = enum_phase.enumerate_cells_with_pruning(_cfg(raw))

    cell_pairs = {(c.platform, c.benchmark) for c in result.cells}
    for platform in ("polars-df", "pandas-df", "pyspark-df"):
        assert (platform, "write_primitives") in cell_pairs
        assert (platform, "tpch") in cell_pairs
    for platform in ("dask-df", "datafusion-df", "modin-df"):
        assert (platform, "write_primitives") not in cell_pairs
        assert (platform, "tpch") in cell_pairs

    pruned = {(c.platform, c.benchmark): c for c in result.compatibility_pruned}
    for platform in matrix.DATAFRAME_PLATFORMS:
        assert pruned[(platform, "transaction_primitives")].rule_id == (
            f"uat.compat.{platform}.transaction_primitives.benchmark_gate"
        )
        assert pruned[(platform, "tpcdi")].rule_id == f"uat.compat.{platform}.tpcdi.benchmark_gate"
        assert "transaction" in pruned[(platform, "tpcdi")].reason.lower()
    for platform in ("dask-df", "datafusion-df", "modin-df"):
        assert pruned[(platform, "write_primitives")].rule_id == (
            f"uat.compat.{platform}.write_primitives.benchmark_gate"
        )
    assert result.candidate_count == len(result.cells) + len(result.compatibility_pruned)


def test_enumerate_keeps_release_gate_runtime_envelopes_for_diagnostic_sweeps():
    raw = {
        "platforms": {"include": ["pg-duckdb", "pg-mooncake", "timescaledb"]},
        "benchmarks": {
            "include": [
                "ai_primitives",
                "datavault",
                "joinorder",
                "read_primitives",
                "tpcds",
                "tpcds_obt",
                "vector_search",
                "tpch",
            ]
        },
        "scales": {"rungs": [0.01]},
    }

    result = enum_phase.enumerate_cells_with_pruning(_cfg(raw))

    cell_pairs = {(c.platform, c.benchmark) for c in result.cells}
    for platform in ("pg-duckdb", "pg-mooncake", "timescaledb"):
        assert (platform, "joinorder") in cell_pairs
        assert (platform, "tpcds_obt") in cell_pairs
    assert ("timescaledb", "datavault") in cell_pairs
    pruned_pairs = {(c.platform, c.benchmark) for c in result.compatibility_pruned}
    assert ("pg-duckdb", "ai_primitives") in pruned_pairs
    assert ("pg-mooncake", "tpcds") in pruned_pairs
    assert all(c.rule_id.endswith(".benchmark_gate") for c in result.compatibility_pruned)


def test_enumerate_records_pg_family_release_gate_compatibility_pruning():
    from benchbox.core.platform_registry import PlatformRegistry

    raw = {
        "platforms": {"include": ["pg-duckdb", "pg-mooncake", "timescaledb"]},
        "benchmarks": {
            "include": [
                "ai_primitives",
                "datavault",
                "joinorder",
                "read_primitives",
                "tpcds",
                "tpcds_obt",
                "vector_search",
                "tpch",
            ]
        },
        "compatibility": {"release_gate_runtime_envelopes": True},
        "scales": {"rungs": [0.01]},
    }

    result = enum_phase.enumerate_cells_with_pruning(_cfg(raw))

    assert {(c.platform, c.benchmark) for c in result.cells} == {
        ("pg-duckdb", "tpch"),
        ("pg-duckdb", "datavault"),
        ("pg-duckdb", "tpcds"),
        ("pg-mooncake", "tpch"),
        ("pg-mooncake", "datavault"),
        ("timescaledb", "tpch"),
        ("timescaledb", "tpcds"),
    }
    assert len(result.compatibility_pruned) == 17
    pruned = {(c.platform, c.benchmark): c for c in result.compatibility_pruned}
    assert pruned[("pg-mooncake", "tpcds")].rule_id == "uat.compat.pg-mooncake.tpcds.benchmark_gate"
    assert pruned[("timescaledb", "datavault")].rule_id == (
        "uat.compat.timescaledb.datavault.release_gate_runtime_envelope"
    )
    for platform in ("pg-duckdb", "pg-mooncake", "timescaledb"):
        caps = PlatformRegistry.get_platform_capabilities(platform)
        assert caps is not None
        assert "joinorder" not in caps.unsupported_benchmarks
        assert "tpcds_obt" not in caps.unsupported_benchmarks
        assert pruned[(platform, "ai_primitives")].rule_id == f"uat.compat.{platform}.ai_primitives.benchmark_gate"
        assert pruned[(platform, "joinorder")].rule_id == (
            f"uat.compat.{platform}.joinorder.release_gate_runtime_envelope"
        )
        assert pruned[(platform, "read_primitives")].rule_id == (
            f"uat.compat.{platform}.read_primitives.benchmark_gate"
        )
        assert pruned[(platform, "tpcds_obt")].rule_id == (
            f"uat.compat.{platform}.tpcds_obt.release_gate_runtime_envelope"
        )
        assert pruned[(platform, "vector_search")].rule_id == f"uat.compat.{platform}.vector_search.benchmark_gate"
    timescaledb_caps = PlatformRegistry.get_platform_capabilities("timescaledb")
    assert timescaledb_caps is not None
    assert "datavault" not in timescaledb_caps.unsupported_benchmarks


def test_enumerate_preserves_explicit_empty_include_as_default_suppression():
    no_platforms = enum_phase.enumerate_cells(
        _cfg(
            {
                "platforms": {"include": []},
                "benchmarks": {"include": ["tpch"]},
                "scales": {"rungs": [0.01]},
            }
        )
    )
    no_benchmarks = enum_phase.enumerate_cells(
        _cfg(
            {
                "platforms": {"include": ["duckdb"]},
                "benchmarks": {"include": []},
                "scales": {"rungs": [0.01]},
            }
        )
    )

    assert no_platforms == []
    assert no_benchmarks == []


def test_enumerate_honours_scale_options():
    raw = {
        "platforms": {"include": ["duckdb"]},
        "benchmarks": {"include": ["tpch"]},
        "scales": {"rungs": [0.01, 0.1, 1.0, 50.0, 100.0]},
    }
    cells = enum_phase.enumerate_cells(_cfg(raw))
    scales = {c.scale for c in cells}
    # tpch scale_options = development subscales + official TPC ladder
    # (PR #332 review follow-up): 0.01, 0.1, 1.0, 10.0, 30.0, 100.0, 300.0…
    # so 100.0 stays, but non-canonical 50.0 is dropped.
    assert 50.0 not in scales
    assert {0.01, 0.1, 1.0, 100.0}.issubset(scales)


def test_enumerate_override_replaces_rungs():
    """`scales.override` wins over `scales.rungs` at enumerate time.

    YAML configs can no longer express both fields at once (w1:
    `scales.rungs`/`scales.override` are validated mutually exclusive at
    load time, uat-config-schema-spec-realignment) -- but the stress-override
    runtime path (`tests/uat/orchestrator.py`'s `SCALE=` handling) legitimately
    builds a config with both set via `dataclasses.replace`, bypassing YAML
    validation entirely. This exercises that same precedence at the enumerate
    layer without going through `validate_config`.
    """
    from dataclasses import replace

    raw = {
        "platforms": {"include": ["duckdb"]},
        "benchmarks": {"include": ["tpch"]},
        "scales": {"rungs": [0.01, 0.1, 1.0]},
    }
    cfg = _cfg(raw)
    cfg = replace(cfg, scales=replace(cfg.scales, override=0.1))
    cells = enum_phase.enumerate_cells(cfg)
    assert {c.scale for c in cells} == {0.1}


# ---------------------------------------------------------------------------
# Execute.
# ---------------------------------------------------------------------------


def _stub_runner_factory(elapsed_map: dict[float, float], pass_map: dict[float, bool]):
    """Build a stand-in for runner.run_cell that drives the ladder logic."""

    def fake_runner(platform, benchmark, scale, **kwargs):
        return CellResult(
            platform=platform,
            benchmark=benchmark,
            scale=scale,
            status="passed" if pass_map.get(scale, True) else "failed",
            exit_code=0 if pass_map.get(scale, True) else 1,
            elapsed_s=elapsed_map.get(scale, 1.0),
            log_path=Path("/tmp/uat-test.log"),
            result_path=None,
        )

    return fake_runner


def test_execute_walks_ladder_and_prunes_after_slow_rung(tmp_path):
    cfg = validate_config(
        {
            "name": "fake",
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01, 0.1, 1.0]},
            "execute": {"early_stop_after_s": 5},
        }
    )
    runner = _stub_runner_factory(
        elapsed_map={0.01: 1.0, 0.1: 100.0, 1.0: 1.0},
        pass_map={0.01: True, 0.1: True, 1.0: True},
    )
    outcome = exec_phase.run_execute(
        cfg,
        log_dir=tmp_path,
        databases_root=tmp_path / "databases",
        runner=runner,
    )
    scales_run = {r.scale for r in outcome.results}
    pruned_scales = {c.scale for c in outcome.pruned}
    assert scales_run == {0.01, 0.1}
    assert 1.0 in pruned_scales


def test_execute_asserts_if_parallel_platforms_bypasses_yaml_validation(tmp_path):
    cfg = UATConfig(name="parallel-bypass", execute=ExecuteConfig(parallel_platforms=True))

    with pytest.raises(AssertionError, match="parallel_platforms must remain False"):
        exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=_stub_runner_factory({}, {}),
        )


def test_execute_skips_unreachable_platform(tmp_path):
    cfg = validate_config(
        {
            "name": "fake",
            "platforms": {"include": ["postgresql"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )
    with platform_reachability(False):
        runner = _stub_runner_factory({}, {})
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=runner,
        )
    assert len(outcome.results) == 0
    assert len(outcome.skipped_unreachable) == 1
    # w2 regression: `all(...)` over an empty `results` tuple is vacuously
    # True, so an all-unreachable sweep (zero cells run) must not exit 0.
    assert outcome.exit_code() == 1


def _docker_platform_from_argv(argv: list[str]) -> str:
    compose_file = argv[argv.index("-f") + 1]
    if compose_path_ends_with(compose_file, "docker", "clickhouse", "docker-compose.yml"):
        return "clickhouse-server"
    if compose_path_ends_with(compose_file, "docker", "postgresql", "docker-compose.yml"):
        return "postgresql"
    if "pg-duckdb" in compose_file:
        return "pg-duckdb"
    return compose_file


def _healthy_ps_result(argv: list[str]) -> docker_assets.DockerCommandResult:
    """A `compose ps -a` result whose single service is Up -- readiness passes."""
    return docker_assets.DockerCommandResult(tuple(argv), 0, healthy_ps_stdout(), "")


def test_execute_managed_docker_tears_down_platform_before_next_starts(tmp_path):
    cfg = validate_config(
        {
            "name": "docker smoke",
            "platforms": {"include": ["clickhouse-server", "postgresql"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )
    sequence: list[tuple[str, str, str]] = []

    def fake_docker(argv, **kwargs):
        action = _docker_verb(argv)
        sequence.append(("docker", action, _docker_platform_from_argv(argv)))
        if action == "ps":
            return _healthy_ps_result(argv)
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    def recording_runner(platform, benchmark, scale, **kwargs):
        sequence.append(("cell", "run", platform))
        return CellResult(
            platform=platform,
            benchmark=benchmark,
            scale=scale,
            status="passed",
            exit_code=0,
            elapsed_s=1.0,
            log_path=tmp_path / f"{platform}.log",
            result_path=None,
        )

    with platform_reachability(True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=recording_runner,
            docker_runner=fake_docker,
            free_space_checks_enabled=True,
            free_space_reader=lambda _path: 100.0,
            sleep_fn=lambda _s: None,
        )

    assert outcome.aborted is False
    assert sequence == [
        ("docker", "up", "clickhouse-server"),
        ("docker", "ps", "clickhouse-server"),
        ("cell", "run", "clickhouse-server"),
        ("docker", "down", "clickhouse-server"),
        ("docker", "up", "postgresql"),
        ("docker", "ps", "postgresql"),
        ("cell", "run", "postgresql"),
        ("docker", "down", "postgresql"),
    ]
    assert any(event.action == "down" and event.status == "ok" for event in outcome.docker_events)
    down_commands = [event.result.argv for event in outcome.docker_events if event.action == "down" and event.result]
    assert all("-v" in argv and "--remove-orphans" in argv for argv in down_commands)


def test_execute_teardown_sweeps_leaked_mocker_volumes_when_resolved_engine_is_mocker(tmp_path, monkeypatch):
    """uat-container-engine-routing w3: mocker's `compose down -v` leaks named
    volumes; teardown must sweep them project-scoped when volumes/images mode
    requested `-v` and the resolved engine is mocker."""
    monkeypatch.setenv(docker_assets.CONTAINER_CLI_ENV_VAR, "mocker")
    monkeypatch.setattr(docker_assets, "_which_container_cli", lambda cli: f"/opt/homebrew/bin/{cli}")
    docker_assets.resolve_container_cli.cache_clear()
    try:
        cfg = validate_config(
            {
                "name": "mocker volume sweep",
                "platforms": {"include": ["postgresql"]},
                "benchmarks": {"include": ["tpch"]},
                "scales": {"rungs": [0.01]},
                "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
            }
        )
        volume_calls: list[tuple[str, ...]] = []

        # Exact leaked name mocker 0.5.4 creates for this project: the
        # postgresql spec declares volume key `postgresql18-data`, and
        # mocker joins <project>-<key> with a hyphen (live-verified).
        leaked_volume = "benchbox-uat-mocker-volume-sweep-postgresql-postgresql18-data"

        def fake_docker(argv, **kwargs):
            argv_tuple = tuple(argv)
            if argv_tuple == ("mocker", "volume", "ls"):
                volume_calls.append(argv_tuple)
                return docker_assets.DockerCommandResult(argv_tuple, 0, f"local    {leaked_volume}\n", "")
            if argv_tuple[:3] == ("mocker", "volume", "rm"):
                volume_calls.append(argv_tuple)
                return docker_assets.DockerCommandResult(argv_tuple, 0, "", "")
            return docker_assets.DockerCommandResult(argv_tuple, 0, "", "")

        def recording_runner(platform, benchmark, scale, **kwargs):
            return CellResult(
                platform=platform,
                benchmark=benchmark,
                scale=scale,
                status="passed",
                exit_code=0,
                elapsed_s=1.0,
                log_path=tmp_path / f"{platform}.log",
                result_path=None,
            )

        with platform_reachability(True):
            outcome = exec_phase.run_execute(
                cfg,
                log_dir=tmp_path,
                databases_root=tmp_path / "databases",
                runner=recording_runner,
                docker_runner=fake_docker,
                sleep_fn=lambda _s: None,
            )

        assert outcome.aborted is False
        sweep_events = [e for e in outcome.docker_events if e.action == "volume-sweep"]
        assert len(sweep_events) == 1
        assert sweep_events[0].status == "ok"
        assert leaked_volume in sweep_events[0].message
        assert ("mocker", "volume", "ls") in volume_calls
        assert ("mocker", "volume", "rm", leaked_volume) in volume_calls
    finally:
        docker_assets.resolve_container_cli.cache_clear()


def test_execute_teardown_skips_mocker_volume_sweep_for_containers_mode(tmp_path, monkeypatch):
    """The sweep only runs when `-v` was requested (volumes/images mode) --
    `containers` mode intentionally keeps volumes for platform-reuse, and the
    sweep must not defeat that."""
    monkeypatch.setenv(docker_assets.CONTAINER_CLI_ENV_VAR, "mocker")
    monkeypatch.setattr(docker_assets, "_which_container_cli", lambda cli: f"/opt/homebrew/bin/{cli}")
    docker_assets.resolve_container_cli.cache_clear()
    try:
        cfg = validate_config(
            {
                "name": "mocker containers mode",
                "platforms": {"include": ["postgresql"]},
                "benchmarks": {"include": ["tpch"]},
                "scales": {"rungs": [0.01]},
                "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "containers"},
            }
        )
        calls: list[tuple[str, ...]] = []

        def fake_docker(argv, **kwargs):
            calls.append(tuple(argv))
            return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

        def recording_runner(platform, benchmark, scale, **kwargs):
            return CellResult(
                platform=platform,
                benchmark=benchmark,
                scale=scale,
                status="passed",
                exit_code=0,
                elapsed_s=1.0,
                log_path=tmp_path / f"{platform}.log",
                result_path=None,
            )

        with platform_reachability(True):
            outcome = exec_phase.run_execute(
                cfg,
                log_dir=tmp_path,
                databases_root=tmp_path / "databases",
                runner=recording_runner,
                docker_runner=fake_docker,
                sleep_fn=lambda _s: None,
            )

        assert not any(e.action == "volume-sweep" for e in outcome.docker_events)
        assert not any(c[:2] == ("mocker", "volume") for c in calls)
    finally:
        docker_assets.resolve_container_cli.cache_clear()


def test_execute_docker_teardown_failure_aborts_before_next_platform(tmp_path):
    cfg = validate_config(
        {
            "name": "docker cleanup failure",
            "platforms": {"include": ["clickhouse-server", "postgresql"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )
    commands: list[str] = []

    def fake_docker(argv, **kwargs):
        action = _docker_verb(argv)
        commands.append(f"{action}:{_docker_platform_from_argv(argv)}")
        if action == "down":
            return docker_assets.DockerCommandResult(tuple(argv), 1, "", "compose down failed")
        if action == "ps":
            return _healthy_ps_result(argv)
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    with platform_reachability(True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=_stub_runner_factory({0.01: 1.0}, {0.01: True}),
            docker_runner=fake_docker,
            free_space_reader=lambda _path: 100.0,
            sleep_fn=lambda _s: None,
        )

    assert outcome.aborted is True
    assert "Docker cleanup failed" in (outcome.abort_reason or "")
    assert commands == ["up:clickhouse-server", "ps:clickhouse-server", "down:clickhouse-server"]


def test_execute_aborts_before_compose_up_when_benchmark_runs_dir_is_relative_for_path_mirroring_platform(tmp_path):
    """must_preserve: compose_environment() (tests/uat/docker_assets.py) is
    the enforcement point every UAT-managed bring-up path funnels through --
    not just `make test-docker-up-*`, which the Makefile's
    require_data_dir_if_mounted guards separately and does not cover this
    path at all. A relative benchmark_runs_dir for a path-mirroring platform
    (lakesail, velox) is a pre-flight config problem identical in kind to
    validate_managed_start_allowed's failures -- it would break EVERY cell
    on the platform identically, not one query -- so it must abort the
    sweep before compose is ever invoked, not silently mount an
    empty/garbage path (`mocker compose config -q` exits 0 on that)."""
    cfg = validate_config(
        {
            "name": "docker relative data dir",
            "platforms": {"include": ["lakesail"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )
    calls: list[str] = []

    def fake_docker(argv, **kwargs):
        calls.append("up" if "up" in argv else "down")
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    outcome = exec_phase.run_execute(
        cfg,
        log_dir=tmp_path,
        databases_root=tmp_path / "databases",
        benchmark_runs_dir=Path("relative_runs"),
        runner=_stub_runner_factory({0.01: 1.0}, {0.01: True}),
        docker_runner=fake_docker,
        free_space_reader=lambda _path: 100.0,
    )

    assert outcome.aborted is True
    assert "BENCHBOX_DATA_DIR" in (outcome.abort_reason or "")
    assert "absolute" in (outcome.abort_reason or "")
    # compose is never invoked at all -- the config error is caught before `up`.
    assert calls == []


def test_run_docker_teardown_substitutes_absolute_placeholder_when_benchmark_runs_dir_is_relative():
    """Down must never fail (or raise out of run_execute's `finally`) just
    because BENCHBOX_DATA_DIR is unset or relative -- `down` never mounts
    anything, so any absolute value lets compose parse the file.

    Direct unit test of _run_docker_teardown rather than through
    run_execute's public API: within one run_execute call, up and down for a
    single platform always share the SAME benchmark_runs_dir value, so if up
    already succeeded (compose_environment did not raise), down's identical
    call cannot raise either -- the defensive substitution in
    _run_docker_teardown is unreachable end-to-end through run_execute as
    currently wired. It exists as defence-in-depth against a future
    caller/refactor that decouples the two values, mirroring the Makefile's
    compose_down_fresh placeholder for `make test-docker-down-*` (same
    reasoning, same fix, different layer)."""
    cfg = validate_config(
        {
            "name": "docker teardown relative data dir",
            "platforms": {"include": ["lakesail"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )
    spec = docker_assets.docker_platform_spec("lakesail")
    docker_state = exec_phase._DockerPlatformState(
        spec=spec, project_name="benchbox-uat-test-lakesail", started=True, cleanup_status="started"
    )
    captured_env: dict[str, str] = {}

    def fake_docker(argv, **kwargs):
        captured_env.update(kwargs.get("env") or {})
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    cleanup_status, abort_reason = exec_phase._run_docker_teardown(
        cfg,
        platform="lakesail",
        docker_state=docker_state,
        benchmark_runs_dir=Path("relative_runs"),
        docker_runner=fake_docker,
        docker_events=[],
        log_dir=None,
    )

    assert cleanup_status == "ok"
    assert abort_reason is None
    assert "BENCHBOX_DATA_DIR" in captured_env
    assert Path(captured_env["BENCHBOX_DATA_DIR"]).is_absolute()


def test_execute_docker_startup_failure_records_and_advances_to_next_platform(tmp_path):
    """A managed compose-up failure must not truncate the sweep.

    Regression for uat-docker-stack-recovery: the 2026-05-28 non-OLTP run ended
    after the LakeSail compose-up timed out, so no other stack ran. A failed
    `up` should record the platform's cells (the failure is captured in
    docker_events / uat_lifecycle.log) and advance to the next stack, one stack
    at a time. Only genuine global aborts (free space, teardown failure, fixed
    container-name policy) may stop the sweep.
    """
    cfg = validate_config(
        {
            "name": "docker startup failure",
            "platforms": {"include": ["clickhouse-server", "postgresql"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )
    sequence: list[tuple[str, str, str]] = []

    def fake_docker(argv, **kwargs):
        action = _docker_verb(argv)
        platform = _docker_platform_from_argv(argv)
        sequence.append(("docker", action, platform))
        # clickhouse-server compose-up fails (e.g. start timeout); others succeed.
        if action == "up" and platform == "clickhouse-server":
            return docker_assets.DockerCommandResult(
                tuple(argv), 1, "", "docker command timed out after 300s", timed_out=True
            )
        if action == "ps":
            return _healthy_ps_result(argv)
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    def recording_runner(platform, benchmark, scale, **kwargs):
        sequence.append(("cell", "run", platform))
        return CellResult(
            platform=platform,
            benchmark=benchmark,
            scale=scale,
            status="passed",
            exit_code=0,
            elapsed_s=1.0,
            log_path=tmp_path / f"{platform}.log",
            result_path=None,
        )

    with platform_reachability(True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=recording_runner,
            docker_runner=fake_docker,
            free_space_checks_enabled=True,
            free_space_reader=lambda _path: 100.0,
            sleep_fn=lambda _s: None,
        )

    # The sweep is NOT aborted by one stack's startup failure.
    assert outcome.aborted is False
    # The failed stack ran no cells but was still torn down; the next stack ran.
    assert sequence == [
        ("docker", "up", "clickhouse-server"),
        ("docker", "down", "clickhouse-server"),
        ("docker", "up", "postgresql"),
        ("docker", "ps", "postgresql"),
        ("cell", "run", "postgresql"),
        ("docker", "down", "postgresql"),
    ]
    # The failed platform's cells are recorded as startup_failed (not
    # skipped_unreachable -- uat-fail-advance-consistency w3 splits the two
    # so accounting can tell "stack failed to start" from "TCP probe found
    # nothing listening"), not silently dropped, and the compose-up failure
    # is captured in the lifecycle events.
    assert any(cell.platform == "clickhouse-server" for cell in outcome.startup_failed)
    assert len(outcome.skipped_unreachable) == 0
    assert any(
        event.platform == "clickhouse-server" and event.action == "up" and event.status == "failed"
        for event in outcome.docker_events
    )


def test_execute_readiness_settle_reprobes_compose_ps_after_up_wait_reports_success(tmp_path):
    """uat-container-readiness-and-memory-headroom-gate w0/w1 (RED-NOW rung 2).

    Regression for the 2026-08-04 CedarDB incident: `up --wait` exited 0,
    but `compose ps` showed the container Exited ~29s later, and UAT ran
    171 cells against the dead stack -- all recorded as CELL failures
    instead of a startup failure. `up --wait` succeeding must not be
    trusted on its own: a settle window plus a `compose ps` re-check must
    run first, and a service that has already Exited by then must route
    into the existing startup_failed path (advance, don't run cells,
    don't abort the sweep) instead of being counted as 171 cell failures.
    """
    cfg = validate_config(
        {
            "name": "readiness settle",
            "platforms": {"include": ["clickhouse-server", "postgresql"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )
    sequence: list[tuple[str, str, str]] = []
    sleep_calls: list[float] = []

    def fake_docker(argv, **kwargs):
        action = _docker_verb(argv)
        platform = _docker_platform_from_argv(argv)
        sequence.append(("docker", action, platform))
        if action == "ps" and platform == "clickhouse-server":
            # `mocker compose ps` output shape (live-observed 2026-08-04):
            # the service reported started by `up --wait` has since exited.
            return docker_assets.DockerCommandResult(
                tuple(argv),
                0,
                "NAME                STATUS\nclickhouse-server   Exited (137) 5 seconds ago\n",
                "",
            )
        if action == "ps":
            return _healthy_ps_result(argv)
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    def recording_runner(platform, benchmark, scale, **kwargs):
        sequence.append(("cell", "run", platform))
        return CellResult(
            platform=platform,
            benchmark=benchmark,
            scale=scale,
            status="passed",
            exit_code=0,
            elapsed_s=1.0,
            log_path=tmp_path / f"{platform}.log",
            result_path=None,
        )

    with platform_reachability(True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=recording_runner,
            docker_runner=fake_docker,
            sleep_fn=sleep_calls.append,
        )

    # The dead stack's cells are NOT run and NOT counted as cell failures --
    # exactly the miscount the 2026-08-04 incident produced.
    assert not any(entry[:2] == ("cell", "run") and entry[2] == "clickhouse-server" for entry in sequence)
    assert any(cell.platform == "clickhouse-server" for cell in outcome.startup_failed)
    assert not any(r.platform == "clickhouse-server" for r in outcome.results)
    # The settle window ran (the default docker_settle_s=10) before the
    # re-check, once per managed Docker platform (clickhouse-server, then
    # postgresql).
    assert sleep_calls == [10, 10]
    # The sweep still advances to the next stack -- one dead stack does not
    # abort the whole sweep (uat-docker-stack-recovery w2, preserved here).
    assert outcome.aborted is False
    assert any(r.platform == "postgresql" and r.status == "passed" for r in outcome.results)
    assert any(
        event.platform == "clickhouse-server" and event.action == "readiness" and event.status == "failed"
        for event in outcome.docker_events
    )
    readiness_event = next(e for e in outcome.docker_events if e.action == "readiness")
    assert "clickhouse-server" in readiness_event.message
    assert "not ready" in readiness_event.message


def test_execute_readiness_check_fails_when_platform_unreachable_after_settle(tmp_path):
    """`compose ps` can look healthy while nothing is actually listening yet
    (or ever) -- the readiness check must also re-probe reachability, reusing
    the same primitive `_run_or_skip_platform`'s skip_unreachable check uses
    (see uat-container-readiness-and-memory-headroom-gate w0 prior_art)."""
    cfg = validate_config(
        {
            "name": "readiness unreachable",
            "platforms": {"include": ["clickhouse-server"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )

    def fake_docker(argv, **kwargs):
        action = _docker_verb(argv)
        if action == "ps":
            return _healthy_ps_result(argv)
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    def fail_runner(platform, benchmark, scale, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("no cell should run against an unreachable stack")

    with platform_reachability(False):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=fail_runner,
            docker_runner=fake_docker,
            sleep_fn=lambda _s: None,
        )

    assert outcome.aborted is False
    assert len(outcome.results) == 0
    assert any(cell.platform == "clickhouse-server" for cell in outcome.startup_failed)
    readiness_event = next(e for e in outcome.docker_events if e.action == "readiness")
    assert readiness_event.status == "failed"
    assert "reachability probe" in readiness_event.message


def test_execute_readiness_settle_uses_configured_docker_settle_s(tmp_path):
    cfg = validate_config(
        {
            "name": "custom settle",
            "platforms": {"include": ["clickhouse-server"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "cleanup": {
                "docker_manage_platforms": True,
                "docker_platform_switch": "volumes",
                "docker_settle_s": 3,
            },
        }
    )
    sleep_calls: list[float] = []

    def fake_docker(argv, **kwargs):
        action = _docker_verb(argv)
        if action == "ps":
            return _healthy_ps_result(argv)
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    with platform_reachability(True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=_stub_runner_factory({0.01: 1.0}, {0.01: True}),
            docker_runner=fake_docker,
            sleep_fn=sleep_calls.append,
        )

    assert outcome.aborted is False
    assert sleep_calls == [3]


def test_execute_readiness_check_skipped_for_dry_run(tmp_path):
    """A dry run never actually starts a container -- there is nothing to
    settle or probe, and the readiness check must not fabricate a settle
    delay or a real reachability probe against it."""
    cfg = validate_config(
        {
            "name": "dry run readiness",
            "dry_run": True,
            "platforms": {"include": ["clickhouse-server"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )
    sleep_calls: list[float] = []

    def fake_docker(argv, **kwargs):  # pragma: no cover - dry_run short-circuits before any real call
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "", dry_run=True)

    with platform_reachability(True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=_stub_runner_factory({0.01: 1.0}, {0.01: True}),
            docker_runner=fake_docker,
            sleep_fn=sleep_calls.append,
        )

    assert outcome.aborted is False
    assert sleep_calls == []
    assert not any(event.action in {"ps", "readiness"} for event in outcome.docker_events)


def _memory_reader(free_gib, swap_used_percent=0.0):
    """A `memory_reader` for run_execute that returns a fixed host reading."""
    return lambda: MemorySnapshot(free_gib=free_gib, swap_used_percent=swap_used_percent)


def _managed_docker_cfg(name, **overrides):
    payload = {
        "name": name,
        "platforms": {"include": ["clickhouse-server"]},
        "benchmarks": {"include": ["tpch"]},
        "scales": {"rungs": [0.01]},
        "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
    }
    for section, values in overrides.items():
        payload.setdefault(section, {}).update(values)
    return validate_config(payload)


def _healthy_fake_docker(argv, **kwargs):
    if _docker_verb(argv) == "ps":
        return _healthy_ps_result(argv)
    return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")


def test_execute_memory_floor_aborts_the_platform_before_starting_it(tmp_path):
    """End-to-end: a host below the free-memory floor aborts the sweep at the
    platform boundary, with abort_kind="memory_floor".

    The gate had zero end-to-end coverage: inserting `return None` as the
    first statement of `_free_memory_abort_reason` (making the gate
    incapable of ever aborting) left the whole suite green. This test, and
    the three below, are what make that mutation fail.
    """
    cfg = _managed_docker_cfg("memory floor abort")
    started: list[str] = []

    def fake_docker(argv, **kwargs):  # pragma: no cover - gate fires before any compose call
        started.append(_docker_verb(argv))
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    def fail_runner(platform, benchmark, scale, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("no cell may run once the memory floor has aborted")

    outcome = exec_phase.run_execute(
        cfg,
        log_dir=tmp_path,
        databases_root=tmp_path / "databases",
        runner=fail_runner,
        docker_runner=fake_docker,
        memory_reader=_memory_reader(0.07, swap_used_percent=88.0),
        sleep_fn=lambda _s: None,
    )

    assert outcome.aborted is True
    assert outcome.abort_kind == "memory_floor"
    assert outcome.results == ()
    # The abort happens BEFORE the stack is started: the whole point is to
    # not ask a starved host for another container VM.
    assert "up" not in started


def test_execute_memory_floor_abort_reason_carries_the_shipped_failure_message(tmp_path):
    """The abort reason is the message `format_memory_headroom_failure`
    renders, plus this call site's context -- not a second, divergent
    open-coded string (see preflight_budget.format_memory_headroom_failure)."""
    cfg = _managed_docker_cfg("memory floor message")

    outcome = exec_phase.run_execute(
        cfg,
        log_dir=tmp_path,
        databases_root=tmp_path / "databases",
        runner=_stub_runner_factory({0.01: 1.0}, {0.01: True}),
        docker_runner=_healthy_fake_docker,
        memory_reader=_memory_reader(0.07, swap_used_percent=88.0),
        sleep_fn=lambda _s: None,
    )

    reason = outcome.abort_reason
    assert reason is not None
    expected_core = format_memory_headroom_failure(
        check_memory_headroom(MemorySnapshot(free_gib=0.07, swap_used_percent=88.0), min_free_gib=2.0)
    )
    assert reason.startswith(expected_core)
    assert "before starting platform clickhouse-server" in reason
    assert "engine=docker" in reason
    # Single source of truth: the swap note comes from the shared formatter
    # and must not be appended a second time by the call site.
    assert reason.count("swap 88.0% used") == 1
    # And the same reading is on the lifecycle log for the operator.
    lifecycle = (tmp_path / "uat_lifecycle.log").read_text(encoding="utf-8")
    assert "[free-memory]" in lifecycle
    assert "0.07 GiB free" in lifecycle


def test_execute_memory_floor_passes_when_host_has_headroom(tmp_path):
    cfg = _managed_docker_cfg("memory floor ok")

    with platform_reachability(True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=_stub_runner_factory({0.01: 1.0}, {0.01: True}),
            docker_runner=_healthy_fake_docker,
            memory_reader=_memory_reader(8.0),
            sleep_fn=lambda _s: None,
        )

    assert outcome.aborted is False
    assert outcome.abort_kind is None
    assert any(r.platform == "clickhouse-server" and r.status == "passed" for r in outcome.results)


def test_execute_memory_floor_disabled_by_zero_never_aborts(tmp_path):
    """0-disables convention: `free_memory_min_gib: 0` turns the gate off even
    on a host with essentially no free memory."""
    cfg = _managed_docker_cfg("memory floor off", preflight={"free_memory_min_gib": 0})

    with platform_reachability(True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=_stub_runner_factory({0.01: 1.0}, {0.01: True}),
            docker_runner=_healthy_fake_docker,
            memory_reader=_memory_reader(0.01),
            sleep_fn=lambda _s: None,
        )

    assert outcome.aborted is False
    assert any(r.status == "passed" for r in outcome.results)
    # Gate off means no reading is logged either -- nothing was measured.
    lifecycle_path = tmp_path / "uat_lifecycle.log"
    lifecycle = lifecycle_path.read_text(encoding="utf-8") if lifecycle_path.exists() else ""
    assert "[free-memory]" not in lifecycle


def test_execute_memory_floor_unmeasurable_host_does_not_gate(tmp_path):
    """A host where free memory cannot be read must neither abort nor pass
    silently: it logs "could not be measured" and lets the sweep proceed."""
    cfg = _managed_docker_cfg("memory unmeasurable")

    with platform_reachability(True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=_stub_runner_factory({0.01: 1.0}, {0.01: True}),
            docker_runner=_healthy_fake_docker,
            memory_reader=_memory_reader(None, swap_used_percent=None),
            sleep_fn=lambda _s: None,
        )

    assert outcome.aborted is False
    lifecycle = (tmp_path / "uat_lifecycle.log").read_text(encoding="utf-8")
    assert "could not be measured" in lifecycle


def test_execute_memory_floor_ignores_non_docker_platforms(tmp_path):
    """The gate exists to protect a container VM start. A native platform
    asks the host for no VM, so a low reading must not abort it."""
    cfg = validate_config(
        {
            "name": "memory native",
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )

    with platform_reachability(True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=_stub_runner_factory({0.01: 1.0}, {0.01: True}),
            docker_runner=_healthy_fake_docker,
            memory_reader=_memory_reader(0.01),
            sleep_fn=lambda _s: None,
        )

    assert outcome.aborted is False
    assert any(r.platform == "duckdb" and r.status == "passed" for r in outcome.results)


def test_execute_disk_floor_takes_precedence_over_memory_floor(tmp_path):
    """Both gates short at the same boundary; disk wins, matching the
    disk-before-docker_required precedence in run_preflight."""
    cfg = _managed_docker_cfg("both floors")

    outcome = exec_phase.run_execute(
        cfg,
        log_dir=tmp_path,
        databases_root=tmp_path / "databases",
        runner=_stub_runner_factory({0.01: 1.0}, {0.01: True}),
        docker_runner=_healthy_fake_docker,
        free_space_checks_enabled=True,
        free_space_path=tmp_path,
        free_space_min_gib=100.0,
        free_space_reader=lambda _p: 1.0,
        memory_reader=_memory_reader(0.01),
        sleep_fn=lambda _s: None,
    )

    assert outcome.aborted is True
    assert outcome.abort_kind == "disk_floor"
    assert "free space" in (outcome.abort_reason or "")


def test_execute_teardown_failure_after_startup_failure_advances_instead_of_aborting(tmp_path):
    """w4: teardown failing on a stack whose OWN startup already failed must not defeat #700's advance.

    Regression for uat-fail-advance-consistency w4: `started=True` is set
    unconditionally after a compose-up so the finally-teardown still runs on
    a broken stack (it can still leak containers/volumes); before this fix,
    a teardown failure on that same broken stack was treated exactly like a
    healthy-stack teardown failure and turned into a GLOBAL abort, defeating
    the #700 advance-past-broken-stack intent. Policy: only a stack that
    started successfully makes an undoable teardown failure a resource-leak
    emergency worth a global abort.
    """
    cfg = validate_config(
        {
            "name": "docker startup and teardown both fail",
            "platforms": {"include": ["clickhouse-server", "postgresql"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )
    sequence: list[tuple[str, str, str]] = []

    def fake_docker(argv, **kwargs):
        action = _docker_verb(argv)
        platform = _docker_platform_from_argv(argv)
        sequence.append(("docker", action, platform))
        # clickhouse-server's compose-up fails AND its teardown also fails.
        if platform == "clickhouse-server":
            return docker_assets.DockerCommandResult(tuple(argv), 1, "", f"{action} failed")
        if action == "ps":
            return _healthy_ps_result(argv)
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    def recording_runner(platform, benchmark, scale, **kwargs):
        sequence.append(("cell", "run", platform))
        return CellResult(
            platform=platform,
            benchmark=benchmark,
            scale=scale,
            status="passed",
            exit_code=0,
            elapsed_s=1.0,
            log_path=tmp_path / f"{platform}.log",
            result_path=None,
        )

    with platform_reachability(True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=recording_runner,
            docker_runner=fake_docker,
            free_space_checks_enabled=True,
            free_space_reader=lambda _path: 100.0,
            sleep_fn=lambda _s: None,
        )

    # The sweep advances past the broken stack instead of a global abort.
    assert outcome.aborted is False
    assert outcome.abort_reason is None
    assert sequence == [
        ("docker", "up", "clickhouse-server"),
        ("docker", "down", "clickhouse-server"),
        ("docker", "up", "postgresql"),
        ("docker", "ps", "postgresql"),
        ("cell", "run", "postgresql"),
        ("docker", "down", "postgresql"),
    ]
    assert any(cell.platform == "clickhouse-server" for cell in outcome.startup_failed)
    # Both the raw teardown failure and the FAIL-and-advance policy decision
    # are recorded as lifecycle events for auditability.
    assert any(
        event.platform == "clickhouse-server" and event.action == "down" and event.status == "failed"
        for event in outcome.docker_events
    )
    assert any(
        event.platform == "clickhouse-server"
        and event.action == "down-policy"
        and event.status == "advance-after-startup-failed"
        for event in outcome.docker_events
    )


def test_execute_healthy_stack_teardown_failure_still_aborts_after_startup_failed_regression_guard(tmp_path):
    """w4 must_preserve: a HEALTHY stack's teardown failure still aborts globally.

    Companion to test_execute_docker_teardown_failure_aborts_before_next_platform:
    that test already pins this behavior, but is duplicated here explicitly
    alongside the new startup-failed-teardown-advances test so the two
    directions of the w4 policy are visible side by side.
    """
    cfg = validate_config(
        {
            "name": "healthy stack teardown failure",
            "platforms": {"include": ["clickhouse-server", "postgresql"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )

    def fake_docker(argv, **kwargs):
        action = _docker_verb(argv)
        if action == "down":
            return docker_assets.DockerCommandResult(tuple(argv), 1, "", "compose down failed")
        if action == "ps":
            return _healthy_ps_result(argv)
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    with platform_reachability(True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=_stub_runner_factory({0.01: 1.0}, {0.01: True}),
            docker_runner=fake_docker,
            free_space_reader=lambda _path: 100.0,
            sleep_fn=lambda _s: None,
        )

    assert outcome.aborted is True
    assert "Docker cleanup failed" in (outcome.abort_reason or "")
    assert len(outcome.startup_failed) == 0


def test_execute_outcome_exit_code_nonzero_when_every_compose_up_fails(tmp_path):
    """w2 regression: every managed compose-up failing means zero cells run.

    A single-platform sweep whose only compose-up fails ends with an empty
    `results` tuple, same as the all-unreachable case -- `all([])` must not
    read as a clean sweep here either.
    """
    cfg = validate_config(
        {
            "name": "docker all compose-up failed",
            "platforms": {"include": ["clickhouse-server"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )

    def fake_docker(argv, **kwargs):
        action = _docker_verb(argv)
        if action == "up":
            return docker_assets.DockerCommandResult(
                tuple(argv), 1, "", "docker command timed out after 300s", timed_out=True
            )
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    def fail_runner(platform, benchmark, scale, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("no cell should run when the only compose-up failed")

    with platform_reachability(True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=fail_runner,
            docker_runner=fake_docker,
            free_space_checks_enabled=True,
            free_space_reader=lambda _path: 100.0,
        )

    assert outcome.aborted is False
    assert len(outcome.results) == 0
    assert len(outcome.skipped_unreachable) == 0
    assert len(outcome.startup_failed) == 1
    assert outcome.exit_code() == 1


def test_execute_outcome_exit_code_zero_only_when_all_passed(tmp_path):
    """Sanity check the guard did not change the ordinary passed/failed behavior."""
    all_passed = exec_phase.ExecuteOutcome(
        phase="execute",
        results=(
            CellResult(
                platform="duckdb",
                benchmark="tpch",
                scale=0.01,
                status="passed",
                exit_code=0,
                elapsed_s=1.0,
                log_path=tmp_path / "cell.log",
                result_path=None,
            ),
        ),
        pruned=(),
        skipped_unreachable=(),
    )
    assert all_passed.exit_code() == 0

    one_failed = exec_phase.ExecuteOutcome(
        phase="execute",
        results=(
            CellResult(
                platform="duckdb",
                benchmark="tpch",
                scale=0.01,
                status="failed",
                exit_code=1,
                elapsed_s=1.0,
                log_path=tmp_path / "cell.log",
                result_path=None,
            ),
        ),
        pruned=(),
        skipped_unreachable=(),
    )
    assert one_failed.exit_code() == 1

    no_results = exec_phase.ExecuteOutcome(
        phase="execute",
        results=(),
        pruned=(),
        skipped_unreachable=(),
    )
    assert no_results.exit_code() == 1


def test_execute_unmanaged_docker_keeps_skip_probe_without_commands(tmp_path):
    cfg = validate_config(
        {
            "name": "external",
            "platforms": {"include": ["postgresql"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "cleanup": {"docker_manage_platforms": False, "docker_platform_switch": "off"},
        }
    )

    def fail_docker(argv, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError(f"unexpected Docker command: {argv}")

    with platform_reachability(False):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            docker_runner=fail_docker,
            runner=_stub_runner_factory({}, {}),
        )

    assert len(outcome.results) == 0
    assert len(outcome.skipped_unreachable) == 1
    assert any(event.action == "manage" and event.status == "disabled" for event in outcome.docker_events)


@pytest.mark.parametrize(
    ("docker_manage_platforms", "expected_local_managed"),
    [(False, False), (True, True)],
)
def test_execute_scopes_local_managed_platform_options_to_managed_docker(
    docker_manage_platforms: bool,
    expected_local_managed: bool,
    tmp_path,
):
    cfg = validate_config(
        {
            "name": "docker scope",
            "platforms": {"include": ["postgresql"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "cleanup": {
                "docker_manage_platforms": docker_manage_platforms,
                "docker_platform_switch": "volumes" if docker_manage_platforms else "off",
            },
        }
    )
    seen: dict[str, bool] = {}

    def fake_docker(argv, **kwargs):
        if _docker_verb(argv) == "ps":
            return _healthy_ps_result(argv)
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    def recording_runner(platform, benchmark, scale, **kwargs):
        seen["local_managed_platform"] = kwargs["local_managed_platform"]
        return CellResult(
            platform=platform,
            benchmark=benchmark,
            scale=scale,
            status="passed",
            exit_code=0,
            elapsed_s=1.0,
            log_path=tmp_path / "postgresql.log",
            result_path=None,
        )

    with platform_reachability(True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=recording_runner,
            docker_runner=fake_docker,
            sleep_fn=lambda _s: None,
        )

    assert outcome.aborted is False
    assert seen["local_managed_platform"] is expected_local_managed


def test_execute_runner_exception_still_tears_down_managed_docker(tmp_path):
    cfg = validate_config(
        {
            "name": "docker failure",
            "platforms": {"include": ["clickhouse-server"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )
    actions: list[str] = []

    def fake_docker(argv, **kwargs):
        action = _docker_verb(argv)
        actions.append(action)
        if action == "ps":
            return _healthy_ps_result(argv)
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    def raising_runner(platform, benchmark, scale, **kwargs):
        raise RuntimeError("cell exploded")

    with (
        platform_reachability(True),
        pytest.raises(RuntimeError, match="cell exploded"),
    ):
        exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=raising_runner,
            docker_runner=fake_docker,
            free_space_reader=lambda _path: 100.0,
            sleep_fn=lambda _s: None,
        )

    assert actions == ["up", "ps", "down"]


def test_execute_fixed_container_name_platform_aborts_before_docker_command(tmp_path, monkeypatch):
    pg_duckdb_spec = docker_assets.docker_platform_spec("pg-duckdb")
    monkeypatch.setitem(
        docker_assets._DOCKER_PLATFORM_SPECS,
        "pg-duckdb",
        docker_assets.DockerPlatformSpec(
            platform=pg_duckdb_spec.platform,
            compose_files=pg_duckdb_spec.compose_files,
            fixed_container_names=("benchbox-pg-duckdb",),
            tcp_probe_label=pg_duckdb_spec.tcp_probe_label,
            notes=pg_duckdb_spec.notes,
        ),
    )
    cfg = validate_config(
        {
            "name": "fixed name",
            "platforms": {"include": ["pg-duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )

    def fail_docker(argv, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError(f"unexpected Docker command: {argv}")

    outcome = exec_phase.run_execute(
        cfg,
        log_dir=tmp_path,
        databases_root=tmp_path / "databases",
        docker_runner=fail_docker,
        runner=_stub_runner_factory({}, {}),
    )

    assert outcome.aborted is True
    assert "fixed container_name" in (outcome.abort_reason or "")
    assert outcome.docker_events == ()


def test_execute_free_space_abort_reports_context_after_docker_teardown(tmp_path):
    cfg = validate_config(
        {
            "name": "docker disk",
            "platforms": {"include": ["clickhouse-server"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "preflight": {"free_space_min_gib": 5, "free_space_path": str(tmp_path)},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )
    readings = iter([10.0, 1.0])

    def fake_docker(argv, **kwargs):
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    with platform_reachability(True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=_stub_runner_factory({0.01: 1.0}, {0.01: True}),
            docker_runner=fake_docker,
            free_space_checks_enabled=True,
            free_space_reader=lambda _path: next(readings),
            sleep_fn=lambda _s: None,
        )

    assert outcome.aborted is True
    assert "after Docker teardown" in (outcome.abort_reason or "")
    assert "last_completed_platform=clickhouse-server" in (outcome.abort_reason or "")
    assert "docker_cleanup_status=ok" in (outcome.abort_reason or "")


def test_execute_passes_config_extra_args_to_runner(tmp_path):
    cfg = validate_config(
        {
            "name": "fake",
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "execute": {"extra_args": ["--tuning", "tuned"]},
        }
    )
    seen: dict[str, tuple[str, ...] | Path] = {}

    def recording_runner(platform, benchmark, scale, **kwargs):
        seen["extra_args"] = tuple(kwargs["extra_args"])
        seen["benchmark_runs_dir"] = kwargs["benchmark_runs_dir"]
        return CellResult(
            platform=platform,
            benchmark=benchmark,
            scale=scale,
            status="passed",
            exit_code=0,
            elapsed_s=1.0,
            log_path=Path("/tmp/x.log"),
            result_path=None,
        )

    exec_phase.run_execute(
        cfg,
        log_dir=tmp_path,
        databases_root=tmp_path / "databases",
        runner=recording_runner,
    )
    assert seen["extra_args"] == ("--tuning", "tuned")
    assert seen["benchmark_runs_dir"] == Path("~/Developer/benchmark_runs").expanduser()


def test_execute_outcome_carries_compatibility_pruned_cells(tmp_path):
    cfg = validate_config(
        {
            "name": "compat",
            "platforms": {"include": ["polars-df"]},
            "benchmarks": {"include": ["vector_search", "tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )

    outcome = exec_phase.run_execute(
        cfg,
        log_dir=tmp_path,
        databases_root=tmp_path / "databases",
        runner=_stub_runner_factory({0.01: 1.0}, {0.01: True}),
    )

    assert len(outcome.results) == 1
    assert len(outcome.compatibility_pruned) == 1
    assert outcome.compatibility_pruned[0].rule_id == "uat.compat.dataframe.sql_only_benchmark"


def test_execute_downgrades_passed_cell_with_query_failure_result(tmp_path):
    """A passed cell whose result JSON refuses submission surfaces as FAILED.

    Submit classification is the runner's job (run_cell, runner.py:256-260);
    execute.py no longer re-applies it. The fake runner therefore mirrors
    run_cell's classification step against the real fixture JSON, and the
    test pins that the classified failure flows through run_execute's
    pipeline (ladder, results aggregation) unmangled.
    """
    result_path = tmp_path / "benchmark_runs" / "results" / "failed-query.json"
    _write_submit_result(result_path, failed=1)
    cfg = validate_config(
        {
            "name": "fake",
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )

    def fake_runner(platform, benchmark, scale, **kwargs):
        # Same classification sequence as the real run_cell: classify the
        # exported result JSON, downgrade a passed status when the submit
        # state is a cell failure.
        submit_state = classify_for_submit(result_path)
        is_failure = submit_state_is_cell_failure(submit_state)
        return CellResult(
            platform=platform,
            benchmark=benchmark,
            scale=scale,
            status="failed" if is_failure else "passed",
            exit_code=1 if is_failure else 0,
            elapsed_s=1.0,
            log_path=tmp_path / "cell.log",
            result_path=result_path,
            submit_terminal_state=submit_state.value,
        )

    outcome = exec_phase.run_execute(
        cfg,
        log_dir=tmp_path,
        databases_root=tmp_path / "databases",
        runner=fake_runner,
    )

    assert outcome.results[0].status == "failed"
    assert outcome.results[0].submit_terminal_state == "query_failure"


def test_package_classifier_agrees_with_query_failure_refusal(tmp_path):
    result_path = tmp_path / "benchmark_runs" / "results" / "failed-query.json"
    _write_submit_result(result_path, failed=1)
    cfg = validate_config({"name": "fake", "package": {"submit_terminal_state": "local-stage"}})
    warnings: list[str] = []
    calls: list[tuple[str, ...]] = []

    def fake_runner(argv, check=False):
        calls.append(tuple(argv))
        return type("Completed", (), {"returncode": 0})()

    result = package_phase.run_package(
        cfg,
        result_paths=[result_path],
        submissions_dir=tmp_path / "subs",
        runner=fake_runner,
        warn=warnings.append,
        classify_results=True,
    )

    assert result.failure_count == 1
    assert calls == []
    assert "query_failure" in warnings[0]


def test_default_log_dir_substitutes_date_and_name():
    cfg = validate_config({"name": "uat-2026-05-02"})
    out = exec_phase.default_log_dir(cfg, now=_dt.datetime(2026, 5, 5))
    assert "20260505" in str(out)
    assert "uat-2026-05-02" not in str(out)  # default template uses {date} only


def test_default_log_dir_substitutes_time_component():
    """The DEFAULT template's {time} placeholder expands to HHMMSS."""
    cfg = validate_config({"name": "uat-smoke"})
    out = exec_phase.default_log_dir(cfg, now=_dt.datetime(2026, 5, 5, 14, 30, 7))
    assert "143007" in str(out)


def test_default_log_dir_time_avoids_same_day_collision():
    """Two same-day sweeps at different times land in distinct default dirs.

    Prior to uat-resume-retirement-artifact-durability the default template
    was {date}-only, so a second same-day run silently overwrote the
    first run's evidence (mode "w" on every durable artifact).
    """
    cfg = validate_config({"name": "uat-smoke"})
    first = exec_phase.default_log_dir(cfg, now=_dt.datetime(2026, 5, 5, 9, 0, 0))
    second = exec_phase.default_log_dir(cfg, now=_dt.datetime(2026, 5, 5, 9, 0, 1))
    assert first != second


def test_default_log_dir_same_second_collision_gets_disambiguated(tmp_path: Path):
    """#1143 review: {time} truncates to HHMMSS, so two sweeps starting in the
    same second (e.g. automation kicking off multiple configs at once)
    resolved to the same directory pre-fix, silently combining/overwriting
    durable artifacts. A path that already exists on disk now gets a
    numeric suffix instead.
    """
    cfg = validate_config(
        {
            "name": "collision-smoke",
            "output": {"logs_dir_template": str(tmp_path / "uat_{date}_{time}")},
        }
    )
    now = _dt.datetime(2026, 5, 5, 9, 0, 0)
    first = exec_phase.default_log_dir(cfg, now=now)
    first.mkdir(parents=True)
    second = exec_phase.default_log_dir(cfg, now=now)

    assert first != second
    assert second.name == f"{first.name}-2"


def test_default_log_dir_explicit_date_only_template_still_works():
    """Existing configs with an explicit {date}-only template keep working verbatim."""
    cfg = validate_config(
        {
            "name": "uat-smoke",
            "output": {"logs_dir_template": "~/Developer/benchmark_runs/logs/uat_custom_{date}"},
        }
    )
    out = exec_phase.default_log_dir(cfg, now=_dt.datetime(2026, 5, 5, 9, 0, 0))
    assert str(out).endswith("uat_custom_20260505")


def test_atomic_write_text_writes_content_and_cleans_up_tmp(tmp_path: Path):
    target = tmp_path / "nested" / "cells.jsonl"
    report_phase.atomic_write_text(target, "line-one\nline-two\n")

    assert target.read_text(encoding="utf-8") == "line-one\nline-two\n"
    assert not target.with_name(target.name + ".tmp").exists()


def test_atomic_write_text_overwrites_existing_content(tmp_path: Path):
    target = tmp_path / "matrix_summary.tsv"
    report_phase.atomic_write_text(target, "first\n")
    report_phase.atomic_write_text(target, "second\n")

    assert target.read_text(encoding="utf-8") == "second\n"


def test_atomic_write_text_survives_a_failed_write_without_torn_output(tmp_path: Path):
    """A write failure must not clobber the previous good artifact.

    The temp-file + os.replace design means a crash or exception while
    building/writing the new content leaves the last successfully written
    artifact untouched -- unlike the prior mode="w" writes, which truncated
    the destination file before any new content was available. The failed
    write's .tmp sibling must also be cleaned up, not orphaned in the run
    directory.
    """
    target = tmp_path / "validator_rollup.tsv"
    report_phase.atomic_write_text(target, "good-content\n")

    with patch("tests.uat.phases.report.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            report_phase.atomic_write_text(target, "new-content-that-never-lands\n")

    assert target.read_text(encoding="utf-8") == "good-content\n"
    assert not target.with_name(target.name + ".tmp").exists()


def test_default_benchmark_runs_dir_substitutes_date_and_name(tmp_path):
    cfg = validate_config(
        {
            "name": "uat-smoke",
            "output": {"benchmark_runs_dir_template": str(tmp_path / "{name}" / "{date}")},
        }
    )
    out = exec_phase.default_benchmark_runs_dir(cfg, now=_dt.datetime(2026, 5, 5))
    assert out == tmp_path / "uat-smoke" / "20260505"


# ---------------------------------------------------------------------------
# BENCHBOX_OUTPUT_DIR as base for DEFAULT output templates
# (uat-operator-provisioning w2). Explicit YAML templates always win
# (must_preserve) -- bare uat-cell already honored the env var
# (tests.uat.runner._default_*_dir); sweeps did not until this fix.
# ---------------------------------------------------------------------------


def test_default_benchmark_runs_dir_honors_env_var_when_template_is_default(monkeypatch, tmp_path):
    monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", str(tmp_path / "external-root"))
    cfg = validate_config({"name": "uat-smoke"})  # output.* left at schema defaults
    out = exec_phase.default_benchmark_runs_dir(cfg, now=_dt.datetime(2026, 5, 5))
    assert out == tmp_path / "external-root"


def test_default_log_dir_honors_env_var_when_template_is_default(monkeypatch, tmp_path):
    monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", str(tmp_path / "external-root"))
    cfg = validate_config({"name": "uat-smoke"})
    out = exec_phase.default_log_dir(cfg, now=_dt.datetime(2026, 5, 5, 9, 0, 0))
    assert out == tmp_path / "external-root" / "logs" / "uat_20260505_090000"


def test_default_submissions_dir_honors_env_var_when_template_is_default(monkeypatch, tmp_path):
    monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", str(tmp_path / "external-root"))
    cfg = validate_config({"name": "uat-smoke"})

    out = exec_phase.default_submissions_dir(cfg, now=_dt.datetime(2026, 5, 5))

    assert out == tmp_path / "external-root" / "submissions" / "uat-smoke"


def test_default_benchmark_runs_dir_explicit_template_wins_over_env_var(monkeypatch, tmp_path):
    """An explicit YAML template must never be silently overridden by the env var."""
    monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", str(tmp_path / "external-root"))
    cfg = validate_config(
        {
            "name": "uat-smoke",
            "output": {"benchmark_runs_dir_template": str(tmp_path / "explicit-root")},
        }
    )
    out = exec_phase.default_benchmark_runs_dir(cfg, now=_dt.datetime(2026, 5, 5))
    assert out == tmp_path / "explicit-root"


def test_default_log_dir_explicit_template_wins_over_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", str(tmp_path / "external-root"))
    cfg = validate_config(
        {
            "name": "uat-smoke",
            "output": {"logs_dir_template": str(tmp_path / "explicit-logs" / "uat_{date}")},
        }
    )
    out = exec_phase.default_log_dir(cfg, now=_dt.datetime(2026, 5, 5, 9, 0, 0))
    assert out == tmp_path / "explicit-logs" / "uat_20260505"


def test_default_benchmark_runs_dir_default_template_without_env_var_unchanged(monkeypatch):
    """No env var set -> the schema default template still resolves verbatim."""
    monkeypatch.delenv("BENCHBOX_OUTPUT_DIR", raising=False)
    cfg = validate_config({"name": "uat-smoke"})
    out = exec_phase.default_benchmark_runs_dir(cfg, now=_dt.datetime(2026, 5, 5))
    assert out == Path("~/Developer/benchmark_runs").expanduser()


def test_default_benchmark_runs_dir_explicit_template_equal_to_default_wins_over_env_var(monkeypatch, tmp_path):
    """Provenance, not value equality (uat-operator-provisioning review response).

    A config that explicitly sets `benchmark_runs_dir_template` to the SAME
    string as the schema default must still be treated as explicit -- the
    prior string-equality check in `_resolve_output_base` could not tell
    this apart from "unset", so BENCHBOX_OUTPUT_DIR would silently reroot an
    explicit template that happened to match the default value.
    """
    monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", str(tmp_path / "external-root"))
    default_template = "~/Developer/benchmark_runs"
    cfg = validate_config(
        {
            "name": "uat-smoke",
            "output": {"benchmark_runs_dir_template": default_template},
        }
    )
    assert "benchmark_runs_dir_template" in cfg.output.explicitly_set
    out = exec_phase.default_benchmark_runs_dir(cfg, now=_dt.datetime(2026, 5, 5))
    # Explicit value wins -- NOT rerooted under tmp_path / "external-root".
    assert out == Path(default_template).expanduser()


def test_topological_sort_moves_source_before_consumer():
    consumer_to_sources = {
        "read_primitives": ["tpch"],
        "write_primitives": ["tpch"],
    }
    out = exec_phase._topological_sort(
        ["read_primitives", "tpch", "write_primitives"],
        consumer_to_sources,
    )
    assert out.index("tpch") < out.index("read_primitives")
    assert out.index("tpch") < out.index("write_primitives")


def test_topological_sort_stable_when_no_constraint():
    """Benchmarks unconstrained by the reuse graph keep input order."""
    out = exec_phase._topological_sort(["clickbench", "ssb", "h2odb"], {})
    assert out == ["clickbench", "ssb", "h2odb"]


def test_topological_sort_keeps_available_unrelated_benchmark_before_source():
    """Stable order should move sources only as far left as dependency constraints require."""
    consumer_to_sources = {
        "read_primitives": ["tpch"],
        "write_primitives": ["tpch"],
        "transaction_primitives": ["tpch"],
        "ai_primitives": ["tpch"],
    }
    out = exec_phase._topological_sort(
        [
            "read_primitives",
            "clickbench",
            "tpch",
            "write_primitives",
            "transaction_primitives",
            "ai_primitives",
        ],
        consumer_to_sources,
    )
    assert out == [
        "clickbench",
        "tpch",
        "read_primitives",
        "write_primitives",
        "transaction_primitives",
        "ai_primitives",
    ]


def test_execute_reorders_consumer_before_source(tmp_path):
    """Even if include lists read_primitives first, tpch must run first."""
    cfg = validate_config(
        {
            "name": "fake",
            "platforms": {"include": ["duckdb"]},
            # Order deliberately puts the consumer first.
            "benchmarks": {"include": ["read_primitives", "tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )
    invocations: list[str] = []

    def recording_runner(platform, benchmark, scale, **kwargs):
        invocations.append(benchmark)
        return CellResult(
            platform=platform,
            benchmark=benchmark,
            scale=scale,
            status="passed",
            exit_code=0,
            elapsed_s=1.0,
            log_path=Path("/tmp/x.log"),
            result_path=None,
        )

    exec_phase.run_execute(
        cfg,
        log_dir=tmp_path,
        databases_root=tmp_path / "databases",
        runner=recording_runner,
    )
    assert "tpch" in invocations and "read_primitives" in invocations
    assert invocations.index("tpch") < invocations.index("read_primitives")


def test_execute_prunes_source_after_consumer_completes(tmp_path):
    """The tpch DB should be pruned once its only consumer (read_primitives) finishes."""
    cfg = validate_config(
        {
            "name": "fake",
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch", "read_primitives"]},
            "scales": {"rungs": [0.01]},
        }
    )
    db_root = tmp_path / "databases"
    # Create a fake on-disk source DB so prune_database_dir has something to remove.
    (db_root / "duckdb" / "tpch" / "0.01").mkdir(parents=True)
    (db_root / "duckdb" / "tpch" / "0.01" / "data.duckdb").write_text("stub")

    runner = _stub_runner_factory(
        elapsed_map={0.01: 1.0},
        pass_map={0.01: True},
    )
    exec_phase.run_execute(
        cfg,
        log_dir=tmp_path,
        databases_root=db_root,
        runner=runner,
    )
    # After read_primitives completes, the tpch source DB should have been pruned.
    assert not (db_root / "duckdb" / "tpch" / "0.01").exists()


def test_execute_does_not_prune_source_while_consumer_pending(tmp_path):
    """During the (duckdb, tpch) cleanup pass, read_primitives is still pending — DB stays."""
    cfg = validate_config(
        {
            "name": "fake",
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch", "read_primitives"]},
            "scales": {"rungs": [0.01]},
        }
    )
    db_root = tmp_path / "databases"
    (db_root / "duckdb" / "tpch" / "0.01").mkdir(parents=True)
    (db_root / "duckdb" / "tpch" / "0.01" / "data.duckdb").write_text("stub")

    # Stop after tpch finishes, before read_primitives runs.
    invocations: list[str] = []

    def stop_after_tpch(platform, benchmark, scale, **kwargs):
        invocations.append(benchmark)
        if benchmark == "read_primitives":
            raise RuntimeError("should be reachable but we want to inspect mid-state")
        return CellResult(
            platform=platform,
            benchmark=benchmark,
            scale=scale,
            status="passed",
            exit_code=0,
            elapsed_s=1.0,
            log_path=Path("/tmp/x.log"),
            result_path=None,
        )

    with pytest.raises(RuntimeError):
        exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=db_root,
            runner=stop_after_tpch,
        )
    # tpch ran; read_primitives was attempted next (before its cleanup);
    # the tpch DB must NOT have been pruned because read_primitives is
    # the consumer that gates the prune.
    assert (db_root / "duckdb" / "tpch" / "0.01").exists()


# ---------------------------------------------------------------------------
# Per-cell liveness probe: the 2026-08-04 incident, reproduced.
#
# `up --wait` returns 0, the readiness check passes, and the container dies
# ~29s later, partway through the platform's cell list. Before the probe
# existed, every remaining cell ran against the dead stack and was recorded
# as a CELL FAILURE -- 171 of them. The post-start readiness check cannot
# catch this: it has rendered its verdict ~12s after `up --wait`.
# ---------------------------------------------------------------------------


def _probe_dying_after(alive_calls: int):
    """Reachability probe that reports True `alive_calls` times, then False forever.

    Call order for a managed Docker platform, so the counts below are
    readable rather than magic:
      1. the post-start readiness check
      2. arming the liveness probe at the start of the platform's cell list
      3+ the per-cell liveness probe, once before each cell
    """
    calls = {"n": 0}

    def probe(_platform, **_kwargs):
        calls["n"] += 1
        return calls["n"] <= alive_calls

    return probe


def test_execute_stack_dying_mid_platform_records_remaining_cells_as_died_not_failures(tmp_path):
    """The headline regression. Stack is up at platform start and for the
    first cell, then dies. Remaining cells must land in `died_mid_platform`
    and must NOT appear as cell failures."""
    cfg = validate_config(
        {
            "name": "mid platform death",
            "platforms": {"include": ["clickhouse-server"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01, 0.1, 1.0]},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )
    ran: list[float] = []

    def recording_runner(platform, benchmark, scale, **kwargs):
        ran.append(scale)
        return CellResult(
            platform=platform,
            benchmark=benchmark,
            scale=scale,
            status="passed",
            exit_code=0,
            elapsed_s=1.0,
            log_path=tmp_path / f"{platform}-{scale}.log",
            result_path=None,
        )

    # readiness + arm + the 0.01 cell all see it alive; it dies before 0.1.
    with platform_reachability(True, probe=_probe_dying_after(3)):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=recording_runner,
            docker_runner=_healthy_fake_docker,
            sleep_fn=lambda _s: None,
        )

    assert ran == [0.01]
    died = [(c.platform, c.scale) for c in outcome.died_mid_platform]
    assert died == [("clickhouse-server", 0.1), ("clickhouse-server", 1.0)]
    # The whole point: NOT cell failures, and not silently dropped either.
    assert [r.status for r in outcome.results] == ["passed"]
    assert not any(r.status == "failed" for r in outcome.results)
    assert outcome.startup_failed == ()
    assert outcome.skipped_unreachable == ()
    # A lost platform is a real failure of the sweep, not a clean skip.
    assert outcome.exit_code() == 1
    lifecycle = (tmp_path / "uat_lifecycle.log").read_text(encoding="utf-8")
    assert "[liveness]" in lifecycle
    assert "died-mid-platform" in lifecycle


def test_execute_stack_death_also_claims_the_platforms_later_benchmarks(tmp_path):
    """The bucket is per-PLATFORM: benchmarks queued after the one that was
    interrupted never run either, and must be accounted, not vanish."""
    cfg = validate_config(
        {
            "name": "death spans benchmarks",
            "platforms": {"include": ["clickhouse-server"]},
            "benchmarks": {"include": ["tpch", "tpcds"]},
            "scales": {"rungs": [0.01, 0.1]},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )

    def recording_runner(platform, benchmark, scale, **kwargs):
        return CellResult(
            platform=platform,
            benchmark=benchmark,
            scale=scale,
            status="passed",
            exit_code=0,
            elapsed_s=1.0,
            log_path=tmp_path / "cell.log",
            result_path=None,
        )

    # readiness + arm + the first cell; dead from the second cell onward.
    with platform_reachability(True, probe=_probe_dying_after(3)):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=recording_runner,
            docker_runner=_healthy_fake_docker,
            sleep_fn=lambda _s: None,
        )

    assert len(outcome.results) == 1
    # Every cell the platform still owed: the rest of tpch plus all of tpcds.
    assert len(outcome.died_mid_platform) == 3
    assert {c.benchmark for c in outcome.died_mid_platform} == {"tpch", "tpcds"}
    # No cell count is lost: 4 defined = 1 run + 3 died.
    assert len(outcome.results) + len(outcome.died_mid_platform) == 4


def test_execute_stack_death_does_not_stop_the_next_platform(tmp_path):
    """One platform dying must not truncate the sweep -- same advance policy
    as a startup failure (uat-docker-stack-recovery w2)."""
    cfg = validate_config(
        {
            "name": "death advances",
            "platforms": {"include": ["clickhouse-server", "duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01, 0.1]},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )

    def probe(platform, **_kwargs):
        # clickhouse is up to arm, then dead; duckdb is always fine.
        if platform != "clickhouse-server":
            return True
        probe.calls += 1  # type: ignore[attr-defined]
        return probe.calls <= 2  # type: ignore[attr-defined]  # readiness + arm only

    probe.calls = 0  # type: ignore[attr-defined]

    with platform_reachability(True, probe=probe):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=_stub_runner_factory({0.01: 1.0, 0.1: 1.0}, {0.01: True, 0.1: True}),
            docker_runner=_healthy_fake_docker,
            sleep_fn=lambda _s: None,
        )

    assert outcome.aborted is False
    assert {c.platform for c in outcome.died_mid_platform} == {"clickhouse-server"}
    assert any(r.platform == "duckdb" and r.status == "passed" for r in outcome.results)


def test_execute_liveness_probe_disabled_by_zero_timeout(tmp_path):
    """0 disables the probe -- the same opt-out shape as the two *_min_gib
    floors. With it off, a dead stack is invisible again (cells run and the
    runner reports whatever it reports), which is exactly why the default is
    not 0."""
    cfg = validate_config(
        {
            "name": "liveness off",
            "platforms": {"include": ["clickhouse-server"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01, 0.1]},
            "execute": {"liveness_probe_timeout_s": 0},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )

    with platform_reachability(True, probe=_probe_dying_after(1)):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=_stub_runner_factory({0.01: 1.0, 0.1: 1.0}, {0.01: True, 0.1: True}),
            docker_runner=_healthy_fake_docker,
            sleep_fn=lambda _s: None,
        )

    assert outcome.died_mid_platform == ()
    assert len(outcome.results) == 2


def test_execute_liveness_probe_not_armed_for_a_platform_that_was_never_reachable(tmp_path):
    """`died_mid_platform` means "was up, then died". A platform that never
    listened (skip_unreachable: false, so cells are attempted anyway) must
    not be relabelled as a mid-run death."""
    cfg = validate_config(
        {
            "name": "never reachable",
            "platforms": {"include": ["clickhouse-server"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01, 0.1]},
            "execute": {"skip_unreachable": False},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )

    # Readiness passes (ps is healthy and its probe is the first call), but
    # the platform is not reachable when the cell list starts.
    with platform_reachability(True, probe=_probe_dying_after(1)):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=_stub_runner_factory({0.01: 1.0, 0.1: 1.0}, {0.01: True, 0.1: True}),
            docker_runner=_healthy_fake_docker,
            sleep_fn=lambda _s: None,
        )

    assert outcome.died_mid_platform == ()
    assert len(outcome.results) == 2


def test_execute_readiness_check_does_not_poison_the_reachability_cache(tmp_path):
    """Regression guard for the defect that made adding the readiness check a
    net LOSS of coverage.

    The readiness check originally probed via the CACHED
    `platform_is_reachable`, which writes True into
    `matrix._REACHABILITY_CACHE`. `_run_or_skip_platform`'s skip_unreachable
    check then read that cached True instead of probing -- so the new check
    silently disabled the existing check downstream of it, and the cache is
    cleared only on lifecycle changes, never in between.

    Asserted directly: when the skip_unreachable check runs, the cache must
    still be empty, i.e. it is about to do real work rather than read
    somebody else's answer.
    """
    cfg = _managed_docker_cfg("no cache poisoning")
    cache_when_skip_check_ran: list[dict] = []
    real_is_reachable = matrix.platform_is_reachable

    def spy(platform, *args, **kwargs):
        cache_when_skip_check_ran.append(dict(matrix._REACHABILITY_CACHE))
        return real_is_reachable(platform, *args, **kwargs)

    with (
        patch.object(matrix, "tcp_probe", return_value=True),
        patch.object(exec_phase, "platform_is_reachable", side_effect=spy),
    ):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=_stub_runner_factory({0.01: 1.0}, {0.01: True}),
            docker_runner=_healthy_fake_docker,
            sleep_fn=lambda _s: None,
        )

    assert outcome.aborted is False
    # The cached entry point is reached exactly once (the skip_unreachable
    # check), and nothing had populated the cache before it.
    assert cache_when_skip_check_ran == [{}]


def test_execute_readiness_check_fails_closed_on_an_empty_compose_ps_table(tmp_path):
    """`ps -a` finding no rows for a project that was just `up`'d means the
    containers are gone. Passing there would be the same fail-open shape as
    the missing `-a` flag: an empty result read as a healthy one."""
    cfg = _managed_docker_cfg("empty ps table")

    def fake_docker(argv, **kwargs):
        if _docker_verb(argv) == "ps":
            return docker_assets.DockerCommandResult(tuple(argv), 0, "NAME   IMAGE   STATUS\n", "")
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    def fail_runner(platform, benchmark, scale, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("no cell may run when compose ps -a lists no services")

    with platform_reachability(True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=fail_runner,
            docker_runner=fake_docker,
            sleep_fn=lambda _s: None,
        )

    assert outcome.aborted is False
    assert any(cell.platform == "clickhouse-server" for cell in outcome.startup_failed)
    readiness_event = next(e for e in outcome.docker_events if e.action == "readiness")
    assert "listed no services" in readiness_event.message


def test_execute_readiness_check_requests_ps_all(tmp_path):
    """Regression guard: without `-a` the dead container is not in the output."""
    cfg = _managed_docker_cfg("ps all argv")
    ps_argvs: list[tuple[str, ...]] = []

    def fake_docker(argv, **kwargs):
        if _docker_verb(argv) == "ps":
            ps_argvs.append(tuple(argv))
            return _healthy_ps_result(argv)
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    with platform_reachability(True):
        exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=_stub_runner_factory({0.01: 1.0}, {0.01: True}),
            docker_runner=fake_docker,
            sleep_fn=lambda _s: None,
        )

    assert ps_argvs and all(argv[-2:] == ("ps", "-a") for argv in ps_argvs)
