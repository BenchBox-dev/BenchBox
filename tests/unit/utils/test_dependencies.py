"""Tests for dependency management utilities.

Tests the dependency checking, error messages, and installation guidance
for BenchBox platform dependencies.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import MagicMock, patch

import pytest

from benchbox.utils.dependencies import (
    DEPENDENCY_GROUPS,
    PLATFORM_TO_EXTRA,
    DependencyInfo,
    InstallationScenario,
    check_platform_dependencies,
    get_dependency_decision_tree,
    get_dependency_error_message,
    get_dependency_group_packages,
    get_install_command,
    get_installation_matrix_rows,
    get_installation_recommendations,
    get_installation_scenarios,
    is_development_install,
    list_available_dependency_groups,
    validate_dependency_group,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestDependencyInfo:
    """Test the DependencyInfo class."""

    def test_dependency_info_creation(self):
        """Test DependencyInfo object creation."""
        info = DependencyInfo(
            name="test",
            description="Test platform",
            packages=["test-package"],
            install_command='uv pip install "benchbox[test]"',
            use_cases=["Testing"],
            platforms=["Test Platform"],
        )

        assert info.name == "test"
        assert info.description == "Test platform"
        assert info.packages == ["test-package"]
        assert info.install_command == 'uv pip install "benchbox[test]"'
        assert info.use_cases == ["Testing"]
        assert info.platforms == ["Test Platform"]

    def test_extra_name_defaults_to_name_when_command_has_no_extra_flag(self):
        """No --extra flag (e.g. the bare 'all' core-install shape) falls back to name."""
        info = DependencyInfo(
            name="test",
            description="Test platform",
            packages=["test-package"],
            install_command="uv add benchbox",
            use_cases=["Testing"],
            platforms=["Test Platform"],
        )

        assert info.extra_name == "test"

    def test_extra_name_follows_install_command_for_retained_aliases(self):
        """A retained-alias group (name != real extra) must report the real extra,
        not its own group name -- the #1194 bug: get_install_message() derived
        'benchbox[databricks-connect]' from .name after that extra was removed,
        even though install_command already pointed at the real replacement.
        """
        info = DependencyInfo(
            name="databricks-connect",
            description="Legacy alias",
            packages=["databricks-sql-connector"],
            install_command="uv add benchbox --extra cloud-spark-databricks",
            use_cases=["Testing"],
            platforms=["Databricks"],
        )

        assert info.extra_name == "cloud-spark-databricks"
        message = info.get_install_message()
        assert "cloud-spark-databricks" in message
        assert "databricks-connect" not in message

    def test_databricks_connect_group_installs_the_real_extra(self):
        """Live catalog regression: the retained databricks-connect group must
        recommend cloud-spark-databricks (the extra that still exists), not
        databricks-connect (removed in #1194).
        """
        info = DEPENDENCY_GROUPS["databricks-connect"]

        assert info.extra_name == "cloud-spark-databricks"
        assert "databricks-connect" not in info.get_install_message()


class TestInstallationScenario:
    """Test InstallationScenario helper."""

    def test_command_generation_with_extras(self):
        """Scenario commands should include extras when specified."""
        scenario = InstallationScenario(
            name="Test",
            description="Desc",
            platforms=["Example"],
            dependency_groups=["cloud", "clickhouse"],
        )

        assert scenario.extras_label == "cloud,clickhouse"
        assert scenario.uv_command == "uv add benchbox --extra cloud --extra clickhouse"
        assert scenario.uv_pip_command == 'uv pip install "benchbox[cloud,clickhouse]"'
        assert scenario.pip_command == 'python -m pip install "benchbox[cloud,clickhouse]"'
        assert scenario.pipx_command == 'pipx install "benchbox[cloud,clickhouse]"'

    def test_command_generation_core(self):
        """Scenario commands fall back to core installation when no extras."""
        scenario = InstallationScenario(
            name="Core",
            description="",
            platforms=["DuckDB"],
            dependency_groups=[],
        )

        assert scenario.extras_label == "core"
        assert scenario.uv_command == "uv add benchbox"
        assert scenario.uv_pip_command == "uv pip install benchbox"
        assert scenario.pip_command == "python -m pip install benchbox"
        assert scenario.pipx_command == "pipx install benchbox"


class TestDependencyGroups:
    """Test the DEPENDENCY_GROUPS configuration."""

    def test_all_expected_groups_exist(self):
        """Test that all expected dependency groups are defined."""
        expected_groups = {
            "clickhouse",
            "databricks",
            "databricks-df",
            "databricks-connect",
            "cloud-spark",
            "bigquery",
            "redshift",
            "snowflake",
            "trino",
            "presto",
            "postgresql",
            "synapse",
            "fabric",  # Microsoft Fabric Warehouse
            "fabric-spark",  # Microsoft Fabric Spark
            "synapse-spark",  # Azure Synapse Spark
            "athena",
            "athena-spark",  # Amazon Athena for Apache Spark
            "glue",  # AWS Glue
            "emr-serverless",  # Amazon EMR Serverless
            "dataproc",  # GCP Dataproc
            "dataproc-serverless",  # GCP Dataproc Serverless
            "snowpark-connect",  # Snowpark Connect
            "spark",
            "firebolt",
            "influxdb",
            "cloudstorage",
            "cloud",
            "all",
        }

        # Allow new groups to be added without failing
        # Just ensure all expected groups exist
        for group in expected_groups:
            assert group in DEPENDENCY_GROUPS, f"Missing expected group: {group}"

    def test_group_structure(self):
        """Test that each group has the required structure."""
        for name, info in DEPENDENCY_GROUPS.items():
            assert isinstance(info, DependencyInfo)
            assert info.name == name
            assert isinstance(info.description, str)
            assert isinstance(info.packages, list)
            assert len(info.packages) > 0
            assert isinstance(info.install_command, str)
            assert "benchbox" in info.install_command
            assert "--extra" in info.install_command or info.install_command == "uv add benchbox"
            assert isinstance(info.use_cases, list)
            assert isinstance(info.platforms, list)

    def test_cloud_group_excludes_clickhouse(self):
        """Test that cloud group doesn't include ClickHouse."""
        cloud_packages = DEPENDENCY_GROUPS["cloud"].packages
        assert "clickhouse-driver" not in cloud_packages

    def test_all_group_includes_everything(self):
        """Test that all group includes all platform packages."""
        all_packages = set(DEPENDENCY_GROUPS["all"].packages)

        # Check that all individual platform packages are included
        for name, info in DEPENDENCY_GROUPS.items():
            if name not in ["cloud", "all"]:
                for package in info.packages:
                    assert package in all_packages

    def test_cloudpathlib_in_cloud_platforms(self):
        """Test that cloud platforms include cloudpathlib."""
        cloud_platforms = ["databricks", "bigquery", "redshift", "snowflake"]

        for platform in cloud_platforms:
            packages = DEPENDENCY_GROUPS[platform].packages
            assert "cloudpathlib" in packages


class TestDependencyHelperFunctions:
    """Test helper utilities that expose dependency metadata."""

    def test_get_dependency_group_packages_returns_copy(self):
        """Returned package list should be a defensive copy."""
        packages = get_dependency_group_packages("databricks")
        assert "databricks-sql-connector" in packages

        packages.append("sentinel")
        refreshed = get_dependency_group_packages("databricks")

        assert "sentinel" not in refreshed
        assert "cloudpathlib" in refreshed

    def test_get_dependency_group_packages_unknown(self):
        """Unknown groups should return an empty list."""
        assert get_dependency_group_packages("unknown") == []


class TestInstallationScenarioRegistry:
    """Test installation scenario registry and matrix helpers."""

    def test_scenarios_cover_expected_cases(self):
        """Scenarios should include core, cloud, and full coverage options."""
        scenarios = get_installation_scenarios()
        names = {scenario.name for scenario in scenarios}

        assert "Local development (core)" in names
        assert "Cloud storage helpers" in names
        assert "Cloud platforms bundle" in names
        assert "Full platform coverage" in names

    def test_matrix_rows_align_with_scenarios(self):
        """Matrix rows should mirror scenario commands."""
        scenarios = {scenario.name: scenario for scenario in get_installation_scenarios()}
        matrix = get_installation_matrix_rows()

        assert len(matrix) == len(scenarios)

        for name, _platforms, extras, uv_command, pip_command, pipx_command in matrix:
            scenario = scenarios[name]
            assert extras == scenario.extras_label
            assert uv_command == scenario.uv_command
            assert pip_command == scenario.pip_command
            assert pipx_command == scenario.pipx_command


class TestCheckPlatformDependencies:
    """Test the check_platform_dependencies function."""

    def test_check_available_packages(self):
        """Test checking packages that are available."""
        with patch("builtins.__import__") as mock_import:
            # Mock successful imports
            mock_import.return_value = MagicMock()

            available, missing = check_platform_dependencies("test", ["os", "sys"])

            assert available is True
            assert missing == []

    def test_check_missing_packages(self):
        """Test checking packages that are missing."""
        with patch("builtins.__import__") as mock_import:
            # Mock failed imports
            mock_import.side_effect = ImportError("Module not found")

            available, missing = check_platform_dependencies("test", ["nonexistent", "alsomissing"])

            assert available is False
            assert set(missing) == {"nonexistent", "alsomissing"}

    def test_check_mixed_packages(self):
        """Test checking a mix of available and missing packages."""

        def mock_import(module_name):
            if module_name.replace("-", "_") in ["os", "sys"]:
                return MagicMock()
            raise ImportError("Module not found")

        with patch("builtins.__import__", side_effect=mock_import):
            available, missing = check_platform_dependencies("test", ["os", "nonexistent", "sys"])

            assert available is False
            assert missing == ["nonexistent"]

    def test_package_name_normalization(self):
        """Test that package names with hyphens are normalized to underscores."""
        with patch("builtins.__import__") as mock_import:
            mock_import.return_value = MagicMock()

            available, missing = check_platform_dependencies("test", ["package-with-hyphens"])

            # Should call import with underscores
            mock_import.assert_called_with("package_with_hyphens")
            assert available is True

    def test_default_group_lookup(self):
        """Test that default dependency groups are used when packages omitted."""
        with patch("builtins.__import__") as mock_import:
            mock_import.side_effect = ImportError("Module not found")

            available, missing = check_platform_dependencies("cloudstorage")

            assert available is False
            assert missing == ["cloudpathlib"]


class TestGetDependencyErrorMessage:
    """Test the get_dependency_error_message function."""

    def test_known_platform_error_message(self):
        """Test error message for known platform."""
        missing = ["databricks-sql-connector"]
        message = get_dependency_error_message("databricks", missing)

        assert "Missing dependencies for databricks platform" in message
        assert "Extra: benchbox[databricks]" in message
        assert "databricks-sql-connector" in message
        # Check for both pip/venv and uv project install options
        assert "pip install 'benchbox[databricks]'" in message
        assert "uv add benchbox --extra databricks" in message
        assert "Need more guidance? Run: benchbox check-deps --platform databricks" in message
        assert "Databricks-specific" in message.lower() or "Unity Catalog" in message

    def test_unknown_platform_error_message(self):
        """Test error message for unknown platform."""
        missing = ["unknown-package"]
        message = get_dependency_error_message("unknown", missing)

        assert "Missing required dependencies for unknown" in message
        assert "unknown-package" in message
        assert "uv pip install unknown-package" in message

    def test_multiple_missing_packages(self):
        """Test error message with multiple missing packages."""
        missing = ["google-cloud-bigquery", "google-cloud-storage"]
        message = get_dependency_error_message("bigquery", missing)

        assert "google-cloud-bigquery" in message
        assert "google-cloud-storage" in message


class TestGetInstallationRecommendations:
    """Test the get_installation_recommendations function."""

    def test_cloud_use_case_recommendations(self):
        """Test recommendations for cloud use case."""
        recommendations = get_installation_recommendations("cloud analytics")

        assert any("cloud" in rec.lower() for rec in recommendations)
        assert len(recommendations) > 0

    def test_databricks_use_case_recommendations(self):
        """Test recommendations for Databricks use case."""
        recommendations = get_installation_recommendations("databricks lakehouse")

        assert any("databricks" in rec.lower() for rec in recommendations)

    def test_generic_recommendations(self):
        """Test default recommendations when no specific use case."""
        recommendations = get_installation_recommendations()

        assert len(recommendations) > 0
        assert any("cloud" in rec for rec in recommendations)
        assert any("all" in rec for rec in recommendations)

    def test_multiple_platform_recommendations(self):
        """Test that recommendations include multiple options."""
        recommendations = get_installation_recommendations()

        platforms = [
            "cloud",
            "all",
            "cloudstorage",
            "databricks",
            "bigquery",
            "redshift",
            "snowflake",
            "clickhouse",
        ]
        for platform in platforms:
            assert any(platform in rec for rec in recommendations)


class TestListAvailableDependencyGroups:
    """Test the list_available_dependency_groups function."""

    def test_returns_copy_of_groups(self):
        """Test that function returns a copy, not reference."""
        groups1 = list_available_dependency_groups()
        groups2 = list_available_dependency_groups()

        assert groups1 is not groups2
        assert groups1 == groups2

    def test_all_groups_included(self):
        """Test that all expected groups are included."""
        groups = list_available_dependency_groups()

        expected = set(DEPENDENCY_GROUPS.keys())
        actual = set(groups.keys())

        assert actual == expected


class TestValidateDependencyGroup:
    """Test the validate_dependency_group function."""

    def test_valid_group_names(self):
        """Test validation of valid group names."""
        valid_groups = [
            "clickhouse",
            "databricks",
            "bigquery",
            "redshift",
            "snowflake",
            "cloudstorage",
            "cloud",
            "all",
        ]

        for group in valid_groups:
            assert validate_dependency_group(group) is True

    def test_case_insensitive_validation(self):
        """Test that validation is case insensitive."""
        assert validate_dependency_group("DATABRICKS") is True
        assert validate_dependency_group("BigQuery") is True
        assert validate_dependency_group("clickHouse") is True

    def test_invalid_group_names(self):
        """Test validation of invalid group names."""
        invalid_groups = ["nonexistent", "mysql", "postgres", ""]

        for group in invalid_groups:
            assert validate_dependency_group(group) is False


class TestGetDependencyDecisionTree:
    """Test the get_dependency_decision_tree function."""

    def test_decision_tree_content(self):
        """Test that decision tree contains expected content."""
        tree = get_dependency_decision_tree()

        # Check for key sections
        assert "Installation Guide" in tree
        assert "Quick Start" in tree
        assert "Cloud Storage Paths" in tree
        assert "Cloud Platform Specific" in tree
        assert "Scenarios:" in tree

        # Check for installation commands (modern syntax)
        assert "uv add benchbox --extra cloud" in tree
        assert "uv add benchbox --extra all" in tree
        assert "uv add benchbox --extra databricks" in tree
        assert "uv add benchbox --extra cloudstorage" in tree
        # Check for alternative syntax mentioned
        assert "Alternative:" in tree or "pip-compatible" in tree

    def test_decision_tree_formatting(self):
        """Test that decision tree is properly formatted."""
        tree = get_dependency_decision_tree()

        # Should have multiple lines
        assert "\n" in tree
        # Should have some structure indicators
        assert "└──" in tree or "├──" in tree or "•" in tree

    def test_decision_tree_includes_all_platforms(self):
        """Test that decision tree mentions all major platforms."""
        tree = get_dependency_decision_tree()

        platforms = ["Databricks", "BigQuery", "Redshift", "Snowflake", "ClickHouse"]
        for platform in platforms:
            assert platform in tree


class TestDependencyIntegration:
    """Integration tests for dependency management."""

    def test_real_platform_dependency_check(self):
        """Test dependency checking with real platform configurations."""
        # Test a platform that should work (using built-in modules)
        available, missing = check_platform_dependencies("test", ["os"])
        assert available is True
        assert missing == []

    def test_error_message_integration(self):
        """Test full error message generation workflow."""
        # Simulate missing dependencies for each platform
        for platform_name in DEPENDENCY_GROUPS:
            if platform_name in ["all", "cloud"]:
                continue

            dep_info = DEPENDENCY_GROUPS[platform_name]
            message = get_dependency_error_message(platform_name, dep_info.packages)

            # Verify message contains key information
            assert platform_name in message.lower()
            assert "install" in message.lower()
            assert f"benchbox[{platform_name}]" in message

    def test_complete_workflow(self):
        """Test the complete dependency management workflow."""
        # Check status
        groups = list_available_dependency_groups()
        assert len(groups) > 0

        # Validate a group
        assert validate_dependency_group("databricks") is True

        # Get recommendations
        recommendations = get_installation_recommendations("cloud")
        assert len(recommendations) > 0

        # Get decision tree
        tree = get_dependency_decision_tree()
        assert len(tree) > 100  # Should be substantial content


class TestInstallCommandDetection:
    """Test install command detection based on development vs package install."""

    def test_is_development_install_returns_bool(self):
        """Test that is_development_install returns a boolean."""
        result = is_development_install()
        assert isinstance(result, bool)

    def test_is_development_install_cached(self):
        """Test that is_development_install is cached (lru_cache)."""
        # Call twice and verify it returns the same result
        result1 = is_development_install()
        result2 = is_development_install()
        assert result1 == result2

    def test_get_install_command_development(self):
        """Test get_install_command returns uv sync for development installs."""
        with (
            patch("benchbox.utils.dependencies.is_development_install", return_value=True),
            patch("benchbox.utils.dependencies.is_uv_tool_environment", return_value=False),
        ):
            cmd = get_install_command("athena")
            assert cmd == "uv sync --extra athena"

    def test_get_install_command_development_uv_tool(self):
        """Dev installs in uv tool envs should target the running interpreter."""
        fake_python = "/tmp/uv/tools/benchbox/bin/python3"
        with (
            patch("benchbox.utils.dependencies.is_development_install", return_value=True),
            patch("benchbox.utils.dependencies.is_uv_tool_environment", return_value=True),
            patch("benchbox.utils.dependencies.sys.executable", fake_python),
        ):
            cmd = get_install_command("athena")
            assert cmd == f'uv pip install --python "{fake_python}" "benchbox[athena]"'

    def test_get_install_command_package(self):
        """Test get_install_command returns uv pip install for package installs."""
        with patch("benchbox.utils.dependencies.is_development_install", return_value=False):
            cmd = get_install_command("athena")
            assert cmd == 'uv pip install "benchbox[athena]"'

    def test_get_install_command_various_extras(self):
        """Test get_install_command with various extra names."""
        extras = ["cloud", "databricks", "snowflake", "bigquery", "redshift"]

        with (
            patch("benchbox.utils.dependencies.is_development_install", return_value=True),
            patch("benchbox.utils.dependencies.is_uv_tool_environment", return_value=False),
        ):
            for extra in extras:
                cmd = get_install_command(extra)
                assert f"--extra {extra}" in cmd

        with patch("benchbox.utils.dependencies.is_development_install", return_value=False):
            for extra in extras:
                cmd = get_install_command(extra)
                assert f"benchbox[{extra}]" in cmd

    def test_get_install_command_databricks_connect_uses_replacement_extra(self):
        """Regression for #1194: databricks-connect's own extra was removed;
        platform_to_extra must map the retained platform-name lookup to the
        real replacement (cloud-spark-databricks), not the deleted extra --
        otherwise the MCP discovery tool recommends an install that fails.
        """
        assert PLATFORM_TO_EXTRA["databricks-connect"] == "cloud-spark-databricks"

        with patch("benchbox.utils.dependencies.is_development_install", return_value=False):
            cmd = get_install_command("databricks-connect")

        assert cmd == 'uv pip install "benchbox[cloud-spark-databricks]"'
