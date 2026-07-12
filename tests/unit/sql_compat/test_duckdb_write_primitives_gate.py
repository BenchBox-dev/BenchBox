# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""Unit tests for the DuckDB write_primitives MERGE INTO token gate (audit N6)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from benchbox.sql_compat.rules.execution_filter.duckdb_write_primitives import (
    duckdb_write_primitive_skip_reason,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _op(sql: str):
    return SimpleNamespace(id="op", write_sql=sql)


def test_real_merge_into_is_skipped():
    assert (
        duckdb_write_primitive_skip_reason(_op("MERGE INTO t USING s ON t.k=s.k WHEN MATCHED THEN DELETE")) is not None
    )


class TestNoFalsePositives:
    """A MERGE INTO that only appears in a comment or string must NOT skip."""

    def test_line_comment(self):
        assert duckdb_write_primitive_skip_reason(_op("-- rewrite as MERGE INTO t later\nUPDATE t SET a = 1")) is None

    def test_block_comment(self):
        assert duckdb_write_primitive_skip_reason(_op("/* MERGE INTO t */ UPDATE t SET a = 1")) is None

    def test_string_literal(self):
        assert duckdb_write_primitive_skip_reason(_op("UPDATE t SET note = 'MERGE INTO staging'")) is None


class TestNoFalseNegatives:
    """Whitespace / CTE variants DuckDB still rejects must skip."""

    def test_double_space(self):
        assert (
            duckdb_write_primitive_skip_reason(_op("MERGE  INTO t USING s ON true WHEN MATCHED THEN DELETE"))
            is not None
        )

    def test_newline_between_tokens(self):
        assert (
            duckdb_write_primitive_skip_reason(_op("MERGE\nINTO t USING s ON true WHEN MATCHED THEN DELETE"))
            is not None
        )

    def test_cte_prefixed(self):
        sql = "WITH src AS (SELECT 1) MERGE\n  INTO t USING src ON true WHEN MATCHED THEN DELETE"
        assert duckdb_write_primitive_skip_reason(_op(sql)) is not None

    def test_lowercase(self):
        assert (
            duckdb_write_primitive_skip_reason(_op("merge into t using s on true when matched then delete")) is not None
        )


class TestEffectiveSqlOverride:
    """The gate judges the effective SQL when supplied, not the catalog default."""

    def test_override_removing_merge_runs(self):
        op = _op("MERGE INTO t USING s ON t.k=s.k WHEN MATCHED THEN DELETE")
        # A per-platform override that rewrites away MERGE INTO must not be skipped.
        assert (
            duckdb_write_primitive_skip_reason(op, effective_sql="DELETE FROM t WHERE k IN (SELECT k FROM s)") is None
        )

    def test_override_introducing_merge_skips(self):
        op = _op("UPDATE t SET a = 1")
        assert (
            duckdb_write_primitive_skip_reason(
                op, effective_sql="MERGE INTO t USING s ON true WHEN MATCHED THEN DELETE"
            )
            is not None
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
