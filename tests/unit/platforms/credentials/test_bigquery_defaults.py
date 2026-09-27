"""Tests for BigQuery credential setup with default values.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import Mock, mock_open, patch

import pytest

from benchbox.platforms.credentials.bigquery import setup_bigquery_credentials

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestBigQueryCredentialDefaults:
    """Test BigQuery credential setup shows existing values as defaults."""

    # NOTE: Confirm is patched through the module under test
    # (``...bigquery.Confirm.ask``), not via ``rich.prompt.Confirm.ask``. Both
    # resolve to the same attribute today, but the module-resolved target keeps
    # working if another test file on the same xdist worker replaces the global
    # ``rich.prompt.Confirm`` without cleanup: the global patch would then mock a
    # stale object while production code calls the real prompt (seen as
    # ``call_count == 0`` in full-suite CI while every smaller scope passes).

    @patch("benchbox.platforms.credentials.bigquery._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.bigquery.validate_bigquery_credentials")
    @patch("benchbox.platforms.credentials.bigquery.Path")
    @patch("builtins.open", new_callable=mock_open, read_data='{"type": "service_account"}')
    @patch("benchbox.platforms.credentials.bigquery.prompt_with_default")
    @patch("benchbox.platforms.credentials.bigquery.Confirm.ask")
    def test_shows_existing_values_as_defaults(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_file,
        mock_path,
        mock_validate,
        mock_output_location,
    ):
        """Test that existing credential values are shown as defaults in prompts."""
        # Setup: existing credentials
        mock_manager = Mock()
        existing_creds = {
            "project_id": "my-gcp-project",
            "credentials_path": "/path/to/key.json",
            "dataset_id": "my_dataset",
            "location": "US",
            "storage_bucket": "my-bucket",
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        # Mock file path validation
        mock_path_obj = Mock()
        mock_path_obj.exists.return_value = True
        mock_path_obj.is_file.return_value = True
        mock_path.return_value = mock_path_obj

        # With existing credentials, no auto-detection prompt - only storage config
        mock_confirm.return_value = True  # Configure storage
        mock_prompt_default.side_effect = [
            "my-gcp-project",  # project_id
            "/path/to/key.json",  # credentials_path
            "my_dataset",  # dataset_id
            "US",  # location
            "my-bucket",  # storage_bucket
        ]

        mock_validate.return_value = (True, None)
        console = Mock()

        setup_bigquery_credentials(mock_manager, console)

        # Verify prompts were called with existing values as current_value
        calls = mock_prompt_default.call_args_list
        assert calls[0][1]["current_value"] == "my-gcp-project"  # project_id
        assert calls[1][1]["current_value"] == "/path/to/key.json"  # credentials_path
        assert calls[2][1]["current_value"] == "my_dataset"  # dataset_id
        assert calls[3][1]["current_value"] == "US"  # location
        assert calls[4][1]["current_value"] == "my-bucket"  # storage_bucket

    @patch("benchbox.platforms.credentials.bigquery._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.bigquery.validate_bigquery_credentials")
    @patch("benchbox.platforms.credentials.bigquery.Path")
    @patch("builtins.open", new_callable=mock_open, read_data='{"type": "service_account"}')
    @patch("benchbox.platforms.credentials.bigquery.prompt_with_default")
    @patch("benchbox.platforms.credentials.bigquery.Confirm.ask")
    def test_works_with_no_existing_credentials(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_file,
        mock_path,
        mock_validate,
        mock_output_location,
    ):
        """Test that setup works when no existing credentials exist."""
        # Setup: no existing credentials
        mock_manager = Mock()
        mock_manager.get_platform_credentials.return_value = None

        # Mock file path validation
        mock_path_obj = Mock()
        mock_path_obj.exists.return_value = True
        mock_path_obj.is_file.return_value = True
        mock_path.return_value = mock_path_obj

        # User provides new values
        mock_confirm.side_effect = [
            False,  # Skip auto-detection
            False,  # Don't configure storage
        ]
        mock_prompt_default.side_effect = [
            "new-project",  # project_id
            "/new/path/key.json",  # credentials_path
            "benchbox",  # dataset_id
            "US",  # location
        ]

        mock_validate.return_value = (True, None)
        console = Mock()

        setup_bigquery_credentials(mock_manager, console)

        # Verify prompts were called with None as current_value
        calls = mock_prompt_default.call_args_list
        assert calls[0][1]["current_value"] is None  # project_id
        assert calls[1][1]["current_value"] is None  # credentials_path
        assert calls[2][1]["current_value"] is None  # dataset_id
        assert calls[3][1]["current_value"] is None  # location

    @patch("benchbox.platforms.credentials.bigquery._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.bigquery.validate_bigquery_credentials")
    @patch("benchbox.platforms.credentials.bigquery.Path")
    @patch("builtins.open", new_callable=mock_open, read_data='{"type": "service_account"}')
    @patch("benchbox.platforms.credentials.bigquery.prompt_with_default")
    @patch("benchbox.platforms.credentials.bigquery.Confirm.ask")
    def test_partial_existing_credentials(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_file,
        mock_path,
        mock_validate,
        mock_output_location,
    ):
        """Test handling of partial existing credentials."""
        # Setup: only some credentials exist
        mock_manager = Mock()
        existing_creds = {
            "project_id": "my-gcp-project",
            "credentials_path": "/path/to/key.json",
            # dataset_id, location missing
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        # Mock file path validation
        mock_path_obj = Mock()
        mock_path_obj.exists.return_value = True
        mock_path_obj.is_file.return_value = True
        mock_path.return_value = mock_path_obj

        mock_confirm.side_effect = [
            False,  # Skip auto-detection
            False,  # Don't configure storage
        ]
        mock_prompt_default.side_effect = [
            "my-gcp-project",  # existing
            "/path/to/key.json",  # existing
            "benchbox",  # new (uses default_if_none)
            "US",  # new (uses default_if_none)
        ]

        mock_validate.return_value = (True, None)
        console = Mock()

        setup_bigquery_credentials(mock_manager, console)

        # Verify existing values were used as defaults
        calls = mock_prompt_default.call_args_list
        assert calls[0][1]["current_value"] == "my-gcp-project"
        assert calls[1][1]["current_value"] == "/path/to/key.json"
        # Missing fields should have None as current_value but have default_if_none
        assert calls[2][1]["current_value"] is None
        assert calls[2][1]["default_if_none"] == "benchbox"
        assert calls[3][1]["current_value"] is None
        assert calls[3][1]["default_if_none"] == "US"

    @patch("benchbox.platforms.credentials.bigquery._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.bigquery._auto_detect_bigquery")
    @patch("benchbox.platforms.credentials.bigquery.validate_bigquery_credentials")
    @patch("benchbox.platforms.credentials.bigquery.Path")
    @patch("builtins.open", new_callable=mock_open, read_data='{"type": "service_account"}')
    @patch("benchbox.platforms.credentials.bigquery.prompt_with_default")
    @patch("benchbox.platforms.credentials.bigquery.Confirm.ask")
    def test_auto_detection_bypasses_existing_defaults(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_file,
        mock_path,
        mock_validate,
        mock_auto_detect,
        mock_output_location,
    ):
        """Test that auto-detection is skipped when existing credentials are present."""
        # Setup: existing credentials
        mock_manager = Mock()
        existing_creds = {
            "project_id": "old-project",
            "credentials_path": "/old/path.json",
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        # Mock file path validation
        mock_path_obj = Mock()
        mock_path_obj.exists.return_value = True
        mock_path_obj.is_file.return_value = True
        mock_path.return_value = mock_path_obj

        # NOTE: With existing credentials, auto-detection is skipped
        mock_confirm.return_value = False  # Don't configure storage
        mock_prompt_default.side_effect = [
            "old-project",
            "/old/path.json",
            "benchbox",
            "US",
        ]
        mock_validate.return_value = (True, None)
        console = Mock()

        setup_bigquery_credentials(mock_manager, console)

        # Verify Confirm.ask was NOT called for auto-detection
        # (only called for storage configuration)
        assert mock_confirm.call_count == 1
        storage_call = mock_confirm.call_args_list[0]
        assert "storage" in str(storage_call).lower()
        # Verify auto-detect was NOT called
        mock_auto_detect.assert_not_called()

    @patch("benchbox.platforms.credentials.bigquery._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.bigquery._auto_detect_bigquery")
    @patch("benchbox.platforms.credentials.bigquery.validate_bigquery_credentials")
    @patch("benchbox.platforms.credentials.bigquery.Path")
    @patch("builtins.open", new_callable=mock_open, read_data='{"type": "service_account"}')
    @patch("benchbox.platforms.credentials.bigquery.prompt_with_default")
    @patch("benchbox.platforms.credentials.bigquery.Confirm.ask")
    def test_skips_auto_detection_when_credentials_exist(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_file,
        mock_path,
        mock_validate,
        mock_auto_detect,
        mock_output_location,
    ):
        """Test that auto-detection is skipped when credentials already exist."""
        # Setup: existing credentials
        mock_manager = Mock()
        existing_creds = {
            "project_id": "my-gcp-project",
            "credentials_path": "/path/to/key.json",
            "dataset_id": "my_dataset",
            "location": "US",
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        # Mock file path validation
        mock_path_obj = Mock()
        mock_path_obj.exists.return_value = True
        mock_path_obj.is_file.return_value = True
        mock_path.return_value = mock_path_obj

        mock_confirm.return_value = False  # Don't configure storage
        mock_prompt_default.side_effect = [
            "my-gcp-project",
            "/path/to/key.json",
            "my_dataset",
            "US",
        ]
        mock_validate.return_value = (True, None)
        console = Mock()

        setup_bigquery_credentials(mock_manager, console)

        # Verify no auto-detection prompt was shown (only storage config prompt)
        assert mock_confirm.call_count == 1
        mock_auto_detect.assert_not_called()

        # Verify "updating configuration" message was displayed
        console_output = " ".join(str(call) for call in console.print.call_args_list)
        assert "Existing credentials found" in console_output
        assert "updating configuration" in console_output

    @patch("benchbox.platforms.credentials.bigquery._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.bigquery._auto_detect_bigquery")
    @patch("benchbox.platforms.credentials.bigquery.validate_bigquery_credentials")
    @patch("benchbox.platforms.credentials.bigquery.Path")
    @patch("builtins.open", new_callable=mock_open, read_data='{"type": "service_account"}')
    @patch("benchbox.platforms.credentials.bigquery.prompt_with_default")
    @patch("benchbox.platforms.credentials.bigquery.Confirm.ask")
    def test_offers_auto_detection_when_no_credentials_exist(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_file,
        mock_path,
        mock_validate,
        mock_auto_detect,
        mock_output_location,
    ):
        """Test that auto-detection is offered when no credentials exist."""
        # Setup: no existing credentials
        mock_manager = Mock()
        mock_manager.get_platform_credentials.return_value = None

        # Mock file path validation
        mock_path_obj = Mock()
        mock_path_obj.exists.return_value = True
        mock_path_obj.is_file.return_value = True
        mock_path.return_value = mock_path_obj

        # User declines auto-detection and storage
        mock_confirm.side_effect = [False, False]  # auto-detect, storage
        mock_prompt_default.side_effect = [
            "new-project",
            "/new/path.json",
            "benchbox",
            "US",
        ]
        mock_validate.return_value = (True, None)
        console = Mock()

        setup_bigquery_credentials(mock_manager, console)

        # Verify auto-detection prompt WAS shown
        auto_detect_call = mock_confirm.call_args_list[0]
        assert "auto-detection" in str(auto_detect_call).lower()

        # Verify "updating configuration" message was NOT displayed
        console_output = " ".join(str(call) for call in console.print.call_args_list)
        assert "Existing credentials found" not in console_output

    @patch("benchbox.platforms.credentials.bigquery._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.bigquery.validate_bigquery_credentials")
    @patch("benchbox.platforms.credentials.bigquery.Path")
    @patch("builtins.open", new_callable=mock_open, read_data='{"type": "service_account"}')
    @patch("benchbox.platforms.credentials.bigquery.prompt_with_default")
    @patch("benchbox.platforms.credentials.bigquery.Confirm.ask")
    def test_storage_bucket_shows_existing_value(
        self,
        mock_confirm,
        mock_prompt_default,
        mock_file,
        mock_path,
        mock_validate,
        mock_output_location,
    ):
        """Test that optional storage bucket shows existing value."""
        # Setup: credentials with storage bucket
        mock_manager = Mock()
        existing_creds = {
            "project_id": "my-gcp-project",
            "credentials_path": "/path/to/key.json",
            "dataset_id": "my_dataset",
            "location": "US",
            "storage_bucket": "existing-bucket",
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        # Mock file path validation
        mock_path_obj = Mock()
        mock_path_obj.exists.return_value = True
        mock_path_obj.is_file.return_value = True
        mock_path.return_value = mock_path_obj

        # With existing credentials, no auto-detection prompt - only storage config
        mock_confirm.return_value = True  # Configure storage
        mock_prompt_default.side_effect = [
            "my-gcp-project",
            "/path/to/key.json",
            "my_dataset",
            "US",
            "existing-bucket",
        ]

        mock_validate.return_value = (True, None)
        console = Mock()

        setup_bigquery_credentials(mock_manager, console)

        # Verify storage bucket was called with existing value
        calls = mock_prompt_default.call_args_list
        assert calls[4][1]["current_value"] == "existing-bucket"
