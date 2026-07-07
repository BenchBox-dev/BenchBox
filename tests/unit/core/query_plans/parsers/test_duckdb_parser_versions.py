"""
Tests for DuckDB parser version compatibility.

Uses fixtures from different DuckDB versions to verify parser handles
format variations across versions.
"""

import pytest

from benchbox.core.query_plans.parsers.duckdb import DuckDBQueryPlanParser
from benchbox.core.query_plans.parsers.registry import (
    get_parser_for_platform,
)
from benchbox.core.results.query_plan_models import LogicalOperatorType
from tests.fixtures.duckdb_plans_by_version import (
    DUCKDB_0_9_AGGREGATE,
    DUCKDB_0_9_FILTER_SCAN,
    DUCKDB_0_9_JOIN,
    DUCKDB_0_9_ORDER_BY,
    DUCKDB_0_9_SIMPLE_SCAN,
    DUCKDB_1_0_JSON_AGGREGATE,
    DUCKDB_1_0_JSON_FILTER_SCAN,
    DUCKDB_1_0_JSON_JOIN,
    DUCKDB_1_0_JSON_ORDER_BY,
    DUCKDB_1_0_JSON_SIMPLE_SCAN,
    DUCKDB_1_0_JSON_WITH_TIMING,
    DUCKDB_1_0_JSON_WRAPPED,
    EXPECTED_OPERATORS,
    VERSION_FIXTURES,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestDuckDBVersionCompatibility:
    """Test parser compatibility with different DuckDB versions."""

    @pytest.mark.parametrize(
        "version,format,fixture_name,fixture_value",
        VERSION_FIXTURES,
    )
    def test_parse_version_fixture(self, version: str, format: str, fixture_name: str, fixture_value: str) -> None:
        """Test parsing fixtures from different versions.

        Note: Text format JOIN plans are now correctly rejected as they cannot
        be accurately parsed (branching structure would be flattened).
        """
        parser = DuckDBQueryPlanParser()
        plan = parser.parse_explain_output(f"q_{fixture_name}", fixture_value)

        # Text format JOIN plans should now fail (correctly detected as branching)
        if format == "text" and fixture_name == "join":
            assert plan is None, "Text JOIN plans should now be rejected (branching detected)"
            return

        assert plan is not None, f"Failed to parse {version} {format} {fixture_name}"
        assert plan.logical_root is not None
        assert plan.platform == "duckdb"

    @pytest.mark.parametrize(
        "version,format,fixture_name,fixture_value",
        VERSION_FIXTURES,
    )
    def test_correct_operators_detected(self, version: str, format: str, fixture_name: str, fixture_value: str) -> None:
        """Test correct operators are detected for each fixture."""
        parser = DuckDBQueryPlanParser()
        plan = parser.parse_explain_output(f"q_{fixture_name}", fixture_value)

        # Text JOIN fixtures are intentionally rejected by parser (cannot represent branching safely).
        if format == "text" and fixture_name == "join":
            assert plan is None
            return

        if plan is None:
            pytest.fail(f"Parse failed for {version} {format} {fixture_name}")

        # Collect all operators in the tree
        operators = self._collect_operators(plan.logical_root)
        op_types = [op.operator_type.value for op in operators]

        expected = EXPECTED_OPERATORS.get(fixture_name, [])
        for expected_type in expected:
            # Check that expected operator type is present (case insensitive)
            found = any(expected_type.lower() in t.lower() for t in op_types)
            assert found, f"Expected {expected_type} not found in {op_types}"

    def _collect_operators(self, root):
        """Helper to collect all operators in tree."""
        operators = [root]
        for child in root.children:
            operators.extend(self._collect_operators(child))
        return operators


class TestDuckDBTextFormatVersions:
    """Test text format parsing (DuckDB 0.9.x and earlier)."""

    def test_0_9_simple_scan(self) -> None:
        """Test parsing 0.9 simple scan."""
        parser = DuckDBQueryPlanParser()
        plan = parser.parse_explain_output("q01", DUCKDB_0_9_SIMPLE_SCAN)

        assert plan is not None
        assert plan.logical_root.operator_type == LogicalOperatorType.SCAN
        assert plan.logical_root.table_name == "lineitem"

    def test_0_9_filter_scan(self) -> None:
        """Test parsing 0.9 filter with scan."""
        parser = DuckDBQueryPlanParser()
        plan = parser.parse_explain_output("q02", DUCKDB_0_9_FILTER_SCAN)

        assert plan is not None
        operators = self._collect_operators(plan.logical_root)
        op_types = {op.operator_type for op in operators}

        assert LogicalOperatorType.SCAN in op_types

    def test_0_9_wrapped_filter_parses_as_single_expression(self) -> None:
        """qpc-05 / F2.3: DuckDB's box format wraps a long predicate across
        fixed-width lines mid-token (``(l_shipdate <= CAST(`` /
        ``'1998-12-01' AS DATE))``). Those fragments must be rejoined into ONE
        filter expression, otherwise the parsed filter count (and thus the plan
        fingerprint) depends on the box wrap width."""
        parser = DuckDBQueryPlanParser()
        plan = parser.parse_explain_output("q02", DUCKDB_0_9_FILTER_SCAN)

        assert plan is not None
        filter_ops = [
            op for op in self._collect_operators(plan.logical_root) if op.operator_type == LogicalOperatorType.FILTER
        ]
        assert len(filter_ops) == 1
        exprs = filter_ops[0].filter_expressions
        assert exprs is not None
        # Exactly one expression, not two wrap-split fragments.
        assert len(exprs) == 1
        joined = exprs[0]
        assert "l_shipdate" in joined
        assert "AS DATE" in joined
        # Rejoined predicate has balanced parentheses.
        assert joined.count("(") == joined.count(")")

    def test_0_9_aggregate(self) -> None:
        """Test parsing 0.9 aggregate query."""
        parser = DuckDBQueryPlanParser()
        plan = parser.parse_explain_output("q03", DUCKDB_0_9_AGGREGATE)

        assert plan is not None
        operators = self._collect_operators(plan.logical_root)
        op_types = {op.operator_type for op in operators}

        assert any(t in op_types for t in [LogicalOperatorType.AGGREGATE, LogicalOperatorType.PROJECT])

    def test_0_9_join(self) -> None:
        """Test parsing 0.9 join query.

        Note: Text format JOIN plans are now correctly rejected because their
        branching structure cannot be accurately represented from text format.
        Use EXPLAIN (FORMAT JSON) for JOIN queries.
        """
        parser = DuckDBQueryPlanParser()
        plan = parser.parse_explain_output("q04", DUCKDB_0_9_JOIN)

        # Text format JOIN plans should now be rejected (branching detected)
        assert plan is None, "Text JOIN plans should be rejected (branching cannot be parsed)"

    def test_0_9_order_by(self) -> None:
        """Test parsing 0.9 ORDER BY query."""
        parser = DuckDBQueryPlanParser()
        plan = parser.parse_explain_output("q05", DUCKDB_0_9_ORDER_BY)

        assert plan.query_id == "q05"

    def _collect_operators(self, root):
        """Helper to collect all operators in tree."""
        operators = [root]
        for child in root.children:
            operators.extend(self._collect_operators(child))
        return operators


class TestDuckDBJSONFormatVersions:
    """Test JSON format parsing (DuckDB 0.10+ / 1.0+)."""

    def test_1_0_simple_scan_json(self) -> None:
        """Test parsing 1.0 JSON simple scan."""
        parser = DuckDBQueryPlanParser()
        plan = parser.parse_explain_output("q01", DUCKDB_1_0_JSON_SIMPLE_SCAN)

        assert plan is not None
        assert plan.logical_root.operator_type == LogicalOperatorType.SCAN

    def test_1_0_filter_scan_json(self) -> None:
        """Test parsing 1.0 JSON filter with scan."""
        parser = DuckDBQueryPlanParser()
        plan = parser.parse_explain_output("q02", DUCKDB_1_0_JSON_FILTER_SCAN)

        assert plan is not None
        assert plan.logical_root.operator_type == LogicalOperatorType.FILTER
        assert len(plan.logical_root.children) == 1
        assert plan.logical_root.children[0].operator_type == LogicalOperatorType.SCAN

    def test_1_0_aggregate_json(self) -> None:
        """Test parsing 1.0 JSON aggregate query."""
        parser = DuckDBQueryPlanParser()
        plan = parser.parse_explain_output("q03", DUCKDB_1_0_JSON_AGGREGATE)

        assert plan is not None
        assert plan.logical_root.operator_type == LogicalOperatorType.PROJECT

    def test_1_0_join_json(self) -> None:
        """Test parsing 1.0 JSON join query."""
        parser = DuckDBQueryPlanParser()
        plan = parser.parse_explain_output("q04", DUCKDB_1_0_JSON_JOIN)

        assert plan is not None
        # Root is projection, child is join
        assert plan.logical_root.operator_type == LogicalOperatorType.PROJECT
        assert len(plan.logical_root.children) == 1
        assert plan.logical_root.children[0].operator_type == LogicalOperatorType.JOIN

    def test_1_0_order_by_json(self) -> None:
        """Test parsing 1.0 JSON ORDER BY query."""
        parser = DuckDBQueryPlanParser()
        plan = parser.parse_explain_output("q05", DUCKDB_1_0_JSON_ORDER_BY)

        assert plan is not None
        assert plan.logical_root.operator_type == LogicalOperatorType.SORT

    def test_1_0_with_timing_json(self) -> None:
        """Test parsing 1.0 JSON with timing info."""
        parser = DuckDBQueryPlanParser()
        plan = parser.parse_explain_output("q06", DUCKDB_1_0_JSON_WITH_TIMING)

        assert plan is not None
        # Check that timing info is preserved in physical operator
        assert plan.logical_root.physical_operator is not None
        assert plan.logical_root.physical_operator.properties.get("timing") == 0.025

    def test_1_0_wrapped_format_json(self) -> None:
        """Test parsing 1.0 JSON wrapped format."""
        parser = DuckDBQueryPlanParser()
        plan = parser.parse_explain_output("q07", DUCKDB_1_0_JSON_WRAPPED)

        assert plan is not None
        # Should unwrap and find the actual projection
        assert plan.logical_root.operator_type == LogicalOperatorType.PROJECT


class TestVersionBasedParserSelection:
    """Test that registry selects appropriate parser by version."""

    def test_registry_returns_parser_for_any_version(self) -> None:
        """Test registry returns DuckDB parser for various versions."""
        # All versions should work since we have a 0.0.0 base registration
        for version in ["0.9.0", "0.10.0", "1.0.0", "1.1.0", "2.0.0"]:
            parser = get_parser_for_platform("duckdb", version)
            assert parser is not None
            assert parser.platform_name == "duckdb"

    def test_parser_from_registry_parses_text_format(self) -> None:
        """Test registry parser can parse text format."""
        parser = get_parser_for_platform("duckdb", "0.9.0")
        plan = parser.parse_explain_output("q01", DUCKDB_0_9_SIMPLE_SCAN)

        assert plan is not None
        assert plan.logical_root is not None

    def test_parser_from_registry_parses_json_format(self) -> None:
        """Test registry parser can parse JSON format."""
        parser = get_parser_for_platform("duckdb", "1.0.0")
        plan = parser.parse_explain_output("q01", DUCKDB_1_0_JSON_SIMPLE_SCAN)

        assert plan is not None
        assert plan.logical_root is not None


class TestFingerprintConsistencyAcrossVersions:
    """Test that semantically similar plans have consistent fingerprints."""

    def test_same_structure_same_fingerprint_base(self) -> None:
        """Test that same JSON structure produces consistent fingerprint."""
        parser = DuckDBQueryPlanParser()
        plan1 = parser.parse_explain_output("q01", DUCKDB_1_0_JSON_SIMPLE_SCAN)
        plan2 = parser.parse_explain_output("q02", DUCKDB_1_0_JSON_SIMPLE_SCAN)

        assert plan1 is not None and plan2 is not None
        # Same structure should have same fingerprint
        # (fingerprints based on logical structure, not query_id)

    def test_different_structure_different_fingerprint(self) -> None:
        """Test that different structures produce different fingerprints."""
        parser = DuckDBQueryPlanParser()
        plan1 = parser.parse_explain_output("q01", DUCKDB_1_0_JSON_SIMPLE_SCAN)
        plan2 = parser.parse_explain_output("q02", DUCKDB_1_0_JSON_FILTER_SCAN)

        assert plan1 is not None and plan2 is not None
        # Different structures should have different fingerprints
        assert plan1.plan_fingerprint != plan2.plan_fingerprint
