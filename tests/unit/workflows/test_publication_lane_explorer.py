"""Publication lane explorer workflow contracts.

Pins least-privilege, concurrency, artifact provenance, and test coverage
for the independent Results Explorer publication lane.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "publication-lane-explorer.yml"
INVENTORY = REPO_ROOT / "docs" / "operations" / "develop-push-drop-inventory.md"
CHECKER_SCRIPT = REPO_ROOT / "scripts" / "publication" / "check_explorer_compat.py"


def _load_workflow() -> dict:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert isinstance(data, dict)
    return data, text


def _get_on_block(workflow: dict):
    # PyYAML 1.1 treats `on` as boolean True
    on = workflow.get(True) or workflow.get("on")
    assert isinstance(on, dict), "workflow missing `on:` block"
    return on


def test_publication_lane_permissions_are_least_privilege() -> None:
    workflow, _ = _load_workflow()
    assert workflow.get("permissions") == {"contents": "read"}, (
        f"publication lane must be least-privilege contents: read, got {workflow.get('permissions')!r}"
    )


def test_publication_lane_no_job_level_permissions() -> None:
    workflow, _ = _load_workflow()
    for job_name, job in workflow.get("jobs", {}).items():
        assert "permissions" not in job, f"job {job_name!r} must not override workflow permissions"


def test_publication_lane_no_deploy_permissions() -> None:
    _, text = _load_workflow()
    # No pages, id-token, packages, deployments, or write permissions
    for needle in ("pages: write", "id-token: write", "packages: write", "deployments: write", "contents: write"):
        assert needle not in text, f"workflow must not contain {needle!r}"
    # No deploy step
    assert "deploy" not in text.lower() or "upload-artifact" in text.lower()


def test_publication_lane_concurrency_is_sha_keyed() -> None:
    _, text = _load_workflow()
    # Must be SHA-keyed for push (not ref) and PR number for pull_request
    assert "github.sha" in text, "concurrency group must be SHA-keyed for push"
    assert "github.event.pull_request.number" in text, "concurrency group must be PR-number-keyed for pull_request"
    # Should not use github.ref as the push key (would coalesce concurrent pushes)
    # The only allowed ref usage is for merge_group etc; publication lane should not use ref as fallback
    workflow, _ = _load_workflow()
    concurrency = workflow.get("concurrency", {})
    group = str(concurrency.get("group", ""))
    assert "github.sha" in group, f"concurrency group must contain github.sha, got {group!r}"
    assert "github.ref" not in group, f"concurrency group must not use github.ref (use github.sha), got {group!r}"


def test_publication_lane_artifact_name_includes_sha() -> None:
    _, text = _load_workflow()
    workflow, _ = _load_workflow()
    jobs = workflow.get("jobs", {})
    found_upload = False
    for job in jobs.values():
        for step in job.get("steps", []):
            if "upload-artifact" in str(step.get("uses", "")):
                found_upload = True
                name = str(step.get("with", {}).get("name", ""))
                # Must include github.sha for provenance
                assert "github.sha" in name, f"artifact name must include github.sha for provenance, got {name!r}"
                assert name != "explorer_app", "artifact name must not be fixed 'explorer_app' (fork PR provenance)"
    assert found_upload, "workflow must have an upload-artifact step"
    # Also check raw text
    assert "explorer_app-${{ github.sha }}" in text or "explorer_app-${{github.sha}}" in text.replace(" ", "")


def test_publication_lane_runs_explorer_tests() -> None:
    workflow, text = _load_workflow()
    # Must run npm test (vitest) and python contract tests
    assert "npm run test" in text or "npm test" in text, "workflow must run Explorer unit tests (npm run test)"
    # Check that npm test step has working-directory results-explorer
    found_npm_test = False
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            run = str(step.get("run", ""))
            if "npm run test" in run and "test:e2e" not in run:
                # Ensure it's the unit test step, not e2e
                found_npm_test = True
                # Check working-directory is results-explorer (if present)
                if "working-directory" in step:
                    assert step["working-directory"] == "results-explorer"
    assert found_npm_test, "workflow must have a step running 'npm run test' for Explorer unit tests"
    # Python contract tests
    assert "test_duckdb_browser_contract" in text or "test_explorer_build_contract" in text, (
        "workflow must run Python contract tests"
    )
    assert "test_duckdb_browser_contract.py" in text
    assert "test_explorer_build_contract.py" in text


def test_publication_lane_has_separate_generate_and_verify_steps() -> None:
    _, text = _load_workflow()
    workflow, _ = _load_workflow()
    jobs = workflow["jobs"]
    # Find generate and verify steps
    generate_count = text.count("--generate-manifest")
    require_count = text.count("--require-manifest")
    assert generate_count >= 1, "workflow must have a step with --generate-manifest"
    assert require_count >= 1, "workflow must have a separate step with --require-manifest for verification"
    # They must be in separate steps (not same run line)
    for job in jobs.values():
        for step in job["steps"]:
            run = str(step.get("run", ""))
            assert not ("--generate-manifest" in run and "--require-manifest" in run), (
                "generate and require must be in separate steps"
            )


def test_publication_lane_manifest_provenance() -> None:
    # Checker script must embed read_model_version and github.sha
    text = CHECKER_SCRIPT.read_text(encoding="utf-8")
    assert "read_model_version" in text
    assert "github_sha" in text or "GITHUB_SHA" in text
    assert "SUPPORTED_SCHEMA_VERSIONS" in text
    # Ensure manifest generation includes provenance
    assert "EXPLORER_READ_MODEL_VERSION" in text or "CURRENT_SCHEMA_VERSION" in text


def test_publication_lane_inventory_is_advisory() -> None:
    inv = INVENTORY.read_text(encoding="utf-8")
    # Find publication-lane row
    assert "publication-lane-explorer.yml" in inv, "inventory must list publication-lane-explorer.yml"
    # The row must not claim required-check as primary safety property
    # Find the line containing the workflow name
    for line in inv.splitlines():
        if "publication-lane-explorer.yml" in line:
            lower = line.lower().replace("*", "").replace("`", "")
            # Must contain advisory and must not claim "required-path gate" or "required check"
            assert "advisory" in lower, f"inventory row must be marked advisory, got: {line!r}"
            # Check that row states lane is not a required check (allow markdown bold)
            assert "not" in lower and "required" in lower, (
                f"inventory row must state lane is not a required check, got: {line!r}"
            )
            # Should not claim pre-merge required gate
            assert "pre-merge required-path gate" not in line, (
                f"inventory must not claim pre-merge required-path gate, got: {line!r}"
            )
            break
    else:
        pytest.fail("publication-lane-explorer row not found in inventory")


def test_publication_lane_checker_supports_only_v9() -> None:
    text = CHECKER_SCRIPT.read_text(encoding="utf-8")
    # Must import from contract or set to 9
    assert "EXPLORER_READ_MODEL_VERSION" in text or "SUPPORTED_SCHEMA_VERSIONS: tuple[int, ...] = (9,)" in text
    assert "SUPPORTED_SCHEMA_VERSIONS: tuple[int, ...] = (7, 8, 9)" not in text
    # Must not contain v7/v8 hand-maintained logic
    assert (
        "if version == 8" not in text or "cpu_identity_provenance" not in text.split("if version == 8")[0][-500:]
    )  # rough
    # Check that get_table_columns_for_version only supports CURRENT_SCHEMA_VERSION
    assert "if version == 7" not in text
    # Ensure checker imports contract
    has_import = "from _project.scripts.explorer_pipeline.contract import" in text
    has_fallback = "SUPPORTED_SCHEMA_VERSIONS: tuple[int, ...] = (9,)" in text
    assert has_import or has_fallback


def test_publication_lane_checker_manifest_fail_closed() -> None:
    text = CHECKER_SCRIPT.read_text(encoding="utf-8")
    # Must have require_manifest handling
    assert "require_manifest" in text
    assert "manifest.json is missing" in text
    assert "SHA256SUMS is missing" in text
    # Must reject malformed SHA256SUMS
    assert "malformed SHA256SUMS" in text
    # Must anchor exclude to root-relative
    assert "relative_to(directory).as_posix()" in text or "as_posix()" in text
    # Check that excludes is checked via rel, not p.name
    assert "if rel in excludes" in text
