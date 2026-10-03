"""Unit tests for scale factor handling and fallback logic.

Tests the scale factor improvements implemented in Phase B and C, including:
- Proper handling of SF≠1.0 (returning None to trigger graceful SKIP)
- Scale-independent query fallback from SF=X to SF=1.0
- Provider registration and availability checking

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.expected_results.models import ValidationMode
from benchbox.core.expected_results.tpcds_results import get_tpcds_expected_results
from benchbox.core.expected_results.tpch_results import get_tpch_expected_results
from benchbox.core.validation.query_validation import QueryValidator

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestScaleFactorHandling:
    """Test scale factor handling and fallback logic."""

    def test_tpch_sf_1_returns_results(self):
        """Test that TPC-H provider returns results for SF=1.0."""
        results = get_tpch_expected_results(scale_factor=1.0)
        assert results is not None
        assert results.benchmark_name == "tpch"
        assert results.scale_factor == 1.0
        assert len(results.query_results) > 0

    def test_tpch_sf_not_1_returns_none(self):
        """Test that TPC-H provider returns None for SF≠1.0."""
        # SF=10 should return None
        results = get_tpch_expected_results(scale_factor=10.0)
        assert results is None

        # SF=100 should return None
        results = get_tpch_expected_results(scale_factor=100.0)
        assert results is None

    def test_tpcds_sf_1_returns_results(self):
        """Test that TPC-DS provider returns results for SF=1.0."""
        results = get_tpcds_expected_results(scale_factor=1.0)
        assert results is not None
        assert results.benchmark_name == "tpcds"
        assert results.scale_factor == 1.0
        assert len(results.query_results) > 0

    def test_tpcds_sf_not_1_returns_none(self):
        """Test that TPC-DS provider returns None for SF≠1.0."""
        # SF=10 should return None
        results = get_tpcds_expected_results(scale_factor=10.0)
        assert results is None

        # SF=100 should return None
        results = get_tpcds_expected_results(scale_factor=100.0)
        assert results is None

    def test_scale_independent_query_validation_at_sf_10(self):
        """Test that scale-independent queries validate at SF≠1.0."""
        validator = QueryValidator()

        # TPC-H Q1 is scale-independent (same row count at any SF)
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="1",
            actual_row_count=4,
            scale_factor=10.0,  # SF=10, but Q1 is scale-independent
        )

        # Should use SF=1.0 expectation due to scale_independent flag
        assert result.is_valid
        assert result.expected_row_count == 4
        assert result.validation_mode == ValidationMode.EXACT

    def test_scale_dependent_query_skipped_at_sf_10(self):
        """Test that scale-dependent queries are skipped at SF≠1.0."""
        validator = QueryValidator()

        # TPC-H Q2 is scale-dependent (different row counts at different SFs)
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="2",
            actual_row_count=100,  # Actual count at SF=10
            scale_factor=10.0,
        )

        # Should skip validation (no expected results for SF=10)
        assert result.is_valid  # Don't fail on missing expectations
        assert result.validation_mode == ValidationMode.SKIP
        assert result.warning_message is not None
        assert (
            "No expected row count defined" in result.warning_message or "Validation skipped" in result.warning_message
        )

    def test_validation_with_none_scale_factor_defaults_to_1(self):
        """Test that None scale factor defaults to 1.0."""
        validator = QueryValidator()

        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="1",
            actual_row_count=4,
            scale_factor=None,  # Should default to 1.0
        )

        assert result.is_valid
        assert result.expected_row_count == 4

    def test_tpch_q1_marked_as_scale_independent(self):
        """Test that TPC-H Q1 is correctly marked as scale-independent."""
        results = get_tpch_expected_results(scale_factor=1.0)
        q1_result = results.get_expected_result("1")

        assert q1_result is not None
        assert q1_result.scale_independent is True

    def test_tpch_q2_marked_as_scale_dependent(self):
        """Test that TPC-H Q2 is correctly marked as scale-dependent."""
        results = get_tpch_expected_results(scale_factor=1.0)
        q2_result = results.get_expected_result("2")

        assert q2_result is not None
        assert q2_result.scale_independent is False

    def test_all_tpcds_queries_scale_dependent(self):

        results = get_tpcds_expected_results(scale_factor=1.0)

        # TPC-DS queries are scale-dependent (most of them)
        for query_id, query_result in results.query_results.items():
            # Unless explicitly marked otherwise, should be scale-dependent
            # (Current implementation has all as scale-dependent)
            if query_id not in []:  # Add scale-independent queries if any
                assert query_result.scale_independent is False

    def test_validation_error_message_mentions_sf(self):

        validator = QueryValidator()

        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="2",
            actual_row_count=100,
            scale_factor=10.0,
        )

        # Warning message should be informative
        assert result.warning_message is not None
        # Should mention either query ID or validation being skipped
        assert "2" in result.warning_message or "skip" in result.warning_message.lower()

    def test_registry_fallback_to_sf_1_for_scale_independent(self):
        """Test registry fallback mechanism for scale-independent queries."""
        from benchbox.core.expected_results.registry import get_registry

        registry = get_registry()

        # scale-independent query at SF=10
        result = registry.get_expected_result("tpch", "1", scale_factor=10.0)

        # Should fall back to SF=1.0 and return result
        assert result is not None
        assert result.query_id == "1"
        assert result.scale_independent is True

        # scale-dependent query at SF=10
        result = registry.get_expected_result("tpch", "2", scale_factor=10.0)

        # Should return None (no fallback for scale-dependent)
        assert result is None

    def test_multiple_scale_factors_cached_independently(self):

        from benchbox.core.expected_results.registry import get_registry

        registry = get_registry()

        # Access SF=1.0
        result_sf1 = registry.get_expected_result("tpch", "1", scale_factor=1.0)
        assert result_sf1 is not None

        # Access SF=10.0 (should use fallback for scale-independent)
        result_sf10 = registry.get_expected_result("tpch", "1", scale_factor=10.0)
        assert result_sf10 is not None

        # Both should return same expectations (since Q1 is scale-independent)
        assert result_sf1.expected_row_count == result_sf10.expected_row_count

    def test_provider_not_registered_returns_none(self):

        from benchbox.core.expected_results.registry import get_registry

        registry = get_registry()

        result = registry.get_expected_result("unknown_benchmark", "1", scale_factor=1.0)
        assert result is None

    def test_provider_registration_status_check(self):

        from benchbox.core.expected_results.registry import get_registry

        registry = get_registry()
        benchmarks = registry.list_available_benchmarks()

        # At minimum, tpch and tpcds should be registered
        assert "tpch" in benchmarks
        assert "tpcds" in benchmarks

    def test_clear_cache_allows_reload(self):

        from benchbox.core.expected_results.registry import get_registry

        registry = get_registry()

        result1 = registry.get_expected_result("tpch", "1", scale_factor=1.0)
        assert result1 is not None

        # Clear cache
        registry.clear_cache()

        # Load again (should reload from provider)
        result2 = registry.get_expected_result("tpch", "1", scale_factor=1.0)
        assert result2 is not None

        # Results should be equivalent
        assert result1.expected_row_count == result2.expected_row_count

    def test_validation_with_fractional_scale_factors(self):

        validator = QueryValidator()

        # SF=0.01 should skip (no provider results)
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="1",
            actual_row_count=4,
            scale_factor=0.01,
        )

        # Should use fallback for scale-independent query
        assert result.is_valid
        assert result.expected_row_count == 4

    def test_validation_consistency_across_scale_factors(self):
        """Test that scale-independent queries validate consistently."""
        validator = QueryValidator()

        scale_factors = [1.0, 10.0, 100.0, 0.01]
        results = []

        for sf in scale_factors:
            result = validator.validate_query_result(
                benchmark_type="tpch", query_id="1", actual_row_count=4, scale_factor=sf
            )
            results.append(result)

        # All should validate successfully (Q1 is scale-independent)
        assert all(r.is_valid for r in results)

        # All should have same expected count
        expected_counts = [r.expected_row_count for r in results]
        assert len(set(expected_counts)) == 1
        assert expected_counts[0] == 4
