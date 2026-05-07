"""Fast-test coverage for tests/uat/orchestrator.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tests.uat import orchestrator
from tests.uat.config import validate_config
from tests.uat.runner import CellResult

pytestmark = pytest.mark.fast


def test_dry_run_records_zero_per_phase(tmp_path: Path):
    cfg = validate_config(
        {
            "name": "smoke",
            "dry_run": True,
            "phases": ["preflight", "enumerate", "execute", "report"],
        }
    )
    result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path)
    assert result.aborted_phase is None
    assert all(c == 0 for c in result.phase_exit_codes.values())
    assert set(result.phase_exit_codes) == {"preflight", "enumerate", "execute", "report"}


def test_preflight_abort_short_circuits(tmp_path: Path):
    cfg = validate_config(
        {
            "name": "smoke",
            "phases": ["preflight", "execute"],
        }
    )
    fake_result = type(
        "Stub",
        (),
        {"aborted": True, "abort_reason": "no disk", "warnings": ()},
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


def test_dry_run_still_runs_enumerate(tmp_path: Path):
    """dry_run should NOT short-circuit enumerate; a malformed config must fail at PR time."""
    cfg = validate_config(
        {
            "name": "smoke",
            "dry_run": True,
            "phases": ["enumerate", "execute"],
            "platforms": {"groups": ["does-not-exist"]},
        }
    )
    result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path)
    assert result.aborted_phase == "enumerate"
    assert result.phase_exit_codes["enumerate"] == 2


def test_dry_run_enumerate_type_error_returns_structured_abort(tmp_path: Path):
    """Malformed list-like fields should abort enumerate instead of escaping run_sweep."""
    cfg = validate_config(
        {
            "name": "smoke",
            "dry_run": True,
            "phases": ["enumerate", "execute"],
            "platforms": {"groups": 1},
        }
    )
    result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path)
    assert result.aborted_phase == "enumerate"
    assert result.phase_exit_codes["enumerate"] == 2
    assert result.exit_code() == 2


def test_dry_run_passes_with_valid_enumerate(tmp_path: Path):
    """A valid dry_run sweep should still pass through enumerate cleanly."""
    cfg = validate_config(
        {
            "name": "smoke",
            "dry_run": True,
            "phases": ["enumerate", "execute", "report"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )
    result = orchestrator.run_sweep(cfg, log_dir_override=tmp_path)
    assert result.aborted_phase is None
    assert all(c == 0 for c in result.phase_exit_codes.values())


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
    execute_outcome = type("ExecuteOutcome", (), {"results": (cell,), "aborted": False, "abort_reason": None})()
    captured: dict[str, Path] = {}

    def fake_package(config, *, result_paths, submissions_dir):
        captured["package_dir"] = submissions_dir
        return type("PackageResult", (), {"exit_code": lambda self: 0})()

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
    fake_preflight = type("Preflight", (), {"aborted": False, "abort_reason": None, "warnings": ()})()
    fake_execute = type(
        "ExecuteOutcome",
        (),
        {"results": (), "pruned": (), "skipped_unreachable": (), "aborted": False, "abort_reason": None},
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
