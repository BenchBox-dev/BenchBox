"""Unit tests for AzureSynapseQueryPlanParser.

Driven by a recorded Dedicated SQL Pool ``EXPLAIN`` (distributed dsql XML)
fixture under tests/fixtures/query_plans/ so they run with no live Synapse
workspace.
"""

from pathlib import Path

import pytest

from benchbox.core.query_plans.parsers.azure_synapse import AzureSynapseQueryPlanParser
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
    return AzureSynapseQueryPlanParser()


class TestAzureSynapsePlan:
    def test_parses_to_valid_dag(self, parser):
        dag = parser.parse_explain_output("q1", _load("azure_synapse_explain_sample.xml"))
        assert dag is not None
        assert dag.logical_root is not None
        assert dag.plan_fingerprint is not None
        assert dag.platform == "azure_synapse"

    def test_root_is_return_projection(self, parser):
        dag = parser.parse_explain_output("q1", _load("azure_synapse_explain_sample.xml"))
        assert dag.logical_root.operator_type == LogicalOperatorType.PROJECT
        assert dag.logical_root.physical_operator.operator_type == "RETURN"

    def test_distributed_chain_preserved(self, parser):
        # The dsql plan is a linear pipeline: RETURN -> SHUFFLE_MOVE -> ON -> RND_ID.
        dag = parser.parse_explain_output("q1", _load("azure_synapse_explain_sample.xml"))
        nodes = _collect(dag.logical_root)
        physical = [n.physical_operator.operator_type for n in nodes]
        assert physical == ["RETURN", "SHUFFLE_MOVE", "ON", "RND_ID"]

    def test_data_movement_maps_to_other(self, parser):
        dag = parser.parse_explain_output("q1", _load("azure_synapse_explain_sample.xml"))
        move = next(n for n in _collect(dag.logical_root) if n.physical_operator.operator_type == "SHUFFLE_MOVE")
        assert move.operator_type == LogicalOperatorType.OTHER

    def test_cost_and_rows_extracted(self, parser):
        dag = parser.parse_explain_output("q1", _load("azure_synapse_explain_sample.xml"))
        assert dag.estimated_cost == pytest.approx(2.345)
        assert dag.estimated_rows == 1500000

    def test_registered_for_synapse_aliases(self):
        assert isinstance(get_parser_for_platform("azure_synapse"), AzureSynapseQueryPlanParser)
        assert isinstance(get_parser_for_platform("synapse"), AzureSynapseQueryPlanParser)


class TestAzureSynapseErrorHandling:
    def test_empty_returns_none(self, parser):
        assert parser.parse_explain_output("q1", "") is None

    def test_non_xml_returns_none(self, parser):
        assert parser.parse_explain_output("q1", "Could not get query plan: boom") is None

    def test_missing_operations_returns_none(self, parser):
        assert parser.parse_explain_output("q1", "<dsql_query></dsql_query>") is None
