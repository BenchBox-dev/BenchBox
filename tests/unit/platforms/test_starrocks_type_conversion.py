"""Unit tests for StarRocks workload type conversion and DDL assembly.

Pins _convert_types mappings (integer promotion, TIMESTAMP case-sensitivity,
bare VARCHAR sizing, ClickBench uint16 promotion) and _extract_first_column
extraction/validation, plus the composed _optimize_table_definition baseline:
DUPLICATE KEY plus engine-mandatory DISTRIBUTED BY HASH on the first column.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.platforms.starrocks.workload import StarRocksWorkloadMixin

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.fixture
def mixin() -> StarRocksWorkloadMixin:
    return StarRocksWorkloadMixin.__new__(StarRocksWorkloadMixin)


class TestConvertTypes:
    def test_integer_becomes_int(self, mixin) -> None:
        assert mixin._convert_types("CREATE TABLE t (a INTEGER)") == "CREATE TABLE t (a INT)"

    def test_smallint_promoted_for_clickbench_range(self, mixin) -> None:
        assert mixin._convert_types("CREATE TABLE t (a SMALLINT)") == "CREATE TABLE t (a INT)"

    def test_uppercase_timestamp_becomes_datetime(self, mixin) -> None:
        out = mixin._convert_types("CREATE TABLE t (ts TIMESTAMP)")
        assert "DATETIME" in out
        assert "TIMESTAMP" not in out

    def test_lowercase_timestamp_column_name_preserved(self, mixin) -> None:
        out = mixin._convert_types("CREATE TABLE t (timestamp BIGINT)")
        assert "timestamp BIGINT" in out
        assert "DATETIME" not in out

    def test_lowercase_type_in_type_position_normalized(self, mixin) -> None:
        out = mixin._convert_types("CREATE TABLE t (ts timestamp)")
        assert "ts DATETIME" in out
        assert "timestamp" not in out

    def test_bare_varchar_gets_size_but_sized_varchar_kept(self, mixin) -> None:
        assert "VARCHAR(65533)" in mixin._convert_types("CREATE TABLE t (c VARCHAR)")
        assert "VARCHAR(50)" in mixin._convert_types("CREATE TABLE t (c VARCHAR(50))")

    def test_string_and_text_become_sized_varchar(self, mixin) -> None:
        assert "VARCHAR(65533)" in mixin._convert_types("CREATE TABLE t (c STRING)")
        assert "VARCHAR(65533)" in mixin._convert_types("CREATE TABLE t (c TEXT)")


class TestExtractFirstColumn:
    def test_extracts_first_column(self, mixin) -> None:
        assert mixin._extract_first_column("CREATE TABLE t (l_orderkey BIGINT, x INT)") == "l_orderkey"

    def test_extracts_backtick_quoted_first_column(self, mixin) -> None:
        assert mixin._extract_first_column("CREATE TABLE t (`l_orderkey` BIGINT)") == "l_orderkey"

    def test_returns_none_without_paren(self, mixin) -> None:
        assert mixin._extract_first_column("CREATE TABLE t") is None


class TestOptimizeBaseline:
    def test_baseline_adds_duplicate_key_and_distribution(self, mixin) -> None:
        out = mixin._optimize_table_definition("CREATE TABLE lineitem (l_orderkey BIGINT, l_partkey BIGINT);")
        assert "DUPLICATE KEY(`l_orderkey`)" in out
        assert "DISTRIBUTED BY HASH(`l_orderkey`) BUCKETS 8" in out

    def test_non_create_passes_through(self, mixin) -> None:
        stmt = "INSERT INTO t VALUES (1)"
        assert mixin._optimize_table_definition(stmt) == stmt

    def test_autoincrement_removed(self, mixin) -> None:
        out = mixin._optimize_table_definition("CREATE TABLE t (id BIGINT AUTOINCREMENT, x INT);")
        assert "AUTOINCREMENT" not in out.upper()
