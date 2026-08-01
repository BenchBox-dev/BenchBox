"""Export + anonymization of the post-load introspection receipt.

The receipt rides inside the ``.applied.json`` companion via
``AppliedTuningLedger.to_payload(receipt=...)``. Anonymized exports must scrub
the receipt's free-text / identifier fields exactly like the ledger statements.
TODO ``tuning-introspection-receipts-20260716``.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.core.results.exporter import ResultExporter
from benchbox.core.tuning.applied_ledger import (
    APPLIED_UNVERIFIED,
    APPLIED_VERIFIED,
    PHASE_DDL,
    AppliedTuningLedger,
)
from benchbox.core.tuning.introspection import KIND_INDEX, IntrospectedObject, IntrospectedState, corroborate

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _receipt_payload(corroborated: bool = True) -> dict:
    ledger = AppliedTuningLedger()
    ledger.record("CREATE INDEX IF NOT EXISTS idx_lineitem_sort ON LINEITEM (L_ORDERKEY)", PHASE_DDL)
    cols = ("l_orderkey",) if corroborated else ("l_partkey",)
    state = IntrospectedState(
        platform="duckdb",
        objects=[
            IntrospectedObject(KIND_INDEX, "LINEITEM", cols, "idx_lineitem_sort", {"index_name": "idx_lineitem_sort"})
        ],
    )
    return corroborate(ledger, state).to_payload()


class TestReceiptRidesInCompanion:
    def test_to_payload_embeds_receipt_and_verified_status(self):
        ledger = AppliedTuningLedger()
        ledger.record("CREATE INDEX IF NOT EXISTS idx_lineitem_sort ON LINEITEM (L_ORDERKEY)", PHASE_DDL)
        payload = ledger.to_payload(status=APPLIED_VERIFIED, receipt=_receipt_payload())
        assert payload["status"] == APPLIED_VERIFIED
        assert payload["receipt"]["corroborated"] is True
        assert payload["receipt"]["entries"][0]["verdict"] == "corroborated"

    def test_to_payload_without_receipt_has_no_receipt_key(self):
        ledger = AppliedTuningLedger()
        ledger.record("SET threads=4", PHASE_DDL)
        payload = ledger.to_payload(status=APPLIED_UNVERIFIED)
        assert "receipt" not in payload

    def test_non_anonymized_receipt_retains_raw_diagnostic_detail(self):
        ledger = AppliedTuningLedger()
        ledger.record("CREATE INDEX idx ON private_table (id)", PHASE_DDL)
        receipt = corroborate(
            ledger,
            IntrospectedState(platform="duckdb", error="connection to secret.internal failed"),
        ).to_payload()

        assert receipt["error"] == "connection to secret.internal failed"
        assert receipt["entries"][0]["reason"] == "introspection degraded"
        assert receipt["entries"][0]["detail"] == "connection to secret.internal failed"


class TestReceiptAnonymization:
    def test_anonymized_export_scrubs_receipt_freetext(self):
        exporter = ResultExporter(anonymize=True)
        applied = {
            "status": APPLIED_VERIFIED,
            "statements": [
                {"statement": "CREATE INDEX idx ON LINEITEM (L_ORDERKEY)", "phase": "ddl", "status": "executed"}
            ],
            "dropped": [],
            "receipt": _receipt_payload(),
        }
        sanitized = exporter._anonymize_applied_payload(applied)

        # Statement text is gone but the structural status is retained.
        assert "statement" not in sanitized["statements"][0]
        entry = sanitized["receipt"]["entries"][0]
        assert entry["verdict"] == "corroborated"  # structural verdict kept
        assert "statement" not in entry and "table" not in entry
        assert "expected_columns" not in entry and "observed_columns" not in entry
        assert entry["statement_redacted"] is True
        # Observed catalog facts are stripped of identifiers.
        for obj in sanitized["receipt"].get("observed", []):
            assert "table" not in obj and "columns" not in obj and obj["redacted"] is True
        # Top-level corroboration signal survives.
        assert sanitized["receipt"]["corroborated"] is True

    def test_anonymization_does_not_mutate_input(self):
        exporter = ResultExporter(anonymize=True)
        applied = {"status": APPLIED_VERIFIED, "statements": [], "dropped": [], "receipt": _receipt_payload()}
        exporter._anonymize_applied_payload(applied)
        # Original receipt entry still carries its statement text.
        assert "statement" in applied["receipt"]["entries"][0]
