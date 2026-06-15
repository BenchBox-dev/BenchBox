"""Unit tests for BigQueryQueryPlanParser.

BigQuery has no EXPLAIN statement; plans come from the completed job's
``query_plan`` statistics. The parser consumes the JSON-serialized stage list,
recorded as a fixture under tests/fixtures/query_plans/ so these run with no
live BigQuery account.
"""

from pathlib import Path

import pytest

from benchbox.core.query_plans.parsers.bigquery import BigQueryQueryPlanParser
from benchbox.core.query_plans.parsers.registry import get_parser_for_platform
from benchbox.core.results.query_plan_models import LogicalOperator, LogicalOperatorType

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
    return BigQueryQueryPlanParser()


class TestBigQueryPlan:
    def test_parses_to_valid_dag(self, parser):
        dag = parser.parse_explain_output("q1", _load("bigquery_query_plan_sample.json"))
        assert dag is not None
        assert dag.logical_root is not None
        assert dag.plan_fingerprint is not None
        assert dag.platform == "bigquery"

    def test_root_is_output_stage(self, parser):
        # The Output stage is read by nobody, so it is the root.
        dag = parser.parse_explain_output("q1", _load("bigquery_query_plan_sample.json"))
        assert "Output" in dag.logical_root.physical_operator.operator_type

    def test_tree_built_from_input_stages(self, parser):
        dag = parser.parse_explain_output("q1", _load("bigquery_query_plan_sample.json"))
        nodes = _collect(dag.logical_root)
        types = [n.operator_type for n in nodes]
        assert LogicalOperatorType.JOIN in types
        assert types.count(LogicalOperatorType.SCAN) == 2
        tables = {n.table_name for n in nodes if n.table_name}
        assert tables == {"tpch.lineitem", "tpch.orders"}

    def test_records_written_to_estimated_rows(self, parser):
        dag = parser.parse_explain_output("q1", _load("bigquery_query_plan_sample.json"))
        assert dag.estimated_rows == 1500000

    def test_registered_for_bigquery(self):
        assert isinstance(get_parser_for_platform("bigquery"), BigQueryQueryPlanParser)


class TestBigQueryStageMapping:
    @pytest.mark.parametrize(
        ("name", "kinds", "expected"),
        [
            ("S00: Input", ["READ", "WRITE"], LogicalOperatorType.SCAN),
            ("S01: Join+", ["READ", "JOIN", "WRITE"], LogicalOperatorType.JOIN),
            ("S02: Aggregate+", ["READ", "AGGREGATE", "WRITE"], LogicalOperatorType.AGGREGATE),
            ("S03: Sort+", ["READ", "SORT", "WRITE"], LogicalOperatorType.SORT),
            ("S04: Output", ["READ", "WRITE"], LogicalOperatorType.SCAN),
            ("S05: Output", [], LogicalOperatorType.PROJECT),
            ("S06: Mystery", [], LogicalOperatorType.OTHER),
        ],
    )
    def test_map_stage_type(self, parser, name, kinds, expected):
        assert parser._map_stage_type(name, kinds) == expected


class TestBigQueryErrorHandling:
    def test_empty_returns_none(self, parser):
        assert parser.parse_explain_output("q1", "") is None

    def test_invalid_json_returns_none(self, parser):
        assert parser.parse_explain_output("q1", "[not json") is None

    def test_empty_list_returns_none(self, parser):
        assert parser.parse_explain_output("q1", "[]") is None
