"""Unit tests for publication workflow step-output wiring.

The promotion writer once read ``steps.upload_pages.outputs.artifact-id``
(dash) while ``actions/upload-pages-artifact`` declares ``artifact_id``
(underscore). The empty interpolation rendered
``const deployedArtifactId = ;``, so the deploy step died at parse time
before any provider write. These tests pin every step-output reference in
the publication workflows against the referenced action's declared
outputs for the upload actions in play.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).parents[4]
WORKFLOWS = [
    REPO_ROOT / ".github/workflows/publication-transaction.yml",
    REPO_ROOT / ".github/workflows/publication-deploy.yml",
]

# Declared outputs for the upload actions referenced by the publication
# workflows. upload-pages-artifact uses underscores; upload-artifact uses
# dashes. That asymmetry is exactly what this guard protects.
KNOWN_ACTION_OUTPUTS = {
    "actions/upload-pages-artifact": {"artifact_id"},
    "actions/upload-artifact": {"artifact-id", "artifact-url"},
}

STEP_OUTPUT_REF = re.compile(r"steps\.([A-Za-z0-9_-]+)\.outputs\.([A-Za-z0-9_-]+)")


def _action_base(uses: str) -> str:
    return uses.split("@", 1)[0]


def _iter_step_strings(workflow: dict) -> tuple[str, str, str]:
    jobs = workflow.get("jobs") or {}
    if not isinstance(jobs, dict):
        return
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        job_outputs = job.get("outputs") or {}
        if isinstance(job_outputs, dict):
            for output_name, value in job_outputs.items():
                if isinstance(value, str):
                    yield job_name, f"outputs.{output_name}", value
        steps = job.get("steps") or []
        for step in steps:
            if not isinstance(step, dict):
                continue
            for key in ("script", "run", "with"):
                value = step.get(key)
                texts = value.values() if isinstance(value, dict) else [value]
                for text in texts:
                    if isinstance(text, str):
                        yield job_name, step.get("name", "<unnamed>"), text


def find_unknown_step_outputs(workflow_path: Path) -> list[str]:
    """Return step-output references naming an undeclared output."""
    with workflow_path.open(encoding="utf-8") as handle:
        workflow = yaml.safe_load(handle)
    steps: dict[str, str] = {}
    jobs = workflow.get("jobs") or {}
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and step.get("id") and step.get("uses"):
                steps[step["id"]] = _action_base(str(step["uses"]))
    problems = []
    for job_name, step_name, text in _iter_step_strings(workflow):
        for step_id, output in STEP_OUTPUT_REF.findall(text):
            uses = steps.get(step_id)
            if uses is None:
                continue
            declared = KNOWN_ACTION_OUTPUTS.get(uses)
            if declared is None:
                continue
            if output not in declared:
                problems.append(
                    f"{workflow_path.name} [{job_name}/{step_name}]: "
                    f"steps.{step_id}.outputs.{output} is not declared by {uses} "
                    f"(known: {sorted(declared)})"
                )
    return problems


def test_known_action_output_tables_cover_upload_steps() -> None:
    assert KNOWN_ACTION_OUTPUTS["actions/upload-pages-artifact"] == {"artifact_id"}
    assert "artifact-id" in KNOWN_ACTION_OUTPUTS["actions/upload-artifact"]


def test_unknown_step_output_reference_is_reported(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yml"
    workflow.write_text(
        "jobs:\n"
        "  deploy:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - id: upload_pages\n"
        "        uses: actions/upload-pages-artifact@v3\n"
        "      - uses: actions/github-script@v7\n"
        "        with:\n"
        "          script: const id = ${{ steps.upload_pages.outputs.artifact-id }};\n",
        "utf-8",
    )
    problems = find_unknown_step_outputs(workflow)
    assert len(problems) == 1
    assert "steps.upload_pages.outputs.artifact-id" in problems[0]


def test_matching_step_output_reference_passes(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yml"
    workflow.write_text(
        "jobs:\n"
        "  deploy:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - id: upload_pages\n"
        "        uses: actions/upload-pages-artifact@v3\n"
        "      - uses: actions/github-script@v7\n"
        "        with:\n"
        "          script: const id = ${{ steps.upload_pages.outputs.artifact_id }};\n",
        "utf-8",
    )
    assert find_unknown_step_outputs(workflow) == []


def test_unknown_job_output_reference_is_reported(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yml"
    workflow.write_text(
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    outputs:\n"
        "      candidate_id: ${{ steps.upload_candidate.outputs.artifact_id }}\n"
        "    steps:\n"
        "      - id: upload_candidate\n"
        "        uses: actions/upload-artifact@v4\n",
        "utf-8",
    )
    problems = find_unknown_step_outputs(workflow)
    assert len(problems) == 1
    assert "steps.upload_candidate.outputs.artifact_id" in problems[0]


def test_matching_job_output_reference_passes(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yml"
    workflow.write_text(
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    outputs:\n"
        "      candidate_id: ${{ steps.upload_candidate.outputs.artifact-id }}\n"
        "    steps:\n"
        "      - id: upload_candidate\n"
        "        uses: actions/upload-artifact@v4\n",
        "utf-8",
    )
    assert find_unknown_step_outputs(workflow) == []


@pytest.mark.parametrize("workflow_path", WORKFLOWS, ids=[p.name for p in WORKFLOWS])
def test_publication_workflow_step_outputs_resolve(workflow_path: Path) -> None:
    assert workflow_path.is_file()
    assert find_unknown_step_outputs(workflow_path) == []


def test_deploy_script_sends_resolvable_build_version() -> None:
    # The provider resolves pages_build_version as a commit. Sending the
    # journal's dangling write-intent OID made it reject the create request
    # with 404, so the wire value must be the run's pushed source SHA while
    # intent correlation stays in the journal's write record.
    text = (REPO_ROOT / ".github/workflows/publication-transaction.yml").read_text(encoding="utf-8")
    assert "pages_build_version: '${{ github.sha }}'" in text
    assert "start_write.outputs.pages_build_version" not in text
