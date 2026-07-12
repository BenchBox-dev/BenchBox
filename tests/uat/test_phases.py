"""Fast-test coverage for tests/uat/phases/*.py (preflight, enumerate, execute)."""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.uat import docker_assets, matrix
from tests.uat.config import ExecuteConfig, UATConfig, validate_config
from tests.uat.phases import (
    enumerate as enum_phase,
    execute as exec_phase,
    package as package_phase,
    preflight as preflight_phase,
    report as report_phase,
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
    raw = {
        "platforms": {"include": ["duckdb"]},
        "benchmarks": {"include": ["tpch"]},
        "scales": {"rungs": [0.01, 0.1, 1.0], "override": 0.1},
    }
    cells = enum_phase.enumerate_cells(_cfg(raw))
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
    with patch("tests.uat.phases.execute.platform_is_reachable", return_value=False):
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
    if "/clickhouse/" in compose_file:
        return "clickhouse-server"
    if "/postgresql/" in compose_file:
        return "postgresql"
    if "pg-duckdb" in compose_file:
        return "pg-duckdb"
    return compose_file


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
        action = "up" if "up" in argv else "down"
        sequence.append(("docker", action, _docker_platform_from_argv(argv)))
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

    with patch("tests.uat.phases.execute.platform_is_reachable", return_value=True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=recording_runner,
            docker_runner=fake_docker,
            free_space_checks_enabled=True,
            free_space_reader=lambda _path: 100.0,
        )

    assert outcome.aborted is False
    assert sequence == [
        ("docker", "up", "clickhouse-server"),
        ("cell", "run", "clickhouse-server"),
        ("docker", "down", "clickhouse-server"),
        ("docker", "up", "postgresql"),
        ("cell", "run", "postgresql"),
        ("docker", "down", "postgresql"),
    ]
    assert any(event.action == "down" and event.status == "ok" for event in outcome.docker_events)
    down_commands = [event.result.argv for event in outcome.docker_events if event.action == "down" and event.result]
    assert all("-v" in argv and "--remove-orphans" in argv for argv in down_commands)


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
        action = "up" if "up" in argv else "down"
        commands.append(f"{action}:{_docker_platform_from_argv(argv)}")
        if action == "down":
            return docker_assets.DockerCommandResult(tuple(argv), 1, "", "compose down failed")
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    with patch("tests.uat.phases.execute.platform_is_reachable", return_value=True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=_stub_runner_factory({0.01: 1.0}, {0.01: True}),
            docker_runner=fake_docker,
            free_space_reader=lambda _path: 100.0,
        )

    assert outcome.aborted is True
    assert "Docker cleanup failed" in (outcome.abort_reason or "")
    assert commands == ["up:clickhouse-server", "down:clickhouse-server"]


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
        action = "up" if "up" in argv else "down"
        platform = _docker_platform_from_argv(argv)
        sequence.append(("docker", action, platform))
        # clickhouse-server compose-up fails (e.g. start timeout); others succeed.
        if action == "up" and platform == "clickhouse-server":
            return docker_assets.DockerCommandResult(
                tuple(argv), 1, "", "docker command timed out after 300s", timed_out=True
            )
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

    with patch("tests.uat.phases.execute.platform_is_reachable", return_value=True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=recording_runner,
            docker_runner=fake_docker,
            free_space_checks_enabled=True,
            free_space_reader=lambda _path: 100.0,
        )

    # The sweep is NOT aborted by one stack's startup failure.
    assert outcome.aborted is False
    # The failed stack ran no cells but was still torn down; the next stack ran.
    assert sequence == [
        ("docker", "up", "clickhouse-server"),
        ("docker", "down", "clickhouse-server"),
        ("docker", "up", "postgresql"),
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
        action = "up" if "up" in argv else "down"
        platform = _docker_platform_from_argv(argv)
        sequence.append(("docker", action, platform))
        # clickhouse-server's compose-up fails AND its teardown also fails.
        if platform == "clickhouse-server":
            return docker_assets.DockerCommandResult(tuple(argv), 1, "", f"{action} failed")
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

    with patch("tests.uat.phases.execute.platform_is_reachable", return_value=True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=recording_runner,
            docker_runner=fake_docker,
            free_space_checks_enabled=True,
            free_space_reader=lambda _path: 100.0,
        )

    # The sweep advances past the broken stack instead of a global abort.
    assert outcome.aborted is False
    assert outcome.abort_reason is None
    assert sequence == [
        ("docker", "up", "clickhouse-server"),
        ("docker", "down", "clickhouse-server"),
        ("docker", "up", "postgresql"),
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
        action = "up" if "up" in argv else "down"
        if action == "down":
            return docker_assets.DockerCommandResult(tuple(argv), 1, "", "compose down failed")
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    with patch("tests.uat.phases.execute.platform_is_reachable", return_value=True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=_stub_runner_factory({0.01: 1.0}, {0.01: True}),
            docker_runner=fake_docker,
            free_space_reader=lambda _path: 100.0,
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
        action = "up" if "up" in argv else "down"
        if action == "up":
            return docker_assets.DockerCommandResult(
                tuple(argv), 1, "", "docker command timed out after 300s", timed_out=True
            )
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    def fail_runner(platform, benchmark, scale, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("no cell should run when the only compose-up failed")

    with patch("tests.uat.phases.execute.platform_is_reachable", return_value=True):
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

    with patch("tests.uat.phases.execute.platform_is_reachable", return_value=False):
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

    with patch("tests.uat.phases.execute.platform_is_reachable", return_value=True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=recording_runner,
            docker_runner=fake_docker,
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
        actions.append("up" if "up" in argv else "down")
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    def raising_runner(platform, benchmark, scale, **kwargs):
        raise RuntimeError("cell exploded")

    with (
        patch("tests.uat.phases.execute.platform_is_reachable", return_value=True),
        pytest.raises(RuntimeError, match="cell exploded"),
    ):
        exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=raising_runner,
            docker_runner=fake_docker,
            free_space_reader=lambda _path: 100.0,
        )

    assert actions == ["up", "down"]


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

    with patch("tests.uat.phases.execute.platform_is_reachable", return_value=True):
        outcome = exec_phase.run_execute(
            cfg,
            log_dir=tmp_path,
            databases_root=tmp_path / "databases",
            runner=_stub_runner_factory({0.01: 1.0}, {0.01: True}),
            docker_runner=fake_docker,
            free_space_checks_enabled=True,
            free_space_reader=lambda _path: next(readings),
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
