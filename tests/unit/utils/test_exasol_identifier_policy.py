"""Exasol translates with unquoted identifiers while reserved words stay quoted.

Exasol folds unquoted identifiers to UPPERCASE. Quoting every identifier by
default would create lower-case quoted names that adapter-internal unquoted
SQL cannot find, so the ``exasol`` target joins the no-identify set. Reserved
words stay safe because sqlglot's ``ExasolGenerator.RESERVED_KEYWORDS`` still
quotes them. These tests pin that contract on both translation paths, and pin
that no other target's output changes.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import logging

import pytest

from benchbox.platforms.base.dialect_translation import DialectTranslationMixin
from benchbox.utils.dialect_utils import (
    NO_IDENTIFY_DIALECTS,
    normalize_dialect_for_sqlglot,
    translate_sql_query,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _ExasolHost(DialectTranslationMixin):
    _dialect = "exasol"
    logger = logging.getLogger("test-exasol-identify")


class TestExasolIdentifierPolicy:
    """Unquoted identifiers, quoted reserved words, unchanged passthrough."""

    def test_exasol_is_a_no_identify_target(self):
        """The policy constant carries exasol alongside the existing members."""
        assert frozenset({"clickhouse", "postgres", "snowflake", "exasol"}) == NO_IDENTIFY_DIALECTS

    def test_normalize_passes_exasol_through(self):
        """sqlglot ships the dialect, so no fallback mapping applies."""
        assert normalize_dialect_for_sqlglot("exasol") == "exasol"
        assert normalize_dialect_for_sqlglot("EXASOL") == "exasol"

    def test_tpch_ddl_emits_unquoted_identifiers(self):
        """TPC-H DDL columns and keys come out unquoted."""
        ddl = (
            "CREATE TABLE lineitem (l_orderkey INTEGER NOT NULL, l_partkey INTEGER NOT NULL, PRIMARY KEY (l_orderkey))"
        )
        result = translate_sql_query(ddl, target_dialect="exasol", source_dialect="standard")
        assert '"l_orderkey"' not in result
        assert '"lineitem"' not in result
        assert "l_orderkey" in result

    def test_tpch_query_emits_unquoted_identifiers(self):
        """A TPC-H query keeps plain identifiers."""
        result = translate_sql_query(
            "SELECT l_orderkey, l_partkey FROM lineitem WHERE l_orderkey > 10",
            target_dialect="exasol",
        )
        assert '"' not in result
        assert "l_orderkey" in result

    def test_tpcds_reserved_aliases_stay_quoted(self):
        """TPC-DS reserved aliases are quoted despite identify=False."""
        result = translate_sql_query(
            "SELECT d_year AS year, c_id AS catalog FROM dates",
            target_dialect="exasol",
        )
        assert '"year"' in result
        assert '"catalog"' in result

    def test_reserved_ddl_column_stays_quoted(self):
        """A synthetic DDL column named after a reserved word is quoted."""
        result = translate_sql_query(
            "CREATE TABLE t (year INTEGER NOT NULL, id INTEGER NOT NULL)",
            target_dialect="exasol",
            source_dialect="standard",
        )
        assert '"year"' in result
        assert '"id"' not in result

    def test_platforms_path_matches_utils_path(self):
        """The adapter mixin path honors the same policy."""
        host = _ExasolHost()
        assert '"' not in host.translate_sql("SELECT l_orderkey FROM lineitem", source_dialect="postgres")
        assert '"year"' in host.translate_sql("SELECT d_year AS year FROM dates", source_dialect="postgres")

    @pytest.mark.parametrize("target", ["duckdb", "postgres", "snowflake", "clickhouse", "sqlite", "trino"])
    def test_other_targets_are_unchanged(self, target):
        """G1: only the exasol target may change behavior."""
        query = "SELECT l_orderkey FROM lineitem"
        before = translate_sql_query(query, target_dialect=target)
        assert before
        assert translate_sql_query(query, target_dialect=target) == before
