"""Nightly-only wiring contract for the SQLGlot generated translation pilot."""

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.medium]

REPO_ROOT = Path(__file__).resolve().parents[2]
NIGHTLY = REPO_ROOT / ".github/workflows/nightly.yml"
PR_WORKFLOW = REPO_ROOT / ".github/workflows/pr.yml"


def _job_block(workflow: str, job: str, next_job: str) -> str:
    start = workflow.index(f"  {job}:\n")
    end = workflow.index(f"  {next_job}:\n", start)
    return workflow[start:end]


def test_generator_is_nightly_only_and_preserves_required_pr_workflow() -> None:
    nightly = NIGHTLY.read_text(encoding="utf-8")
    pr_workflow = PR_WORKFLOW.read_text(encoding="utf-8")

    assert "  sqlglot-generator:\n" in nightly
    assert "_project/sqlglot-upstream/repros/generator.py" in nightly
    assert "_project/sqlglot-upstream/repros/generator.py" not in pr_workflow


def test_policy_and_infrastructure_failures_stay_blocking() -> None:
    workflow = NIGHTLY.read_text(encoding="utf-8")
    job = _job_block(workflow, "sqlglot-generator", "integration-smoke")

    guard = job.index("scripts/check_sqlglot_generator_known_failures.py")
    generator = job.index("_project/sqlglot-upstream/repros/generator.py")
    advisory = job.index('if [ "${status}" -eq 1 ]')
    evidence_validation = job.index("--validate-advisory-evidence")
    infrastructure = job.index('if [ "${status}" -ne 0 ]')

    assert guard < generator < advisory < evidence_validation < infrastructure
    assert "continue-on-error" not in job
    assert 'exit "${status}"' in job


def test_nightly_pilot_is_bounded_and_uploads_replay_evidence() -> None:
    workflow = NIGHTLY.read_text(encoding="utf-8")
    job = _job_block(workflow, "sqlglot-generator", "integration-smoke")

    assert "timeout-minutes: 10" in job
    assert "--cases 1024" in job
    assert "--deadline-seconds 300" in job
    assert '--seed "${GITHUB_RUN_ID}"' in job
    assert "sqlglot-generator-summary.json" in job
    assert "sqlglot-generator-failure.json" in job
