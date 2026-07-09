"""Plan-capture wiring tests for the cloud SaaS platform family.

Covers Snowflake, BigQuery, Azure Synapse, Firebolt, Fabric Warehouse, and
LakeSail. All tests are driven by recorded EXPLAIN/plan fixtures under
``tests/fixtures/query_plans/`` and fake/mocked connections, so no cloud account
(and no cloud credentials) is required.

Properties checked per platform:
  1. ``get_query_plan_parser()`` returns the expected non-None parser.
  2. ``execute_query()`` with ``capture_plans=True`` parses and stores a
     ``QueryPlanDAG`` plus ``plan_fingerprint``.
  3. Capture degrades gracefully: nothing extra runs when capture is disabled,
     and a successful query with an unavailable plan still returns
     ``status=SUCCESS``.

BigQuery has no EXPLAIN statement; its plan comes from the completed job's
statistics, so it is covered by exercising ``_capture_bq_plan`` directly with a
mock ``QueryJob`` (per the design in the cloud-saas TODO).
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from benchbox.core.query_plans.parsers.azure_synapse import AzureSynapseQueryPlanParser
from benchbox.core.query_plans.parsers.bigquery import BigQueryQueryPlanParser
from benchbox.core.query_plans.parsers.fabric_warehouse import FabricWarehouseQueryPlanParser
from benchbox.core.query_plans.parsers.firebolt import FireboltQueryPlanParser
from benchbox.core.query_plans.parsers.registry import get_parser_for_platform
from benchbox.core.query_plans.parsers.snowflake import SnowflakeQueryPlanParser
from benchbox.core.query_plans.parsers.spark import SparkQueryPlanParser

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "query_plans"


def _load(name: str) -> str:
    return (_FIXTURES / name).read_text()


# ---------------------------------------------------------------------------
# Registry resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("platform", "parser_cls"),
    [
        ("snowflake", SnowflakeQueryPlanParser),
        ("bigquery", BigQueryQueryPlanParser),
        ("azure_synapse", AzureSynapseQueryPlanParser),
        ("firebolt", FireboltQueryPlanParser),
        ("fabric_warehouse", FabricWarehouseQueryPlanParser),
        # LakeSail is a Spark-Connect engine and reuses the Spark parser.
        ("lakesail", SparkQueryPlanParser),
    ],
)
def test_registry_resolves_platform(platform, parser_cls):
    assert isinstance(get_parser_for_platform(platform), parser_cls)


# ---------------------------------------------------------------------------
# Adapter construction helpers (bypass the dependency guard; no driver needed)
# ---------------------------------------------------------------------------


def _build(module_name: str, class_name: str, monkeypatch, **config):
    module = importlib.import_module(module_name)
    if hasattr(module, "check_platform_dependencies"):
        monkeypatch.setattr(module, "check_platform_dependencies", lambda *a, **k: (True, []))
    adapter = getattr(module, class_name)(capture_plans=True, **config)
    return adapter


def _make_snowflake(monkeypatch):
    adapter = _build(
        "benchbox.platforms.snowflake",
        "SnowflakeAdapter",
        monkeypatch,
        account="a",
        username="u",
        password="p",
        warehouse="w",
        database="d",
    )
    # _get_query_statistics queries Snowflake's query history; stub it out.
    monkeypatch.setattr(adapter, "_get_query_statistics", lambda *a, **k: {})
    return adapter


def _make_azure_synapse(monkeypatch):
    return _build(
        "benchbox.platforms.azure_synapse",
        "AzureSynapseAdapter",
        monkeypatch,
        server="s",
        username="u",
        password="p",
        database="d",
    )


def _make_firebolt(monkeypatch):
    return _build("benchbox.platforms.firebolt", "FireboltAdapter", monkeypatch)


def _make_fabric(monkeypatch):
    return _build(
        "benchbox.platforms.fabric_warehouse",
        "FabricWarehouseAdapter",
        monkeypatch,
        server="s.datawarehouse.fabric.microsoft.com",
        database="d",
        username="u",
        password="p",
    )


def _cursor_conn():
    """A DB-API-style connection whose cursor returns one row for any query."""
    conn = MagicMock()
    cursor = conn.cursor.return_value
    cursor.fetchall.return_value = [(1,)]
    cursor.fetchone.return_value = (1,)
    return conn


# ---------------------------------------------------------------------------
# Cursor-style adapters: Snowflake / Azure Synapse / Firebolt / Fabric
# ---------------------------------------------------------------------------

# (make, fixture, parser_cls, call_kwargs)
# Fabric Warehouse's execute_query signature predates the validation kwargs, so
# its call kwargs differ from the validation-aware cursor adapters.
_CURSOR_CASES = [
    (_make_snowflake, "snowflake_explain_sample.json", SnowflakeQueryPlanParser, {"validate_row_count": False}),
    (
        _make_azure_synapse,
        "azure_synapse_explain_sample.xml",
        AzureSynapseQueryPlanParser,
        {"validate_row_count": False},
    ),
    (_make_firebolt, "firebolt_explain_sample.txt", FireboltQueryPlanParser, {"validate_row_count": False}),
    (_make_fabric, "fabric_warehouse_showplan_sample.txt", FabricWarehouseQueryPlanParser, {}),
]


class TestCursorAdapterWiring:
    @pytest.mark.parametrize(("make", "fixture", "parser_cls", "call_kwargs"), _CURSOR_CASES)
    def test_parser_is_expected(self, make, fixture, parser_cls, call_kwargs, monkeypatch):
        adapter = make(monkeypatch)
        assert isinstance(adapter.get_query_plan_parser(), parser_cls)

    @pytest.mark.parametrize(("make", "fixture", "parser_cls", "call_kwargs"), _CURSOR_CASES)
    def test_execute_query_captures_plan(self, make, fixture, parser_cls, call_kwargs, monkeypatch):
        adapter = make(monkeypatch)
        monkeypatch.setattr(adapter, "get_query_plan", lambda *a, **k: _load(fixture))
        result = adapter.execute_query(_cursor_conn(), "SELECT 1", "q1", **call_kwargs)
        assert result["status"] == "SUCCESS"
        assert result["query_plan"] is not None
        assert result["plan_fingerprint"] == result["query_plan"].plan_fingerprint

    @pytest.mark.parametrize(("make", "fixture", "parser_cls", "call_kwargs"), _CURSOR_CASES)
    def test_no_capture_when_disabled(self, make, fixture, parser_cls, call_kwargs, monkeypatch):
        adapter = make(monkeypatch)
        adapter.capture_plans = False
        boom = MagicMock(side_effect=AssertionError("EXPLAIN must not run when capture is disabled"))
        monkeypatch.setattr(adapter, "get_query_plan", boom)
        result = adapter.execute_query(_cursor_conn(), "SELECT 1", "q2", **call_kwargs)
        assert result["status"] == "SUCCESS"
        assert "query_plan" not in result

    @pytest.mark.parametrize(("make", "fixture", "parser_cls", "call_kwargs"), _CURSOR_CASES)
    def test_graceful_when_plan_unavailable(self, make, fixture, parser_cls, call_kwargs, monkeypatch):
        adapter = make(monkeypatch)
        monkeypatch.setattr(adapter, "get_query_plan", lambda *a, **k: None)
        result = adapter.execute_query(_cursor_conn(), "SELECT 1", "q3", **call_kwargs)
        assert result["status"] == "SUCCESS"
        assert "query_plan" not in result

    @pytest.mark.parametrize(("make", "fixture", "parser_cls", "call_kwargs"), _CURSOR_CASES)
    def test_strict_capture_failure_propagates(self, make, fixture, parser_cls, call_kwargs, monkeypatch):
        # The capture must sit outside the adapter's broad except so a strict
        # PlanCaptureError surfaces instead of mislabeling the query FAILED.
        from benchbox.core.errors import PlanCaptureError

        adapter = make(monkeypatch)
        adapter.strict_plan_capture = True

        def boom(*a, **k):
            raise RuntimeError("EXPLAIN blew up")

        monkeypatch.setattr(adapter, "get_query_plan", boom)
        with pytest.raises(PlanCaptureError):
            adapter.execute_query(_cursor_conn(), "SELECT 1", "q_strict", **call_kwargs)


# ---------------------------------------------------------------------------
# LakeSail (Spark-Connect engine: reuses Spark execution mixin + Spark parser)
# ---------------------------------------------------------------------------


class _DF:
    def __init__(self, rows):
        self._rows = rows

    def collect(self):
        return self._rows


class _FakeSpark:
    def __init__(self):
        self.queries = []

    def sql(self, query):
        self.queries.append(query)
        if query.strip().upper().startswith("EXPLAIN"):
            return _DF([(_load("spark_explain_sample.txt"),)])
        return _DF([(1,)])


class TestLakeSailWiring:
    @pytest.fixture()
    def adapter(self, monkeypatch):
        adapter = _build("benchbox.platforms.lakesail", "LakeSailAdapter", monkeypatch)
        adapter.disable_cache = False  # avoid catalog.clearCache() on the fake session
        return adapter

    def test_parser_is_spark(self, adapter):
        assert isinstance(adapter.get_query_plan_parser(), SparkQueryPlanParser)

    def test_execute_query_captures_plan(self, adapter, monkeypatch):
        monkeypatch.setattr(adapter, "get_query_plan", lambda *a, **k: _load("spark_explain_sample.txt"))
        result = adapter.execute_query(_FakeSpark(), "SELECT 1", "q1", validate_row_count=False)
        assert result["status"] == "SUCCESS"
        assert result["query_plan"] is not None
        assert result["plan_fingerprint"] == result["query_plan"].plan_fingerprint

    def test_no_capture_when_disabled(self, adapter):
        adapter.capture_plans = False
        spark = _FakeSpark()
        result = adapter.execute_query(spark, "SELECT 1", "q2", validate_row_count=False)
        assert result["status"] == "SUCCESS"
        assert "query_plan" not in result or result.get("query_plan") is None
        assert not any(q.strip().upper().startswith("EXPLAIN") for q in spark.queries)

    def test_graceful_when_plan_unavailable(self, adapter, monkeypatch):
        monkeypatch.setattr(adapter, "get_query_plan", lambda *a, **k: None)
        result = adapter.execute_query(_FakeSpark(), "SELECT 1", "q3", validate_row_count=False)
        assert result["status"] == "SUCCESS"
        assert "query_plan" not in result or result.get("query_plan") is None


# ---------------------------------------------------------------------------
# BigQuery (no EXPLAIN; plan comes from job statistics via _capture_bq_plan)
# ---------------------------------------------------------------------------


def _make_bigquery(monkeypatch):
    return _build("benchbox.platforms.bigquery", "BigQueryAdapter", monkeypatch, project_id="proj")


class _FakeQueryJob:
    """Minimal stand-in for a completed ``google.cloud.bigquery.QueryJob``."""

    def __init__(self, query_plan):
        self.query_plan = query_plan


class TestBigQueryCapture:
    def test_parser_is_bigquery(self, monkeypatch):
        adapter = _make_bigquery(monkeypatch)
        assert isinstance(adapter.get_query_plan_parser(), BigQueryQueryPlanParser)

    def test_get_query_plan_unchanged_returns_cost_dict(self, monkeypatch):
        # The plan-capture path must NOT repurpose get_query_plan; it still
        # returns a cost/dry-run dict (or an error dict), never a DAG.
        adapter = _make_bigquery(monkeypatch)
        result = adapter.get_query_plan(MagicMock(), "SELECT 1")
        assert isinstance(result, dict)

    def test_capture_bq_plan_builds_dag(self, monkeypatch):
        adapter = _make_bigquery(monkeypatch)
        stages = json.loads(_load("bigquery_query_plan_sample.json"))
        plan, capture_ms = adapter._capture_bq_plan(_FakeQueryJob(stages), "q1")
        assert plan is not None
        assert plan.platform == "bigquery"
        assert plan.plan_fingerprint is not None
        assert capture_ms >= 0

    def test_capture_bq_plan_disabled_is_noop(self, monkeypatch):
        adapter = _make_bigquery(monkeypatch)
        adapter.capture_plans = False
        stages = json.loads(_load("bigquery_query_plan_sample.json"))
        plan, capture_ms = adapter._capture_bq_plan(_FakeQueryJob(stages), "q2")
        assert plan is None
        assert capture_ms == 0.0

    def test_capture_bq_plan_graceful_without_stages(self, monkeypatch):
        adapter = _make_bigquery(monkeypatch)
        plan, _ = adapter._capture_bq_plan(_FakeQueryJob([]), "q3")
        assert plan is None
        # A successful query whose job exposes no plan must not raise in non-strict
        # mode; the failure is recorded for observability instead.
        assert adapter.plan_capture_failures >= 1
