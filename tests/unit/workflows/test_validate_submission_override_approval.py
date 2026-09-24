"""Primary-bundle counters exclude overrides (review follow-ups).

Pins the ``*.override.json`` exclusion in the primary-bundle counters
that must agree with the corpus inventory (publication-deploy,
publication-corpus-cutover).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "publication-deploy.yml"
CUTOVER_WORKFLOW = ROOT / ".github" / "workflows" / "publication-corpus-cutover.yml"


def _all_run_text(workflow: Path) -> str:
    jobs = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]
    return "\n".join(str(step.get("run", "")) for job in jobs.values() for step in job.get("steps", []))


def test_deploy_bundle_count_excludes_overrides() -> None:
    run = _all_run_text(DEPLOY_WORKFLOW)
    assert "BUNDLE_COUNT" in run
    assert "! -name '*.override.json'" in run


def test_cutover_count_primary_excludes_overrides() -> None:
    run = _all_run_text(CUTOVER_WORKFLOW)
    assert "count_primary" in run
    assert "! -name '*.override.json'" in run
