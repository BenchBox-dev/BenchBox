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


def test_no_throughput_step_is_quarantined() -> None:
    assert [step["name"] for step in _steps() if _is_quarantined(step)] == []
    assert "#2571" not in yaml.safe_dump(_jobs()["throughput-uat"])


def test_cedardb_steps_gate_like_the_duckdb_steps() -> None:
    sweep = _step("Run CedarDB throughput UAT cell")
    assert "continue-on-error" not in sweep
    assert "if" not in sweep
    assert "uat-throughput-cedardb-nightly.yaml" in sweep["run"]
    assert "continue-on-error" not in _step("Assert the CedarDB cell")


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


def test_status_description_reports_the_cedardb_sweep_outcome_without_a_quarantine_label() -> None:
    assert _jobs()["throughput-uat"]["outputs"] == {"cedardb_sweep_outcome": "${{ steps.cedardb-sweep.outcome }}"}
    assert _step("Run CedarDB throughput UAT cell")["id"] == "cedardb-sweep"
    run = "\n".join(str(step.get("run", "")) for step in _jobs()["throughput-uat-signal"]["steps"])
    assert "CEDARDB_SWEEP_OUTCOME" in run
    assert "quarantine" not in run


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


def test_throughput_job_grants_only_contents_and_actions_read() -> None:
    assert _jobs()["throughput-uat"]["permissions"] == {"contents": "read", "actions": "read"}
    assert "actions" not in (yaml.safe_load(NIGHTLY.read_text(encoding="utf-8")).get("permissions") or {})


def test_baseline_history_is_downloaded_before_the_duckdb_assert() -> None:
    names = [step.get("name", "") for step in _steps()]
    download = _step("Download retained Throughput@Size baselines")
    assert names.index(download["name"]) < names.index(_step("Assert the requested stream count")["name"])
    assert names.index(download["name"]) > names.index(_step("Run DuckDB throughput UAT cell")["name"])
    assert "continue-on-error" not in download
    assert _condition(download) == "${{!cancelled()}}"
    assert download["env"] == {"GH_TOKEN": "${{ github.token }}"}
    run = download["run"]
    assert "gh run list" in run
    assert "--workflow nightly.yml" in run
    assert "--branch develop" in run
    assert "--event schedule" in run
    assert "--event workflow_dispatch" not in run
    assert '--dir "${history}/${run_id}"' in run
    assert "gh run download" in run
    assert "--pattern 'throughput-baseline-duckdb-tpch-sf1-*'" in run
    assert "${GITHUB_RUN_ID}" in run


def test_duckdb_assert_reads_the_downloaded_history_not_the_output_dir() -> None:
    run = _step("Assert the requested stream count reached the driver")["run"]
    history = '--baseline-history "$HOME/Developer/benchmark_runs/throughput-baseline-history"'
    assert history in run
    assert '--baseline-out "$HOME/Developer/benchmark_runs/throughput-baseline"' in run
    assert "--baseline-history" not in _step("Assert the CedarDB cell")["run"]


def test_baseline_reset_variable_reaches_the_assert_environment() -> None:
    env = _jobs()["throughput-uat"]["env"]
    assert env["THROUGHPUT_BASELINE_MIN_RECORDED_AT"] == "${{ vars.THROUGHPUT_BASELINE_MIN_RECORDED_AT }}"
