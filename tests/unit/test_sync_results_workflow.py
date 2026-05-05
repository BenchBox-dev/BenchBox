from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "sync-results-data-to-published.yml"


def test_sync_results_workflow_sources_triggering_commit() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "ref: ${{ github.sha }}" in workflow
    assert 'git diff --name-only origin/published-results "${GITHUB_SHA}"' in workflow
    assert 'SOURCE_REF="${GITHUB_SHA}"' in workflow
    assert 'git checkout "${SOURCE_REF}" -- "${path}"' in workflow
    assert "origin/develop" not in workflow
