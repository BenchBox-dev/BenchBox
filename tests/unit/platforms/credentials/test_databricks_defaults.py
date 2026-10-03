"""Tests for Databricks credential setup with default values.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import Mock, patch

import pytest

from benchbox.platforms.databricks.credentials import setup_databricks_credentials

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestDatabricksCredentialDefaults:
    """Test Databricks credential setup shows existing values as defaults."""

    @patch("benchbox.platforms.databricks.credentials.validate_databricks_credentials")
    @patch("benchbox.platforms.databricks.credentials._prompt_default_output_location")
    @patch("benchbox.platforms.databricks.credentials.prompt_secure_field")
    @patch("benchbox.platforms.databricks.credentials.prompt_with_default")
    @patch("rich.prompt.Confirm.ask")
    def test_shows_existing_values_as_defaults(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_prompt_secure,
        mock_output_location,
        mock_validate,
    ):

        # Setup: existing credentials
        mock_manager = Mock()
        existing_creds = {
            "server_hostname": "myworkspace.cloud.databricks.com",
            "http_path": "/sql/1.0/warehouses/abc123",
            "access_token": "secret_token",
            "catalog": "main",
            "schema": "benchbox",
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        # User declines auto-detection, provides same values
        mock_confirm.return_value = False  # Skip auto-detection
        mock_prompt_default.side_effect = [
            "myworkspace.cloud.databricks.com",  # server_hostname
            "/sql/1.0/warehouses/abc123",  # http_path
            "main",  # catalog
            "benchbox",  # schema
        ]
        mock_prompt_secure.return_value = "secret_token"  # access_token (preserved)

        mock_validate.return_value = (True, None)
        console = Mock()

        setup_databricks_credentials(mock_manager, console)

        # Verify prompts were called with existing values as current_value
        calls = mock_prompt_default.call_args_list
        assert calls[0][1]["current_value"] == "myworkspace.cloud.databricks.com"  # server_hostname
        assert calls[1][1]["current_value"] == "/sql/1.0/warehouses/abc123"  # http_path
        assert calls[2][1]["current_value"] == "main"  # catalog
        assert calls[3][1]["current_value"] == "benchbox"  # schema

        # Verify secure field was called with existing token
        mock_prompt_secure.assert_called_once_with("Access token", current_value="secret_token", console=console)

    @patch("benchbox.platforms.databricks.credentials.validate_databricks_credentials")
    @patch("benchbox.platforms.databricks.credentials._prompt_default_output_location")
    @patch("benchbox.platforms.databricks.credentials.prompt_secure_field")
    @patch("benchbox.platforms.databricks.credentials.prompt_with_default")
    @patch("rich.prompt.Confirm.ask")
    def test_works_with_no_existing_credentials(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_prompt_secure,
        mock_output_location,
        mock_validate,
    ):

        # Setup: no existing credentials
        mock_manager = Mock()
        mock_manager.get_platform_credentials.return_value = None

        # User provides new values
        mock_confirm.return_value = False  # Skip auto-detection
        mock_prompt_default.side_effect = [
            "newworkspace.cloud.databricks.com",  # server_hostname
            "/sql/1.0/warehouses/new123",  # http_path
            "main",  # catalog
            "benchbox",  # schema
        ]
        mock_prompt_secure.return_value = "new_token"

        mock_validate.return_value = (True, None)
        console = Mock()

        setup_databricks_credentials(mock_manager, console)

        # Verify prompts were called with None as current_value
        calls = mock_prompt_default.call_args_list
        assert calls[0][1]["current_value"] is None  # server_hostname
        assert calls[1][1]["current_value"] is None  # http_path
        assert calls[2][1]["current_value"] is None  # catalog
        assert calls[3][1]["current_value"] is None  # schema

        # Verify secure field was called with None
        mock_prompt_secure.assert_called_once_with("Access token", current_value=None, console=console)

    @patch("benchbox.platforms.databricks.credentials.validate_databricks_credentials")
    @patch("benchbox.platforms.databricks.credentials._prompt_default_output_location")
    @patch("benchbox.platforms.databricks.credentials.prompt_secure_field")
    @patch("benchbox.platforms.databricks.credentials.prompt_with_default")
    @patch("rich.prompt.Confirm.ask")
    def test_token_preserved_on_empty_input(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_prompt_secure,
        mock_output_location,
        mock_validate,
    ):

        # Setup: existing credentials with token
        mock_manager = Mock()
        existing_creds = {
            "server_hostname": "myworkspace.cloud.databricks.com",
            "http_path": "/sql/1.0/warehouses/abc123",
            "access_token": "existing_token",
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        mock_confirm.return_value = False
        mock_prompt_default.side_effect = [
            "myworkspace.cloud.databricks.com",
            "/sql/1.0/warehouses/abc123",
            "main",
            "benchbox",
        ]
        # User enters empty string, existing token should be preserved
        mock_prompt_secure.return_value = "existing_token"

        mock_validate.return_value = (True, None)
        console = Mock()

        setup_databricks_credentials(mock_manager, console)

        # Verify the saved credentials still have the token
        saved_creds = mock_manager.set_platform_credentials.call_args[0][1]
        assert saved_creds["access_token"] == "existing_token"

    @patch("benchbox.platforms.databricks.credentials._auto_detect_databricks")
    @patch("benchbox.platforms.databricks.credentials.validate_databricks_credentials")
    @patch("benchbox.platforms.databricks.credentials._prompt_default_output_location")
    @patch("benchbox.platforms.databricks.credentials.prompt_secure_field")
    @patch("benchbox.platforms.databricks.credentials.prompt_with_default")
    @patch("rich.prompt.Confirm.ask")
    def test_auto_detection_bypasses_existing_defaults(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_prompt_secure,
        mock_output_location,
        mock_validate,
        mock_auto_detect,
    ):

        # Setup: existing credentials
        mock_manager = Mock()
        existing_creds = {
            "server_hostname": "old_workspace.cloud.databricks.com",
            "http_path": "/sql/1.0/warehouses/old123",
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        # NOTE: With existing credentials, auto-detection is skipped
        mock_prompt_default.side_effect = [
            "old_workspace.cloud.databricks.com",
            "/sql/1.0/warehouses/old123",
            "main",
            "benchbox",
        ]
        mock_prompt_secure.return_value = "token"
        mock_validate.return_value = (True, None)
        console = Mock()

        setup_databricks_credentials(mock_manager, console)

        # Verify Confirm.ask was NOT called (no auto-detection prompt)
        mock_confirm.assert_not_called()
        # Verify auto-detect was NOT called
        mock_auto_detect.assert_not_called()

    @patch("benchbox.platforms.databricks.credentials._auto_detect_databricks")
    @patch("benchbox.platforms.databricks.credentials.validate_databricks_credentials")
    @patch("benchbox.platforms.databricks.credentials._prompt_default_output_location")
    @patch("benchbox.platforms.databricks.credentials.prompt_secure_field")
    @patch("benchbox.platforms.databricks.credentials.prompt_with_default")
    @patch("rich.prompt.Confirm.ask")
    def test_skips_auto_detection_when_credentials_exist(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_prompt_secure,
        mock_output_location,
        mock_validate,
        mock_auto_detect,
    ):

        # Setup: existing credentials
        mock_manager = Mock()
        existing_creds = {
            "server_hostname": "myworkspace.cloud.databricks.com",
            "http_path": "/sql/1.0/warehouses/abc123",
            "access_token": "secret_token",
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        mock_prompt_default.side_effect = [
            "myworkspace.cloud.databricks.com",
            "/sql/1.0/warehouses/abc123",
            "main",
            "benchbox",
        ]
        mock_prompt_secure.return_value = "secret_token"
        mock_validate.return_value = (True, None)
        console = Mock()

        setup_databricks_credentials(mock_manager, console)

        # Verify no auto-detection prompt was shown
        mock_confirm.assert_not_called()
        mock_auto_detect.assert_not_called()

        # Verify "updating configuration" message was displayed
        console_output = " ".join(str(call) for call in console.print.call_args_list)
        assert "Existing credentials found" in console_output
        assert "updating configuration" in console_output

    @patch("benchbox.platforms.databricks.credentials._auto_detect_databricks")
    @patch("benchbox.platforms.databricks.credentials.validate_databricks_credentials")
    @patch("benchbox.platforms.databricks.credentials._prompt_default_output_location")
    @patch("benchbox.platforms.databricks.credentials.prompt_secure_field")
    @patch("benchbox.platforms.databricks.credentials.prompt_with_default")
    @patch("rich.prompt.Confirm.ask")
    def test_offers_auto_detection_when_no_credentials_exist(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_prompt_secure,
        mock_output_location,
        mock_validate,
        mock_auto_detect,
    ):

        # Setup: no existing credentials
        mock_manager = Mock()
        mock_manager.get_platform_credentials.return_value = None

        # User declines auto-detection
        mock_confirm.return_value = False
        mock_prompt_default.side_effect = [
            "newworkspace.cloud.databricks.com",
            "/sql/1.0/warehouses/new123",
            "main",
            "benchbox",
        ]
        mock_prompt_secure.return_value = "new_token"
        mock_validate.return_value = (True, None)
        console = Mock()

        setup_databricks_credentials(mock_manager, console)

        # Verify auto-detection prompt WAS shown
        mock_confirm.assert_called_once_with("🔍 Attempt auto-detection using Databricks SDK?", default=True)

        # Verify "updating configuration" message was NOT displayed
        console_output = " ".join(str(call) for call in console.print.call_args_list)
        assert "Existing credentials found" not in console_output

    @patch("benchbox.platforms.databricks.credentials.validate_databricks_credentials")
    @patch("benchbox.platforms.databricks.credentials._prompt_default_output_location")
    @patch("benchbox.platforms.databricks.credentials.prompt_secure_field")
    @patch("benchbox.platforms.databricks.credentials.prompt_with_default")
    @patch("rich.prompt.Confirm.ask")
    def test_partial_existing_credentials(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_prompt_secure,
        mock_output_location,
        mock_validate,
    ):

        # Setup: only some credentials exist
        mock_manager = Mock()
        existing_creds = {
            "server_hostname": "myworkspace.cloud.databricks.com",
            # http_path, access_token missing
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        mock_confirm.return_value = False
        mock_prompt_default.side_effect = [
            "myworkspace.cloud.databricks.com",  # existing
            "/sql/1.0/warehouses/new123",  # new
            "main",  # new (uses default_if_none)
            "benchbox",  # new (uses default_if_none)
        ]
        mock_prompt_secure.return_value = "new_token"

        mock_validate.return_value = (True, None)
        console = Mock()

        setup_databricks_credentials(mock_manager, console)

        # Verify existing values were used as defaults
        calls = mock_prompt_default.call_args_list
        assert calls[0][1]["current_value"] == "myworkspace.cloud.databricks.com"
        # Missing fields should have None as current_value
        assert calls[1][1]["current_value"] is None
        assert calls[2][1]["current_value"] is None
        assert calls[2][1]["default_if_none"] == "main"
