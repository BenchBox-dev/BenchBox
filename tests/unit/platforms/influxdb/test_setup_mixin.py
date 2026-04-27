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
        self.host = "localhost"
        self.port = 8086
        self.token = None
        self.org = None
        self.database = "benchbox"
        self.ssl = True
        self.verify_ssl = True
        self.ca_cert_path = None
        self.mode = "cloud"


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
