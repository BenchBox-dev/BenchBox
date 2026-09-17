"""The inlined applied ledger carries the same entry cap as the companion.

``_validate_applied_companion_limits`` bounds ``*.applied.json`` by filename, so
folding the ledger into ``platform.tuning.applied`` opened a path around it: the
validator runs on attacker-controlled PR JSON, and a hand-authored bundle can
inline an unbounded receipt while shipping no companion at all.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for
details.
"""

from __future__ import annotations

import pytest

from benchbox.validation.bundle import (
    APPLIED_RECEIPT_MAX_ENTRIES,
    ValidationResult,
    _validate_platform_section,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _platform(applied: dict) -> dict:
    return {"name": "duckdb", "tuning": {"applied": applied}}


def _validate(platform: dict) -> ValidationResult:
    vr = ValidationResult(path="bundle.json")
    _validate_platform_section(platform, vr)
    return vr


class TestInlineAppliedLedgerBounds:
    def test_oversized_statement_list_is_rejected(self) -> None:
        over = APPLIED_RECEIPT_MAX_ENTRIES + 1
        vr = _validate(_platform({"statements": [{"phase": "ddl"}] * over}))

        assert not vr.ok
        assert any("platform.tuning.applied.statements" in error for error in vr.errors)

    def test_oversized_receipt_entry_list_is_rejected(self) -> None:
        over = APPLIED_RECEIPT_MAX_ENTRIES + 1
        vr = _validate(_platform({"receipt": {"entries": [{"kind": "index"}] * over}}))

        assert not vr.ok
        assert any("platform.tuning.applied.receipt.entries" in error for error in vr.errors)

    def test_ledger_within_the_cap_passes(self) -> None:
        vr = _validate(
            _platform(
                {
                    "status": "applied_unverified",
                    "statements": [{"phase": "ddl", "statement_redacted": True}],
                    "receipt": {"entries": [{"kind": "index", "verdict": "match"}]},
                }
            )
        )

        assert vr.ok

    @pytest.mark.parametrize("tuning", [None, {}, {"applied": None}, {"applied": "not-a-dict"}])
    def test_absent_or_malformed_blocks_are_not_errors_here(self, tuning: object) -> None:
        """Shape validation for the ledger stays with its producer; this gate
        only bounds resources and must not broaden rejection semantics."""
        platform: dict = {"name": "duckdb"}
        if tuning is not None:
            platform["tuning"] = tuning

        assert _validate(platform).ok
