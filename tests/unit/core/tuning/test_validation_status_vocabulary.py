"""Pin the real `tuning_validation_status` vocabulary.

History: from the 2026-07-12 tuning review (finding R7), the reviewed
vocabulary used to be hand-extracted from string literals assigned to the
`tuning_validation_status` local in `adapter.py` (`NOT_APPLICABLE`, `APPLIED`,
`FAILED_TO_SAVE`) plus the dataclass default (`NOT_VALIDATED`).

The applied-tuning ledger (TODO
`tuning-applied-ledger-and-validation-status-20260712`) moved the vocabulary
into one authoritative place: `benchbox.core.tuning.applied_ledger`. The status
is now derived by `AppliedTuningLedger.overall_status()` from what actually
executed, so `adapter.py` no longer holds bare status literals to scrape. This
module therefore pins the exported `TUNING_STATUS_VOCABULARY` frozenset against
the reviewed set directly, asserts the `BenchmarkResults` default matches, and
keeps the R7 regression guard (pass/fail-style values never enter the vocab).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import dataclasses

import pytest

from benchbox.core.results.models import BenchmarkResults
from benchbox.core.tuning.applied_ledger import (
    APPLIED_UNVERIFIED,
    APPLIED_VERIFIED,
    FAILED,
    LEGACY_STATUS_MAP,
    NOOP,
    NOT_APPLICABLE,
    NOT_VALIDATED,
    TUNING_STATUS_VOCABULARY,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# The reviewed, real vocabulary. Execution-derived, all-lowercase (the old
# uppercase metadata-write proxy is gone). Adding/renaming a status must be a
# conscious edit here AND in benchbox/core/tuning/applied_ledger.py.
EXPECTED_VALIDATION_STATUSES = frozenset(
    {
        "not_applicable",
        "noop",
        "applied_unverified",
        "applied_verified",
        "failed",
        "not_validated",
    }
)


def _models_default_validation_status() -> str:
    """Read `BenchmarkResults.tuning_validation_status`'s dataclass default."""
    for f in dataclasses.fields(BenchmarkResults):
        if f.name == "tuning_validation_status":
            assert f.default is not dataclasses.MISSING, (
                "tuning_validation_status must have a plain default (no default_factory) "
                "for this test to read it statically"
            )
            return f.default
    raise AssertionError("BenchmarkResults has no 'tuning_validation_status' field")


class TestValidationStatusVocabulary:
    def test_exported_vocabulary_matches_reviewed_set(self) -> None:
        assert TUNING_STATUS_VOCABULARY == EXPECTED_VALIDATION_STATUSES, (
            f"applied_ledger.TUNING_STATUS_VOCABULARY changed: {sorted(TUNING_STATUS_VOCABULARY)}. "
            "Update EXPECTED_VALIDATION_STATUSES (and any fixtures/docs referencing the "
            "vocabulary) to match, or revert the unintended change."
        )

    def test_named_constants_are_members_of_the_vocabulary(self) -> None:
        for status in (NOT_APPLICABLE, NOOP, APPLIED_UNVERIFIED, APPLIED_VERIFIED, FAILED, NOT_VALIDATED):
            assert status in TUNING_STATUS_VOCABULARY
            assert status == status.lower(), "statuses are all-lowercase now"

    def test_models_default_is_not_validated(self) -> None:
        default = _models_default_validation_status()
        assert default == "not_validated"
        assert default == NOT_VALIDATED
        assert default in TUNING_STATUS_VOCABULARY

    def test_pass_fail_style_values_are_not_part_of_the_vocabulary(self) -> None:
        # Regression guard for finding R7: "PASSED"/"FAILED" (uppercase, a
        # pass/fail test-result vocabulary) must never be tuning statuses. Note
        # the real failure token is lowercase "failed", which is fine.
        assert "PASSED" not in TUNING_STATUS_VOCABULARY
        assert "FAILED" not in TUNING_STATUS_VOCABULARY
        assert FAILED == "failed"

    def test_legacy_uppercase_statuses_map_into_the_vocabulary(self) -> None:
        # Back-compat readers translate old uppercase statuses; every mapped
        # target must be a current, valid status.
        for legacy, new in LEGACY_STATUS_MAP.items():
            assert legacy.upper() == legacy, "legacy keys are the old uppercase tokens"
            assert new in TUNING_STATUS_VOCABULARY
        # The metadata-write proxy collapses: both old APPLIED and FAILED_TO_SAVE
        # mean "a statement executed" now.
        assert LEGACY_STATUS_MAP["APPLIED"] == APPLIED_UNVERIFIED
        assert LEGACY_STATUS_MAP["FAILED_TO_SAVE"] == APPLIED_UNVERIFIED
