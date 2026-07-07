"""
Tests for query plan comparison engine.
"""

import pytest

from benchbox.core.query_plans.comparison import (
    QueryPlanComparator,
    compare_query_plans,
)
from benchbox.core.results.query_plan_models import (
    JoinType,
    LogicalOperator,
    LogicalOperatorType,
    QueryPlanDAG,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestQueryPlanComparison:
    """Test query plan comparison functionality."""

    @pytest.fixture
    def simple_scan_plan(self) -> QueryPlanDAG:
        """Create a simple scan plan."""
        root = LogicalOperator(
            operator_id="scan_1",
            operator_type=LogicalOperatorType.SCAN,
            table_name="orders",
        )
        return QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=root,
        )

    @pytest.fixture
    def simple_scan_plan_different_table(self) -> QueryPlanDAG:
        """Create a simple scan plan with different table."""
        root = LogicalOperator(
            operator_id="scan_1",
            operator_type=LogicalOperatorType.SCAN,
            table_name="customers",
        )
        return QueryPlanDAG(
            query_id="q2",
            platform="duckdb",
            logical_root=root,
        )

    @pytest.fixture
    def join_plan(self) -> QueryPlanDAG:
        """Create a plan with a join."""
        scan_left = LogicalOperator(
            operator_id="scan_1",
            operator_type=LogicalOperatorType.SCAN,
            table_name="orders",
        )
        scan_right = LogicalOperator(
            operator_id="scan_2",
            operator_type=LogicalOperatorType.SCAN,
            table_name="customers",
        )
        join = LogicalOperator(
            operator_id="join_1",
            operator_type=LogicalOperatorType.JOIN,
            join_type=JoinType.INNER,
            children=[scan_left, scan_right],
        )
        return QueryPlanDAG(
            query_id="q3",
            platform="duckdb",
            logical_root=join,
        )

    @pytest.fixture
    def join_plan_different_type(self) -> QueryPlanDAG:
        """Create a plan with a different join type."""
        scan_left = LogicalOperator(
            operator_id="scan_1",
            operator_type=LogicalOperatorType.SCAN,
            table_name="orders",
        )
        scan_right = LogicalOperator(
            operator_id="scan_2",
            operator_type=LogicalOperatorType.SCAN,
            table_name="customers",
        )
        join = LogicalOperator(
            operator_id="join_1",
            operator_type=LogicalOperatorType.JOIN,
            join_type=JoinType.LEFT,
            children=[scan_left, scan_right],
        )
        return QueryPlanDAG(
            query_id="q4",
            platform="duckdb",
            logical_root=join,
        )

    @pytest.fixture
    def complex_plan(self) -> QueryPlanDAG:
        """Create a complex plan with multiple operators."""
        # Build tree: Join -> Filter -> Scan (left), Scan (right)
        scan_left = LogicalOperator(
            operator_id="scan_1",
            operator_type=LogicalOperatorType.SCAN,
            table_name="orders",
        )
        filter_op = LogicalOperator(
            operator_id="filter_1",
            operator_type=LogicalOperatorType.FILTER,
            filter_expressions=["o_orderdate > '2023-01-01'"],
            children=[scan_left],
        )
        scan_right = LogicalOperator(
            operator_id="scan_2",
            operator_type=LogicalOperatorType.SCAN,
            table_name="customers",
        )
        join = LogicalOperator(
            operator_id="join_1",
            operator_type=LogicalOperatorType.JOIN,
            join_type=JoinType.INNER,
            children=[filter_op, scan_right],
        )
        aggregate = LogicalOperator(
            operator_id="agg_1",
            operator_type=LogicalOperatorType.AGGREGATE,
            aggregation_functions=["SUM(o_totalprice)"],
            children=[join],
        )
        return QueryPlanDAG(
            query_id="q5",
            platform="duckdb",
            logical_root=aggregate,
        )

    def test_identical_plans(self, simple_scan_plan):
        """Test comparison of identical plans."""
        result = compare_query_plans(simple_scan_plan, simple_scan_plan)

        assert result.plans_identical is True
        assert result.fingerprints_match is True
        assert result.similarity.overall_similarity == 1.0
        assert result.similarity.matching_operators > 0
        assert result.similarity.type_mismatches == 0
        assert result.similarity.property_mismatches == 0

    def test_different_table_name(self, simple_scan_plan, simple_scan_plan_different_table):
        """Test comparison of plans with different table names."""
        result = compare_query_plans(simple_scan_plan, simple_scan_plan_different_table)

        assert result.plans_identical is False
        assert result.fingerprints_match is False
        assert result.similarity.property_mismatches > 0
        assert result.similarity.overall_similarity < 1.0

        # Should find property mismatch
        property_diffs = [d for d in result.operator_diffs if d.diff_type == "property_mismatch"]
        assert len(property_diffs) > 0
        assert "table_name" in property_diffs[0].differences

    def test_different_join_type(self, join_plan, join_plan_different_type):
        """Test comparison of plans with different join types."""
        result = compare_query_plans(join_plan, join_plan_different_type)

        assert result.plans_identical is False
        assert result.similarity.property_mismatches > 0

        # Should find property mismatch on join operator
        property_diffs = [d for d in result.operator_diffs if d.diff_type == "property_mismatch"]
        assert len(property_diffs) > 0
        assert "join_type" in property_diffs[0].differences

    def test_different_operator_types(self, simple_scan_plan, join_plan):
        """Test comparison of plans with different operator types."""
        result = compare_query_plans(simple_scan_plan, join_plan)

        assert result.plans_identical is False
        assert result.similarity.type_mismatches > 0
        assert result.similarity.overall_similarity < 0.5

    def test_complex_plan_comparison(self, complex_plan):
        """Test comparison of complex plans."""
        # Compare plan to itself
        result = compare_query_plans(complex_plan, complex_plan)

        assert result.plans_identical is True
        assert result.similarity.overall_similarity == 1.0
        assert result.similarity.total_operators_left > 3  # Multiple operators

    def test_similarity_score_calculation(self, join_plan, join_plan_different_type):
        """Test that similarity scores are calculated correctly."""
        result = compare_query_plans(join_plan, join_plan_different_type)

        # Plans have same structure, just different join type
        # Should have high structural similarity (no structure mismatches)
        assert result.similarity.structural_similarity == 1.0
        # All operator types match (join + 2 scans)
        assert result.similarity.operator_similarity == 1.0
        # But lower property similarity due to join type difference (2/3 match)
        assert result.similarity.property_similarity < 1.0
        assert result.similarity.property_mismatches == 1

    def test_structure_mismatch(self, simple_scan_plan, complex_plan):
        """Test detection of structural mismatches."""
        result = compare_query_plans(simple_scan_plan, complex_plan)

        assert result.plans_identical is False
        assert result.similarity.structure_mismatches > 0
        assert result.similarity.overall_similarity < 0.5

    def test_filter_expression_comparison(self):
        """Test comparison of filter expressions."""
        # Plan 1: Single filter
        scan1 = LogicalOperator(
            operator_id="scan_1",
            operator_type=LogicalOperatorType.SCAN,
            table_name="orders",
        )
        filter1 = LogicalOperator(
            operator_id="filter_1",
            operator_type=LogicalOperatorType.FILTER,
            filter_expressions=["o_orderdate > '2023-01-01'"],
            children=[scan1],
        )
        plan1 = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=filter1,
        )

        # Plan 2: Different filter
        scan2 = LogicalOperator(
            operator_id="scan_1",
            operator_type=LogicalOperatorType.SCAN,
            table_name="orders",
        )
        filter2 = LogicalOperator(
            operator_id="filter_1",
            operator_type=LogicalOperatorType.FILTER,
            filter_expressions=["o_orderdate > '2024-01-01'"],
            children=[scan2],
        )
        plan2 = QueryPlanDAG(
            query_id="q2",
            platform="duckdb",
            logical_root=filter2,
        )

        result = compare_query_plans(plan1, plan2)

        assert result.plans_identical is False
        property_diffs = [d for d in result.operator_diffs if d.diff_type == "property_mismatch"]
        assert len(property_diffs) > 0
        assert "filter_expressions" in property_diffs[0].differences

    def test_aggregation_function_comparison(self):
        """Test comparison of aggregation functions."""
        # Plan 1: SUM aggregation
        scan1 = LogicalOperator(
            operator_id="scan_1",
            operator_type=LogicalOperatorType.SCAN,
            table_name="orders",
        )
        agg1 = LogicalOperator(
            operator_id="agg_1",
            operator_type=LogicalOperatorType.AGGREGATE,
            aggregation_functions=["SUM(o_totalprice)"],
            children=[scan1],
        )
        plan1 = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=agg1,
        )

        # Plan 2: AVG aggregation
        scan2 = LogicalOperator(
            operator_id="scan_1",
            operator_type=LogicalOperatorType.SCAN,
            table_name="orders",
        )
        agg2 = LogicalOperator(
            operator_id="agg_1",
            operator_type=LogicalOperatorType.AGGREGATE,
            aggregation_functions=["AVG(o_totalprice)"],
            children=[scan2],
        )
        plan2 = QueryPlanDAG(
            query_id="q2",
            platform="duckdb",
            logical_root=agg2,
        )

        result = compare_query_plans(plan1, plan2)

        assert result.plans_identical is False
        property_diffs = [d for d in result.operator_diffs if d.diff_type == "property_mismatch"]
        assert len(property_diffs) > 0
        assert "aggregation_functions" in property_diffs[0].differences

    def test_summary_generation(self, simple_scan_plan, join_plan):
        """Test that summary is generated."""
        result = compare_query_plans(simple_scan_plan, join_plan)

        assert result.summary
        assert isinstance(result.summary, str)
        assert len(result.summary) > 0

    def test_comparator_reusable(self, simple_scan_plan, join_plan):
        """Test that comparator can be reused for multiple comparisons."""
        comparator = QueryPlanComparator()

        result1 = comparator.compare_plans(simple_scan_plan, simple_scan_plan)
        result2 = comparator.compare_plans(join_plan, join_plan)

        assert result1.plans_identical is True
        assert result2.plans_identical is True

    def test_cross_platform_comparison(self):
        """Test comparison of plans from different platforms."""
        # DuckDB plan
        duckdb_plan = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="scan_1",
                operator_type=LogicalOperatorType.SCAN,
                table_name="orders",
            ),
        )

        # SQLite plan (same logical structure)
        sqlite_plan = QueryPlanDAG(
            query_id="q1",
            platform="sqlite",
            logical_root=LogicalOperator(
                operator_id="scan_1",
                operator_type=LogicalOperatorType.SCAN,
                table_name="orders",
            ),
        )

        result = compare_query_plans(duckdb_plan, sqlite_plan)

        # Should match structurally even though platforms differ
        assert result.similarity.overall_similarity == 1.0

    def test_empty_children_handling(self):
        """Test comparison handles operators with no children."""
        plan1 = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="scan_1",
                operator_type=LogicalOperatorType.SCAN,
                table_name="orders",
                children=None,
            ),
        )

        plan2 = QueryPlanDAG(
            query_id="q2",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="scan_1",
                operator_type=LogicalOperatorType.SCAN,
                table_name="orders",
                children=[],
            ),
        )

        result = compare_query_plans(plan1, plan2)

        # Should handle None vs [] gracefully
        assert result.similarity.overall_similarity == 1.0

    def test_unequal_children_count(self):
        """Test comparison when operators have different numbers of children."""
        # Plan 1: Join with 2 children
        join1 = LogicalOperator(
            operator_id="join_1",
            operator_type=LogicalOperatorType.JOIN,
            join_type=JoinType.INNER,
            children=[
                LogicalOperator(
                    operator_id="scan_1",
                    operator_type=LogicalOperatorType.SCAN,
                    table_name="orders",
                ),
                LogicalOperator(
                    operator_id="scan_2",
                    operator_type=LogicalOperatorType.SCAN,
                    table_name="customers",
                ),
            ],
        )
        plan1 = QueryPlanDAG(query_id="q1", platform="duckdb", logical_root=join1)

        # Plan 2: Join with 1 child (invalid but test error handling)
        join2 = LogicalOperator(
            operator_id="join_1",
            operator_type=LogicalOperatorType.JOIN,
            join_type=JoinType.INNER,
            children=[
                LogicalOperator(
                    operator_id="scan_1",
                    operator_type=LogicalOperatorType.SCAN,
                    table_name="orders",
                ),
            ],
        )
        plan2 = QueryPlanDAG(query_id="q2", platform="duckdb", logical_root=join2)

        result = compare_query_plans(plan1, plan2)

        assert result.plans_identical is False
        assert result.similarity.structure_mismatches > 0


class TestFingerprintIntegrityInComparison:
    """Test that comparator respects fingerprint integrity."""

    def test_identical_comparison_requires_trusted_fingerprints(self):
        """Test that fingerprint fast-path only works with trusted fingerprints."""

        # Create two identical plans
        plan1 = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="scan_1",
                operator_type=LogicalOperatorType.SCAN,
                table_name="orders",
            ),
        )
        plan2 = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="scan_1",
                operator_type=LogicalOperatorType.SCAN,
                table_name="orders",
            ),
        )

        # Both have trusted fingerprints - fast path should work
        assert plan1.is_fingerprint_trusted()
        assert plan2.is_fingerprint_trusted()
        result = compare_query_plans(plan1, plan2)
        assert result.plans_identical is True
        assert result.fingerprints_match is True

    def test_stale_fingerprint_forces_full_comparison(self):
        """Test that stale fingerprint forces full tree comparison."""
        from benchbox.core.results.query_plan_models import FingerprintIntegrity

        # Create identical plans
        plan1 = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="scan_1",
                operator_type=LogicalOperatorType.SCAN,
                table_name="orders",
            ),
        )
        plan2 = QueryPlanDAG(
            query_id="q2",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="scan_1",
                operator_type=LogicalOperatorType.SCAN,
                table_name="orders",
            ),
        )

        # Make plan1's fingerprint untrusted
        plan1.fingerprint_integrity = FingerprintIntegrity.STALE

        # Should not use fast path, but should still find they're similar
        result = compare_query_plans(plan1, plan2)
        # Plans are identical in structure, so similarity should be 1.0
        assert result.similarity.overall_similarity == 1.0
        # But not marked as "plans_identical" because fingerprint was not trusted
        # (would need full comparison which finds they match)

    def test_unverified_fingerprint_forces_full_comparison(self):
        """Test that unverified fingerprint forces full tree comparison."""
        from benchbox.core.results.query_plan_models import FingerprintIntegrity

        # Create a plan and manually set it to unverified
        plan1 = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="scan_1",
                operator_type=LogicalOperatorType.SCAN,
                table_name="orders",
            ),
        )
        plan1.fingerprint_integrity = FingerprintIntegrity.UNVERIFIED

        plan2 = QueryPlanDAG(
            query_id="q2",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="scan_1",
                operator_type=LogicalOperatorType.SCAN,
                table_name="orders",
            ),
        )

        # Even with same fingerprint, should not trust it
        plan1.plan_fingerprint = plan2.plan_fingerprint  # Make them match

        result = compare_query_plans(plan1, plan2)
        # Full comparison should find they match structurally
        assert result.similarity.overall_similarity == 1.0


class TestFingerprintVersionMismatchInComparison:
    """qpc-03: the fingerprint fast path must require matching fingerprint_version
    AND trust; across versions it must fall back to the full tree walk and never
    assert identity from cross-version fingerprint equality."""

    def _plan(self, table: str = "orders") -> QueryPlanDAG:
        return QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="scan_1", operator_type=LogicalOperatorType.SCAN, table_name=table
            ),
        )

    def test_version_mismatch_falls_back_to_tree_walk_even_if_fingerprints_equal(self):
        """Two trusted plans whose fingerprint STRINGS happen to be equal but
        whose fingerprint_version differs must NOT be declared identical via the
        fast path -- equality across versions is meaningless."""
        plan1 = self._plan()
        plan2 = self._plan()
        # Force equal fingerprint strings but different versions.
        plan2.plan_fingerprint = plan1.plan_fingerprint
        plan1.fingerprint_version = 2
        plan2.fingerprint_version = 1
        assert plan1.is_fingerprint_trusted() and plan2.is_fingerprint_trusted()

        result = compare_query_plans(plan1, plan2)

        # Fast path suppressed: not declared identical purely from the equal
        # strings; the tree walk ran (and here the trees do match structurally).
        assert result.plans_identical is False
        assert result.fingerprints_match is False
        assert result.similarity.overall_similarity == 1.0

    def test_same_version_trusted_equal_fingerprints_uses_fast_path(self):
        """Control: same version + trusted + equal fingerprints still fast-paths
        to identical (the optimization is preserved within a version)."""
        plan1 = self._plan()
        plan2 = self._plan()
        assert plan1.fingerprint_version == plan2.fingerprint_version

        result = compare_query_plans(plan1, plan2)

        assert result.plans_identical is True
        assert result.fingerprints_match is True


class TestStringOperatorTypeHandling:
    """Test comparison with string operator types (unknown/unmapped operators)."""

    def test_compare_plans_with_string_operator_types(self):
        """Test that comparison works with string operator types."""
        # Plan 1: String operator type (unknown operator)
        plan1 = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="custom_1",
                operator_type="CustomScan",  # String instead of enum
                table_name="orders",
            ),
        )

        # Plan 2: Identical structure with string operator type
        plan2 = QueryPlanDAG(
            query_id="q2",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="custom_1",
                operator_type="CustomScan",
                table_name="orders",
            ),
        )

        result = compare_query_plans(plan1, plan2)

        # Same structure should match
        assert result.fingerprints_match is True
        assert result.plans_identical is True
        assert result.similarity.overall_similarity == 1.0

    def test_compare_mixed_enum_and_string_types(self):
        """Test comparison where one plan uses enum and other uses matching string."""
        # Plan with enum type
        plan1 = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="scan_1",
                operator_type=LogicalOperatorType.SCAN,
                table_name="orders",
            ),
        )

        # Plan with string type matching the enum value
        plan2 = QueryPlanDAG(
            query_id="q2",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="scan_1",
                operator_type="Scan",  # String matching LogicalOperatorType.SCAN.value
                table_name="orders",
            ),
        )

        result = compare_query_plans(plan1, plan2)

        # Should match because string "Scan" == LogicalOperatorType.SCAN.value
        assert result.plans_identical is True
        assert result.similarity.overall_similarity == 1.0

    def test_compare_different_string_operator_types(self):
        """Test comparison of plans with different string operator types."""
        plan1 = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="op_1",
                operator_type="CustomScan",
            ),
        )

        plan2 = QueryPlanDAG(
            query_id="q2",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="op_1",
                operator_type="IndexScan",
            ),
        )

        result = compare_query_plans(plan1, plan2)

        # Different types should not match
        assert result.plans_identical is False
        assert result.similarity.type_mismatches > 0

        # Verify the diff contains the correct type strings
        type_diffs = [d for d in result.operator_diffs if d.diff_type == "type_mismatch"]
        assert len(type_diffs) > 0
        assert type_diffs[0].differences["left_type"] == "CustomScan"
        assert type_diffs[0].differences["right_type"] == "IndexScan"

    def test_compare_with_string_join_type(self):
        """Test comparison works with string join types."""
        # Plan with string join type
        plan1 = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="join_1",
                operator_type=LogicalOperatorType.JOIN,
                join_type="custom_join",  # String instead of JoinType enum
                children=[
                    LogicalOperator(
                        operator_id="scan_1",
                        operator_type=LogicalOperatorType.SCAN,
                        table_name="orders",
                    ),
                    LogicalOperator(
                        operator_id="scan_2",
                        operator_type=LogicalOperatorType.SCAN,
                        table_name="customers",
                    ),
                ],
            ),
        )

        # Different join type
        plan2 = QueryPlanDAG(
            query_id="q2",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="join_1",
                operator_type=LogicalOperatorType.JOIN,
                join_type="different_join",
                children=[
                    LogicalOperator(
                        operator_id="scan_1",
                        operator_type=LogicalOperatorType.SCAN,
                        table_name="orders",
                    ),
                    LogicalOperator(
                        operator_id="scan_2",
                        operator_type=LogicalOperatorType.SCAN,
                        table_name="customers",
                    ),
                ],
            ),
        )

        result = compare_query_plans(plan1, plan2)

        # Should detect property mismatch
        assert result.plans_identical is False
        property_diffs = [d for d in result.operator_diffs if d.diff_type == "property_mismatch"]
        assert len(property_diffs) > 0
        assert "join_type" in property_diffs[0].differences

    def test_complex_plan_with_mixed_operator_types(self):
        """Test complex plan comparison with mixed enum and string operator types."""
        # Build a complex plan with mix of enum and string types
        plan1 = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="agg_1",
                operator_type=LogicalOperatorType.AGGREGATE,  # Enum
                aggregation_functions=["SUM(total)"],
                children=[
                    LogicalOperator(
                        operator_id="custom_1",
                        operator_type="ParallelHashJoin",  # String (unknown type)
                        children=[
                            LogicalOperator(
                                operator_id="scan_1",
                                operator_type=LogicalOperatorType.SCAN,  # Enum
                                table_name="orders",
                            ),
                            LogicalOperator(
                                operator_id="scan_2",
                                operator_type="IndexSeek",  # String
                                table_name="customers",
                            ),
                        ],
                    ),
                ],
            ),
        )

        result = compare_query_plans(plan1, plan1)

        # Self-comparison should work without exceptions
        assert result.plans_identical is True
        assert result.similarity.overall_similarity == 1.0
