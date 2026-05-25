"""Resource-heavy public submission validator tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.slow,
    pytest.mark.resource_heavy,
]


def _minimal_bundle() -> dict:
    """Return a minimal valid schema-v2 bundle dict."""
    return {
        "version": "2.1",
        "run": {
            "id": "abc123",
            "timestamp": "2026-04-01T12:00:00",
            "total_duration_ms": 5000,
        },
        "benchmark": {
            "id": "tpch",
            "name": "TPC-H",
            "scale_factor": 0.01,
        },
        "platform": {
            "name": "DuckDB",
            "version": "1.4.3",
        },
        "summary": {
            "validation": "passed",
            "queries": {"total": 2, "passed": 2, "failed": 0},
        },
        "queries": [
            {"id": "Q1", "ms": 100, "status": "pass"},
            {"id": "Q2", "ms": 200, "status": "pass"},
        ],
    }


def _uv_executable() -> str:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is required to exercise no-project validator execution")
    return uv


def _env_without_pythonpath() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    return env


@pytest.fixture
def valid_bundle_file(tmp_path: Path) -> Path:
    """Write a valid bundle to a temp file."""
    p = tmp_path / "tpch_result.json"
    p.write_text(json.dumps(_minimal_bundle()), encoding="utf-8")
    return p


def test_cli_runs_from_develop_checkout_without_project_install(valid_bundle_file: Path) -> None:
    """The develop checkout CLI runs under uv --no-project."""
    repo_root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            _uv_executable(),
            "run",
            "--no-project",
            "--",
            "python",
            "scripts/validate_submission.py",
            str(valid_bundle_file),
        ],
        cwd=repo_root,
        env=_env_without_pythonpath(),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "Validated 1 bundle(s): 0 error(s)" in result.stdout


def test_cli_runs_in_slim_no_project_checkout(tmp_path: Path) -> None:
    """The published-results mirror runs without installing the BenchBox project."""
    repo_root = Path(__file__).resolve().parents[3]
    slim_root = tmp_path / "published-results"
    (slim_root / "scripts").mkdir(parents=True)
    (slim_root / "benchbox" / "validation").mkdir(parents=True)
    (slim_root / "results-data" / "bundles").mkdir(parents=True)

    shutil.copy2(repo_root / "scripts" / "validate_submission.py", slim_root / "scripts" / "validate_submission.py")
    shutil.copy2(
        repo_root / "benchbox" / "validation" / "bundle.py", slim_root / "benchbox" / "validation" / "bundle.py"
    )

    bundle = slim_root / "results-data" / "bundles" / "tpch_result.json"
    bundle.write_text(json.dumps(_minimal_bundle()), encoding="utf-8")

    result = subprocess.run(
        [
            _uv_executable(),
            "run",
            "--no-project",
            "--",
            "python",
            "scripts/validate_submission.py",
            str(bundle.relative_to(slim_root)),
        ],
        cwd=slim_root,
        env=_env_without_pythonpath(),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "Validated 1 bundle(s): 0 error(s)" in result.stdout
