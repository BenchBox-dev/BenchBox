"""Fast-test coverage for tests/uat/orchestrator.py."""

from __future__ import annotations

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


def test_resume_manifest_written_on_disk_floor_abort(tmp_path: Path):
    cfg = validate_config(
        {
            "name": "resume-smoke",
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
    manifest = tmp_path / "logs" / "resume.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["aborted_phase"] == "execute"
    assert payload["source"]["commit_sha"]
    assert payload["attempted"][0]["cell_key"] == "duckdb|tpch|0.01"
    cells = [json.loads(line) for line in (tmp_path / "logs" / "cells.jsonl").read_text().splitlines()]
    assert cells[0]["source_commit_sha"] == payload["source"]["commit_sha"]
    partial_report = tmp_path / "logs" / "matrix_summary.partial.tsv"
    assert partial_report.exists()
    partial_text = partial_report.read_text(encoding="utf-8")
    assert "# run_status=ABORTED" in partial_text
    assert "abort_phase=execute" in partial_text


def test_resume_manifest_written_on_execute_free_space_abort(tmp_path: Path):
    cfg = validate_config(
        {
            "name": "resume-smoke",
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
    manifest = tmp_path / "logs" / "resume.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["aborted_phase"] == "execute"
    assert payload["attempted"][0]["cell_key"] == "duckdb|tpch|0.01"
    assert (tmp_path / "logs" / "matrix_summary.partial.tsv").exists()


def test_manifest_runner_reuses_attempted_cells_and_runs_complement(tmp_path: Path):
    manifest = tmp_path / "resume.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "attempted": [
                    {
                        "cell_key": "duckdb|tpch|0.01",
                        "platform": "duckdb",
                        "benchmark": "tpch",
                        "scale": 0.01,
                        "terminal_state": "passed",
                        "exit_code": 0,
                        "elapsed_s": 1.0,
                        "log_path": str(tmp_path / "prior.log"),
                        "result_path": str(tmp_path / "prior.json"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cfg = validate_config(
        {
            "name": "resume-smoke",
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01, 0.1]},
        }
    )
    calls: list[float] = []

    def base_runner(platform, benchmark, scale, **kwargs):
        calls.append(scale)
        return CellResult(
            platform=platform,
            benchmark=benchmark,
            scale=scale,
            status="passed",
            exit_code=0,
            elapsed_s=2.0,
            log_path=tmp_path / f"{scale}.log",
            result_path=tmp_path / f"{scale}.json",
        )

    runner = orchestrator.build_resume_runner(
        orchestrator.load_resume_attempts(manifest),
        base_runner,
        log_dir=tmp_path,
    )

    outcome = exec_phase.run_execute(
        cfg,
        log_dir=tmp_path,
        databases_root=tmp_path / "databases",
        runner=runner,
    )

    assert calls == [0.1]
    assert [result.scale for result in outcome.results] == [0.01, 0.1]
    assert outcome.results[0].result_path == tmp_path / "prior.json"
