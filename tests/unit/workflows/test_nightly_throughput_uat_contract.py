from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
NIGHTLY = REPO_ROOT / ".github" / "workflows" / "nightly.yml"
CEDARDB_CONFIG = REPO_ROOT / "tests" / "uat" / "configs" / "uat-throughput-cedardb-nightly.yaml"
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


def test_only_the_cedardb_sweep_and_assert_steps_are_quarantined() -> None:
    quarantined = [step["name"] for step in _steps() if _is_quarantined(step)]
    assert len(quarantined) == 2
    assert all("CedarDB" in name and "#2571" in name for name in quarantined)
    assert any(name.startswith("Run CedarDB throughput UAT cell") for name in quarantined)
    assert any(name.startswith("Assert the CedarDB cell") for name in quarantined)


def test_cedardb_assert_still_runs_after_a_failed_sweep() -> None:
    step = _step("Assert the CedarDB cell")
    assert _condition(step) == "${{!cancelled()}}"
    assert "uat_throughput_cedardb_nightly_*/cells.jsonl" in step["run"]
    assert "--platform cedardb" in step["run"]
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
    for prefix in ("Run DuckDB throughput", "Run CedarDB throughput", "Assert the requested", "Assert the CedarDB"):
        assert next(index for index, name in enumerate(names) if name.startswith(prefix)) < upload_index


def test_baseline_record_is_uploaded_only_after_a_successful_duckdb_sweep() -> None:
    step = _step("Upload Throughput@Size baseline record")
    assert _step("Run DuckDB throughput UAT cell")["id"] == "duckdb-sweep"
    assert _condition(step) == "${{!cancelled()&&steps.duckdb-sweep.outcome=='success'}}"
    assert step["uses"].startswith(UPLOAD_ARTIFACT_PIN)
    assert step["with"]["path"].startswith("~/Developer/benchmark_runs/throughput-baseline")
    assert step["with"]["retention-days"] == 90
    assert "${{ github.run_id }}" in step["with"]["name"]


def test_failure_signal_is_a_separate_status_independent_of_other_jobs() -> None:
    job = _jobs()["throughput-uat-signal"]
    assert job["needs"] == "throughput-uat"
    assert "".join(str(job["if"]).split()) == "${{always()}}"
    assert job["permissions"] == {"statuses": "write"}
    assert "continue-on-error" not in job
    run = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert 'context="nightly/throughput-uat"' in run
    assert "needs.throughput-uat.result" in yaml.safe_dump(job)


def test_only_a_successful_job_publishes_a_success_status() -> None:
    run = "\n".join(str(step.get("run", "")) for step in _jobs()["throughput-uat-signal"]["steps"])
    assert run.count("state=success") == 1
    assert "success) state=success ;;" in run
    assert "cancelled) state=error ;;" in run
    assert "*) state=failure ;;" in run


def test_status_description_reports_the_quarantined_cedardb_sweep_outcome() -> None:
    assert _jobs()["throughput-uat"]["outputs"] == {"cedardb_sweep_outcome": "${{ steps.cedardb-sweep.outcome }}"}
    assert _step("Run CedarDB throughput UAT cell")["id"] == "cedardb-sweep"
    run = "\n".join(str(step.get("run", "")) for step in _jobs()["throughput-uat-signal"]["steps"])
    assert "CEDARDB_SWEEP_OUTCOME" in run


def test_cedardb_cell_keeps_the_throughput_workload_and_a_bounded_timeout() -> None:
    config = yaml.safe_load(CEDARDB_CONFIG.read_text(encoding="utf-8"))
    execute = config["execute"]
    assert config["platforms"]["include"] == ["cedardb"]
    assert config["benchmarks"]["include"] == ["tpch"]
    assert config["scales"]["rungs"] == [1]
    assert (execute["official"], execute["streams"], execute["phases_arg"]) == (True, 3, "load,throughput")
    assert execute["extra_args"] == ["--platform-option", "port=5435"]
    assert 0 < execute["per_cell_timeout_s"] <= 900
    assert config["cleanup"]["docker_manage_platforms"] is True
    assert "uat_throughput_cedardb_nightly_" in config["output"]["logs_dir_template"]


def test_cedardb_image_is_pinned_by_digest() -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker" / "cedardb" / "docker-compose.yml").read_text(encoding="utf-8"))
    assert compose["services"]["cedardb"]["image"] == (
        "cedardb/cedardb@sha256:dbbacb16b24421a9a123cd1d065e2a049c60b7cc6060d7db2f3cccbf69f5ff62"
    )
