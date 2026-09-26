"""Contract tests for the publication release-handoff workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
HANDOFF_PATH = ROOT / ".github" / "workflows" / "publication-release-handoff.yml"


def _load() -> dict[str, Any]:
    assert HANDOFF_PATH.is_file(), f"Workflow file missing at {HANDOFF_PATH}"
    return yaml.safe_load(HANDOFF_PATH.read_text(encoding="utf-8"))


def test_handoff_runs_on_published_release() -> None:
    wf = _load()
    triggers = wf.get("on") or wf.get(True) or {}
    assert "push" not in triggers
    assert "pull_request" not in triggers
    assert triggers.get("release", {}).get("types") == ["published"]
    assert "workflow_dispatch" in triggers


def test_handoff_dispatches_candidate_then_promotion() -> None:
    wf = _load()
    steps = wf["jobs"]["handoff"]["steps"]
    run_text = "\n".join(str(step.get("run", "")) for step in steps)

    assert "candidate_only=true" in run_text
    assert "Publication Control Plane Deployment" in run_text
    assert "publication-candidate-$RUN_ID" in run_text
    assert "Publication Transactions" in run_text
    assert "kind=promotion" in run_text
    assert "github-pages approval" in run_text


def test_handoff_opens_tracked_issue_on_failure() -> None:
    wf = _load()
    steps = wf["jobs"]["handoff"]["steps"]
    fallback = next(
        (s for s in steps if s.get("name") == "Open tracked fallback issue when handoff fails"),
        None,
    )
    assert fallback is not None
    assert "failure()" in str(fallback.get("if", ""))
    fallback_run = fallback.get("run", "")
    assert "gh label create publication" in fallback_run
    assert "gh issue create" in fallback_run
    assert "--label" in fallback_run


def test_handoff_never_writes_pages() -> None:
    text = HANDOFF_PATH.read_text(encoding="utf-8")
    assert "deploy-pages" not in text
    assert "pages.cjs" not in text
    assert "upload-pages-artifact" not in text


def test_handoff_permissions_are_scoped() -> None:
    wf = _load()
    assert wf.get("permissions") == {"contents": "read"}
    job_perm = wf["jobs"]["handoff"]["permissions"]
    assert job_perm == {"contents": "read", "actions": "write", "issues": "write"}
