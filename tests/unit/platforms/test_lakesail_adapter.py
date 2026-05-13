"""Unit tests for LakeSail Sail platform adapter."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestLakeSailAdapter:
    """Tests for LakeSailAdapter class."""

    @pytest.fixture
    def mock_pyspark(self):
        """Mock pyspark module for LakeSail adapter tests."""
        mock_spark_session = MagicMock()
        mock_builder = MagicMock()
        mock_builder.remote.return_value = mock_builder
        mock_builder.config.return_value = mock_builder
        mock_builder.getOrCreate.return_value = mock_spark_session

        mock_spark_session.version = "3.5.0"
        mock_spark_session.catalog.listDatabases.return_value = []
        mock_spark_session.sql.return_value = MagicMock()

        mock_session_class = MagicMock()
        mock_session_class.builder = mock_builder

        with patch.dict(
            "sys.modules",
            {
                "pyspark": MagicMock(),
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
        ):
            yield mock_session_class, mock_spark_session

    def test_initialization_success(self, mock_pyspark):
        """Test successful adapter initialization."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        config = {
            "endpoint": "sc://sail-server:50051",
            "app_name": "TestApp",
            "database": "test_db",
            "driver_memory": "8g",
        }

        adapter = LakeSailAdapter(**config)

        assert adapter.platform_name == "LakeSail"
        assert adapter.endpoint == "sc://sail-server:50051"
        assert adapter.app_name == "TestApp"
        assert adapter.database == "test_db"
        assert adapter.driver_memory == "8g"

    def test_csv_compression_codecs_includes_zstd(self, mock_pyspark):
        """Sail's CSV reader accepts zstd but doesn't auto-detect from extensions."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()
        assert "zstd" in adapter._csv_compression_codecs
        assert isinstance(adapter._csv_compression_codecs, frozenset)

    def test_initialization_with_defaults(self, mock_pyspark):
        """Test initialization with default values."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()

        assert adapter.endpoint == "sc://localhost:50051"
        assert adapter.app_name == "BenchBox-LakeSail"
        assert adapter.database == "default"
        assert adapter.driver_memory == "4g"
        assert adapter.shuffle_partitions == 200
        assert adapter.adaptive_enabled is True
        assert adapter.table_format == "parquet"
        assert adapter.sail_mode == "local"
        assert adapter.sail_workers is None
        assert adapter.disable_cache is True

    def test_initialization_with_distributed_mode(self, mock_pyspark):
        """Test initialization with distributed deployment mode."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        config = {
            "endpoint": "sc://cluster-master:50051",
            "sail_mode": "distributed",
            "sail_workers": 8,
        }

        adapter = LakeSailAdapter(**config)

        assert adapter.endpoint == "sc://cluster-master:50051"
        assert adapter.sail_mode == "distributed"
        assert adapter.sail_workers == 8

    def test_get_target_dialect(self, mock_pyspark):
        """Test that target dialect returns spark."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()
        assert adapter.get_target_dialect() == "spark"

    def test_vector_search_queries_use_lakesail_compat_key(self, mock_pyspark):
        """Vector search needs LakeSail-specific skips, not generic Spark variants."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()
        benchmark = MagicMock()
        benchmark.get_queries.return_value = {}

        queries = adapter._get_dialect_queries(benchmark, "vector_search", connection=None)

        assert queries == {}
        benchmark.get_queries.assert_called_once_with(dialect="lakesail", platform_version=None)

    def test_platform_info(self, mock_pyspark):
        """Test platform info collection."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        config = {
            "endpoint": "sc://sail:50051",
            "database": "benchmark",
            "driver_memory": "16g",
            "sail_mode": "distributed",
            "sail_workers": 4,
        }

        adapter = LakeSailAdapter(**config)
        info = adapter.get_platform_info(connection=None)

        assert info["platform_type"] == "lakesail"
        assert info["platform_name"] == "LakeSail Sail"
        assert info["connection_mode"] == "distributed"
        assert info["endpoint"] == "sc://sail:50051"
        assert info["configuration"]["database"] == "benchmark"
        assert info["configuration"]["driver_memory"] == "16g"
        assert info["configuration"]["sail_mode"] == "distributed"
        assert info["configuration"]["sail_workers"] == 4

    def test_platform_info_local_mode(self, mock_pyspark):
        """Test platform info in local mode."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()
        info = adapter.get_platform_info(connection=None)

        assert info["connection_mode"] == "local"

    def test_from_config(self, mock_pyspark):
        """Test adapter creation from config."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        config = {
            "benchmark": "TPC-H",
            "scale_factor": 10.0,
            "endpoint": "sc://sail:50051",
            "driver_memory": "8g",
        }

        adapter = LakeSailAdapter.from_config(config)

        assert adapter.driver_memory == "8g"
        assert adapter.endpoint == "sc://sail:50051"
        # Database name should be auto-generated
        assert "tpch" in adapter.database.lower() or "benchmark" in adapter.database.lower()

    def test_get_spark_conf(self, mock_pyspark):
        """Test Spark Connect configuration generation."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter(
            app_name="TestApp",
            shuffle_partitions=500,
            adaptive_enabled=True,
        )

        conf = adapter._get_spark_conf()

        assert conf["spark.app.name"] == "TestApp"
        assert conf["spark.sql.shuffle.partitions"] == "500"
        assert conf["spark.sql.adaptive.enabled"] == "true"
        assert conf["spark.sql.inMemoryColumnarStorage.enabled"] == "false"

    def test_get_spark_conf_no_adaptive(self, mock_pyspark):
        """Test configuration with AQE disabled."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter(adaptive_enabled=False)

        conf = adapter._get_spark_conf()

        assert "spark.sql.adaptive.enabled" not in conf

    def test_add_cli_arguments_supports_disabling_adaptive(self, mock_pyspark):
        """CLI args should allow disabling AQE via --no-adaptive-enabled."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        parser = argparse.ArgumentParser()
        LakeSailAdapter.add_cli_arguments(parser)

        default_args = parser.parse_args([])
        disabled_args = parser.parse_args(["--no-adaptive-enabled"])

        assert default_args.adaptive_enabled is True
        assert disabled_args.adaptive_enabled is False

    def test_normalize_table_name(self, mock_pyspark):
        """Test table name normalization (delegates to shared helper)."""
        from benchbox.platforms._spark_helpers import normalize_spark_table_name_in_sql

        sql = 'CREATE TABLE "CUSTOMER" (id INT)'
        normalized = normalize_spark_table_name_in_sql(sql)

        assert "customer" in normalized.lower()

    def test_optimize_table_definition_parquet(self, mock_pyspark):
        """LakeSail uses the shared optimize_spark_table_definition helper."""
        from benchbox.platforms._spark_helpers import optimize_spark_table_definition

        sql = "CREATE TABLE orders (id INT, amount DECIMAL)"
        optimized = optimize_spark_table_definition(sql, table_format="parquet")
        assert "USING PARQUET" in optimized.upper()

    def test_optimize_table_definition_orc(self, mock_pyspark):
        """LakeSail uses the shared optimize_spark_table_definition helper."""
        from benchbox.platforms._spark_helpers import optimize_spark_table_definition

        sql = "CREATE TABLE orders (id INT, amount DECIMAL)"
        optimized = optimize_spark_table_definition(sql, table_format="orc")
        assert "USING ORC" in optimized.upper()

    def test_validate_identifier(self, mock_pyspark):
        """Test SQL identifier validation (delegates to shared helper)."""
        from benchbox.platforms._spark_helpers import validate_spark_identifier

        # Valid identifiers
        assert validate_spark_identifier("my_table") is True
        assert validate_spark_identifier("_private") is True
        assert validate_spark_identifier("Table123") is True

        # Invalid identifiers
        assert validate_spark_identifier("") is False
        assert validate_spark_identifier("123table") is False
        assert validate_spark_identifier("table-name") is False
        assert validate_spark_identifier("table; DROP TABLE users") is False

    def test_supports_tuning_type(self, mock_pyspark):
        """Test tuning type support."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()

        try:
            from benchbox.core.tuning.interface import TuningType

            assert adapter.supports_tuning_type(TuningType.PARTITIONING) is True
            assert adapter.supports_tuning_type(TuningType.SORTING) is True
            assert adapter.supports_tuning_type(TuningType.CLUSTERING) is False
        except ImportError:
            pass

    def test_extract_table_name(self, mock_pyspark):
        """Test extracting table name from CREATE TABLE (shared helper)."""
        from benchbox.platforms._spark_helpers import extract_spark_table_name

        assert extract_spark_table_name("CREATE TABLE orders (id INT)") == "orders"
        assert extract_spark_table_name("CREATE TABLE IF NOT EXISTS lineitem (id INT)") == "lineitem"

    def test_create_connection_initializes_session_before_existing_db_handling(self, mock_pyspark):
        """Existing-database handling should run after Spark session is available."""
        import benchbox.platforms.lakesail as lakesail_module
        from benchbox.platforms.lakesail import LakeSailAdapter

        mock_session_class, mock_spark_session = mock_pyspark
        with patch.object(lakesail_module, "SparkSession", mock_session_class):
            adapter = LakeSailAdapter(database="test_db")

            def _assert_session_ready(**_kwargs):
                assert adapter._spark_session is mock_spark_session

            with (
                patch.object(adapter, "_ensure_server_ready"),
                patch.object(adapter, "handle_existing_database", side_effect=_assert_session_ready) as mocked_handle,
            ):
                connection = adapter.create_connection()

            assert connection is mock_spark_session
            mocked_handle.assert_called_once()


class TestLakeSailAdapterExecution:
    """Tests for LakeSail query execution and connection lifecycle."""

    @pytest.fixture
    def mock_pyspark(self):
        """Mock pyspark module."""
        mock_spark_session = MagicMock()
        mock_builder = MagicMock()
        mock_builder.remote.return_value = mock_builder
        mock_builder.config.return_value = mock_builder
        mock_builder.getOrCreate.return_value = mock_spark_session

        mock_spark_session.version = "3.5.0"
        mock_spark_session.catalog.listDatabases.return_value = []
        mock_spark_session.sql.return_value = MagicMock()

        mock_session_class = MagicMock()
        mock_session_class.builder = mock_builder

        with patch.dict(
            "sys.modules",
            {
                "pyspark": MagicMock(),
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
        ):
            yield mock_session_class, mock_spark_session

    def test_execute_query_success(self, mock_pyspark):
        """Test successful query execution."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_spark_session = mock_pyspark

        mock_df = MagicMock()
        mock_df.collect.return_value = [(1, "test"), (2, "test2")]
        mock_df.count.return_value = 2
        mock_spark_session.sql.return_value = mock_df

        adapter = LakeSailAdapter()

        result = adapter.execute_query(mock_spark_session, "SELECT * FROM test", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 2

    def test_execute_query_disable_cache_skips_unsupported_clear_cache(self, mock_pyspark):
        """LakeSail must not call clearCache() even when disable_cache=True."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_spark_session = mock_pyspark

        mock_df = MagicMock()
        mock_df.collect.return_value = [(1,)]
        mock_spark_session.sql.return_value = mock_df

        adapter = LakeSailAdapter(disable_cache=True)

        result = adapter.execute_query(mock_spark_session, "SELECT 1", "q1")

        assert result["status"] == "SUCCESS"
        mock_spark_session.catalog.clearCache.assert_not_called()

    def test_execute_query_failure(self, mock_pyspark):
        """Test query execution failure."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_spark_session = mock_pyspark
        mock_spark_session.sql.side_effect = Exception("Query failed")

        adapter = LakeSailAdapter()

        result = adapter.execute_query(mock_spark_session, "INVALID SQL", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "FAILED"
        assert "Query failed" in result.get("error", "")

    def test_close_connection(self, mock_pyspark):
        """Test connection (SparkSession) closing."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_spark_session = mock_pyspark

        adapter = LakeSailAdapter()
        adapter.close_connection(mock_spark_session)

        mock_spark_session.stop.assert_called_once()

    def test_close_connection_handles_none(self, mock_pyspark):
        """Test connection closing handles None gracefully."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()

        # Should not raise
        adapter.close_connection(None)

    def test_configure_for_benchmark_olap(self, mock_pyspark):
        """Test OLAP benchmark configuration."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_spark_session = mock_pyspark

        adapter = LakeSailAdapter()

        # Should not raise
        adapter.configure_for_benchmark(mock_spark_session, "olap")

    def test_get_query_plan(self, mock_pyspark):
        """Test query plan retrieval."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_spark_session = mock_pyspark

        mock_df = MagicMock()
        mock_df.collect.return_value = [("== Physical Plan ==\nScan",)]
        mock_spark_session.sql.return_value = mock_df

        adapter = LakeSailAdapter()

        plan = adapter.get_query_plan(mock_spark_session, "SELECT * FROM test")
        assert isinstance(plan, str)

    def test_analyze_table(self, mock_pyspark):
        """Test table analysis for query optimization."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_spark_session = mock_pyspark

        adapter = LakeSailAdapter(database="test_db")

        # Should not raise
        adapter.analyze_table(mock_spark_session, "orders")

    def test_generate_tuning_clause_partitioning(self, mock_pyspark):
        """Test tuning clause generation with partitioning."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()

        mock_col = MagicMock()
        mock_col.name = "date_col"
        mock_col.order = 1

        mock_tuning = MagicMock()
        mock_tuning.has_any_tuning.return_value = True
        mock_tuning.table_name = "orders"

        with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
            mock_tuning_type.PARTITIONING = "partitioning"
            mock_tuning_type.SORTING = "sorting"
            mock_tuning.get_columns_by_type.side_effect = lambda t: (
                [mock_col] if t == mock_tuning_type.PARTITIONING else []
            )

            clause = adapter.generate_tuning_clause(mock_tuning)
            assert "PARTITIONED BY" in clause
            assert "date_col" in clause

    def test_generate_tuning_clause_empty(self, mock_pyspark):
        """Test tuning clause generation with no tuning."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()

        mock_tuning = MagicMock()
        mock_tuning.has_any_tuning.return_value = False

        clause = adapter.generate_tuning_clause(mock_tuning)
        assert clause == ""


class TestLakeSailAdapterRegistration:
    """Tests for platform registration."""

    def test_lakesail_in_platform_list(self):
        """Test that LakeSail is listed in available platforms."""
        from benchbox.platforms import list_available_platforms

        platforms = list_available_platforms()
        assert "lakesail" in platforms

    def test_lakesail_requirements(self):
        """Test that LakeSail requirements are correct."""
        from benchbox.platforms import get_platform_requirements

        requirements = get_platform_requirements("lakesail")
        assert "pyspark" in requirements

    def test_lakesail_dependency_group(self):
        """Test that LakeSail dependency group is defined."""
        from benchbox.utils.dependencies import DEPENDENCY_GROUPS

        assert "lakesail" in DEPENDENCY_GROUPS
        lakesail_deps = DEPENDENCY_GROUPS["lakesail"]
        assert "pyspark" in lakesail_deps.packages

    def test_lakesail_df_is_dataframe_platform(self):
        """Test that lakesail-df is recognized as a DataFrame platform."""
        from benchbox.platforms import is_dataframe_platform

        assert is_dataframe_platform("lakesail-df") is True

    def test_lakesail_platform_info_from_registry(self):
        """Test that LakeSail platform info is accessible from registry."""
        from benchbox.core.platform_registry import PlatformRegistry

        info = PlatformRegistry.get_platform_info("lakesail")
        assert info is not None
        assert info.display_name == "LakeSail Sail"


class TestLakeSailIdentifierValidation:
    """Tests for SQL injection prevention via identifier validation."""

    @pytest.fixture
    def mock_pyspark(self):
        """Mock pyspark module for LakeSail adapter tests."""
        mock_spark_session = MagicMock()
        mock_builder = MagicMock()
        mock_builder.remote.return_value = mock_builder
        mock_builder.config.return_value = mock_builder
        mock_builder.getOrCreate.return_value = mock_spark_session

        mock_spark_session.version = "3.5.0"
        mock_spark_session.catalog.listDatabases.return_value = []
        mock_spark_session.sql.return_value = MagicMock()

        mock_session_class = MagicMock()
        mock_session_class.builder = mock_builder

        with patch.dict(
            "sys.modules",
            {
                "pyspark": MagicMock(),
                "pyspark.sql": MagicMock(SparkSession=mock_session_class),
                "pyspark.sql.types": MagicMock(),
            },
        ):
            yield mock_session_class, mock_spark_session

    def test_create_connection_rejects_invalid_database(self, mock_pyspark):
        """create_connection should reject databases with SQL injection characters."""
        import benchbox.platforms.lakesail as lakesail_module
        from benchbox.platforms.lakesail import LakeSailAdapter

        mock_session_class, _mock_spark_session = mock_pyspark
        with patch.object(lakesail_module, "SparkSession", mock_session_class):
            adapter = LakeSailAdapter(database="valid_db")

            with (
                patch.object(adapter, "_ensure_server_ready"),
                patch.object(adapter, "handle_existing_database"),
                pytest.raises(ValueError, match="Invalid database identifier"),
            ):
                adapter.create_connection(database="DROP TABLE; --")

    def test_normalize_table_name_preserves_if_not_exists(self, mock_pyspark):
        """_normalize_table_name_in_sql should preserve IF NOT EXISTS clause."""
        from benchbox.platforms._spark_helpers import normalize_spark_table_name_in_sql
        from benchbox.platforms.lakesail import LakeSailAdapter

        result = normalize_spark_table_name_in_sql("CREATE TABLE IF NOT EXISTS LINEITEM (id INT)")

        assert "IF NOT EXISTS" in result
        assert "lineitem" in result

    def test_normalize_table_name_works_without_if_not_exists(self, mock_pyspark):
        """normalize_spark_table_name_in_sql should work when IF NOT EXISTS is absent."""
        from benchbox.platforms._spark_helpers import normalize_spark_table_name_in_sql

        result = normalize_spark_table_name_in_sql("CREATE TABLE ORDERS (id INT)")

        assert "orders" in result
        assert "IF NOT EXISTS" not in result


class TestLakeSailServerLifecycle:
    """Tests for server readiness, auto-start, and cleanup methods."""

    @pytest.fixture
    def mock_pyspark(self):
        """Mock pyspark module for LakeSail adapter tests."""
        mock_spark_session = MagicMock()
        mock_builder = MagicMock()
        mock_builder.remote.return_value = mock_builder
        mock_builder.config.return_value = mock_builder
        mock_builder.getOrCreate.return_value = mock_spark_session

        mock_spark_session.version = "3.5.0"
        mock_spark_session.catalog.listDatabases.return_value = []
        mock_spark_session.sql.return_value = MagicMock()

        mock_session_class = MagicMock()
        mock_session_class.builder = mock_builder

        with patch.dict(
            "sys.modules",
            {
                "pyspark": MagicMock(),
                "pyspark.sql": MagicMock(SparkSession=mock_session_class),
                "pyspark.sql.types": MagicMock(),
            },
        ):
            yield mock_session_class, mock_spark_session

    # --- parse_spark_connect_endpoint (shared helper) ---

    def test_parse_endpoint_standard(self, mock_pyspark):
        """Parse standard sc://host:port endpoint."""
        from benchbox.platforms._spark_helpers import parse_spark_connect_endpoint

        assert parse_spark_connect_endpoint("sc://myhost:9999") == ("myhost", 9999)

    def test_parse_endpoint_default_port(self, mock_pyspark):
        """Default port 50051 when no port in endpoint."""
        from benchbox.platforms._spark_helpers import parse_spark_connect_endpoint

        assert parse_spark_connect_endpoint("sc://myhost") == ("myhost", 50051)

    def test_parse_endpoint_no_scheme(self, mock_pyspark):
        """Handle endpoint without sc:// prefix."""
        from benchbox.platforms._spark_helpers import parse_spark_connect_endpoint

        assert parse_spark_connect_endpoint("myhost:8080") == ("myhost", 8080)

    def test_parse_endpoint_invalid_port(self, mock_pyspark):
        """Invalid port string falls back to 50051."""
        from benchbox.platforms._spark_helpers import parse_spark_connect_endpoint

        assert parse_spark_connect_endpoint("sc://myhost:notaport") == ("myhost", 50051)

    def test_parse_endpoint_empty_host(self, mock_pyspark):
        """Empty host defaults to localhost."""
        from benchbox.platforms._spark_helpers import parse_spark_connect_endpoint

        assert parse_spark_connect_endpoint("sc://:50051") == ("localhost", 50051)

    # --- is_spark_connect_reachable (shared helper) ---

    def test_is_server_reachable_true(self, mock_pyspark):
        """Returns True when socket connects."""
        from benchbox.platforms._spark_helpers import is_spark_connect_reachable

        with patch("benchbox.platforms._spark_helpers.socket.create_connection"):
            assert is_spark_connect_reachable("sc://localhost:50051") is True

    def test_is_server_reachable_false(self, mock_pyspark):
        """Returns False when socket fails."""
        from benchbox.platforms._spark_helpers import is_spark_connect_reachable

        with patch(
            "benchbox.platforms._spark_helpers.socket.create_connection",
            side_effect=OSError("refused"),
        ):
            assert is_spark_connect_reachable("sc://localhost:50051") is False

    # --- _ensure_server_ready ---

    def test_ensure_server_ready_already_reachable(self, mock_pyspark):
        """No-op when server is already reachable."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()
        with patch("benchbox.platforms.lakesail.is_spark_connect_reachable", return_value=True):
            adapter._ensure_server_ready()  # should not raise

    def test_ensure_server_ready_distributed_unreachable(self, mock_pyspark):
        """Raises RuntimeError immediately for unreachable distributed server."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter(sail_mode="distributed", endpoint="sc://cluster:50051")
        with patch("benchbox.platforms.lakesail.is_spark_connect_reachable", return_value=False):
            with pytest.raises(RuntimeError, match="Cannot connect to LakeSail Sail server"):
                adapter._ensure_server_ready()

    def test_ensure_server_ready_local_no_pysail(self, mock_pyspark):
        """Raises RuntimeError with install instructions when pysail is missing."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter(sail_mode="local")
        with (
            patch("benchbox.platforms.lakesail.is_spark_connect_reachable", return_value=False),
            patch.dict("sys.modules", {"pysail": None}),
            pytest.raises(RuntimeError, match="pysail.*not installed"),
        ):
            adapter._ensure_server_ready()

    def test_ensure_server_ready_local_auto_starts(self, mock_pyspark):
        """Delegates to _auto_start_local_server when pysail is available."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter(sail_mode="local")
        with (
            patch("benchbox.platforms.lakesail.is_spark_connect_reachable", return_value=False),
            patch.dict("sys.modules", {"pysail": MagicMock()}),
            patch.object(adapter, "_auto_start_local_server") as mock_auto,
        ):
            adapter._ensure_server_ready()
            mock_auto.assert_called_once()

    # --- _auto_start_local_server ---

    def test_auto_start_server_success(self, mock_pyspark):
        """Successful auto-start: process stays running, server becomes reachable."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # process still running

        reachable_calls = iter([False, True])

        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch(
                "benchbox.platforms.lakesail.is_spark_connect_reachable",
                side_effect=reachable_calls,
            ),
            patch("atexit.register"),
        ):
            adapter._auto_start_local_server()

        assert adapter._managed_server_process is mock_proc

    def test_auto_start_server_process_crashes(self, mock_pyspark):
        """Raises RuntimeError with stderr when pysail exits immediately."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # exited with error
        mock_proc.returncode = 1
        mock_proc.stderr.read.return_value = b"Address already in use"

        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("atexit.register"),
            pytest.raises(RuntimeError, match="exited immediately.*Address already in use"),
        ):
            adapter._auto_start_local_server()

    def test_auto_start_server_timeout(self, mock_pyspark):
        """Raises RuntimeError with stderr after 10s timeout, terminates process."""
        import time

        from benchbox.platforms.lakesail import LakeSailAdapter

        adapter = LakeSailAdapter()

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # still running
        mock_proc.stderr.read.return_value = b"some debug output"

        # Make time.monotonic advance past deadline immediately
        start = 1000.0
        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("benchbox.platforms.lakesail.is_spark_connect_reachable", return_value=False),
            patch("time.monotonic", side_effect=[start, start, start + 11]),
            patch("time.sleep"),
            patch("atexit.register"),
            pytest.raises(RuntimeError, match=r"(?s)did not become ready.*some debug output"),
        ):
            adapter._auto_start_local_server()

        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=5)

    # --- close_connection: managed server cleanup ---

    def test_close_connection_stops_managed_server(self, mock_pyspark):
        """close_connection terminates and waits on managed server process."""
        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_spark_session = mock_pyspark
        adapter = LakeSailAdapter()

        mock_proc = MagicMock()
        adapter._managed_server_process = mock_proc
        cleanup_fn = MagicMock()
        adapter._managed_server_atexit = cleanup_fn

        with patch("atexit.unregister") as mock_unregister:
            adapter.close_connection(mock_spark_session)

        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=5)
        assert adapter._managed_server_process is None
        mock_unregister.assert_called_once_with(cleanup_fn)

    def test_close_connection_kills_on_timeout(self, mock_pyspark):
        """close_connection escalates to kill if terminate+wait times out."""
        import subprocess

        from benchbox.platforms.lakesail import LakeSailAdapter

        _, mock_spark_session = mock_pyspark
        adapter = LakeSailAdapter()

        mock_proc = MagicMock()
        mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="pysail", timeout=5)
        adapter._managed_server_process = mock_proc

        adapter.close_connection(mock_spark_session)

        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()
        assert adapter._managed_server_process is None
