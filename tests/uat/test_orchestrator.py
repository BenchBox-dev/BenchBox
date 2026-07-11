"""Fast-test coverage for tests/uat/orchestrator.py."""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.uat import orchestrator
from tests.uat.config import validate_config
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
    _write_cells_jsonl, so a stream-count failure left durable artifacts
    saying only failed/exit 1 with no explanation.
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

    orchestrator._write_cells_jsonl(tmp_path / "cells.jsonl", (cell,), source_info=source_info)

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

    orchestrator._write_cells_jsonl(tmp_path / "cells.jsonl", (timed_out_cell,), source_info=source_info)
    orchestrator._write_cells_jsonl(tmp_path / "cells.jsonl", (timed_out_cell,), source_info=source_info)

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
        patch.object(orchestrator.preflight_phase, "free_space_gib", return_value=1.0),
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
        patch.object(orchestrator.preflight_phase, "free_space_gib", return_value=1.0),
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
    fixed_times = iter(
        [
            _dt.datetime(2026, 5, 5, 9, 0, 0),
            _dt.datetime(2026, 5, 5, 9, 0, 1),
        ]
    )
    with patch.object(orchestrator, "_dt") as mock_dt:
        mock_dt.datetime.now.side_effect = lambda: next(fixed_times)
        result1 = orchestrator.run_sweep(cfg)
        result2 = orchestrator.run_sweep(cfg)

    assert result1.log_dir != result2.log_dir


def _source_info() -> orchestrator.RunSourceInfo:
    return orchestrator.RunSourceInfo(commit_sha="deadbeef", commit_short_sha="deadbee", dirty=False)


def test_write_cells_jsonl_persists_skipped_unreachable_sidecar(tmp_path: Path):
    cells_jsonl = tmp_path / "cells.jsonl"
    orchestrator._write_cells_jsonl(
        cells_jsonl,
        (),
        source_info=_source_info(),
        skipped_unreachable_count=3,
    )
    sidecar = cells_jsonl.with_name("cells.jsonl.accounting.json")
    assert sidecar.exists()
    assert json.loads(sidecar.read_text(encoding="utf-8"))["skipped_unreachable_count"] == 3


def test_write_cells_jsonl_writes_cell_stream_before_accounting_sidecar(tmp_path: Path):
    """cells.jsonl must land before its accounting sidecar (w4).

    A crash between the two writes must never leave a fresh sidecar beside a
    stale (or absent) cell stream -- see
    uat-resume-retirement-artifact-durability w4. Record the path order
    `atomic_write_text` is called in and assert cells.jsonl comes first.
    """
    cells_jsonl = tmp_path / "cells.jsonl"
    written_paths: list[Path] = []
    real_atomic_write_text = orchestrator.report_phase.atomic_write_text

    def recording_atomic_write_text(path: Path, text: str) -> None:
        written_paths.append(path)
        real_atomic_write_text(path, text)

    with patch.object(orchestrator.report_phase, "atomic_write_text", side_effect=recording_atomic_write_text):
        orchestrator._write_cells_jsonl(
            cells_jsonl,
            (),
            source_info=_source_info(),
            skipped_unreachable_count=1,
        )

    sidecar = cells_jsonl.with_name("cells.jsonl.accounting.json")
    assert written_paths == [cells_jsonl, sidecar]


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
    with patch.object(exec_phase, "platform_is_reachable", side_effect=lambda p, **_: p != "duckdb"):
        with pytest.raises(orchestrator.DiskFloorAbort) as excinfo:
            exec_phase.run_execute(
                cfg,
                log_dir=Path("/tmp"),
                databases_root=Path("/tmp/databases"),
                runner=runner,
            )
    assert getattr(excinfo.value, "skipped_unreachable_count", None) == 1
