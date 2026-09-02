"""Contract tests for publication-canaries.yml workflow."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "publication-canaries.yml"


def _workflow() -> dict[str, Any]:
    assert WORKFLOW_PATH.is_file(), f"Workflow file missing at {WORKFLOW_PATH}"
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_publication_canaries_workflow_is_valid_yaml() -> None:
    wf = _workflow()
    assert "name" in wf
    assert "Publication Canaries" in wf["name"]
    assert "jobs" in wf
    assert "canaries" in wf["jobs"]


def test_publication_canaries_permissions_are_least_privilege() -> None:
    wf = _workflow()
    # Top-level permissions
    assert wf.get("permissions") == {"contents": "read"}

    # Job permissions must not escalate
    job_perms = wf["jobs"]["canaries"].get("permissions")
    assert job_perms == {"contents": "read"}

    # Raw content verification for strict no-write rule
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "pages: write" not in raw
    assert "id-token: write" not in raw
    assert "contents: write" not in raw
    assert "actions: write" not in raw
    assert "deploy-pages" not in raw


def test_publication_canaries_triggers_and_schedule() -> None:
    wf = _workflow()
    triggers = wf.get("on") or wf.get(True) or {}

    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers

    schedules = triggers["schedule"]
    assert len(schedules) >= 1
    cron_expr = schedules[0].get("cron", "")
    assert cron_expr, "Missing cron schedule expression"

    # Validate 5-part cron syntax (minute hour dom month dow)
    parts = cron_expr.strip().split()
    assert len(parts) == 5, f"Expected 5 parts in cron expression '{cron_expr}', got {len(parts)}"
    # Verify valid minute and hour
    assert re.match(r"^[0-9*,\-/]+$", parts[0]), f"Invalid cron minute: {parts[0]}"
    assert re.match(r"^[0-9*,\-/]+$", parts[1]), f"Invalid cron hour: {parts[1]}"


def test_publication_canaries_referenced_scripts() -> None:
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "scripts/publication/reconciliation.py" in raw
    assert "scripts/publication/verify_independence_matrix.py" in raw
    assert "scripts/publication/check_operational_receipts.py" in raw


def test_publication_canaries_upload_artifact_retention() -> None:
    wf = _workflow()
    steps = wf["jobs"]["canaries"]["steps"]

    upload_steps = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact")]
    assert len(upload_steps) >= 1

    upload = upload_steps[0]
    assert upload.get("with", {}).get("retention-days") == 30
    assert upload.get("if") == "always()"
