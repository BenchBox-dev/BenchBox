from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from benchbox.core.validation.data import (
    DataValidator,
    ValidationStatus,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def make_validator(platform_name: str = "duckdb") -> DataValidator:
    adapter = SimpleNamespace(platform_name=platform_name, config={})
    return DataValidator(adapter, tolerance_percent=0.1, absolute_tolerance=100)


def test_quote_identifier_various_platforms():
    dv = make_validator("bigquery")
    assert dv._quote_identifier("t", "bigquery") == "`t`"
    assert dv._quote_identifier("t", "mysql") == "`t`"
    assert dv._quote_identifier("t", "postgresql") == '"t"'
    assert dv._quote_identifier("t", "snowflake") == '"t"'
    assert dv._quote_identifier("t", "clickhouse") == "t"
    assert dv._quote_identifier("t", "duckdb") == "t"


def test_tolerance_small_tables_uses_absolute_threshold():
    dv = make_validator()
    # absolute_tolerance = 100, threshold for small tables = 1000
    # difference within tolerance
    assert not dv._is_tolerance_exceeded(500, 590, 90, 18.0)
    # difference beyond tolerance
    assert dv._is_tolerance_exceeded(500, 701, 201, 40.2)


def test_tolerance_large_tables_uses_percentage():
    dv = make_validator()
    # For large table, use percentage (0.1%)
    # 10/20000 = 0.05% -> within tolerance
    assert not dv._is_tolerance_exceeded(20000, 20010, 10, 0.05)
    # 40/20000 = 0.2% -> exceeds tolerance
    assert dv._is_tolerance_exceeded(20000, 20040, 40, 0.2)


def test_count_query_platform_specific():
    dv = make_validator()
    assert dv._get_count_query("t", "clickhouse") == "SELECT COUNT(*) FROM t"
    assert dv._get_count_query("t", "duckdb") == "SELECT COUNT(*) FROM t"
    # default path
    assert dv._get_count_query("t", "postgresql") == 'SELECT COUNT(*) FROM "t"'


def test_get_actual_row_counts_happy_path_and_approximate():
    class FakeCursor:
        def __init__(self, value=5):
            self.value = value
            self.executed = []

        def execute(self, sql):
            self.executed.append(sql)

        def fetchone(self):
            return (self.value,)

    class FakeConn:
        def __init__(self, value=5):
            self.cur = FakeCursor(value)

        def cursor(self):
            return self.cur

    class FakeAdapter:
        def __init__(self, platform="clickhouse"):
            self.platform_name = platform
            self.platform_config = {}

        def create_connection(self, **_):
            return FakeConn(12345678)

        def close_connection(self, c):
            return None

    dv = DataValidator(FakeAdapter("clickhouse"))
    # Force approximate path by lowering threshold
    dv.large_table_threshold = 0
    counts = dv.get_actual_row_counts(FakeConn(10), ["tbl"])
    assert counts["tbl"] >= 0


def test_create_discrepancy_status_assignment():
    dv = make_validator()
    # Exact match -> PASSED
    d0 = dv._create_discrepancy("t", 1000, 1000)
    assert d0.status == ValidationStatus.PASSED
    assert not d0.tolerance_exceeded

    # Within absolute tolerance -> WARNING
    d1 = dv._create_discrepancy("t", 900, 980)  # diff = 80
    assert d1.status == ValidationStatus.WARNING
    assert not d1.tolerance_exceeded

    # Beyond tolerance -> FAILED
    d2 = dv._create_discrepancy("t", 900, 1105)  # diff = 205
    assert d2.status == ValidationStatus.FAILED
    assert d2.tolerance_exceeded

    # expected_count=0 and actual>0 -> percentage inf path
    d3 = dv._create_discrepancy("t", 0, 5)
    assert d3.tolerance_exceeded is False
    assert d3.status == ValidationStatus.WARNING


def test_compare_row_counts_includes_missing_tables_as_failed():
    dv = make_validator()
    discrepancies = dv.compare_row_counts({"a": 10, "b": 20}, {"a": 10, "c": 5})
    # Two discrepancies expected: a (match), b (missing)
    assert len(discrepancies) == 2
    # Find entries
    by_tbl = {d.table_name: d for d in discrepancies}
    assert by_tbl["a"].status in (ValidationStatus.PASSED, ValidationStatus.WARNING)
    assert by_tbl["b"].status == ValidationStatus.FAILED


def test_get_table_exists_status_and_integrity_checks():
    # Fake adapter/connection/cursor
    class FakeCursor:
        def __init__(self, table_exists: bool = True, retval=(1,)):
            self.table_exists = table_exists
            self.retval = retval
            self.executed = []

        def execute(self, sql):
            self.executed.append(sql)
            # Simulate raise for non-existent tables
            if "MISSING_TABLE" in sql:
                raise Exception("no such table")

        def fetchone(self):
            return self.retval

    class FakeConn:
        def __init__(self, retval=(1,)):
            self.cursor_obj = FakeCursor(retval=retval)

        def cursor(self):
            return self.cursor_obj

    class FakeAdapter:
        def __init__(self):
            self.platform_name = "duckdb"
            self.platform_config = {}
            self._conns = []

        def create_connection(self, **_):
            c = FakeConn()
            self._conns.append(c)
            return c

        def close_connection(self, _c):
            return None

    adapter = FakeAdapter()
    dv = DataValidator(adapter)

    status = dv.get_table_exists_status(["EXISTS_TABLE", "MISSING_TABLE"])
    assert status["EXISTS_TABLE"] is True
    assert status["MISSING_TABLE"] is False

    # Integrity checks: one True, one False, one None result
    class FakeConn2(FakeConn):
        def __init__(self):
            self.calls = []

            # single persistent cursor instance
            class C:
                def __init__(self, outer):
                    self.outer = outer
                    self.last_sql = ""

                def execute(self, sql):
                    self.outer.calls.append(sql)
                    self.last_sql = sql

                def fetchone(self):
                    sql = self.last_sql.lower()
                    if "select 1" in sql:
                        return (1,)
                    if "select 0" in sql:
                        return (0,)
                    return None

            self._cursor = C(self)

        def cursor(self):
            return self._cursor

    class FakeAdapter2(FakeAdapter):
        def create_connection(self, **_):
            c = FakeConn2()
            self._conns.append(c)
            return c

    dv2 = DataValidator(FakeAdapter2())
    res = dv2.validate_data_integrity({"ok": "select 1", "bad": "select 0", "none": "select"})
    assert res.passed_tables == 1
    assert res.failed_tables >= 1


def test_try_approximate_count_variants():
    class C:
        def __init__(self, value):
            self.value = value

        def cursor(self):
            return self

        def execute(self, _):
            return None

        def fetchone(self):
            return (self.value,)

    dv = make_validator()
    for platform in [
        "postgresql",
        "mysql",
        "snowflake",
        "bigquery",
        "redshift",
        "clickhouse",
    ]:
        val = dv._try_approximate_count(C(42), "tbl", platform)
        assert val in (42, None)


def test_validate_row_counts_uses_monotonic_elapsed_time():
    class FakeCursor:
        def execute(self, _):
            return None

        def fetchone(self):
            return (10,)

    class FakeConn:
        def cursor(self):
            return FakeCursor()

    class FakeAdapter:
        platform_name = "duckdb"
        platform_config = {}

        def create_connection(self, **_):
            return FakeConn()

        def close_connection(self, _):
            return None

    dv = DataValidator(FakeAdapter())
    mock_clock = Mock(side_effect=[100.0, 101.75])
    with (
        patch("benchbox.core.validation.data.mono_time", mock_clock),
        patch("benchbox.utils.clock.mono_time", mock_clock),
    ):
        result = dv.validate_row_counts({"orders": 10})

    assert result.execution_time == pytest.approx(1.75)
