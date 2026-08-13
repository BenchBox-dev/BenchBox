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
    assert "_project/scripts/todo export" in text
    assert text.count("uv run --project _project/scripts --locked") == 5
    for forbidden in (
        "todo_db.py",
        "BENCHBOX_TODO_DB_STANDALONE",
        "TODO_DB_PACKAGE_URL",
        "TODO_DB_PACKAGE_SHA256",
        "curl --fail",
        "--with",
    ):
        assert forbidden not in text


def test_restore_validation_compares_the_complete_export_envelope() -> None:
    text = WORKFLOW.read_text()

    assert "assert source == restored" in text
    assert 'k not in {"schema_migrations", "audit_head"}' not in text


def test_versioned_recovery_artifacts_have_bounded_retention() -> None:
    text = WORKFLOW.read_text()

    assert "uses: actions/upload-artifact@v4" in text
    assert "name: todo-db-export-${{ github.run_id }}-${{ github.run_attempt }}" in text
    assert "retention-days: 90" in text
