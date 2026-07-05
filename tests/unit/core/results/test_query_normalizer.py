"""Unit tests for query result normalization utilities."""

from __future__ import annotations

import pytest

from benchbox.core.results.models import (
    QUERY_RUN_TYPE_MEASUREMENT,
    QUERY_RUN_TYPE_METADATA,
    QUERY_RUN_TYPE_SUMMARY,
    QUERY_RUN_TYPE_WARMUP,
    QUERY_RUN_TYPES,
)
from benchbox.core.results.query_normalizer import (
    QueryResultInput,
    format_query_id,
    normalize_query_id,
    normalize_query_result,
    normalize_query_results,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_canonical_query_run_type_constants_are_defined() -> None:
    assert QUERY_RUN_TYPE_WARMUP in QUERY_RUN_TYPES
    assert QUERY_RUN_TYPE_MEASUREMENT in QUERY_RUN_TYPES
    assert QUERY_RUN_TYPE_METADATA in QUERY_RUN_TYPES
    assert QUERY_RUN_TYPE_SUMMARY in QUERY_RUN_TYPES


class TestNormalizeQueryId:
    """Tests for normalize_query_id function."""

    def test_normalize_with_q_prefix(self) -> None:
        """Test normalizing query ID with Q prefix."""
        assert normalize_query_id("Q1") == "1"
        assert normalize_query_id("Q21") == "21"
        assert normalize_query_id("Q99") == "99"

    def test_normalize_lowercase_q_prefix(self) -> None:
        """Test normalizing query ID with lowercase q prefix."""
        assert normalize_query_id("q1") == "1"
        assert normalize_query_id("q21") == "21"

    def test_normalize_without_prefix(self) -> None:
        """Test normalizing query ID without prefix."""
        assert normalize_query_id("1") == "1"
        assert normalize_query_id("21") == "21"
        assert normalize_query_id("99") == "99"

    def test_normalize_query_prefix(self) -> None:
        """Test normalizing query ID with QUERY prefix."""
        assert normalize_query_id("QUERY_1") == "1"
        assert normalize_query_id("query_21") == "21"
        assert normalize_query_id("QUERY1") == "1"

    def test_normalize_integer_input(self) -> None:
        """Test normalizing integer input."""
        assert normalize_query_id(1) == "1"
        assert normalize_query_id(21) == "21"

    def test_normalize_with_whitespace(self) -> None:
        """Test normalizing query ID with whitespace."""
        assert normalize_query_id("  Q1  ") == "1"
        assert normalize_query_id("Q21 ") == "21"

    def test_normalize_with_suffix(self) -> None:
        """Test normalizing query ID with suffixes."""
        assert normalize_query_id("Q1.sql") == "1"
        assert normalize_query_id("query_12.txt") == "12"

    def test_normalize_preserves_ssb_dot_notation(self) -> None:
        """SSB query IDs use dot notation (Q1.1, Q3.4) and must not be truncated.

        Bug: the old code did split(".", 1)[0] which collapsed Q3.1/Q3.2/Q3.3/Q3.4
        all to "3", causing plan capture to only keep the last query's plan.
        """
        assert normalize_query_id("Q1.1") == "1.1"
        assert normalize_query_id("Q1.2") == "1.2"
        assert normalize_query_id("Q1.3") == "1.3"
        assert normalize_query_id("Q2.1") == "2.1"
        assert normalize_query_id("Q3.1") == "3.1"
        assert normalize_query_id("Q3.2") == "3.2"
        assert normalize_query_id("Q3.3") == "3.3"
        assert normalize_query_id("Q3.4") == "3.4"
        assert normalize_query_id("Q4.1") == "4.1"
        assert normalize_query_id("Q4.2") == "4.2"
        assert normalize_query_id("Q4.3") == "4.3"
        # File extensions must still be stripped (alpha suffix only)
        assert normalize_query_id("Q1.sql") == "1"
        assert normalize_query_id("3.1.sql") == "3.1"

    def test_normalize_preserves_variant_suffix(self) -> None:
        """TPC-DS/TPC-H variant suffixes should remain distinct."""
        assert normalize_query_id("14a") == "14a"
        assert normalize_query_id("Q14A") == "14a"
        assert normalize_query_id("query_39b") == "39b"

    def test_normalize_strips_q_from_named_queries(self) -> None:
        """Q prefix should be stripped from non-numeric query names."""
        assert normalize_query_id("Qfilter_decimal_selective") == "filter_decimal_selective"
        assert normalize_query_id("Qaggregation_groupby_large") == "aggregation_groupby_large"
        assert normalize_query_id("Qempty_build_join") == "empty_build_join"
        assert normalize_query_id("Qtopn") == "topn"

    def test_normalize_preserves_bare_names_without_q(self) -> None:
        """Names without Q prefix should pass through unchanged."""
        assert normalize_query_id("filter_decimal_selective") == "filter_decimal_selective"
        assert normalize_query_id("aggregation_groupby") == "aggregation_groupby"


class TestFormatQueryId:
    """Tests for format_query_id function."""

    def test_format_with_prefix(self) -> None:
        """Test formatting query ID with Q prefix."""
        assert format_query_id("1") == "Q1"
        assert format_query_id("21") == "Q21"
        assert format_query_id("Q1") == "Q1"  # Already has prefix

    def test_format_without_prefix(self) -> None:
        """Test formatting query ID without prefix."""
        assert format_query_id("1", with_prefix=False) == "1"
        assert format_query_id("Q1", with_prefix=False) == "1"

    def test_format_integer_input(self) -> None:
        """Test formatting integer input."""
        assert format_query_id(1) == "Q1"
        assert format_query_id(21) == "Q21"


class TestNormalizeQueryResult:
    """Tests for normalize_query_result function."""

    def test_normalize_basic_result(self) -> None:
        """Test normalizing a basic query result."""
        raw = {
            "query_id": "Q1",
            "execution_time_seconds": 1.5,
            "rows_returned": 100,
            "status": "SUCCESS",
        }
        result = normalize_query_result(raw)

        assert result.query_id == "1"
        assert result.execution_time_seconds == 1.5
        assert result.rows_returned == 100
        assert result.status == "SUCCESS"
        assert result.iteration == 1
        assert result.stream_id == 0
        assert result.run_type == "measurement"

    def test_normalize_with_iteration_and_stream(self) -> None:
        """Test normalizing result with iteration and stream info."""
        raw = {
            "query_id": "Q1",
            "execution_time_seconds": 1.5,
            "rows_returned": 100,
            "status": "SUCCESS",
            "iteration": 2,
            "stream_id": 3,
        }
        result = normalize_query_result(raw)

        assert result.iteration == 2
        assert result.stream_id == 3
        assert result.run_type == "measurement"

    def test_normalize_preserves_explicit_run_type_over_iteration_inference(self) -> None:
        """Explicit producer run_type should win over inferred fallback values."""
        raw = {
            "query_id": "Q1",
            "execution_time_seconds": 1.5,
            "rows_returned": 100,
            "status": "SUCCESS",
            "iteration": 1,
            "run_type": "warmup",
        }
        result = normalize_query_result(raw)

        assert result.iteration == 1
        assert result.run_type == "warmup"

    def test_normalize_preserves_zero_iteration(self) -> None:
        """Test that iteration=0 is preserved."""
        raw = {
            "query_id": "Q1",
            "execution_time_seconds": 1.5,
            "rows_returned": 100,
            "status": "SUCCESS",
            "iteration": 0,
            "stream_id": 0,
        }
        result = normalize_query_result(raw)

        assert result.iteration == 0
        assert result.stream_id == 0
        assert result.run_type == "warmup"

    def test_normalize_execution_time_from_ms(self) -> None:
        """Test normalizing execution time from milliseconds."""
        raw = {
            "query_id": "Q1",
            "execution_time_ms": 1500,
            "rows_returned": 100,
            "status": "SUCCESS",
        }
        result = normalize_query_result(raw)

        assert result.execution_time_seconds == 1.5

    def test_normalize_alternative_field_names(self) -> None:
        """Test normalizing with alternative field names."""
        raw = {
            "id": "Q1",
            "execution_time_ms": 1500,
            "rows": 100,
            "status": "SUCCEEDED",  # Alternative success value
        }
        result = normalize_query_result(raw)

        assert result.query_id == "1"
        assert result.execution_time_seconds == 1.5
        assert result.rows_returned == 100
        assert result.status == "SUCCESS"  # Normalized

    def test_normalize_prefers_execution_time_seconds_when_multiple_keys(self) -> None:
        """Canonical execution_time_seconds should win over legacy timing keys."""
        raw = {
            "query_id": "Q1",
            "execution_time_seconds": 1.25,
            "execution_time": 9.99,
            "execution_time_ms": 9999,
            "rows_returned": 100,
            "status": "SUCCESS",
        }
        result = normalize_query_result(raw)

        assert result.execution_time_seconds == 1.25

    def test_normalize_ignores_legacy_execution_time_without_explicit_units(self) -> None:
        """Legacy execution_time is ignored to avoid unit ambiguity."""
        raw = {
            "query_id": "Q1",
            "execution_time": 1.5,
            "rows_returned": 100,
            "status": "SUCCESS",
        }
        result = normalize_query_result(raw)

        assert result.execution_time_seconds == 0.0

    def test_normalize_failed_result(self) -> None:
        """Test normalizing a failed query result."""
        raw = {
            "query_id": "Q1",
            "execution_time_seconds": 0.0,
            "rows_returned": 0,
            "status": "FAILED",
            "error_message": "Timeout occurred",
        }
        result = normalize_query_result(raw)

        assert result.status == "FAILED"
        assert result.error_message == "Timeout occurred"

    def test_normalize_with_cost(self) -> None:
        """Test normalizing result with cost information."""
        raw = {
            "query_id": "Q1",
            "execution_time_seconds": 1.5,
            "rows_returned": 100,
            "status": "SUCCESS",
            "cost": 0.05,
        }
        result = normalize_query_result(raw)

        assert result.cost == 0.05

    def test_normalize_with_row_count_validation(self) -> None:
        """Test normalizing result with row count validation."""
        raw = {
            "query_id": "Q1",
            "execution_time_seconds": 1.5,
            "rows_returned": 100,
            "status": "SUCCESS",
            "row_count_validation": {"expected": 100, "actual": 100, "status": "PASSED"},
        }
        result = normalize_query_result(raw)

        assert result.row_count_validation == {"expected": 100, "actual": 100, "status": "PASSED"}

    def test_normalize_with_defaults(self) -> None:
        """Test normalizing with custom defaults."""
        raw = {
            "query_id": "Q1",
            "execution_time_seconds": 1.5,
            "status": "SUCCESS",
        }
        result = normalize_query_result(raw, default_iteration=5, default_stream_id=2)

        assert result.iteration == 5
        assert result.stream_id == 2

    def test_normalize_preserves_test_type(self) -> None:
        """test_type (the combined-run phase discriminator stamped by platform
        adapters, e.g. benchbox/platforms/base/execution.py) must survive
        normalization - it's how build_plans_payload disambiguates a power row
        and a throughput row for the same query_id/stream_id in a combined run."""
        raw = {
            "query_id": "Q1",
            "execution_time_seconds": 1.5,
            "rows_returned": 100,
            "status": "SUCCESS",
            "test_type": "throughput",
        }
        result = normalize_query_result(raw)

        assert result.test_type == "throughput"

    def test_normalize_test_type_defaults_to_none(self) -> None:
        """Standard single-phase runs never set test_type; normalization must not
        invent a value."""
        raw = {
            "query_id": "Q1",
            "execution_time_seconds": 1.5,
            "rows_returned": 100,
            "status": "SUCCESS",
        }
        result = normalize_query_result(raw)

        assert result.test_type is None


class TestNormalizeQueryResults:
    """Tests for normalize_query_results function."""

    def test_normalize_multiple_results(self) -> None:
        """Test normalizing multiple query results."""
        raw_results = [
            {"query_id": "Q1", "execution_time_seconds": 1.0, "status": "SUCCESS"},
            {"query_id": "Q2", "execution_time_seconds": 2.0, "status": "SUCCESS"},
            {"query_id": "Q3", "execution_time_seconds": 3.0, "status": "FAILED"},
        ]
        results = normalize_query_results(raw_results)

        assert len(results) == 3
        assert all(isinstance(r, QueryResultInput) for r in results)
        assert results[0].query_id == "1"
        assert results[1].query_id == "2"
        assert results[2].query_id == "3"

    def test_normalize_empty_list(self) -> None:
        """Test normalizing empty results list."""
        results = normalize_query_results([])
        assert results == []

    def test_normalize_with_default_stream_id(self) -> None:
        """Test normalizing with default stream ID."""
        raw_results = [
            {"query_id": "Q1", "execution_time_seconds": 1.0, "status": "SUCCESS"},
        ]
        results = normalize_query_results(raw_results, default_stream_id=5)

        assert results[0].stream_id == 5

    def test_normalize_preserves_explicit_iteration(self) -> None:
        """Test that explicit iteration values are preserved."""
        raw_results = [
            {"query_id": "Q1", "execution_time_seconds": 1.0, "status": "SUCCESS", "iteration": 3},
        ]
        results = normalize_query_results(raw_results)

        assert results[0].iteration == 3


class TestQueryResultInput:
    """Tests for QueryResultInput dataclass."""

    def test_create_basic(self) -> None:
        """Test creating a basic QueryResultInput."""
        result = QueryResultInput(
            query_id="1",
            execution_time_seconds=1.5,
            rows_returned=100,
            status="SUCCESS",
        )

        assert result.query_id == "1"
        assert result.execution_time_seconds == 1.5
        assert result.rows_returned == 100
        assert result.status == "SUCCESS"
        assert result.iteration == 1
        assert result.stream_id == 0
        assert result.error_message is None

    def test_create_with_all_fields(self) -> None:
        """Test creating QueryResultInput with all fields."""
        result = QueryResultInput(
            query_id="21",
            execution_time_seconds=2.5,
            rows_returned=500,
            status="FAILED",
            iteration=3,
            stream_id=2,
            error_message="Query timeout",
            cost=0.10,
            run_type="measurement",
            row_count_validation={"status": "PASSED"},
        )

        assert result.query_id == "21"
        assert result.execution_time_seconds == 2.5
        assert result.rows_returned == 500
        assert result.status == "FAILED"
        assert result.iteration == 3
        assert result.stream_id == 2
        assert result.error_message == "Query timeout"
        assert result.cost == 0.10
        assert result.run_type == "measurement"
        assert result.row_count_validation == {"status": "PASSED"}
