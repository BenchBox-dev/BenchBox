from unittest.mock import Mock, patch

import pytest

from benchbox.cli.database import DatabaseManager
from benchbox.cli.platform_hooks import PlatformHookRegistry, PlatformOptionError
from benchbox.core.schemas import DatabaseConfig
from benchbox.utils.runtime_env import DriverResolution

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_clickhouse_platform_options_defaults():
    options = PlatformHookRegistry.parse_options("clickhouse", [])
    assert options["deployment_mode"] == "server"
    assert options["secure"] is False
    assert options["port"] == 9000


def test_clickhouse_platform_options_overrides():
    parsed = PlatformHookRegistry.parse_options(
        "clickhouse",
        [
            ("deployment_mode", "local"),
            ("secure", "true"),
            ("port", "9440"),
        ],
    )
    assert parsed["deployment_mode"] == "local"
    assert parsed["secure"] is True
    assert parsed["port"] == 9440


def test_databricks_platform_options_support_tuning_overrides():
    parsed = PlatformHookRegistry.parse_options(
        "databricks",
        [
            ("databricks_clustering_strategy", "liquid_clustering_auto"),
        ],
    )
    assert parsed["databricks_clustering_strategy"] == "liquid_clustering_auto"

    parsed = PlatformHookRegistry.parse_options(
        "databricks",
        [
            ("databricks_clustering_strategy", "liquid_clustering"),
            ("liquid_clustering_columns", "event_time,customer_id"),
        ],
    )
    assert parsed["databricks_clustering_strategy"] == "liquid_clustering"
    assert parsed["liquid_clustering_columns"] == "event_time,customer_id"


def test_parse_options_omits_none_defaults():
    parsed = PlatformHookRegistry.parse_options("databricks", [])
    assert "databricks_clustering_strategy" not in parsed
    assert "liquid_clustering_columns" not in parsed


def test_parse_options_unknown_key_raises():
    with pytest.raises(PlatformOptionError):
        PlatformHookRegistry.parse_options("clickhouse", [("unknown", "value")])


def test_spark_platform_options_adaptive_enabled():
    # Spec-row string defaults are normalized through the declared parser, so
    # the default arrives with the same type as parsed user input.
    parsed = PlatformHookRegistry.parse_options("spark", [])
    assert parsed["adaptive_enabled"] is True

    # Explicit values go through parse_bool, so AQE-off runs are reachable via
    # --platform-option adaptive_enabled=false.
    parsed = PlatformHookRegistry.parse_options("spark", [("adaptive_enabled", "false")])
    assert parsed["adaptive_enabled"] is False


@pytest.mark.parametrize(
    ("platform", "option", "expected"),
    [
        # str 'true' reaching polars scan_parquet(rechunk=...) raised
        # "failed to extract field Extract.rechunk" once #1062 started
        # forwarding options into DataFrame adapter constructors.
        ("polars", "rechunk", True),
        # str 'false' defaults are truthy — without parser normalization the
        # effective default inverts wherever consumers rely on truthiness.
        ("polars", "streaming", False),
        ("sqlite", "check_same_thread", False),
        ("datafusion", "batch_size", 8192),
        ("sqlite", "timeout", 30.0),
        ("cudf", "device_id", 0),
        ("velox", "shuffle_partitions", 200),
    ],
)
def test_spec_row_string_defaults_are_parser_typed(platform, option, expected):
    defaults = PlatformHookRegistry.get_default_options(platform)
    assert defaults[option] == expected
    assert type(defaults[option]) is type(expected)


@pytest.mark.parametrize(
    ("platform", "expected_defaults"),
    [
        (
            "pg-duckdb",
            {
                "admin_database": "postgres",
                "sslmode": "prefer",
                "work_mem": "256MB",
                "maintenance_work_mem": "512MB",
                "effective_cache_size": "1GB",
                "max_parallel_workers_per_gather": 2,
                "compare_native": False,
            },
        ),
        (
            "pg-mooncake",
            {
                "admin_database": "postgres",
                "sslmode": "prefer",
                "work_mem": "256MB",
                "maintenance_work_mem": "512MB",
                "effective_cache_size": "1GB",
                "max_parallel_workers_per_gather": 2,
            },
        ),
        (
            "timescaledb",
            {
                "admin_database": "postgres",
                "sslmode": "prefer",
                "work_mem": "256MB",
                "maintenance_work_mem": "512MB",
                "effective_cache_size": "1GB",
                "max_parallel_workers_per_gather": 2,
            },
        ),
    ],
)
def test_group_c_platform_defaults_cover_load_bearing_builder_fields(platform, expected_defaults):
    defaults = PlatformHookRegistry.get_default_options(platform)
    assert {key: defaults[key] for key in expected_defaults} == expected_defaults


def test_pg_duckdb_platform_options_parse_group_c_builder_fields():
    parsed = PlatformHookRegistry.parse_options(
        "pg-duckdb",
        [
            ("compare_native", "true"),
            ("max_parallel_workers_per_gather", "4"),
        ],
    )

    assert parsed["compare_native"] is True
    assert parsed["max_parallel_workers_per_gather"] == 4


def test_database_manager_create_config_merges_options(monkeypatch):
    monkeypatch.setattr(
        "benchbox.cli.database.ensure_driver_version",
        lambda package_name, requested_version, auto_install=False, install_hint=None: DriverResolution(
            package=package_name or "",
            requested=requested_version,
            resolved=requested_version or "local-dev",
            actual=requested_version or "local-dev",
            auto_install_used=False,
            runtime_strategy="current-process",
            runtime_path=None,
            runtime_python_executable="/tmp/python",
        ),
    )
    manager = DatabaseManager()
    config = manager.create_config(
        "clickhouse",
        {"deployment_mode": "local", "secure": True},
        {"force_recreate": True},
    )
    assert config.type == "clickhouse"
    assert config.options["deployment_mode"] == "local"
    assert config.options["secure"] is True
    assert config.options["force_recreate"] is True
    # Local mode should always include a data path
    if config.options.get("deployment_mode") == "local":
        assert config.options["data_path"]
    assert config.driver_package == "clickhouse-driver"
    assert config.driver_version_resolved == "local-dev"
    assert config.driver_version_actual == "local-dev"
    assert config.driver_runtime_strategy == "current-process"
    assert config.driver_runtime_python_executable == "/tmp/python"
    assert config.options["driver_version_actual"] == "local-dev"
    assert config.options["driver_runtime_strategy"] == "current-process"


def test_database_manager_create_config_preserves_saved_credentials_over_defaults(monkeypatch):
    monkeypatch.setattr(
        "benchbox.cli.database.ensure_driver_version",
        lambda package_name, requested_version, auto_install=False, install_hint=None: DriverResolution(
            package=package_name or "",
            requested=requested_version,
            resolved=requested_version or "local-dev",
            actual=requested_version or "local-dev",
            auto_install_used=False,
            runtime_strategy="current-process",
            runtime_path=None,
            runtime_python_executable="/tmp/python",
        ),
    )

    manager = DatabaseManager()

    with patch("benchbox.security.credentials.CredentialManager") as mock_cm_class:
        mock_cm_class.return_value.get_platform_credentials.return_value = {
            "host": "saved-host",
            "username": "saved-user",
        }

        config = manager.create_config("pg-duckdb", None, {"benchmark": "tpch", "scale_factor": 1})

    assert config.host == "saved-host"
    assert config.username == "saved-user"
    assert config.options["host"] == "saved-host"
    assert config.options["username"] == "saved-user"
    assert config.options["schema"] == "public"


def test_database_manager_create_config_explicit_options_override_saved_credentials(monkeypatch):
    monkeypatch.setattr(
        "benchbox.cli.database.ensure_driver_version",
        lambda package_name, requested_version, auto_install=False, install_hint=None: DriverResolution(
            package=package_name or "",
            requested=requested_version,
            resolved=requested_version or "local-dev",
            actual=requested_version or "local-dev",
            auto_install_used=False,
            runtime_strategy="current-process",
            runtime_path=None,
            runtime_python_executable="/tmp/python",
        ),
    )

    manager = DatabaseManager()

    with patch("benchbox.security.credentials.CredentialManager") as mock_cm_class:
        mock_cm_class.return_value.get_platform_credentials.return_value = {
            "host": "saved-host",
            "username": "saved-user",
        }

        config = manager.create_config(
            "pg-duckdb",
            {"host": "cli-host"},
            {"benchmark": "tpch", "scale_factor": 1},
        )

    assert config.host == "cli-host"
    assert config.username == "saved-user"
    assert config.options["host"] == "cli-host"
    assert config.options["username"] == "saved-user"


class TestPlatformConfigBuilders:
    """Test platform-specific config builders for credential loading."""

    @pytest.fixture
    def mock_credential_manager(self):
        """Mock CredentialManager for testing."""
        with patch("benchbox.security.credentials.CredentialManager") as mock_cm_class:
            mock_cm = Mock()
            mock_cm_class.return_value = mock_cm
            yield mock_cm

    @pytest.fixture
    def mock_platform_info(self):
        """Mock PlatformInfo for testing."""
        return Mock(display_name="Test Platform", driver_package="test-driver")

    def test_bigquery_config_builder_loads_credentials(self, mock_credential_manager):
        """Test BigQuery config builder loads and merges credentials."""
        from benchbox.platforms.bigquery import _build_bigquery_config

        # Mock saved credentials
        mock_credential_manager.get_platform_credentials.return_value = {
            "project_id": "saved-project",
            "dataset_id": "saved-dataset",
            "credentials_path": "/saved/path/creds.json",
        }

        # CLI options
        options = {"dataset_id": "cli-dataset", "location": "US"}

        # Runtime overrides
        overrides = {"location": "EU"}

        # Mock platform info
        info = Mock(display_name="BigQuery", driver_package="google-cloud-bigquery")

        # Call the config builder
        config = _build_bigquery_config("bigquery", options, overrides, info)

        # Verify credential loading was called
        mock_credential_manager.get_platform_credentials.assert_called_once_with("bigquery")

        # Verify result is DatabaseConfig
        assert isinstance(config, DatabaseConfig)
        assert config.type == "bigquery"
        assert config.name == "BigQuery"
        assert config.driver_package == "google-cloud-bigquery"

        # Verify priority: defaults < saved < explicit_options < overrides
        assert config.options["project_id"] == "saved-project"  # from saved (not overridden)
        assert config.options["dataset_id"] == "saved-dataset"  # saved creds override registered defaults
        assert config.options["location"] == "EU"  # from overrides (highest priority)
        assert config.options["credentials_path"] == "/saved/path/creds.json"  # from saved

    def test_bigquery_config_builder_no_saved_credentials(self, mock_credential_manager):
        """Test BigQuery config builder works with no saved credentials."""
        from benchbox.platforms.bigquery import _build_bigquery_config

        # No saved credentials
        mock_credential_manager.get_platform_credentials.return_value = None

        options = {"project_id": "cli-project", "dataset_id": "cli-dataset"}
        overrides = {}
        info = Mock(display_name="BigQuery", driver_package="google-cloud-bigquery")

        config = _build_bigquery_config("bigquery", options, overrides, info)

        assert isinstance(config, DatabaseConfig)
        assert config.options["project_id"] == "cli-project"
        assert config.options["dataset_id"] == "cli-dataset"

    def test_bigquery_config_builder_fallback_display_name(self, mock_credential_manager):
        """Test BigQuery config builder uses fallback when info is None."""
        from benchbox.platforms.bigquery import _build_bigquery_config

        mock_credential_manager.get_platform_credentials.return_value = {}

        config = _build_bigquery_config("bigquery", {}, {}, None)

        assert config.name == "Google BigQuery"
        assert config.driver_package == "google-cloud-bigquery"

    def test_snowflake_config_builder_loads_credentials(self, mock_credential_manager):
        """Test Snowflake config builder loads and merges credentials."""
        from benchbox.platforms.snowflake import _build_snowflake_config

        # Mock saved credentials
        mock_credential_manager.get_platform_credentials.return_value = {
            "account": "saved-account",
            "username": "saved-user",
            "password": "saved-pass",
            "warehouse": "saved-wh",
        }

        # CLI options
        options = {"warehouse": "cli-wh", "database": "cli-db"}

        # Runtime overrides
        overrides = {"database": "override-db"}

        # Mock platform info
        info = Mock(display_name="Snowflake", driver_package="snowflake-connector-python")

        # Call the config builder
        config = _build_snowflake_config("snowflake", options, overrides, info)

        # Verify credential loading was called
        mock_credential_manager.get_platform_credentials.assert_called_once_with("snowflake")

        # Verify result is DatabaseConfig
        assert isinstance(config, DatabaseConfig)
        assert config.type == "snowflake"
        assert config.name == "Snowflake"
        assert config.driver_package == "snowflake-connector-python"

        # Verify priority: defaults < saved < explicit_options < overrides
        assert config.options["account"] == "saved-account"  # from saved (not overridden)
        assert config.options["username"] == "saved-user"  # from saved (not overridden)
        assert config.options["password"] == "saved-pass"  # from saved (not overridden)
        assert config.options["warehouse"] == "saved-wh"  # saved creds override registered defaults
        assert config.options["database"] == "override-db"  # from overrides (highest priority)

    def test_snowflake_config_builder_no_saved_credentials(self, mock_credential_manager):
        """Test Snowflake config builder works with no saved credentials."""
        from benchbox.platforms.snowflake import _build_snowflake_config

        mock_credential_manager.get_platform_credentials.return_value = None

        options = {"account": "cli-account", "username": "cli-user", "password": "cli-pass"}
        overrides = {}
        info = Mock(display_name="Snowflake", driver_package="snowflake-connector-python")

        config = _build_snowflake_config("snowflake", options, overrides, info)

        assert isinstance(config, DatabaseConfig)
        assert config.options["account"] == "cli-account"
        assert config.options["username"] == "cli-user"
        assert config.options["password"] == "cli-pass"

    def test_snowflake_config_builder_fallback_display_name(self, mock_credential_manager):
        """Test Snowflake config builder uses fallback when info is None."""
        from benchbox.platforms.snowflake import _build_snowflake_config

        mock_credential_manager.get_platform_credentials.return_value = {}

        config = _build_snowflake_config("snowflake", {}, {}, None)

        assert config.name == "Snowflake"
        assert config.driver_package == "snowflake-connector-python"

    def test_redshift_config_builder_loads_credentials(self, mock_credential_manager):
        """Test Redshift config builder loads and merges credentials."""
        from benchbox.platforms.redshift import _build_redshift_config

        # Mock saved credentials
        mock_credential_manager.get_platform_credentials.return_value = {
            "host": "saved-host.redshift.amazonaws.com",
            "username": "saved-user",
            "password": "saved-pass",
            "database": "saved-db",
        }

        # CLI options
        options = {"database": "cli-db", "port": 5439}

        # Runtime overrides
        overrides = {"port": 5440}

        # Mock platform info
        info = Mock(display_name="Redshift", driver_package="redshift-connector")

        # Call the config builder
        config = _build_redshift_config("redshift", options, overrides, info)

        # Verify credential loading was called
        mock_credential_manager.get_platform_credentials.assert_called_once_with("redshift")

        # Verify result is DatabaseConfig
        assert isinstance(config, DatabaseConfig)
        assert config.type == "redshift"
        assert config.name == "Redshift"
        assert config.driver_package == "redshift-connector"

        # Verify priority: defaults < saved < explicit_options < overrides
        assert config.options["host"] == "saved-host.redshift.amazonaws.com"  # from saved (not overridden)
        assert config.options["username"] == "saved-user"  # from saved (not overridden)
        assert config.options["password"] == "saved-pass"  # from saved (not overridden)
        assert config.options["database"] == "saved-db"  # saved creds override registered defaults
        assert config.options["port"] == 5440  # from overrides (highest priority)

    def test_redshift_config_builder_no_saved_credentials(self, mock_credential_manager):
        """Test Redshift config builder works with no saved credentials."""
        from benchbox.platforms.redshift import _build_redshift_config

        mock_credential_manager.get_platform_credentials.return_value = None

        options = {"host": "cli-host.redshift.amazonaws.com", "username": "cli-user", "password": "cli-pass"}
        overrides = {}
        info = Mock(display_name="Redshift", driver_package="redshift-connector")

        config = _build_redshift_config("redshift", options, overrides, info)

        assert isinstance(config, DatabaseConfig)
        assert config.options["host"] == "cli-host.redshift.amazonaws.com"
        assert config.options["username"] == "cli-user"
        assert config.options["password"] == "cli-pass"

    def test_redshift_config_builder_fallback_display_name(self, mock_credential_manager):
        """Test Redshift config builder uses fallback when info is None."""
        from benchbox.platforms.redshift import _build_redshift_config

        mock_credential_manager.get_platform_credentials.return_value = {}

        config = _build_redshift_config("redshift", {}, {}, None)

        assert config.name == "Amazon Redshift"
        assert config.driver_package == "redshift-connector"

    def test_databricks_config_builder_loads_credentials(self, mock_credential_manager):
        """Test Databricks config builder loads and merges credentials."""
        from benchbox.platforms.databricks import _build_databricks_config

        # Mock saved credentials
        mock_credential_manager.get_platform_credentials.return_value = {
            "server_hostname": "saved-host.databricks.com",
            "http_path": "/sql/1.0/saved",
            "access_token": "saved-token",
            "catalog": "saved-catalog",
        }

        # CLI options
        options = {"catalog": "cli-catalog", "schema": "cli-schema"}

        # Runtime overrides
        overrides = {"schema": "override-schema"}

        # Mock platform info
        info = Mock(display_name="Databricks", driver_package="databricks-sql-connector")

        # Call the config builder
        config = _build_databricks_config("databricks", options, overrides, info)

        # Verify credential loading was called
        mock_credential_manager.get_platform_credentials.assert_called_once_with("databricks")

        # Verify result is DatabaseConfig
        assert isinstance(config, DatabaseConfig)
        assert config.type == "databricks"
        assert config.name == "Databricks"
        assert config.driver_package == "databricks-sql-connector"

        # Verify priority: defaults < saved < explicit_options < overrides
        assert config.options["server_hostname"] == "saved-host.databricks.com"  # from saved (not overridden)
        assert config.options["http_path"] == "/sql/1.0/saved"  # from saved (not overridden)
        assert config.options["access_token"] == "saved-token"  # from saved (not overridden)
        assert config.options["catalog"] == "saved-catalog"  # saved creds override registered defaults
        assert config.options["schema"] == "override-schema"  # from overrides (highest priority)

    def test_databricks_config_builder_no_saved_credentials(self, mock_credential_manager):
        """Test Databricks config builder works with no saved credentials."""
        from benchbox.platforms.databricks import _build_databricks_config

        mock_credential_manager.get_platform_credentials.return_value = None

        options = {
            "server_hostname": "cli-host.databricks.com",
            "http_path": "/sql/1.0/cli",
            "access_token": "cli-token",
        }
        overrides = {}
        info = Mock(display_name="Databricks", driver_package="databricks-sql-connector")

        config = _build_databricks_config("databricks", options, overrides, info)

        assert isinstance(config, DatabaseConfig)
        assert config.options["server_hostname"] == "cli-host.databricks.com"
        assert config.options["http_path"] == "/sql/1.0/cli"
        assert config.options["access_token"] == "cli-token"

    def test_databricks_config_builder_fallback_display_name(self, mock_credential_manager):
        """Test Databricks config builder uses fallback when info is None."""
        from benchbox.platforms.databricks import _build_databricks_config

        mock_credential_manager.get_platform_credentials.return_value = {}

        config = _build_databricks_config("databricks", {}, {}, None)

        assert config.name == "Databricks"
        assert config.driver_package == "databricks-sql-connector"

    def test_config_builder_functions_exist(self):
        """Test that config builder functions are defined in platform modules."""
        # This test verifies the functions exist, not that they're registered
        # (registration requires platform dependencies to be available)

        # Test BigQuery
        from benchbox.platforms.bigquery import _build_bigquery_config

        assert callable(_build_bigquery_config)

        # Test Snowflake
        from benchbox.platforms.snowflake import _build_snowflake_config

        assert callable(_build_snowflake_config)

        # Test Redshift
        from benchbox.platforms.redshift import _build_redshift_config

        assert callable(_build_redshift_config)

        # Test Databricks
        from benchbox.platforms.databricks import _build_databricks_config

        assert callable(_build_databricks_config)
