"""Unit tests for query validation engine.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.expected_results.models import ValidationMode
from benchbox.core.expected_results.tpch_results import (
    PARAMETER_SENSITIVE_QUERY_IDS,
    TPCH_LOOSE_QUERY_IDS,
    TPCH_RANGE_ROW_COUNT_BOUNDS,
    get_tpch_expected_results,
)
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


class TestParameterSensitiveValidation:
    """Tests for TPC-H's reference-seed-aware validation of the answer-set
    boundary queries: EXACT against the answer file at the reference seed,
    relaxed to RANGE/LOOSE only under a non-reference seed."""

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
        answer-set-boundary queries."""
        assert frozenset({"11", "16", "18", "20"}) == PARAMETER_SENSITIVE_QUERY_IDS
        assert set(TPCH_RANGE_ROW_COUNT_BOUNDS) | set(TPCH_LOOSE_QUERY_IDS) == PARAMETER_SENSITIVE_QUERY_IDS

    def test_tpch_provider_assigns_exact_mode_with_ride_along_bounds(self):
        """Every query -- parameter-sensitive or not -- carries canonical EXACT
        mode and its answer-file count, so a reference-seed run is exact-checked.
        The parameter-sensitive queries additionally carry the RANGE bounds
        (Q11/18/20) / LOOSE tolerance (Q16) that QueryValidator applies only
        under a non-reference seed. The preserved exact count sits inside the
        query's own bounds."""
        results = get_tpch_expected_results(scale_factor=1.0)
        assert results is not None

        for query_id, (minimum, maximum) in TPCH_RANGE_ROW_COUNT_BOUNDS.items():
            result = results.get_expected_result(query_id)
            assert result is not None
            assert result.validation_mode == ValidationMode.EXACT
            assert result.expected_row_count is not None  # answer-file count preserved
            assert minimum <= result.expected_row_count <= maximum
            assert result.expected_row_count_min == minimum
            assert result.expected_row_count_max == maximum

        q16 = results.get_expected_result("16")
        assert q16 is not None
        assert q16.validation_mode == ValidationMode.EXACT
        assert q16.expected_row_count == 18_314
        assert q16.expected_row_count_min is None
        assert q16.expected_row_count_max is None
        assert q16.loose_tolerance_percent == 50.0

        # The provider no longer advertises a per-query "static" RANGE/LOOSE mode
        # -- the relaxation is a runtime, reference-seed-aware decision.
        for query_id, result in results.query_results.items():
            assert result.validation_mode == ValidationMode.EXACT

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

    @pytest.mark.parametrize("query_id,bounds", sorted(TPCH_RANGE_ROW_COUNT_BOUNDS.items()))
    def test_range_queries_accept_both_documented_bounds_under_non_reference_context(self, query_id, bounds):
        """The old non-reference exclusion must not preempt the provider's
        RANGE mode."""
        set_reference_seed_context(False)
        validator = QueryValidator()
        minimum, maximum = bounds

        for actual_count in (minimum, maximum):
            result = validator.validate_query_result(
                benchmark_type="tpch",
                query_id=query_id,
                actual_row_count=actual_count,
                scale_factor=1.0,
            )
            assert result.is_valid
            assert result.validation_mode == ValidationMode.RANGE

    @pytest.mark.parametrize(
        "query_id,actual_count",
        [(query_id, minimum - 1) for query_id, (minimum, _) in sorted(TPCH_RANGE_ROW_COUNT_BOUNDS.items())]
        + [(query_id, maximum + 1) for query_id, (_, maximum) in sorted(TPCH_RANGE_ROW_COUNT_BOUNDS.items())],
    )
    def test_range_queries_reject_counts_outside_documented_bounds(self, query_id, actual_count):
        set_reference_seed_context(False)
        result = QueryValidator().validate_query_result(
            benchmark_type="tpch",
            query_id=query_id,
            actual_row_count=actual_count,
            scale_factor=1.0,
        )
        assert not result.is_valid
        assert result.validation_mode == ValidationMode.RANGE

    def test_loose_query_uses_tolerance_under_non_reference_context(self):
        set_reference_seed_context(False)
        validator = QueryValidator()

        accepted = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="16",
            actual_row_count=18_000,
            scale_factor=1.0,
        )
        rejected = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="16",
            actual_row_count=9_156,
            scale_factor=1.0,
        )

        assert accepted.is_valid
        assert accepted.validation_mode == ValidationMode.LOOSE
        assert not rejected.is_valid
        assert rejected.validation_mode == ValidationMode.LOOSE

    @pytest.mark.parametrize("query_id,bounds", sorted(TPCH_RANGE_ROW_COUNT_BOUNDS.items()))
    def test_range_query_exact_compared_at_reference_seed(self, query_id, bounds):
        """Under the reference seed a parameter-sensitive RANGE query is
        EXACT-compared against its answer-file count: an in-range but wrong
        count -- the regression an unconditional RANGE mode would have let pass
        (the reviewer's Q11=999-in-[514,1469] case) -- must FAIL, and the exact
        answer must PASS.
        """
        minimum, maximum = bounds
        set_reference_seed_context(True)
        validator = QueryValidator()

        # Derive the pinned reference answer from the registry (never hardcoded).
        expected = validator.registry.get_expected_result("tpch", query_id, 1.0)
        assert expected is not None
        reference_count = expected.get_expected_count(1.0)
        assert reference_count is not None
        assert minimum <= reference_count <= maximum

        # An in-range value that is NOT the exact answer.
        in_range_wrong = maximum if reference_count != maximum else minimum
        assert minimum <= in_range_wrong <= maximum
        assert in_range_wrong != reference_count

        rejected = validator.validate_query_result(
            benchmark_type="tpch",
            query_id=query_id,
            actual_row_count=in_range_wrong,
            scale_factor=1.0,
        )
        assert not rejected.is_valid
        assert rejected.validation_mode == ValidationMode.EXACT

        accepted = validator.validate_query_result(
            benchmark_type="tpch",
            query_id=query_id,
            actual_row_count=reference_count,
            scale_factor=1.0,
        )
        assert accepted.is_valid
        assert accepted.validation_mode == ValidationMode.EXACT

    def test_parameter_sensitive_query_exact_when_context_unset(self):
        """An unset reference-seed context (the default -- qgen defaults, or any
        non-TPC-H caller) keeps EXACT validation for a parameter-sensitive
        query, so an in-range but wrong count still fails (preserves the
        pre-existing always-EXACT behavior for callers that never signal a
        seed)."""
        assert get_reference_seed_context() is None  # sanity: truly unset
        validator = QueryValidator()
        expected = validator.registry.get_expected_result("tpch", "11", 1.0)
        assert expected is not None
        reference_count = expected.get_expected_count(1.0)
        assert reference_count is not None

        minimum, maximum = TPCH_RANGE_ROW_COUNT_BOUNDS["11"]
        in_range_wrong = maximum if reference_count != maximum else minimum
        assert in_range_wrong != reference_count

        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="11",
            actual_row_count=in_range_wrong,  # in-range, wrong answer
            scale_factor=1.0,
        )
        assert not result.is_valid
        assert result.validation_mode == ValidationMode.EXACT

    def test_loose_query_exact_compared_at_reference_seed(self):
        """Q16 is EXACT-compared at the reference seed: a within-±50% but wrong
        count fails, closing the same broadening the reviewer flagged for the
        LOOSE branch."""
        set_reference_seed_context(True)
        validator = QueryValidator()
        # 18_000 is within ±50% of the 18_314 answer but is not the exact count.
        result = validator.validate_query_result(
            benchmark_type="tpch",
            query_id="16",
            actual_row_count=18_000,
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
