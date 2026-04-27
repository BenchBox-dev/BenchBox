"""Tests for CLI platform management functionality.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import shutil
import sys
import tempfile
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner
from rich.console import Console

from benchbox.cli.platform import (
    PLATFORM_ALIASES,
    LibraryInfo,
    PlatformInfo,
    PlatformManager,
    check_platforms,
    disable_platform,
    enable_platform,
    get_platform_manager,
    install_platform,
    list_platforms,
    normalize_platform_name,
    platform_status,
    setup_platforms,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# Skip marker for tests that use mock.patch on CLI module attributes (Python 3.10 incompatible)
skip_py310_cli_mock = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="CLI mock.patch requires Python 3.11+ for module attribute access",
)


class TestLibraryInfo:
    """Test LibraryInfo dataclass."""

    def test_library_info_installed(self):
        """Test LibraryInfo for installed library."""
        lib = LibraryInfo(name="duckdb", version="0.9.0", installed=True)
        assert lib.name == "duckdb"
        assert lib.version == "0.9.0"
        assert lib.installed is True
        assert lib.import_error is None

    def test_library_info_missing(self):
        """Test LibraryInfo for missing library."""
        lib = LibraryInfo(
            name="nonexistent",
            version=None,
            installed=False,
            import_error="No module named 'nonexistent'",
        )
        assert lib.name == "nonexistent"
        assert lib.version is None
        assert lib.installed is False
        assert "No module named" in lib.import_error


class TestPlatformNameNormalization:
    """Test platform name normalization and aliases."""

    def test_normalize_lowercase(self):
        """Test that names are lowercased."""
        assert normalize_platform_name("DuckDB") == "duckdb"
        assert normalize_platform_name("PostgreSQL") == "postgresql"
        assert normalize_platform_name("CLICKHOUSE") == "clickhouse"

    def test_normalize_postgres_aliases(self):
        """Test PostgreSQL aliases."""
        assert normalize_platform_name("postgres") == "postgresql"
        assert normalize_platform_name("pg") == "postgresql"
        assert normalize_platform_name("pgsql") == "postgresql"
        assert normalize_platform_name("POSTGRES") == "postgresql"
        assert normalize_platform_name("PG") == "postgresql"

    def test_normalize_trino_presto_aliases(self):
        """Test Trino and Presto aliases."""
        assert normalize_platform_name("trinodb") == "trino"
        assert normalize_platform_name("TrinoDB") == "trino"
        assert normalize_platform_name("prestodb") == "presto"
        assert normalize_platform_name("PrestoDB") == "presto"

    def test_normalize_clickhouse_alias(self):
        """Test ClickHouse alias."""
        assert normalize_platform_name("ch") == "clickhouse"
        assert normalize_platform_name("CH") == "clickhouse"

    def test_normalize_bigquery_aliases(self):
        """Test BigQuery aliases."""
        assert normalize_platform_name("bq") == "bigquery"
        assert normalize_platform_name("gbq") == "bigquery"
        assert normalize_platform_name("BQ") == "bigquery"

    def test_normalize_other_aliases(self):
        """Test other platform aliases."""
        assert normalize_platform_name("duck") == "duckdb"
        assert normalize_platform_name("dbx") == "databricks"
        assert normalize_platform_name("snow") == "snowflake"
        assert normalize_platform_name("rs") == "redshift"
        assert normalize_platform_name("fusion") == "datafusion"
        assert normalize_platform_name("azure-synapse") == "synapse"
        assert normalize_platform_name("azuresynapse") == "synapse"

    def test_normalize_canonical_names_unchanged(self):
        """Test that canonical names are not changed."""
        assert normalize_platform_name("duckdb") == "duckdb"
        assert normalize_platform_name("postgresql") == "postgresql"
        assert normalize_platform_name("clickhouse") == "clickhouse"
        assert normalize_platform_name("bigquery") == "bigquery"
        assert normalize_platform_name("trino") == "trino"
        assert normalize_platform_name("presto") == "presto"

    def test_platform_aliases_dict_exists(self):
        """Test that PLATFORM_ALIASES contains expected entries."""
        assert "postgres" in PLATFORM_ALIASES
        assert "pg" in PLATFORM_ALIASES
        assert "ch" in PLATFORM_ALIASES
        assert "bq" in PLATFORM_ALIASES
        assert PLATFORM_ALIASES["postgres"] == "postgresql"


class TestPlatformInfo:
    """Test PlatformInfo dataclass."""

    def test_platform_info_complete(self):
        """Test PlatformInfo with all fields."""
        lib = LibraryInfo(name="duckdb", version="0.9.0", installed=True)
        platform = PlatformInfo(
            name="duckdb",
            display_name="DuckDB",
            description="High-performance analytical database",
            libraries=[lib],
            available=True,
            enabled=True,
            requirements=["duckdb>=0.8.0"],
            installation_command="uv add duckdb",
            adoption="mainstream",
            category="analytical",
        )

        assert platform.name == "duckdb"
        assert platform.display_name == "DuckDB"
        assert platform.available is True
        assert platform.enabled is True
        assert platform.adoption == "mainstream"
        assert platform.category == "analytical"
        assert len(platform.libraries) == 1
        assert platform.libraries[0].name == "duckdb"


class TestPlatformManager:
    """Test PlatformManager functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.config_path = self.temp_dir / "test_platforms.yaml"
        self.manager = PlatformManager(config_path=self.config_path)

    def teardown_method(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir)

    def test_platform_registry_exists(self):
        """Test that platform registry is properly initialized."""
        registry = self.manager.platform_registry
        assert isinstance(registry, dict)
        # Base platforms should always be present
        assert "duckdb" in registry
        assert "sqlite" in registry
        # Cloud platforms are included if their dependencies can be imported
        # (clickhouse, bigquery, databricks, snowflake, redshift)

    def test_platform_registry_structure(self):
        """Test platform registry has correct structure."""
        duckdb_spec = self.manager.platform_registry["duckdb"]

        required_keys = [
            "display_name",
            "description",
            "category",
            "libraries",
            "requirements",
            "installation_command",
            "adoption",
            "supports",
        ]

        for key in required_keys:
            assert key in duckdb_spec, f"Missing required key: {key}"

        assert isinstance(duckdb_spec["libraries"], list)
        assert len(duckdb_spec["libraries"]) > 0
        assert duckdb_spec["libraries"][0]["name"] == "duckdb"
        assert duckdb_spec["libraries"][0]["required"] is True

    def test_config_loading_new_file(self):
        """Test config loading when file doesn't exist."""
        config = self.manager._config
        assert "enabled_platforms" in config
        assert isinstance(config["enabled_platforms"], list)
        # Should default to all platforms enabled
        assert len(config["enabled_platforms"]) == len(self.manager.platform_registry)

    def test_config_save_and_load(self):
        """Test saving and loading configuration."""
        # Modify config
        self.manager._config["enabled_platforms"] = ["duckdb", "sqlite"]
        self.manager._save_config()

        # Create new manager to test loading
        new_manager = PlatformManager(config_path=self.config_path)
        assert new_manager._config["enabled_platforms"] == ["duckdb", "sqlite"]

    @patch("importlib.import_module")
    def test_detect_library_success(self, mock_import):
        """Test successful library detection."""
        mock_module = Mock()
        mock_module.__version__ = "1.0.0"
        mock_import.return_value = mock_module

        lib_spec = {"name": "duckdb", "required": True}
        lib_info = self.manager._detect_library(lib_spec)

        assert lib_info.name == "duckdb"
        assert lib_info.version == "1.0.0"
        assert lib_info.installed is True
        assert lib_info.import_error is None

    @patch("importlib.import_module")
    def test_detect_library_failure(self, mock_import):
        """Test library detection failure."""
        mock_import.side_effect = ImportError("No module named 'missing_lib'")

        lib_spec = {"name": "missing_lib", "required": True}
        lib_info = self.manager._detect_library(lib_spec)

        assert lib_info.name == "missing_lib"
        assert lib_info.version is None
        assert lib_info.installed is False
        assert "No module named" in lib_info.import_error

    @patch("importlib.import_module")
    def test_detect_platforms_all_available(self, mock_import):
        """Test platform detection when all libraries are available."""
        mock_module = Mock()
        mock_module.__version__ = "1.0.0"
        mock_import.return_value = mock_module

        platforms = self.manager.detect_platforms()

        assert isinstance(platforms, dict)
        assert len(platforms) == len(self.manager.platform_registry)

        # All platforms should be available and enabled (default config)
        for _platform_name, platform_info in platforms.items():
            assert platform_info.available is True
            assert platform_info.enabled is True
            assert len(platform_info.libraries) > 0

    @patch("importlib.import_module")
    def test_detect_platforms_some_missing(self, mock_import):
        """Test platform detection when some libraries are missing."""

        def side_effect(module_name):
            if module_name in ["duckdb", "sqlite3"]:
                mock_module = Mock()
                mock_module.__version__ = "1.0.0"
                return mock_module
            else:
                raise ImportError(f"No module named '{module_name}'")

        mock_import.side_effect = side_effect

        platforms = self.manager.detect_platforms()

        # DuckDB and SQLite should be available
        assert platforms["duckdb"].available is True
        assert platforms["sqlite"].available is True

        # Cloud platforms are registered if their dependencies can be imported
        # In this test, only duckdb and sqlite dependencies are mocked as available

    def test_get_available_platforms(self):
        """Test getting list of available platforms."""
        with patch.object(self.manager, "detect_platforms") as mock_detect:
            mock_platforms = {
                "duckdb": PlatformInfo(
                    name="duckdb",
                    display_name="DuckDB",
                    description="",
                    libraries=[],
                    available=True,
                    enabled=True,
                    requirements=[],
                    installation_command="",
                    category="analytical",
                ),
                "missing": PlatformInfo(
                    name="missing",
                    display_name="Missing",
                    description="",
                    libraries=[],
                    available=False,
                    enabled=False,
                    requirements=[],
                    installation_command="",
                    category="database",
                ),
            }
            mock_detect.return_value = mock_platforms

            available = self.manager.get_available_platforms()
            assert available == ["duckdb"]

    def test_get_enabled_platforms(self):
        """Test getting list of enabled platforms."""
        with patch.object(self.manager, "detect_platforms") as mock_detect:
            mock_platforms = {
                "duckdb": PlatformInfo(
                    name="duckdb",
                    display_name="DuckDB",
                    description="",
                    libraries=[],
                    available=True,
                    enabled=True,
                    requirements=[],
                    installation_command="",
                    category="analytical",
                ),
                "disabled": PlatformInfo(
                    name="disabled",
                    display_name="Disabled",
                    description="",
                    libraries=[],
                    available=True,
                    enabled=False,
                    requirements=[],
                    installation_command="",
                    category="database",
                ),
            }
            mock_detect.return_value = mock_platforms

            enabled = self.manager.get_enabled_platforms()
            assert enabled == ["duckdb"]

    def test_enable_platform_success(self):
        """Test successfully enabling a platform."""
        # Set up config with only duckdb enabled
        self.manager._config["enabled_platforms"] = ["duckdb"]

        with patch.object(self.manager, "detect_platforms") as mock_detect:
            mock_platforms = {
                "sqlite": PlatformInfo(
                    name="sqlite",
                    display_name="SQLite",
                    description="",
                    libraries=[],
                    available=True,
                    enabled=False,
                    requirements=[],
                    installation_command="",
                    category="embedded",
                )
            }
            mock_detect.return_value = mock_platforms

            result = self.manager.enable_platform("sqlite")
            assert result is True
            assert "sqlite" in self.manager._config["enabled_platforms"]

    def test_enable_platform_not_available(self):
        """Test enabling a platform that's not available."""
        with patch.object(self.manager, "detect_platforms") as mock_detect:
            mock_platforms = {
                "missing": PlatformInfo(
                    name="missing",
                    display_name="Missing",
                    description="",
                    libraries=[],
                    available=False,
                    enabled=False,
                    requirements=[],
                    installation_command="",
                    category="database",
                )
            }
            mock_detect.return_value = mock_platforms

            result = self.manager.enable_platform("missing")
            assert result is False

    def test_enable_platform_unknown(self):
        """Test enabling an unknown platform."""
        result = self.manager.enable_platform("nonexistent")
        assert result is False

    def test_disable_platform_success(self):
        """Test successfully disabling a platform."""
        # Set up config with platforms enabled
        self.manager._config["enabled_platforms"] = ["duckdb", "sqlite"]

        result = self.manager.disable_platform("sqlite")
        assert result is True
        assert "sqlite" not in self.manager._config["enabled_platforms"]
        assert "duckdb" in self.manager._config["enabled_platforms"]

    def test_disable_platform_unknown(self):
        """Test disabling an unknown platform."""
        result = self.manager.disable_platform("nonexistent")
        assert result is False

    def test_is_platform_available(self):
        """Test platform availability checking."""
        with patch.object(self.manager, "detect_platforms") as mock_detect:
            mock_platforms = {
                "duckdb": PlatformInfo(
                    name="duckdb",
                    display_name="DuckDB",
                    description="",
                    libraries=[],
                    available=True,
                    enabled=True,
                    requirements=[],
                    installation_command="",
                    category="analytical",
                ),
                "missing": PlatformInfo(
                    name="missing",
                    display_name="Missing",
                    description="",
                    libraries=[],
                    available=False,
                    enabled=False,
                    requirements=[],
                    installation_command="",
                    category="database",
                ),
            }
            mock_detect.return_value = mock_platforms

            assert self.manager.is_platform_available("duckdb") is True
            assert self.manager.is_platform_available("missing") is False
            assert self.manager.is_platform_available("nonexistent") is False

    def test_get_installation_guide(self):
        """Test getting installation guide for a platform."""
        # Use real platform from registry
        guide = self.manager.get_installation_guide("duckdb")

        assert guide is not None
        assert guide["platform"] == "DuckDB"
        assert guide["description"] == "Columnar OLAP engine • Single-node • In-memory"
        assert guide["installation_command"] == "uv add duckdb"
        assert guide["category"] == "analytical"
        assert isinstance(guide["available"], bool)
        assert isinstance(guide["missing_libraries"], list)

    def test_get_installation_guide_unknown_platform(self):
        """Test getting installation guide for unknown platform."""
        guide = self.manager.get_installation_guide("nonexistent")
        assert guide is None

    def test_display_platform_status_renders_rows_and_summary(self):
        """Status table should render grouped rows and the aggregate summary."""
        stream = StringIO()
        self.manager.console = Console(file=stream, force_terminal=False, color_system=None, width=120)

        with patch.object(self.manager, "detect_platforms") as mock_detect:
            mock_detect.return_value = {
                "duckdb": PlatformInfo(
                    name="duckdb",
                    display_name="DuckDB",
                    description="Embedded OLAP",
                    libraries=[LibraryInfo(name="duckdb", version="1.0.0", installed=True)],
                    available=True,
                    enabled=True,
                    requirements=[],
                    installation_command="uv add duckdb",
                    category="analytical",
                ),
                "snowflake": PlatformInfo(
                    name="snowflake",
                    display_name="Snowflake",
                    description="Cloud warehouse",
                    libraries=[LibraryInfo(name="snowflake", version=None, installed=False)],
                    available=False,
                    enabled=False,
                    requirements=["snowflake-connector-python"],
                    installation_command="uv add snowflake-connector-python",
                    category="cloud",
                ),
                "sqlite": PlatformInfo(
                    name="sqlite",
                    display_name="SQLite",
                    description="Embedded row store",
                    libraries=[LibraryInfo(name="sqlite3", version="3.45.0", installed=True)],
                    available=True,
                    enabled=False,
                    requirements=[],
                    installation_command="builtin",
                    category="embedded",
                ),
            }

            self.manager.display_platform_status()

        output = stream.getvalue()
        assert "DuckDB" in output
        assert "Snowflake" in output
        assert "SQLite" in output
        assert "Summary:" in output
        assert "1 enabled, 2 available, 3 total" in output

    def test_display_platform_list_hides_unavailable_when_show_all_false(self):
        """Simple list output should omit unavailable platforms unless show_all=True."""
        stream = StringIO()
        self.manager.console = Console(file=stream, force_terminal=False, color_system=None, width=120)

        with patch.object(self.manager, "detect_platforms") as mock_detect:
            mock_detect.return_value = {
                "duckdb": PlatformInfo(
                    name="duckdb",
                    display_name="DuckDB",
                    description="Embedded OLAP",
                    libraries=[],
                    available=True,
                    enabled=True,
                    requirements=[],
                    installation_command="uv add duckdb",
                    category="analytical",
                ),
                "snowflake": PlatformInfo(
                    name="snowflake",
                    display_name="Snowflake",
                    description="Cloud warehouse",
                    libraries=[],
                    available=False,
                    enabled=False,
                    requirements=["snowflake-connector-python"],
                    installation_command="uv add snowflake-connector-python",
                    category="cloud",
                ),
            }

            self.manager.display_platform_list(show_all=False)

        output = stream.getvalue()
        assert "DuckDB" in output
        assert "Snowflake" not in output

    @patch("benchbox.cli.platform.PlatformRegistry.get_platform_capabilities")
    def test_display_platform_deployments_renders_modes_and_requirements(self, mock_caps):
        """Deployment mode table should include CLI names and requirement hints."""
        stream = StringIO()
        self.manager.console = Console(file=stream, force_terminal=False, color_system=None, width=120)

        with patch.object(self.manager, "detect_platforms") as mock_detect:
            mock_detect.return_value = {
                "clickhouse": PlatformInfo(
                    name="clickhouse",
                    display_name="ClickHouse",
                    description="Columnar OLAP",
                    libraries=[],
                    available=True,
                    enabled=True,
                    requirements=[],
                    installation_command="uv add benchbox --extra clickhouse-cloud",
                    category="analytical",
                ),
                "duckdb": PlatformInfo(
                    name="duckdb",
                    display_name="DuckDB",
                    description="Embedded OLAP",
                    libraries=[],
                    available=True,
                    enabled=True,
                    requirements=[],
                    installation_command="uv add duckdb",
                    category="analytical",
                ),
            }
            mock_caps.side_effect = lambda name: (
                SimpleNamespace(
                    default_deployment="local",
                    deployment_modes={
                        "server": SimpleNamespace(
                            mode="self-hosted",
                            requires_credentials=True,
                            requires_cloud_storage=False,
                            requires_network=True,
                        ),
                        "local": SimpleNamespace(
                            mode="local",
                            requires_credentials=False,
                            requires_cloud_storage=False,
                            requires_network=False,
                        ),
                    },
                )
                if name == "clickhouse"
                else None
            )

            self.manager.display_platform_deployments()

        output = stream.getvalue()
        assert "clickhouse:server" in output
        assert "clickhouse:local" in output
        assert "credentials, network" in output
        assert "Usage: benchbox run --platform <platform>:<mode>" in output


@skip_py310_cli_mock
class TestCLICommands:
    """Test CLI command functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.runner = CliRunner()
        self.temp_dir = Path(tempfile.mkdtemp())
        self.config_path = self.temp_dir / "test_platforms.yaml"

    def teardown_method(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir)

    @patch("benchbox.cli.platform.get_platform_manager")
    def test_list_platforms_table_format(self, mock_get_manager):
        """Test list platforms command with table format."""
        mock_manager = Mock()
        mock_get_manager.return_value = mock_manager

        result = self.runner.invoke(list_platforms, ["--format", "table"])

        assert result.exit_code == 0
        mock_manager.display_platform_status.assert_called_once()

    @patch("benchbox.cli.platform.get_platform_manager")
    def test_list_platforms_simple_format(self, mock_get_manager):
        """Test list platforms command with simple format."""
        mock_manager = Mock()
        mock_get_manager.return_value = mock_manager

        result = self.runner.invoke(list_platforms, ["--format", "simple", "--all"])

        assert result.exit_code == 0
        mock_manager.display_platform_list.assert_called_once_with(show_all=True)

    @patch("benchbox.cli.platform.get_platform_manager")
    def test_list_platforms_show_deployments(self, mock_get_manager):
        """Test list platforms command with deployment mode output."""
        mock_manager = Mock()
        mock_get_manager.return_value = mock_manager

        result = self.runner.invoke(list_platforms, ["--show-deployments"])

        assert result.exit_code == 0
        mock_manager.display_platform_deployments.assert_called_once()
        mock_manager.display_platform_status.assert_not_called()

    @patch("benchbox.cli.platform.get_platform_manager")
    def test_platform_status_all(self, mock_get_manager):
        """Test platform status command for all platforms."""
        mock_manager = Mock()
        mock_get_manager.return_value = mock_manager

        result = self.runner.invoke(platform_status)

        assert result.exit_code == 0
        mock_manager.display_platform_status.assert_called_once()

    @patch("benchbox.cli.platform.get_platform_manager")
    def test_platform_status_specific(self, mock_get_manager):
        """Test platform status command for specific platform."""
        mock_manager = Mock()
        mock_lib = LibraryInfo(name="duckdb", version="1.0.0", installed=True)
        mock_platforms = {
            "duckdb": PlatformInfo(
                name="duckdb",
                display_name="DuckDB",
                description="High-performance database",
                libraries=[mock_lib],
                available=True,
                enabled=True,
                requirements=["duckdb>=0.8.0"],
                installation_command="uv add duckdb",
                category="analytical",
            )
        }
        mock_manager.detect_platforms.return_value = mock_platforms
        mock_get_manager.return_value = mock_manager

        result = self.runner.invoke(platform_status, ["duckdb"])

        assert result.exit_code == 0
        assert "DuckDB" in result.output
        assert "High-performance database" in result.output

    @patch("benchbox.cli.platform.get_platform_manager")
    def test_platform_status_missing_dependencies_shows_installation_details(self, mock_get_manager):
        """Missing platform details should include import errors and install guidance."""
        mock_manager = Mock()
        mock_lib = LibraryInfo(
            name="snowflake.connector",
            version=None,
            installed=False,
            import_error="No module named 'snowflake.connector'",
        )
        mock_manager.detect_platforms.return_value = {
            "snowflake": PlatformInfo(
                name="snowflake",
                display_name="Snowflake",
                description="Cloud data warehouse",
                libraries=[mock_lib],
                available=False,
                enabled=False,
                requirements=["snowflake-connector-python>=3.0.0"],
                installation_command="uv add snowflake-connector-python",
                category="cloud",
            )
        }
        mock_get_manager.return_value = mock_manager

        result = self.runner.invoke(platform_status, ["snowflake"])

        assert result.exit_code == 0
        assert "Missing Dependencies" in result.output
        assert "snowflake.connector" in result.output
        assert "No module named 'snowflake.connector'" in result.output
        assert "uv add snowflake-connector-python" in result.output
        assert "snowflake-connector-python>=3.0.0" in result.output

    @patch("benchbox.cli.platform.get_platform_manager")
    def test_platform_status_unknown(self, mock_get_manager):
        """Test platform status command for unknown platform."""
        mock_manager = Mock()
        mock_manager.detect_platforms.return_value = {}
        mock_get_manager.return_value = mock_manager

        result = self.runner.invoke(platform_status, ["nonexistent"])

        assert result.exit_code == 1
        assert "Unknown platform" in result.output

    @patch("benchbox.cli.platform.get_platform_manager")
    def test_enable_platform_success(self, mock_get_manager):
        """Test enabling platform successfully."""
        mock_manager = Mock()
        mock_platforms = {
            "duckdb": PlatformInfo(
                name="duckdb",
                display_name="DuckDB",
                description="",
                libraries=[],
                available=True,
                enabled=False,
                requirements=[],
                installation_command="",
                category="analytical",
            )
        }
        mock_manager.detect_platforms.return_value = mock_platforms
        mock_manager.enable_platform.return_value = True
        mock_get_manager.return_value = mock_manager

        result = self.runner.invoke(enable_platform, ["duckdb"])

        assert result.exit_code == 0
        assert "Enabled platform: DuckDB" in result.output
        mock_manager.enable_platform.assert_called_once_with("duckdb")

    @patch("benchbox.cli.platform.get_platform_manager")
    def test_enable_platform_already_enabled(self, mock_get_manager):
        """Test enabling platform that's already enabled."""
        mock_manager = Mock()
        mock_platforms = {
            "duckdb": PlatformInfo(
                name="duckdb",
                display_name="DuckDB",
                description="",
                libraries=[],
                available=True,
                enabled=True,
                requirements=[],
                installation_command="",
                category="analytical",
            )
        }
        mock_manager.detect_platforms.return_value = mock_platforms
        mock_get_manager.return_value = mock_manager

        result = self.runner.invoke(enable_platform, ["duckdb"])

        assert result.exit_code == 0
        assert "already enabled" in result.output

    @patch("benchbox.cli.platform.get_platform_manager")
    def test_enable_platform_not_available(self, mock_get_manager):
        """Test enabling platform that's not available."""
        mock_manager = Mock()
        mock_platforms = {
            "missing": PlatformInfo(
                name="missing",
                display_name="Missing Platform",
                description="",
                libraries=[],
                available=False,
                enabled=False,
                requirements=[],
                installation_command="uv add missing",
                category="database",
            )
        }
        mock_manager.detect_platforms.return_value = mock_platforms
        mock_get_manager.return_value = mock_manager

        result = self.runner.invoke(enable_platform, ["missing"])

        assert result.exit_code == 1
        assert "missing required dependencies" in result.output
        assert "uv add missing" in result.output

    @patch("benchbox.cli.platform.get_platform_manager")
    def test_enable_platform_force_allows_missing_dependencies(self, mock_get_manager):
        """Force mode should enable a missing platform after alias normalization."""
        mock_manager = Mock()
        mock_platforms = {
            "datafusion": PlatformInfo(
                name="datafusion",
                display_name="DataFusion",
                description="",
                libraries=[],
                available=False,
                enabled=False,
                requirements=["datafusion>=0.0.0"],
                installation_command="uv add datafusion",
                category="analytical",
            )
        }
        mock_manager.detect_platforms.return_value = mock_platforms
        mock_manager.enable_platform.return_value = True
        mock_get_manager.return_value = mock_manager

        result = self.runner.invoke(enable_platform, ["fusion", "--force"])

        assert result.exit_code == 0
        assert "Enabled platform: DataFusion" in result.output
        assert "dependencies missing" in result.output
        mock_manager.enable_platform.assert_called_once_with("datafusion")

    @patch("benchbox.cli.platform.get_platform_manager")
    def test_disable_platform_success(self, mock_get_manager):
        """Test disabling platform successfully."""
        mock_manager = Mock()
        mock_platforms = {
            "duckdb": PlatformInfo(
                name="duckdb",
                display_name="DuckDB",
                description="",
                libraries=[],
                available=True,
                enabled=True,
                requirements=[],
                installation_command="",
                category="analytical",
            )
        }
        mock_manager.detect_platforms.return_value = mock_platforms
        mock_manager.disable_platform.return_value = True
        mock_get_manager.return_value = mock_manager

        result = self.runner.invoke(disable_platform, ["duckdb"], input="y\n")

        assert result.exit_code == 0
        assert "Disabled platform: DuckDB" in result.output
        mock_manager.disable_platform.assert_called_once_with("duckdb")

    @patch("benchbox.cli.platform.get_platform_manager")
    def test_disable_platform_cancelled_by_user(self, mock_get_manager):
        """Declining the confirmation should leave the platform unchanged."""
        mock_manager = Mock()
        mock_platforms = {
            "duckdb": PlatformInfo(
                name="duckdb",
                display_name="DuckDB",
                description="",
                libraries=[],
                available=True,
                enabled=True,
                requirements=[],
                installation_command="",
                category="analytical",
            )
        }
        mock_manager.detect_platforms.return_value = mock_platforms
        mock_get_manager.return_value = mock_manager

        result = self.runner.invoke(disable_platform, ["duck"], input="n\n")

        assert result.exit_code == 0
        assert "Cancelled" in result.output
        mock_manager.disable_platform.assert_not_called()

    @patch("benchbox.cli.platform.get_platform_manager")
    def test_install_platform_available(self, mock_get_manager):
        """Test install command for already available platform."""
        mock_manager = Mock()
        mock_guide = {
            "platform": "DuckDB",
            "description": "High-performance database",
            "category": "analytical",
            "available": True,
            "installation_command": "uv add duckdb",
            "requirements": ["duckdb>=0.8.0"],
            "missing_libraries": [],
        }
        mock_manager.get_installation_guide.return_value = mock_guide
        mock_get_manager.return_value = mock_manager

        result = self.runner.invoke(install_platform, ["duckdb"])

        assert result.exit_code == 0
        assert "Already installed and available" in result.output

    @patch("benchbox.cli.platform.get_platform_manager")
    def test_install_platform_missing(self, mock_get_manager):
        """Test install command for missing platform."""
        mock_manager = Mock()
        mock_guide = {
            "platform": "ClickHouse",
            "description": "Columnar database",
            "category": "analytical",
            "available": False,
            "installation_command": "uv add clickhouse-driver",
            "requirements": ["clickhouse-driver>=0.2.0"],
            "missing_libraries": ["clickhouse_driver"],
        }
        mock_manager.get_installation_guide.return_value = mock_guide
        mock_get_manager.return_value = mock_manager

        result = self.runner.invoke(install_platform, ["clickhouse"], input="n\n")

        assert result.exit_code == 0
        assert "Missing dependencies" in result.output
        assert "uv add clickhouse-driver" in result.output
        assert "clickhouse_driver" in result.output

    @patch("benchbox.cli.platform.get_platform_manager")
    def test_install_platform_dry_run_reports_no_install(self, mock_get_manager):
        """Dry-run mode should stop after showing installation instructions."""
        mock_manager = Mock()
        mock_manager.get_installation_guide.return_value = {
            "platform": "ClickHouse",
            "description": "Columnar database",
            "category": "analytical",
            "available": False,
            "installation_command": "uv add clickhouse-driver",
            "requirements": ["clickhouse-driver>=0.2.0"],
            "missing_libraries": ["clickhouse_driver"],
        }
        mock_get_manager.return_value = mock_manager

        result = self.runner.invoke(install_platform, ["clickhouse", "--dry-run"])

        assert result.exit_code == 0
        assert "Dry run mode: No installation performed" in result.output
        assert "After installation, run" not in result.output

    @patch("benchbox.cli.platform.get_platform_manager")
    def test_check_platforms_all_ready(self, mock_get_manager):
        """Test check platforms command when all are ready."""
        mock_manager = Mock()
        mock_platforms = {
            "duckdb": PlatformInfo(
                name="duckdb",
                display_name="DuckDB",
                description="",
                libraries=[],
                available=True,
                enabled=True,
                requirements=[],
                installation_command="",
                category="analytical",
            )
        }
        mock_manager.detect_platforms.return_value = mock_platforms
        mock_manager.is_platform_available.return_value = True
        mock_get_manager.return_value = mock_manager

        result = self.runner.invoke(check_platforms, ["duckdb"])

        assert result.exit_code == 0
        assert "DuckDB: Ready" in result.output
        assert "All checked platforms are ready!" in result.output

    @patch("benchbox.cli.platform.get_platform_manager")
    def test_check_platforms_some_missing(self, mock_get_manager):
        """Test check platforms command when some have issues."""
        mock_manager = Mock()
        mock_platforms = {
            "duckdb": PlatformInfo(
                name="duckdb",
                display_name="DuckDB",
                description="",
                libraries=[],
                available=True,
                enabled=True,
                requirements=[],
                installation_command="",
                category="analytical",
            ),
            "missing": PlatformInfo(
                name="missing",
                display_name="Missing Platform",
                description="",
                libraries=[],
                available=False,
                enabled=False,
                requirements=[],
                installation_command="uv add missing",
                category="database",
            ),
        }
        mock_manager.detect_platforms.return_value = mock_platforms
        mock_manager.is_platform_available.side_effect = lambda x: x == "duckdb"
        mock_get_manager.return_value = mock_manager

        result = self.runner.invoke(check_platforms, ["duckdb", "missing"])

        assert result.exit_code == 1
        assert "DuckDB: Ready" in result.output
        assert "Missing Platform: Missing dependencies" in result.output
        assert "Some platforms need attention" in result.output

    @patch("benchbox.cli.platform.get_platform_manager")
    def test_check_platforms_enabled_only_with_none_enabled(self, mock_get_manager):
        """Enabled-only mode should short-circuit when nothing is enabled."""
        mock_manager = Mock()
        mock_manager.detect_platforms.return_value = {}
        mock_manager.get_enabled_platforms.return_value = []
        mock_get_manager.return_value = mock_manager

        result = self.runner.invoke(check_platforms, ["--enabled-only"])

        assert result.exit_code == 0
        assert "No platforms to check" in result.output


class TestGlobalPlatformManager:
    """Test global platform manager function."""

    def test_get_platform_manager_singleton(self):
        """Test that get_platform_manager returns same instance."""
        manager1 = get_platform_manager()
        manager2 = get_platform_manager()
        assert manager1 is manager2

    def test_get_platform_manager_returns_platform_manager(self):
        """Test that get_platform_manager returns PlatformManager instance."""
        manager = get_platform_manager()
        assert isinstance(manager, PlatformManager)


@skip_py310_cli_mock
class TestSetupPlatformsCommand:
    """Test the interactive and non-interactive setup wizard branches."""

    def setup_method(self):
        self.runner = CliRunner()

    @patch("benchbox.cli.platform.get_platform_manager")
    def test_setup_platforms_non_interactive_enables_available_disabled_platforms(self, mock_get_manager):
        mock_manager = Mock()
        mock_manager.detect_platforms.return_value = {
            "duckdb": PlatformInfo(
                name="duckdb",
                display_name="DuckDB",
                description="",
                libraries=[],
                available=True,
                enabled=False,
                requirements=[],
                installation_command="uv add duckdb",
                category="analytical",
            ),
            "sqlite": PlatformInfo(
                name="sqlite",
                display_name="SQLite",
                description="",
                libraries=[],
                available=True,
                enabled=True,
                requirements=[],
                installation_command="builtin",
                category="embedded",
            ),
            "snowflake": PlatformInfo(
                name="snowflake",
                display_name="Snowflake",
                description="",
                libraries=[],
                available=False,
                enabled=False,
                requirements=[],
                installation_command="uv add snowflake-connector-python",
                category="cloud",
            ),
        }
        mock_manager.enable_platform.return_value = True
        mock_get_manager.return_value = mock_manager

        result = self.runner.invoke(setup_platforms, ["--non-interactive"])

        assert result.exit_code == 0
        mock_manager.enable_platform.assert_called_once_with("duckdb")
        assert "Enabled: DuckDB" in result.output
        assert "Enabled 1 platforms" in result.output

    @patch("benchbox.cli.platform.get_platform_manager")
    @patch("benchbox.cli.platform.NumberedSelectPrompt.ask")
    def test_setup_platforms_status_branch_displays_current_status(self, mock_ask, mock_get_manager):
        mock_manager = Mock()
        mock_manager.detect_platforms.return_value = {}
        mock_get_manager.return_value = mock_manager
        mock_ask.side_effect = ["status", "done"]

        result = self.runner.invoke(setup_platforms, ["--interactive"])

        assert result.exit_code == 0
        mock_manager.display_platform_status.assert_called_once()

    @patch("benchbox.cli.platform.numbered_platform_select", return_value=None)
    @patch("benchbox.cli.platform.get_platform_manager")
    @patch("benchbox.cli.platform.NumberedSelectPrompt.ask")
    def test_setup_platforms_install_branch_reports_no_missing_platforms(self, mock_ask, mock_get_manager, mock_select):
        mock_manager = Mock()
        mock_manager.detect_platforms.return_value = {}
        mock_get_manager.return_value = mock_manager
        mock_ask.side_effect = ["install", "done"]

        result = self.runner.invoke(setup_platforms, ["--interactive"])

        assert result.exit_code == 0
        mock_select.assert_called_once()
        assert "No platforms with missing dependencies." in result.output

    @patch("benchbox.cli.platform.numbered_platform_select", return_value=None)
    @patch("benchbox.cli.platform.get_platform_manager")
    @patch("benchbox.cli.platform.NumberedSelectPrompt.ask")
    def test_setup_platforms_enable_branch_reports_no_candidates(self, mock_ask, mock_get_manager, mock_select):
        mock_manager = Mock()
        mock_manager.detect_platforms.return_value = {}
        mock_get_manager.return_value = mock_manager
        mock_ask.side_effect = ["enable", "done"]

        result = self.runner.invoke(setup_platforms, ["--interactive"])

        assert result.exit_code == 0
        mock_select.assert_called_once()
        assert "No available platforms to enable." in result.output

    @patch("benchbox.cli.platform.numbered_platform_select", return_value=None)
    @patch("benchbox.cli.platform.get_platform_manager")
    @patch("benchbox.cli.platform.NumberedSelectPrompt.ask")
    def test_setup_platforms_disable_branch_reports_no_enabled_platforms(self, mock_ask, mock_get_manager, mock_select):
        mock_manager = Mock()
        mock_manager.detect_platforms.return_value = {}
        mock_get_manager.return_value = mock_manager
        mock_ask.side_effect = ["disable", "done"]

        result = self.runner.invoke(setup_platforms, ["--interactive"])

        assert result.exit_code == 0
        mock_select.assert_called_once()
        assert "No enabled platforms to disable." in result.output
