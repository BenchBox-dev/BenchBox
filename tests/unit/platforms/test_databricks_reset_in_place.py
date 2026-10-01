"""Databricks reloads reset tables in place instead of dropping the schema."""

from unittest.mock import MagicMock, patch

import pytest

from benchbox.platforms.databricks import DatabricksAdapter

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.fixture
def adapter():
    with patch("benchbox.platforms.databricks.adapter.check_platform_dependencies", return_value=(True, [])):
        return DatabricksAdapter(
            server_hostname="h.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/x",
            access_token="t",
            catalog="cat",
            schema="sch",
        )


def _connection(tables, fail_on=None):
    cursor = MagicMock()
    executed = []

    def execute(sql):
        executed.append(sql)
        if fail_on and fail_on in sql:
            raise RuntimeError("boom")

    cursor.execute.side_effect = execute
    cursor.fetchall.return_value = tables
    connection = MagicMock()
    connection.cursor.return_value = cursor
    return connection, executed


def test_reset_truncates_every_table_and_never_drops(adapter):
    connection, executed = _connection([("sch", "orders", False), ("sch", "lineitem", False), ("sch", "tmp", True)])
    with patch.object(adapter, "_create_admin_connection", return_value=connection):
        assert adapter.reset_database_in_place(catalog="cat", schema="sch") is True

    assert executed == [
        "SHOW TABLES IN cat.sch",
        "TRUNCATE TABLE cat.sch.`orders`",
        "TRUNCATE TABLE cat.sch.`lineitem`",
    ]
    connection.close.assert_called_once()


def test_reset_declines_when_a_table_cannot_be_truncated(adapter):
    connection, executed = _connection([("sch", "v_orders", False)], fail_on="TRUNCATE")
    with patch.object(adapter, "_create_admin_connection", return_value=connection):
        assert adapter.reset_database_in_place(catalog="cat", schema="sch") is False

    assert not any(sql.startswith("DROP") for sql in executed)
