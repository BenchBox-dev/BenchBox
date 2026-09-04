from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "todo-db-export.yml"


def test_workflow_uses_only_the_locked_package_runtime() -> None:
    text = WORKFLOW.read_text()

    assert text.count("uv sync --project _project/scripts --locked") == 1
    # The tracker is read only through the pinned isolated-project boundary:
    # two invocations for the export step (envelope, then view rendering) plus
    # four for the clean-database restore validation.
    assert text.count("uv run --project _project/scripts --locked") == 6
    # The retired `_project/scripts/todo` shim is gone. 0.6.0's `export` emits
    # only the lossless envelope; the standalone stdlib script renders the
    # committed views from it.
    assert "_project/scripts/todo export" not in text
    assert 'todo-db --project-id "${TODO_DB_PROJECT_ID}" --repository "${TODO_DB_REPOSITORY}" \\\n' in text
    assert 'export --output "${RUNNER_TEMP}/todo-db.json"' in text
    assert "python _project/scripts/todo_db_export_views.py" in text
    assert '--envelope "${RUNNER_TEMP}/todo-db.json"' in text
    assert '--out "${EXPORT_DIR}"' in text
    assert '--lossless-out "${LOSSLESS_DIR}"' in text
    for forbidden in (
        "todo_db.py",
        "BENCHBOX_TODO_DB_STANDALONE",
        "TODO_DB_PACKAGE_URL",
        "TODO_DB_PACKAGE_SHA256",
        "curl --fail",
        "--with",
    ):
        assert forbidden not in text


def test_export_step_selects_the_v2_auth_contract() -> None:
    # Without it the floor CLI returns a legacy-safe exit 2 on hosted calls.
    text = WORKFLOW.read_text()

    assert "TODO_DB_AUTH_CONTRACT: v2" in text


def test_restore_validation_compares_the_exact_recovery_artifact_bytes() -> None:
    text = WORKFLOW.read_text()

    assert 'cmp -s "${LOSSLESS_DIR}/todo-db.json" "${restore_dir}/restored.json"' in text
    assert "sha256sum" in text
    assert "assert source == restored" not in text


def test_versioned_recovery_artifacts_have_bounded_retention() -> None:
    text = WORKFLOW.read_text()

    assert "uses: actions/upload-artifact@v4" in text
    assert "name: todo-db-export-${{ github.run_id }}-${{ github.run_attempt }}" in text
    assert "retention-days: 90" in text
