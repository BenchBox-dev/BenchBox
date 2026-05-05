"""Fast-test coverage for tests/uat/phases/*.py (preflight, enumerate, execute)."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.uat import matrix
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


def test_default_log_dir_substitutes_date_and_name():
    cfg = validate_config({"name": "uat-2026-05-02"})
    out = exec_phase.default_log_dir(cfg, now=_dt.datetime(2026, 5, 5))
    assert "20260505" in str(out)
    assert "uat-2026-05-02" not in str(out)  # default template uses {date} only
