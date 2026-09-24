"""EXPLAIN-failure handling for the sentinel-sniffing plan parsers (qpc-13).

The inline ``get_query_plan`` implementations that returned
``"Could not get query plan: ..."`` as plan text now return ``None`` instead.
This file is an invariant regression suite for the kept defenses: the
retired ``"Could not"`` prefix and the still-emitted ``"Failed to get query
plan"`` prefix (MySQL-wire helper feeding Doris/SingleStore, QuestDB
adapter) must both keep being rejected — otherwise error text would parse
as a bogus one-node plan and captured-failure accounting would regress.
"""

import pytest

from benchbox.core.query_plans.parsers.databend import DatabendQueryPlanParser
from benchbox.core.query_plans.parsers.doris import DorisQueryPlanParser
from benchbox.core.query_plans.parsers.questdb import QuestDBQueryPlanParser
from benchbox.core.query_plans.parsers.singlestore import SingleStoreQueryPlanParser
from benchbox.core.query_plans.parsers.spark import SparkQueryPlanParser

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture(
    params=[
        DatabendQueryPlanParser(),
        DorisQueryPlanParser(),
        QuestDBQueryPlanParser(),
        SingleStoreQueryPlanParser(),
        SparkQueryPlanParser(),
    ],
    ids=["databend", "doris", "questdb", "singlestore", "spark"],
)
def parser(request):
    return request.param


class TestExplainFailureHandling:
    def test_failed_prefix_returns_none(self, parser):
        """A live EXPLAIN-failure string is rejected, never parsed as a plan."""
        assert parser.parse_explain_output("q", "Failed to get query plan: connection reset") is None

    def test_retired_prefix_returns_none(self, parser):
        """The retired prefix stays rejected as defense (stray/custom-adapter text)."""
        assert parser.parse_explain_output("q", "Could not get query plan: boom") is None

    def test_none_returns_none(self, parser):
        """The qpc-13 failure signal (get_query_plan returned None) yields no plan."""
        assert parser.parse_explain_output("q", None) is None

    def test_empty_returns_none(self, parser):
        assert parser.parse_explain_output("q", "") is None
        assert parser.parse_explain_output("q", "   \n  ") is None
