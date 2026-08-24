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
            {"id": "Q1", "ms": 100, "status": "SUCCESS"},
            {"id": "Q2", "ms": 200, "status": "SUCCESS"},
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


def _copy_slim_validator(repo_root: Path, slim_root: Path) -> None:
    """Copy the complete stdlib-only validator surface to a slim checkout."""
    (slim_root / "scripts").mkdir(parents=True)
    (slim_root / "benchbox" / "validation").mkdir(parents=True)
    (slim_root / "benchbox" / "core" / "results").mkdir(parents=True)
    (slim_root / "results-data" / "bundles").mkdir(parents=True)
    shutil.copy2(repo_root / "scripts" / "validate_submission.py", slim_root / "scripts" / "validate_submission.py")
    shutil.copy2(
        repo_root / "benchbox" / "validation" / "bundle.py", slim_root / "benchbox" / "validation" / "bundle.py"
    )
    shutil.copy2(
        repo_root / "benchbox" / "core" / "results" / "query_status.py",
        slim_root / "benchbox" / "core" / "results" / "query_status.py",
    )


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
    _copy_slim_validator(repo_root, slim_root)

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


def test_slim_no_project_checkout_rejects_empty_public_result(tmp_path: Path) -> None:
    """The mirrored stdlib-only validator enforces the zero-query invariant."""
    repo_root = Path(__file__).resolve().parents[3]
    slim_root = tmp_path / "published-results"
    _copy_slim_validator(repo_root, slim_root)
    payload = _minimal_bundle()
    payload["summary"]["queries"] = {"total": 0, "passed": 0, "failed": 0}
    payload["queries"] = []
    bundle = slim_root / "results-data" / "bundles" / "empty.json"
    bundle.write_text(json.dumps(payload), encoding="utf-8")

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

    assert result.returncode == 1
    assert "queries array must not be empty" in result.stdout


def test_slim_no_project_checkout_rejects_false_clean_measurement(tmp_path: Path) -> None:
    """Slim validation uses the same failed-measurement policy as develop."""
    repo_root = Path(__file__).resolve().parents[3]
    slim_root = tmp_path / "published-results"
    _copy_slim_validator(repo_root, slim_root)
    payload = _minimal_bundle()
    payload["queries"][0]["status"] = "FAILED"
    bundle = slim_root / "results-data" / "bundles" / "false_clean.json"
    bundle.write_text(json.dumps(payload), encoding="utf-8")

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

    assert result.returncode == 1
    assert "contradicts 1 failed measurement query" in result.stdout
