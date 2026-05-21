"""Tests for SQL translation policy metadata in result bundles."""

from __future__ import annotations

import pytest

from benchbox.core.results.loader import reconstruct_benchmark_results
from benchbox.core.results.schema import build_result_payload
from benchbox.core.runner.runner import (
    _attach_translation_metadata,
    _finalize_validation_metadata,
    _resolve_strict_translation_mode,
)
from benchbox.utils.dialect_utils import SqlTranslationOutcome
from tests.fixtures.result_dict_fixtures import make_benchmark_results

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_translation_fallback_metadata_exports_and_marks_validation_uncertain() -> None:
    result = make_benchmark_results(
        validation_status="PASSED",
        validation_details={"row_count_matches": True},
        execution_metadata={},
    )
    outcomes = [
        SqlTranslationOutcome(
            source_dialect="netezza",
            target_dialect="duckdb",
            normalized_source_dialect="postgres",
            normalized_target_dialect="duckdb",
            translator="sqlglot",
            status="fallback",
            strict_mode=False,
            warning_category="translation_failed",
            message="synthetic failure",
        )
    ]

    enriched = _attach_translation_metadata(result, outcomes, strict_mode=False)
    payload = build_result_payload(enriched)

    assert enriched.validation_status == "UNCERTAIN"
    assert payload["summary"]["validation"] == "uncertain"
    assert payload["execution"]["translation"]["status"] == "fallback"
    assert payload["execution"]["translation"]["warning_categories"] == ["translation_failed"]
    assert payload["execution"]["translation"]["outcomes"][0]["count"] == 1


def test_loader_preserves_translation_metadata_on_reconstruct() -> None:
    result = make_benchmark_results(
        validation_status="UNCERTAIN",
        validation_details={"warnings": ["translation fallback"]},
        execution_metadata={
            "translation": {
                "status": "fallback",
                "strict_mode": False,
                "attempt_count": 1,
                "fallback_count": 1,
                "success_count": 0,
                "failed_count": 0,
                "translators": ["sqlglot"],
                "source_dialects": ["netezza"],
                "target_dialects": ["duckdb"],
            }
        },
    )
    payload = build_result_payload(result)

    reconstructed = reconstruct_benchmark_results(payload)

    assert reconstructed.validation_status == "uncertain"
    assert reconstructed.execution_metadata == {"translation": payload["execution"]["translation"]}


def test_no_validation_records_do_not_leave_default_passed_status() -> None:
    result = make_benchmark_results(validation_status="PASSED", validation_details=None)

    finalized = _finalize_validation_metadata(result, [])

    assert finalized.validation_status == "NOT_RUN"
    assert finalized.validation_details == {"stages": [], "error_count": 0, "warning_count": 0}


@pytest.mark.parametrize(
    "options",
    [
        {"strict_translation": True},
        {"platform_options": {"translation_strict": "true"}},
        {"benchmark_options": {"sql_translation_strict": "strict"}},
    ],
)
def test_strict_translation_mode_resolves_from_supported_option_scopes(options: dict) -> None:
    assert _resolve_strict_translation_mode(options) is True
