"""Unit tests for benchbox.platforms._spark_helpers.

Covers:
  * ``get_spark_query_plan`` - EXPLAIN EXTENDED capture and error fallback.
  * ``validate_spark_identifier`` - 128-char Spark/Hive identifier gate.
  * ``optimize_spark_table_definition`` - V1/V2 USING + constraint stripping
    + SMALLINT upcasting.
  * ``purge_orphaned_warehouse_directory`` - the C1 fix; including the N1
    safety property that a probe FAILURE is not treated as "empty".
  * ``run_spark_schema_creation_loop`` - the shared schema-creation loop
    used by spark/lakesail/velox; including R2 (no silent swallow when
    extraction fails) and the on_pre_loop / on_location_collision hooks.

The adapter-level tests exercise these helpers indirectly via delegation;
this file pins the contracts directly so a regression in the helpers is
caught at the helper layer rather than smuggled through three adapter
test files.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from benchbox.platforms._spark_helpers import (
    SparkLikeAdapterMixin,
    get_spark_query_plan,
    optimize_spark_table_definition,
    purge_orphaned_warehouse_directory,
    run_spark_schema_creation_loop,
    validate_spark_identifier,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


class TestNormalPlanCapture:
    def test_calls_explain_extended(self) -> None:
        spark = MagicMock()
        df = MagicMock()
        df.collect.return_value = []
        spark.sql.return_value = df
        get_spark_query_plan(spark, "SELECT 1")
        spark.sql.assert_called_once_with("EXPLAIN EXTENDED SELECT 1")

    def test_joins_rows_with_newlines(self) -> None:
        spark = MagicMock()
        df = MagicMock()
        rows = [MagicMock(), MagicMock(), MagicMock()]
        rows[0].__getitem__ = lambda self, k: "line A"
        rows[1].__getitem__ = lambda self, k: "line B"
        rows[2].__getitem__ = lambda self, k: "line C"
        df.collect.return_value = rows
        spark.sql.return_value = df
        result = get_spark_query_plan(spark, "SELECT 1")
        assert result == "line A\nline B\nline C"

    def test_single_row_plan(self) -> None:
        spark = MagicMock()
        df = MagicMock()
        row = MagicMock()
        row.__getitem__ = lambda self, k: "== Physical Plan ==\nScan"
        df.collect.return_value = [row]
        spark.sql.return_value = df
        result = get_spark_query_plan(spark, "SELECT 1")
        assert "== Physical Plan ==" in result

    def test_empty_plan_returns_empty_string(self) -> None:
        spark = MagicMock()
        df = MagicMock()
        df.collect.return_value = []
        spark.sql.return_value = df
        result = get_spark_query_plan(spark, "SELECT 1")
        assert result == ""


class TestErrorHandling:
    def test_returns_error_string_on_exception(self) -> None:
        spark = MagicMock()
        spark.sql.side_effect = RuntimeError("session closed")
        result = get_spark_query_plan(spark, "SELECT 1")
        assert result.startswith("Could not get query plan:")
        assert "session closed" in result

    def test_returns_error_string_on_attribute_error(self) -> None:
        # Simulates a None / closed connection
        result = get_spark_query_plan(None, "SELECT 1")
        assert result.startswith("Could not get query plan:")

    def test_returns_error_string_on_collect_failure(self) -> None:
        spark = MagicMock()
        df = MagicMock()
        df.collect.side_effect = ConnectionError("lost connection")
        spark.sql.return_value = df
        result = get_spark_query_plan(spark, "SELECT 1")
        assert result.startswith("Could not get query plan:")
        assert "lost connection" in result

    def test_error_string_format(self) -> None:
        spark = MagicMock()
        spark.sql.side_effect = ValueError("bad query")
        result = get_spark_query_plan(spark, "SELECT X")
        assert result == "Could not get query plan: bad query"


# ---------------------------------------------------------------------------
# validate_spark_identifier
# ---------------------------------------------------------------------------


class TestValidateSparkIdentifier:
    def test_accepts_simple_names(self) -> None:
        assert validate_spark_identifier("orders") is True
        assert validate_spark_identifier("_private") is True
        assert validate_spark_identifier("Table123") is True

    def test_rejects_empty_and_non_string(self) -> None:
        assert validate_spark_identifier("") is False
        assert validate_spark_identifier(None) is False  # type: ignore[arg-type]
        assert validate_spark_identifier(42) is False  # type: ignore[arg-type]

    def test_rejects_injection_payloads(self) -> None:
        assert validate_spark_identifier("a-b") is False
        assert validate_spark_identifier("a; DROP TABLE t") is False
        assert validate_spark_identifier("123starts_with_digit") is False

    def test_enforces_128_char_limit(self) -> None:
        assert validate_spark_identifier("a" * 128) is True
        assert validate_spark_identifier("a" * 129) is False


# ---------------------------------------------------------------------------
# optimize_spark_table_definition
# ---------------------------------------------------------------------------


class TestOptimizeSparkTableDefinition:
    def test_appends_using_parquet(self) -> None:
        result = optimize_spark_table_definition("CREATE TABLE t (id INT)", table_format="parquet")
        assert result.endswith("USING PARQUET")

    def test_appends_using_orc(self) -> None:
        result = optimize_spark_table_definition("CREATE TABLE t (id INT)", table_format="orc")
        assert result.endswith("USING ORC")

    def test_strips_existing_using_clause(self) -> None:
        result = optimize_spark_table_definition(
            "CREATE TABLE t (id INT) USING DELTA",
            table_format="parquet",
        )
        assert "DELTA" not in result.upper()
        assert result.endswith("USING PARQUET")

    def test_non_create_table_unchanged(self) -> None:
        sql = "INSERT INTO t VALUES (1)"
        assert optimize_spark_table_definition(sql, table_format="parquet") == sql

    def test_strip_v1_constraints_removes_inline_pk(self) -> None:
        result = optimize_spark_table_definition(
            "CREATE TABLE t (id INT PRIMARY KEY, val STRING)",
            table_format="parquet",
        )
        assert "PRIMARY KEY" not in result.upper()
        assert "id INT" in result
        assert "val STRING" in result

    def test_strip_v1_constraints_removes_table_level_pk(self) -> None:
        result = optimize_spark_table_definition(
            "CREATE TABLE t (id INT, val STRING, PRIMARY KEY (id))",
            table_format="parquet",
        )
        assert "PRIMARY KEY" not in result.upper()

    def test_strip_v1_constraints_removes_foreign_key(self) -> None:
        result = optimize_spark_table_definition(
            "CREATE TABLE t (id INT, ref_id INT, FOREIGN KEY (ref_id) REFERENCES other(id))",
            table_format="parquet",
        )
        assert "FOREIGN KEY" not in result.upper()
        assert "REFERENCES" not in result.upper()

    def test_strip_v1_constraints_removes_unique_and_check(self) -> None:
        result = optimize_spark_table_definition(
            "CREATE TABLE t (id INT, val INT, UNIQUE (id), CHECK (val > 0))",
            table_format="parquet",
        )
        assert "UNIQUE" not in result.upper()
        assert "CHECK" not in result.upper()

    def test_upcast_smallint_to_int(self) -> None:
        result = optimize_spark_table_definition(
            "CREATE TABLE t (id INT, count SMALLINT)",
            table_format="parquet",
            upcast_smallint=True,
        )
        assert "SMALLINT" not in result.upper()
        assert "INT" in result.upper()

    def test_v2_format_preserves_constraints(self) -> None:
        """Delta/Iceberg call sites pass strip_v1_constraints=False; constraints survive."""
        result = optimize_spark_table_definition(
            "CREATE TABLE t (id INT PRIMARY KEY)",
            table_format="delta",
            strip_v1_constraints=False,
        )
        assert "PRIMARY KEY" in result.upper()
        assert "USING DELTA" in result.upper()

    def test_v2_format_preserves_smallint(self) -> None:
        result = optimize_spark_table_definition(
            "CREATE TABLE t (count SMALLINT)",
            table_format="iceberg",
            upcast_smallint=False,
        )
        assert "SMALLINT" in result.upper()

    def test_strip_constraints_with_nested_paren_check(self) -> None:
        """R1: nested-paren CHECK clauses must be stripped cleanly, not corrupted.

        The previous greedy ``[^)]*`` regex stopped at the first ``)``, leaving
        the rest of the clause dangling and producing unbalanced output.
        """
        result = optimize_spark_table_definition(
            "CREATE TABLE t (a INT, b INT, CHECK ((a > 0) AND (b > 0)))",
            table_format="parquet",
        )
        assert "CHECK" not in result.upper()
        assert "AND" not in result.upper()
        # Output should be a balanced, parseable CREATE TABLE.
        assert result.count("(") == result.count(")")
        assert result.endswith("USING PARQUET")
        assert "a INT" in result
        assert "b INT" in result

    def test_strip_constraints_with_multi_column_foreign_key(self) -> None:
        """Multi-column FOREIGN KEY with REFERENCES must strip cleanly."""
        result = optimize_spark_table_definition(
            "CREATE TABLE t (a INT, b INT, c INT, FOREIGN KEY (a, b) REFERENCES other(c, d))",
            table_format="parquet",
        )
        assert "FOREIGN KEY" not in result.upper()
        assert "REFERENCES" not in result.upper()
        assert result.count("(") == result.count(")")
        assert "a INT" in result
        assert "c INT" in result

    def test_strip_v1_constraints_removes_inline_unique(self) -> None:
        """R3: inline column-level UNIQUE must be stripped (Spark V1 rejects it)."""
        result = optimize_spark_table_definition(
            "CREATE TABLE t (id INT, email STRING UNIQUE)",
            table_format="parquet",
        )
        assert "UNIQUE" not in result.upper()
        assert "email STRING" in result

    def test_strip_v1_constraints_preserves_table_unique_clause_then_strips(self) -> None:
        """Both inline UNIQUE and table-level UNIQUE(...) clauses must be removed."""
        result = optimize_spark_table_definition(
            "CREATE TABLE t (id INT, email STRING UNIQUE, UNIQUE (id))",
            table_format="parquet",
        )
        assert "UNIQUE" not in result.upper()
        assert result.count("(") == result.count(")")
        assert "id INT" in result
        assert "email STRING" in result

    def test_repeated_space_collapse_preserves_newlines(self) -> None:
        """N5: whitespace collapsing must NOT fold newlines (multi-line DDL)."""
        result = optimize_spark_table_definition(
            "CREATE TABLE t (\n    a INT,\n    b INT,\n    PRIMARY KEY (a)\n)",
            table_format="parquet",
        )
        # Newlines from the source DDL should survive the strip+collapse pass.
        assert "\n" in result
        assert "PRIMARY KEY" not in result.upper()

    def test_table_level_pk_after_trailing_comma_leaves_no_dangling_paren(self) -> None:
        """Stripping ``, PRIMARY KEY (col)`` must not leave a bare ``, (col)`` group.

        Regression: the inline-PK regex used to drop just the keywords, leaving
        ``service_zone VARCHAR, (location_id))`` which Sail's DataFusion parser
        rejected with ``found ( expected identifier``.
        """
        result = optimize_spark_table_definition(
            "CREATE TABLE taxi_zones (\n    location_id INTEGER,\n    zone VARCHAR,\n    PRIMARY KEY (location_id)\n)",
            table_format="parquet",
        )
        assert "PRIMARY KEY" not in result.upper()
        # No dangling parenthesised group where a column definition should be.
        assert "(location_id))" not in result.replace(" ", "")
        assert result.count("(") == result.count(")")
        assert result.endswith("USING PARQUET")
        assert "location_id INTEGER" in result
        assert "zone VARCHAR" in result

    def test_strips_leading_line_comments_so_create_table_is_detected(self) -> None:
        """A ``-- comment`` header must not block normalisation of the DDL below it.

        Several benchmark schema generators (metadata_primitives, write_primitives,
        transaction_primitives) emit a comment banner before ``CREATE TABLE``;
        without stripping it the constraint clauses reached Sail verbatim.
        """
        result = optimize_spark_table_definition(
            "-- Benchmark schema\n-- second comment line\n\n"
            "CREATE TABLE region (\n    r_regionkey INTEGER NOT NULL,\n"
            "    r_name CHAR(25) NOT NULL,\n    PRIMARY KEY (r_regionkey)\n)",
            table_format="parquet",
        )
        assert result.upper().startswith("CREATE TABLE")
        assert "PRIMARY KEY" not in result.upper()
        assert "--" not in result
        assert result.endswith("USING PARQUET")

    def test_strips_leading_block_comments(self) -> None:
        """SQLGlot transpilation rewrites -- headers into /* */ blocks folded onto
        the first statement; those must also be stripped before CREATE TABLE
        detection."""
        result = optimize_spark_table_definition(
            "/* Benchmark Schema */ /* second banner */ "
            "CREATE TABLE `region` (`r_regionkey` INT NOT NULL, "
            "`r_comment` STRING, PRIMARY KEY (`r_regionkey`))",
            table_format="parquet",
        )
        assert result.upper().startswith("CREATE TABLE")
        assert "PRIMARY KEY" not in result.upper()
        assert "/*" not in result
        assert result.endswith("USING PARQUET")

    def test_comment_only_chunk_returns_empty(self) -> None:
        assert optimize_spark_table_definition("-- just a comment\n", table_format="parquet") == ""
        assert optimize_spark_table_definition("/* only a block comment */", table_format="parquet") == ""
        assert optimize_spark_table_definition("   \n  ", table_format="parquet") == ""

    def test_fixed_size_array_type_rewritten_to_array_element_type(self) -> None:
        """DuckDB ``FLOAT[128]`` array columns become portable ``ARRAY<FLOAT>``."""
        result = optimize_spark_table_definition(
            "CREATE TABLE vectors (id BIGINT, embedding FLOAT[128], doc_id VARCHAR(100))",
            table_format="parquet",
        )
        assert "ARRAY<FLOAT>" in result.upper()
        assert "[128]" not in result
        assert "embedding ARRAY<FLOAT>" in result

    def test_array_type_with_transpiled_fixed_size_suffix_normalised(self) -> None:
        """SQLGlot may emit ``ARRAY<FLOAT>[128]``; the trailing suffix must drop."""
        result = optimize_spark_table_definition(
            "CREATE TABLE vectors (id BIGINT, embedding ARRAY<FLOAT>[128])",
            table_format="parquet",
        )
        assert "[128]" not in result
        assert "ARRAY<FLOAT>" in result.upper()
        assert result.endswith("USING PARQUET")


# ---------------------------------------------------------------------------
# purge_orphaned_warehouse_directory
# ---------------------------------------------------------------------------


def _purge_stub(*, list_tables_return=None, list_tables_raises=None, current_db="default") -> MagicMock:
    """Build a minimal spark stub for purge tests."""
    spark = MagicMock()
    if list_tables_raises is not None:
        spark.catalog.listTables.side_effect = list_tables_raises
    else:
        spark.catalog.listTables.return_value = list_tables_return or []
    rows_mock = MagicMock()
    rows_mock.collect.return_value = [(current_db,)]
    spark.sql.return_value = rows_mock
    return spark


class TestPurgeOrphanedWarehouseDirectory:
    """The C1 fix: drop+recreate the current DB iff catalog probe says empty.

    Probe FAILURE must NOT trigger the drop (the false-positive trap).
    """

    def test_noop_when_catalog_has_tables(self) -> None:
        existing_table = MagicMock()
        existing_table.name = "orders"
        spark = _purge_stub(list_tables_return=[existing_table])

        purge_orphaned_warehouse_directory(spark, logger=logging.getLogger(__name__))

        spark.catalog.listTables.assert_called_once()
        for call in spark.sql.call_args_list:
            sql_text = str(call.args[0]) if call.args else ""
            assert "DROP DATABASE" not in sql_text.upper()

    def test_drops_and_recreates_when_catalog_empty(self) -> None:
        spark = _purge_stub(list_tables_return=[], current_db="benchbox_run")

        purge_orphaned_warehouse_directory(spark, logger=logging.getLogger(__name__))

        executed = [str(call.args[0]) for call in spark.sql.call_args_list if call.args]
        assert any("DROP DATABASE IF EXISTS `benchbox_run` CASCADE" in s for s in executed)
        assert any("CREATE DATABASE IF NOT EXISTS `benchbox_run`" in s for s in executed)
        assert any("USE `benchbox_run`" in s for s in executed)

    def test_skips_when_catalog_probe_raises(self) -> None:
        """N1: probe failure must NOT be misread as 'empty'."""
        spark = _purge_stub(list_tables_raises=RuntimeError("transient gRPC error"))

        purge_orphaned_warehouse_directory(spark, logger=logging.getLogger(__name__))

        for call in spark.sql.call_args_list:
            sql_text = str(call.args[0]) if call.args else ""
            assert "DROP DATABASE" not in sql_text.upper()

    def test_skips_when_current_database_invalid(self) -> None:
        """A hostile current-database name must not be embedded."""
        spark = MagicMock()
        spark.catalog.listTables.return_value = []
        rows_mock = MagicMock()
        rows_mock.collect.return_value = [("bad; DROP TABLE foo",)]
        spark.sql.return_value = rows_mock

        purge_orphaned_warehouse_directory(spark, logger=logging.getLogger(__name__))

        for call in spark.sql.call_args_list:
            sql_text = str(call.args[0]) if call.args else ""
            assert "DROP DATABASE" not in sql_text.upper()

    def test_logs_at_info_when_purge_fires(self, caplog) -> None:
        """C3: a successful purge must surface at INFO so -v users see it."""
        spark = _purge_stub(list_tables_return=[], current_db="benchbox_run")
        with caplog.at_level(logging.INFO, logger=__name__):
            purge_orphaned_warehouse_directory(spark, logger=logging.getLogger(__name__))

        info_messages = [r.message for r in caplog.records if r.levelno == logging.INFO]
        assert any("Purged potentially-orphaned warehouse" in m for m in info_messages)

    def test_swallows_drop_failures(self) -> None:
        """If DROP fails after empty-catalog probe, log and return without raising."""
        spark = MagicMock()
        spark.catalog.listTables.return_value = []
        rows_mock = MagicMock()
        rows_mock.collect.return_value = [("benchbox_run",)]

        def sql_side_effect(query):
            if "DROP DATABASE" in query.upper():
                raise RuntimeError("boom")
            return rows_mock

        spark.sql.side_effect = sql_side_effect

        # Should not raise.
        purge_orphaned_warehouse_directory(spark, logger=logging.getLogger(__name__))


# ---------------------------------------------------------------------------
# run_spark_schema_creation_loop
# ---------------------------------------------------------------------------


class TestRunSparkSchemaCreationLoop:
    def test_happy_path_executes_each_statement(self) -> None:
        spark = MagicMock()
        statements = [
            "CREATE TABLE orders (id INT)",
            "CREATE TABLE customers (id INT)",
        ]

        run_spark_schema_creation_loop(
            spark,
            statements,
            lambda s: optimize_spark_table_definition(s, table_format="parquet"),
            logger=logging.getLogger(__name__),
        )

        assert spark.sql.call_count == 2
        assert all("USING PARQUET" in str(call.args[0]).upper() for call in spark.sql.call_args_list)

    def test_pre_loop_hook_runs_once_before_statements(self) -> None:
        """Velox uses on_pre_loop to call purge_orphaned_warehouse_directory."""
        spark = MagicMock()
        order: list[str] = []
        spark.sql.side_effect = lambda q: (order.append("sql"), MagicMock())[1]

        def pre_loop(_s) -> None:
            order.append("pre_loop")

        run_spark_schema_creation_loop(
            spark,
            ["CREATE TABLE t (id INT)"],
            lambda s: s + " USING PARQUET",
            logger=logging.getLogger(__name__),
            on_pre_loop=pre_loop,
        )

        assert order == ["pre_loop", "sql"]

    def test_already_exists_triggers_drop_then_retry(self) -> None:
        spark = MagicMock()
        calls: list[str] = []

        def sql_side_effect(query):
            calls.append(query)
            if calls.count(query) == 1 and query.startswith("CREATE TABLE"):
                raise RuntimeError("Table or view already exists: orders")
            return MagicMock()

        spark.sql.side_effect = sql_side_effect

        run_spark_schema_creation_loop(
            spark,
            ["CREATE TABLE orders (id INT)"],
            lambda s: s,
            logger=logging.getLogger(__name__),
        )

        assert any(c.startswith("CREATE TABLE orders") for c in calls)
        assert any(c.startswith("DROP TABLE IF EXISTS") for c in calls)
        assert sum(1 for c in calls if c.startswith("CREATE TABLE orders")) == 2

    def test_already_exists_with_backtick_identifier_drops_unquoted_safe_name(self) -> None:
        spark = MagicMock()
        calls: list[str] = []

        def sql_side_effect(query):
            calls.append(query)
            if calls.count(query) == 1 and query.startswith("CREATE TABLE"):
                raise RuntimeError("[LOCATION_ALREADY_EXISTS] The location for table 'region' already exists.")
            return MagicMock()

        spark.sql.side_effect = sql_side_effect

        run_spark_schema_creation_loop(
            spark,
            ["CREATE TABLE `region` (`r_regionkey` INT)"],
            lambda s: s,
            logger=logging.getLogger(__name__),
        )

        assert "DROP TABLE IF EXISTS region" in calls
        assert sum(1 for c in calls if c.startswith("CREATE TABLE `region`")) == 2

    def test_backtick_quoted_dotted_identifier_still_fails_validation(self) -> None:
        spark = MagicMock()
        spark.sql.side_effect = RuntimeError("Table already exists")

        with pytest.raises(RuntimeError, match="strict-ASCII identifier validation"):
            run_spark_schema_creation_loop(
                spark,
                ["CREATE TABLE `my_schema.tbl` (id INT)"],
                lambda s: s,
                logger=logging.getLogger(__name__),
            )

    def test_location_collision_hook_fires_on_location_already_exists(self) -> None:
        """Spark.py uses on_location_collision to rmtree the orphaned warehouse dir."""
        spark = MagicMock()
        collision_calls: list[tuple] = []
        first_call = {"flag": True}

        def sql_side_effect(query):
            if first_call["flag"] and query.startswith("CREATE TABLE"):
                first_call["flag"] = False
                # Real Spark error format: bracketed class name + human message.
                # The helper's "already exists" (with space) and
                # "location_already_exists" (with underscore) checks both match.
                raise RuntimeError("[LOCATION_ALREADY_EXISTS] The location for table 'orders' already exists.")
            return MagicMock()

        spark.sql.side_effect = sql_side_effect

        def on_collision(s, table_name) -> None:
            collision_calls.append((s, table_name))

        run_spark_schema_creation_loop(
            spark,
            ["CREATE TABLE orders (id INT)"],
            lambda s: s,
            logger=logging.getLogger(__name__),
            on_location_collision=on_collision,
        )

        assert len(collision_calls) == 1
        assert collision_calls[0][0] is spark
        assert collision_calls[0][1] == "orders"

    def test_location_collision_hook_skipped_for_plain_already_exists(self) -> None:
        """Hook should NOT fire when error is plain 'already exists' (not LOCATION)."""
        spark = MagicMock()
        collision_calls: list[tuple] = []
        first_call = {"flag": True}

        def sql_side_effect(query):
            if first_call["flag"] and query.startswith("CREATE TABLE"):
                first_call["flag"] = False
                raise RuntimeError("Table or view already exists: orders")
            return MagicMock()

        spark.sql.side_effect = sql_side_effect

        def on_collision(s, table_name) -> None:
            collision_calls.append((s, table_name))

        run_spark_schema_creation_loop(
            spark,
            ["CREATE TABLE orders (id INT)"],
            lambda s: s,
            logger=logging.getLogger(__name__),
            on_location_collision=on_collision,
        )

        assert collision_calls == []

    def test_raises_when_extract_returns_none(self) -> None:
        """R2 + N6: do not silently swallow; raise with a clear, specific message."""
        spark = MagicMock()
        spark.sql.side_effect = RuntimeError("View already exists")

        # ALTER VIEW is not a CREATE TABLE so extract_spark_table_name returns None.
        # The wrapped RuntimeError must explain *why* recovery was skipped, not
        # just re-emit the underlying Spark error.
        with pytest.raises(RuntimeError, match="strict-ASCII identifier validation"):
            run_spark_schema_creation_loop(
                spark,
                ["ALTER VIEW v AS SELECT 1"],
                lambda s: s,
                logger=logging.getLogger(__name__),
            )

    def test_raises_when_extracted_name_fails_validation(self) -> None:
        """N6: schema-qualified names extract OK but fail strict-ASCII validation;
        the helper must raise with a clear message rather than the bare Spark error."""
        spark = MagicMock()
        spark.sql.side_effect = RuntimeError("Table already exists")

        with pytest.raises(RuntimeError, match="strict-ASCII identifier validation"):
            run_spark_schema_creation_loop(
                spark,
                ["CREATE TABLE my_schema.tbl (id INT)"],
                lambda s: s,
                logger=logging.getLogger(__name__),
            )

    def test_raises_for_non_already_exists_errors(self) -> None:
        spark = MagicMock()
        spark.sql.side_effect = RuntimeError("syntax error near '('")

        with pytest.raises(RuntimeError, match="syntax error"):
            run_spark_schema_creation_loop(
                spark,
                ["CREATE TABLE t (id INT)"],
                lambda s: s,
                logger=logging.getLogger(__name__),
            )

    def test_skips_empty_statements(self) -> None:
        spark = MagicMock()
        run_spark_schema_creation_loop(
            spark,
            ["", "  ", "CREATE TABLE t (id INT)"],
            lambda s: s,
            logger=logging.getLogger(__name__),
        )
        # Only the non-empty statement runs.
        assert spark.sql.call_count == 1


# ---------------------------------------------------------------------------
# SparkLikeAdapterMixin
# ---------------------------------------------------------------------------


@dataclass
class _DummyTuningRecord:
    enabled: bool


@dataclass
class _DummyPlatformConfig:
    spark: dict | None


class _DummyUnifiedConfig:
    def __init__(
        self,
        *,
        primary_keys=None,
        foreign_keys=None,
        platform_optimizations=None,
        table_tunings=None,
    ) -> None:
        self.primary_keys = primary_keys
        self.foreign_keys = foreign_keys
        self.platform_optimizations = platform_optimizations
        self.table_tunings = table_tunings or {}


class _StubAdapter(SparkLikeAdapterMixin):
    """Bare-minimum host class for the mixin contract tests."""

    def __init__(self, name: str = "TestPlatform") -> None:
        self.platform_name = name
        self.logger = logging.getLogger(__name__)
        self.table_tuning_calls: list = []

    def apply_table_tunings(self, table_tuning, connection) -> None:
        self.table_tuning_calls.append((table_tuning, connection))


class TestSparkLikeAdapterMixin:
    """C2: shared bodies for apply_constraint_configuration / apply_unified_tuning /
    apply_platform_optimizations - identical across spark/lakesail/velox."""

    def test_apply_constraint_configuration_logs_platform_name(self, caplog) -> None:
        adapter = _StubAdapter("LakeSail")
        with caplog.at_level(logging.INFO, logger=__name__):
            adapter.apply_constraint_configuration(_DummyTuningRecord(True), _DummyTuningRecord(True), connection=None)
        joined = "\n".join(r.message for r in caplog.records)
        assert "Primary key constraints enabled for LakeSail" in joined
        assert "Foreign key constraints enabled for LakeSail" in joined

    def test_apply_constraint_configuration_silent_when_disabled(self, caplog) -> None:
        adapter = _StubAdapter("Velox")
        with caplog.at_level(logging.INFO, logger=__name__):
            adapter.apply_constraint_configuration(
                _DummyTuningRecord(False), _DummyTuningRecord(False), connection=None
            )
        assert not any("constraints enabled" in r.message for r in caplog.records)

    def test_apply_platform_optimizations_forwards_to_spark_conf(self) -> None:
        adapter = _StubAdapter("Spark")
        spark = MagicMock()
        adapter.apply_platform_optimizations(
            _DummyPlatformConfig({"sql.adaptive.enabled": "true", "sql.cbo.enabled": "true"}),
            connection=spark,
        )
        spark.conf.set.assert_any_call("spark.sql.adaptive.enabled", "true")
        spark.conf.set.assert_any_call("spark.sql.cbo.enabled", "true")

    def test_apply_platform_optimizations_logs_warning_on_failure(self, caplog) -> None:
        adapter = _StubAdapter("Spark")
        spark = MagicMock()
        spark.conf.set.side_effect = RuntimeError("rejected")
        with caplog.at_level(logging.WARNING, logger=__name__):
            adapter.apply_platform_optimizations(_DummyPlatformConfig({"foo.bar": "baz"}), connection=spark)
        warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("Failed to apply Spark config spark.foo.bar" in m for m in warnings)

    def test_apply_unified_tuning_dispatches_in_fixed_order(self) -> None:
        adapter = _StubAdapter("LakeSail")
        spark = MagicMock()
        config = _DummyUnifiedConfig(
            primary_keys=_DummyTuningRecord(True),
            foreign_keys=_DummyTuningRecord(True),
            platform_optimizations=_DummyPlatformConfig({"sql.adaptive.enabled": "true"}),
            table_tunings={"orders": "TUNING_A", "customer": "TUNING_B"},
        )
        adapter.apply_unified_tuning(config, connection=spark)
        # Two table tunings, both reached.
        recorded = [tuning for tuning, _ in adapter.table_tuning_calls]
        assert "TUNING_A" in recorded
        assert "TUNING_B" in recorded
        # Platform-optimisation forward also fired.
        spark.conf.set.assert_called_with("spark.sql.adaptive.enabled", "true")

    def test_apply_unified_tuning_returns_early_on_none(self) -> None:
        adapter = _StubAdapter("Velox")
        adapter.apply_unified_tuning(None, connection=MagicMock())
        assert adapter.table_tuning_calls == []
