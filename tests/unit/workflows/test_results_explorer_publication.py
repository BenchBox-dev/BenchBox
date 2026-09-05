"""Contract tests for the curated Results Explorer Pages publication path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "docs.yml"


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_release_docs_workflow_requires_curated_explorer_inputs_before_build() -> None:
    steps = _workflow()["jobs"]["build"]["steps"]
    names = [step.get("name") for step in steps]

    input_index = names.index("Verify curated Explorer publication inputs")
    build_index = names.index("Build explorer data (static pipeline)")
    invariant_index = names.index("Validate explorer snapshot invariants")

    assert input_index < build_index < invariant_index
    assert "test -d results-data/bundles" in steps[input_index]["run"]
    assert "test -f _project/scripts/explorer_publish.py" in steps[input_index]["run"]
    assert "test -s results-explorer/public/data/results.duckdb" in steps[invariant_index]["run"]


def test_release_docs_workflow_deploys_only_from_protected_release_push() -> None:
    deploy = _workflow()["jobs"]["deploy"]

    assert deploy["if"] == "github.event_name == 'push' && github.ref == 'refs/heads/release'"
    assert deploy["needs"] == "build"
    assert deploy["environment"]["name"] == "github-pages"
    assert deploy["concurrency"] == {"group": "pages-deploy", "cancel-in-progress": False}

    steps = deploy["steps"]
    guard_index = next(
        i for i, step in enumerate(steps) if step.get("name") == "Check for independent publication ownership"
    )
    deploy_index = next(i for i, step in enumerate(steps) if step.get("uses") == "actions/deploy-pages@v4")
    assert guard_index < deploy_index
    assert steps[deploy_index]["if"] == "steps.independent.outputs.active != 'true'"
    guard_run = steps[guard_index]["run"]
    assert "Publication Control Plane Deployment" in guard_run
    assert 'RUN_BRANCH" == "develop"' in guard_run
    assert 'RUN_CONCLUSION" == "success"' in guard_run
