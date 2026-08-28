"""Static contract pins for receipt presentation files outside Python tests."""

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]


def test_run_receipt_labels_entries_and_surfaces_defensive_truncation() -> None:
    source = (ROOT / "results-explorer/src/components/RunReceipt.tsx").read_text(encoding="utf-8")

    assert "Receipt entries ({entryCount})" in source
    assert "Statement receipt" not in source
    assert "published receipt exceeded the defensive receipt bound" in source
    assert "original_entry_count" in source


def test_same_requested_hash_annotation_keeps_applied_hashes_in_the_tuning_row() -> None:
    source = (ROOT / "results-explorer/src/components/ComparabilityReceipt.tsx").read_text(encoding="utf-8")

    assert 'summary: "Requested configuration matches; applied statements differ"' in source
    assert "sameRecordedRequest" in source
    assert "appliedStatementsDiffer" in source
    assert "formatTuning" in source
