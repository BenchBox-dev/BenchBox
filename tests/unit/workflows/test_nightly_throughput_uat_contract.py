from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
NIGHTLY = REPO_ROOT / ".github" / "workflows" / "nightly.yml"
POSTGRES_CONFIG = REPO_ROOT / "tests" / "uat" / "configs" / "uat-throughput-postgresql-nightly.yaml"
UPLOAD_ARTIFACT_PIN = "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f"


def _jobs() -> dict[str, Any]:
    return yaml.safe_load(NIGHTLY.read_text(encoding="utf-8"))["jobs"]


def _steps() -> list[dict[str, Any]]:
    return _jobs()["throughput-uat"]["steps"]


def _step(prefix: str) -> dict[str, Any]:
    matches = [step for step in _steps() if str(step.get("name", "")).startswith(prefix)]
    assert len(matches) == 1, f"expected exactly one step starting with {prefix!r}, found {len(matches)}"
    return matches[0]


def _is_quarantined(step: dict[str, Any]) -> bool:
    return step.get("continue-on-error") is True or "quarantine" in str(step.get("name", ""))


def _condition(step: dict[str, Any]) -> str:
    return "".join(str(step.get("if", "")).split())


def test_duckdb_sweep_step_gates_without_continue_on_error() -> None:
    step = _step("Run DuckDB throughput UAT cell")
    assert "continue-on-error" not in step
    assert "if" not in step
    assert "uat-throughput-duckdb-nightly.yaml" in step["run"]


def test_duckdb_assert_step_gates_and_runs_after_a_failed_sweep() -> None:
    step = _step("Assert the requested stream count reached the driver")
    assert "continue-on-error" not in step
    assert _condition(step) == "${{!cancelled()}}"
    run = step["run"]
    assert "tests.uat.throughput assert" in run
    assert "--platform duckdb" in run
    assert "--streams 3" in run
    assert "--scale 1" in run
    assert "--evaluate-floor" in run
    assert "uat_throughput_duckdb_nightly_*/cells.jsonl" in run
    assert "--baseline-out" in run


def test_duckdb_assert_resolves_through_cells_jsonl_not_a_results_glob() -> None:
    run = _step("Assert the requested stream count reached the driver")["run"]
    assert "glob(" not in run
    assert "st_mtime" not in run
    assert "THROUGHPUT_UAT_STARTED_AT" not in NIGHTLY.read_text(encoding="utf-8")


def test_throughput_job_is_not_continue_on_error() -> None:
    job = _jobs()["throughput-uat"]
    assert "continue-on-error" not in job
    assert "if" not in job


def test_only_the_postgres_sweep_and_assert_steps_are_quarantined() -> None:
    quarantined = [step["name"] for step in _steps() if _is_quarantined(step)]
    assert len(quarantined) == 2
    assert all("Postgres" in name and "#2571" in name for name in quarantined)
    assert any(name.startswith("Run Postgres throughput UAT cell") for name in quarantined)
    assert any(name.startswith("Assert the Postgres cell") for name in quarantined)


def test_postgres_assert_still_runs_after_a_failed_sweep() -> None:
    step = _step("Assert the Postgres cell")
    assert _condition(step) == "${{!cancelled()}}"
    assert "uat_throughput_postgresql_nightly_*/cells.jsonl" in step["run"]
    assert "--platform postgresql" in step["run"]
    assert "--evaluate-floor" not in step["run"]


def test_logs_and_results_upload_even_when_the_job_fails_or_times_out() -> None:
    step = _step("Upload throughput UAT logs and results")
    assert step["if"] == "always()"
    assert step["uses"].startswith(UPLOAD_ARTIFACT_PIN)
    paths = step["with"]["path"]
    assert "~/Developer/benchmark_runs/logs/uat_throughput_*" in paths
    assert "~/Developer/benchmark_runs/results/tpch_sf1_*.json" in paths
    assert "${{ github.run_attempt }}" in step["with"]["name"]


def test_upload_steps_come_after_every_sweep_and_assert_step() -> None:
    names = [step.get("name", "") for step in _steps()]
    upload_index = names.index("Upload throughput UAT logs and results")
    for prefix in ("Run DuckDB throughput", "Run Postgres throughput", "Assert the requested", "Assert the Postgres"):
        assert next(index for index, name in enumerate(names) if name.startswith(prefix)) < upload_index


def test_baseline_record_is_uploaded_with_long_retention() -> None:
    step = _step("Upload Throughput@Size baseline record")
    assert step["uses"].startswith(UPLOAD_ARTIFACT_PIN)
    assert step["with"]["path"].startswith("~/Developer/benchmark_runs/throughput-baseline")
    assert step["with"]["retention-days"] == 90
    assert "${{ github.run_id }}" in step["with"]["name"]


def test_failure_signal_is_a_separate_status_independent_of_other_jobs() -> None:
    job = _jobs()["throughput-uat-signal"]
    assert job["needs"] == "throughput-uat"
    assert "".join(str(job["if"]).split()) == "${{!cancelled()}}"
    assert job["permissions"] == {"statuses": "write"}
    assert "continue-on-error" not in job
    run = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert 'context="nightly/throughput-uat"' in run
    assert "needs.throughput-uat.result" in yaml.safe_dump(job)


def test_postgres_cell_bounds_statements_so_one_query_cannot_consume_the_cell() -> None:
    config = yaml.safe_load(POSTGRES_CONFIG.read_text(encoding="utf-8"))
    extra_args = config["execute"]["extra_args"]
    assert extra_args[extra_args.index("--platform-option") + 1].startswith("statement_timeout=")
    timeout_ms = int(extra_args[extra_args.index("--platform-option") + 1].split("=", 1)[1])
    assert 0 < timeout_ms < config["execute"]["per_cell_timeout_s"] * 1000
