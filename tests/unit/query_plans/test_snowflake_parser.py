"""Unit tests for SnowflakeQueryPlanParser.

Driven by a recorded ``EXPLAIN USING JSON`` fixture under
tests/fixtures/query_plans/ so they run with no live Snowflake account.
"""

from pathlib import Path

import pytest

from benchbox.core.query_plans.parsers.registry import get_parser_for_platform
from benchbox.core.query_plans.parsers.snowflake import SnowflakeQueryPlanParser
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
    return SnowflakeQueryPlanParser()


class TestSnowflakePlan:
    def test_parses_to_valid_dag(self, parser):
        dag = parser.parse_explain_output("q1", _load("snowflake_explain_sample.json"))
        assert dag is not None
        assert dag.logical_root is not None
        assert dag.plan_fingerprint is not None
        assert dag.platform == "snowflake"

    def test_root_is_result_projection(self, parser):
        dag = parser.parse_explain_output("q1", _load("snowflake_explain_sample.json"))
        assert dag.logical_root.operator_type == LogicalOperatorType.PROJECT
        assert dag.logical_root.physical_operator.operator_type == "Result"

    def test_tree_has_join_over_two_scans(self, parser):
        dag = parser.parse_explain_output("q1", _load("snowflake_explain_sample.json"))
        nodes = _collect(dag.logical_root)
        types = [n.operator_type for n in nodes]
        assert LogicalOperatorType.JOIN in types
        assert LogicalOperatorType.AGGREGATE in types
        assert LogicalOperatorType.SORT in types
        assert types.count(LogicalOperatorType.SCAN) == 2
        tables = {n.table_name for n in nodes if n.table_name}
        assert tables == {"TPCH_SF1.PUBLIC.LINEITEM", "TPCH_SF1.PUBLIC.ORDERS"}

    def test_join_classified_inner(self, parser):
        dag = parser.parse_explain_output("q1", _load("snowflake_explain_sample.json"))
        joins = [n for n in _collect(dag.logical_root) if n.operator_type == LogicalOperatorType.JOIN]
        assert joins and joins[0].join_type == JoinType.INNER

    def test_estimated_rows_from_global_stats(self, parser):
        dag = parser.parse_explain_output("q1", _load("snowflake_explain_sample.json"))
        assert dag.estimated_rows == 12

    def test_registered_for_snowflake(self):
        assert isinstance(get_parser_for_platform("snowflake"), SnowflakeQueryPlanParser)


class TestSnowflakeOperatorNormalization:
    @pytest.mark.parametrize(
        ("operation", "expected"),
        [
            ("TableScan", LogicalOperatorType.SCAN),
            ("JoinFilter", LogicalOperatorType.SCAN),
            ("InnerJoin", LogicalOperatorType.JOIN),
            ("LeftOuterJoin", LogicalOperatorType.JOIN),
            ("Aggregate", LogicalOperatorType.AGGREGATE),
            ("Sort", LogicalOperatorType.SORT),
            ("Filter", LogicalOperatorType.FILTER),
            ("Result", LogicalOperatorType.PROJECT),
            ("WithReference", LogicalOperatorType.PROJECT),
            ("UnionAll", LogicalOperatorType.UNION),
            ("SomethingExotic", LogicalOperatorType.OTHER),
        ],
    )
    def test_map_operator_type(self, parser, operation, expected):
        assert parser._map_operator_type(operation) == expected


class TestSnowflakeErrorHandling:
    def test_empty_returns_none(self, parser):
        assert parser.parse_explain_output("q1", "") is None

    def test_invalid_json_returns_none(self, parser):
        assert parser.parse_explain_output("q1", "not json {") is None

    def test_missing_operations_returns_none(self, parser):
        assert parser.parse_explain_output("q1", '{"GlobalStats": {}}') is None
