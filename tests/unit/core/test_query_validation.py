"""
Unit tests for query-level row count validation.

Tests cover:
- EXACT validation mode with missing expected counts
- Variant query handling (14a/b, 23a/b)
- Validation mode override behavior
"""

import pytest

from benchbox.core.expected_results.models import (
    BenchmarkExpectedResults,
    ExpectedQueryResult,
    ValidationMode,
)
from benchbox.core.expected_results.registry import ExpectedResultsRegistry, get_registry
from benchbox.core.validation.query_validation import (
    QueryValidator,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestQueryValidatorExactModeSafeguards:
    """Test EXACT validation mode safeguards for missing expectations.

    These tests verify the critical safeguard added in query_validation.py
    that prevents false failures when EXACT mode is enabled but expected_count is None.
    """

    @pytest.mark.parametrize(
        ("expected_count", "actual_count", "mode", "valid"),
        [
            (None, 123, ValidationMode.SKIP, True),
            (7, 7, ValidationMode.EXACT, True),
            (7, 8, ValidationMode.EXACT, False),
        ],
        ids=["missing-count-skips-with-warning", "known-count-matches", "known-count-mismatch-fails"],
    )
    def test_exact_count_lookup_verdict(self, monkeypatch, expected_count, actual_count, mode, valid):
        expected = ExpectedQueryResult(query_id="14a", expected_row_count=7, validation_mode=ValidationMode.EXACT)
        if expected_count is None:
            monkeypatch.setattr(expected, "get_expected_count", lambda scale_factor: None)
        answers = BenchmarkExpectedResults(
            benchmark_name="missing_count_fixture",
            scale_factor=1.0,
            query_results={"14a": expected},
        )
        registry = ExpectedResultsRegistry()
        registry.register_provider("missing_count_fixture", lambda scale_factor: answers)
        validator = QueryValidator()
        validator.registry = registry

        result = validator.validate_query_result(
            benchmark_type="missing_count_fixture",
            query_id="14a",
            actual_row_count=actual_count,
            scale_factor=1.0,
        )

        assert result.is_valid is valid
        assert result.validation_mode == mode
        assert result.query_id == "14a"
        assert result.expected_row_count == expected_count
        assert result.actual_row_count == actual_count
        if expected_count is None:
            assert result.warning_message is not None
            assert "EXACT validation mode but no expected count available" in result.warning_message
            assert "Validation skipped" in result.warning_message
            assert result.error_message is None
        else:
            assert result.warning_message is None
            assert (result.error_message is None) is valid

    def test_integration_with_real_tpcds_variants(self):
        """
        Integration test: Verify TPC-DS variants work end-to-end with validation.

        This tests the full flow: loader registers variants → validator uses them.
        """
        from benchbox.core.expected_results.loader import load_tpcds_expected_results

        validator = QueryValidator()

        # Load TPC-DS results (which now includes variant registration from Phase 1.2)
        tpcds_results = load_tpcds_expected_results(scale_factor=1.0)

        # If query 14 exists, test variant validation
        if "14" in tpcds_results and "14a" in tpcds_results:
            # Validate query 14a - should work if variant is properly registered
            result = validator.validate_query_result(
                benchmark_type="tpcds",
                query_id="14a",
                actual_row_count=tpcds_results["14a"],  # Use actual expected count
                scale_factor=1.0,
            )

            # Should not fail - either PASSED (if expectations match) or SKIP (if default mode)
            assert result.is_valid is True, f"Variant 14a validation should not fail: {result.error_message}"
            assert result.validation_mode in (ValidationMode.EXACT, ValidationMode.SKIP, ValidationMode.RANGE)


class TestQueryValidatorVariantHandling:
    """Test handling of TPC-DS variant queries (14a/b, 23a/b)."""

    def test_variant_registration_via_loader(self):
        """
        Test that the loader registers variant aliases correctly.

        This test verifies that load_tpcds_expected_results() registers
        both base queries (14, 23) and their variants (14a/b, 23a/b).
        """
        from benchbox.core.expected_results.loader import load_tpcds_expected_results

        # Load TPC-DS expected results
        results = load_tpcds_expected_results(scale_factor=1.0)

        # If query 14 has expectations, variants should too
        if "14" in results:
            assert "14a" in results, "Variant 14a should be registered"
            assert "14b" in results, "Variant 14b should be registered"
            assert results["14a"] == results["14"], "Variant should have same count as base"
            assert results["14b"] == results["14"], "Variant should have same count as base"

        # Same for query 23
        if "23" in results:
            assert "23a" in results, "Variant 23a should be registered"
            assert "23b" in results, "Variant 23b should be registered"
            assert results["23a"] == results["23"], "Variant should have same count as base"
            assert results["23b"] == results["23"], "Variant should have same count as base"


class TestQueryValidatorSkipMode:
    """Test SKIP validation mode behavior."""

    def test_skip_mode_always_passes(self):
        """Test that SKIP mode always returns is_valid=True."""
        test_result = ExpectedQueryResult(
            query_id="test_skip",
            validation_mode=ValidationMode.SKIP,
            scale_independent=True,
        )

        test_registry = BenchmarkExpectedResults(
            benchmark_name="TEST_SKIP_MODE",
            scale_factor=1.0,
            query_results={"test_skip": test_result},
        )

        registry = get_registry()
        if "TEST_SKIP_MODE" not in registry._cache:
            registry._cache["TEST_SKIP_MODE"] = {}
        registry._cache["TEST_SKIP_MODE"][1.0] = test_registry

        try:
            validator = QueryValidator()

            # Even with any row count, SKIP should pass
            result = validator.validate_query_result(
                benchmark_type="TEST_SKIP_MODE",
                query_id="test_skip",
                actual_row_count=999,
                scale_factor=1.0,
            )

            assert result.is_valid is True
            assert result.validation_mode == ValidationMode.SKIP
            assert "skipped" in result.warning_message.lower()

        finally:
            registry._cache.pop("TEST_SKIP_MODE", None)


class TestQueryValidatorNoExpectation:
    """Test behavior when no expected result is registered."""

    def test_query_without_expectation_skips_validation(self):
        """Test that queries without expectations skip validation with warning."""
        validator = QueryValidator()

        # Use a benchmark name that's unlikely to be registered
        result = validator.validate_query_result(
            benchmark_type="NONEXISTENT_BENCHMARK",
            query_id="Q999",
            actual_row_count=1000,
            scale_factor=1.0,
        )

        assert result.is_valid is True
        assert result.validation_mode == ValidationMode.SKIP
        # The warning message says "No expected row count defined" which is close enough
        assert "no expected" in result.warning_message.lower() or "validation skipped" in result.warning_message.lower()
        assert result.expected_row_count is None
