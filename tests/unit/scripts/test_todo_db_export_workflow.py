from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "todo-db-export.yml"


def test_standalone_package_is_single_resolution_and_hash_pinned() -> None:
    text = WORKFLOW.read_text()

    assert "todo-db[hosted]==" not in text
    assert text.count("curl --fail --location") == 1
    assert text.count("sha256sum --check --strict") == 1
    assert "TODO_DB_PACKAGE_URL: ${{ vars.TODO_DB_PACKAGE_URL }}" in text
    assert "TODO_DB_PACKAGE_SHA256: ${{ vars.TODO_DB_PACKAGE_SHA256 }}" in text
    assert text.count('--with "${TODO_DB_WHEEL}[hosted]"') == 6


def test_restore_validation_compares_the_complete_export_envelope() -> None:
    text = WORKFLOW.read_text()

    assert "assert source == restored" in text
    assert 'k not in {"schema_migrations", "audit_head"}' not in text


def test_versioned_recovery_artifacts_have_bounded_retention() -> None:
    text = WORKFLOW.read_text()

    assert "uses: actions/upload-artifact@v4" in text
    assert "name: todo-db-export-${{ github.run_id }}-${{ github.run_attempt }}" in text
    assert "retention-days: 90" in text
