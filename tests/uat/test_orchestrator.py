"""Fast-test coverage for tests/uat/orchestrator.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tests.uat import orchestrator
from tests.uat.config import validate_config

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
