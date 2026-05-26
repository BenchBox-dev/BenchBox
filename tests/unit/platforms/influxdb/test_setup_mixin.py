from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from benchbox.platforms.influxdb.setup import InfluxDBSetupMixin

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _Adapter(InfluxDBSetupMixin):
    def __init__(self):
        self.logger = MagicMock()
        self.force_recreate = False
        self.log_operation_start = MagicMock()
        self.log_verbose = MagicMock()
        self.host = "localhost"
        self.port = 8086
        self.token = None
        self.org = None
        self.database = "benchbox"
        self.ssl = True
        self.verify_ssl = True
        self.ca_cert_path = None
        self.mode = "cloud"


class _BaseLifecycle:
    def __init__(self):
        self.base_handle_calls = []

    def handle_existing_database(self, **connection_config):
        self.base_handle_calls.append(connection_config)


class _AdapterWithBase(_Adapter, _BaseLifecycle):
    def __init__(self):
        _Adapter.__init__(self)
        _BaseLifecycle.__init__(self)


def test_setup_connection_params_defaults_and_overrides():
    adapter = _Adapter()
    adapter._setup_connection_params({"host": "influx.local", "token": "abc", "mode": "core", "ssl": False})

    assert adapter.host == "influx.local"
    assert adapter.token == "abc"
    assert adapter.mode == "core"
    assert adapter.ssl is False


def test_create_connection_success_and_close(monkeypatch):
    adapter = _Adapter()
    adapter.token = "abc"
    fake_conn = MagicMock()
    fake_conn.test_connection.return_value = True

    monkeypatch.setattr("benchbox.platforms.influxdb.setup.InfluxDBConnection", lambda **kwargs: fake_conn)

    conn = adapter.create_connection(host="localhost", port=8086)
    assert conn is fake_conn
    fake_conn.connect.assert_called_once_with()
    adapter.close_connection(conn)
    fake_conn.close.assert_called_once_with()


def test_create_connection_failure_paths(monkeypatch):
    adapter = _Adapter()
    adapter.token = "abc"
    fake_conn = MagicMock()
    fake_conn.test_connection.return_value = False
    monkeypatch.setattr("benchbox.platforms.influxdb.setup.InfluxDBConnection", lambda **kwargs: fake_conn)

    with pytest.raises(ConnectionError, match="Connection test failed"):
        adapter.create_connection()

    noisy_conn = MagicMock()
    noisy_conn.close.side_effect = RuntimeError("boom")
    adapter.close_connection(noisy_conn)
    adapter.logger.warning.assert_called()


def test_handle_existing_database_and_database_path():
    adapter = _Adapter()
    adapter.force_recreate = True
    adapter.handle_existing_database()
    adapter.logger.warning.assert_called()
    assert adapter.get_database_path() is None


def test_handle_existing_database_preserves_warning_and_delegates_to_base():
    adapter = _AdapterWithBase()
    adapter.force_recreate = True

    adapter.handle_existing_database(database="benchbox_test")

    adapter.logger.warning.assert_called_once()
    assert adapter.base_handle_calls == [{"database": "benchbox_test"}]


def test_check_benchmark_tables_exist_returns_true_when_all_tables_present(monkeypatch):
    adapter = _Adapter()
    adapter.benchmark = MagicMock()
    adapter.benchmark.tables = {"cpu": None, "mem": None}
    adapter.get_tables = MagicMock(return_value=["cpu", "mem"])
    fake_conn = MagicMock()
    monkeypatch.setattr("benchbox.platforms.influxdb.setup.InfluxDBConnection", lambda **kwargs: fake_conn)

    assert adapter.check_benchmark_tables_exist() is True

    fake_conn.connect.assert_called_once_with()
    adapter.get_tables.assert_called_once_with(fake_conn)
    fake_conn.close.assert_called_once_with()


def test_check_benchmark_tables_exist_returns_false_when_tables_missing(monkeypatch):
    adapter = _Adapter()
    adapter.benchmark = MagicMock()
    adapter.benchmark.tables = {"cpu": None, "mem": None}
    adapter.get_tables = MagicMock(return_value=["cpu"])
    fake_conn = MagicMock()
    monkeypatch.setattr("benchbox.platforms.influxdb.setup.InfluxDBConnection", lambda **kwargs: fake_conn)

    assert adapter.check_benchmark_tables_exist() is False

    fake_conn.connect.assert_called_once_with()
    adapter.get_tables.assert_called_once_with(fake_conn)
    fake_conn.close.assert_called_once_with()


def test_check_benchmark_tables_exist_returns_false_for_force_recreate(monkeypatch):
    adapter = _Adapter()
    adapter.force_recreate = True
    adapter.benchmark = MagicMock()
    adapter.benchmark.tables = {"cpu": None}
    connection_factory = MagicMock()
    monkeypatch.setattr("benchbox.platforms.influxdb.setup.InfluxDBConnection", connection_factory)

    assert adapter.check_benchmark_tables_exist() is False

    connection_factory.assert_not_called()


def test_check_benchmark_tables_exist_returns_false_when_connection_creation_fails(monkeypatch):
    adapter = _Adapter()
    adapter.benchmark = MagicMock()
    adapter.benchmark.tables = {"cpu": None}
    connection_factory = MagicMock(side_effect=RuntimeError("cannot create client"))
    monkeypatch.setattr("benchbox.platforms.influxdb.setup.InfluxDBConnection", connection_factory)

    assert adapter.check_benchmark_tables_exist() is False

    adapter.logger.debug.assert_called_once()
