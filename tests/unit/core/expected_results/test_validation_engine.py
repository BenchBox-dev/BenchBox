"""Unit tests for query validation engine.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.expected_results.models import ValidationMode
from benchbox.core.expected_results.tpch_results import PARAMETER_SENSITIVE_QUERY_IDS
from benchbox.core.validation.query_validation import (
    QueryValidator,
    clear_reference_seed_context,
    get_parameter_sensitive_query_ids,
    get_reference_seed_context,
    set_reference_seed_context,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestQueryValidator:
    """Test QueryValidator class."""

    def test_validate_tpch_query_exact_match(self):
        """Test validation with exact match for TPC-H Q1."""
        validator = QueryValidator()
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="1",
            actual_row_count=4,
            scale_factor=1.0,
        )
        assert result.is_valid
        assert result.expected_row_count == 4
        assert result.actual_row_count == 4
        assert result.validation_mode == ValidationMode.EXACT

    def test_validate_tpch_query_mismatch(self):
        """Test validation with row count mismatch."""
        validator = QueryValidator()
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="1",
            actual_row_count=5,  # Wrong count
            scale_factor=1.0,
        )
        assert not result.is_valid
        assert result.expected_row_count == 4
        assert result.actual_row_count == 5
        assert result.difference == 1
        assert result.error_message is not None

    def test_validate_unknown_benchmark(self):
        """Test validation with unknown benchmark type."""
        validator = QueryValidator()
        result = validator.validate_query_result(
            benchmark_type="unknown_benchmark",
            query_id="1",
            actual_row_count=100,
            scale_factor=1.0,
        )
        # Should skip validation gracefully
        assert result.is_valid
        assert result.validation_mode == ValidationMode.SKIP
        assert result.warning_message is not None

    def test_validate_unknown_query(self):
        """Test validation with unknown query ID."""
        validator = QueryValidator()
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="999",  # Non-existent query
            actual_row_count=100,
            scale_factor=1.0,
        )
        # Should skip validation gracefully
        assert result.is_valid
        assert result.validation_mode == ValidationMode.SKIP
        assert result.warning_message is not None

    def test_validate_tpcds_query(self):
        """Test validation with TPC-DS query.

        TPC-DS queries use SKIP validation mode by default because queries are
        parameterized with random seeds. The answer files represent one specific
        parameterization, but benchmark runs may use different seeds.
        """
        validator = QueryValidator()
        result = validator.validate_query_result(
            benchmark_type="tpcds",
            query_id="1",
            actual_row_count=101,  # TPC-DS Q1 returns 101 rows at SF=1
            scale_factor=1.0,
        )
        assert result.is_valid
        assert result.validation_mode == ValidationMode.SKIP
        assert result.actual_row_count == 101
        # expected_row_count is available but validation is skipped
        assert result.warning_message is not None
        assert "SKIP" in result.warning_message or "skip" in result.warning_message


class TestParameterSensitiveExclusion:
    """Tests for the tpch-throughput-seed-validation-fix parameter-sensitive
    exclusion: TPC-H's answer-set-boundary queries (Q11/16/18/20) should not
    EXACT-fail when the caller (a TPC-H power/throughput driver) has recorded
    that the current query is NOT running under the pinned reference seed's
    substitution parameters (see set_reference_seed_context()).
    """

    @pytest.fixture(autouse=True)
    def _reset_reference_seed_context(self):
        """Guard every test in this class against thread-local context leakage.

        set_reference_seed_context()/clear_reference_seed_context() store
        state on threading.local(), which persists across test functions
        running on the same worker thread/process. Reset before AND after
        each test so test order never matters.
        """
        clear_reference_seed_context()
        yield
        clear_reference_seed_context()

    def test_parameter_sensitive_query_ids_constant(self):
        """The TPC-H parameter-sensitive set matches the four documented
        answer-set-boundary queries (mirrors the bounded correctness gate's
        exclusion list -- docs/operations/release-guide.md)."""
        assert frozenset({"11", "16", "18", "20"}) == PARAMETER_SENSITIVE_QUERY_IDS

    def test_get_parameter_sensitive_query_ids_tpch(self):
        assert get_parameter_sensitive_query_ids("tpch") == PARAMETER_SENSITIVE_QUERY_IDS
        assert get_parameter_sensitive_query_ids("tpc-h") == PARAMETER_SENSITIVE_QUERY_IDS
        assert get_parameter_sensitive_query_ids("TPCH") == PARAMETER_SENSITIVE_QUERY_IDS

    def test_get_parameter_sensitive_query_ids_unknown_benchmark_is_empty(self):
        """Benchmarks with no known parameter-sensitive queries (e.g. TPC-DS
        today) get an empty set, so the exclusion can never fire for them."""
        assert get_parameter_sensitive_query_ids("tpcds") == frozenset()
        assert get_parameter_sensitive_query_ids("unknown_benchmark") == frozenset()

    def test_context_default_is_none(self):
        """Unset context (the default for every caller that never calls
        set_reference_seed_context) reads back as None."""
        assert get_reference_seed_context() is None

    def test_context_set_get_clear_round_trip(self):
        set_reference_seed_context(True)
        assert get_reference_seed_context() is True
        set_reference_seed_context(False)
        assert get_reference_seed_context() is False
        clear_reference_seed_context()
        assert get_reference_seed_context() is None

    @pytest.mark.parametrize("query_id", sorted(PARAMETER_SENSITIVE_QUERY_IDS))
    def test_boundary_query_excluded_when_non_reference_seed(self, query_id):
        """Q11/16/18/20 with a row count that would FAIL exact match are
        excluded (SKIP, is_valid=True) once the context says non-reference."""
        set_reference_seed_context(False)
        validator = QueryValidator()
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id=query_id,
            actual_row_count=999_999_999,  # deliberately implausible/wrong
            scale_factor=1.0,
        )
        assert result.is_valid
        assert result.validation_mode == ValidationMode.SKIP
        assert result.warning_message is not None
        assert "parameter-sensitive" in result.warning_message
        assert "non-reference params" in result.warning_message

    @pytest.mark.parametrize("query_id", sorted(PARAMETER_SENSITIVE_QUERY_IDS))
    def test_boundary_query_still_exact_validated_when_reference_seed(self, query_id):
        """Reference-seed runs (context True) keep EXACT-match validation for
        Q11/16/18/20 -- the exclusion must not fire (must_preserve)."""
        set_reference_seed_context(True)
        validator = QueryValidator()
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id=query_id,
            actual_row_count=999_999_999,  # deliberately implausible/wrong
            scale_factor=1.0,
        )
        assert not result.is_valid
        assert result.validation_mode == ValidationMode.EXACT
        assert result.error_message is not None

    @pytest.mark.parametrize("query_id", sorted(PARAMETER_SENSITIVE_QUERY_IDS))
    def test_boundary_query_still_exact_validated_when_context_unset(self, query_id):
        """No caller ever set the context (e.g. a QueryValidator caller other
        than the TPC-H power/throughput drivers) -- preserves the pre-existing
        always-EXACT behavior exactly, so nothing regresses silently."""
        assert get_reference_seed_context() is None  # sanity: truly unset
        validator = QueryValidator()
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id=query_id,
            actual_row_count=999_999_999,
            scale_factor=1.0,
        )
        assert not result.is_valid
        assert result.validation_mode == ValidationMode.EXACT

    def test_non_boundary_query_not_excluded_when_non_reference_seed(self):
        """The exclusion is scoped to the parameter-sensitive set only -- a
        wrong row count on a non-excluded query (e.g. Q1) must still fail,
        even with a non-reference-seed context (anti_pattern guard: no
        unconditional exclusion, no tolerance widening)."""
        set_reference_seed_context(False)
        validator = QueryValidator()
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="1",
            actual_row_count=5,  # TPC-H Q1 at SF=1 is 4, not 5
            scale_factor=1.0,
        )
        assert not result.is_valid
        assert result.validation_mode == ValidationMode.EXACT

    def test_boundary_query_skipped_regardless_of_count_when_non_reference_seed(self):
        """The exclusion is deterministic: it fires BEFORE the registry
        lookup, so under a non-reference context a parameter-sensitive query
        is SKIPped no matter what count it returned -- even a count that
        happens to equal the reference answer. This pins the always-SKIP
        semantics (a coincidental match is NOT reported as an EXACT PASS,
        because under different substitution parameters the reference
        expectation is meaningless either way)."""
        validator = QueryValidator()

        # Wrong count -> SKIP (not FAILED).
        set_reference_seed_context(False)
        wrong = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="11",
            actual_row_count=999_999_999,
            scale_factor=1.0,
        )
        assert wrong.is_valid
        assert wrong.validation_mode == ValidationMode.SKIP

        # Reference-matching count -> still SKIP (not an EXACT PASS). Derive
        # the reference expectation from the registry itself so this test
        # never hardcodes an answer-set row count.
        reference_expected = validator.registry.get_expected_result("tpch", "11", 1.0)
        assert reference_expected is not None
        reference_count = reference_expected.get_expected_count(1.0)
        assert reference_count is not None

        set_reference_seed_context(False)
        coincidental = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="11",
            actual_row_count=reference_count,
            scale_factor=1.0,
        )
        assert coincidental.is_valid
        assert coincidental.validation_mode == ValidationMode.SKIP
        assert coincidental.warning_message is not None
        assert "parameter-sensitive" in coincidental.warning_message

    def test_tpcds_query_unaffected_by_reference_seed_context(self):
        """TPC-DS never sets the reference-seed context, and has no entry in
        the parameter-sensitive registry -- a non-reference-seed context must
        not change its (pre-existing, SKIP-by-default) validation behavior."""
        set_reference_seed_context(False)
        validator = QueryValidator()
        result = validator.validate_query_result(
            benchmark_type="tpcds",
            query_id="1",
            actual_row_count=101,
            scale_factor=1.0,
        )
        assert result.is_valid
        assert result.validation_mode == ValidationMode.SKIP
        assert "SKIP" in result.warning_message or "skip" in result.warning_message
