"""Unit tests for Firebolt DDL optimizer branch coverage.

Pins _optimize_table_definition transforms not covered elsewhere: bare
VARCHAR and CHAR(n) to TEXT, DECIMAL precision preservation as NUMERIC,
non-CREATE passthrough, and double-comma cleanup after constraint removal.
Existing tests pin VARCHAR(n), PRIMARY KEY and FOREIGN KEY removal.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.platforms.firebolt import FireboltAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _adapter():
    try:
        return FireboltAdapter(deployment_mode="core")
    except ImportError:
        pytest.skip("Firebolt SDK not installed")


class TestOptimizeTableDefinitionBranches:
    def test_bare_varchar_becomes_text(self) -> None:
        out = _adapter()._optimize_table_definition("CREATE TABLE t (c VARCHAR)")
        assert "VARCHAR" not in out.upper()
        assert "TEXT" in out

    def test_char_with_length_becomes_text(self) -> None:
        out = _adapter()._optimize_table_definition("CREATE TABLE t (c CHAR(10))")
        assert "CHAR(10)" not in out
        assert "TEXT" in out

    def test_decimal_precision_preserved_as_numeric(self) -> None:
        out = _adapter()._optimize_table_definition("CREATE TABLE t (price DECIMAL(15, 2))")
        assert "DECIMAL" not in out.upper()
        assert "NUMERIC(15, 2)" in out

    def test_non_create_statement_passes_through(self) -> None:
        stmt = "INSERT INTO t VALUES (1)"
        assert _adapter()._optimize_table_definition(stmt) == stmt

    def test_double_comma_cleaned_after_constraint_removal(self) -> None:
        out = _adapter()._optimize_table_definition("CREATE TABLE t (a INT, PRIMARY KEY (a), b TEXT)")
        assert ",," not in out
        assert "PRIMARY KEY" not in out.upper()
        assert "b TEXT" in out

    def test_trailing_comma_before_paren_cleaned(self) -> None:
        out = _adapter()._optimize_table_definition("CREATE TABLE t (a INT, b TEXT, PRIMARY KEY (a))")
        assert ",)" not in out
        assert out.rstrip().endswith(")")

    def test_tpch_lineitem_ddl_shape(self) -> None:
        out = _adapter()._optimize_table_definition(
            "CREATE TABLE LineItem (l_orderkey BIGINT, l_comment VARCHAR(44), "
            "l_extendedprice DECIMAL(15, 2), PRIMARY KEY (l_orderkey))"
        )
        assert "TEXT" in out
        assert "NUMERIC(15, 2)" in out
        assert "PRIMARY KEY" not in out.upper()
