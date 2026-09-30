"""Databricks cache enforcement across session setup, measurement and bundles."""

import json
from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from benchbox.core.exceptions import ConfigurationError
from benchbox.core.results.models import BenchmarkResults
from benchbox.core.results.schema import build_result_payload
from benchbox.core.tuning.applied_ledger import PHASE_SESSION, AppliedTuningLedger, recording_connection
from benchbox.platforms.databricks import DatabricksAdapter
from benchbox.validation.bundle import ValidationResult, _validate_cache_control_section

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.fixture
def adapter():
    with patch("benchbox.platforms.databricks.adapter.check_platform_dependencies", return_value=(True, [])):
        return DatabricksAdapter(
            server_hostname="test.cloud.databricks.com", http_path="/sql/1.0/warehouses/test", access_token="test"
        )


class Session:
    def __init__(self, *, reject=None, value="false"):
        self.commands = []
        self.reject = reject
        self.value = value
        self.closed = False

    def cursor(self):
        return Cursor(self)

    def close(self):
        self.closed = True


class Cursor:
    __slots__ = ("connection", "closed")

    def __init__(self, connection):
        self.connection = connection
        self.closed = False

    def execute(self, sql):
        self.connection.commands.append(sql)
        if sql == self.connection.reject:
            raise RuntimeError("rejected")

    def fetchall(self):
        return [(1,)]

    def fetchone(self):
        value = self.connection.value
        return None if value is None else ("use_cached_result", value)

    def close(self):
        self.closed = True


def test_none_defaults_to_required_disable(adapter):
    with patch("benchbox.platforms.databricks.adapter.check_platform_dependencies", return_value=(True, [])):
        configured = DatabricksAdapter(
            server_hostname="test", http_path="test", access_token="test", disable_result_cache=None
        )
    assert configured.disable_result_cache is True
    session = Session()
    assert configured.execute_query(session, "SELECT 1", "q1")["status"] == "SUCCESS"
    assert session.commands == ["SET use_cached_result = false", "SET use_cached_result", "SELECT 1"]


@pytest.mark.parametrize(
    "reject,value",
    [("SET use_cached_result = false", "false"), ("SET use_cached_result", "false"), (None, "true"), (None, None)],
)
def test_failed_set_or_probe_never_executes_benchmark_sql(adapter, reject, value):
    session = Session(reject=reject, value=value)
    result = adapter.execute_query(session, "SELECT expensive_query", "q1")
    assert result["status"] == "FAILED"
    assert result["execution_time_seconds"] == 0.0
    assert "SELECT expensive_query" not in session.commands
    assert adapter._cache_control_receipt["validated"] is False
    assert adapter._cache_control_receipt["errors"]


def test_distinct_slotted_cursors_share_actual_session_and_single_ledger_capture(adapter):
    session = Session()
    ledger = AppliedTuningLedger()
    adapter._applied_tuning_ledger = ledger
    wrapped = recording_connection(session, ledger, PHASE_SESSION)
    adapter._ensure_session_cache_disabled(wrapped.cursor())
    adapter._ensure_session_cache_disabled(session.cursor())
    adapter.execute_query(wrapped, "SELECT 1", "q1")
    assert session.commands.count("SET use_cached_result = false") == 1
    assert len(ledger.statements) == 1
    assert ledger.statements[0].statement == "SET use_cached_result = false"


def test_dynamic_cursor_attributes_do_not_invent_session_keys(adapter):
    cursor = Mock(spec=["execute", "fetchall", "fetchone"])
    cursor.fetchone.return_value = ("use_cached_result", "false")
    adapter._ensure_session_cache_disabled(cursor)
    adapter._ensure_session_cache_disabled(cursor)
    assert cursor.execute.call_count == 2


@pytest.mark.parametrize("entry", ["create", "configure"])
def test_old_setup_paths_propagate_rejected_set(adapter, entry):
    session = Session(reject="SET use_cached_result = false")
    with (
        patch.object(adapter, "handle_existing_database"),
        patch.object(adapter, "_create_admin_connection", return_value=session),
    ):
        with pytest.raises(ConfigurationError):
            if entry == "create":
                adapter.create_connection()
            else:
                adapter.configure_for_benchmark(session, "tpch")
    assert adapter._cache_control_receipt["validated"] is False
    if entry == "create":
        assert session.closed


def test_setup_and_execute_have_one_capture_owner(adapter):
    session = Session()
    ledger = AppliedTuningLedger()
    adapter._applied_tuning_ledger = ledger
    with (
        patch.object(adapter, "handle_existing_database"),
        patch.object(adapter, "_create_admin_connection", return_value=session),
    ):
        connection = adapter.create_connection()
    adapter.spark_configs = {"use_cached_result": "false"}
    adapter.configure_for_benchmark(recording_connection(connection, ledger, PHASE_SESSION), "tpch")
    adapter.execute_query(connection, "SELECT 1", "q1")
    assert len(ledger.statements) == 1


@pytest.mark.parametrize("factory", ["_make_direct_power_connection_adapter", "_make_power_connection_adapter"])
def test_zero_warmup_power_factory_initializes_before_harness_execution(adapter, factory):
    session = Session()
    wrapper = getattr(adapter, factory)(session, "tpch", 1.0)
    assert session.commands == ["SET use_cached_result = false", "SET use_cached_result"]
    # The harness has not started. Its first query must not do session setup.
    session.commands.clear()
    wrapper.execute("SELECT 1")
    assert session.commands == ["SELECT 1"]


def test_new_throughput_stream_is_initialized_before_first_query(adapter):
    session = Session()
    stream = adapter.new_stream_connection(session)
    assert session.commands == ["SET use_cached_result = false", "SET use_cached_result"]
    session.commands.clear()
    adapter.execute_query(stream, "SELECT 1", "q1")
    assert session.commands == ["SELECT 1"]


@pytest.mark.parametrize(
    "value,enabled,reject",
    [
        ("false", False, None),
        ("true", False, None),
        (None, False, None),
        ("true", True, None),
        ("false", False, "SET use_cached_result = false"),
    ],
)
def test_producer_persistence_validator_seam(adapter, value, enabled, reject):
    adapter.disable_result_cache = not enabled
    session = Session(value=value, reject=reject)
    result = adapter.execute_query(session, "SELECT 1", "q1")
    metadata = adapter.get_normalized_result_metadata(platform_info={})
    receipt = metadata["platform_compute"]["cache_control"]
    benchmark = BenchmarkResults(
        benchmark_name="tpch",
        platform="Databricks",
        scale_factor=1.0,
        execution_id="cache-test",
        timestamp=datetime(2026, 1, 1),
        duration_seconds=1.0,
        total_queries=1,
        successful_queries=int(result["status"] == "SUCCESS"),
        failed_queries=int(result["status"] == "FAILED"),
        platform_compute=metadata["platform_compute"],
    )
    payload = json.loads(json.dumps(build_result_payload(benchmark)))
    from benchbox.platforms.cloud_shared import sanitize_cache_control_receipt

    assert sanitize_cache_control_receipt(payload["platform"]["compute"]["cache_control"]) == receipt
    validation = ValidationResult("cache-test")
    _validate_cache_control_section(payload["platform"], validation)
    assert validation.ok is (value == "false" and not enabled and reject is None)
    if value != "false" or enabled or reject is not None:
        assert validation.errors


def test_failed_session_cannot_be_hidden_by_later_success(adapter):
    adapter.execute_query(Session(value="true"), "SELECT 1", "q1")
    adapter.execute_query(Session(), "SELECT 1", "q2")
    assert adapter._cache_control_receipt["validated"] is False
    assert adapter._cache_control_receipt["errors"]


def test_throughput_setup_precedes_parent_harness_timer(adapter):
    from benchbox.platforms.base.execution import TestDriversMixin

    session = Session()

    def timed_parent(self, benchmark, connection, run_config):
        assert session.commands == ["SET use_cached_result = false", "SET use_cached_result"]
        session.commands.clear()
        stream = self.new_stream_connection(connection)
        self.execute_query(stream, "SELECT 1", "q1")
        assert session.commands == ["SELECT 1"]
        return []

    with patch.object(TestDriversMixin, "_execute_tpch_throughput_test", timed_parent):
        assert adapter._execute_tpch_throughput_test(Mock(), session, {}) == []


def test_unsupported_readback_shape_refuses_execution(adapter):
    cursor = Mock(spec=["execute", "fetchall", "fetchone"])
    cursor.fetchone.return_value = ("different_setting", "false")
    with pytest.raises(ConfigurationError):
        adapter._ensure_session_cache_disabled(cursor)
    assert "Unsupported cache readback" in adapter._cache_control_receipt["errors"][0]


def test_zero_warmup_real_power_runner_initializes_before_run_timer(adapter):
    from benchbox.core.tpch.power_test import TPCHPowerTest

    session = Session()
    benchmark = Mock()

    def timed_run(power):
        assert session.commands == ["SET use_cached_result = false", "SET use_cached_result"]
        session.commands.clear()
        power.connection.execute("SELECT 1")
        assert session.commands == ["SELECT 1"]
        return Mock(query_results=[], success=True)

    with patch.object(TPCHPowerTest, "run", timed_run):
        adapter._execute_tpch_power_test(
            benchmark, session, {"warm_up_iterations": 0, "iterations": 1, "seed": 42, "query_subset": ["1"]}
        )


def test_custom_spark_configuration_cannot_undo_cache_disable(adapter):
    adapter.spark_configs = {"use_cached_result": "true"}
    session = Session()
    with pytest.raises(ConfigurationError, match="conflicts"):
        adapter.configure_for_benchmark(session, "tpch")
    assert not session.commands
    assert adapter._cache_control_receipt["validated"] is False


def test_rejected_set_has_exactly_one_failed_ledger_entry(adapter):
    session = Session(reject="SET use_cached_result = false")
    ledger = AppliedTuningLedger()
    adapter._applied_tuning_ledger = ledger
    result = adapter.execute_query(recording_connection(session, ledger, PHASE_SESSION), "SELECT 1", "q1")
    assert result["status"] == "FAILED"
    assert len(ledger.statements) == 1
    assert ledger.statements[0].status == "failed"
    assert session.commands == ["SET use_cached_result = false"]


def test_unsupported_session_identity_refuses_before_measurement(adapter):
    class UntrackableCursor:
        __slots__ = ()

    with pytest.raises(ConfigurationError, match="Unsupported session identity"):
        adapter._ensure_session_cache_disabled(UntrackableCursor())
    assert adapter._cache_control_receipt["validated"] is False


def test_metadata_never_labels_intent_as_observed_disabled(adapter):
    metadata = adapter.get_normalized_result_metadata(platform_info={"configuration": {"result_cache_enabled": False}})
    assert "result_cache_enabled" not in metadata["platform_compute"]
