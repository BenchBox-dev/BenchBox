"""Coverage-targeted tests for LakeSail Sail platform adapter.

Targets uncovered branches in benchbox/platforms/lakesail.py to reach ≥80%.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# ---------------------------------------------------------------------------
# Shared test fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_pyspark():
    """Mock pyspark module stack for LakeSail adapter tests."""
    mock_spark_session = MagicMock()
    mock_builder = MagicMock()
    mock_builder.remote.return_value = mock_builder
    mock_builder.config.return_value = mock_builder
    mock_builder.getOrCreate.return_value = mock_spark_session

    mock_spark_session.version = "3.5.0"
    mock_spark_session.catalog.listDatabases.return_value = []
    mock_spark_session.sql.return_value = MagicMock()
    mock_spark_session.conf = MagicMock()

    mock_session_class = MagicMock()
    mock_session_class.builder = mock_builder

    with (
        patch.dict(
            "sys.modules",
            {
                "pyspark": MagicMock(__version__="3.5.0"),
                "pyspark.sql": MagicMock(SparkSession=mock_session_class),
                "pyspark.sql.types": MagicMock(
                    StructType=MagicMock(),
                    StructField=MagicMock(),
                    StringType=MagicMock(),
                    IntegerType=MagicMock(),
                    LongType=MagicMock(),
                    DoubleType=MagicMock(),
                    DecimalType=MagicMock(),
                    DateType=MagicMock(),
                ),
            },
        ),
        # Bypass real TCP connect so create_connection() doesn't need a live server.
        patch("benchbox.platforms.lakesail.is_spark_connect_reachable", return_value=True),
    ):
        yield mock_session_class, mock_spark_session


# ---------------------------------------------------------------------------
# Init: SparkSession=None path (lines 88-92)
# ---------------------------------------------------------------------------


class TestLakeSailInitNoPyspark:
    """Test __init__ when pyspark is unavailable."""

    def test_init_raises_when_no_pyspark_and_deps_missing(self):
        """ImportError raised when SparkSession is None and deps are missing."""
        import benchbox.platforms.lakesail as mod

        orig = mod.SparkSession
        try:
            mod.SparkSession = None
            with (
                patch(
                    "benchbox.platforms.lakesail.check_platform_dependencies",
                    return_value=(False, ["pyspark"]),
                ),
                patch(
                    "benchbox.platforms.lakesail.get_dependency_error_message",
                    return_value="pyspark is required",
                ),
                pytest.raises(ImportError, match="pyspark is required"),
            ):
                from benchbox.platforms.lakesail import LakeSailAdapter

                LakeSailAdapter()
        finally:
            mod.SparkSession = orig

    def test_init_ok_when_no_pyspark_but_deps_available(self):
        """No error when SparkSession is None but deps report available."""
        import benchbox.platforms.lakesail as mod

        orig = mod.SparkSession
        try:
            mod.SparkSession = None
            with (
                patch(
                    "benchbox.platforms.lakesail.check_platform_dependencies",
                    return_value=(True, []),
                ),
            ):
                from benchbox.platforms.lakesail import LakeSailAdapter

                adapter = LakeSailAdapter()
            assert adapter.endpoint == "sc://localhost:50051"
        finally:
            mod.SparkSession = orig


# ---------------------------------------------------------------------------
# from_config: explicit database branch (line 191)
# ---------------------------------------------------------------------------


class TestLakeSailFromConfig:
    """Test from_config() branching."""

    def test_from_config_with_explicit_database(self, mock_pyspark):
        """from_config uses provided database without generating a name."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        config = {
            "benchmark": "tpch",
            "scale_factor": 1.0,
            "database": "my_explicit_db",
            "endpoint": "sc://server:50051",
        }
        adapter = LakeSailAdapter.from_config(config)
        assert adapter.database == "my_explicit_db"

    def test_from_config_optional_keys_forwarded(self, mock_pyspark):
        """from_config forwards all optional config keys."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        config = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "shuffle_partitions": 100,
            "adaptive_enabled": False,
            "table_format": "orc",
            "spark_config": {"some.key": "val"},
            "disable_cache": False,
        }
        adapter = LakeSailAdapter.from_config(config)
        assert adapter.shuffle_partitions == 100
        assert adapter.adaptive_enabled is False
        assert adapter.table_format == "orc"
        assert adapter.spark_config == {"some.key": "val"}
        assert adapter.disable_cache is False


# ---------------------------------------------------------------------------
# get_platform_info: pyspark version, connection version, error paths
# (lines 252, 256-261)
# ---------------------------------------------------------------------------


class TestLakeSailGetPlatformInfo:
    """Test get_platform_info() branches."""

    def test_platform_info_with_connection_version(self, mock_pyspark):
        """platform_version set when live connection provided."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        mock_conn = MagicMock()
        mock_conn.version = "3.5.1"

        adapter = LakeSailAdapter()
        info = adapter.get_platform_info(connection=mock_conn)

        assert info["platform_version"] == "3.5.1"

    def test_platform_info_connection_version_error(self, mock_pyspark):
        """platform_version is None when connection.version raises."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        mock_conn = MagicMock()
        type(mock_conn).version = property(lambda self: (_ for _ in ()).throw(RuntimeError("no version")))

        adapter = LakeSailAdapter()
        info = adapter.get_platform_info(connection=mock_conn)

        assert info["platform_version"] is None

    def test_platform_info_pyspark_version_importerror(self, mock_pyspark):
        """client_library_version is None when pyspark import fails inside get_platform_info."""
        import benchbox.platforms.lakesail as mod

        with patch.object(mod, "SparkSession", MagicMock()):
            adapter = mod.LakeSailAdapter()
            # Patch pyspark to None so the `import pyspark` inside get_platform_info raises
            with patch.dict("sys.modules", {"pyspark": None}):
                info = adapter.get_platform_info()
            assert info["client_library_version"] is None


# ---------------------------------------------------------------------------
# _get_spark_conf: disable_cache=False, spark_config merge (lines 285-289)
# ---------------------------------------------------------------------------


class TestLakeSailGetSparkConf:
    """Test _get_spark_conf() variations."""

    def test_spark_conf_disable_cache_false(self, mock_pyspark):
        """No cache-disable key when disable_cache is False."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter(disable_cache=False)
        conf = adapter._get_spark_conf()
        assert "spark.sql.inMemoryColumnarStorage.enabled" not in conf

    def test_spark_conf_merges_user_spark_config(self, mock_pyspark):
        """User-provided spark_config keys override defaults."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter(spark_config={"custom.key": "custom_val"})
        conf = adapter._get_spark_conf()
        assert conf["custom.key"] == "custom_val"


# ---------------------------------------------------------------------------
# _create_spark_session: builder chain (lines 295-298)
# ---------------------------------------------------------------------------


class TestLakeSailCreateSparkSession:
    """Test _create_spark_session() builder chain."""

    def test_create_spark_session_calls_remote(self, mock_pyspark):
        """_create_spark_session calls SparkSession.builder.remote(endpoint)."""
        import benchbox.platforms.lakesail as mod

        mock_session_class, mock_session = mock_pyspark

        with patch.object(mod, "SparkSession", mock_session_class):
            from benchbox.platforms.lakesail import LakeSailAdapter

            adapter = LakeSailAdapter(endpoint="sc://myhost:50051")
            result = adapter._create_spark_session()

        mock_session_class.builder.remote.assert_called_with("sc://myhost:50051")
        assert result is mock_session


# ---------------------------------------------------------------------------
# check_server_database_exists: various branches (lines 305-321)
# ---------------------------------------------------------------------------


class TestLakeSailCheckServerDatabaseExists:
    """Test check_server_database_exists() branching."""

    def test_check_db_exists_uses_existing_session(self, mock_pyspark):
        """No new session created when _spark_session already set."""
        import benchbox.platforms.lakesail as mod

        mock_session_class, mock_session = mock_pyspark
        mock_db = MagicMock()
        mock_db.name = "mydb"
        mock_session.catalog.listDatabases.return_value = [mock_db]

        with patch.object(mod, "SparkSession", mock_session_class):
            from benchbox.platforms.lakesail import LakeSailAdapter

            adapter = LakeSailAdapter(database="mydb")
            adapter._spark_session = mock_session  # pre-set session

            result = adapter.check_server_database_exists(database="mydb")

        assert result is True
        # builder.remote should NOT have been called since session was pre-set
        mock_session_class.builder.remote.assert_not_called()

    def test_check_db_creates_session_and_stops(self, mock_pyspark):
        """New session created and stopped when _spark_session is None."""
        import benchbox.platforms.lakesail as mod

        mock_session_class, mock_session = mock_pyspark
        mock_session.catalog.listDatabases.return_value = []

        with patch.object(mod, "SparkSession", mock_session_class):
            from benchbox.platforms.lakesail import LakeSailAdapter

            adapter = LakeSailAdapter(database="test_db")
            adapter._spark_session = None

            result = adapter.check_server_database_exists(database="test_db")

        assert result is False
        mock_session.stop.assert_called_once()

    def test_check_db_returns_false_on_exception(self, mock_pyspark):
        """Returns False when session creation raises."""
        import benchbox.platforms.lakesail as mod

        mock_session_class, mock_session = mock_pyspark
        mock_session_class.builder.remote.side_effect = RuntimeError("connection refused")

        with patch.object(mod, "SparkSession", mock_session_class):
            from benchbox.platforms.lakesail import LakeSailAdapter

            adapter = LakeSailAdapter()
            result = adapter.check_server_database_exists()

        assert result is False

    def test_check_db_stop_error_suppressed_in_finally(self, mock_pyspark):
        """stop() errors in finally block are silently suppressed."""
        import benchbox.platforms.lakesail as mod

        mock_session_class, mock_session = mock_pyspark
        mock_session.catalog.listDatabases.return_value = []
        mock_session.stop.side_effect = RuntimeError("stop failed")

        with patch.object(mod, "SparkSession", mock_session_class):
            from benchbox.platforms.lakesail import LakeSailAdapter

            adapter = LakeSailAdapter()
            # Should not raise despite stop() failing
            result = adapter.check_server_database_exists()

        assert result is False


# ---------------------------------------------------------------------------
# drop_database: all branches (lines 325-350)
# ---------------------------------------------------------------------------


class TestLakeSailDropDatabase:
    """Test drop_database() branching."""

    def test_drop_database_invalid_identifier_raises(self, mock_pyspark):
        """ValueError raised for invalid database name."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter(database="valid_db")
        with pytest.raises(ValueError, match="Invalid database identifier"):
            adapter.drop_database(database="123invalid")

    def test_drop_database_nonexistent_returns_early(self, mock_pyspark):
        """Returns early (no session created) when database does not exist."""
        import benchbox.platforms.lakesail as mod

        mock_session_class, mock_session = mock_pyspark

        with patch.object(mod, "SparkSession", mock_session_class):
            from benchbox.platforms.lakesail import LakeSailAdapter

            adapter = LakeSailAdapter(database="mydb")

            with patch.object(adapter, "check_server_database_exists", return_value=False):
                adapter.drop_database(database="mydb")

            # sql should not be called since db doesn't exist
            mock_session.sql.assert_not_called()

    def test_drop_database_success(self, mock_pyspark):
        """Successfully drops an existing database."""
        import benchbox.platforms.lakesail as mod

        mock_session_class, mock_session = mock_pyspark

        with patch.object(mod, "SparkSession", mock_session_class):
            from benchbox.platforms.lakesail import LakeSailAdapter

            adapter = LakeSailAdapter(database="mydb")

            with patch.object(adapter, "check_server_database_exists", return_value=True):
                adapter.drop_database(database="mydb")

            mock_session.sql.assert_called_once_with("DROP DATABASE IF EXISTS mydb CASCADE")
            mock_session.stop.assert_called_once()

    def test_drop_database_uses_existing_session(self, mock_pyspark):
        """Uses pre-existing _spark_session without creating new one."""
        import benchbox.platforms.lakesail as mod

        mock_session_class, mock_session = mock_pyspark

        with patch.object(mod, "SparkSession", mock_session_class):
            from benchbox.platforms.lakesail import LakeSailAdapter

            adapter = LakeSailAdapter(database="mydb")
            adapter._spark_session = mock_session

            with patch.object(adapter, "check_server_database_exists", return_value=True):
                adapter.drop_database(database="mydb")

        # Stop not called since we own_session=False (pre-existing session)
        mock_session.stop.assert_not_called()
        mock_session.sql.assert_called_with("DROP DATABASE IF EXISTS mydb CASCADE")

    def test_drop_database_exception_raises_runtime_error(self, mock_pyspark):
        """RuntimeError raised when drop fails."""
        import benchbox.platforms.lakesail as mod

        mock_session_class, mock_session = mock_pyspark
        mock_session.sql.side_effect = Exception("permission denied")

        with patch.object(mod, "SparkSession", mock_session_class):
            from benchbox.platforms.lakesail import LakeSailAdapter

            adapter = LakeSailAdapter(database="mydb")

            with (
                patch.object(adapter, "check_server_database_exists", return_value=True),
                pytest.raises(RuntimeError, match="Failed to drop database"),
            ):
                adapter.drop_database(database="mydb")

    def test_drop_database_default_database_name(self, mock_pyspark):
        """Uses self.database when no database keyword arg given."""
        import benchbox.platforms.lakesail as mod

        mock_session_class, mock_session = mock_pyspark

        with patch.object(mod, "SparkSession", mock_session_class):
            from benchbox.platforms.lakesail import LakeSailAdapter

            adapter = LakeSailAdapter(database="default_db")

            with patch.object(adapter, "check_server_database_exists", return_value=True):
                adapter.drop_database()  # no database= kwarg

            mock_session.sql.assert_called_once_with("DROP DATABASE IF EXISTS default_db CASCADE")


# ---------------------------------------------------------------------------
# create_connection: database_was_reused=True path, db creation, exception path
# (lines 380-405)
# ---------------------------------------------------------------------------


class TestLakeSailCreateConnection:
    """Test create_connection() branching."""

    def test_create_connection_database_was_reused_skips_db_check(self, mock_pyspark):
        """When database_was_reused=True, skips create-database check."""
        import benchbox.platforms.lakesail as mod

        mock_session_class, mock_session = mock_pyspark

        with patch.object(mod, "SparkSession", mock_session_class):
            from benchbox.platforms.lakesail import LakeSailAdapter

            adapter = LakeSailAdapter(database="reused_db")

            with patch.object(adapter, "handle_existing_database"):
                adapter.database_was_reused = True
                adapter.create_connection()

        assert adapter._spark_session is mock_session
        # check_server_database_exists should NOT be called
        # (only USE is called)
        calls = [str(c) for c in mock_session.sql.call_args_list]
        assert any("USE" in c for c in calls)

    def test_create_connection_creates_db_when_not_exists(self, mock_pyspark):
        """CREATE DATABASE called when database doesn't exist."""
        import benchbox.platforms.lakesail as mod

        mock_session_class, mock_session = mock_pyspark

        with patch.object(mod, "SparkSession", mock_session_class):
            from benchbox.platforms.lakesail import LakeSailAdapter

            adapter = LakeSailAdapter(database="new_db")

            with (
                patch.object(adapter, "handle_existing_database"),
                patch.object(adapter, "check_server_database_exists", return_value=False),
            ):
                adapter.database_was_reused = False
                adapter.create_connection()

        assert adapter._spark_session is mock_session
        sql_calls = [c[0][0] for c in mock_session.sql.call_args_list]
        assert any("CREATE DATABASE" in s for s in sql_calls)
        assert any("USE" in s for s in sql_calls)

    def test_create_connection_skips_create_when_db_exists(self, mock_pyspark):
        """No CREATE DATABASE when database already exists."""
        import benchbox.platforms.lakesail as mod

        mock_session_class, mock_session = mock_pyspark

        with patch.object(mod, "SparkSession", mock_session_class):
            from benchbox.platforms.lakesail import LakeSailAdapter

            adapter = LakeSailAdapter(database="existing_db")

            with (
                patch.object(adapter, "handle_existing_database"),
                patch.object(adapter, "check_server_database_exists", return_value=True),
            ):
                adapter.database_was_reused = False
                adapter.create_connection()

        sql_calls = [c[0][0] for c in mock_session.sql.call_args_list]
        assert not any("CREATE DATABASE" in s for s in sql_calls)
        assert any("USE" in s for s in sql_calls)

    def test_create_connection_exception_stops_and_clears_session(self, mock_pyspark):
        """Session stopped and cleared on exception."""
        import benchbox.platforms.lakesail as mod

        mock_session_class, mock_session = mock_pyspark

        with patch.object(mod, "SparkSession", mock_session_class):
            from benchbox.platforms.lakesail import LakeSailAdapter

            adapter = LakeSailAdapter(database="mydb")

            with (
                patch.object(adapter, "handle_existing_database", side_effect=RuntimeError("db error")),
                pytest.raises(RuntimeError, match="db error"),
            ):
                adapter.create_connection()

        mock_session.stop.assert_called_once()
        assert adapter._spark_session is None

    def test_create_connection_stop_error_in_exception_handler_suppressed(self, mock_pyspark):
        """stop() error in exception handler does not mask original error."""
        import benchbox.platforms.lakesail as mod

        mock_session_class, mock_session = mock_pyspark
        mock_session.stop.side_effect = RuntimeError("stop failed")

        with patch.object(mod, "SparkSession", mock_session_class):
            from benchbox.platforms.lakesail import LakeSailAdapter

            adapter = LakeSailAdapter(database="mydb")

            with (
                patch.object(adapter, "handle_existing_database", side_effect=RuntimeError("original error")),
                pytest.raises(RuntimeError, match="original error"),
            ):
                adapter.create_connection()

        assert adapter._spark_session is None


# ---------------------------------------------------------------------------
# create_schema: all branches including already-exists retry (lines 409-446)
# ---------------------------------------------------------------------------


class TestLakeSailCreateSchema:
    """Test create_schema() branching."""

    def test_create_schema_success(self, mock_pyspark):
        """Successfully executes all schema statements."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_session = mock_pyspark

        adapter = LakeSailAdapter(table_format="parquet")

        mock_benchmark = MagicMock()
        with patch.object(
            adapter,
            "_create_schema_with_tuning",
            return_value="CREATE TABLE orders (id INT); CREATE TABLE lineitem (id INT)",
        ):
            elapsed = adapter.create_schema(mock_benchmark, mock_session)

        assert isinstance(elapsed, float)
        assert mock_session.sql.call_count >= 2

    def test_create_schema_table_already_exists_retries(self, mock_pyspark):
        """Drops and recreates table when 'already exists' error raised."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_session = mock_pyspark

        # Make the pre-loop purge a no-op (catalog reports an existing table,
        # so purge_orphaned_warehouse_directory returns early).  This isolates
        # the test to the in-loop drop-and-retry path.
        existing = MagicMock()
        existing.name = "orders"
        mock_session.catalog.listTables.return_value = [existing]

        # First CREATE raises "already exists", DROP + retry succeed.
        mock_session.sql.side_effect = [
            Exception("table already exists"),
            MagicMock(),  # DROP TABLE
            MagicMock(),  # retry CREATE
        ]

        adapter = LakeSailAdapter(table_format="parquet")
        mock_benchmark = MagicMock()
        with patch.object(
            adapter,
            "_create_schema_with_tuning",
            return_value="CREATE TABLE orders (id INT)",
        ):
            adapter.create_schema(mock_benchmark, mock_session)

        # Should have called DROP TABLE IF EXISTS then the original statement again
        calls = [str(c) for c in mock_session.sql.call_args_list]
        assert any("DROP TABLE IF EXISTS" in c for c in calls)

    def test_create_schema_non_exists_error_raises(self, mock_pyspark):
        """Non-exists errors propagate upward."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_session = mock_pyspark
        mock_session.sql.side_effect = Exception("syntax error")

        adapter = LakeSailAdapter()
        mock_benchmark = MagicMock()
        with (
            patch.object(
                adapter,
                "_create_schema_with_tuning",
                return_value="CREATE TABLE orders (id INT)",
            ),
            pytest.raises(Exception, match="syntax error"),
        ):
            adapter.create_schema(mock_benchmark, mock_session)

    def test_create_schema_skips_empty_statements(self, mock_pyspark):
        """Empty statements (after split) are skipped."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_session = mock_pyspark

        # Pre-loop purge no-op: catalog reports an existing table.
        existing = MagicMock()
        existing.name = "orders"
        mock_session.catalog.listTables.return_value = [existing]

        adapter = LakeSailAdapter()
        mock_benchmark = MagicMock()
        with patch.object(
            adapter,
            "_create_schema_with_tuning",
            return_value="CREATE TABLE orders (id INT); ; ",
        ):
            adapter.create_schema(mock_benchmark, mock_session)

        # Only one real statement is executed via spark.sql() (the purge
        # short-circuited because the catalog reports tables present).
        assert mock_session.sql.call_count == 1


# ---------------------------------------------------------------------------
# load_data delegates to mixin (line 456)
# ---------------------------------------------------------------------------


class TestLakeSailLoadData:
    """Test load_data() delegation."""

    def test_load_data_delegates_to_mixin(self, mock_pyspark):
        """load_data delegates to _load_data_spark."""
        from pathlib import Path

        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()
        mock_benchmark = MagicMock()
        mock_conn = MagicMock()
        expected = ({"orders": 100}, 1.0, None)

        with patch.object(adapter, "_load_data_spark", return_value=expected) as mock_mixin:
            result = adapter.load_data(mock_benchmark, mock_conn, Path("/tmp/data"))

        mock_mixin.assert_called_once_with(mock_benchmark, Path("/tmp/data"), mock_conn)
        assert result == expected


# ---------------------------------------------------------------------------
# configure_for_benchmark: non-OLAP path (line 463->exit, 472-473)
# ---------------------------------------------------------------------------


class TestLakeSailConfigureForBenchmark:
    """Test configure_for_benchmark() branching."""

    def test_configure_non_olap_benchmark_no_confs_set(self, mock_pyspark):
        """Non-OLAP benchmark types skip setting Spark conf."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_session = mock_pyspark
        adapter = LakeSailAdapter()
        adapter.configure_for_benchmark(mock_session, "ssb")
        mock_session.conf.set.assert_not_called()

    def test_configure_for_benchmark_exception_logged(self, mock_pyspark):
        """Exception during conf.set is caught and logged."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_session = mock_pyspark
        mock_session.conf.set.side_effect = Exception("conf error")

        adapter = LakeSailAdapter()
        # Should not raise
        adapter.configure_for_benchmark(mock_session, "tpch")


# ---------------------------------------------------------------------------
# _optimize_table_definition: existing USING clause stripped (line 513, 520-526)
# ---------------------------------------------------------------------------


class TestLakeSailOptimizeTableDefinition:
    """LakeSail's table-definition normalisation comes from the shared helper.

    Comprehensive coverage of the helper itself lives in test_spark_helpers.py;
    these tests pin LakeSail-specific edge cases that aren't redundant with that.
    """

    def test_optimize_strips_existing_using_clause(self, mock_pyspark):
        """Existing USING clause is removed before adding new one."""
        from benchbox.platforms._spark_helpers import optimize_spark_table_definition

        result = optimize_spark_table_definition(
            "CREATE TABLE t (id INT) USING DELTA",
            table_format="parquet",
        )
        assert "USING PARQUET" in result.upper()
        assert "DELTA" not in result.upper()

    def test_optimize_non_create_table_returned_unchanged(self, mock_pyspark):
        """Non-CREATE TABLE statements are returned unchanged."""
        from benchbox.platforms._spark_helpers import optimize_spark_table_definition

        sql = "INSERT INTO t VALUES (1)"
        assert optimize_spark_table_definition(sql, table_format="parquet") == sql

    def test_optimize_no_paren_returns_unchanged(self, mock_pyspark):
        """Statements without ')' are returned unchanged (no USING appended)."""
        from benchbox.platforms._spark_helpers import optimize_spark_table_definition

        sql = "CREATE TABLE t"
        result = optimize_spark_table_definition(sql, table_format="orc")
        assert "USING ORC" not in result.upper()


# ---------------------------------------------------------------------------
# close_connection: exception path (lines 544-545)
# ---------------------------------------------------------------------------


class TestLakeSailCloseConnection:
    """Test close_connection() exception handling."""

    def test_close_connection_stop_error_logged(self, mock_pyspark):
        """stop() exception is caught and logged, not re-raised."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_session = mock_pyspark
        mock_session.stop.side_effect = RuntimeError("stop error")

        adapter = LakeSailAdapter()
        # Should not raise
        adapter.close_connection(mock_session)


# ---------------------------------------------------------------------------
# test_connection: success and failure paths (lines 549-559)
# ---------------------------------------------------------------------------


class TestLakeSailTestConnection:
    """Test test_connection() paths."""

    def test_test_connection_success(self, mock_pyspark):
        """Returns True when SELECT 1 succeeds."""
        import benchbox.platforms.lakesail as mod

        mock_session_class, mock_session = mock_pyspark

        with patch.object(mod, "SparkSession", mock_session_class):
            from benchbox.platforms.lakesail import LakeSailAdapter

            adapter = LakeSailAdapter()
            result = adapter.test_connection()

        assert result is True
        mock_session.sql.assert_called_with("SELECT 1")
        mock_session.stop.assert_called_once()

    def test_test_connection_failure(self, mock_pyspark):
        """Returns False when session creation raises."""
        import benchbox.platforms.lakesail as mod

        mock_session_class, _ = mock_pyspark
        mock_session_class.builder.remote.side_effect = Exception("refused")

        with patch.object(mod, "SparkSession", mock_session_class):
            from benchbox.platforms.lakesail import LakeSailAdapter

            adapter = LakeSailAdapter()
            result = adapter.test_connection()

        assert result is False


# ---------------------------------------------------------------------------
# supports_tuning_type: ImportError fallback (lines 570-571)
# ---------------------------------------------------------------------------


class TestLakeSailSupportsTuningType:
    """Test supports_tuning_type() fallback."""

    def test_supports_tuning_type_import_error(self, mock_pyspark):
        """Returns False when TuningType cannot be imported."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()

        with patch.dict("sys.modules", {"benchbox.core.tuning.interface": None}):
            result = adapter.supports_tuning_type("partitioning")

        assert result is False


# ---------------------------------------------------------------------------
# generate_tuning_clause: no partition cols (lines 584-592), ImportError (589-590)
# ---------------------------------------------------------------------------


class TestLakeSailGenerateTuningClause:
    """Test generate_tuning_clause() branching."""

    def test_generate_tuning_clause_no_partition_cols(self, mock_pyspark):
        """Empty string returned when partitioning columns list is empty."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()
        mock_tuning = MagicMock()
        mock_tuning.has_any_tuning.return_value = True
        mock_tuning.get_columns_by_type.return_value = []

        clause = adapter.generate_tuning_clause(mock_tuning)
        assert clause == ""

    def test_generate_tuning_clause_import_error(self, mock_pyspark):
        """Returns empty string when TuningType import fails."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()
        mock_tuning = MagicMock()
        mock_tuning.has_any_tuning.return_value = True

        with patch.dict("sys.modules", {"benchbox.core.tuning.interface": None}):
            clause = adapter.generate_tuning_clause(mock_tuning)

        assert clause == ""


# ---------------------------------------------------------------------------
# apply_table_tunings (lines 596-598)
# ---------------------------------------------------------------------------


class TestLakeSailApplyTableTunings:
    """Test apply_table_tunings()."""

    def test_apply_table_tunings_calls_log_partition(self, mock_pyspark):
        """apply_table_tunings delegates to log_partition_tunings."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()
        mock_tuning = MagicMock()
        mock_conn = MagicMock()

        with patch("benchbox.platforms.base.tuning_utils.log_partition_tunings") as mock_log:
            adapter.apply_table_tunings(mock_tuning, mock_conn)
            mock_log.assert_called_once_with(mock_tuning, adapter.logger, "LakeSail")


# ---------------------------------------------------------------------------
# apply_unified_tuning: None config, with platform_optimizations (lines 602-611)
# ---------------------------------------------------------------------------


class TestLakeSailApplyUnifiedTuning:
    """Test apply_unified_tuning() branching."""

    def test_apply_unified_tuning_none_returns_early(self, mock_pyspark):
        """Returns immediately when unified_config is None/falsy."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()
        # Should not raise
        adapter.apply_unified_tuning(None, MagicMock())

    def test_apply_unified_tuning_calls_sub_methods(self, mock_pyspark):
        """Calls constraint configuration and per-table tuning."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()
        mock_conn = MagicMock()

        mock_config = MagicMock()
        mock_config.platform_optimizations = None  # skip platform opts
        mock_config.table_tunings = {"orders": MagicMock()}

        with (
            patch.object(adapter, "apply_constraint_configuration") as mock_constraints,
            patch.object(adapter, "apply_table_tunings") as mock_table_tunings,
        ):
            adapter.apply_unified_tuning(mock_config, mock_conn)

        mock_constraints.assert_called_once()
        mock_table_tunings.assert_called_once()

    def test_apply_unified_tuning_with_platform_optimizations(self, mock_pyspark):
        """Calls apply_platform_optimizations when config has them."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()
        mock_conn = MagicMock()
        mock_platform_opt = MagicMock()

        mock_config = MagicMock()
        mock_config.platform_optimizations = mock_platform_opt
        mock_config.table_tunings = {}

        with (
            patch.object(adapter, "apply_constraint_configuration"),
            patch.object(adapter, "apply_platform_optimizations") as mock_plat,
        ):
            adapter.apply_unified_tuning(mock_config, mock_conn)

        mock_plat.assert_called_once_with(mock_platform_opt, mock_conn)


# ---------------------------------------------------------------------------
# apply_platform_optimizations: None, spark attrs, error (lines 615-628)
# ---------------------------------------------------------------------------


class TestLakeSailApplyPlatformOptimizations:
    """Test apply_platform_optimizations() branching."""

    def test_apply_platform_opts_none_returns_early(self, mock_pyspark):
        """Returns immediately when platform_config is None."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()
        # Should not raise
        adapter.apply_platform_optimizations(None, MagicMock())

    def test_apply_platform_opts_sets_spark_conf(self, mock_pyspark):
        """Sets spark conf when platform_config.spark is populated."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_session = mock_pyspark
        adapter = LakeSailAdapter()

        mock_config = MagicMock()
        mock_config.spark = {"sql.shuffle.partitions": "400"}

        adapter.apply_platform_optimizations(mock_config, mock_session)

        mock_session.conf.set.assert_called_with("spark.sql.shuffle.partitions", "400")

    def test_apply_platform_opts_conf_error_logged(self, mock_pyspark):
        """conf.set errors are caught and logged."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_session = mock_pyspark
        mock_session.conf.set.side_effect = Exception("conf error")

        adapter = LakeSailAdapter()
        mock_config = MagicMock()
        mock_config.spark = {"bad.key": "value"}

        # Should not raise
        adapter.apply_platform_optimizations(mock_config, mock_session)

    def test_apply_platform_opts_no_spark_attr(self, mock_pyspark):
        """No conf.set calls when config has no spark attribute."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_session = mock_pyspark
        adapter = LakeSailAdapter()

        mock_config = MagicMock(spec=[])  # No spark attribute

        adapter.apply_platform_optimizations(mock_config, mock_session)
        mock_session.conf.set.assert_not_called()


# ---------------------------------------------------------------------------
# apply_constraint_configuration (lines 637-641)
# ---------------------------------------------------------------------------


class TestLakeSailApplyConstraintConfiguration:
    """Test apply_constraint_configuration() branching."""

    def test_apply_constraints_primary_key_enabled(self, mock_pyspark):
        """Logs info when primary_key_config.enabled is True."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()
        mock_pk = MagicMock()
        mock_pk.enabled = True
        mock_fk = MagicMock()
        mock_fk.enabled = False

        with patch.object(adapter.logger, "info") as mock_log:
            adapter.apply_constraint_configuration(mock_pk, mock_fk, MagicMock())

        calls = [str(c) for c in mock_log.call_args_list]
        assert any("Primary key" in c for c in calls)

    def test_apply_constraints_foreign_key_enabled(self, mock_pyspark):
        """Logs info when foreign_key_config.enabled is True."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()
        mock_pk = MagicMock()
        mock_pk.enabled = False
        mock_fk = MagicMock()
        mock_fk.enabled = True

        with patch.object(adapter.logger, "info") as mock_log:
            adapter.apply_constraint_configuration(mock_pk, mock_fk, MagicMock())

        calls = [str(c) for c in mock_log.call_args_list]
        assert any("Foreign key" in c for c in calls)

    def test_apply_constraints_none_values(self, mock_pyspark):
        """No error when both configs are None."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()
        adapter.apply_constraint_configuration(None, None, MagicMock())


# ---------------------------------------------------------------------------
# _get_existing_tables: success and exception (lines 645-650)
# ---------------------------------------------------------------------------


class TestLakeSailGetExistingTables:
    """Test _get_existing_tables() branching."""

    def test_get_existing_tables_success(self, mock_pyspark):
        """Returns list of lowercase table names."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_session = mock_pyspark
        t1, t2 = MagicMock(), MagicMock()
        t1.name = "Orders"
        t2.name = "LINEITEM"
        mock_session.catalog.listTables.return_value = [t1, t2]

        adapter = LakeSailAdapter()
        tables = adapter._get_existing_tables(mock_session)

        assert tables == ["orders", "lineitem"]

    def test_get_existing_tables_exception_returns_empty(self, mock_pyspark):
        """Returns [] when catalog.listTables raises."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_session = mock_pyspark
        mock_session.catalog.listTables.side_effect = RuntimeError("catalog error")

        adapter = LakeSailAdapter()
        tables = adapter._get_existing_tables(mock_session)

        assert tables == []


# ---------------------------------------------------------------------------
# analyze_table: exception path (lines 658-659)
# ---------------------------------------------------------------------------


class TestLakeSailAnalyzeTable:
    """Test analyze_table() exception path."""

    def test_analyze_table_exception_logged(self, mock_pyspark):
        """Exception from ANALYZE TABLE is caught and logged."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_session = mock_pyspark
        mock_session.sql.side_effect = RuntimeError("analyze failed")

        adapter = LakeSailAdapter()
        # Should not raise
        adapter.analyze_table(mock_session, "orders")


# ---------------------------------------------------------------------------
# _build_lakesail_config module-level function (lines 669-671)
# ---------------------------------------------------------------------------


class TestBuildLakeSailConfig:
    """Test _build_lakesail_config() module-level function."""

    def test_build_lakesail_config_calls_build_platform_config(self):
        """_build_lakesail_config delegates to build_platform_config."""
        from benchbox.platforms.lakesail import _build_lakesail_config

        mock_result = MagicMock()
        mock_info = MagicMock()

        with patch(
            "benchbox.platforms.base.config_utils.build_platform_config", return_value=mock_result
        ) as mock_build:
            result = _build_lakesail_config(
                platform="lakesail",
                options={"endpoint": "sc://host:50051"},
                overrides={},
                info=mock_info,
            )

        mock_build.assert_called_once()
        call_kwargs = mock_build.call_args[1]
        assert call_kwargs["platform_type"] == "lakesail"
        assert call_kwargs["credential_key"] == "lakesail"
        assert result is mock_result
