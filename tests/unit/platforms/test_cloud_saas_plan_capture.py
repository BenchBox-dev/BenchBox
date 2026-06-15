"""Adapter-level plan-capture wiring tests for the cloud SaaS warehouses.

Covers the five platforms wired in this change — Snowflake, BigQuery,
Azure Synapse, Fabric Warehouse, and LakeSail — with mocked connections so no
cloud credentials are required:

- ``get_query_plan_parser()`` returns the expected non-None parser.
- ``execute_query()`` with ``capture_plans=True`` attaches a ``query_plan`` /
  ``plan_fingerprint`` to the result (BigQuery via ``_capture_bq_plan`` since it
  has no EXPLAIN statement).
- capture failure degrades gracefully (no exception, result still SUCCESS) when
  ``strict_plan_capture`` is False, and propagates when it is True.

Firebolt is intentionally absent: its parser/wiring is deferred (blocked on a
recorded EXPLAIN fixture) — see the source TODO's w5 notes.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

import benchbox.platforms.azure_synapse as synapse_module
import benchbox.platforms.fabric_warehouse as fabric_module
from benchbox.core.errors import PlanCaptureError
from benchbox.core.query_plans.parsers.azure_synapse import AzureSynapseQueryPlanParser
from benchbox.core.query_plans.parsers.bigquery import BigQueryQueryPlanParser
from benchbox.core.query_plans.parsers.fabric_warehouse import FabricWarehouseQueryPlanParser
from benchbox.core.query_plans.parsers.snowflake import SnowflakeQueryPlanParser
from benchbox.core.query_plans.parsers.spark import SparkQueryPlanParser

pytestmark = [pytest.mark.unit, pytest.mark.fast]

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "query_plans"


def _fixture(name: str) -> str:
    return (_FIXTURES / name).read_text()


# ---------------------------------------------------------------------------
# Adapter builders (context managers keeping required module patches active)
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _snowflake_adapter():
    from benchbox.platforms.snowflake import SnowflakeAdapter

    with (
        patch("benchbox.platforms.snowflake.check_platform_dependencies", return_value=(True, [])),
        patch("benchbox.platforms.snowflake.snowflake"),
    ):
        adapter = SnowflakeAdapter(account="acct", username="u", password="p")
        yield adapter


@contextlib.contextmanager
def _azure_synapse_adapter():
    from benchbox.platforms.azure_synapse import AzureSynapseAdapter

    mock_pyodbc = Mock()
    with (
        patch.object(synapse_module, "pyodbc", mock_pyodbc),
        patch.object(synapse_module, "check_platform_dependencies", lambda *a, **k: (True, [])),
    ):
        adapter = AzureSynapseAdapter(server="ws.sql.azuresynapse.net", username="admin", password="secret")
        yield adapter


@contextlib.contextmanager
def _fabric_adapter():
    from benchbox.platforms.fabric_warehouse import FabricWarehouseAdapter

    mock_pyodbc = MagicMock()
    mock_pyodbc.Error = Exception
    with (
        patch.object(fabric_module, "pyodbc", mock_pyodbc),
        patch.object(fabric_module, "check_platform_dependencies", lambda *a, **k: (True, [])),
    ):
        adapter = FabricWarehouseAdapter(workspace="ws", warehouse="wh", auth_method="default_credential")
        yield adapter


@contextlib.contextmanager
def _bigquery_adapter():
    from benchbox.platforms.bigquery import BigQueryAdapter

    with (
        patch("benchbox.platforms.bigquery.check_platform_dependencies", return_value=(True, [])),
        patch("benchbox.platforms.bigquery.bigquery"),
    ):
        adapter = BigQueryAdapter(project_id="proj", dataset_id="ds")
        yield adapter


@contextlib.contextmanager
def _lakesail_adapter():
    with patch.dict(
        "sys.modules",
        {
            "pyspark": MagicMock(),
            "pyspark.sql": MagicMock(SparkSession=MagicMock()),
            "pyspark.sql.types": MagicMock(),
        },
    ):
        from benchbox.platforms.lakesail import LakeSailAdapter

        yield LakeSailAdapter()


_BUILDERS = {
    "snowflake": (_snowflake_adapter, SnowflakeQueryPlanParser),
    "bigquery": (_bigquery_adapter, BigQueryQueryPlanParser),
    "azure_synapse": (_azure_synapse_adapter, AzureSynapseQueryPlanParser),
    "fabric_warehouse": (_fabric_adapter, FabricWarehouseQueryPlanParser),
    "lakesail": (_lakesail_adapter, SparkQueryPlanParser),
}


# ---------------------------------------------------------------------------
# get_query_plan_parser() returns the expected parser for every wired adapter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("platform", sorted(_BUILDERS))
def test_get_query_plan_parser_non_none(platform):
    builder, expected_type = _BUILDERS[platform]
    with builder() as adapter:
        parser = adapter.get_query_plan_parser()
        assert parser is not None
        assert isinstance(parser, expected_type)


# ---------------------------------------------------------------------------
# Snowflake: EXPLAIN USING JSON capture
# ---------------------------------------------------------------------------


class TestSnowflakeCapture:
    def _connection_for(self, query_rows, plan_payload):
        cursor = Mock()
        cursor.fetchall.side_effect = [query_rows, plan_payload]
        connection = Mock()
        connection.cursor.return_value = cursor
        return connection

    def test_capture_attaches_plan(self):
        with _snowflake_adapter() as adapter:
            adapter.capture_plans = True
            adapter._get_query_statistics = lambda *a, **k: {}
            connection = self._connection_for([(1, 2)], [(_fixture("snowflake_explain_sample.json"),)])
            result = adapter.execute_query(connection, "SELECT 1", "q1")
            assert result["status"] == "SUCCESS"
            assert "query_plan" in result
            assert result["plan_fingerprint"]

    def test_no_explain_when_capture_disabled(self):
        with _snowflake_adapter() as adapter:
            adapter.capture_plans = False
            adapter._get_query_statistics = lambda *a, **k: {}
            adapter.get_query_plan = Mock(side_effect=AssertionError("EXPLAIN must not run"))
            connection = self._connection_for([(1, 2)], [])
            result = adapter.execute_query(connection, "SELECT 1", "q1")
            assert result["status"] == "SUCCESS"
            assert "query_plan" not in result
            adapter.get_query_plan.assert_not_called()

    def test_capture_failure_is_silent(self):
        with _snowflake_adapter() as adapter:
            adapter.capture_plans = True
            adapter.strict_plan_capture = False
            adapter._get_query_statistics = lambda *a, **k: {}
            adapter.get_query_plan = Mock(return_value=None)
            connection = self._connection_for([(1, 2)], [])
            result = adapter.execute_query(connection, "SELECT 1", "q1")
            assert result["status"] == "SUCCESS"
            assert "query_plan" not in result


# ---------------------------------------------------------------------------
# Azure Synapse: EXPLAIN -> dsql XML capture
# ---------------------------------------------------------------------------


class TestAzureSynapseCapture:
    def _connection_for(self, query_rows, plan_rows):
        cursor = Mock()
        cursor.fetchall.side_effect = [query_rows, plan_rows]
        connection = Mock()
        connection.cursor.return_value = cursor
        return connection

    def test_capture_attaches_plan(self):
        with _azure_synapse_adapter() as adapter:
            adapter.capture_plans = True
            connection = self._connection_for([(1,)], [(_fixture("azure_synapse_explain_sample.xml"),)])
            result = adapter.execute_query(connection, "SELECT 1", "q1")
            assert result["status"] == "SUCCESS"
            assert "query_plan" in result
            assert result["plan_fingerprint"]

    def test_capture_failure_is_silent(self):
        with _azure_synapse_adapter() as adapter:
            adapter.capture_plans = True
            adapter.strict_plan_capture = False
            adapter.get_query_plan = Mock(return_value="Could not get query plan: boom")
            connection = self._connection_for([(1,)], [])
            result = adapter.execute_query(connection, "SELECT 1", "q1")
            assert result["status"] == "SUCCESS"
            assert "query_plan" not in result


# ---------------------------------------------------------------------------
# Fabric Warehouse: SET SHOWPLAN_TEXT capture
# ---------------------------------------------------------------------------


class TestFabricWarehouseCapture:
    def _connection_for(self, query_rows, plan_rows):
        cursor = Mock()
        cursor.fetchall.side_effect = [query_rows, plan_rows]
        connection = Mock()
        connection.cursor.return_value = cursor
        return connection

    def test_capture_attaches_plan(self):
        with _fabric_adapter() as adapter:
            adapter.capture_plans = True
            plan_rows = [(line,) for line in _fixture("fabric_warehouse_showplan_sample.txt").splitlines()]
            connection = self._connection_for([(1,)], plan_rows)
            result = adapter.execute_query(connection, "SELECT 1", "q1")
            assert result["status"] == "SUCCESS"
            assert "query_plan" in result
            assert result["plan_fingerprint"]

    def test_capture_failure_is_silent(self):
        with _fabric_adapter() as adapter:
            adapter.capture_plans = True
            adapter.strict_plan_capture = False
            adapter.get_query_plan = Mock(return_value="Failed to get query plan: boom")
            connection = self._connection_for([(1,)], [])
            result = adapter.execute_query(connection, "SELECT 1", "q1")
            assert result["status"] == "SUCCESS"
            assert "query_plan" not in result

    def test_showplan_turned_off_when_explain_query_fails(self):
        # SHOWPLAN_TEXT is session-scoped: a failure after SET ... ON must still
        # issue SET ... OFF, or later statements return plans instead of running.
        with _fabric_adapter() as adapter:
            cursor = Mock()
            cursor.execute.side_effect = (
                lambda sql: (_ for _ in ()).throw(RuntimeError("boom")) if sql == "BAD" else None
            )
            connection = Mock()
            connection.cursor.return_value = cursor
            plan = adapter.get_query_plan(connection, "BAD")
            assert plan.startswith("Failed to get query plan")
            executed = [c.args[0] for c in cursor.execute.call_args_list]
            assert "SET SHOWPLAN_TEXT ON" in executed
            assert "SET SHOWPLAN_TEXT OFF" in executed  # reset ran despite failure


# ---------------------------------------------------------------------------
# BigQuery: post-execution job-statistics capture (no EXPLAIN)
# ---------------------------------------------------------------------------


def _mock_query_job(stages_json: str | None):
    """Build a mock QueryJob whose query_plan mirrors a serialized stage list."""
    import json as _json

    job = Mock()
    if stages_json is None:
        job.query_plan = []
        return job
    entries = []
    for stage in _json.loads(stages_json):
        steps = []
        for s in stage.get("steps", []):
            step = Mock(substeps=s.get("substeps", []))
            step.kind = s["kind"]
            steps.append(step)
        entry = Mock(
            entry_id=stage.get("id"),
            status=stage.get("status"),
            records_read=stage.get("records_read"),
            records_written=stage.get("records_written"),
            input_stages=stage.get("input_stages", []),
            steps=steps,
        )
        # ``name`` is a reserved Mock constructor kwarg, so assign it explicitly.
        entry.name = stage.get("name")
        entries.append(entry)
    job.query_plan = entries
    return job


class TestBigQueryCapture:
    def test_capture_bq_plan_builds_dag(self):
        with _bigquery_adapter() as adapter:
            adapter.capture_plans = True
            job = _mock_query_job(_fixture("bigquery_query_plan_sample.json"))
            dag, ms = adapter._capture_bq_plan(job, "q1")
            assert dag is not None
            assert dag.plan_fingerprint
            assert ms >= 0
            assert adapter.query_plans_captured == 1

    def test_capture_bq_plan_no_extra_api_call(self):
        # The job object is read directly; no client/connection .query() is issued.
        with _bigquery_adapter() as adapter:
            adapter.capture_plans = True
            job = _mock_query_job(_fixture("bigquery_query_plan_sample.json"))
            adapter._capture_bq_plan(job, "q1")
            assert not job.query.called  # no second query/EXPLAIN against the job
            assert not job.result.called

    def test_empty_plan_degrades_silently(self):
        with _bigquery_adapter() as adapter:
            adapter.capture_plans = True
            adapter.strict_plan_capture = False
            dag, ms = adapter._capture_bq_plan(_mock_query_job(None), "q1")
            assert dag is None
            assert adapter.plan_capture_failures == 1

    def test_empty_plan_raises_in_strict_mode(self):
        with _bigquery_adapter() as adapter:
            adapter.capture_plans = True
            adapter.strict_plan_capture = True
            with pytest.raises(PlanCaptureError):
                adapter._capture_bq_plan(_mock_query_job(None), "q1")


# ---------------------------------------------------------------------------
# LakeSail: reuses the Spark parser over Spark Connect EXPLAIN text
# ---------------------------------------------------------------------------


class TestLakeSailCapture:
    def test_parser_is_spark(self):
        with _lakesail_adapter() as adapter:
            assert isinstance(adapter.get_query_plan_parser(), SparkQueryPlanParser)

    def test_get_query_plan_feeds_spark_parser(self):
        with _lakesail_adapter() as adapter:
            spark = MagicMock()
            df = MagicMock()
            df.collect.return_value = [(line,) for line in _fixture("spark_explain_sample.txt").splitlines()]
            spark.sql.return_value = df
            plan_text = adapter.get_query_plan(spark, "SELECT 1")
            dag = adapter.get_query_plan_parser().parse_explain_output("q1", plan_text)
            assert dag is not None
            assert dag.plan_fingerprint
