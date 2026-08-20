"""Fast-test coverage for tests/uat/orchestrator.py."""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.uat import _cli as uat_cli, cells_io, docker_assets, orchestrator
from tests.uat.config import validate_config
from tests.uat.conftest import docker_verb, platform_reachability
from tests.uat.docker_path_helpers import compose_path_ends_with
from tests.uat.phases import execute as exec_phase
from tests.uat.phases.enumerate import CompatibilityPrunedCell
from tests.uat.runner import CellResult

pytestmark = pytest.mark.fast


def test_dry_run_records_zero_per_phase(tmp_path: Path):
    cfg = validate_config(
        {
            "name": "smoke",
            "dry_run": True,
            "phases": ["preflight", "execute", "report"],
        }
    )
    result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path)
    assert result.aborted_phase is None
    assert all(c == 0 for c in result.phase_exit_codes.values())
    assert set(result.phase_exit_codes) == {"preflight", "execute", "report"}


def test_preflight_abort_short_circuits(tmp_path: Path, capsys):
    cfg = validate_config(
        {
            "name": "smoke",
            "phases": ["preflight", "execute"],
        }
    )
    fake_result = type(
        "Stub",
        (),
        {
            "aborted": True,
            "abort_reason": "no disk",
            "warnings": ("disk budget gate has 1 unknown largest-scale cell(s); estimate may be low",),
            "disk_budget_summary": "Disk budget estimate: 12.34 GiB peak",
            "free_space_report": ("Free space: tmp 10.00 GiB (required 12.34 GiB) /tmp",),
            "exit_code": lambda self: 2,
        },
    )()
    with patch.object(
        orchestrator.preflight_phase,
        "run_preflight",
        return_value=fake_result,
    ):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path)
    assert result.aborted_phase == "preflight"
    assert "execute" not in result.phase_exit_codes
    assert result.exit_code() == 2
    captured = capsys.readouterr()
    assert "Disk budget estimate: 12.34 GiB peak" in captured.err
    assert "Free space: tmp 10.00 GiB (required 12.34 GiB) /tmp" in captured.err
    assert "[preflight warn] disk budget gate has 1 unknown largest-scale cell(s); estimate may be low" in captured.err


def test_stress_default_yaml_loads():
    p = Path(__file__).resolve().parent / "configs" / "stress-default.yaml"
    assert p.exists()
    from tests.uat.config import load_config

    cfg = load_config(p)
    assert cfg.name == "stress-default"
    assert "package" not in cfg.phases
    assert "explorer_smoke" not in cfg.phases


def test_stress_docker_managed_yaml_loads():
    p = Path(__file__).resolve().parent / "configs" / "stress-docker-managed.yaml"
    assert p.exists()
    from tests.uat.config import load_config

    cfg = load_config(p)
    assert cfg.name == "stress-docker-managed"
    assert cfg.cleanup.docker_manage_platforms is True
    assert cfg.cleanup.docker_platform_switch == "volumes"
    assert cfg.preflight.docker_required is True


def test_enumerate_is_not_a_public_phase():
    with pytest.raises(ValueError, match="Unknown phase"):
        validate_config({"name": "smoke", "phases": ["enumerate", "execute"]})


def test_dry_run_passes_without_public_enumerate(tmp_path: Path):
    """A valid dry_run sweep no longer exposes enumerate as its own phase."""
    cfg = validate_config(
        {
            "name": "smoke",
            "dry_run": True,
            "phases": ["execute", "report"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )
    result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path)
    assert result.aborted_phase is None
    assert all(c == 0 for c in result.phase_exit_codes.values())
    assert "enumerate" not in result.phase_exit_codes


def test_explorer_smoke_uses_package_submissions_dir(tmp_path: Path):
    cfg = validate_config(
        {
            "name": "smoke",
            "phases": ["execute", "package", "explorer_smoke"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "package": {"submit_terminal_state": "local-stage"},
            "output": {"submissions_dir_template": str(tmp_path / "submissions" / "{name}")},
        }
    )
    cell = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.01,
        status="passed",
        exit_code=0,
        elapsed_s=1.0,
        log_path=tmp_path / "cell.log",
        result_path=tmp_path / "result.json",
    )
    execute_outcome = type(
        "ExecuteOutcome",
        (),
        {"results": (cell,), "aborted": False, "abort_reason": None, "exit_code": lambda self: 0},
    )()
    captured: dict[str, Path] = {}

    def fake_package(config, *, result_paths, submissions_dir):
        captured["package_dir"] = submissions_dir
        return type("PackageResult", (), {"aborted": False, "abort_reason": None, "exit_code": lambda self: 0})()

    def fake_explorer_smoke(**kwargs):
        captured["bundles_dir"] = kwargs["bundles_dir"]
        return type("ExplorerResult", (), {"exit_code": lambda self: 0})()

    with (
        patch.object(orchestrator.exec_phase, "run_execute", return_value=execute_outcome),
        patch("tests.uat.phases.package.run_package", side_effect=fake_package),
        patch("tests.uat.phases.explorer_smoke.run_explorer_smoke", side_effect=fake_explorer_smoke),
    ):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")

    assert result.aborted_phase is None
    assert captured["bundles_dir"] == captured["package_dir"]
    assert captured["bundles_dir"] == tmp_path / "submissions" / "smoke"


# ---------------------------------------------------------------------------
# uat-fail-advance-consistency w1: report-without-execute must abort.
# ---------------------------------------------------------------------------


def test_report_phase_aborts_when_execute_outcome_missing(tmp_path: Path):
    """A report phase with no execute phase in this sweep must abort, not print an empty clean report.

    Before this fix, `cells = execute_outcome.results if execute_outcome
    else []` let the report phase proceed with zero rows and exit 0 -- an
    empty report reads as a clean sweep. validate/package already abort in
    this situation; report must match.
    """
    cfg = validate_config({"name": "report-only", "phases": ["report"]})

    result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")

    assert result.aborted_phase == "report"
    assert "execute phase" in (result.abort_reason or "")
    assert result.exit_code() == 2
    partial_text = (tmp_path / "logs" / "matrix_summary.partial.tsv").read_text(encoding="utf-8")
    assert "# run_status=ABORTED" in partial_text
    assert "abort_phase=report" in partial_text


def test_dry_run_report_only_sweep_stays_exit_zero(tmp_path: Path):
    """Dry-run sweeps skip all phases upstream of the phase-specific branches -- must stay exit 0."""
    cfg = validate_config({"name": "report-only-dry-run", "dry_run": True, "phases": ["report"]})

    result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")

    assert result.aborted_phase is None
    assert result.exit_code() == 0
    assert result.phase_exit_codes == {"report": 0}


# ---------------------------------------------------------------------------
# uat-fail-advance-consistency w2: explorer_smoke corpus failures abort;
# node-missing is a recorded, visible skip.
# ---------------------------------------------------------------------------


def test_explorer_smoke_corpus_failure_emits_abort_artifacts(tmp_path: Path):
    """A structured explorer_smoke corpus failure flows through _emit_abort_artifacts, not an uncaught raise."""
    cfg = validate_config(
        {
            "name": "explorer-corpus-fail",
            "phases": ["execute", "explorer_smoke"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )
    cell = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.01,
        status="passed",
        exit_code=0,
        elapsed_s=1.0,
        log_path=tmp_path / "cell.log",
        result_path=tmp_path / "result.json",
    )
    execute_outcome = type(
        "ExecuteOutcome",
        (),
        {"results": (cell,), "aborted": False, "abort_reason": None, "exit_code": lambda self: 0},
    )()
    aborted_result = type(
        "ExplorerResult",
        (),
        {
            "aborted": True,
            "abort_reason": "Explorer smoke corpus contract failed:\n  - no result bundles",
            "skip_reason": None,
            "exit_code": lambda self: 2,
        },
    )()

    with (
        patch.object(orchestrator.exec_phase, "run_execute", return_value=execute_outcome),
        patch("tests.uat.phases.explorer_smoke.run_explorer_smoke", return_value=aborted_result),
    ):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")

    assert result.aborted_phase == "explorer_smoke"
    assert result.exit_code() == 2
    partial_text = (tmp_path / "logs" / "matrix_summary.partial.tsv").read_text(encoding="utf-8")
    assert "# run_status=ABORTED" in partial_text
    assert "abort_phase=explorer_smoke" in partial_text


def test_explorer_smoke_node_missing_records_sidecar_status_and_warns(tmp_path: Path, capsys):
    """node-missing stays exit 0 but is recorded in the accounting sidecar plus a prominent stderr warning."""
    cfg = validate_config(
        {
            "name": "explorer-node-missing",
            "phases": ["execute", "explorer_smoke"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )
    cell = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.01,
        status="passed",
        exit_code=0,
        elapsed_s=1.0,
        log_path=tmp_path / "cell.log",
        result_path=tmp_path / "result.json",
    )
    execute_outcome = type(
        "ExecuteOutcome",
        (),
        {"results": (cell,), "aborted": False, "abort_reason": None, "exit_code": lambda self: 0},
    )()
    skipped_result = type(
        "ExplorerResult",
        (),
        {
            "aborted": False,
            "abort_reason": None,
            "skipped": True,
            "skip_reason": "node not on PATH",
            "exit_code": lambda self: 0,
        },
    )()

    with (
        patch.object(orchestrator.exec_phase, "run_execute", return_value=execute_outcome),
        patch("tests.uat.phases.explorer_smoke.run_explorer_smoke", return_value=skipped_result),
    ):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")

    assert result.aborted_phase is None
    assert result.phase_exit_codes["explorer_smoke"] == 0
    accounting = json.loads((tmp_path / "logs" / "cells.jsonl.accounting.json").read_text(encoding="utf-8"))
    assert accounting["explorer_smoke_status"] == "skipped_no_node"
    stderr = capsys.readouterr().err
    assert "node not on PATH" in stderr
    assert "skipped_no_node" in stderr
    # The recorded-path warning must claim durable recording, not hedge.
    assert "recorded in the accounting sidecar" in stderr
    assert "NOT durably recorded" not in stderr


def test_explorer_smoke_node_missing_warns_not_durably_recorded_without_sidecar(tmp_path: Path, capsys):
    """When no accounting sidecar exists (no execute phase ran), the warning must say so.

    `update_accounting_sidecar` deliberately refuses to fabricate a sidecar
    (its presence implies confirmed execute-derived counts), so the stderr
    warning must state the status was NOT durably recorded instead of
    implying it was.
    """
    cfg = validate_config({"name": "explorer-node-missing-no-sidecar", "phases": ["explorer_smoke"]})
    skipped_result = type(
        "ExplorerResult",
        (),
        {
            "aborted": False,
            "abort_reason": None,
            "skipped": True,
            "skip_reason": "node not on PATH",
            "exit_code": lambda self: 0,
        },
    )()

    with patch("tests.uat.phases.explorer_smoke.run_explorer_smoke", return_value=skipped_result):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")

    assert result.aborted_phase is None
    assert result.phase_exit_codes["explorer_smoke"] == 0
    assert not (tmp_path / "logs" / "cells.jsonl.accounting.json").exists()
    stderr = capsys.readouterr().err
    assert "node not on PATH" in stderr
    assert "NOT durably recorded" in stderr


def test_package_phase_excludes_failed_cells_result_paths(tmp_path: Path):
    """w4 regression: a failed official cell's exported JSON must not be packaged/submitted.

    runner.py resolves a result path for official cells regardless of exit
    code, so the package-phase input filter must check cell.status, not just
    `result_path is not None`.
    """
    cfg = validate_config(
        {
            "name": "smoke",
            "phases": ["execute", "package"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "package": {"submit_terminal_state": "local-stage"},
            "output": {"submissions_dir_template": str(tmp_path / "submissions" / "{name}")},
        }
    )
    passed_cell = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.01,
        status="passed",
        exit_code=0,
        elapsed_s=1.0,
        log_path=tmp_path / "passed.log",
        result_path=tmp_path / "passed.json",
    )
    failed_cell = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.1,
        status="failed",
        exit_code=1,
        elapsed_s=1.0,
        log_path=tmp_path / "failed.log",
        result_path=tmp_path / "failed.json",
    )
    execute_outcome = type(
        "ExecuteOutcome",
        (),
        {"results": (passed_cell, failed_cell), "aborted": False, "abort_reason": None, "exit_code": lambda self: 1},
    )()
    captured: dict[str, list[Path]] = {}

    def fake_package(config, *, result_paths, submissions_dir):
        captured["result_paths"] = list(result_paths)
        return type("PackageResult", (), {"aborted": False, "abort_reason": None, "exit_code": lambda self: 0})()

    with (
        patch.object(orchestrator.exec_phase, "run_execute", return_value=execute_outcome),
        patch("tests.uat.phases.package.run_package", side_effect=fake_package),
    ):
        orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")

    assert captured["result_paths"] == [passed_cell.result_path]
    assert failed_cell.result_path not in captured["result_paths"]


def test_write_cells_jsonl_persists_throughput_check(tmp_path: Path):
    """w5 regression: throughput_check must survive the cells.jsonl round-trip.

    Before this, CellResult.throughput_check -- the one diagnostic the
    stream-count guard exists to surface -- was dropped by
    cells_io.write_cells_jsonl, so a stream-count failure left durable
    artifacts saying only failed/exit 1 with no explanation.
    """
    cell = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.01,
        status="failed",
        exit_code=1,
        elapsed_s=1.0,
        log_path=tmp_path / "cell.log",
        result_path=tmp_path / "result.json",
        throughput_check="throughput stream count mismatch: requested 3, executed 1",
    )
    source_info = orchestrator.RunSourceInfo(commit_sha="abc123", commit_short_sha="abc123", dirty=False)

    cells_io.write_cells_jsonl(tmp_path / "cells.jsonl", (cell,), source_info=source_info)

    lines = [json.loads(line) for line in (tmp_path / "cells.jsonl").read_text().splitlines()]
    assert lines[0]["throughput_check"] == "throughput stream count mismatch: requested 3, executed 1"


def test_orchestrator_uses_output_root_for_preflight_execute_and_cleanup(tmp_path: Path):
    root = tmp_path / "shared-runs"
    cfg = validate_config(
        {
            "name": "smoke",
            "phases": ["preflight", "execute"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "output": {"benchmark_runs_dir_template": str(root)},
        }
    )
    fake_preflight = type(
        "Preflight",
        (),
        {"aborted": False, "abort_reason": None, "warnings": (), "free_space_report": (), "exit_code": lambda self: 0},
    )()
    fake_execute = type(
        "ExecuteOutcome",
        (),
        {
            "results": (),
            "pruned": (),
            "skipped_unreachable": (),
            "aborted": False,
            "abort_reason": None,
            "exit_code": lambda self: 0,
        },
    )()
    captured: dict[str, Path | str] = {}

    def fake_run_preflight(**kwargs):
        captured["free_space_path"] = kwargs["free_space_path"]
        return fake_preflight

    def fake_run_execute(config, **kwargs):
        captured["benchmark_runs_dir"] = kwargs["benchmark_runs_dir"]
        captured["databases_root"] = kwargs["databases_root"]
        captured["cleanup_enabled"] = kwargs["cleanup_enabled"]
        captured["free_space_checks_enabled"] = kwargs["free_space_checks_enabled"]
        return fake_execute

    with (
        patch.object(orchestrator.preflight_phase, "run_preflight", side_effect=fake_run_preflight),
        patch.object(orchestrator.exec_phase, "run_execute", side_effect=fake_run_execute),
    ):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")

    assert result.aborted_phase is None
    assert captured["free_space_path"] == str(root)
    assert captured["benchmark_runs_dir"] == root
    assert captured["databases_root"] == root / "databases"
    assert captured["cleanup_enabled"] is True
    assert captured["free_space_checks_enabled"] is True


def test_orchestrator_cells_jsonl_marks_timed_out_cells(tmp_path: Path):
    cfg = validate_config(
        {
            "name": "timeout-smoke",
            "phases": ["execute"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )
    cell_log = tmp_path / "cell.log"
    cell_log.write_text("# benchbox run\nstderr tail line\n", encoding="utf-8")
    timed_out_cell = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.01,
        status="timed-out",
        exit_code=124,
        elapsed_s=1.0,
        log_path=cell_log,
        result_path=None,
    )
    fake_execute = type(
        "ExecuteOutcome",
        (),
        {
            "results": (timed_out_cell,),
            "pruned": (),
            "skipped_unreachable": (),
            "aborted": False,
            "abort_reason": None,
            "exit_code": lambda self: 1,
        },
    )()

    with patch.object(orchestrator.exec_phase, "run_execute", return_value=fake_execute):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")

    assert result.phase_exit_codes["execute"] == 1
    cells = [json.loads(line) for line in (tmp_path / "logs" / "cells.jsonl").read_text().splitlines()]
    assert cells[0]["status"] == "timed-out"
    assert cells[0]["terminal_state"] == "timeout"
    assert cells[0]["timed_out"] is True
    assert cells[0]["exit_code"] == 124
    assert cells[0]["source_commit_sha"]
    assert isinstance(cells[0]["source_dirty"], bool)
    assert cells[0]["failure_tail"] == "stderr tail line"
    assert "# UAT_TERMINAL_STATE terminal_state=timeout" in cell_log.read_text(encoding="utf-8")


def test_cells_jsonl_terminal_marker_is_idempotent_after_timeout_marker(tmp_path: Path):
    cell_log = tmp_path / "cell.log"
    cell_log.write_text("# benchbox run\nstderr tail line\n# UAT_TIMEOUT timeout_s=1 exit_code=124\n", encoding="utf-8")
    timed_out_cell = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.01,
        status="timed-out",
        exit_code=124,
        elapsed_s=1.0,
        log_path=cell_log,
        result_path=None,
    )
    source_info = orchestrator.RunSourceInfo(commit_sha="abc123", commit_short_sha="abc123", dirty=False)

    cells_io.write_cells_jsonl(tmp_path / "cells.jsonl", (timed_out_cell,), source_info=source_info)
    cells_io.write_cells_jsonl(tmp_path / "cells.jsonl", (timed_out_cell,), source_info=source_info)

    text = cell_log.read_text(encoding="utf-8")
    assert text.count("# UAT_TERMINAL_STATE terminal_state=timeout") == 1
    assert text.count("# UAT_FAILURE_TAIL_START") == 1


def test_orchestrator_writes_compatibility_pruned_jsonl_and_report_count(tmp_path: Path):
    cfg = validate_config(
        {
            "name": "compat-smoke",
            "phases": ["execute", "report"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )
    cell = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.01,
        status="passed",
        exit_code=0,
        elapsed_s=1.0,
        log_path=tmp_path / "cell.log",
        result_path=None,
    )
    pruned = CompatibilityPrunedCell(
        platform="polars-df",
        benchmark="vector_search",
        scale=0.01,
        rule_id="uat.compat.dataframe.sql_only_benchmark",
        status="blocked",
        reason="not supported",
        evidence="test evidence",
    )
    fake_execute = type(
        "ExecuteOutcome",
        (),
        {
            "results": (cell,),
            "pruned": (),
            "skipped_unreachable": (),
            "compatibility_pruned": (pruned,),
            "aborted": False,
            "abort_reason": None,
            "exit_code": lambda self: 0,
        },
    )()

    with patch.object(orchestrator.exec_phase, "run_execute", return_value=fake_execute):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")

    assert result.phase_exit_codes == {"execute": 0, "report": 0}
    pruned_rows = [
        json.loads(line) for line in (tmp_path / "logs" / "compatibility_pruned.jsonl").read_text().splitlines()
    ]
    assert pruned_rows[0]["status"] == "compatibility-pruned"
    assert pruned_rows[0]["rule_id"] == "uat.compat.dataframe.sql_only_benchmark"
    assert "compatibility_pruned=1" in (tmp_path / "logs" / "matrix_summary.tsv").read_text()


def test_predictive_disk_floor_aborts_before_launching_oversized_known_cell(tmp_path: Path):
    row = orchestrator.preflight_budget.DiskBudgetRow(
        platform="duckdb",
        benchmark="tpch",
        scale_factor=0.01,
        peak_datagen_gib=2.0,
        peak_database_gib=0.0,
        transient_growth_gib=0.5,
        database_status=orchestrator.preflight_budget.DATABASE_STATUS_UNMEASURED,
    )
    attempted: list[tuple[str, str, float]] = []

    def base_runner(platform: str, benchmark: str, scale: float, **kwargs) -> CellResult:
        attempted.append((platform, benchmark, scale))
        raise AssertionError("predictive disk guard must run before the cell subprocess")

    runner = orchestrator._build_disk_floor_runner(
        base_runner,
        attempted_cells=[],
        watch_disk_floor=True,
        free_space_path=tmp_path,
        free_space_min_gib=3.0,
        budget_table={("duckdb", "tpch", 0.01): row},
        free_space_reader=lambda _path: 4.0,
        # No benchmark_runs_dir: the reuse probe has no root to resolve, so the
        # datagen reserve stands and the guard fires. Machine state under
        # BENCHBOX_OUTPUT_DIR cannot reach this test.
        benchmark_runs_dir=None,
    )

    with pytest.raises(orchestrator.DiskFloorAbort, match="predictive disk check failed"):
        runner("duckdb", "tpch", 0.01, log_dir=tmp_path)

    assert attempted == []


def _datagen_budget_row(benchmark: str) -> orchestrator.preflight_budget.DiskBudgetRow:
    return orchestrator.preflight_budget.DiskBudgetRow(
        platform="duckdb",
        benchmark=benchmark,
        scale_factor=0.01,
        peak_datagen_gib=2.0,
        peak_database_gib=0.0,
        transient_growth_gib=0.0,
        database_status=orchestrator.preflight_budget.DATABASE_STATUS_UNMEASURED,
    )


def _passed_cell(platform: str, benchmark: str, scale: float, tmp_path: Path) -> CellResult:
    return CellResult(
        platform=platform,
        benchmark=benchmark,
        scale=scale,
        status="passed",
        exit_code=0,
        elapsed_s=1.0,
        log_path=tmp_path / "cell.log",
        result_path=tmp_path / "result.json",
    )


def _complete_datagen(runs_dir: Path, benchmark: str, scale: float) -> Path:
    """Materialize a finished datagen cache the way a generator leaves one."""
    path = orchestrator._cell_datagen_dir(runs_dir, benchmark, scale)
    assert path is not None
    path.mkdir(parents=True, exist_ok=True)
    (path / "lineitem.tbl").write_text("data")
    (path / "_datagen_manifest.json").write_text("{}")
    return path


def test_cell_datagen_dir_matches_the_cells_own_output_resolution(tmp_path: Path):
    """UAT passes --output <runs>/datagen, which normalizes by REQUESTED benchmark.

    A custom --output takes precedence over DATA_SOURCE_BENCHMARK sharing, so
    read_primitives does not land in tpch's directory here even though it
    consumes TPC-H data through the CLI's shared-root path.
    """
    tpch = orchestrator._cell_datagen_dir(tmp_path, "tpch", 0.01)
    alias = orchestrator._cell_datagen_dir(tmp_path, "read_primitives", 0.01)

    assert tpch == tmp_path / "datagen" / "tpch_sf001"
    assert alias == tmp_path / "datagen" / "read_primitives_sf001"
    assert tpch != alias
    assert orchestrator._cell_datagen_dir(None, "tpch", 0.01) is None


def test_partial_datagen_cache_does_not_drop_the_reserve(tmp_path: Path):
    """A directory populated but missing its manifest is an unfinished generation."""
    partial = orchestrator._cell_datagen_dir(tmp_path, "tpch", 0.01)
    assert partial is not None
    partial.mkdir(parents=True)
    (partial / "lineitem.tbl.1").write_text("partial")

    assert orchestrator._datagen_cache_complete(partial) is False

    (partial / "_datagen_manifest.json").write_text("{}")
    assert orchestrator._datagen_cache_complete(partial) is True


def test_failed_cell_does_not_mark_its_datagen_available(tmp_path: Path):
    """A cell that died before finishing generation must not zero the next reserve."""
    cells = [
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
        _passed_cell("clickhouse", "tpch", 0.01, tmp_path),
    ]

    def base_runner(platform: str, benchmark: str, scale: float, **kwargs) -> CellResult:
        return cells.pop(0)

    free_readings = iter((3.5, 3.5, 2.5, 2.5))

    def free_space(_path) -> float:
        return next(free_readings, 2.5)

    runner = orchestrator._build_disk_floor_runner(
        base_runner,
        attempted_cells=[],
        watch_disk_floor=True,
        free_space_path=tmp_path,
        free_space_min_gib=1.0,
        budget_table={
            ("duckdb", "tpch", 0.01): _datagen_budget_row("tpch"),
            ("clickhouse", "tpch", 0.01): _datagen_budget_row("tpch"),
        },
        free_space_reader=free_space,
        benchmark_runs_dir=tmp_path,
    )

    runner("duckdb", "tpch", 0.01, log_dir=tmp_path)

    # The failed cell left no manifest, so the second cell must still reserve
    # 2.0 datagen + 1.0 floor against 2.5 GiB free and be refused. Treating the
    # dead cell as having produced the dataset would need only the floor.
    with pytest.raises(orchestrator.DiskFloorAbort, match="predictive disk check failed"):
        runner("clickhouse", "tpch", 0.01, log_dir=tmp_path)


def test_existing_datagen_cache_is_not_reserved_again(tmp_path: Path):
    """A rerun over a finished dataset must not reserve growth it will not create."""
    _complete_datagen(tmp_path, "tpch", 0.01)

    def base_runner(platform: str, benchmark: str, scale: float, **kwargs) -> CellResult:
        return _passed_cell(platform, benchmark, scale, tmp_path)

    runner = orchestrator._build_disk_floor_runner(
        base_runner,
        attempted_cells=[],
        watch_disk_floor=True,
        free_space_path=tmp_path,
        free_space_min_gib=1.0,
        budget_table={("duckdb", "tpch", 0.01): _datagen_budget_row("tpch")},
        free_space_reader=lambda _path: 1.5,
        benchmark_runs_dir=tmp_path,
    )

    # 1.5 GiB free is under the 2.0 datagen reserve but over the 1.0 floor: the
    # cell is refused unless the finished cache is recognised.
    assert runner("duckdb", "tpch", 0.01, log_dir=tmp_path).status == "passed"


def test_alias_workload_keeps_its_own_datagen_reserve(tmp_path: Path):
    """tpch data on disk must not zero read_primitives' reserve under --output.

    The two land in separate directories during a sweep, so the alias cell has
    its own generation still to do.
    """
    _complete_datagen(tmp_path, "tpch", 0.01)

    def base_runner(platform: str, benchmark: str, scale: float, **kwargs) -> CellResult:
        return _passed_cell(platform, benchmark, scale, tmp_path)

    runner = orchestrator._build_disk_floor_runner(
        base_runner,
        attempted_cells=[],
        watch_disk_floor=True,
        free_space_path=tmp_path,
        free_space_min_gib=1.0,
        budget_table={
            ("duckdb", "tpch", 0.01): _datagen_budget_row("tpch"),
            ("duckdb", "read_primitives", 0.01): _datagen_budget_row("read_primitives"),
        },
        free_space_reader=lambda _path: 1.5,
        benchmark_runs_dir=tmp_path,
    )

    # tpch reuses its finished cache and passes on 1.5 GiB.
    assert runner("duckdb", "tpch", 0.01, log_dir=tmp_path).status == "passed"

    # read_primitives writes elsewhere, so its 2.0 GiB datagen reserve stands.
    with pytest.raises(orchestrator.DiskFloorAbort, match="predictive disk check failed"):
        runner("duckdb", "read_primitives", 0.01, log_dir=tmp_path)


def test_datagen_probe_uses_the_sweeps_configured_root(tmp_path: Path):
    """The probe must read the sweep's root, not an ambient default."""
    configured = tmp_path / "configured"
    unrelated = tmp_path / "unrelated"
    _complete_datagen(unrelated, "tpch", 0.01)

    def base_runner(platform: str, benchmark: str, scale: float, **kwargs) -> CellResult:
        return _passed_cell(platform, benchmark, scale, tmp_path)

    runner = orchestrator._build_disk_floor_runner(
        base_runner,
        attempted_cells=[],
        watch_disk_floor=True,
        free_space_path=tmp_path,
        free_space_min_gib=1.0,
        budget_table={("duckdb", "tpch", 0.01): _datagen_budget_row("tpch")},
        free_space_reader=lambda _path: 1.5,
        benchmark_runs_dir=configured,
    )

    # The cache under the unrelated root must not suppress the reserve for the
    # empty configured root.
    with pytest.raises(orchestrator.DiskFloorAbort, match="predictive disk check failed"):
        runner("duckdb", "tpch", 0.01, log_dir=tmp_path)

    _complete_datagen(configured, "tpch", 0.01)
    assert runner("duckdb", "tpch", 0.01, log_dir=tmp_path).status == "passed"


def test_disk_floor_abort_emits_partial_artifacts(tmp_path: Path):
    """A mid-sweep disk-floor abort still emits the #691 abort-safe artifacts.

    Resume machinery (resume.json manifest) was retired -- see
    uat-resume-retirement-artifact-durability -- but the abort-safe
    provenance contract (cells.jsonl + partial report on abort) must
    keep working.
    """
    cfg = validate_config(
        {
            "name": "disk-floor-smoke",
            "phases": ["preflight", "execute"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )
    cell = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.01,
        status="passed",
        exit_code=0,
        elapsed_s=1.0,
        log_path=tmp_path / "cell.log",
        result_path=tmp_path / "result.json",
    )
    fake_preflight = type(
        "Preflight",
        (),
        {
            "aborted": False,
            "abort_reason": None,
            "warnings": (),
            "disk_budget_summary": None,
            "exit_code": lambda self: 0,
        },
    )()

    with (
        patch.object(orchestrator.preflight_phase, "run_preflight", return_value=fake_preflight),
        patch.object(orchestrator.exec_phase, "run_cell", return_value=cell),
        patch.object(orchestrator.exec_phase, "default_free_space_reader", return_value=100.0),
        patch.object(orchestrator.preflight_budget, "free_space_gib", return_value=1.0),
        patch.object(orchestrator.preflight_budget, "load_budget_table", return_value={}),
    ):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")

    assert result.aborted_phase == "execute"
    cells = [json.loads(line) for line in (tmp_path / "logs" / "cells.jsonl").read_text().splitlines()]
    assert cells[0]["platform"] == "duckdb"
    assert cells[0]["source_commit_sha"]
    partial_report = tmp_path / "logs" / "matrix_summary.partial.tsv"
    assert partial_report.exists()
    partial_text = partial_report.read_text(encoding="utf-8")
    assert "# run_status=ABORTED" in partial_text
    assert "abort_phase=execute" in partial_text


def test_disk_floor_abort_threads_real_compatibility_pruned_without_reenumerating(tmp_path: Path):
    """w5: abort artifacts on a mid-sweep disk-floor trip must use execute's
    actual enumeration -- threaded onto the DiskFloorAbort exception -- not a
    second independent re-enumeration (`_compatibility_pruned_for_config`)
    that could diverge from what execute actually used.
    """
    cfg = validate_config(
        {
            "name": "disk-floor-compat-smoke",
            "phases": ["execute"],
            "platforms": {"include": ["polars-df"]},
            "benchmarks": {"include": ["vector_search", "tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )
    cell = CellResult(
        platform="polars-df",
        benchmark="tpch",
        scale=0.01,
        status="passed",
        exit_code=0,
        elapsed_s=1.0,
        log_path=tmp_path / "cell.log",
        result_path=tmp_path / "result.json",
    )
    reenumerate_calls: list[object] = []
    real_compat_for_config = orchestrator._compatibility_pruned_for_config

    def spy_compat_for_config(config):
        reenumerate_calls.append(config)
        return real_compat_for_config(config)

    with (
        patch.object(orchestrator.exec_phase, "run_cell", return_value=cell),
        patch.object(orchestrator.exec_phase, "default_free_space_reader", return_value=100.0),
        patch.object(orchestrator.preflight_budget, "free_space_gib", return_value=1.0),
        patch.object(orchestrator, "_compatibility_pruned_for_config", side_effect=spy_compat_for_config),
    ):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")

    assert result.aborted_phase == "execute"
    assert reenumerate_calls == []  # the disk-floor abort path must not re-enumerate
    assert result.execute_outcome is not None
    assert result.execute_outcome.abort_kind == "disk_floor"

    pruned_rows = [
        json.loads(line)
        for line in (tmp_path / "logs" / "compatibility_pruned.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert pruned_rows[0]["benchmark"] == "vector_search"
    assert pruned_rows[0]["rule_id"] == "uat.compat.dataframe.sql_only_benchmark"


def test_execute_only_config_still_gets_disk_floor_watch(tmp_path: Path):
    """An execute-only config (no `preflight` in `phases:`) still aborts on low disk.

    Regression for uat-disk-gate-always-on w1/w4: the mid-sweep per-cell
    watch and platform-boundary check used to be keyed on
    `"preflight" in config.phases`, so a legitimate execute-only composition
    ran with zero disk gating. `free_space_min_gib` defaults to 5.0, so the
    gate is on by default; there is no `preflight` phase here to have
    established it.
    """
    cfg = validate_config(
        {
            "name": "execute-only-disk-smoke",
            "phases": ["execute"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )
    cell = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.01,
        status="passed",
        exit_code=0,
        elapsed_s=1.0,
        log_path=tmp_path / "cell.log",
        result_path=tmp_path / "result.json",
    )

    with (
        patch.object(orchestrator.exec_phase, "run_cell", return_value=cell),
        patch.object(orchestrator.exec_phase, "default_free_space_reader", return_value=100.0),
        patch.object(orchestrator.preflight_budget, "free_space_gib", return_value=1.0),
    ):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")

    assert result.aborted_phase == "execute"
    assert "free space" in (result.abort_reason or "")
    partial_report = tmp_path / "logs" / "matrix_summary.partial.tsv"
    assert partial_report.exists()
    assert "# run_status=ABORTED" in partial_report.read_text(encoding="utf-8")


def test_zero_floor_warns_loudly_and_flags_accounting_sidecar(tmp_path: Path, capsys):
    """`free_space_min_gib: 0` disables the gate but must say so loudly.

    Regression for uat-disk-gate-always-on w2: the explicit opt-out prints a
    `[disk-gate] DISABLED by config` warning at sweep start and records
    `disk_gate_disabled: true` in the `cells.jsonl.accounting.json` sidecar
    so the opt-out is visible without re-reading the YAML.
    """
    cfg = validate_config(
        {
            "name": "zero-floor-smoke",
            "phases": ["execute", "report"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "preflight": {"free_space_min_gib": 0},
        }
    )
    assert cfg.disk_gate_enabled is False
    cell = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.01,
        status="passed",
        exit_code=0,
        elapsed_s=1.0,
        log_path=tmp_path / "cell.log",
        result_path=tmp_path / "result.json",
    )
    fake_execute = type(
        "ExecuteOutcome",
        (),
        {
            "results": (cell,),
            "pruned": (),
            "skipped_unreachable": (),
            "aborted": False,
            "abort_reason": None,
            "exit_code": lambda self: 0,
        },
    )()

    with patch.object(orchestrator.exec_phase, "run_execute", return_value=fake_execute):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")

    assert result.aborted_phase is None
    assert "[disk-gate] DISABLED by config" in capsys.readouterr().err
    accounting = json.loads((tmp_path / "logs" / "cells.jsonl.accounting.json").read_text(encoding="utf-8"))
    assert accounting["disk_gate_disabled"] is True
    # The memory gate was left at its default, so it is NOT flagged.
    assert accounting["memory_gate_disabled"] is False


def test_zero_memory_floor_warns_loudly_and_flags_accounting_sidecar(tmp_path: Path, capsys):
    """`free_memory_min_gib: 0` disables the memory gate and must say so loudly.

    Mirrors the disk gate's opt-out disclosure exactly. Before this,
    `memory_gate_disabled_warning` existed but had no production caller at
    all -- the documented `[memory-gate] DISABLED by config` line was never
    printed and nothing in the evidence artifacts recorded that the gate had
    been switched off, so a sweep with the gate disabled was
    indistinguishable from one where it ran and passed.
    """
    cfg = validate_config(
        {
            "name": "zero-memory-floor-smoke",
            "phases": ["execute", "report"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "preflight": {"free_memory_min_gib": 0},
        }
    )
    assert cfg.memory_gate_enabled is False
    cell = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.01,
        status="passed",
        exit_code=0,
        elapsed_s=1.0,
        log_path=tmp_path / "cell.log",
        result_path=tmp_path / "result.json",
    )
    fake_execute = type(
        "ExecuteOutcome",
        (),
        {
            "results": (cell,),
            "pruned": (),
            "skipped_unreachable": (),
            "aborted": False,
            "abort_reason": None,
            "exit_code": lambda self: 0,
        },
    )()

    with patch.object(orchestrator.exec_phase, "run_execute", return_value=fake_execute):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")

    assert result.aborted_phase is None
    stderr = capsys.readouterr().err
    assert "[memory-gate] DISABLED by config" in stderr
    # The disk gate is at its default here, so only the memory warning fires.
    assert "[disk-gate] DISABLED by config" not in stderr
    accounting = json.loads((tmp_path / "logs" / "cells.jsonl.accounting.json").read_text(encoding="utf-8"))
    assert accounting["memory_gate_disabled"] is True
    assert accounting["disk_gate_disabled"] is False


def test_memory_floor_abort_records_memory_floor_abort_kind_in_gate_summary(tmp_path: Path):
    """An execute-phase memory-floor abort is machine-distinguishable from a
    disk-floor abort in the gate summary, not only by prose.

    `ExecuteOutcome.abort_kind="memory_floor"` was write-only before this:
    it reached no artifact, so every abort looked identical to a reader of
    `uat_gate_summary.json`.
    """
    cfg = validate_config(
        {
            "name": "memory-floor-abort",
            "phases": ["execute", "report"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )
    aborted_outcome = exec_phase.ExecuteOutcome(
        phase="execute",
        results=(),
        pruned=(),
        skipped_unreachable=(),
        startup_failed=(),
        compatibility_pruned=(),
        aborted=True,
        abort_reason="memory headroom gate failed: 0.07 GiB free < 2.00 GiB required",
        abort_kind="memory_floor",
    )

    with patch.object(orchestrator.exec_phase, "run_execute", return_value=aborted_outcome):
        orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")

    payload = json.loads((tmp_path / "logs" / "uat_gate_summary.json").read_text(encoding="utf-8"))
    assert payload["abort_kind"] == "memory_floor"
    assert payload["abort_phase"] == "execute"
    assert payload["verdict"] == "red"


def test_gate_summary_abort_kind_is_none_on_a_clean_sweep(tmp_path: Path):
    cfg = validate_config(
        {
            "name": "clean-abort-kind",
            "phases": ["execute", "report"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )
    cell = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.01,
        status="passed",
        exit_code=0,
        elapsed_s=1.0,
        log_path=tmp_path / "cell.log",
        result_path=tmp_path / "result.json",
    )
    fake_execute = type(
        "ExecuteOutcome",
        (),
        {
            "results": (cell,),
            "pruned": (),
            "skipped_unreachable": (),
            "aborted": False,
            "abort_reason": None,
            "exit_code": lambda self: 0,
        },
    )()

    with patch.object(orchestrator.exec_phase, "run_execute", return_value=fake_execute):
        orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")

    payload = json.loads((tmp_path / "logs" / "uat_gate_summary.json").read_text(encoding="utf-8"))
    assert payload["abort_kind"] is None


def test_execute_free_space_abort_emits_partial_artifacts(tmp_path: Path):
    """An execute-outcome-reported free-space abort still emits abort artifacts (resume machinery retired)."""
    cfg = validate_config(
        {
            "name": "free-space-smoke",
            "phases": ["preflight", "execute"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )
    cell = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.01,
        status="passed",
        exit_code=0,
        elapsed_s=1.0,
        log_path=tmp_path / "cell.log",
        result_path=tmp_path / "result.json",
    )
    fake_preflight = type(
        "Preflight",
        (),
        {
            "aborted": False,
            "abort_reason": None,
            "warnings": (),
            "disk_budget_summary": None,
            "exit_code": lambda self: 0,
        },
    )()
    fake_execute = type(
        "ExecuteOutcome",
        (),
        {
            "results": (cell,),
            "pruned": (),
            "skipped_unreachable": (),
            "aborted": True,
            "abort_reason": "free space 1.0 GiB < cutoff 5.0 GiB after Docker teardown",
        },
    )()

    with (
        patch.object(orchestrator.preflight_phase, "run_preflight", return_value=fake_preflight),
        patch.object(orchestrator.exec_phase, "run_execute", return_value=fake_execute),
    ):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")

    assert result.aborted_phase == "execute"
    cells = [json.loads(line) for line in (tmp_path / "logs" / "cells.jsonl").read_text().splitlines()]
    assert cells[0]["platform"] == "duckdb"
    assert (tmp_path / "logs" / "matrix_summary.partial.tsv").exists()


def test_two_sweeps_in_one_process_land_in_distinct_log_dirs(tmp_path: Path):
    """Two same-day sweeps (no log_dir_override) land in distinct default dirs.

    Regression test for w3 of uat-resume-retirement-artifact-durability: the
    default logs_dir_template was {date}-only, so a second same-day sweep of
    the same config silently overwrote the first run's mode="w" artifacts.
    """
    cfg = validate_config(
        {
            "name": "collision-smoke",
            "dry_run": True,
            "output": {"logs_dir_template": str(tmp_path / "uat_{date}_{time}")},
        }
    )
    # Each sweep calls _dt.datetime.now() twice: once for the log-dir stamp
    # and once for the gate summary's completed_at (uat-release-gate-enforcement w1).
    fixed_times = iter(
        [
            _dt.datetime(2026, 5, 5, 9, 0, 0),
            _dt.datetime(2026, 5, 5, 9, 0, 0, 500000),
            _dt.datetime(2026, 5, 5, 9, 0, 1),
            _dt.datetime(2026, 5, 5, 9, 0, 1, 500000),
        ]
    )
    with patch.object(orchestrator, "_dt") as mock_dt:
        mock_dt.datetime.now.side_effect = lambda: next(fixed_times)
        result1 = orchestrator.run_sweep(cfg)
        result2 = orchestrator.run_sweep(cfg)

    assert result1.log_dir != result2.log_dir


def _source_info() -> orchestrator.RunSourceInfo:
    return orchestrator.RunSourceInfo(commit_sha="deadbeef", commit_short_sha="deadbee", dirty=False)


def test_sweep_records_container_engine_identity_and_sidecar_field(tmp_path: Path):
    """uat-container-engine-routing w2: engine identity is logged at sweep
    start and threaded into the cells.jsonl accounting sidecar."""
    cfg = validate_config(
        {
            "name": "engine-identity",
            "phases": ["execute"],
            "platforms": {"include": []},
        }
    )
    with patch.object(docker_assets, "container_engine_identity", return_value=("mocker", "mocker 0.5.4")):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path)

    assert result.aborted_phase is None
    lifecycle_log = (tmp_path / "uat_lifecycle.log").read_text(encoding="utf-8")
    assert "[engine] resolved_container_cli=mocker version=mocker 0.5.4" in lifecycle_log

    sidecar = json.loads((tmp_path / "cells.jsonl.accounting.json").read_text(encoding="utf-8"))
    assert sidecar["container_engine"] == "mocker"


def test_sweep_records_engine_resolution_failure_without_aborting(tmp_path: Path):
    """A resolution failure (no engine binary at all) is logged, not fatal --
    a sweep with no Docker-managed platforms never needs one."""
    cfg = validate_config(
        {
            "name": "engine-identity-missing",
            "phases": ["execute"],
            "platforms": {"include": []},
        }
    )
    with patch.object(
        docker_assets,
        "container_engine_identity",
        side_effect=docker_assets.DockerAssetError("no engine on PATH"),
    ):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path)

    assert result.aborted_phase is None
    lifecycle_log = (tmp_path / "uat_lifecycle.log").read_text(encoding="utf-8")
    assert "[engine] resolution failed: no engine on PATH" in lifecycle_log
    sidecar = json.loads((tmp_path / "cells.jsonl.accounting.json").read_text(encoding="utf-8"))
    assert sidecar["container_engine"] is None


def test_write_cells_jsonl_persists_skipped_unreachable_sidecar(tmp_path: Path):
    cells_jsonl = tmp_path / "cells.jsonl"
    cells_io.write_cells_jsonl(
        cells_jsonl,
        (),
        source_info=_source_info(),
        skipped_unreachable_count=3,
    )
    sidecar = cells_jsonl.with_name("cells.jsonl.accounting.json")
    assert sidecar.exists()
    assert json.loads(sidecar.read_text(encoding="utf-8"))["skipped_unreachable_count"] == 3


def test_write_cells_jsonl_writes_cell_stream_before_accounting_sidecar(tmp_path: Path):
    """cells.jsonl, then its accounting sidecar, then the finalize marker (w1/w4).

    A crash between the row and sidecar writes must never leave a fresh sidecar
    beside a stale (or absent) cell stream -- see
    uat-resume-retirement-artifact-durability w4. The finalize marker is
    written strictly last (uat-sweep-durability-and-signal-teardown w1) so its
    presence guarantees both the rows and the sidecar preceded it. Record the
    path order `atomic_write_text` is called in and assert that ordering.
    """
    cells_jsonl = tmp_path / "cells.jsonl"
    written_paths: list[Path] = []
    real_atomic_write_text = cells_io.atomic_write_text

    def recording_atomic_write_text(path: Path, text: str) -> None:
        written_paths.append(path)
        real_atomic_write_text(path, text)

    with patch.object(cells_io, "atomic_write_text", side_effect=recording_atomic_write_text):
        cells_io.write_cells_jsonl(
            cells_jsonl,
            (),
            source_info=_source_info(),
            skipped_unreachable_count=1,
        )

    sidecar = cells_jsonl.with_name("cells.jsonl.accounting.json")
    finalized = cells_jsonl.with_name("cells.jsonl.finalized")
    assert written_paths == [cells_jsonl, sidecar, finalized]


def test_abort_artifacts_thread_skipped_unreachable_when_outcome_missing(tmp_path: Path):
    cfg = validate_config(
        {
            "name": "abort-accounting",
            "phases": ["execute"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    orchestrator._emit_abort_artifacts(
        config=cfg,
        log_dir=log_dir,
        attempted=(),
        execute_outcome=None,
        source_info=_source_info(),
        aborted_phase="execute",
        abort_reason="free space 1.0 GiB < cutoff 5.0 GiB",
        skipped_unreachable_count=2,
    )
    # The abort report must reflect the unreachable cells skipped before the
    # disk-floor trip, not the zero implied by execute_outcome=None.
    partial = log_dir / "matrix_summary.partial.tsv"
    text = partial.read_text(encoding="utf-8")
    assert "unreachable=2" in text
    assert "# UNREACHABLE_CELLS=2 release_gate_attention=required" in text
    # And the sidecar carries the count for report regeneration.
    sidecar = (log_dir / "cells.jsonl").with_name("cells.jsonl.accounting.json")
    assert json.loads(sidecar.read_text(encoding="utf-8"))["skipped_unreachable_count"] == 2


def test_disk_floor_abort_carries_skipped_unreachable_count():
    cfg = validate_config(
        {
            "name": "disk-floor-annotate",
            "platforms": {"include": ["duckdb", "clickhouse-server"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )

    def runner(platform, benchmark, scale, **kwargs):
        raise orchestrator.DiskFloorAbort("free space 1.0 GiB < cutoff 5.0 GiB")

    # duckdb is processed first and recorded as skipped-unreachable; the
    # reachable clickhouse-server stack then trips the disk-floor runner. The
    # raised abort must carry the already-accumulated unreachable count (1).
    with (
        patch.object(exec_phase, "platform_is_reachable", side_effect=lambda p, **_: p != "duckdb"),
        patch.object(exec_phase, "probe_platform_reachability", side_effect=lambda p, **_: p != "duckdb"),
    ):
        with pytest.raises(orchestrator.DiskFloorAbort) as excinfo:
            exec_phase.run_execute(
                cfg,
                log_dir=Path("/tmp"),
                databases_root=Path("/tmp/databases"),
                runner=runner,
            )
    assert getattr(excinfo.value, "skipped_unreachable_count", None) == 1


def _startup_fail_clickhouse_docker(argv, **kwargs):
    """Fake docker runner: clickhouse compose-up fails, everything else succeeds."""
    action = docker_verb(argv)
    compose_file = argv[argv.index("-f") + 1] if "-f" in argv else ""
    if action == "up" and compose_path_ends_with(compose_file, "docker", "clickhouse", "docker-compose.yml"):
        return docker_assets.DockerCommandResult(tuple(argv), 1, "", "compose up failed")
    return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")


def test_disk_floor_abort_carries_startup_failed_count(tmp_path: Path):
    """Mirror of test_disk_floor_abort_carries_skipped_unreachable_count for w3's counter.

    clickhouse-server is processed first: its managed compose-up fails, so
    its cells accumulate in `startup_failed` (the #700 advance path). The
    non-Docker duckdb platform then trips the disk-floor runner. The raised
    abort must carry the already-accumulated startup_failed count (1) via
    `_annotate_disk_floor_abort`.
    """
    cfg = validate_config(
        {
            "name": "disk-floor-annotate-startup-failed",
            "platforms": {"include": ["clickhouse-server", "duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )

    def runner(platform, benchmark, scale, **kwargs):
        raise orchestrator.DiskFloorAbort("free space 1.0 GiB < cutoff 5.0 GiB")

    with platform_reachability(True):
        with pytest.raises(orchestrator.DiskFloorAbort) as excinfo:
            exec_phase.run_execute(
                cfg,
                log_dir=tmp_path,
                databases_root=tmp_path / "databases",
                runner=runner,
                docker_runner=_startup_fail_clickhouse_docker,
            )
    assert getattr(excinfo.value, "startup_failed_count", None) == 1


def test_disk_floor_abort_threads_startup_failed_count_into_sidecar_and_partial_report(tmp_path: Path):
    """Orchestrator-level: startup_failed survives the synthesized-outcome disk-floor path.

    run_sweep's DiskFloorAbort handler synthesizes an ExecuteOutcome with an
    EMPTY startup_failed tuple (the Cell objects are lost crossing the
    exception boundary), so the abort artifacts must be fed from the
    exc-annotated `startup_failed_count` instead. Assert the durable
    accounting sidecar and the partial report TSV both carry the real count.
    """
    cfg = validate_config(
        {
            "name": "disk-floor-startup-failed-artifacts",
            "phases": ["execute"],
            "platforms": {"include": ["clickhouse-server", "duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )
    cell = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.01,
        status="passed",
        exit_code=0,
        elapsed_s=1.0,
        log_path=tmp_path / "cell.log",
        result_path=tmp_path / "result.json",
    )

    with (
        platform_reachability(True),
        patch.object(exec_phase.docker_assets, "run_docker_command", side_effect=_startup_fail_clickhouse_docker),
        patch.object(orchestrator.exec_phase, "run_cell", return_value=cell),
        patch.object(orchestrator.exec_phase, "default_free_space_reader", return_value=100.0),
        patch.object(orchestrator.preflight_budget, "free_space_gib", return_value=1.0),
        patch.object(orchestrator.preflight_budget, "load_budget_table", return_value={}),
    ):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")

    assert result.aborted_phase == "execute"
    assert result.execute_outcome is not None
    assert result.execute_outcome.abort_kind == "disk_floor"
    # The durable sidecar carries the exc-annotated count, not the
    # synthesized outcome's empty tuple.
    accounting = json.loads((tmp_path / "logs" / "cells.jsonl.accounting.json").read_text(encoding="utf-8"))
    assert accounting["startup_failed_count"] == 1
    # And the partial report accounts for it (components precede the total).
    partial_text = (tmp_path / "logs" / "matrix_summary.partial.tsv").read_text(encoding="utf-8")
    assert "startup_failed=1" in partial_text
    assert "attempted=1 skipped=0 unreachable=0 startup_failed=1 died_mid_platform=0 total_defined=2" in partial_text


# ---------------------------------------------------------------------------
# cells_io.update_accounting_sidecar unit coverage (review REQUIRED 2).
# ---------------------------------------------------------------------------


def test_update_accounting_sidecar_returns_false_and_creates_no_file_without_sidecar(tmp_path: Path):
    cells_jsonl = tmp_path / "cells.jsonl"

    recorded = cells_io.update_accounting_sidecar(cells_jsonl, explorer_smoke_status="skipped_no_node")

    assert recorded is False
    # No sidecar is fabricated: presence implies confirmed execute-derived
    # counts, which a patch-only write could not provide.
    assert not cells_jsonl.with_name("cells.jsonl.accounting.json").exists()


def test_update_accounting_sidecar_preserves_existing_counts(tmp_path: Path):
    cells_jsonl = tmp_path / "cells.jsonl"
    cells_io.write_cells_jsonl(
        cells_jsonl,
        (),
        source_info=_source_info(),
        skipped_unreachable_count=3,
        startup_failed_count=2,
    )

    recorded = cells_io.update_accounting_sidecar(cells_jsonl, explorer_smoke_status="skipped_no_node")

    assert recorded is True
    payload = json.loads(cells_jsonl.with_name("cells.jsonl.accounting.json").read_text(encoding="utf-8"))
    assert payload == {
        "skipped_unreachable_count": 3,
        "startup_failed_count": 2,
        "died_mid_platform_count": 0,
        "compatibility_pruned_count": 0,
        "early_stop_pruned_count": 0,
        "registry_pruned_count": 0,
        "disk_gate_disabled": False,
        "memory_gate_disabled": False,
        "container_engine": None,
        "explorer_smoke_status": "skipped_no_node",
    }


def test_update_accounting_sidecar_returns_false_on_corrupt_sidecar_without_clobbering(tmp_path: Path):
    cells_jsonl = tmp_path / "cells.jsonl"
    sidecar = cells_jsonl.with_name("cells.jsonl.accounting.json")
    sidecar.write_text("{not valid json", encoding="utf-8")

    recorded = cells_io.update_accounting_sidecar(cells_jsonl, explorer_smoke_status="skipped_no_node")

    assert recorded is False
    # The corrupt sidecar is left untouched for post-mortem inspection, not
    # overwritten with a fabricated payload.
    assert sidecar.read_text(encoding="utf-8") == "{not valid json"


# ---------------------------------------------------------------------------
# uat-release-gate-enforcement w1: every sweep writes uat_gate_summary.json.
# ---------------------------------------------------------------------------


def _read_gate_summary(log_dir: Path) -> dict:
    return json.loads((log_dir / "uat_gate_summary.json").read_text(encoding="utf-8"))


def test_dry_run_sweep_writes_gate_summary_with_dry_run_verdict(tmp_path: Path):
    """Dry-run sweeps still write the summary; the verdict marks them as non-evidence."""
    cfg = validate_config({"name": "gate-dry", "dry_run": True, "phases": ["preflight", "execute", "report"]})

    orchestrator.run_sweep(cfg, log_dir_override=tmp_path)

    payload = _read_gate_summary(tmp_path)
    assert payload["version"] == 1
    assert payload["verdict"] == "dry_run"
    assert payload["dry_run"] is True
    assert payload["config_name"] == "gate-dry"
    assert payload["phase_exit_codes"] == {"preflight": 0, "execute": 0, "report": 0}
    assert payload["completed_at"]
    assert payload["source_commit_sha"]


def test_gate_summary_completed_at_is_offset_aware(tmp_path: Path):
    """#1162 review: completed_at must carry an explicit UTC offset, not a
    naive local timestamp -- release_readiness_check.py evaluates the
    committed evidence in a different process (CI), possibly in a different
    timezone than the operator who ran the sweep. A naive timestamp there
    gets reinterpreted against the *evaluating* process's local timezone,
    which can misjudge freshness near the max-age cutoff.
    """
    cfg = validate_config({"name": "gate-tz", "dry_run": True, "phases": ["preflight", "execute", "report"]})

    orchestrator.run_sweep(cfg, log_dir_override=tmp_path)

    payload = _read_gate_summary(tmp_path)
    completed_at = _dt.datetime.fromisoformat(payload["completed_at"])
    assert completed_at.tzinfo is not None


def test_green_sweep_writes_green_gate_summary_with_accounting(tmp_path: Path):
    cfg = validate_config(
        {
            "name": "gate-green",
            "phases": ["execute", "report"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "report": {"cross_scale_coverage_min_pairs": 1},
        }
    )
    cell = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.01,
        status="passed",
        exit_code=0,
        elapsed_s=1.0,
        log_path=tmp_path / "cell.log",
        result_path=tmp_path / "result.json",
    )
    fake_execute = type(
        "ExecuteOutcome",
        (),
        {
            "results": (cell,),
            "pruned": (),
            "skipped_unreachable": (),
            "startup_failed": (),
            "compatibility_pruned": (),
            "aborted": False,
            "abort_reason": None,
            "exit_code": lambda self: 0,
        },
    )()
    with patch.object(orchestrator.exec_phase, "run_execute", return_value=fake_execute):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path)

    assert result.exit_code() == 0
    payload = _read_gate_summary(tmp_path)
    assert payload["verdict"] == "green"
    assert payload["aborted"] is False
    assert payload["accounting"]["passed"] == 1
    assert payload["accounting"]["attempted"] == 1
    assert payload["accounting"]["total_defined"] == 1
    assert payload["cross_scale_clean_pairs"] == 1
    assert payload["cross_scale_floor"] == 1
    assert payload["cross_scale_floor_breached"] is False
    assert payload["unreachable_is_estimated"] is False
    assert payload["explorer_smoke_status"] == "not_run"


def test_green_sweep_with_unvalidated_cells_reports_unvalidated_count_not_zero(tmp_path: Path):
    """Regression: uat_gate_summary.json must not silently disagree with matrix_summary.tsv.

    tests.uat.phases.report.write_report already rolls an unvalidated DataFrame
    cell into ReportSummary.unvalidated_count and the TSV's
    `# UNVALIDATED_CELLS=N` footer; this pins that
    orchestrator._accounting_for_gate_summary actually copies that count into
    PhaseAccounting.unvalidated rather than leaving the gate summary --
    the one artifact a release gate reads by machine, not by a human scanning
    rows -- silently asserting 0. The verdict must still be green: unvalidated
    is not a UAT cell failure.
    """
    cfg = validate_config(
        {
            "name": "gate-green-unvalidated",
            "phases": ["execute", "report"],
            "platforms": {"include": ["duckdb", "polars-df"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "report": {"cross_scale_coverage_min_pairs": 1},
        }
    )
    clean_cell = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.01,
        status="passed",
        exit_code=0,
        elapsed_s=1.0,
        log_path=tmp_path / "duckdb.log",
        result_path=tmp_path / "duckdb_result.json",
        submit_terminal_state="submittable",
    )
    unvalidated_cell = CellResult(
        platform="polars-df",
        benchmark="tpch",
        scale=0.01,
        status="passed",
        exit_code=0,
        elapsed_s=1.0,
        log_path=tmp_path / "polars_df.log",
        result_path=tmp_path / "polars_df_result.json",
        submit_terminal_state="unvalidated",
    )
    fake_execute = type(
        "ExecuteOutcome",
        (),
        {
            "results": (clean_cell, unvalidated_cell),
            "pruned": (),
            "skipped_unreachable": (),
            "startup_failed": (),
            "compatibility_pruned": (),
            "aborted": False,
            "abort_reason": None,
            "exit_code": lambda self: 0,
        },
    )()
    with patch.object(orchestrator.exec_phase, "run_execute", return_value=fake_execute):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path)

    assert result.exit_code() == 0
    payload = _read_gate_summary(tmp_path)
    assert payload["verdict"] == "green"
    assert payload["accounting"]["passed"] == 2
    assert payload["accounting"]["attempted"] == 2
    # The one assertion this test exists for: not 0.
    assert payload["accounting"]["unvalidated"] == 1

    tsv_text = (tmp_path / "matrix_summary.tsv").read_text(encoding="utf-8")
    assert "# UNVALIDATED_CELLS=1 release_gate_attention=required" in tsv_text


def test_failed_cell_sweep_writes_red_gate_summary(tmp_path: Path):
    cfg = validate_config(
        {
            "name": "gate-red",
            "phases": ["execute", "report"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )
    cell = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.01,
        status="failed",
        exit_code=1,
        elapsed_s=1.0,
        log_path=tmp_path / "cell.log",
        result_path=None,
    )
    fake_execute = type(
        "ExecuteOutcome",
        (),
        {
            "results": (cell,),
            "pruned": (),
            "skipped_unreachable": (),
            "startup_failed": (),
            "compatibility_pruned": (),
            "aborted": False,
            "abort_reason": None,
            "exit_code": lambda self: 1,
        },
    )()
    with patch.object(orchestrator.exec_phase, "run_execute", return_value=fake_execute):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path)

    assert result.exit_code() == 1
    payload = _read_gate_summary(tmp_path)
    assert payload["verdict"] == "red"
    assert payload["accounting"]["failed"] == 1
    assert payload["phase_exit_codes"]["execute"] == 1


def test_aborted_sweep_writes_red_gate_summary_with_abort_fields(tmp_path: Path):
    """An abort path also lands in the gate summary (partial-report accounting)."""
    cfg = validate_config({"name": "gate-abort", "phases": ["report"]})

    result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path)

    assert result.aborted_phase == "report"
    payload = _read_gate_summary(tmp_path)
    assert payload["verdict"] == "red"
    assert payload["aborted"] is True
    assert payload["abort_phase"] == "report"
    assert "execute phase" in payload["abort_reason"]


def test_derive_verdict_matrix():
    from tests.uat import gate_summary

    assert gate_summary.derive_verdict(dry_run=True, aborted=False, phase_exit_codes={"execute": 0}) == "dry_run"
    assert gate_summary.derive_verdict(dry_run=False, aborted=True, phase_exit_codes={}) == "red"
    assert gate_summary.derive_verdict(dry_run=False, aborted=False, phase_exit_codes={"execute": 1}) == "red"
    assert (
        gate_summary.derive_verdict(dry_run=False, aborted=False, phase_exit_codes={"execute": 0, "report": 0})
        == "green"
    )


def test_gate_summary_round_trips_and_ignores_unknown_keys(tmp_path: Path):
    """Forward compat: a later summary with additive fields must still read."""
    from tests.uat import gate_summary

    cfg = validate_config({"name": "gate-rt", "dry_run": True, "phases": ["execute"]})
    orchestrator.run_sweep(cfg, log_dir_override=tmp_path)

    path = tmp_path / "uat_gate_summary.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["a_future_field"] = "ignored"
    payload["accounting"]["a_future_count"] = 7
    path.write_text(json.dumps(payload), encoding="utf-8")

    summary = gate_summary.read_gate_summary(path)
    assert summary.config_name == "gate-rt"
    assert summary.verdict == "dry_run"


# ---------------------------------------------------------------------------
# uat-release-gate-enforcement w3: combined release-gate evidence aggregation.
# ---------------------------------------------------------------------------


def _stage_summary(name: str, completed_at: str, **overrides):
    from tests.uat import gate_summary

    kwargs = {
        "config_name": name,
        "source_commit_sha": "abc123",
        "source_dirty": False,
        "container_engine": "docker",
        "completed_at": completed_at,
        "dry_run": False,
        "aborted": False,
        "abort_phase": None,
        "abort_reason": None,
        "phase_exit_codes": {"execute": 0, "validate": 0, "explorer_smoke": 0, "report": 0},
        "accounting": gate_summary.PhaseAccounting(attempted=5, passed=5, total_defined=5),
        "unreachable_is_estimated": False,
        "validator_clean_rate": 1.0,
        "validator_clean_rate_floor": 1.0,
        "validator_floor_breached": False,
        "cross_scale_clean_pairs": 10,
        "cross_scale_floor": 8,
        "cross_scale_floor_breached": False,
        "explorer_smoke_status": "ran",
        "artifact_digests": {
            "cells_jsonl": "a" * 64,
            "accounting_sidecar": "b" * 64,
            "lifecycle_log": "c" * 64,
        },
        "verdict": "green",
    }
    kwargs.update(overrides)
    return gate_summary.GateSummary(**kwargs)


def test_combined_evidence_green_when_all_stages_clean():
    from tests.uat import gate_summary

    stages = [
        _stage_summary(gate_summary.EXPECTED_RELEASE_GATE_STAGES[0], "2026-07-10T10:00:00"),
        _stage_summary(gate_summary.EXPECTED_RELEASE_GATE_STAGES[1], "2026-07-10T12:00:00"),
        _stage_summary(gate_summary.EXPECTED_RELEASE_GATE_STAGES[2], "2026-07-10T14:00:00"),
    ]
    evidence = gate_summary.build_combined_evidence(
        stages, ordering_violations=(), generated_at=_dt.datetime(2026, 7, 10, 15)
    )
    assert evidence.verdict == "green"
    assert evidence.reasons == ()
    assert evidence.source_commit_sha == "abc123"
    assert evidence.completed_at == "2026-07-10T10:00:00"
    assert evidence.stage_verdicts == dict.fromkeys(gate_summary.EXPECTED_RELEASE_GATE_STAGES, "green")


@pytest.mark.parametrize(
    ("overrides", "reason_fragment"),
    [
        ({"verdict": "red"}, "not green"),
        ({"dry_run": True, "verdict": "dry_run"}, "dry-run summary"),
        ({"unreachable_is_estimated": True}, "sidecar missing"),
        ({"explorer_smoke_status": "skipped_no_node"}, "explorer_smoke but it did not run"),
        ({"source_dirty": True}, "dirty source tree"),
        ({"source_commit_sha": "other"}, "source_commit_sha differs"),
    ],
)
def test_combined_evidence_red_on_each_hold_condition(overrides: dict, reason_fragment: str):
    from tests.uat import gate_summary

    stages = [
        _stage_summary(gate_summary.EXPECTED_RELEASE_GATE_STAGES[0], "2026-07-10T10:00:00"),
        _stage_summary(gate_summary.EXPECTED_RELEASE_GATE_STAGES[1], "2026-07-10T12:00:00", **overrides),
        _stage_summary(gate_summary.EXPECTED_RELEASE_GATE_STAGES[2], "2026-07-10T14:00:00"),
    ]
    evidence = gate_summary.build_combined_evidence(
        stages, ordering_violations=(), generated_at=_dt.datetime(2026, 7, 10, 15)
    )
    assert evidence.verdict == "red"
    assert any(reason_fragment in reason for reason in evidence.reasons), evidence.reasons


def test_combined_evidence_red_on_wrong_stage_count_and_ordering_violation():
    from tests.uat import gate_summary

    stages = [
        _stage_summary(gate_summary.EXPECTED_RELEASE_GATE_STAGES[0], "2026-07-10T10:00:00"),
        _stage_summary(gate_summary.EXPECTED_RELEASE_GATE_STAGES[1], "2026-07-10T12:00:00"),
    ]
    evidence = gate_summary.build_combined_evidence(
        stages,
        ordering_violations=("stage1 boundary: Docker stack 'x' started early",),
        generated_at=_dt.datetime(2026, 7, 10, 15),
    )
    assert evidence.verdict == "red"
    assert any("expected 3" in reason for reason in evidence.reasons)
    assert any("started early" in reason for reason in evidence.reasons)


def test_explorer_smoke_stage_not_flagged_when_not_configured():
    """A stage whose phases list never included explorer_smoke is not held for skipping it."""
    from tests.uat import gate_summary

    stages = [
        _stage_summary(
            gate_summary.EXPECTED_RELEASE_GATE_STAGES[0],
            "2026-07-10T10:00:00",
            phase_exit_codes={"execute": 0, "report": 0},
            explorer_smoke_status="not_run",
        ),
        _stage_summary(gate_summary.EXPECTED_RELEASE_GATE_STAGES[1], "2026-07-10T12:00:00"),
        _stage_summary(gate_summary.EXPECTED_RELEASE_GATE_STAGES[2], "2026-07-10T14:00:00"),
    ]
    evidence = gate_summary.build_combined_evidence(
        stages, ordering_violations=(), generated_at=_dt.datetime(2026, 7, 10, 15)
    )
    assert evidence.verdict == "green"


def test_combined_evidence_red_when_stage_names_are_not_the_expected_set():
    """R1(a): three green summaries from the WRONG configs (or the same config
    thrice) must never mint release evidence."""
    from tests.uat import gate_summary

    same_stage_thrice = [
        _stage_summary(gate_summary.EXPECTED_RELEASE_GATE_STAGES[0], "2026-07-10T10:00:00"),
        _stage_summary(gate_summary.EXPECTED_RELEASE_GATE_STAGES[0], "2026-07-10T12:00:00"),
        _stage_summary(gate_summary.EXPECTED_RELEASE_GATE_STAGES[0], "2026-07-10T14:00:00"),
    ]
    evidence = gate_summary.build_combined_evidence(
        same_stage_thrice, ordering_violations=(), generated_at=_dt.datetime(2026, 7, 10, 15)
    )
    assert evidence.verdict == "red"
    assert any("do not match the expected" in reason for reason in evidence.reasons), evidence.reasons

    hollow_substitute = [
        _stage_summary(gate_summary.EXPECTED_RELEASE_GATE_STAGES[0], "2026-07-10T10:00:00"),
        _stage_summary("my-adhoc-config", "2026-07-10T12:00:00"),
        _stage_summary(gate_summary.EXPECTED_RELEASE_GATE_STAGES[2], "2026-07-10T14:00:00"),
    ]
    evidence = gate_summary.build_combined_evidence(
        hollow_substitute, ordering_violations=(), generated_at=_dt.datetime(2026, 7, 10, 15)
    )
    assert evidence.verdict == "red"
    assert any("do not match the expected" in reason for reason in evidence.reasons), evidence.reasons


def test_combined_evidence_red_when_a_stage_has_no_floor_gates():
    """R1(b): a stage whose config never armed the validator/cross-scale floors
    is hollow evidence even if every phase exited 0."""
    from tests.uat import gate_summary

    stages = [
        _stage_summary(gate_summary.EXPECTED_RELEASE_GATE_STAGES[0], "2026-07-10T10:00:00"),
        _stage_summary(
            gate_summary.EXPECTED_RELEASE_GATE_STAGES[1],
            "2026-07-10T12:00:00",
            validator_clean_rate_floor=None,
            cross_scale_floor=None,
        ),
        _stage_summary(gate_summary.EXPECTED_RELEASE_GATE_STAGES[2], "2026-07-10T14:00:00"),
    ]
    evidence = gate_summary.build_combined_evidence(
        stages, ordering_violations=(), generated_at=_dt.datetime(2026, 7, 10, 15)
    )
    assert evidence.verdict == "red"
    assert any("floor gates were not configured" in reason for reason in evidence.reasons), evidence.reasons


def test_mid_platform_death_surfaces_in_every_machine_readable_rollup(tmp_path: Path):
    """The threading test this batch keeps needing: a source change whose
    consumers stay blind is the recurring failure mode here (cf. the
    `unvalidated` accounting fix). A stack dying mid-platform must be
    visible in ALL THREE roll-up surfaces built from the same sweep, not
    just the ExecuteOutcome that produced it:

      - matrix_summary.tsv's footer (human-readable)
      - uat_gate_summary.json's accounting block (what a release gate reads)
      - cells.jsonl's accounting sidecar (what `uat report` regenerates from)
    """
    cfg = validate_config(
        {
            "name": "mid-platform-death-rollup",
            "phases": ["execute", "report"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )
    ran = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.01,
        status="passed",
        exit_code=0,
        elapsed_s=1.0,
        log_path=tmp_path / "cell.log",
        result_path=tmp_path / "result.json",
    )
    died = tuple(
        exec_phase.Cell(platform="clickhouse-server", benchmark="tpch", scale=scale) for scale in (0.1, 1.0, 10.0)
    )
    outcome = exec_phase.ExecuteOutcome(
        phase="execute",
        results=(ran,),
        pruned=(),
        skipped_unreachable=(),
        startup_failed=(),
        died_mid_platform=died,
        compatibility_pruned=(),
    )

    with patch.object(orchestrator.exec_phase, "run_execute", return_value=outcome):
        result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")

    # 1. matrix_summary.tsv footer.
    tsv = (tmp_path / "logs" / "matrix_summary.tsv").read_text(encoding="utf-8")
    assert "died_mid_platform=3" in tsv
    assert "# DIED_MID_PLATFORM_CELLS=3 release_gate_attention=required" in tsv

    # 2. uat_gate_summary.json accounting.
    gate = json.loads((tmp_path / "logs" / "uat_gate_summary.json").read_text(encoding="utf-8"))
    assert gate["accounting"]["died_mid_platform"] == 3
    assert gate["accounting"]["total_defined"] == 4
    # A lost platform makes the stage red, not green.
    assert gate["verdict"] == "red"

    # 3. cells.jsonl accounting sidecar (the regeneration input).
    accounting = json.loads((tmp_path / "logs" / "cells.jsonl.accounting.json").read_text(encoding="utf-8"))
    assert accounting["died_mid_platform_count"] == 3
    # Disjoint from both neighbours -- not laundered into either.
    assert accounting["startup_failed_count"] == 0
    assert accounting["skipped_unreachable_count"] == 0

    assert result.exit_code() != 0


def test_report_cli_json_surfaces_died_mid_platform_from_the_sidecar(tmp_path: Path, capsys):
    """`uat report --json` is the fourth reader, and it rebuilds from the
    sidecar rather than from the live outcome -- so it needs its own wiring
    or a regenerated report silently loses the count."""
    cells_jsonl = tmp_path / "cells.jsonl"
    cell = CellResult(
        platform="duckdb",
        benchmark="tpch",
        scale=0.01,
        status="passed",
        exit_code=0,
        elapsed_s=1.0,
        log_path=tmp_path / "cell.log",
        result_path=None,
    )
    cells_io.write_cells_jsonl(
        cells_jsonl,
        (cell,),
        source_info=_source_info(),
        died_mid_platform_count=171,
    )

    exit_code = uat_cli.main(
        [
            "report",
            "--cells-jsonl",
            str(cells_jsonl),
            "--output-tsv",
            str(tmp_path / "matrix_summary.tsv"),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["died_mid_platform"] == 171
    assert payload["total_defined"] == 172
    assert exit_code == 1
