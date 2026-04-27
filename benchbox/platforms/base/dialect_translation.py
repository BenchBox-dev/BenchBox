"""SQL dialect translation helpers for PlatformAdapter.

Extracted from `benchbox.platforms.base.adapter` per the refactor map in
`docs/development/adapter-refactor-map.md` (Slice 1). Keeps `dialect`,
`translate_sql`, and `get_tpc_base_dialect` grouped as a cohesive cluster
so the adapter facade can delegate without carrying dialect logic inline.

Consumers continue to call `PlatformAdapter.translate_sql(...)` etc.; the
mixin only changes where the implementations live.
"""

from __future__ import annotations

import logging


class DialectTranslationMixin:
    """Mixin providing SQL dialect negotiation for `PlatformAdapter`.

    Expects the host class to supply `self._dialect` (str | None) and
    `self.logger` (`logging.Logger`). Both are initialized by
    `PlatformAdapter.__init__`.
    """

    _dialect: str | None
    logger: logging.Logger

    @property
    def dialect(self) -> str | None:
        """Return the SQL dialect for this platform (for sqlglot translation)."""
        return self._dialect

    def translate_sql(self, sql: str, source_dialect: str = "duckdb") -> str:
        """Translate SQL from source dialect to platform dialect using sqlglot.

        Delegates to the centralized dialect_utils pipeline, gaining dialect
        normalization, identifier quoting policy, and platform-specific
        post-fixes (DuckDB GROUP BY ALL, SQLite syntax rewrites). Handles
        multi-statement schema SQL that translate_sql_query() does not.

        Args:
            sql: SQL query or schema block (may contain multiple statements)
            source_dialect: Source SQL dialect (default: duckdb)

        Returns:
            Translated SQL string, preserving multi-statement structure.
        """
        if not self.dialect or self.dialect == source_dialect:
            return sql

        from benchbox.utils.dialect_utils import (
            _fix_sqlite_unsupported_syntax,
            _query_has_group_or_order_by_all,
            _restore_group_order_by_all_keyword,
            normalize_dialect_for_sqlglot,
        )

        try:
            import sqlglot

            src = normalize_dialect_for_sqlglot(source_dialect)
            tgt = normalize_dialect_for_sqlglot(self.dialect)
            should_identify = tgt not in ("clickhouse", "postgres")

            translated_statements = sqlglot.transpile(sql, read=src, write=tgt, identify=should_identify)

            has_all = _query_has_group_or_order_by_all(sql)
            fixed = []
            for stmt in translated_statements:
                if tgt == "duckdb" and has_all:
                    stmt = _restore_group_order_by_all_keyword(stmt)
                elif tgt == "sqlite":
                    stmt = _fix_sqlite_unsupported_syntax(stmt)
                fixed.append(stmt)

            return ";\n\n".join(fixed) + ";"

        except ImportError:
            self.logger.warning("sqlglot not available for SQL translation")
            return sql
        except Exception as e:
            self.logger.warning(f"Failed to translate SQL: {e}")
            return sql

    def get_tpc_base_dialect(self, benchmark_name: str) -> str:
        """Return the base dialect for TPC query generation (qgen/dsqgen).

        Default is 'netezza' for both TPC-DS and TPC-H for modern SQL compatibility.
        Adapters may override to select a closer match if beneficial.

        Args:
            benchmark_name: 'tpch', 'tpcds', etc. (case-insensitive)

        Returns:
            Base dialect string to use when invoking qgen/dsqgen
        """
        benchmark_lower = benchmark_name.lower()
        if benchmark_lower == "tpcds":
            return "netezza"
        else:
            return "netezza"
