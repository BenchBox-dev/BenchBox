from __future__ import annotations

import logging

import pytest

from benchbox.core.tpcds.maintenance_operations import MaintenanceOperations, MaintenanceOperationType
from benchbox.core.tpcds.schema import get_create_all_tables_sql

pytestmark = [pytest.mark.unit, pytest.mark.fast]

CHANNELS = {
    "store": {
        "operation": MaintenanceOperationType.INSERT_STORE_RETURNS,
        "sales": ("STORE_SALES", "SS_ITEM_SK", "SS_TICKET_NUMBER", "SS_QUANTITY"),
        "returns": ("STORE_RETURNS", "SR_ITEM_SK", "SR_TICKET_NUMBER"),
    },
    "catalog": {
        "operation": MaintenanceOperationType.INSERT_CATALOG_RETURNS,
        "sales": ("CATALOG_SALES", "CS_ITEM_SK", "CS_ORDER_NUMBER", "CS_QUANTITY"),
        "returns": ("CATALOG_RETURNS", "CR_ITEM_SK", "CR_ORDER_NUMBER"),
    },
    "web": {
        "operation": MaintenanceOperationType.INSERT_WEB_RETURNS,
        "sales": ("WEB_SALES", "WS_ITEM_SK", "WS_ORDER_NUMBER", "WS_QUANTITY"),
        "returns": ("WEB_RETURNS", "WR_ITEM_SK", "WR_ORDER_NUMBER"),
    },
}

SALES_LINES = 40
RETURNED_LINES = 30
NULL_QUANTITY_LINES = 3


class _Connection:
    def __init__(self, connection):
        self._connection = connection

    def execute(self, sql, params=None):
        if params is None:
            return self._connection.execute(sql)
        return self._connection.execute(sql, params)


@pytest.fixture
def maintenance_connection():
    duckdb = pytest.importorskip("duckdb")
    raw = duckdb.connect()
    raw.execute(get_create_all_tables_sql(enable_primary_keys=True, enable_foreign_keys=False))
    yield _Connection(raw)
    raw.close()


@pytest.fixture(autouse=True)
def _quiet_logs():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


def _seed_sales_and_returns(connection, channel, null_quantity_lines=NULL_QUANTITY_LINES):
    sales_table, sales_item, sales_number, sales_quantity = channel["sales"]
    returns_table, returns_item, returns_number = channel["returns"]
    for line in range(1, SALES_LINES + 1):
        quantity = None if line > SALES_LINES - null_quantity_lines else 5
        connection.execute(
            f"INSERT INTO {sales_table} ({sales_item}, {sales_number}, {sales_quantity}) VALUES (?, ?, ?)",
            (line, 1000 + line, quantity),
        )
    for line in range(1, RETURNED_LINES + 1):
        connection.execute(
            f"INSERT INTO {returns_table} ({returns_item}, {returns_number}) VALUES (?, ?)",
            (line, 1000 + line),
        )


def _returned_keys(connection, channel):
    _, returns_item, returns_number = channel["returns"]
    rows = connection.execute(f"SELECT {returns_item}, {returns_number} FROM {channel['returns'][0]}").fetchall()
    return sorted(rows)


def _operations(connection, seed):
    operations = MaintenanceOperations()
    operations.random_gen.seed(seed)
    operations.initialize(connection, None, None)
    operations.random_gen.seed(seed)
    return operations


@pytest.mark.parametrize("channel_name", sorted(CHANNELS))
@pytest.mark.parametrize("seed", range(5))
def test_return_insert_only_references_sales_without_a_return(maintenance_connection, channel_name, seed):
    channel = CHANNELS[channel_name]
    _seed_sales_and_returns(maintenance_connection, channel)
    operations = _operations(maintenance_connection, seed)

    result = operations.execute_operation(maintenance_connection, channel["operation"], 7)

    assert result.success, result.error_message
    assert result.rows_affected == 7
    keys = _returned_keys(maintenance_connection, channel)
    assert len(keys) == RETURNED_LINES + 7
    assert len(set(keys)) == len(keys)
    new_keys = {key for key in keys if key[0] > RETURNED_LINES}
    assert len(new_keys) == 7
    assert all(item <= SALES_LINES - NULL_QUANTITY_LINES for item, _ in new_keys)
    assert all(number == 1000 + item for item, number in new_keys)


@pytest.mark.parametrize("channel_name", sorted(CHANNELS))
def test_return_insert_stops_at_the_sales_that_have_no_return(maintenance_connection, channel_name):
    channel = CHANNELS[channel_name]
    _seed_sales_and_returns(maintenance_connection, channel)
    operations = _operations(maintenance_connection, 0)
    available = SALES_LINES - RETURNED_LINES - NULL_QUANTITY_LINES

    first = operations.execute_operation(maintenance_connection, channel["operation"], 50)
    second = operations.execute_operation(maintenance_connection, channel["operation"], 50)

    assert first.success, first.error_message
    assert first.rows_affected == available
    assert second.success, second.error_message
    assert second.rows_affected == 0
    keys = _returned_keys(maintenance_connection, channel)
    assert len(set(keys)) == len(keys) == RETURNED_LINES + available


@pytest.mark.parametrize("channel_name", sorted(CHANNELS))
@pytest.mark.parametrize("seed", range(5))
def test_return_insert_does_not_collide_with_existing_return_keys(maintenance_connection, channel_name, seed):
    channel = CHANNELS[channel_name]
    _seed_sales_and_returns(maintenance_connection, channel, null_quantity_lines=0)
    operations = _operations(maintenance_connection, seed)

    result = operations.execute_operation(maintenance_connection, channel["operation"], 10)

    assert result.success, result.error_message
    assert result.rows_affected == 10
    assert len(_returned_keys(maintenance_connection, channel)) == RETURNED_LINES + 10
