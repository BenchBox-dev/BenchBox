"""
Unit tests for query plan data models.

Tests cover:
- Model instantiation and validation
- Operator tree construction and traversal
- Fingerprint computation and uniqueness
- JSON serialization round-trips
- Edge cases and error handling
"""

import json

import pytest

from benchbox.core.results.query_plan_models import (
    FINGERPRINT_VERSION,
    LEGACY_FINGERPRINT_VERSION,
    AggregateFunction,
    FingerprintIntegrity,
    JoinType,
    LogicalOperator,
    LogicalOperatorType,
    PhysicalOperator,
    QueryPlanDAG,
    _normalize_literal_text,
    compute_plan_fingerprint,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _scan(table: str, operator_id: str = "scan") -> LogicalOperator:
    return LogicalOperator(operator_type=LogicalOperatorType.SCAN, operator_id=operator_id, table_name=table)


class TestFingerprintV2Encoding:
    """qpc-03: the v2 structural encoding closes the F2.1 collision classes and
    versions fingerprints so cross-version equality is never assumed."""

    def test_sibling_children_vs_nested_chain_are_distinguished(self) -> None:
        """F2.1 tree shape: Join[Scan(t1), Scan(t2)] (two siblings) and
        Join[Scan(t1) -> Scan(t2)] (a nested chain) must NOT collide. The v1
        pipe-joined encoding produced ``Join|Scan|table:t1|Scan|table:t2`` for
        both."""
        siblings = LogicalOperator(
            operator_type=LogicalOperatorType.JOIN,
            operator_id="j",
            children=[_scan("t1", "s1"), _scan("t2", "s2")],
        )
        nested_inner = _scan("t1", "s1")
        nested_inner.children = [_scan("t2", "s2")]
        nested = LogicalOperator(operator_type=LogicalOperatorType.JOIN, operator_id="j", children=[nested_inner])

        assert siblings.get_structural_signature() != nested.get_structural_signature()
        assert compute_plan_fingerprint(siblings) != compute_plan_fingerprint(nested)

    def test_filter_list_separator_injection_is_distinguished(self) -> None:
        """F2.1 separator injection: two filters ["a","b"] must NOT collide with
        a single filter ["a,b"] (the v1 ``,``-join made both ``filters:a,b``)."""
        two = LogicalOperator(operator_type=LogicalOperatorType.FILTER, operator_id="f", filter_expressions=["a", "b"])
        one = LogicalOperator(operator_type=LogicalOperatorType.FILTER, operator_id="f", filter_expressions=["a,b"])

        assert two.get_structural_signature() != one.get_structural_signature()

    def test_table_name_field_injection_is_distinguished(self) -> None:
        """F2.1 separator injection: a table_name that embeds the v1 field
        syntax (``x|filters:y``) must NOT collide with table ``x`` + filter
        ``y``."""
        crafted = LogicalOperator(operator_type=LogicalOperatorType.SCAN, operator_id="s", table_name="x|filters:y")
        genuine = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN, operator_id="s", table_name="x", filter_expressions=["y"]
        )

        assert crafted.get_structural_signature() != genuine.get_structural_signature()

    def test_signature_is_canonical_json(self) -> None:
        """The v2 signature is parseable canonical JSON with structural keys."""
        op = LogicalOperator(
            operator_type=LogicalOperatorType.JOIN,
            operator_id="j",
            join_type=JoinType.INNER,
            children=[_scan("t1"), _scan("t2")],
        )
        parsed = json.loads(op.get_structural_signature())
        assert parsed["op"] == "Join"
        assert parsed["join"] == "inner"
        assert [c["table"] for c in parsed["children"]] == ["t1", "t2"]

    def test_set_like_fields_stay_order_independent(self) -> None:
        """join_cond / filters / aggs remain set-like (sorted), so reordering
        them does not change the fingerprint."""
        a = LogicalOperator(
            operator_type=LogicalOperatorType.FILTER, operator_id="f", filter_expressions=["a", "b", "c"]
        )
        b = LogicalOperator(
            operator_type=LogicalOperatorType.FILTER, operator_id="f", filter_expressions=["c", "a", "b"]
        )
        assert a.get_structural_signature() == b.get_structural_signature()

    def test_ordered_fields_are_order_sensitive(self) -> None:
        """proj / group / sort preserve order (they affect output), so a
        reorder DOES change the fingerprint."""
        a = LogicalOperator(
            operator_type=LogicalOperatorType.PROJECT, operator_id="p", projection_expressions=["x", "y"]
        )
        b = LogicalOperator(
            operator_type=LogicalOperatorType.PROJECT, operator_id="p", projection_expressions=["y", "x"]
        )
        assert a.get_structural_signature() != b.get_structural_signature()


class TestFingerprintVersioningAndIntegrity:
    """qpc-03 / F2.2: honest integrity states and version handling on load."""

    def test_fresh_plan_is_current_version_and_verified(self) -> None:
        plan = QueryPlanDAG(query_id="q", platform="duckdb", logical_root=_scan("t"))
        assert plan.fingerprint_version == FINGERPRINT_VERSION
        assert plan.fingerprint_integrity == FingerprintIntegrity.VERIFIED
        assert plan.is_fingerprint_trusted()

    def test_to_dict_carries_fingerprint_version(self) -> None:
        plan = QueryPlanDAG(query_id="q", platform="duckdb", logical_root=_scan("t"))
        assert plan.to_dict()["fingerprint_version"] == FINGERPRINT_VERSION

    def test_from_dict_roundtrips_version_and_verifies(self) -> None:
        plan = QueryPlanDAG(query_id="q", platform="duckdb", logical_root=_scan("t"))
        restored = QueryPlanDAG.from_dict(plan.to_dict())
        assert restored.fingerprint_version == FINGERPRINT_VERSION
        assert restored.fingerprint_integrity == FingerprintIntegrity.VERIFIED

    def test_from_dict_absent_fingerprint_is_recomputed_not_verified(self) -> None:
        """F2.2 trust laundering: deleting the stored fingerprint must yield
        RECOMPUTED (untrusted-for-provenance), NOT VERIFIED -- otherwise
        dropping the field bypasses stale-tamper detection."""
        data = QueryPlanDAG(query_id="q", platform="duckdb", logical_root=_scan("t")).to_dict()
        data.pop("plan_fingerprint")

        restored = QueryPlanDAG.from_dict(data)

        assert restored.fingerprint_integrity == FingerprintIntegrity.RECOMPUTED
        # RECOMPUTED is still "trusted" for internal consistency (it was just
        # computed from the tree), but it is explicitly NOT VERIFIED.
        assert restored.fingerprint_integrity != FingerprintIntegrity.VERIFIED

    def test_from_dict_tampered_fingerprint_is_stale(self) -> None:
        data = QueryPlanDAG(query_id="q", platform="duckdb", logical_root=_scan("t")).to_dict()
        data["plan_fingerprint"] = "deadbeef" * 8  # does not match the tree

        restored = QueryPlanDAG.from_dict(data)

        assert restored.fingerprint_integrity == FingerprintIntegrity.STALE
        assert not restored.is_fingerprint_trusted()

    def test_legacy_bundle_without_version_loads_as_v1_and_is_stale(self) -> None:
        """must_preserve: an old bundle (v1 fingerprint, no fingerprint_version)
        still LOADS. Its stored v1 fingerprint recomputes to a different v2
        value, so it lands STALE (untrusted) and will compare via tree walk --
        never via cross-version fingerprint equality."""
        legacy = {
            "query_id": "q",
            "platform": "duckdb",
            "logical_root": _scan("t").to_dict(),
            "plan_fingerprint": "Scan|table:t",  # a v1-style pipe-joined stand-in
            # no fingerprint_version key
        }

        restored = QueryPlanDAG.from_dict(legacy)

        assert restored.fingerprint_version == LEGACY_FINGERPRINT_VERSION
        assert restored.fingerprint_integrity == FingerprintIntegrity.STALE
        assert not restored.is_fingerprint_trusted()


class TestPhysicalOperator:
    """Test PhysicalOperator dataclass."""

    def test_basic_instantiation(self) -> None:
        """Test creating a basic physical operator."""
        op = PhysicalOperator(
            operator_type="SeqScan",
            operator_id="scan_1",
            properties={"cost": 100.0, "rows": 1000},
            platform_metadata={"table_oid": 12345},
        )

        assert op.operator_type == "SeqScan"
        assert op.operator_id == "scan_1"
        assert op.properties["cost"] == 100.0
        assert op.platform_metadata["table_oid"] == 12345

    def test_default_properties(self) -> None:
        """Test that properties and metadata default to empty dicts."""
        op = PhysicalOperator(operator_type="HashJoin", operator_id="join_1")

        assert op.properties == {}
        assert op.platform_metadata == {}

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        op = PhysicalOperator(
            operator_type="IndexScan",
            operator_id="idx_1",
            properties={"cost": 50.0},
            platform_metadata={"index_name": "idx_customer_pk"},
        )

        result = op.to_dict()

        assert result == {
            "operator_type": "IndexScan",
            "operator_id": "idx_1",
            "properties": {"cost": 50.0},
            "platform_metadata": {"index_name": "idx_customer_pk"},
        }

    def test_from_dict(self) -> None:
        """Test deserialization from dictionary."""
        data = {
            "operator_type": "HashAggregate",
            "operator_id": "agg_1",
            "properties": {"estimated_rows": 100},
            "platform_metadata": {"parallel_workers": 4},
        }

        op = PhysicalOperator.from_dict(data)

        assert op.operator_type == "HashAggregate"
        assert op.operator_id == "agg_1"
        assert op.properties == {"estimated_rows": 100}
        assert op.platform_metadata == {"parallel_workers": 4}

    def test_round_trip_serialization(self) -> None:
        """Test that to_dict -> from_dict preserves all data."""
        original = PhysicalOperator(
            operator_type="MergeJoin",
            operator_id="join_2",
            properties={"cost": 250.0, "rows": 5000, "memory_mb": 128},
            platform_metadata={"join_algorithm": "sort-merge"},
        )

        serialized = original.to_dict()
        deserialized = PhysicalOperator.from_dict(serialized)

        assert deserialized.operator_type == original.operator_type
        assert deserialized.operator_id == original.operator_id
        assert deserialized.properties == original.properties
        assert deserialized.platform_metadata == original.platform_metadata


class TestLogicalOperator:
    """Test LogicalOperator dataclass."""

    def test_basic_scan_operator(self) -> None:
        """Test creating a simple Scan operator."""
        op = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="lineitem",
        )

        assert op.operator_type == LogicalOperatorType.SCAN
        assert op.operator_id == "scan_1"
        assert op.table_name == "lineitem"
        assert op.children == []

    def test_join_operator(self) -> None:
        """Test creating a Join operator with children."""
        left_scan = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="orders",
        )
        right_scan = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_2",
            table_name="customer",
        )
        join = LogicalOperator(
            operator_type=LogicalOperatorType.JOIN,
            operator_id="join_1",
            join_type=JoinType.INNER,
            join_conditions=["o_custkey = c_custkey"],
            children=[left_scan, right_scan],
        )

        assert join.operator_type == LogicalOperatorType.JOIN
        assert join.join_type == JoinType.INNER
        assert len(join.children) == 2
        assert join.children[0].table_name == "orders"
        assert join.children[1].table_name == "customer"

    def test_aggregate_operator(self) -> None:
        """Test Aggregate operator with aggregation functions."""
        scan = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="lineitem",
        )
        agg = LogicalOperator(
            operator_type=LogicalOperatorType.AGGREGATE,
            operator_id="agg_1",
            aggregation_functions=["sum(l_extendedprice)", "count(*)"],
            group_by_keys=["l_orderkey"],
            children=[scan],
        )

        assert agg.operator_type == LogicalOperatorType.AGGREGATE
        assert agg.aggregation_functions == ["sum(l_extendedprice)", "count(*)"]
        assert agg.group_by_keys == ["l_orderkey"]
        assert len(agg.children) == 1

    def test_sort_operator(self) -> None:
        """Test Sort operator with sort keys."""
        scan = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="orders",
        )
        sort = LogicalOperator(
            operator_type=LogicalOperatorType.SORT,
            operator_id="sort_1",
            sort_keys=[
                {"expr": "o_orderdate", "direction": "DESC"},
                {"expr": "o_totalprice", "direction": "ASC"},
            ],
            children=[scan],
        )

        assert sort.operator_type == LogicalOperatorType.SORT
        assert len(sort.sort_keys) == 2
        assert sort.sort_keys[0]["expr"] == "o_orderdate"
        assert sort.sort_keys[0]["direction"] == "DESC"

    def test_filter_operator(self) -> None:
        """Test Filter operator with predicates."""
        scan = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="lineitem",
        )
        filter_op = LogicalOperator(
            operator_type=LogicalOperatorType.FILTER,
            operator_id="filter_1",
            filter_expressions=["l_shipdate >= '1994-01-01'", "l_quantity > 10"],
            children=[scan],
        )

        assert filter_op.operator_type == LogicalOperatorType.FILTER
        assert len(filter_op.filter_expressions) == 2
        assert "l_shipdate" in filter_op.filter_expressions[0]

    def test_limit_offset_operator(self) -> None:
        """Test Limit operator with offset."""
        scan = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="orders",
        )
        limit = LogicalOperator(
            operator_type=LogicalOperatorType.LIMIT,
            operator_id="limit_1",
            limit_count=100,
            offset_count=50,
            children=[scan],
        )

        assert limit.operator_type == LogicalOperatorType.LIMIT
        assert limit.limit_count == 100
        assert limit.offset_count == 50

    def test_operator_with_physical_layer(self) -> None:
        """Test logical operator linked to physical operator."""
        physical = PhysicalOperator(
            operator_type="HashAggregate",
            operator_id="phys_agg_1",
            properties={"cost": 500.0, "memory_mb": 256},
        )
        logical = LogicalOperator(
            operator_type=LogicalOperatorType.AGGREGATE,
            operator_id="log_agg_1",
            physical_operator=physical,
        )

        assert logical.physical_operator is not None
        assert logical.physical_operator.operator_type == "HashAggregate"
        assert logical.physical_operator.properties["cost"] == 500.0

    def test_to_dict_simple(self) -> None:
        """Test serialization of simple operator."""
        op = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="orders",
        )

        result = op.to_dict()

        assert result["operator_type"] == "Scan"
        assert result["operator_id"] == "scan_1"
        assert result["table_name"] == "orders"
        assert result["children"] == []

    def test_to_dict_with_tree(self) -> None:
        """Test serialization of operator tree."""
        scan = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="lineitem",
        )
        filter_op = LogicalOperator(
            operator_type=LogicalOperatorType.FILTER,
            operator_id="filter_1",
            filter_expressions=["l_shipdate >= '1994-01-01'"],
            children=[scan],
        )

        result = filter_op.to_dict()

        assert result["operator_type"] == "Filter"
        assert result["filter_expressions"] == ["l_shipdate >= '1994-01-01'"]
        assert len(result["children"]) == 1
        assert result["children"][0]["operator_type"] == "Scan"
        assert result["children"][0]["table_name"] == "lineitem"

    def test_from_dict_simple(self) -> None:
        """Test deserialization of simple operator."""
        data = {
            "operator_type": "Scan",
            "operator_id": "scan_1",
            "table_name": "customer",
            "properties": {},
            "children": [],
            "physical_operator": None,
            "join_type": None,
            "join_conditions": None,
            "filter_expressions": None,
            "aggregation_functions": None,
            "group_by_keys": None,
            "sort_keys": None,
            "projection_expressions": None,
            "limit_count": None,
            "offset_count": None,
        }

        op = LogicalOperator.from_dict(data)

        assert op.operator_type == LogicalOperatorType.SCAN
        assert op.table_name == "customer"

    def test_from_dict_with_tree(self) -> None:
        """Test deserialization of operator tree."""
        data = {
            "operator_type": "Join",
            "operator_id": "join_1",
            "join_type": "inner",
            "join_conditions": ["o_custkey = c_custkey"],
            "properties": {},
            "children": [
                {
                    "operator_type": "Scan",
                    "operator_id": "scan_1",
                    "table_name": "orders",
                    "properties": {},
                    "children": [],
                    "physical_operator": None,
                    "join_type": None,
                    "join_conditions": None,
                    "filter_expressions": None,
                    "aggregation_functions": None,
                    "group_by_keys": None,
                    "sort_keys": None,
                    "projection_expressions": None,
                    "limit_count": None,
                    "offset_count": None,
                },
                {
                    "operator_type": "Scan",
                    "operator_id": "scan_2",
                    "table_name": "customer",
                    "properties": {},
                    "children": [],
                    "physical_operator": None,
                    "join_type": None,
                    "join_conditions": None,
                    "filter_expressions": None,
                    "aggregation_functions": None,
                    "group_by_keys": None,
                    "sort_keys": None,
                    "projection_expressions": None,
                    "limit_count": None,
                    "offset_count": None,
                },
            ],
            "physical_operator": None,
            "table_name": None,
            "filter_expressions": None,
            "aggregation_functions": None,
            "group_by_keys": None,
            "sort_keys": None,
            "projection_expressions": None,
            "limit_count": None,
            "offset_count": None,
        }

        op = LogicalOperator.from_dict(data)

        assert op.operator_type == LogicalOperatorType.JOIN
        assert op.join_type == JoinType.INNER
        assert len(op.children) == 2
        assert op.children[0].table_name == "orders"
        assert op.children[1].table_name == "customer"

    def test_round_trip_serialization_complex(self) -> None:
        """Test that complex tree survives to_dict -> from_dict."""
        # Build: Filter(l_shipdate > X) -> Join(orders, lineitem) -> [Scan(orders), Scan(lineitem)]
        scan_orders = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="orders",
        )
        scan_lineitem = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_2",
            table_name="lineitem",
        )
        join = LogicalOperator(
            operator_type=LogicalOperatorType.JOIN,
            operator_id="join_1",
            join_type=JoinType.INNER,
            join_conditions=["o_orderkey = l_orderkey"],
            children=[scan_orders, scan_lineitem],
        )
        filter_op = LogicalOperator(
            operator_type=LogicalOperatorType.FILTER,
            operator_id="filter_1",
            filter_expressions=["l_shipdate >= '1994-01-01'"],
            children=[join],
        )

        # Round trip
        serialized = filter_op.to_dict()
        deserialized = LogicalOperator.from_dict(serialized)

        # Verify structure preserved
        assert deserialized.operator_type == LogicalOperatorType.FILTER
        assert deserialized.filter_expressions == ["l_shipdate >= '1994-01-01'"]
        assert len(deserialized.children) == 1

        join_child = deserialized.children[0]
        assert join_child.operator_type == LogicalOperatorType.JOIN
        assert join_child.join_type == JoinType.INNER
        assert len(join_child.children) == 2

    def test_structural_signature_simple(self) -> None:
        """Test structural signature for simple operator."""
        op = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="orders",
        )

        signature = op.get_structural_signature()

        # v2 encoding is canonical JSON (qpc-03): the operator type and table
        # appear as structured fields rather than pipe-joined tokens.
        parsed = json.loads(signature)
        assert parsed["op"] == "Scan"
        assert parsed["table"] == "orders"

    def test_structural_signature_excludes_non_structural(self) -> None:
        """Test that structural signature excludes costs, IDs, etc."""
        op1 = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",  # Different ID
            table_name="orders",
            properties={"cost": 100.0},  # Different cost
        )
        op2 = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_999",  # Different ID
            table_name="orders",
            properties={"cost": 999.0},  # Different cost
        )

        # Signatures should be identical (structural elements only)
        assert op1.get_structural_signature() == op2.get_structural_signature()

    def test_structural_signature_includes_join_type(self) -> None:
        """Test that structural signature includes join type."""
        left_scan = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="orders",
        )
        right_scan = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_2",
            table_name="lineitem",
        )

        inner_join = LogicalOperator(
            operator_type=LogicalOperatorType.JOIN,
            operator_id="join_1",
            join_type=JoinType.INNER,
            children=[left_scan, right_scan],
        )
        left_join = LogicalOperator(
            operator_type=LogicalOperatorType.JOIN,
            operator_id="join_1",
            join_type=JoinType.LEFT,
            children=[left_scan, right_scan],
        )

        # Different join types should produce different signatures
        assert inner_join.get_structural_signature() != left_join.get_structural_signature()
        assert json.loads(inner_join.get_structural_signature())["join"] == "inner"
        assert json.loads(left_join.get_structural_signature())["join"] == "left"


class TestQueryPlanDAG:
    """Test QueryPlanDAG container."""

    def test_basic_instantiation(self) -> None:
        """Test creating a basic query plan."""
        root = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="orders",
        )
        plan = QueryPlanDAG(
            query_id="q01",
            platform="duckdb",
            logical_root=root,
            estimated_cost=100.0,
            estimated_rows=1000,
        )

        assert plan.query_id == "q01"
        assert plan.platform == "duckdb"
        assert plan.logical_root.table_name == "orders"
        assert plan.estimated_cost == 100.0
        assert plan.estimated_rows == 1000

    def test_automatic_fingerprint_computation(self) -> None:
        """Test that fingerprint is computed automatically on init."""
        root = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="lineitem",
        )
        plan = QueryPlanDAG(query_id="q01", platform="duckdb", logical_root=root)

        # Fingerprint should be computed automatically
        assert plan.plan_fingerprint is not None
        assert isinstance(plan.plan_fingerprint, str)
        assert len(plan.plan_fingerprint) == 64  # SHA256 hex length

    def test_explicit_fingerprint_preserved(self) -> None:
        """Test that explicit fingerprint is not overwritten."""
        root = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="customer",
        )
        explicit_fp = "a" * 64
        plan = QueryPlanDAG(
            query_id="q01",
            platform="duckdb",
            logical_root=root,
            plan_fingerprint=explicit_fp,
        )

        assert plan.plan_fingerprint == explicit_fp

    def test_fingerprint_deterministic(self) -> None:
        """Test that same plan produces same fingerprint."""
        root1 = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="orders",
        )
        root2 = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="orders",
        )

        plan1 = QueryPlanDAG(query_id="q01", platform="duckdb", logical_root=root1)
        plan2 = QueryPlanDAG(query_id="q01", platform="duckdb", logical_root=root2)

        assert plan1.plan_fingerprint == plan2.plan_fingerprint

    def test_fingerprint_different_for_different_plans(self) -> None:
        """Test that different plans produce different fingerprints."""
        root1 = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="orders",
        )
        root2 = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="customer",  # Different table
        )

        plan1 = QueryPlanDAG(query_id="q01", platform="duckdb", logical_root=root1)
        plan2 = QueryPlanDAG(query_id="q01", platform="duckdb", logical_root=root2)

        assert plan1.plan_fingerprint != plan2.plan_fingerprint

    def test_fingerprint_ignores_cost_changes(self) -> None:
        """Test that fingerprint is stable across cost changes."""
        root1 = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="lineitem",
            properties={"cost": 100.0},
        )
        root2 = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_2",  # Different ID
            table_name="lineitem",
            properties={"cost": 999.0},  # Different cost
        )

        plan1 = QueryPlanDAG(
            query_id="q01",
            platform="duckdb",
            logical_root=root1,
            estimated_cost=100.0,
        )
        plan2 = QueryPlanDAG(
            query_id="q01",
            platform="duckdb",
            logical_root=root2,
            estimated_cost=999.0,
        )

        # Fingerprints should match (same logical structure)
        assert plan1.plan_fingerprint == plan2.plan_fingerprint

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        root = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="orders",
        )
        plan = QueryPlanDAG(
            query_id="q01",
            platform="duckdb",
            logical_root=root,
            estimated_cost=100.0,
            raw_explain_output="EXPLAIN SELECT * FROM orders",
        )

        result = plan.to_dict()

        assert result["query_id"] == "q01"
        assert result["platform"] == "duckdb"
        assert result["estimated_cost"] == 100.0
        assert result["raw_explain_output"] == "EXPLAIN SELECT * FROM orders"
        assert "logical_root" in result
        assert result["logical_root"]["table_name"] == "orders"

    def test_from_dict(self) -> None:
        """Test deserialization from dictionary."""
        data = {
            "query_id": "q05",
            "platform": "postgres",
            "estimated_cost": 250.0,
            "estimated_rows": 5000,
            "plan_fingerprint": "abc123",
            "raw_explain_output": None,
            "logical_root": {
                "operator_type": "Scan",
                "operator_id": "scan_1",
                "table_name": "customer",
                "properties": {},
                "children": [],
                "physical_operator": None,
                "join_type": None,
                "join_conditions": None,
                "filter_expressions": None,
                "aggregation_functions": None,
                "group_by_keys": None,
                "sort_keys": None,
                "projection_expressions": None,
                "limit_count": None,
                "offset_count": None,
            },
        }

        plan = QueryPlanDAG.from_dict(data)

        assert plan.query_id == "q05"
        assert plan.platform == "postgres"
        assert plan.estimated_cost == 250.0
        assert plan.logical_root.table_name == "customer"

    def test_round_trip_serialization(self) -> None:
        """Test that to_dict -> from_dict preserves all data."""
        # Build complex plan
        scan_orders = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="orders",
        )
        scan_lineitem = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_2",
            table_name="lineitem",
        )
        join = LogicalOperator(
            operator_type=LogicalOperatorType.JOIN,
            operator_id="join_1",
            join_type=JoinType.INNER,
            join_conditions=["o_orderkey = l_orderkey"],
            children=[scan_orders, scan_lineitem],
        )

        original = QueryPlanDAG(
            query_id="q01",
            platform="duckdb",
            logical_root=join,
            estimated_cost=500.0,
            estimated_rows=10000,
            raw_explain_output="EXPLAIN ...",
        )

        # Round trip
        serialized = original.to_dict()
        deserialized = QueryPlanDAG.from_dict(serialized)

        # Verify
        assert deserialized.query_id == original.query_id
        assert deserialized.platform == original.platform
        assert deserialized.estimated_cost == original.estimated_cost
        assert deserialized.estimated_rows == original.estimated_rows
        assert deserialized.raw_explain_output == original.raw_explain_output
        assert deserialized.logical_root.operator_type == LogicalOperatorType.JOIN
        assert len(deserialized.logical_root.children) == 2

    def test_to_json(self) -> None:
        """Test JSON string serialization."""
        root = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="lineitem",
        )
        plan = QueryPlanDAG(query_id="q01", platform="duckdb", logical_root=root)

        json_str = plan.to_json()

        # Should be valid JSON
        parsed = json.loads(json_str)
        assert parsed["query_id"] == "q01"
        assert parsed["platform"] == "duckdb"
        assert parsed["logical_root"]["table_name"] == "lineitem"

    def test_from_json(self) -> None:
        """Test JSON string deserialization."""
        json_str = """
        {
            "query_id": "q17",
            "platform": "snowflake",
            "estimated_cost": 1000.0,
            "estimated_rows": null,
            "plan_fingerprint": "xyz789",
            "raw_explain_output": null,
            "logical_root": {
                "operator_type": "Scan",
                "operator_id": "scan_1",
                "table_name": "part",
                "properties": {},
                "children": [],
                "physical_operator": null,
                "join_type": null,
                "join_conditions": null,
                "filter_expressions": null,
                "aggregation_functions": null,
                "group_by_keys": null,
                "sort_keys": null,
                "projection_expressions": null,
                "limit_count": null,
                "offset_count": null
            }
        }
        """

        plan = QueryPlanDAG.from_json(json_str)

        assert plan.query_id == "q17"
        assert plan.platform == "snowflake"
        assert plan.estimated_cost == 1000.0
        assert plan.logical_root.table_name == "part"

    def test_json_round_trip(self) -> None:
        """Test that to_json -> from_json preserves data."""
        scan = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="supplier",
        )
        filter_op = LogicalOperator(
            operator_type=LogicalOperatorType.FILTER,
            operator_id="filter_1",
            filter_expressions=["s_acctbal > 0"],
            children=[scan],
        )

        original = QueryPlanDAG(
            query_id="q22",
            platform="datafusion",
            logical_root=filter_op,
            estimated_cost=75.0,
        )

        json_str = original.to_json()
        deserialized = QueryPlanDAG.from_json(json_str)

        assert deserialized.query_id == original.query_id
        assert deserialized.platform == original.platform
        assert deserialized.estimated_cost == original.estimated_cost
        assert deserialized.logical_root.operator_type == LogicalOperatorType.FILTER


class TestStandaloneFingerprintFunction:
    """Test the standalone compute_plan_fingerprint function."""

    def test_standalone_fingerprint_matches_method(self) -> None:
        """Test that standalone function matches QueryPlanDAG method."""
        root = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="nation",
        )

        # Compute via standalone function
        standalone_fp = compute_plan_fingerprint(root)

        # Compute via QueryPlanDAG
        plan = QueryPlanDAG(query_id="q01", platform="duckdb", logical_root=root)

        assert standalone_fp == plan.plan_fingerprint

    def test_standalone_fingerprint_deterministic(self) -> None:
        """Test that standalone function is deterministic."""
        root = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="region",
        )

        fp1 = compute_plan_fingerprint(root)
        fp2 = compute_plan_fingerprint(root)

        assert fp1 == fp2
        assert len(fp1) == 64  # SHA256 hex


class TestEnumTypes:
    """Test enum types for operator classification."""

    def test_logical_operator_type_enum(self) -> None:
        """Test LogicalOperatorType enum values."""
        assert LogicalOperatorType.SCAN.value == "Scan"
        assert LogicalOperatorType.JOIN.value == "Join"
        assert LogicalOperatorType.FILTER.value == "Filter"
        assert LogicalOperatorType.AGGREGATE.value == "Aggregate"

    def test_join_type_enum(self) -> None:
        """Test JoinType enum values."""
        assert JoinType.INNER.value == "inner"
        assert JoinType.LEFT.value == "left"
        assert JoinType.RIGHT.value == "right"
        assert JoinType.FULL.value == "full"

    def test_aggregate_function_enum(self) -> None:
        """Test AggregateFunction enum values."""
        assert AggregateFunction.COUNT.value == "count"
        assert AggregateFunction.SUM.value == "sum"
        assert AggregateFunction.AVG.value == "avg"


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_operator_tree(self) -> None:
        """Test operator with no children."""
        op = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="empty",
            children=[],
        )

        assert len(op.children) == 0
        signature = op.get_structural_signature()
        assert "Scan" in signature

    def test_deep_operator_tree(self) -> None:
        """Test deeply nested operator tree."""
        # Build: Limit -> Sort -> Aggregate -> Filter -> Join -> [Scan, Scan]
        scan1 = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="table1",
        )
        scan2 = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_2",
            table_name="table2",
        )
        join = LogicalOperator(
            operator_type=LogicalOperatorType.JOIN,
            operator_id="join_1",
            join_type=JoinType.INNER,
            children=[scan1, scan2],
        )
        filter_op = LogicalOperator(
            operator_type=LogicalOperatorType.FILTER,
            operator_id="filter_1",
            filter_expressions=["col > 0"],
            children=[join],
        )
        agg = LogicalOperator(
            operator_type=LogicalOperatorType.AGGREGATE,
            operator_id="agg_1",
            aggregation_functions=["count(*)"],
            children=[filter_op],
        )
        sort = LogicalOperator(
            operator_type=LogicalOperatorType.SORT,
            operator_id="sort_1",
            sort_keys=[{"expr": "col", "direction": "ASC"}],
            children=[agg],
        )
        limit = LogicalOperator(
            operator_type=LogicalOperatorType.LIMIT,
            operator_id="limit_1",
            limit_count=10,
            children=[sort],
        )

        # Should serialize and deserialize without issues
        serialized = limit.to_dict()
        deserialized = LogicalOperator.from_dict(serialized)

        assert deserialized.operator_type == LogicalOperatorType.LIMIT
        assert deserialized.limit_count == 10
        # Traverse to bottom
        current = deserialized
        depth = 0
        while current.children:
            current = current.children[0]
            depth += 1
        assert depth == 5  # 5 levels deep

    def test_plan_with_no_cost_estimates(self) -> None:
        """Test plan with None cost/row estimates."""
        root = LogicalOperator(
            operator_type=LogicalOperatorType.SCAN,
            operator_id="scan_1",
            table_name="test",
        )
        plan = QueryPlanDAG(
            query_id="q01",
            platform="sqlite",
            logical_root=root,
            estimated_cost=None,
            estimated_rows=None,
        )

        assert plan.estimated_cost is None
        assert plan.estimated_rows is None
        # Fingerprint should still be computed
        assert plan.plan_fingerprint is not None

    def test_operator_with_string_type_instead_of_enum(self) -> None:
        """Test that operators accept string types for flexibility."""
        op = LogicalOperator(
            operator_type="CustomScan",  # String instead of enum
            operator_id="custom_1",
        )

        assert op.operator_type == "CustomScan"
        # Should still serialize
        serialized = op.to_dict()
        assert serialized["operator_type"] == "CustomScan"


class TestFingerprintCoverage:
    """Test that fingerprints include all semantically significant fields."""

    def test_fingerprint_includes_join_conditions(self) -> None:
        """Test that different join conditions produce different fingerprints."""
        from benchbox.core.results.query_plan_models import FingerprintIntegrity

        plan1 = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="join_1",
                operator_type=LogicalOperatorType.JOIN,
                join_type=JoinType.INNER,
                join_conditions=["a.id = b.id"],
                children=[
                    LogicalOperator(operator_id="scan_1", operator_type=LogicalOperatorType.SCAN, table_name="a"),
                    LogicalOperator(operator_id="scan_2", operator_type=LogicalOperatorType.SCAN, table_name="b"),
                ],
            ),
        )

        plan2 = QueryPlanDAG(
            query_id="q2",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="join_1",
                operator_type=LogicalOperatorType.JOIN,
                join_type=JoinType.INNER,
                join_conditions=["a.id = b.foreign_id"],  # Different condition
                children=[
                    LogicalOperator(operator_id="scan_1", operator_type=LogicalOperatorType.SCAN, table_name="a"),
                    LogicalOperator(operator_id="scan_2", operator_type=LogicalOperatorType.SCAN, table_name="b"),
                ],
            ),
        )

        assert plan1.plan_fingerprint != plan2.plan_fingerprint
        assert plan1.fingerprint_integrity == FingerprintIntegrity.VERIFIED

    def test_fingerprint_includes_group_by_keys(self) -> None:
        """Test that different group by keys produce different fingerprints."""
        plan1 = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="agg_1",
                operator_type=LogicalOperatorType.AGGREGATE,
                group_by_keys=["region", "year"],
                children=[
                    LogicalOperator(operator_id="scan_1", operator_type=LogicalOperatorType.SCAN, table_name="orders"),
                ],
            ),
        )

        plan2 = QueryPlanDAG(
            query_id="q2",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="agg_1",
                operator_type=LogicalOperatorType.AGGREGATE,
                group_by_keys=["region", "month"],  # Different grouping
                children=[
                    LogicalOperator(operator_id="scan_1", operator_type=LogicalOperatorType.SCAN, table_name="orders"),
                ],
            ),
        )

        assert plan1.plan_fingerprint != plan2.plan_fingerprint

    def test_fingerprint_includes_projection_expressions(self) -> None:
        """Test that different projections produce different fingerprints."""
        plan1 = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="proj_1",
                operator_type=LogicalOperatorType.PROJECT,
                projection_expressions=["id", "name", "total"],
                children=[
                    LogicalOperator(operator_id="scan_1", operator_type=LogicalOperatorType.SCAN, table_name="orders"),
                ],
            ),
        )

        plan2 = QueryPlanDAG(
            query_id="q2",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="proj_1",
                operator_type=LogicalOperatorType.PROJECT,
                projection_expressions=["id", "name"],  # Different projection
                children=[
                    LogicalOperator(operator_id="scan_1", operator_type=LogicalOperatorType.SCAN, table_name="orders"),
                ],
            ),
        )

        assert plan1.plan_fingerprint != plan2.plan_fingerprint

    def test_fingerprint_includes_limit_count(self) -> None:
        """Test that different limit counts produce different fingerprints."""
        plan1 = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="limit_1",
                operator_type=LogicalOperatorType.LIMIT,
                limit_count=100,
                children=[
                    LogicalOperator(operator_id="scan_1", operator_type=LogicalOperatorType.SCAN, table_name="orders"),
                ],
            ),
        )

        plan2 = QueryPlanDAG(
            query_id="q2",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="limit_1",
                operator_type=LogicalOperatorType.LIMIT,
                limit_count=50,  # Different limit
                children=[
                    LogicalOperator(operator_id="scan_1", operator_type=LogicalOperatorType.SCAN, table_name="orders"),
                ],
            ),
        )

        assert plan1.plan_fingerprint != plan2.plan_fingerprint

    def test_fingerprint_includes_offset_count(self) -> None:
        """Test that different offset counts produce different fingerprints."""
        plan1 = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="limit_1",
                operator_type=LogicalOperatorType.LIMIT,
                limit_count=100,
                offset_count=0,
                children=[
                    LogicalOperator(operator_id="scan_1", operator_type=LogicalOperatorType.SCAN, table_name="orders"),
                ],
            ),
        )

        plan2 = QueryPlanDAG(
            query_id="q2",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="limit_1",
                operator_type=LogicalOperatorType.LIMIT,
                limit_count=100,
                offset_count=10,  # Different offset
                children=[
                    LogicalOperator(operator_id="scan_1", operator_type=LogicalOperatorType.SCAN, table_name="orders"),
                ],
            ),
        )

        assert plan1.plan_fingerprint != plan2.plan_fingerprint

    def test_fingerprint_join_conditions_order_invariant(self) -> None:
        """Test that join conditions order doesn't affect fingerprint (set semantics)."""
        plan1 = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="join_1",
                operator_type=LogicalOperatorType.JOIN,
                join_conditions=["a.id = b.id", "a.type = b.type"],
                children=[
                    LogicalOperator(operator_id="scan_1", operator_type=LogicalOperatorType.SCAN, table_name="a"),
                    LogicalOperator(operator_id="scan_2", operator_type=LogicalOperatorType.SCAN, table_name="b"),
                ],
            ),
        )

        plan2 = QueryPlanDAG(
            query_id="q2",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="join_1",
                operator_type=LogicalOperatorType.JOIN,
                join_conditions=["a.type = b.type", "a.id = b.id"],  # Same conditions, different order
                children=[
                    LogicalOperator(operator_id="scan_1", operator_type=LogicalOperatorType.SCAN, table_name="a"),
                    LogicalOperator(operator_id="scan_2", operator_type=LogicalOperatorType.SCAN, table_name="b"),
                ],
            ),
        )

        assert plan1.plan_fingerprint == plan2.plan_fingerprint

    def test_fingerprint_group_by_order_matters(self) -> None:
        """Test that group by key order affects fingerprint (order matters)."""
        plan1 = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="agg_1",
                operator_type=LogicalOperatorType.AGGREGATE,
                group_by_keys=["region", "year"],
                children=[
                    LogicalOperator(operator_id="scan_1", operator_type=LogicalOperatorType.SCAN, table_name="orders"),
                ],
            ),
        )

        plan2 = QueryPlanDAG(
            query_id="q2",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="agg_1",
                operator_type=LogicalOperatorType.AGGREGATE,
                group_by_keys=["year", "region"],  # Different order
                children=[
                    LogicalOperator(operator_id="scan_1", operator_type=LogicalOperatorType.SCAN, table_name="orders"),
                ],
            ),
        )

        assert plan1.plan_fingerprint != plan2.plan_fingerprint


class TestLiteralNormalization:
    """Test the normalize_literals structural-signature / fingerprint option."""

    def test_numeric_and_string_literals_are_masked(self) -> None:
        assert _normalize_literal_text("l_quantity > 24") == "l_quantity > ?"
        assert _normalize_literal_text("c_name = 'ALICE'") == "c_name = ?"

    def test_ordinal_column_references_are_preserved(self) -> None:
        """DuckDB (and others) emit ordinal refs like #0/#1 for projected/grouped
        columns. Without excluding '#' from the numeric-literal lookbehind, every
        ordinal collapses to the same '#?' placeholder, so plans that group/sort/
        project DIFFERENT columns would spuriously fingerprint identically."""
        assert _normalize_literal_text("#0") == "#0"
        assert _normalize_literal_text("#1") == "#1"
        assert _normalize_literal_text("group by #0, #1") == "group by #0, #1"
        # A genuine numeric literal alongside an ordinal ref is still masked.
        assert _normalize_literal_text("#0 > 24") == "#0 > ?"

    def test_normalize_literals_distinguishes_different_ordinal_refs(self) -> None:
        """End-to-end: two plans referencing different ordinal columns must NOT
        collapse to the same normalized fingerprint."""
        plan_col0 = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="agg_1",
                operator_type=LogicalOperatorType.AGGREGATE,
                group_by_keys=["#0"],
                children=[
                    LogicalOperator(operator_id="scan_1", operator_type=LogicalOperatorType.SCAN, table_name="orders"),
                ],
            ),
        )
        plan_col1 = QueryPlanDAG(
            query_id="q2",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="agg_1",
                operator_type=LogicalOperatorType.AGGREGATE,
                group_by_keys=["#1"],
                children=[
                    LogicalOperator(operator_id="scan_1", operator_type=LogicalOperatorType.SCAN, table_name="orders"),
                ],
            ),
        )

        assert plan_col0.compute_plan_fingerprint(normalize_literals=True) != plan_col1.compute_plan_fingerprint(
            normalize_literals=True
        )

    def test_normalize_literals_collapses_only_constant_differences(self) -> None:
        """Plans differing only in a literal constant DO collapse under normalization,
        while the default (literal-sensitive) fingerprint still distinguishes them."""
        plan_a = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="filter_1",
                operator_type=LogicalOperatorType.FILTER,
                filter_expressions=["l_quantity > 24"],
                children=[
                    LogicalOperator(
                        operator_id="scan_1", operator_type=LogicalOperatorType.SCAN, table_name="lineitem"
                    ),
                ],
            ),
        )
        plan_b = QueryPlanDAG(
            query_id="q2",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="filter_1",
                operator_type=LogicalOperatorType.FILTER,
                filter_expressions=["l_quantity > 30"],
                children=[
                    LogicalOperator(
                        operator_id="scan_1", operator_type=LogicalOperatorType.SCAN, table_name="lineitem"
                    ),
                ],
            ),
        )

        assert plan_a.plan_fingerprint != plan_b.plan_fingerprint
        assert plan_a.compute_plan_fingerprint(normalize_literals=True) == plan_b.compute_plan_fingerprint(
            normalize_literals=True
        )


class TestFingerprintVerification:
    """Test fingerprint verification and integrity tracking."""

    def test_from_dict_verifies_fingerprint(self) -> None:
        """Test that from_dict verifies fingerprint by default."""
        from benchbox.core.results.query_plan_models import FingerprintIntegrity

        # Create a plan and serialize it
        original = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="scan_1",
                operator_type=LogicalOperatorType.SCAN,
                table_name="orders",
            ),
        )
        data = original.to_dict()

        # Deserialize - should verify fingerprint
        loaded = QueryPlanDAG.from_dict(data)
        assert loaded.fingerprint_integrity == FingerprintIntegrity.VERIFIED
        assert loaded.is_fingerprint_trusted()

    def test_from_dict_detects_stale_fingerprint(self) -> None:
        """Test that from_dict detects tampered fingerprints."""
        from benchbox.core.results.query_plan_models import FingerprintIntegrity

        # Create and serialize a plan
        original = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="scan_1",
                operator_type=LogicalOperatorType.SCAN,
                table_name="orders",
            ),
        )
        data = original.to_dict()

        # Tamper with the fingerprint
        data["plan_fingerprint"] = "invalid_fingerprint"

        # Deserialize - should detect stale fingerprint
        loaded = QueryPlanDAG.from_dict(data)
        assert loaded.fingerprint_integrity == FingerprintIntegrity.STALE
        assert not loaded.is_fingerprint_trusted()

    def test_from_dict_refresh_on_mismatch(self) -> None:
        """Test that from_dict can recompute fingerprint on mismatch."""
        from benchbox.core.results.query_plan_models import FingerprintIntegrity

        # Create and serialize a plan
        original = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="scan_1",
                operator_type=LogicalOperatorType.SCAN,
                table_name="orders",
            ),
        )
        data = original.to_dict()
        correct_fingerprint = original.plan_fingerprint

        # Tamper with the fingerprint
        data["plan_fingerprint"] = "invalid_fingerprint"

        # Deserialize with refresh_on_mismatch=True
        loaded = QueryPlanDAG.from_dict(data, refresh_on_mismatch=True)
        assert loaded.fingerprint_integrity == FingerprintIntegrity.RECOMPUTED
        assert loaded.is_fingerprint_trusted()
        assert loaded.plan_fingerprint == correct_fingerprint

    def test_from_dict_skip_verification(self) -> None:
        """Test that from_dict can skip verification."""
        from benchbox.core.results.query_plan_models import FingerprintIntegrity

        # Create and serialize a plan
        original = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="scan_1",
                operator_type=LogicalOperatorType.SCAN,
                table_name="orders",
            ),
        )
        data = original.to_dict()

        # Tamper with the fingerprint
        data["plan_fingerprint"] = "invalid_fingerprint"

        # Deserialize without verification
        loaded = QueryPlanDAG.from_dict(data, verify_fingerprint=False)
        assert loaded.fingerprint_integrity == FingerprintIntegrity.UNVERIFIED
        assert not loaded.is_fingerprint_trusted()
        assert loaded.plan_fingerprint == "invalid_fingerprint"  # Kept as-is

    def test_verify_fingerprint_method(self) -> None:
        """Test the verify_fingerprint method."""
        from benchbox.core.results.query_plan_models import FingerprintIntegrity

        plan = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="scan_1",
                operator_type=LogicalOperatorType.SCAN,
                table_name="orders",
            ),
        )

        # Fingerprint should be valid initially
        assert plan.verify_fingerprint() is True
        assert plan.fingerprint_integrity == FingerprintIntegrity.VERIFIED

        # Tamper with fingerprint
        plan.plan_fingerprint = "invalid"
        assert plan.verify_fingerprint() is False
        assert plan.fingerprint_integrity == FingerprintIntegrity.STALE

    def test_refresh_fingerprint_method(self) -> None:
        """Test the refresh_fingerprint method."""
        from benchbox.core.results.query_plan_models import FingerprintIntegrity

        plan = QueryPlanDAG(
            query_id="q1",
            platform="duckdb",
            logical_root=LogicalOperator(
                operator_id="scan_1",
                operator_type=LogicalOperatorType.SCAN,
                table_name="orders",
            ),
        )

        # Tamper and then refresh
        plan.plan_fingerprint = "invalid"
        plan.fingerprint_integrity = FingerprintIntegrity.STALE

        plan.refresh_fingerprint()
        assert plan.fingerprint_integrity == FingerprintIntegrity.VERIFIED
        assert plan.verify_fingerprint() is True


class TestHelperFunctions:
    """Test helper functions for safe operator type handling."""

    def test_get_operator_type_str_with_enum(self) -> None:
        """Test get_operator_type_str with enum value."""
        from benchbox.core.results.query_plan_models import get_operator_type_str

        result = get_operator_type_str(LogicalOperatorType.SCAN)
        assert result == "Scan"

        result = get_operator_type_str(LogicalOperatorType.JOIN)
        assert result == "Join"

    def test_get_operator_type_str_with_string(self) -> None:
        """Test get_operator_type_str with string value."""
        from benchbox.core.results.query_plan_models import get_operator_type_str

        result = get_operator_type_str("CustomScan")
        assert result == "CustomScan"

        result = get_operator_type_str("IndexSeek")
        assert result == "IndexSeek"

    def test_get_join_type_str_with_enum(self) -> None:
        """Test get_join_type_str with enum value."""
        from benchbox.core.results.query_plan_models import get_join_type_str

        result = get_join_type_str(JoinType.INNER)
        assert result == "inner"

        result = get_join_type_str(JoinType.LEFT)
        assert result == "left"

    def test_get_join_type_str_with_string(self) -> None:
        """Test get_join_type_str with string value."""
        from benchbox.core.results.query_plan_models import get_join_type_str

        result = get_join_type_str("parallel_hash")
        assert result == "parallel_hash"

    def test_get_join_type_str_with_none(self) -> None:
        """Test get_join_type_str with None value."""
        from benchbox.core.results.query_plan_models import get_join_type_str

        result = get_join_type_str(None)
        assert result is None

    def test_normalize_operator_type_with_enum(self) -> None:
        """Test normalize_operator_type returns enum as-is."""
        from benchbox.core.results.query_plan_models import normalize_operator_type

        result = normalize_operator_type(LogicalOperatorType.SCAN)
        assert result == LogicalOperatorType.SCAN

    def test_normalize_operator_type_with_matching_string(self) -> None:
        """Test normalize_operator_type converts matching string to enum."""
        from benchbox.core.results.query_plan_models import normalize_operator_type

        result = normalize_operator_type("Scan")
        assert result == LogicalOperatorType.SCAN

        result = normalize_operator_type("Join")
        assert result == LogicalOperatorType.JOIN

    def test_normalize_operator_type_with_unknown_string(self) -> None:
        """Test normalize_operator_type returns unknown string as-is."""
        from benchbox.core.results.query_plan_models import normalize_operator_type

        result = normalize_operator_type("CustomScan")
        assert result == "CustomScan"

    def test_is_operator_type_match_same_enum(self) -> None:
        """Test is_operator_type_match with same enum values."""
        from benchbox.core.results.query_plan_models import is_operator_type_match

        result = is_operator_type_match(LogicalOperatorType.SCAN, LogicalOperatorType.SCAN)
        assert result is True

    def test_is_operator_type_match_different_enum(self) -> None:
        """Test is_operator_type_match with different enum values."""
        from benchbox.core.results.query_plan_models import is_operator_type_match

        result = is_operator_type_match(LogicalOperatorType.SCAN, LogicalOperatorType.JOIN)
        assert result is False

    def test_is_operator_type_match_enum_and_matching_string(self) -> None:
        """Test is_operator_type_match with enum and matching string."""
        from benchbox.core.results.query_plan_models import is_operator_type_match

        result = is_operator_type_match(LogicalOperatorType.SCAN, "Scan")
        assert result is True

        result = is_operator_type_match("Scan", LogicalOperatorType.SCAN)
        assert result is True

    def test_is_operator_type_match_same_string(self) -> None:
        """Test is_operator_type_match with same string values."""
        from benchbox.core.results.query_plan_models import is_operator_type_match

        result = is_operator_type_match("CustomScan", "CustomScan")
        assert result is True

    def test_is_operator_type_match_different_string(self) -> None:
        """Test is_operator_type_match with different string values."""
        from benchbox.core.results.query_plan_models import is_operator_type_match

        result = is_operator_type_match("CustomScan", "IndexScan")
        assert result is False


class TestUnknownTypeWarnings:
    """Test warning behavior for unknown operator and join types."""

    def test_unknown_operator_type_logs_warning(self, caplog) -> None:
        """Test that unknown operator types log a warning."""
        import logging

        from benchbox.core.results.query_plan_models import (
            clear_unknown_type_warnings,
            get_operator_type_str,
        )

        # Clear any previously logged warnings
        clear_unknown_type_warnings()

        with caplog.at_level(logging.WARNING):
            result = get_operator_type_str("UnknownCustomOperator")

        assert result == "UnknownCustomOperator"
        assert "Unknown operator type 'UnknownCustomOperator'" in caplog.text
        assert "Consider adding a mapping" in caplog.text

    def test_known_string_operator_type_no_warning(self, caplog) -> None:
        """Test that known enum value as string doesn't log a warning."""
        import logging

        from benchbox.core.results.query_plan_models import (
            clear_unknown_type_warnings,
            get_operator_type_str,
        )

        clear_unknown_type_warnings()

        with caplog.at_level(logging.WARNING):
            result = get_operator_type_str("Scan")  # Known enum value

        assert result == "Scan"
        assert "Unknown operator type" not in caplog.text

    def test_unknown_operator_type_warning_logged_once(self, caplog) -> None:
        """Test that unknown operator types are only logged once per unique type."""
        import logging

        from benchbox.core.results.query_plan_models import (
            clear_unknown_type_warnings,
            get_operator_type_str,
        )

        clear_unknown_type_warnings()

        with caplog.at_level(logging.WARNING):
            # Call multiple times with the same unknown type
            get_operator_type_str("RepeatedUnknownType")
            get_operator_type_str("RepeatedUnknownType")
            get_operator_type_str("RepeatedUnknownType")

        # Warning should only appear once
        assert caplog.text.count("Unknown operator type 'RepeatedUnknownType'") == 1

    def test_multiple_unknown_operator_types_each_warned(self, caplog) -> None:
        """Test that different unknown operator types each get their own warning."""
        import logging

        from benchbox.core.results.query_plan_models import (
            clear_unknown_type_warnings,
            get_operator_type_str,
        )

        clear_unknown_type_warnings()

        with caplog.at_level(logging.WARNING):
            get_operator_type_str("UnknownTypeA")
            get_operator_type_str("UnknownTypeB")

        assert "Unknown operator type 'UnknownTypeA'" in caplog.text
        assert "Unknown operator type 'UnknownTypeB'" in caplog.text

    def test_warn_unknown_parameter(self, caplog) -> None:
        """Test that warn_unknown=False suppresses warnings."""
        import logging

        from benchbox.core.results.query_plan_models import (
            clear_unknown_type_warnings,
            get_operator_type_str,
        )

        clear_unknown_type_warnings()

        with caplog.at_level(logging.WARNING):
            result = get_operator_type_str("SilentUnknownType", warn_unknown=False)

        assert result == "SilentUnknownType"
        assert "Unknown operator type 'SilentUnknownType'" not in caplog.text

    def test_unknown_join_type_logs_warning(self, caplog) -> None:
        """Test that unknown join types log a warning."""
        import logging

        from benchbox.core.results.query_plan_models import (
            clear_unknown_type_warnings,
            get_join_type_str,
        )

        clear_unknown_type_warnings()

        with caplog.at_level(logging.WARNING):
            result = get_join_type_str("parallel_hash_join")

        assert result == "parallel_hash_join"
        assert "Unknown join type 'parallel_hash_join'" in caplog.text
        assert "Consider adding a mapping" in caplog.text

    def test_known_string_join_type_no_warning(self, caplog) -> None:
        """Test that known enum value as string doesn't log a warning."""
        import logging

        from benchbox.core.results.query_plan_models import (
            clear_unknown_type_warnings,
            get_join_type_str,
        )

        clear_unknown_type_warnings()

        with caplog.at_level(logging.WARNING):
            result = get_join_type_str("inner")  # Known enum value

        assert result == "inner"
        assert "Unknown join type" not in caplog.text

    def test_unknown_join_type_warning_logged_once(self, caplog) -> None:
        """Test that unknown join types are only logged once per unique type."""
        import logging

        from benchbox.core.results.query_plan_models import (
            clear_unknown_type_warnings,
            get_join_type_str,
        )

        clear_unknown_type_warnings()

        with caplog.at_level(logging.WARNING):
            get_join_type_str("repeated_custom_join")
            get_join_type_str("repeated_custom_join")

        assert caplog.text.count("Unknown join type 'repeated_custom_join'") == 1

    def test_clear_unknown_type_warnings_resets_state(self, caplog) -> None:
        """Test that clear_unknown_type_warnings resets warning state."""
        import logging

        from benchbox.core.results.query_plan_models import (
            clear_unknown_type_warnings,
            get_operator_type_str,
        )

        # First call with unknown type
        clear_unknown_type_warnings()
        with caplog.at_level(logging.WARNING):
            get_operator_type_str("ClearTestType")
        assert "Unknown operator type 'ClearTestType'" in caplog.text

        # Clear and call again - should warn again
        caplog.clear()
        clear_unknown_type_warnings()
        with caplog.at_level(logging.WARNING):
            get_operator_type_str("ClearTestType")
        assert "Unknown operator type 'ClearTestType'" in caplog.text

    def test_is_operator_type_match_does_not_warn(self, caplog) -> None:
        """Test that is_operator_type_match doesn't trigger warnings."""
        import logging

        from benchbox.core.results.query_plan_models import (
            clear_unknown_type_warnings,
            is_operator_type_match,
        )

        clear_unknown_type_warnings()

        with caplog.at_level(logging.WARNING):
            result = is_operator_type_match("UnknownMatch1", "UnknownMatch2")

        assert result is False
        # Should not trigger warnings during comparison
        assert "Unknown operator type" not in caplog.text


class TestPlanDepthTruncation:
    """qpc-10: deep plans serialize with a truncated_at_depth marker, not dropped."""

    @staticmethod
    def _linear_chain(depth: int) -> LogicalOperator:
        """Build a linear operator chain ``depth`` levels below a SCAN leaf.

        Returns the root; the chain is root -> child -> ... -> scan, so the deepest
        node sits at ``current_depth == depth``.
        """
        node = LogicalOperator(operator_type=LogicalOperatorType.SCAN, operator_id="scan_leaf", table_name="t")
        for level in range(depth):
            node = LogicalOperator(
                operator_type=LogicalOperatorType.FILTER,
                operator_id=f"filter_{level}",
                filter_expressions=[f"c > {level}"],
                children=[node],
            )
        return node

    def test_to_dict_emits_truncation_marker_beyond_max_depth(self) -> None:
        root = self._linear_chain(6)

        serialized = root.to_dict(max_depth=3)

        # Walk down; at depth 4 (first node with current_depth > max_depth=3) we
        # must hit a truncation marker instead of a raise or a dropped plan.
        node = serialized
        depth = 0
        while "truncated_at_depth" not in node:
            assert node["children"], f"reached a leaf at depth {depth} before truncation"
            node = node["children"][0]
            depth += 1
        assert node["truncated_at_depth"] == 4
        assert node["children_omitted"] >= 1
        # The marker node carries operator identity but no recursed children key.
        assert node["operator_id"].startswith(("filter_", "scan_"))
        assert "children" not in node

    def test_to_dict_no_truncation_when_within_max_depth(self) -> None:
        root = self._linear_chain(3)
        serialized = root.to_dict(max_depth=50)

        # Full tree present, no marker anywhere.
        node = serialized
        while node.get("children"):
            assert "truncated_at_depth" not in node
            node = node["children"][0]
        assert node["operator_id"] == "scan_leaf"

    def test_deep_plan_serializes_instead_of_raising(self) -> None:
        # A plan deeper than the default cap must NOT raise / disappear; it must
        # produce a bounded serialization carrying the marker.
        root = self._linear_chain(60)
        plan = QueryPlanDAG(query_id="deep_q", platform="duckdb", logical_root=root)

        size = plan.estimate_serialized_size()  # default max_depth
        assert size > 0
        payload = plan.to_json()
        assert "truncated_at_depth" in payload

    def test_truncation_marker_round_trips_as_leaf(self) -> None:
        root = self._linear_chain(5)
        serialized = root.to_dict(max_depth=2)
        restored = LogicalOperator.from_dict(serialized)

        # Traverse to the deepest restored node: it is a childless leaf (the
        # marker's omitted children are not reconstructed).
        node = restored
        while node.children:
            node = node.children[0]
        assert node.children == []

    def test_fingerprint_unaffected_by_serialization_truncation(self) -> None:
        # The fingerprint is computed over the FULL in-memory tree, so shrinking
        # the serialization depth must not change it (anti-pattern: never
        # fingerprint a truncated tree as complete).
        root = self._linear_chain(60)
        plan = QueryPlanDAG(query_id="fp_q", platform="duckdb", logical_root=root)

        fp = plan.plan_fingerprint
        # Recompute after a shallow serialization round-trip of the size guard.
        plan.estimate_serialized_size(max_depth=3)
        assert plan.plan_fingerprint == fp
        # And equals a fresh full-tree fingerprint (depth cap plays no role).
        assert plan.compute_plan_fingerprint() == fp

    def test_configurable_max_depth_changes_truncation_point(self) -> None:
        root = self._linear_chain(10)

        def _first_truncated_depth(md: int) -> int:
            node = root.to_dict(max_depth=md)
            depth = 0
            while "truncated_at_depth" not in node:
                node = node["children"][0]
                depth += 1
            return depth

        assert _first_truncated_depth(2) == 3
        assert _first_truncated_depth(5) == 6
