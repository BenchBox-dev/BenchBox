"""Tests for idempotent Snowflake table loads (skip COPY when data present).

Regression coverage: reruns against an existing database must not append a
second copy of every table. _load_table_from_stage returns the existing row
count without PUT/COPY when the target already holds rows.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture(autouse=True)
def mock_sf_deps():
    with patch("benchbox.platforms.snowflake.check_platform_dependencies", return_value=(True, [])):
        yield


def _make_adapter():
    from benchbox.platforms.snowflake import SnowflakeAdapter

    with patch("benchbox.platforms.snowflake.snowflake"):
        return SnowflakeAdapter(
            account="test_account",
            username="test_user",
            password="test_pass",
            schema="PUBLIC",
            database="BENCHBOX",
        )


def _make_cursor(count_result=None, count_raises=False):
    cursor = MagicMock()
    if count_raises:
        cursor.execute.side_effect = Exception("table does not exist")
        cursor.fetchone.return_value = None
    else:
        cursor.execute.return_value = None
        cursor.fetchone.return_value = (count_result,)
    cursor.fetchall.return_value = [("hits.csv.gz", "LOADED", "", 100, "", "")]
    return cursor


class TestCountExistingRows:
    def test_returns_count(self):
        adapter = _make_adapter()
        assert adapter._count_existing_rows(_make_cursor(42), "HITS", "hits") == 42

    def test_returns_zero_on_missing_table(self):
        adapter = _make_adapter()
        assert adapter._count_existing_rows(_make_cursor(count_raises=True), "HITS", "hits") == 0


class TestLoadTableFromStageIdempotent:
    def test_skips_put_and_copy_when_rows_exist(self):
        adapter = _make_adapter()
        cursor = _make_cursor(100000)
        rows = adapter._load_table_from_stage(cursor, "hits", "HITS", [Path("/tmp/hits.csv.gz")])
        assert rows == 100000
        executed = [str(call.args[0]) for call in cursor.execute.call_args_list]
        assert not any("PUT " in stmt for stmt in executed), executed
        assert not any("COPY INTO" in stmt for stmt in executed), executed

    def test_loads_when_table_empty(self):
        adapter = _make_adapter()
        cursor = _make_cursor(0)
        cursor.fetchone.side_effect = [(0,), (100000,)]
        rows = adapter._load_table_from_stage(cursor, "hits", "HITS", [Path("/tmp/hits.csv.gz")])
        assert rows == 100000
        executed = [str(call.args[0]) for call in cursor.execute.call_args_list]
        assert any("PUT " in stmt for stmt in executed), executed
        assert any("COPY INTO" in stmt for stmt in executed), executed
