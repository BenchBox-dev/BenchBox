"""G2 preview deploy + soak contract pins.

publication-preview-deploy.yml may write production Pages (same-site preview
path), so its trigger discipline and permission scoping are load-bearing:
workflow_dispatch only, pages:write confined to the deploy job, and a
root-neutrality gate before any Pages write. The soak workflow must never
write Pages and must fail safe (INCONCLUSIVE on root movement, FAIL on
preview mismatch, receipt only after the 12h window).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_PATH = REPO_ROOT / ".github" / "workflows" / "publication-preview-deploy.yml"
SOAK_PATH = REPO_ROOT / ".github" / "workflows" / "publication-preview-soak.yml"

_SOUNDNESS_SPEC = importlib.util.spec_from_file_location(
    "auto_merge_soundness_paths",
    REPO_ROOT / "_project" / "scripts" / "auto_merge_soundness_paths.py",
)
assert _SOUNDNESS_SPEC is not None and _SOUNDNESS_SPEC.loader is not None
_soundness = importlib.util.module_from_spec(_SOUNDNESS_SPEC)
_SOUNDNESS_SPEC.loader.exec_module(_soundness)


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(data: dict) -> dict:
    # Quoted "on" stays a string key; unquoted `on:` parses as boolean True.
    if True in data:
        return data[True]
    return data["on"]


def test_deploy_is_dispatch_only() -> None:
    data = _load(DEPLOY_PATH)
    on = _triggers(data)
    assert "workflow_dispatch" in on
    assert "push" not in on, "no automatic trigger may gain a production Pages write"
    assert "pull_request" not in on
    assert "pull_request_target" not in on


def test_deploy_pages_write_scoped_to_deploy_job() -> None:
    data = _load(DEPLOY_PATH)
    top = data.get("permissions", {})
    assert top.get("pages") != "write", "top-level must not grant Pages write"
    jobs = data["jobs"]
    writers = [
        name
        for name, job in jobs.items()
        if isinstance(job.get("permissions"), dict) and job["permissions"].get("pages") == "write"
    ]
    assert writers == ["deploy"], f"only the deploy job may hold pages:write, got {writers}"
    assert jobs["deploy"]["permissions"].get("id-token") == "write"
    assert "github-pages" in str(jobs["deploy"].get("environment", {}))


def test_deploy_has_root_neutrality_gate_before_pages_write() -> None:
    text = DEPLOY_PATH.read_text(encoding="utf-8")
    assert "root neutrality" in text.lower() or "root-neutrality" in text.lower()
    assert "live_database" in text
    # Gate compares rebuilt root DB against the live baseline digest.
    assert "refusing deploy" in text or "refuses" in text or "refusing" in text


def test_deploy_requires_pinned_shas_and_approver() -> None:
    data = _load(DEPLOY_PATH)
    inputs = _triggers(data)["workflow_dispatch"]["inputs"]
    for name in ("develop_sha", "published_results_sha", "generation", "approver"):
        assert inputs[name]["required"] is True, f"{name} must be required"
    text = DEPLOY_PATH.read_text(encoding="utf-8")
    assert "40" in text and "hex" in text, "SHAs must be validated as 40-hex"
    assert "cat-file -e" in text, "pinned SHAs must be proven present"


def test_deploy_writes_receipts_with_both_shas() -> None:
    text = DEPLOY_PATH.read_text(encoding="utf-8")
    assert "desired-manifest.json" in text
    assert "assembly-receipt.json" in text
    assert "deployment-receipt.json" in text
    assert "develop_sha" in text and "published_results_sha" in text
    assert "soak-state.json" in text


def test_deploy_builds_docs_before_assembly() -> None:
    """Root rebuild mirrors docs.yml: Sphinx HTML must exist before assemble.

    Missing docs/_build/html fails assembly with FileNotFoundError (first
    gen1 deploy red). The sphinx-build step must precede assemble_public_site.
    """
    text = DEPLOY_PATH.read_text(encoding="utf-8")
    assert "sphinx-build -b html" in text
    assert text.index("sphinx-build -b html") < text.index("assemble_public_site.py")


def test_deploy_serializes_dispatches() -> None:
    data = _load(DEPLOY_PATH)
    assert "concurrency" in data, "concurrent dispatches must serialize (Pages is last-writer-wins)"


def test_soak_never_writes_pages() -> None:
    data = _load(SOAK_PATH)
    text = SOAK_PATH.read_text(encoding="utf-8")
    assert "deploy-pages" not in text
    assert "upload-pages-artifact" not in text
    for job in data["jobs"].values():
        perms = job.get("permissions", {}) if isinstance(job, dict) else {}
        assert perms.get("pages") != "write"


def test_soak_is_cron_plus_dispatch() -> None:
    data = _load(SOAK_PATH)
    on = _triggers(data)
    assert "schedule" in on, "soak must probe on a schedule without human action"
    crons = [entry.get("cron", "") for entry in on["schedule"]]
    assert any("30" in c for c in crons), f"expected a 30min cadence, got {crons}"
    assert "workflow_dispatch" in on


def test_soak_verdict_discipline() -> None:
    text = SOAK_PATH.read_text(encoding="utf-8")
    assert "INCONCLUSIVE" in text, "root movement must be inconclusive, never PASS"
    assert "12" in text, "live receipt requires the 12h window"
    assert "live-receipt.json" in text
    assert "verify_live.py" in text


def test_preview_workflows_are_soundness_paths() -> None:
    assert ".github/workflows/publication-preview-deploy.yml" in _soundness.SOUNDNESS_FILES
    assert ".github/workflows/publication-preview-soak.yml" in _soundness.SOUNDNESS_FILES


def test_preview_workflows_have_codeowners() -> None:
    text = (REPO_ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
    assert ".github/workflows/publication-preview-deploy.yml" in text
    assert ".github/workflows/publication-preview-soak.yml" in text
