"""Unit tests for FabricWarehouseQueryPlanParser.

Fabric Warehouse retrieves its plan via ``SET SHOWPLAN_TEXT`` (SQL Server text
showplan) rather than Azure Synapse's distributed dsql XML, so it uses a
dedicated parser (the w6 decision gate). Driven by a recorded SHOWPLAN_TEXT
fixture under tests/fixtures/query_plans/ so these run with no live Fabric
workspace.
"""

from pathlib import Path

import pytest

from benchbox.core.query_plans.parsers.fabric_warehouse import FabricWarehouseQueryPlanParser
from benchbox.core.query_plans.parsers.registry import get_parser_for_platform
from benchbox.core.results.query_plan_models import JoinType, LogicalOperator, LogicalOperatorType

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "query_plans"


def _load(name: str) -> str:
    return (_FIXTURES / name).read_text()


def _collect(op: LogicalOperator) -> list[LogicalOperator]:
    nodes = [op]
    for child in op.children:
        nodes.extend(_collect(child))
    return nodes


@pytest.fixture()
def parser():
    return FabricWarehouseQueryPlanParser()


class TestFabricWarehousePlan:
    def test_parses_to_valid_dag(self, parser):
        dag = parser.parse_explain_output("q1", _load("fabric_warehouse_showplan_sample.txt"))
        assert dag is not None
        assert dag.logical_root is not None
        assert dag.plan_fingerprint is not None
        assert dag.platform == "fabric_warehouse"

    def test_root_is_sort(self, parser):
        dag = parser.parse_explain_output("q1", _load("fabric_warehouse_showplan_sample.txt"))
        assert dag.logical_root.operator_type == LogicalOperatorType.SORT

    def test_tree_has_join_over_two_scans(self, parser):
        dag = parser.parse_explain_output("q1", _load("fabric_warehouse_showplan_sample.txt"))
        nodes = _collect(dag.logical_root)
        types = [n.operator_type for n in nodes]
        assert LogicalOperatorType.JOIN in types
        assert LogicalOperatorType.AGGREGATE in types
        assert types.count(LogicalOperatorType.SCAN) == 2
        tables = {n.table_name for n in nodes if n.table_name}
        assert tables == {"tpch.dbo.lineitem", "tpch.dbo.orders"}

    def test_join_is_inner_with_condition(self, parser):
        dag = parser.parse_explain_output("q1", _load("fabric_warehouse_showplan_sample.txt"))
        join = next(n for n in _collect(dag.logical_root) if n.operator_type == LogicalOperatorType.JOIN)
        assert join.join_type == JoinType.INNER
        assert join.join_conditions

    def test_leading_statement_line_skipped(self, parser):
        # The first (statement) row has no |-- connector and must not be an operator.
        dag = parser.parse_explain_output("q1", _load("fabric_warehouse_showplan_sample.txt"))
        assert "SELECT" not in dag.logical_root.physical_operator.operator_type

    def test_registered_for_fabric_aliases(self):
        assert isinstance(get_parser_for_platform("fabric_warehouse"), FabricWarehouseQueryPlanParser)
        assert isinstance(get_parser_for_platform("fabric"), FabricWarehouseQueryPlanParser)


class TestFabricWarehouseOperatorNormalization:
    @pytest.mark.parametrize(
        ("name", "args", "expected"),
        [
            ("Clustered Index Scan", "OBJECT:([db].[dbo].[t])", LogicalOperatorType.SCAN),
            ("Index Seek", "OBJECT:([db].[dbo].[t].[ix])", LogicalOperatorType.SCAN),
            ("Hash Match", "Inner Join, HASH:([a])=([b])", LogicalOperatorType.JOIN),
            ("Hash Match", "Aggregate, HASH:([a]) DEFINE:([x]=SUM([y]))", LogicalOperatorType.AGGREGATE),
            ("Nested Loops", "Inner Join", LogicalOperatorType.JOIN),
            ("Stream Aggregate", "GROUP BY:([a])", LogicalOperatorType.AGGREGATE),
            ("Sort", "ORDER BY:([a] ASC)", LogicalOperatorType.SORT),
            ("Compute Scalar", "DEFINE:([x]=...)", LogicalOperatorType.PROJECT),
            ("Top", "TOP EXPRESSION", LogicalOperatorType.LIMIT),
        ],
    )
    def test_map_operator_type(self, parser, name, args, expected):
        assert parser._map_operator_type(name, args) == expected


class TestFabricWarehouseErrorHandling:
    def test_empty_returns_none(self, parser):
        assert parser.parse_explain_output("q1", "") is None

    def test_statement_only_returns_none(self, parser):
        # No |-- rows at all -> no operators.
        assert parser.parse_explain_output("q1", "SELECT 1") is None
