"""Tests for the CLI setup command.

Tests the credential setup CLI command functionality.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from benchbox.cli.main import cli
from benchbox.security.credentials import CredentialStatus

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestSetupCommand:
    """Test the setup CLI command."""

    def test_setup_command_exists(self):
        """Test that the setup command is available."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "setup" in result.output

    def test_setup_help(self):
        """Test the setup help output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--help"])

        assert result.exit_code == 0
        assert "Interactive setup for cloud platform credentials" in result.output
        assert "--platform" in result.output
        assert "--validate-only" in result.output
        assert "--list-platforms" in result.output
        assert "--status" in result.output
        assert "--remove" in result.output

    def test_setup_no_platform_error(self):
        """Test setup without platform shows error."""
        runner = CliRunner()
        result = runner.invoke(cli, ["setup"])

        assert result.exit_code == 0
        assert "Error: --platform is required" in result.output
        assert "Available platforms:" in result.output

    @patch("benchbox.cli.commands.setup.CredentialManager")
    def test_setup_list_platforms(self, mock_cred_manager_class):
        """Test setup --list-platforms."""
        mock_manager = MagicMock()
        mock_manager.list_platforms.return_value = {
            "databricks": CredentialStatus.VALID,
            "snowflake": CredentialStatus.MISSING,
        }
        mock_cred_manager_class.return_value = mock_manager

        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--list-platforms"])

        assert result.exit_code == 0
        assert "Cloud Platforms Requiring Credentials" in result.output
        assert "Databricks" in result.output
        assert "Snowflake" in result.output
        assert "BigQuery" in result.output
        assert "Redshift" in result.output
        assert "MotherDuck" in result.output
        assert "✅ Configured" in result.output
        assert "○ Not configured" in result.output

    @patch("benchbox.cli.commands.setup.CredentialManager")
    def test_setup_status_no_credentials(self, mock_cred_manager_class):
        """Test setup --status with no credentials configured."""
        mock_manager = MagicMock()
        mock_manager.list_platforms.return_value = {}
        mock_cred_manager_class.return_value = mock_manager

        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--status"])

        assert result.exit_code == 0
        assert "No credentials configured yet" in result.output
        assert "benchbox setup --platform" in result.output

    @patch("benchbox.cli.commands.setup.CredentialManager")
    def test_setup_status_with_credentials(self, mock_cred_manager_class):
        """Test setup --status with configured credentials."""
        mock_manager = MagicMock()
        mock_manager.list_platforms.return_value = {
            "databricks": CredentialStatus.VALID,
            "snowflake": CredentialStatus.INVALID,
        }
        mock_manager.get_platform_credentials.side_effect = lambda p: {
            "last_updated": "2025-01-15T10:00:00",
            "last_validated": "2025-01-15T10:00:00",
        }
        mock_cred_manager_class.return_value = mock_manager

        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--status"])

        assert result.exit_code == 0
        assert "Credential Status" in result.output
        assert "✅ Valid" in result.output
        assert "❌ Invalid" in result.output
        assert "2025-01-15" in result.output

    @patch("benchbox.cli.commands.setup.CredentialManager")
    @patch("benchbox.cli.commands.setup.Confirm.ask")
    def test_setup_remove_confirmed(self, mock_confirm, mock_cred_manager_class):
        """Test setup --remove with confirmation."""
        mock_manager = MagicMock()
        mock_manager.has_credentials.return_value = True
        mock_cred_manager_class.return_value = mock_manager
        mock_confirm.return_value = True

        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--platform", "databricks", "--remove"])

        assert result.exit_code == 0
        assert "Removed credentials for databricks" in result.output
        mock_manager.remove_platform_credentials.assert_called_once_with("databricks")
        mock_manager.save_credentials.assert_called_once()

    @patch("benchbox.cli.commands.setup.CredentialManager")
    @patch("benchbox.cli.commands.setup.Confirm.ask")
    def test_setup_remove_cancelled(self, mock_confirm, mock_cred_manager_class):
        """Test setup --remove with cancellation."""
        mock_manager = MagicMock()
        mock_manager.has_credentials.return_value = True
        mock_cred_manager_class.return_value = mock_manager
        mock_confirm.return_value = False

        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--platform", "databricks", "--remove"])

        assert result.exit_code == 0
        assert "Cancelled" in result.output
        mock_manager.remove_platform_credentials.assert_not_called()

    @patch("benchbox.cli.commands.setup.CredentialManager")
    def test_setup_remove_no_credentials(self, mock_cred_manager_class):
        """Test setup --remove with no existing credentials."""
        mock_manager = MagicMock()
        mock_manager.has_credentials.return_value = False
        mock_cred_manager_class.return_value = mock_manager

        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--platform", "databricks", "--remove"])

        assert result.exit_code == 0
        assert "No credentials found for databricks" in result.output

    @patch("benchbox.cli.commands.setup.CredentialManager")
    @patch("benchbox.platforms.databricks.credentials.validate_databricks_credentials")
    def test_setup_validate_only_success(self, mock_validate, mock_cred_manager_class):
        """Test setup --validate-only with valid credentials."""
        mock_manager = MagicMock()
        mock_manager.has_credentials.return_value = True
        mock_cred_manager_class.return_value = mock_manager
        mock_validate.return_value = (True, None)

        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--platform", "databricks", "--validate-only"])

        assert result.exit_code == 0
        assert "Databricks credentials are valid" in result.output
        mock_validate.assert_called_once_with(mock_manager)
        mock_manager.update_validation_status.assert_called_once_with("databricks", CredentialStatus.VALID)
        mock_manager.save_credentials.assert_called_once()

    @patch("benchbox.cli.commands.setup.CredentialManager")
    @patch("benchbox.platforms.databricks.credentials.validate_databricks_credentials")
    def test_setup_validate_only_failure(self, mock_validate, mock_cred_manager_class):
        """Test setup --validate-only with invalid credentials."""
        mock_manager = MagicMock()
        mock_manager.has_credentials.return_value = True
        mock_cred_manager_class.return_value = mock_manager
        mock_validate.return_value = (False, "Authentication failed")

        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--platform", "databricks", "--validate-only"])

        assert result.exit_code == 0
        assert "Databricks credentials are invalid" in result.output
        assert "Authentication failed" in result.output
        mock_manager.update_validation_status.assert_called_once_with(
            "databricks", CredentialStatus.INVALID, "Authentication failed"
        )

    @patch("benchbox.cli.commands.setup.CredentialManager")
    def test_setup_validate_only_no_credentials(self, mock_cred_manager_class):
        """Test setup --validate-only with no credentials."""
        mock_manager = MagicMock()
        mock_manager.has_credentials.return_value = False
        mock_cred_manager_class.return_value = mock_manager

        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--platform", "databricks", "--validate-only"])

        assert result.exit_code == 0
        assert "No credentials found for databricks" in result.output
        assert "Setup credentials: benchbox setup --platform databricks" in result.output

    @patch("benchbox.cli.commands.setup.CredentialManager")
    @patch("benchbox.utils.dependencies.check_platform_dependencies")
    def test_setup_missing_dependencies(self, mock_check_deps, mock_cred_manager_class):
        """Test setup with missing platform dependencies."""
        mock_manager = MagicMock()
        mock_cred_manager_class.return_value = mock_manager
        mock_check_deps.return_value = (False, ["databricks-sql-connector"])

        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--platform", "databricks"])

        assert result.exit_code == 0
        assert "Missing dependencies for databricks" in result.output
        assert "databricks-sql-connector" in result.output
        assert "Install with:" in result.output

    @patch("benchbox.cli.commands.setup.CredentialManager")
    @patch("benchbox.utils.dependencies.check_platform_dependencies")
    @patch("benchbox.platforms.databricks.credentials.setup_databricks_credentials")
    def test_setup_interactive_databricks(self, mock_setup_databricks, mock_check_deps, mock_cred_manager_class):
        """Test interactive setup for Databricks."""
        mock_manager = MagicMock()
        mock_cred_manager_class.return_value = mock_manager
        mock_check_deps.return_value = (True, [])

        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--platform", "databricks"])

        assert result.exit_code == 0
        assert "Databricks Credentials Setup" in result.output
        mock_setup_databricks.assert_called_once()
        # Check that manager and console were passed
        call_args = mock_setup_databricks.call_args
        assert call_args[0][0] == mock_manager

    @patch("benchbox.cli.commands.setup.CredentialManager")
    @patch("benchbox.utils.dependencies.check_platform_dependencies")
    @patch("benchbox.platforms.credentials.snowflake.setup_snowflake_credentials")
    def test_setup_interactive_snowflake(self, mock_setup_snowflake, mock_check_deps, mock_cred_manager_class):
        """Test interactive setup for Snowflake."""
        mock_manager = MagicMock()
        mock_cred_manager_class.return_value = mock_manager
        mock_check_deps.return_value = (True, [])

        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--platform", "snowflake"])

        assert result.exit_code == 0
        assert "Snowflake Credentials Setup" in result.output
        mock_setup_snowflake.assert_called_once()
        # Check that manager and console were passed
        call_args = mock_setup_snowflake.call_args
        assert call_args[0][0] == mock_manager

    @patch("benchbox.cli.commands.setup.CredentialManager")
    @patch("benchbox.utils.dependencies.check_platform_dependencies")
    @patch("benchbox.platforms.credentials.redshift.setup_redshift_credentials")
    def test_setup_interactive_redshift(self, mock_setup_redshift, mock_check_deps, mock_cred_manager_class):
        """Test interactive setup for Redshift."""
        mock_manager = MagicMock()
        mock_cred_manager_class.return_value = mock_manager
        mock_check_deps.return_value = (True, [])

        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--platform", "redshift"])

        assert result.exit_code == 0
        assert "Redshift Credentials Setup" in result.output
        mock_setup_redshift.assert_called_once()
        # Check that manager and console were passed
        call_args = mock_setup_redshift.call_args
        assert call_args[0][0] == mock_manager

    @patch("benchbox.cli.commands.setup.CredentialManager")
    @patch("benchbox.utils.dependencies.check_platform_dependencies")
    @patch("benchbox.platforms.credentials.motherduck.setup_motherduck_credentials")
    def test_setup_interactive_motherduck(self, mock_setup_motherduck, mock_check_deps, mock_cred_manager_class):
        """Test interactive setup for MotherDuck."""
        mock_manager = MagicMock()
        mock_cred_manager_class.return_value = mock_manager
        mock_check_deps.return_value = (True, [])

        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--platform", "motherduck"])

        assert result.exit_code == 0
        assert "MotherDuck Credentials Setup" in result.output
        mock_setup_motherduck.assert_called_once()
        call_args = mock_setup_motherduck.call_args
        assert call_args[0][0] == mock_manager

    @patch("benchbox.cli.commands.setup.CredentialManager")
    @patch("benchbox.utils.dependencies.check_platform_dependencies")
    @patch("benchbox.platforms.credentials.bigquery.setup_bigquery_credentials")
    def test_setup_interactive_bigquery(self, mock_setup_bigquery, mock_check_deps, mock_cred_manager_class):
        """Test interactive setup for BigQuery."""
        mock_manager = MagicMock()
        mock_cred_manager_class.return_value = mock_manager
        mock_check_deps.return_value = (True, [])

        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--platform", "bigquery"])

        assert result.exit_code == 0
        assert "Bigquery Credentials Setup" in result.output
        mock_setup_bigquery.assert_called_once()
        # Check that manager and console were passed
        call_args = mock_setup_bigquery.call_args
        assert call_args[0][0] == mock_manager

    def test_setup_platform_case_insensitive(self):
        """Test that platform names are case insensitive."""
        with patch("benchbox.cli.commands.setup.CredentialManager") as mock_cred_manager_class:
            with patch("benchbox.utils.dependencies.check_platform_dependencies") as mock_check_deps:
                with patch("benchbox.platforms.databricks.credentials.setup_databricks_credentials"):
                    mock_manager = MagicMock()
                    mock_cred_manager_class.return_value = mock_manager
                    mock_check_deps.return_value = (True, [])

                    runner = CliRunner()
                    result = runner.invoke(cli, ["setup", "--platform", "DATABRICKS"])

                    assert result.exit_code == 0
                    assert "Databricks Credentials Setup" in result.output


class TestSetupValidation:
    """Test validation logic for setup command."""

    @patch("benchbox.cli.commands.setup.CredentialManager")
    @patch("benchbox.platforms.credentials.snowflake.validate_snowflake_credentials")
    def test_validate_snowflake(self, mock_validate, mock_cred_manager_class):
        """Test validation for Snowflake platform."""
        mock_manager = MagicMock()
        mock_manager.has_credentials.return_value = True
        mock_cred_manager_class.return_value = mock_manager
        mock_validate.return_value = (True, None)

        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--platform", "snowflake", "--validate-only"])

        assert result.exit_code == 0
        assert "Snowflake credentials are valid" in result.output

    @patch("benchbox.cli.commands.setup.CredentialManager")
    @patch("benchbox.platforms.credentials.bigquery.validate_bigquery_credentials")
    def test_validate_bigquery(self, mock_validate, mock_cred_manager_class):
        """Test validation for BigQuery platform."""
        mock_manager = MagicMock()
        mock_manager.has_credentials.return_value = True
        mock_cred_manager_class.return_value = mock_manager
        mock_validate.return_value = (True, None)

        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--platform", "bigquery", "--validate-only"])

        assert result.exit_code == 0
        assert "Bigquery credentials are valid" in result.output

    @patch("benchbox.cli.commands.setup.CredentialManager")
    @patch("benchbox.platforms.credentials.redshift.validate_redshift_credentials")
    def test_validate_redshift(self, mock_validate, mock_cred_manager_class):
        """Test validation for Redshift platform."""
        mock_manager = MagicMock()
        mock_manager.has_credentials.return_value = True
        mock_cred_manager_class.return_value = mock_manager
        mock_validate.return_value = (True, None)

        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--platform", "redshift", "--validate-only"])

        assert result.exit_code == 0
        assert "Redshift credentials are valid" in result.output

    @patch("benchbox.cli.commands.setup.CredentialManager")
    @patch("benchbox.platforms.credentials.motherduck.validate_motherduck_credentials")
    def test_validate_motherduck_without_stored_credentials(self, mock_validate, mock_cred_manager_class):
        """MotherDuck validates from MOTHERDUCK_TOKEN even without stored credentials."""
        mock_manager = MagicMock()
        mock_manager.has_credentials.return_value = False
        mock_cred_manager_class.return_value = mock_manager
        mock_validate.return_value = (True, None)

        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--platform", "motherduck", "--validate-only"])

        assert result.exit_code == 0
        assert "MotherDuck credentials are valid" in result.output
        mock_validate.assert_called_once_with(mock_manager)
        mock_manager.set_platform_credentials.assert_called_once()
        saved_credentials = mock_manager.set_platform_credentials.call_args[0][1]
        assert saved_credentials == {
            "database": "benchbox",
            "token_env_var": "MOTHERDUCK_TOKEN",
        }


class TestSetupIntegration:
    """Integration tests for setup command."""

    def test_setup_real_execution_list(self):
        """Test setup --list-platforms with real execution."""
        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--list-platforms"])

        assert result.exit_code == 0
        assert "Cloud Platforms Requiring Credentials" in result.output
        assert "Databricks" in result.output
        assert "Snowflake" in result.output
        assert "MotherDuck" in result.output

    def test_setup_real_execution_status(self):
        """Test setup --status with real execution."""
        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--status"])

        # Should run without errors
        assert result.exit_code == 0
        # Will either show "No credentials" or show the status table
        assert "No credentials configured yet" in result.output or "Credential Status" in result.output

    @patch("benchbox.platforms.databricks.credentials.setup_databricks_credentials")
    @patch("benchbox.utils.dependencies.check_platform_dependencies")
    def test_setup_databricks_interactive_flow(self, mock_check_deps, mock_setup):
        """Test full interactive flow for Databricks setup."""
        mock_check_deps.return_value = (True, [])

        runner = CliRunner()
        result = runner.invoke(cli, ["setup", "--platform", "databricks"])

        assert result.exit_code == 0
        assert "Databricks Credentials Setup" in result.output
        mock_setup.assert_called_once()
