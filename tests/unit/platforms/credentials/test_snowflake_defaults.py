"""Tests for Snowflake credential setup with default values.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import Mock, patch

import pytest

from benchbox.platforms.credentials.snowflake import setup_snowflake_credentials

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestSnowflakeCredentialDefaults:
    """Test Snowflake credential setup shows existing values as defaults."""

    @patch("benchbox.platforms.credentials.snowflake.validate_snowflake_credentials")
    @patch("benchbox.platforms.credentials.snowflake._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.snowflake.prompt_secure_field")
    @patch("benchbox.platforms.credentials.snowflake.prompt_with_default")
    @patch("rich.prompt.Confirm.ask")
    def test_shows_existing_values_as_defaults(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_prompt_secure,
        mock_output_location,
        mock_validate,
    ):
        """Test that existing credential values are shown as defaults in prompts."""
        # Setup: existing credentials
        mock_manager = Mock()
        existing_creds = {
            "account": "myorg-account123",
            "username": "JOEHARRIS76",
            "password": "secret_password",
            "warehouse": "MY_WAREHOUSE",
            "database": "MY_DATABASE",
            "schema": "MY_SCHEMA",
            "role": "MY_ROLE",
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        # User declines auto-detection, provides same values
        mock_confirm.return_value = False  # Skip auto-detection
        mock_prompt_default.side_effect = [
            "myorg-account123",  # account
            "JOEHARRIS76",  # username
            "MY_WAREHOUSE",  # warehouse
            "MY_DATABASE",  # database
            "MY_SCHEMA",  # schema
            "MY_ROLE",  # role
        ]
        mock_prompt_secure.return_value = "secret_password"  # password (preserved)

        mock_validate.return_value = (True, None)
        console = Mock()

        setup_snowflake_credentials(mock_manager, console)

        # Verify prompts were called with existing values as current_value
        calls = mock_prompt_default.call_args_list
        assert calls[0][1]["current_value"] == "myorg-account123"  # account
        assert calls[1][1]["current_value"] == "JOEHARRIS76"  # username
        assert calls[2][1]["current_value"] == "MY_WAREHOUSE"  # warehouse
        assert calls[3][1]["current_value"] == "MY_DATABASE"  # database
        assert calls[4][1]["current_value"] == "MY_SCHEMA"  # schema
        assert calls[5][1]["current_value"] == "MY_ROLE"  # role

        # Verify secure field was called with existing password
        mock_prompt_secure.assert_called_once_with("Password", current_value="secret_password", console=console)

    @patch("benchbox.platforms.credentials.snowflake.validate_snowflake_credentials")
    @patch("benchbox.platforms.credentials.snowflake._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.snowflake.prompt_secure_field")
    @patch("benchbox.platforms.credentials.snowflake.prompt_with_default")
    @patch("rich.prompt.Confirm.ask")
    def test_works_with_no_existing_credentials(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_prompt_secure,
        mock_output_location,
        mock_validate,
    ):
        """Test that setup works when no existing credentials exist."""
        # Setup: no existing credentials
        mock_manager = Mock()
        mock_manager.get_platform_credentials.return_value = None

        # User provides new values
        mock_confirm.return_value = False  # Skip auto-detection
        mock_prompt_default.side_effect = [
            "newaccount",  # account
            "newuser",  # username
            "COMPUTE_WH",  # warehouse
            "BENCHBOX",  # database
            "PUBLIC",  # schema
            "",  # role
        ]
        mock_prompt_secure.return_value = "newpassword"

        mock_validate.return_value = (True, None)
        console = Mock()

        setup_snowflake_credentials(mock_manager, console)

        # Verify prompts were called with None as current_value
        calls = mock_prompt_default.call_args_list
        assert calls[0][1]["current_value"] is None  # account
        assert calls[1][1]["current_value"] is None  # username
        assert calls[2][1]["current_value"] is None  # warehouse
        assert calls[3][1]["current_value"] is None  # database
        assert calls[4][1]["current_value"] is None  # schema
        assert calls[5][1]["current_value"] is None  # role

        # Verify secure field was called with None
        mock_prompt_secure.assert_called_once_with("Password", current_value=None, console=console)

    @patch("benchbox.platforms.credentials.snowflake.validate_snowflake_credentials")
    @patch("benchbox.platforms.credentials.snowflake._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.snowflake.prompt_secure_field")
    @patch("benchbox.platforms.credentials.snowflake.prompt_with_default")
    @patch("rich.prompt.Confirm.ask")
    def test_password_preserved_on_empty_input(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_prompt_secure,
        mock_output_location,
        mock_validate,
    ):
        """Test that existing password is preserved when user enters empty input."""
        # Setup: existing credentials with password
        mock_manager = Mock()
        existing_creds = {
            "account": "myorg-account123",
            "username": "JOEHARRIS76",
            "password": "existing_secret",
            "warehouse": "MY_WAREHOUSE",
            "database": "MY_DATABASE",
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        mock_confirm.return_value = False
        mock_prompt_default.side_effect = [
            "myorg-account123",
            "JOEHARRIS76",
            "MY_WAREHOUSE",
            "MY_DATABASE",
            "PUBLIC",
            "",
        ]
        # User enters empty string, existing password should be preserved
        mock_prompt_secure.return_value = "existing_secret"

        mock_validate.return_value = (True, None)
        console = Mock()

        setup_snowflake_credentials(mock_manager, console)

        # Verify the saved credentials still have the password
        saved_creds = mock_manager.set_platform_credentials.call_args[0][1]
        assert saved_creds["password"] == "existing_secret"

    @patch("benchbox.platforms.credentials.snowflake.validate_snowflake_credentials")
    @patch("benchbox.platforms.credentials.snowflake._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.snowflake.prompt_secure_field")
    @patch("benchbox.platforms.credentials.snowflake.prompt_with_default")
    @patch("rich.prompt.Confirm.ask")
    def test_new_password_overrides_existing(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_prompt_secure,
        mock_output_location,
        mock_validate,
    ):
        """Test that new password overrides existing password."""
        # Setup: existing credentials
        mock_manager = Mock()
        existing_creds = {
            "account": "myorg-account123",
            "username": "JOEHARRIS76",
            "password": "old_password",
            "warehouse": "MY_WAREHOUSE",
            "database": "MY_DATABASE",
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        mock_confirm.return_value = False
        mock_prompt_default.side_effect = [
            "myorg-account123",
            "JOEHARRIS76",
            "MY_WAREHOUSE",
            "MY_DATABASE",
            "PUBLIC",
            "",
        ]
        # User provides new password
        mock_prompt_secure.return_value = "new_password"

        mock_validate.return_value = (True, None)
        console = Mock()

        setup_snowflake_credentials(mock_manager, console)

        # Verify the saved credentials have the new password
        saved_creds = mock_manager.set_platform_credentials.call_args[0][1]
        assert saved_creds["password"] == "new_password"

    @patch("benchbox.platforms.credentials.snowflake.validate_snowflake_credentials")
    @patch("benchbox.platforms.credentials.snowflake._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.snowflake.prompt_secure_field")
    @patch("benchbox.platforms.credentials.snowflake.prompt_with_default")
    @patch("rich.prompt.Confirm.ask")
    def test_partial_existing_credentials(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_prompt_secure,
        mock_output_location,
        mock_validate,
    ):
        """Test handling of partial existing credentials."""
        # Setup: only some credentials exist
        mock_manager = Mock()
        existing_creds = {
            "account": "myorg-account123",
            "username": "JOEHARRIS76",
            # password, warehouse, database missing
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        mock_confirm.return_value = False
        mock_prompt_default.side_effect = [
            "myorg-account123",  # existing
            "JOEHARRIS76",  # existing
            "COMPUTE_WH",  # new (uses default_if_none)
            "BENCHBOX",  # new (uses default_if_none)
            "PUBLIC",  # new
            "",  # new
        ]
        mock_prompt_secure.return_value = "new_password"

        mock_validate.return_value = (True, None)
        console = Mock()

        setup_snowflake_credentials(mock_manager, console)

        # Verify existing values were used as defaults
        calls = mock_prompt_default.call_args_list
        assert calls[0][1]["current_value"] == "myorg-account123"
        assert calls[1][1]["current_value"] == "JOEHARRIS76"
        # Missing fields should have None as current_value but have default_if_none
        assert calls[2][1]["current_value"] is None
        assert calls[2][1]["default_if_none"] == "COMPUTE_WH"

    @patch("benchbox.platforms.credentials.snowflake.validate_snowflake_credentials")
    @patch("benchbox.platforms.credentials.snowflake._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.snowflake.prompt_secure_field")
    @patch("benchbox.platforms.credentials.snowflake.prompt_with_default")
    @patch("rich.prompt.Confirm.ask")
    def test_optional_fields_show_existing_values(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_prompt_secure,
        mock_output_location,
        mock_validate,
    ):
        """Test that optional fields (schema, role) show existing values."""
        # Setup: credentials with optional fields
        mock_manager = Mock()
        existing_creds = {
            "account": "myorg-account123",
            "username": "JOEHARRIS76",
            "password": "secret",
            "warehouse": "MY_WAREHOUSE",
            "database": "MY_DATABASE",
            "schema": "CUSTOM_SCHEMA",
            "role": "CUSTOM_ROLE",
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        mock_confirm.return_value = False
        mock_prompt_default.side_effect = [
            "myorg-account123",
            "JOEHARRIS76",
            "MY_WAREHOUSE",
            "MY_DATABASE",
            "CUSTOM_SCHEMA",
            "CUSTOM_ROLE",
        ]
        mock_prompt_secure.return_value = "secret"

        mock_validate.return_value = (True, None)
        console = Mock()

        setup_snowflake_credentials(mock_manager, console)

        # Verify optional fields were called with existing values
        calls = mock_prompt_default.call_args_list
        assert calls[4][1]["current_value"] == "CUSTOM_SCHEMA"  # schema
        assert calls[5][1]["current_value"] == "CUSTOM_ROLE"  # role

    @patch("benchbox.platforms.credentials.snowflake._auto_detect_snowflake")
    @patch("benchbox.platforms.credentials.snowflake.validate_snowflake_credentials")
    @patch("benchbox.platforms.credentials.snowflake._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.snowflake.prompt_secure_field")
    @patch("benchbox.platforms.credentials.snowflake.prompt_with_default")
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
        """Test that auto-detection is skipped when existing credentials are present."""
        # Setup: existing credentials
        mock_manager = Mock()
        existing_creds = {
            "account": "old_account",
            "username": "old_user",
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        # NOTE: With existing credentials, auto-detection is skipped
        # This test verifies that existing credentials flow directly to manual prompts
        # Auto-detection is no longer offered when credentials exist

        mock_prompt_default.side_effect = [
            "old_account",
            "old_user",
            "COMPUTE_WH",
            "BENCHBOX",
            "PUBLIC",
            "",
        ]
        mock_prompt_secure.return_value = "password"
        mock_validate.return_value = (True, None)
        console = Mock()

        setup_snowflake_credentials(mock_manager, console)

        # Verify Confirm.ask was NOT called (no auto-detection prompt)
        mock_confirm.assert_not_called()
        # Verify auto-detect was NOT called
        mock_auto_detect.assert_not_called()

    @patch("benchbox.platforms.credentials.snowflake._auto_detect_snowflake")
    @patch("benchbox.platforms.credentials.snowflake.validate_snowflake_credentials")
    @patch("benchbox.platforms.credentials.snowflake._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.snowflake.prompt_secure_field")
    @patch("benchbox.platforms.credentials.snowflake.prompt_with_default")
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
        """Test that auto-detection is skipped when credentials already exist."""
        # Setup: existing credentials
        mock_manager = Mock()
        existing_creds = {
            "account": "myorg-account123",
            "username": "JOEHARRIS76",
            "password": "secret",
            "warehouse": "MY_WAREHOUSE",
            "database": "MY_DATABASE",
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        mock_prompt_default.side_effect = [
            "myorg-account123",
            "JOEHARRIS76",
            "MY_WAREHOUSE",
            "MY_DATABASE",
            "PUBLIC",
            "",
        ]
        mock_prompt_secure.return_value = "secret"
        mock_validate.return_value = (True, None)
        console = Mock()

        setup_snowflake_credentials(mock_manager, console)

        # Verify no auto-detection prompt was shown
        mock_confirm.assert_not_called()
        mock_auto_detect.assert_not_called()

        # Verify "updating configuration" message was displayed
        console_output = " ".join(str(call) for call in console.print.call_args_list)
        assert "Existing credentials found" in console_output
        assert "updating configuration" in console_output

    @patch("benchbox.platforms.credentials.snowflake._auto_detect_snowflake")
    @patch("benchbox.platforms.credentials.snowflake.validate_snowflake_credentials")
    @patch("benchbox.platforms.credentials.snowflake._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.snowflake.prompt_secure_field")
    @patch("benchbox.platforms.credentials.snowflake.prompt_with_default")
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
        """Test that auto-detection is offered when no credentials exist."""
        # Setup: no existing credentials
        mock_manager = Mock()
        mock_manager.get_platform_credentials.return_value = None

        # User declines auto-detection
        mock_confirm.return_value = False
        mock_prompt_default.side_effect = [
            "newaccount",
            "newuser",
            "COMPUTE_WH",
            "BENCHBOX",
            "PUBLIC",
            "",
        ]
        mock_prompt_secure.return_value = "newpassword"
        mock_validate.return_value = (True, None)
        console = Mock()

        setup_snowflake_credentials(mock_manager, console)

        # Verify auto-detection prompt WAS shown
        mock_confirm.assert_called_once_with("🔍 Attempt auto-detection from environment variables?", default=True)

        # Verify "updating configuration" message was NOT displayed
        console_output = " ".join(str(call) for call in console.print.call_args_list)
        assert "Existing credentials found" not in console_output

    @patch("benchbox.platforms.credentials.snowflake._auto_detect_snowflake")
    @patch("benchbox.platforms.credentials.snowflake.validate_snowflake_credentials")
    @patch("benchbox.platforms.credentials.snowflake._prompt_default_output_location")
    @patch("rich.prompt.Confirm.ask")
    def test_auto_detection_success_skips_manual_prompts(
        self,
        mock_confirm,
        mock_output_location,
        mock_validate,
        mock_auto_detect,
    ):
        """Test that successful auto-detection populates values without manual prompts."""
        mock_manager = Mock()
        mock_manager.get_platform_credentials.return_value = None

        # User accepts auto-detection, and it succeeds
        mock_confirm.return_value = True
        mock_auto_detect.return_value = {
            "account": "auto-account",
            "username": "auto-user",
            "password": "auto-pass",
            "warehouse": "AUTO_WH",
            "database": "AUTO_DB",
            "schema": "AUTO_SCHEMA",
            "role": "AUTO_ROLE",
        }
        mock_validate.return_value = (True, None)
        console = Mock()

        setup_snowflake_credentials(mock_manager, console)

        # Credentials should be saved with auto-detected values
        saved_creds = mock_manager.set_platform_credentials.call_args[0][1]
        assert saved_creds["account"] == "auto-account"
        assert saved_creds["username"] == "auto-user"
        assert saved_creds["warehouse"] == "AUTO_WH"
        assert saved_creds["database"] == "AUTO_DB"

        # Verify the console printed auto-detected values
        console_output = " ".join(str(call) for call in console.print.call_args_list)
        assert "auto-account" in console_output
        assert "auto-user" in console_output

    @patch("benchbox.platforms.credentials.snowflake.validate_snowflake_credentials")
    @patch("benchbox.platforms.credentials.snowflake._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.snowflake.prompt_secure_field")
    @patch("benchbox.platforms.credentials.snowflake.prompt_with_default")
    @patch("rich.prompt.Confirm.ask")
    def test_validation_failure_saves_invalid_credentials(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_prompt_secure,
        mock_output_location,
        mock_validate,
    ):
        """Test that validation failure saves credentials as invalid and shows error."""
        mock_manager = Mock()
        mock_manager.get_platform_credentials.return_value = None

        mock_confirm.return_value = False
        mock_prompt_default.side_effect = [
            "badaccount",
            "user",
            "WH",
            "DB",
            "PUBLIC",
            "",
        ]
        mock_prompt_secure.return_value = "wrongpassword"
        mock_validate.return_value = (False, "Authentication failed. Check your username and password.")
        console = Mock()

        setup_snowflake_credentials(mock_manager, console)

        # output_location should NOT be called on failure
        mock_output_location.assert_not_called()

        console_output = " ".join(str(call) for call in console.print.call_args_list)
        assert "Validation failed" in console_output


# ---------------------------------------------------------------------------
# _prompt_default_output_location direct tests
# ---------------------------------------------------------------------------


class TestPromptDefaultOutputLocation:
    """Test _prompt_default_output_location paths."""

    def _make_manager(self):
        mgr = Mock()
        mgr.credentials_path = "/fake/path"
        return mgr

    @patch("benchbox.platforms.credentials.snowflake.Confirm.ask")
    def test_user_declines_output_location(self, mock_confirm):
        from benchbox.platforms.credentials.snowflake import _prompt_default_output_location

        mgr = self._make_manager()
        console = Mock()
        mock_confirm.return_value = False

        _prompt_default_output_location(mgr, console, {"account": "acct"})

        mgr.set_platform_credentials.assert_not_called()

    @patch("benchbox.platforms.credentials.snowflake.Prompt.ask")
    @patch("benchbox.platforms.credentials.snowflake.Confirm.ask")
    def test_user_stage_path_saved(self, mock_confirm, mock_prompt):
        from benchbox.platforms.credentials.snowflake import _prompt_default_output_location

        mgr = self._make_manager()
        console = Mock()
        # wants default=True, confirm=True
        mock_confirm.side_effect = [True, True]
        mock_prompt.return_value = "@~/benchbox"

        creds = {"account": "acct"}
        _prompt_default_output_location(mgr, console, creds)

        assert creds["default_output_location"] == "@~/benchbox"
        mgr.set_platform_credentials.assert_called_once()
        mgr.save_credentials.assert_called()

    @patch("benchbox.platforms.credentials.snowflake.Prompt.ask")
    @patch("benchbox.platforms.credentials.snowflake.Confirm.ask")
    @patch("benchbox.utils.cloud_storage.is_cloud_path")
    def test_invalid_path_with_confirmation_proceeds(self, mock_is_cloud, mock_confirm, mock_prompt):
        from benchbox.platforms.credentials.snowflake import _prompt_default_output_location

        mgr = self._make_manager()
        console = Mock()
        # wants default=True, invalid path → proceed anyway=True, confirm=True
        mock_confirm.side_effect = [True, True, True]
        mock_prompt.return_value = "not-a-valid-path"
        mock_is_cloud.return_value = False

        creds = {"account": "acct"}
        _prompt_default_output_location(mgr, console, creds)

        assert creds["default_output_location"] == "not-a-valid-path"

    @patch("benchbox.platforms.credentials.snowflake.Prompt.ask")
    @patch("benchbox.platforms.credentials.snowflake.Confirm.ask")
    @patch("benchbox.utils.cloud_storage.is_cloud_path")
    def test_invalid_path_declined_retries_then_valid(self, mock_is_cloud, mock_confirm, mock_prompt):
        from benchbox.platforms.credentials.snowflake import _prompt_default_output_location

        mgr = self._make_manager()
        console = Mock()
        # wants default=True; 1st path invalid, user declines → retry; 2nd path valid, user confirms
        mock_confirm.side_effect = [True, False, True]
        mock_prompt.side_effect = ["bad-path", "@~/good"]
        mock_is_cloud.side_effect = [False, False]  # called for bad-path only (second is @~)

        creds = {"account": "acct"}
        _prompt_default_output_location(mgr, console, creds)

        assert creds["default_output_location"] == "@~/good"

    @patch("benchbox.platforms.credentials.snowflake.Prompt.ask")
    @patch("benchbox.platforms.credentials.snowflake.Confirm.ask")
    def test_valid_cloud_path_saved(self, mock_confirm, mock_prompt):
        from benchbox.platforms.credentials.snowflake import _prompt_default_output_location

        mgr = self._make_manager()
        console = Mock()
        mock_confirm.side_effect = [True, True]
        mock_prompt.return_value = "s3://my-bucket/data"

        creds = {"account": "acct"}
        _prompt_default_output_location(mgr, console, creds)

        assert creds["default_output_location"] == "s3://my-bucket/data"


# ---------------------------------------------------------------------------
# validate_snowflake_credentials error translation tests
# ---------------------------------------------------------------------------


class TestValidateSnowflakeErrorTranslation:
    """Test that connection errors produce user-friendly messages."""

    def _make_mgr_with_creds(self):
        mgr = Mock()
        mgr.get_platform_credentials.return_value = {
            "account": "acct",
            "username": "u",
            "password": "p",
            "warehouse": "WH",
            "database": "DB",
            "role": "MYROLE",
        }
        return mgr

    def _run_with_error(self, error_message: str):
        from unittest.mock import MagicMock, patch

        from benchbox.platforms.credentials.snowflake import validate_snowflake_credentials

        mock_connector = MagicMock()
        mock_connector.connect.side_effect = Exception(error_message)
        mock_snowflake = MagicMock()
        mock_snowflake.connector = mock_connector

        mgr = self._make_mgr_with_creds()
        with patch.dict("sys.modules", {"snowflake": mock_snowflake, "snowflake.connector": mock_connector}):
            return validate_snowflake_credentials(mgr)

    def test_authentication_error_message(self):
        ok, err = self._run_with_error("incorrect username or password")
        assert ok is False
        assert "Authentication failed" in err

    def test_authentication_keyword_error(self):
        ok, err = self._run_with_error("authentication token expired")
        assert ok is False
        assert "Authentication failed" in err

    def test_account_not_exist_error(self):
        ok, err = self._run_with_error("account xyz does not exist")
        assert ok is False
        assert "Account identifier is invalid" in err

    def test_warehouse_error_message(self):
        ok, err = self._run_with_error("warehouse WH not found")
        assert ok is False
        assert "WH" in err

    def test_database_not_exist_error(self):
        ok, err = self._run_with_error("database DB does not exist")
        assert ok is False
        assert "DB" in err

    def test_role_error_message(self):
        ok, err = self._run_with_error("role MYROLE does not exist")
        assert ok is False
        assert "MYROLE" in err

    def test_generic_error_message(self):
        ok, err = self._run_with_error("network timeout")
        assert ok is False
        assert "Connection failed" in err
        assert "network timeout" in err


# ---------------------------------------------------------------------------
# _auto_detect_snowflake direct tests
# ---------------------------------------------------------------------------


class TestAutoDetectSnowflake:
    """Test _auto_detect_snowflake reads from environment variables."""

    def _console(self):
        from unittest.mock import MagicMock

        return MagicMock()

    def test_returns_dict_when_all_required_vars_set(self):
        from unittest.mock import patch

        from benchbox.platforms.credentials.snowflake import _auto_detect_snowflake

        env = {
            "SNOWFLAKE_ACCOUNT": "myorg-acct",
            "SNOWFLAKE_USERNAME": "joe",
            "SNOWFLAKE_PASSWORD": "secret",
            "SNOWFLAKE_WAREHOUSE": "COMPUTE_WH",
            "SNOWFLAKE_DATABASE": "BENCHBOX",
        }
        with patch.dict("os.environ", env, clear=True):
            result = _auto_detect_snowflake(self._console())

        assert result is not None
        assert result["account"] == "myorg-acct"
        assert result["username"] == "joe"
        assert result["database"] == "BENCHBOX"

    def test_returns_none_when_required_vars_missing(self):
        from unittest.mock import patch

        from benchbox.platforms.credentials.snowflake import _auto_detect_snowflake

        with patch.dict("os.environ", {}, clear=True):
            result = _auto_detect_snowflake(self._console())

        assert result is None

    def test_normalizes_account_strips_snowflakecomputing_com(self):
        from unittest.mock import patch

        from benchbox.platforms.credentials.snowflake import _auto_detect_snowflake

        env = {
            "SNOWFLAKE_ACCOUNT": "acct.snowflakecomputing.com",
            "SNOWFLAKE_USERNAME": "joe",
            "SNOWFLAKE_PASSWORD": "secret",
            "SNOWFLAKE_WAREHOUSE": "COMPUTE_WH",
            "SNOWFLAKE_DATABASE": "BENCHBOX",
        }
        with patch.dict("os.environ", env, clear=True):
            result = _auto_detect_snowflake(self._console())

        assert result is not None
        assert result["account"] == "acct"

    def test_plain_account_unchanged(self):
        from unittest.mock import patch

        from benchbox.platforms.credentials.snowflake import _auto_detect_snowflake

        env = {
            "SNOWFLAKE_ACCOUNT": "myorg-account123",
            "SNOWFLAKE_USERNAME": "joe",
            "SNOWFLAKE_PASSWORD": "secret",
            "SNOWFLAKE_WAREHOUSE": "COMPUTE_WH",
            "SNOWFLAKE_DATABASE": "BENCHBOX",
        }
        with patch.dict("os.environ", env, clear=True):
            result = _auto_detect_snowflake(self._console())

        assert result is not None
        assert result["account"] == "myorg-account123"


# ---------------------------------------------------------------------------
# validate_snowflake_credentials direct tests
# ---------------------------------------------------------------------------


class TestValidateSnowflakeCredentials:
    """Test validate_snowflake_credentials success/failure paths."""

    def _make_cred_manager(self, creds=None):
        from unittest.mock import MagicMock

        mgr = MagicMock()
        mgr.get_platform_credentials.return_value = creds
        return mgr

    def test_returns_false_when_no_credentials(self):
        from benchbox.platforms.credentials.snowflake import validate_snowflake_credentials

        mgr = self._make_cred_manager(None)
        ok, err = validate_snowflake_credentials(mgr)
        assert ok is False
        assert err is not None

    def test_returns_false_when_missing_required_fields(self):
        from benchbox.platforms.credentials.snowflake import validate_snowflake_credentials

        mgr = self._make_cred_manager({"account": "acct"})
        ok, err = validate_snowflake_credentials(mgr)
        assert ok is False
        assert "Missing required fields" in err

    def test_returns_false_when_connector_missing(self):
        import sys
        from unittest.mock import patch

        from benchbox.platforms.credentials.snowflake import validate_snowflake_credentials

        creds = {
            "account": "acct",
            "username": "u",
            "password": "p",
            "warehouse": "WH",
            "database": "DB",
        }
        mgr = self._make_cred_manager(creds)

        with patch.dict(sys.modules, {"snowflake": None, "snowflake.connector": None}):
            ok, err = validate_snowflake_credentials(mgr)

        assert ok is False
        assert err is not None

    def test_returns_true_on_successful_connection(self):
        from unittest.mock import MagicMock, patch

        from benchbox.platforms.credentials.snowflake import validate_snowflake_credentials

        creds = {
            "account": "acct",
            "username": "u",
            "password": "p",
            "warehouse": "WH",
            "database": "DB",
        }
        mgr = self._make_cred_manager(creds)

        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_connector = MagicMock()
        mock_connector.connect.return_value = mock_conn

        mock_snowflake = MagicMock()
        mock_snowflake.connector = mock_connector

        with patch.dict("sys.modules", {"snowflake": mock_snowflake, "snowflake.connector": mock_connector}):
            ok, err = validate_snowflake_credentials(mgr)

        assert ok is True
        assert err is None

    def test_returns_false_on_connection_exception(self):
        from unittest.mock import MagicMock, patch

        from benchbox.platforms.credentials.snowflake import validate_snowflake_credentials

        creds = {
            "account": "acct",
            "username": "u",
            "password": "p",
            "warehouse": "WH",
            "database": "DB",
        }
        mgr = self._make_cred_manager(creds)

        mock_connector = MagicMock()
        mock_connector.connect.side_effect = RuntimeError("authentication failed")

        mock_snowflake = MagicMock()
        mock_snowflake.connector = mock_connector

        with patch.dict("sys.modules", {"snowflake": mock_snowflake, "snowflake.connector": mock_connector}):
            ok, err = validate_snowflake_credentials(mgr)

        assert ok is False
        assert err is not None
