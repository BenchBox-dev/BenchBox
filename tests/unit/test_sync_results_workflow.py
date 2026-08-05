from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "sync-results-data-to-published.yml"

FIXED_POINT_GATE_STEP = "Gate corpus publication fixed point"
BUILD_MIRROR_STEP = "Build mirror branch"
FIXED_POINT_TEST_FRAGMENT = "rederived_corpus_publishes_byte_identically"


def test_sync_results_workflow_sources_triggering_commit() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "ref: ${{ github.sha }}" in workflow
    assert 'git diff --name-only origin/published-results "${GITHUB_SHA}"' in workflow
    assert 'SOURCE_REF="${GITHUB_SHA}"' in workflow
    assert 'git checkout "${SOURCE_REF}" -- "${path}"' in workflow
    assert "origin/develop" not in workflow


def test_sync_workflow_references_publication_fixed_point_gate() -> None:
    """The mirror must refuse a corpus that re-anonymization would rewrite.

    Pins the workflow to the same fixed-point invariant as
    ``test_rederived_corpus_publishes_byte_identically_to_what_is_stored`` so a
    future edit cannot drop the gate while leaving the unit suite green.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert FIXED_POINT_TEST_FRAGMENT in workflow, (
        "sync workflow does not reference the publication fixed-point gate "
        f"({FIXED_POINT_TEST_FRAGMENT}); a non-fixed-point corpus could still be mirrored"
    )
    assert "AnonymizationManager" in workflow
    assert "canonical_json_bytes" in workflow
    assert "publication fixed point" in workflow.lower() or "not at the publication fixed point" in workflow


def test_sync_workflow_fixed_point_gate_runs_before_mirror_build() -> None:
    """Gate must run on develop content before any mirror branch is built.

    Building first would push rewriteable bytes; the gate is a precondition for
    opening a public mirror, not a post-hoc status on an already-opened PR.
    """
    steps = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))["jobs"]["mirror"]["steps"]
    names = [step.get("name") for step in steps]
    assert FIXED_POINT_GATE_STEP in names, f"missing step {FIXED_POINT_GATE_STEP!r}"
    assert BUILD_MIRROR_STEP in names, f"missing step {BUILD_MIRROR_STEP!r}"
    assert names.index(FIXED_POINT_GATE_STEP) < names.index(BUILD_MIRROR_STEP), (
        "publication fixed-point gate runs after Build mirror branch; "
        "the mirror could be built from a corpus that publishing would rewrite"
    )

    gate = next(step for step in steps if step.get("name") == FIXED_POINT_GATE_STEP)
    run = gate.get("run", "")
    assert "Refusing to open a mirror" in run or "not at the publication fixed point" in run
    assert "SystemExit(1)" in run or "raise SystemExit" in run
