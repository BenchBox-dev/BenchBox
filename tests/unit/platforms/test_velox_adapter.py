"""Unit tests for the VeloxAdapter (Apache Gluten + Velox)."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestVeloxAdapterInit:
    """Initialization and default values."""

    @pytest.fixture
    def mock_pyspark(self):
        """Mock pyspark so tests run without the real library."""
        mock_spark_session = MagicMock()
        mock_builder = MagicMock()
        mock_builder.master.return_value = mock_builder
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
                ),
            },
        ):
            yield mock_session_class, mock_spark_session

    def test_platform_name(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        assert VeloxAdapter().platform_name == "Velox"

    def test_defaults(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        adapter = VeloxAdapter()
        assert adapter.deployment == "local"
        assert adapter.endpoint == "sc://localhost:50051"
        assert adapter.gluten_jar_path == ""
        assert adapter.gluten_version == "1.6.0"
        assert adapter.offheap_size == "8g"
        assert adapter.app_name == "BenchBox-Velox"
        assert adapter.database == "default"
        assert adapter.driver_memory == "4g"
        assert adapter.shuffle_partitions == 200
        assert adapter.adaptive_enabled is True
        assert adapter.table_format == "parquet"
        assert adapter.disable_cache is True

    def test_custom_config(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        adapter = VeloxAdapter(
            deployment="remote",
            endpoint="sc://myserver:50051",
            gluten_jar_path="/opt/gluten.jar",
            gluten_version="1.4.1",
            offheap_size="16g",
            app_name="MyApp",
            database="bench",
            driver_memory="8g",
            shuffle_partitions=400,
            adaptive_enabled=False,
            table_format="orc",
            disable_cache=False,
        )
        assert adapter.deployment == "remote"
        assert adapter.endpoint == "sc://myserver:50051"
        assert adapter.gluten_jar_path == "/opt/gluten.jar"
        assert adapter.gluten_version == "1.4.1"
        assert adapter.offheap_size == "16g"
        assert adapter.app_name == "MyApp"
        assert adapter.database == "bench"
        assert adapter.driver_memory == "8g"
        assert adapter.shuffle_partitions == 400
        assert adapter.adaptive_enabled is False
        assert adapter.table_format == "orc"
        assert adapter.disable_cache is False

    def test_deployment_mode_alias(self, mock_pyspark):
        """deployment_mode key (from platform factory) maps to deployment."""
        from benchbox.platforms.velox import VeloxAdapter

        adapter = VeloxAdapter(deployment_mode="remote")
        assert adapter.deployment == "remote"

    def test_get_target_dialect(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        assert VeloxAdapter().get_target_dialect() == "spark"


class TestVeloxSparkConf:
    """_get_spark_conf() correctness."""

    @pytest.fixture
    def mock_pyspark(self):
        with patch.dict(
            "sys.modules",
            {
                "pyspark": MagicMock(),
                "pyspark.sql": MagicMock(SparkSession=MagicMock()),
                "pyspark.sql.types": MagicMock(),
            },
        ):
            yield

    def test_local_mode_includes_gluten_conf(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        adapter = VeloxAdapter(
            deployment="local",
            gluten_jar_path="/opt/gluten.jar",
            offheap_size="12g",
        )
        conf = adapter._get_spark_conf()

        assert conf["spark.plugins"] == "org.apache.gluten.GlutenPlugin"
        assert conf["spark.memory.offHeap.enabled"] == "true"
        assert conf["spark.memory.offHeap.size"] == "12g"
        assert conf["spark.shuffle.manager"] == "org.apache.spark.shuffle.sort.ColumnarShuffleManager"
        assert conf["spark.jars"] == "/opt/gluten.jar"
        # extraClassPath entries are required for plugin-class loading: the
        # GlutenPlugin is instantiated by SparkContext.initializeSparkContext
        # *before* spark.jars promotions reach the executor classpath, so the
        # plugin silently no-ops without these entries.  Mirrors the docker
        # entrypoint server-side config.
        assert conf["spark.driver.extraClassPath"] == "/opt/gluten.jar"
        assert conf["spark.executor.extraClassPath"] == "/opt/gluten.jar"

    def test_remote_mode_excludes_gluten_conf(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        adapter = VeloxAdapter(deployment="remote", endpoint="sc://remote:50051")
        conf = adapter._get_spark_conf()

        assert "spark.plugins" not in conf
        assert "spark.memory.offHeap.enabled" not in conf
        assert "spark.shuffle.manager" not in conf

    def test_aqe_enabled_by_default(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        conf = VeloxAdapter()._get_spark_conf()
        assert conf["spark.sql.adaptive.enabled"] == "true"
        assert conf["spark.sql.adaptive.coalescePartitions.enabled"] == "true"

    def test_aqe_disabled(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        conf = VeloxAdapter(adaptive_enabled=False)._get_spark_conf()
        assert "spark.sql.adaptive.enabled" not in conf

    def test_cache_disabled_by_default(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        conf = VeloxAdapter()._get_spark_conf()
        assert conf["spark.sql.inMemoryColumnarStorage.enabled"] == "false"

    def test_spark_config_overrides_merged(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        adapter = VeloxAdapter(spark_config={"spark.foo.bar": "baz"})
        conf = adapter._get_spark_conf()
        assert conf["spark.foo.bar"] == "baz"

    def test_columnar_shuffle_override_rejected_in_local_mode(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        adapter = VeloxAdapter(
            deployment="local",
            gluten_jar_path="/opt/gluten.jar",
            spark_config={"spark.shuffle.manager": "org.apache.spark.shuffle.sort.SortShuffleManager"},
        )
        with pytest.raises(ValueError, match="ColumnarShuffleManager"):
            adapter._get_spark_conf()


class TestVeloxLocalModeValidation:
    """Local mode validates jar path before session creation."""

    @pytest.fixture
    def mock_pyspark(self):
        with patch.dict(
            "sys.modules",
            {
                "pyspark": MagicMock(),
                "pyspark.sql": MagicMock(SparkSession=MagicMock()),
                "pyspark.sql.types": MagicMock(),
            },
        ):
            yield

    def test_missing_jar_path_raises(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        adapter = VeloxAdapter(deployment="local", gluten_jar_path="")
        with pytest.raises(ValueError, match="gluten_jar_path is required"):
            adapter._create_spark_session()

    def test_nonexistent_jar_raises(self, mock_pyspark, tmp_path):
        from benchbox.platforms.velox import VeloxAdapter

        adapter = VeloxAdapter(
            deployment="local",
            gluten_jar_path=str(tmp_path / "nonexistent.jar"),
        )
        with pytest.raises(ValueError, match="Gluten jar not found"):
            adapter._create_spark_session()

    def test_valid_jar_path_proceeds(self, mock_pyspark, tmp_path):
        import benchbox.platforms.velox as velox_module
        from benchbox.platforms.velox import VeloxAdapter

        jar = tmp_path / "gluten.jar"
        jar.write_bytes(b"fake-jar")

        mock_session_class = MagicMock()
        mock_builder = MagicMock()
        mock_builder.master.return_value = mock_builder
        mock_builder.config.return_value = mock_builder
        mock_builder.getOrCreate.return_value = MagicMock()
        mock_session_class.builder = mock_builder

        adapter = VeloxAdapter(deployment="local", gluten_jar_path=str(jar))
        with patch.object(velox_module, "SparkSession", mock_session_class):
            session = adapter._create_spark_session()
        assert session is not None
        mock_builder.master.assert_called_once_with("local[*]")


class TestVeloxRemoteMode:
    """Remote mode parses endpoints and probes server reachability."""

    @pytest.fixture
    def mock_pyspark(self):
        with patch.dict(
            "sys.modules",
            {
                "pyspark": MagicMock(),
                "pyspark.sql": MagicMock(SparkSession=MagicMock()),
                "pyspark.sql.types": MagicMock(),
            },
        ):
            yield

    def test_parse_endpoint_default(self, mock_pyspark):
        from benchbox.platforms._spark_helpers import parse_spark_connect_endpoint
        from benchbox.platforms.velox import VeloxAdapter

        adapter = VeloxAdapter(deployment="remote")
        host, port = parse_spark_connect_endpoint(adapter.endpoint)
        assert host == "localhost"
        assert port == 50051

    def test_parse_endpoint_custom(self, mock_pyspark):
        from benchbox.platforms._spark_helpers import parse_spark_connect_endpoint
        from benchbox.platforms.velox import VeloxAdapter

        adapter = VeloxAdapter(deployment="remote", endpoint="sc://myhost:12345")
        host, port = parse_spark_connect_endpoint(adapter.endpoint)
        assert host == "myhost"
        assert port == 12345

    def test_ensure_server_ready_raises_when_unreachable(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        adapter = VeloxAdapter(deployment="remote", endpoint="sc://unreachable-host:50051")
        with patch("benchbox.platforms.velox.is_spark_connect_reachable", return_value=False):
            with pytest.raises(RuntimeError, match="Cannot connect"):
                adapter._ensure_server_ready()

    def test_ensure_server_ready_passes_when_reachable(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        adapter = VeloxAdapter(deployment="remote")
        with patch("benchbox.platforms.velox.is_spark_connect_reachable", return_value=True):
            adapter._ensure_server_ready()  # should not raise


class TestVeloxPlatformInfo:
    """get_platform_info() returns expected fields."""

    @pytest.fixture
    def mock_pyspark(self):
        with patch.dict(
            "sys.modules",
            {
                "pyspark": MagicMock(__version__="3.5.0"),
                "pyspark.sql": MagicMock(SparkSession=MagicMock()),
                "pyspark.sql.types": MagicMock(),
            },
        ):
            yield

    def test_platform_info_no_connection(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        adapter = VeloxAdapter(gluten_version="1.6.0", offheap_size="8g")
        info = adapter.get_platform_info(connection=None)

        assert info["platform_type"] == "velox"
        assert info["platform_name"] == "Apache Gluten + Velox"
        assert info["gluten_version"] == "1.6.0"
        assert info["offheap_size"] == "8g"
        assert info["velox_active"] is None
        assert info["platform_version"] is None

    def test_platform_info_remote_has_endpoint(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        adapter = VeloxAdapter(deployment="remote", endpoint="sc://host:50051")
        info = adapter.get_platform_info(connection=None)

        assert info["deployment"] == "remote"
        assert info["endpoint"] == "sc://host:50051"

    def test_platform_info_local_has_jar_name(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        adapter = VeloxAdapter(deployment="local", gluten_jar_path="/opt/gluten-velox-1.6.0.jar")
        info = adapter.get_platform_info(connection=None)

        assert info["deployment"] == "local"
        assert "gluten-velox-1.6.0.jar" in info["gluten_jar"]
        assert "/opt/" not in info["gluten_jar"]  # path redacted

    def test_velox_active_probe_detects_velox_nodes(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        mock_spark = MagicMock()
        mock_spark.version = "3.5.0"
        mock_df = MagicMock()
        mock_df.collect.return_value = [("VeloxColumnarToRow\nScan",)]
        mock_spark.sql.return_value = mock_df

        adapter = VeloxAdapter()
        info = adapter.get_platform_info(connection=mock_spark)

        assert info["velox_active"] is True

    def test_velox_active_probe_false_without_velox_nodes(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        mock_spark = MagicMock()
        mock_spark.version = "3.5.0"
        mock_df = MagicMock()
        mock_df.collect.return_value = [("HashAggregate\nFileScan",)]
        mock_spark.sql.return_value = mock_df

        adapter = VeloxAdapter()
        info = adapter.get_platform_info(connection=mock_spark)

        assert info["velox_active"] is False


class TestVeloxQueryPlan:
    """get_query_plan() annotates Velox vs JVM-fallback nodes."""

    @pytest.fixture
    def mock_pyspark(self):
        with patch.dict(
            "sys.modules",
            {
                "pyspark": MagicMock(),
                "pyspark.sql": MagicMock(SparkSession=MagicMock()),
                "pyspark.sql.types": MagicMock(),
            },
        ):
            yield

    def test_velox_native_annotation(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        mock_spark = MagicMock()
        mock_df = MagicMock()
        mock_df.collect.return_value = [("VeloxColumnarToRow\nVeloxColumnarHashAggregate",)]
        mock_spark.sql.return_value = mock_df

        adapter = VeloxAdapter()
        plan = adapter.get_query_plan(mock_spark, "SELECT count(*) FROM t")

        assert "Velox native execution: YES" in plan
        # VeloxColumnarToRow is the native materialization node, NOT a fallback -
        # annotation must not false-positive when only Velox nodes are present.
        assert "JVM fallback: DETECTED" not in plan

    def test_fallback_annotation(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        mock_spark = MagicMock()
        mock_df = MagicMock()
        # A real fallback plan has a bare ColumnarToRow (without Velox prefix)
        # sitting between a JVM-side operator and a Velox transformer.
        mock_df.collect.return_value = [("VeloxColumnarHashAggregate\nColumnarToRow\nHashAgg",)]
        mock_spark.sql.return_value = mock_df

        adapter = VeloxAdapter()
        plan = adapter.get_query_plan(mock_spark, "SELECT count(*) FROM t")

        assert "JVM fallback: DETECTED" in plan

    def test_row_to_columnar_is_fallback(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        mock_spark = MagicMock()
        mock_df = MagicMock()
        mock_df.collect.return_value = [("VeloxColumnarHashAggregate\nRowToColumnar\nScan",)]
        mock_spark.sql.return_value = mock_df

        adapter = VeloxAdapter()
        plan = adapter.get_query_plan(mock_spark, "SELECT count(*) FROM t")

        assert "JVM fallback: DETECTED" in plan

    def test_no_velox_annotation(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        mock_spark = MagicMock()
        mock_df = MagicMock()
        mock_df.collect.return_value = [("HashAggregate\nFileScan",)]
        mock_spark.sql.return_value = mock_df

        adapter = VeloxAdapter()
        plan = adapter.get_query_plan(mock_spark, "SELECT count(*) FROM t")

        assert "NOT DETECTED" in plan


class TestVeloxFromConfig:
    """from_config() builds the adapter correctly."""

    @pytest.fixture
    def mock_pyspark(self):
        with patch.dict(
            "sys.modules",
            {
                "pyspark": MagicMock(),
                "pyspark.sql": MagicMock(SparkSession=MagicMock()),
                "pyspark.sql.types": MagicMock(),
            },
        ):
            yield

    def test_from_config_basic(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        config = {
            "benchmark": "tpch",
            "scale_factor": 1.0,
            "gluten_jar_path": "/opt/gluten.jar",
            "offheap_size": "16g",
        }
        adapter = VeloxAdapter.from_config(config)

        assert adapter.gluten_jar_path == "/opt/gluten.jar"
        assert adapter.offheap_size == "16g"
        assert "tpch" in adapter.database.lower() or adapter.database

    def test_from_config_explicit_database(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        config = {
            "benchmark": "tpch",
            "scale_factor": 1.0,
            "database": "my_db",
        }
        adapter = VeloxAdapter.from_config(config)
        assert adapter.database == "my_db"

    def test_from_config_remote_deployment(self, mock_pyspark):
        from benchbox.platforms.velox import VeloxAdapter

        config = {
            "benchmark": "tpch",
            "scale_factor": 1.0,
            "deployment": "remote",
            "endpoint": "sc://velox-server:50051",
        }
        adapter = VeloxAdapter.from_config(config)
        assert adapter.deployment == "remote"
        assert adapter.endpoint == "sc://velox-server:50051"


class TestVeloxCLIArguments:
    """Velox configuration flows through PlatformHookRegistry option specs.

    The adapter's add_cli_arguments() is intentionally a no-op (the abstract
    method is satisfied with an empty body). Argparse-level flags would be a
    second source of truth that drifts from the option-spec registry, so we
    just verify the no-op contract here.
    """

    def test_add_cli_arguments_is_noop(self):
        from benchbox.platforms.velox import VeloxAdapter

        parser = argparse.ArgumentParser()
        VeloxAdapter.add_cli_arguments(parser)
        # The parser should have no velox-specific args registered.
        actions = [a for a in parser._actions if a.dest != "help"]
        assert actions == []

    def test_option_specs_registered(self):
        from benchbox.cli.platform_hooks import PlatformHookRegistry

        specs = PlatformHookRegistry.list_option_specs("velox")
        # Sanity: the option-spec registry is the single source of truth and
        # carries the flags Velox cares about.
        for name in (
            "deployment",
            "endpoint",
            "gluten_jar_path",
            "offheap_size",
            "driver_memory",
            "shuffle_partitions",
            "adaptive_enabled",
        ):
            assert name in specs, f"Velox option-spec '{name}' is missing"
        assert specs["deployment"].choices == ("local", "remote")


class TestVeloxIdentifierValidation:
    """Identifier validation lives in benchbox.platforms._spark_helpers and is
    shared with the Spark and LakeSail adapters. This test pins the contract
    Velox depends on - dedicated coverage of the helper itself lives alongside
    the helper module."""

    def test_valid_identifiers(self):
        from benchbox.platforms._spark_helpers import validate_spark_identifier

        assert validate_spark_identifier("my_table") is True
        assert validate_spark_identifier("_priv") is True
        assert validate_spark_identifier("T123") is True

    def test_invalid_identifiers(self):
        from benchbox.platforms._spark_helpers import validate_spark_identifier

        assert validate_spark_identifier("") is False
        assert validate_spark_identifier("123bad") is False
        assert validate_spark_identifier("a-b") is False
        assert validate_spark_identifier("a; DROP TABLE t") is False


class TestVeloxTuning:
    """Tuning support mirrors LakeSail (partitioning + sorting only)."""

    @pytest.fixture
    def mock_pyspark(self):
        with patch.dict(
            "sys.modules",
            {
                "pyspark": MagicMock(),
                "pyspark.sql": MagicMock(SparkSession=MagicMock()),
                "pyspark.sql.types": MagicMock(),
            },
        ):
            yield

    def test_supports_partitioning_only(self, mock_pyspark):
        """Plain Parquet/ORC tables have no DDL sort key - only PARTITIONING is supported."""
        from benchbox.platforms.velox import VeloxAdapter

        adapter = VeloxAdapter()
        try:
            from benchbox.core.tuning.interface import TuningType

            assert adapter.supports_tuning_type(TuningType.PARTITIONING) is True
            assert adapter.supports_tuning_type(TuningType.SORTING) is False
            assert adapter.supports_tuning_type(TuningType.CLUSTERING) is False
        except ImportError:
            pytest.skip("TuningType not available")


class TestVeloxTableOptimization:
    """Velox uses the shared optimize_spark_table_definition helper.

    Comprehensive tests for the helper itself (V1 constraint stripping,
    SMALLINT upcast, V2 preservation) live in test_spark_helpers.py.
    These tests pin the contract Velox depends on - parquet/orc V1 mode,
    no overrides.
    """

    def test_parquet_format(self):
        from benchbox.platforms._spark_helpers import optimize_spark_table_definition

        result = optimize_spark_table_definition("CREATE TABLE orders (id INT)", table_format="parquet")
        assert "USING PARQUET" in result.upper()

    def test_orc_format(self):
        from benchbox.platforms._spark_helpers import optimize_spark_table_definition

        result = optimize_spark_table_definition("CREATE TABLE orders (id INT)", table_format="orc")
        assert "USING ORC" in result.upper()

    def test_non_create_table_unchanged(self):
        from benchbox.platforms._spark_helpers import optimize_spark_table_definition

        sql = "SELECT * FROM orders"
        assert optimize_spark_table_definition(sql, table_format="parquet") == sql


class TestVeloxRegistration:
    """Adapter is reachable via the platform registry."""

    def test_module_imports_without_pyspark(self):
        """Module should load cleanly even if pyspark is missing."""
        with patch.dict("sys.modules", {"pyspark": None, "pyspark.sql": None, "pyspark.sql.types": None}):
            import importlib

            import benchbox.platforms.velox as velox_mod

            importlib.reload(velox_mod)
            assert hasattr(velox_mod, "VeloxAdapter")

    def test_dependency_info_registered(self):
        from benchbox.utils.dependencies import DEPENDENCY_GROUPS

        assert "velox" in DEPENDENCY_GROUPS
        dep = DEPENDENCY_GROUPS["velox"]
        assert "pyspark" in dep.packages

    def test_platform_to_extra_registered(self):
        from benchbox.utils.dependencies import PLATFORM_TO_EXTRA

        assert "velox" in PLATFORM_TO_EXTRA
        assert PLATFORM_TO_EXTRA["velox"] == "velox"
        assert PLATFORM_TO_EXTRA.get("gluten-velox") == "velox"
