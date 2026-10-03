"""Unit tests for query ID normalization.

Tests the robust query ID normalization implemented in Phase C.2, which handles
various query ID formats including integers, strings, prefixed IDs, and variants.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.validation.query_validation import QueryValidator

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestQueryIDNormalization:
    """Test query ID normalization across different formats."""

    @pytest.fixture
    def validator(self):
        """Provide QueryValidator instance."""
        return QueryValidator()

    def test_normalize_integer_query_id(self, validator):

        # Integer query IDs should be converted to strings
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id=1,  # Integer
            actual_row_count=4,
            scale_factor=1.0,
        )
        assert result.is_valid
        assert result.expected_row_count == 4

    def test_normalize_string_numeric_query_id(self, validator):

        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="1",  # String numeric
            actual_row_count=4,
            scale_factor=1.0,
        )
        assert result.is_valid
        assert result.expected_row_count == 4

    def test_normalize_prefixed_query_id_uppercase_q(self, validator):
        """Test normalization of Q-prefixed query IDs (e.g., Q1, Q15)."""
        # Q1 format
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="Q1",
            actual_row_count=4,
            scale_factor=1.0,
        )
        assert result.is_valid
        assert result.expected_row_count == 4

    def test_normalize_prefixed_query_id_lowercase_q(self, validator):
        """Test normalization of lowercase q-prefixed query IDs (e.g., q1)."""
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="q1",
            actual_row_count=4,
            scale_factor=1.0,
        )
        assert result.is_valid
        assert result.expected_row_count == 4

    def test_normalize_query_prefix_format(self, validator):
        """Test normalization of 'query'-prefixed IDs (e.g., query1, query15)."""
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="query1",
            actual_row_count=4,
            scale_factor=1.0,
        )
        assert result.is_valid
        assert result.expected_row_count == 4

    def test_normalize_variant_suffix_single_letter(self, validator):
        """Test normalization of query variants with single letter suffix (e.g., 15a)."""
        # TPC-H Q15 has variants - the base query should be validated
        # Note: This tests that variant suffix is stripped to find base query
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="15a",
            actual_row_count=1,  # Q15 at SF=1.0
            scale_factor=1.0,
        )
        assert result.is_valid
        assert result.expected_row_count == 1

    def test_normalize_variant_suffix_multi_letter(self, validator):
        """Test normalization of query variants with multi-letter suffix (e.g., 15abc)."""
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="15abc",
            actual_row_count=1,
            scale_factor=1.0,
        )
        assert result.is_valid
        assert result.expected_row_count == 1

    def test_normalize_combined_prefix_and_variant(self, validator):
        """Test normalization of combined prefix and variant (e.g., Q15a, query15b)."""
        # Q15a format
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="Q15a",
            actual_row_count=1,
            scale_factor=1.0,
        )
        assert result.is_valid
        assert result.expected_row_count == 1

        # query15b format
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="query15b",
            actual_row_count=1,
            scale_factor=1.0,
        )
        assert result.is_valid
        assert result.expected_row_count == 1

    def test_normalize_multi_digit_query_ids(self, validator):

        # Plain multi-digit
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="15",
            actual_row_count=1,
            scale_factor=1.0,
        )
        assert result.is_valid

        # Prefixed multi-digit
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="Q15",
            actual_row_count=1,
            scale_factor=1.0,
        )
        assert result.is_valid

    def test_normalize_tpcds_query_ids(self, validator):

        result = validator.validate_query_result(
            benchmark_type="tpcds",
            query_id="Q1",
            actual_row_count=101,
            scale_factor=1.0,
        )
        assert result.is_valid
        # TPC-DS uses SKIP validation mode by default, so expected_row_count is None
        assert result.validation_mode.value == "skip"
        assert result.expected_row_count is None

    def test_normalize_non_tpc_benchmark_preserves_id(self, validator):
        """Test that non-TPC benchmarks preserve original ID format."""
        # For unknown benchmarks, ID should be preserved as-is (after str conversion)
        result = validator.validate_query_result(
            benchmark_type="custom_benchmark",
            query_id="MY_CUSTOM_ID_123",
            actual_row_count=100,
            scale_factor=1.0,
        )
        # Should skip validation (unknown benchmark)
        assert result.is_valid
        assert result.validation_mode.value == "skip"

    def test_normalize_leading_zeros_extracted(self, validator):
        """Test that leading zeros are stripped correctly (BUG-1 fix)."""
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="01",  # Leading zero - now correctly stripped to "1"
            actual_row_count=4,
            scale_factor=1.0,
        )
        # "01" is now normalized to "1" and matches expected results
        assert result.is_valid
        assert result.validation_mode.value == "exact"
        assert result.expected_row_count == 4

    def test_normalize_whitespace_handling(self, validator):

        # Whitespace should not prevent digit extraction
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="Q 1",  # Space in ID
            actual_row_count=4,
            scale_factor=1.0,
        )
        assert result.is_valid
        assert result.expected_row_count == 4

    def test_normalize_mixed_case_prefix(self, validator):

        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="Query1",  # Mixed case
            actual_row_count=4,
            scale_factor=1.0,
        )
        assert result.is_valid
        assert result.expected_row_count == 4

    def test_normalize_id_with_no_digits_falls_back(self, validator):

        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="INVALID_NO_DIGITS",
            actual_row_count=100,
            scale_factor=1.0,
        )
        # Should skip validation (can't find query)
        assert result.is_valid
        assert result.validation_mode.value == "skip"

    def test_normalize_consistency_across_formats(self, validator):

        # After BUG-1 fix, "01" also normalizes correctly to "1"
        formats = ["1", 1, "01", "Q1", "q1", "query1", "Query1"]

        results = []
        for query_id_format in formats:
            result = validator.validate_query_result(
                benchmark_type="tpch",
                query_id=query_id_format,
                actual_row_count=4,
                scale_factor=1.0,
            )
            results.append(result)

        # All should validate successfully
        assert all(r.is_valid for r in results)
        # All should have same expected count
        expected_counts = [r.expected_row_count for r in results]
        assert len(set(expected_counts)) == 1  # All same
        assert expected_counts[0] == 4

    def test_internal_normalize_method_directly(self, validator):

        # Test various formats
        assert validator._normalize_query_id("tpch", 1) == "1"
        assert validator._normalize_query_id("tpch", "1") == "1"
        assert validator._normalize_query_id("tpch", "Q1") == "1"
        assert validator._normalize_query_id("tpch", "q1") == "1"
        assert validator._normalize_query_id("tpch", "query15") == "15"
        assert validator._normalize_query_id("tpch", "15a") == "15"
        assert validator._normalize_query_id("tpch", "Q15b") == "15"

        # Test leading zeros (BUG-1 fix)
        assert validator._normalize_query_id("tpch", "01") == "1"
        assert validator._normalize_query_id("tpch", "001") == "1"
        assert validator._normalize_query_id("tpch", "Q01") == "1"

        # Test non-TPC benchmark preservation
        assert validator._normalize_query_id("custom", "MY_ID") == "MY_ID"
        assert validator._normalize_query_id("custom", 123) == "123"

    def test_negative_row_count_validation(self, validator):
        """Test that negative row counts raise ValueError (BUG-5 fix)."""
        import pytest

        with pytest.raises(ValueError, match="actual_row_count must be non-negative"):
            validator.validate_query_result(
                benchmark_type="tpch",
                query_id="1",
                actual_row_count=-1,  # Invalid negative count
                scale_factor=1.0,
            )

    def test_query_id_type_consistency(self, validator):
        """Test that query_id is always returned as string (BUG-4 fix)."""
        # Test with integer input
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id=1,  # Integer input
            actual_row_count=4,
            scale_factor=1.0,
        )
        assert isinstance(result.query_id, str)
        assert result.query_id == "1"

        # Test with string input
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="15",  # String input
            actual_row_count=1,
            scale_factor=1.0,
        )
        assert isinstance(result.query_id, str)
        assert result.query_id == "15"
