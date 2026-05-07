"""Fast-test coverage for tests/uat/phases/*.py (preflight, enumerate, execute)."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.uat import docker_assets, matrix
from tests.uat.config import validate_config
from tests.uat.phases import enumerate as enum_phase, execute as exec_phase, preflight as preflight_phase
from tests.uat.runner import CellResult

pytestmark = pytest.mark.fast


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
    cells = enum_phase.enumerate_cells(raw)
    benches = {c.benchmark for c in cells}
    assert "vector_search" not in benches  # sql-only
    assert "tpch" in benches


def test_enumerate_honours_scale_options():
    raw = {
        "platforms": {"include": ["duckdb"]},
        "benchmarks": {"include": ["tpch"]},
        "scales": {"rungs": [0.01, 0.1, 1.0, 100.0]},
    }
    cells = enum_phase.enumerate_cells(raw)
    scales = {c.scale for c in cells}
    # tpch scale_options=[0.01, 0.1, 1.0, 10.0] → 100.0 dropped.
    assert 100.0 not in scales
    assert {0.01, 0.1, 1.0}.issubset(scales)


def test_enumerate_override_replaces_rungs():
    raw = {
        "platforms": {"include": ["duckdb"]},
        "benchmarks": {"include": ["tpch"]},
        "scales": {"rungs": [0.01, 0.1, 1.0], "override": 0.1},
    }
    cells = enum_phase.enumerate_cells(raw)
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
    matrix.reset_reachability_cache()
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


def test_execute_skips_unreachable_platform(tmp_path):
    matrix.reset_reachability_cache()
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
    matrix.reset_reachability_cache()
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
    matrix.reset_reachability_cache()
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


def test_execute_unmanaged_docker_keeps_skip_probe_without_commands(tmp_path):
    matrix.reset_reachability_cache()
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


def test_execute_runner_exception_still_tears_down_managed_docker(tmp_path):
    matrix.reset_reachability_cache()
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


def test_execute_fixed_container_name_platform_aborts_before_docker_command(tmp_path):
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
    assert "cannot be UAT-managed" in (outcome.abort_reason or "")
    assert outcome.docker_events == ()


def test_execute_free_space_abort_reports_context_after_docker_teardown(tmp_path):
    matrix.reset_reachability_cache()
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
    matrix.reset_reachability_cache()
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


def test_default_log_dir_substitutes_date_and_name():
    cfg = validate_config({"name": "uat-2026-05-02"})
    out = exec_phase.default_log_dir(cfg, now=_dt.datetime(2026, 5, 5))
    assert "20260505" in str(out)
    assert "uat-2026-05-02" not in str(out)  # default template uses {date} only


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
    """Benchmarks unconstrained by SOURCE_REUSE_GRAPH keep input order."""
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
    matrix.reset_reachability_cache()
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
    matrix.reset_reachability_cache()
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
    matrix.reset_reachability_cache()
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
