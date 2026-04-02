from enum import Enum

import pytest

from benchbox.core.tpcds.maintenance_operations import (
    MaintenanceOperations,
    MaintenanceOperationType,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class FakeCursor:
    """Mock cursor that supports fetchall() for returns operations."""

    def __init__(self, sales_records=None, rowcount=0):
        self.sales_records = sales_records or []
        self.rowcount = rowcount

    def fetchall(self):
        """Return mock sales records for returns operations."""
        return self.sales_records

    def fetchone(self):
        """Return mock single row for MIN/MAX queries."""
        return (1, 100) if self.sales_records else None


class FakeConn:
    def __init__(self):
        self.executed = []
        # Mock sales records for store_returns (8 fields)
        self.store_sales_records = [
            (12345, 1, 1, 1, 1, 1, 1, 10),  # ticket_num, item_sk, cust_sk, cdemo, hdemo, addr, store, qty
            (12346, 2, 2, 2, 2, 2, 2, 5),
            (12347, 3, 3, 3, 3, 3, 3, 8),
        ]
        # Mock sales records for catalog_returns (11 fields)
        self.catalog_sales_records = [
            (
                12345,
                1,
                1,
                1,
                1,
                1,
                1,
                1,
                1,
                1,
                10,
            ),  # order_num, item, cust, cdemo, hdemo, addr, call_ctr, cat_page, ship_mode, warehouse, qty
            (12346, 2, 2, 2, 2, 2, 2, 2, 2, 2, 5),
            (12347, 3, 3, 3, 3, 3, 3, 3, 3, 3, 8),
        ]
        # Mock sales records for web_returns (8 fields)
        self.web_sales_records = [
            (12345, 1, 1, 1, 1, 1, 1, 10),  # order_num, item, cust, cdemo, hdemo, addr, web_page, qty
            (12346, 2, 2, 2, 2, 2, 2, 5),
            (12347, 3, 3, 3, 3, 3, 3, 8),
        ]

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        # If query is for dimension ranges (MIN/MAX), return range cursor
        if "MIN(" in sql.upper() and "MAX(" in sql.upper():
            return FakeCursor(sales_records=None, rowcount=0)
        # Return appropriate sales records based on table being queried
        elif "FROM STORE_SALES" in sql.upper():
            return FakeCursor(sales_records=self.store_sales_records[:3], rowcount=3)
        elif "FROM CATALOG_SALES" in sql.upper():
            return FakeCursor(sales_records=self.catalog_sales_records[:3], rowcount=3)
        elif "FROM WEB_SALES" in sql.upper():
            return FakeCursor(sales_records=self.web_sales_records[:3], rowcount=3)
        # For INSERT/UPDATE/DELETE, return empty cursor
        else:
            return FakeCursor(sales_records=[], rowcount=1)


def test_execute_operation_insert_store_sales_success():
    ops = MaintenanceOperations()
    conn = FakeConn()

    result = ops.execute_operation(conn, MaintenanceOperationType.INSERT_STORE_SALES, estimated_rows=5)

    assert result.success is True
    assert result.rows_affected == 5
    # ensure some SQL was executed
    assert len(conn.executed) >= 1


def test_execute_operation_unsupported_returns_failure():
    # Create an enum not in the handlers mapping
    Unknown = Enum("Unknown", "FOO")
    ops = MaintenanceOperations()
    conn = FakeConn()

    result = ops.execute_operation(conn, Unknown.FOO, estimated_rows=1)

    assert result.success is False
    assert "Unsupported operation type" in (result.error_message or "")


def test_execute_multiple_operations_succeed_quickly():
    ops = MaintenanceOperations()
    conn = FakeConn()

    op_types = [
        MaintenanceOperationType.INSERT_CATALOG_SALES,
        MaintenanceOperationType.INSERT_WEB_SALES,
        MaintenanceOperationType.INSERT_STORE_RETURNS,
        MaintenanceOperationType.INSERT_CATALOG_RETURNS,
        MaintenanceOperationType.INSERT_WEB_RETURNS,
        MaintenanceOperationType.UPDATE_CUSTOMER,
        MaintenanceOperationType.UPDATE_ITEM,
        MaintenanceOperationType.UPDATE_INVENTORY,
        MaintenanceOperationType.DELETE_OLD_SALES,
        MaintenanceOperationType.DELETE_OLD_RETURNS,
        MaintenanceOperationType.BULK_LOAD_SALES,
        MaintenanceOperationType.BULK_UPDATE_INVENTORY,
    ]

    for op in op_types:
        res = ops.execute_operation(conn, op, estimated_rows=3)
        assert res.success is True
        assert res.rows_affected >= 0


def test_delete_queries_rowcount_branch():
    class FakeConnWithRowcount(FakeConn):
        class Result:
            def __init__(self, n):
                self.rowcount = n

        def execute(self, sql, params=None):
            self.executed.append((sql, params))
            return self.Result(2)

    ops = MaintenanceOperations()
    conn = FakeConnWithRowcount()

    # exercise rowcount path in deletes
    deleted_sales = ops._delete_old_sales(conn, estimated_rows=9)
    deleted_returns = ops._delete_old_returns(conn, estimated_rows=9)
    assert deleted_sales > 0
    assert deleted_returns > 0


def test_generate_catalog_returns_from_sale_preserves_sale_keys():
    ops = MaintenanceOperations()
    ops.random_gen.seed(7)
    ops._get_random_key = lambda _name: 42

    sale_record = (1001, 2002, 3003, 4004, 5005, 6006, 7007, 8008, 9009, 10010, 12)

    result = ops._generate_catalog_returns_from_sale(sale_record)

    assert len(result) == 27
    assert result[0] == 42
    assert result[1] == 42
    assert result[2:15] == (
        2002,
        3003,
        4004,
        5005,
        6006,
        3003,
        4004,
        5005,
        6006,
        7007,
        8008,
        9009,
        10010,
    )
    assert result[16] == 1001
    assert 1 <= result[17] <= 12


def test_generate_web_returns_from_sale_preserves_sale_keys():
    ops = MaintenanceOperations()
    ops.random_gen.seed(11)
    ops._get_random_key = lambda _name: 24

    sale_record = (1111, 2222, 3333, 4444, 5555, 6666, 7777, 9)

    result = ops._generate_web_returns_from_sale(sale_record)

    assert len(result) == 24
    assert result[0] == 24
    assert result[1] == 24
    assert result[2:12] == (
        2222,
        3333,
        4444,
        5555,
        6666,
        3333,
        4444,
        5555,
        6666,
        7777,
    )
    assert result[13] == 1111
    assert 1 <= result[14] <= 9
