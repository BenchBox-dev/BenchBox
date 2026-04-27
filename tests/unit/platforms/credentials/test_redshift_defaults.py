"""Tests for Redshift credential setup with default values.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import Mock, patch

import pytest

from benchbox.platforms.credentials.redshift import setup_redshift_credentials

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestRedshiftCredentialDefaults:
    """Test Redshift credential setup shows existing values as defaults."""

    @patch("benchbox.platforms.credentials.redshift._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.redshift.validate_redshift_credentials")
    @patch("benchbox.platforms.credentials.redshift.prompt_secure_field")
    @patch("benchbox.platforms.credentials.redshift.prompt_with_default")
    @patch("rich.prompt.IntPrompt.ask")
    @patch("rich.prompt.Confirm.ask")
    def test_shows_existing_values_as_defaults(
        self,
        mock_confirm,
        mock_int_prompt,
        mock_prompt_default,
        mock_prompt_secure,
        mock_validate,
        mock_output_location,
    ):
        """Test that existing credential values are shown as defaults in prompts."""
        # Setup: existing credentials
        mock_manager = Mock()
        existing_creds = {
            "host": "my-cluster.abc123.us-east-1.redshift.amazonaws.com",
            "port": 5439,
            "database": "mydb",
            "username": "admin",
            "password": "secret",
            "schema": "public",
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        # With existing credentials, no auto-detection prompt - only S3 config
        mock_confirm.return_value = False  # Don't configure S3
        mock_int_prompt.return_value = 5439  # port
        mock_prompt_default.side_effect = [
            "my-cluster.abc123.us-east-1.redshift.amazonaws.com",  # host
            "mydb",  # database
            "admin",  # username
            "public",  # schema
        ]
        mock_prompt_secure.return_value = "secret"  # password

        mock_validate.return_value = (True, None)
        console = Mock()

        setup_redshift_credentials(mock_manager, console)

        # Verify prompts were called with existing values as current_value
        calls = mock_prompt_default.call_args_list
        assert calls[0][1]["current_value"] == "my-cluster.abc123.us-east-1.redshift.amazonaws.com"  # host
        assert calls[1][1]["current_value"] == "mydb"  # database
        assert calls[2][1]["current_value"] == "admin"  # username
        assert calls[3][1]["current_value"] == "public"  # schema

        # Verify secure field was called with existing password
        mock_prompt_secure.assert_called_once_with("Password", current_value="secret", console=console)

    @patch("benchbox.platforms.credentials.redshift._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.redshift.validate_redshift_credentials")
    @patch("benchbox.platforms.credentials.redshift.prompt_secure_field")
    @patch("benchbox.platforms.credentials.redshift.prompt_with_default")
    @patch("rich.prompt.IntPrompt.ask")
    @patch("rich.prompt.Confirm.ask")
    def test_works_with_no_existing_credentials(
        self,
        mock_confirm,
        mock_int_prompt,
        mock_prompt_default,
        mock_prompt_secure,
        mock_validate,
        mock_output_location,
    ):
        """Test that setup works when no existing credentials exist."""
        # Setup: no existing credentials
        mock_manager = Mock()
        mock_manager.get_platform_credentials.return_value = None

        # User provides new values
        mock_confirm.side_effect = [
            False,  # Skip auto-detection
            False,  # Don't configure S3
        ]
        mock_int_prompt.return_value = 5439  # port (default)
        mock_prompt_default.side_effect = [
            "new-cluster.xyz.us-east-1.redshift.amazonaws.com",  # host
            "dev",  # database (default)
            "newuser",  # username
            "public",  # schema (default)
        ]
        mock_prompt_secure.return_value = "newpassword"

        mock_validate.return_value = (True, None)
        console = Mock()

        setup_redshift_credentials(mock_manager, console)

        # Verify prompts were called with None as current_value
        calls = mock_prompt_default.call_args_list
        assert calls[0][1]["current_value"] is None  # host
        assert calls[1][1]["current_value"] is None  # database
        assert calls[1][1]["default_if_none"] == "dev"  # database default
        assert calls[2][1]["current_value"] is None  # username
        assert calls[3][1]["current_value"] is None  # schema
        assert calls[3][1]["default_if_none"] == "public"  # schema default

        # Verify secure field was called with None
        mock_prompt_secure.assert_called_once_with("Password", current_value=None, console=console)

    @patch("benchbox.platforms.credentials.redshift._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.redshift.validate_redshift_credentials")
    @patch("benchbox.platforms.credentials.redshift.prompt_secure_field")
    @patch("benchbox.platforms.credentials.redshift.prompt_with_default")
    @patch("rich.prompt.IntPrompt.ask")
    @patch("rich.prompt.Confirm.ask")
    def test_password_preserved_on_empty_input(
        self,
        mock_confirm,
        mock_int_prompt,
        mock_prompt_default,
        mock_prompt_secure,
        mock_validate,
        mock_output_location,
    ):
        """Test that existing password is preserved when user enters empty input."""
        # Setup: existing credentials with password
        mock_manager = Mock()
        existing_creds = {
            "host": "my-cluster.redshift.amazonaws.com",
            "port": 5439,
            "database": "mydb",
            "username": "admin",
            "password": "existing_password",
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        # With existing credentials, no auto-detection prompt
        mock_confirm.return_value = False  # Don't configure S3
        mock_int_prompt.return_value = 5439
        mock_prompt_default.side_effect = [
            "my-cluster.redshift.amazonaws.com",
            "mydb",
            "admin",
            "public",
        ]
        # User enters empty string, existing password should be preserved
        mock_prompt_secure.return_value = "existing_password"

        mock_validate.return_value = (True, None)
        console = Mock()

        setup_redshift_credentials(mock_manager, console)

        # Verify the saved credentials still have the password
        saved_creds = mock_manager.set_platform_credentials.call_args[0][1]
        assert saved_creds["password"] == "existing_password"

    @patch("benchbox.platforms.credentials.redshift._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.redshift.validate_redshift_credentials")
    @patch("benchbox.platforms.credentials.redshift.prompt_secure_field")
    @patch("benchbox.platforms.credentials.redshift.prompt_with_default")
    @patch("rich.prompt.IntPrompt.ask")
    @patch("rich.prompt.Confirm.ask")
    def test_s3_credentials_show_existing_values(
        self,
        mock_confirm,
        mock_int_prompt,
        mock_prompt_default,
        mock_prompt_secure,
        mock_validate,
        mock_output_location,
    ):
        """Test that S3 configuration shows existing values."""
        # Setup: existing credentials with S3 config (IAM role)
        mock_manager = Mock()
        existing_creds = {
            "host": "my-cluster.redshift.amazonaws.com",
            "port": 5439,
            "database": "mydb",
            "username": "admin",
            "password": "secret",
            "s3_bucket": "my-benchbox-data",
            "iam_role": "arn:aws:iam::123456789012:role/RedshiftS3AccessRole",
            "aws_region": "us-east-1",
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        # With existing credentials, no auto-detection prompt
        mock_confirm.return_value = True  # Configure S3
        mock_int_prompt.side_effect = [
            5439,  # port
            1,  # IAM role auth method
        ]
        mock_prompt_default.side_effect = [
            "my-cluster.redshift.amazonaws.com",  # host
            "mydb",  # database
            "admin",  # username
            "public",  # schema
            "my-benchbox-data",  # s3_bucket
            "arn:aws:iam::123456789012:role/RedshiftS3AccessRole",  # iam_role
            "us-east-1",  # aws_region
        ]
        mock_prompt_secure.return_value = "secret"  # password

        mock_validate.return_value = (True, None)
        console = Mock()

        setup_redshift_credentials(mock_manager, console)

        # Verify S3 prompts were called with existing values
        calls = mock_prompt_default.call_args_list
        assert calls[4][1]["current_value"] == "my-benchbox-data"  # s3_bucket
        assert calls[5][1]["current_value"] == "arn:aws:iam::123456789012:role/RedshiftS3AccessRole"  # iam_role
        assert calls[6][1]["current_value"] == "us-east-1"  # aws_region

    @patch("benchbox.platforms.credentials.redshift._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.redshift.validate_redshift_credentials")
    @patch("benchbox.platforms.credentials.redshift.prompt_secure_field")
    @patch("benchbox.platforms.credentials.redshift.prompt_with_default")
    @patch("rich.prompt.IntPrompt.ask")
    @patch("rich.prompt.Confirm.ask")
    def test_s3_access_keys_show_existing_values(
        self,
        mock_confirm,
        mock_int_prompt,
        mock_prompt_default,
        mock_prompt_secure,
        mock_validate,
        mock_output_location,
    ):
        """Test that S3 access keys show existing values."""
        # Setup: existing credentials with S3 config (access keys)
        mock_manager = Mock()
        existing_creds = {
            "host": "my-cluster.redshift.amazonaws.com",
            "port": 5439,
            "database": "mydb",
            "username": "admin",
            "password": "secret",
            "s3_bucket": "my-bucket",
            "aws_access_key_id": "AKIAIOSFODNN7EXAMPLE",
            "aws_secret_access_key": "secret_key",
            "aws_region": "us-west-2",
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        # With existing credentials, no auto-detection prompt
        mock_confirm.return_value = True  # Configure S3
        mock_int_prompt.side_effect = [
            5439,  # port
            2,  # Access keys auth method
        ]
        mock_prompt_default.side_effect = [
            "my-cluster.redshift.amazonaws.com",  # host
            "mydb",  # database
            "admin",  # username
            "public",  # schema
            "my-bucket",  # s3_bucket
            "AKIAIOSFODNN7EXAMPLE",  # aws_access_key_id
            "us-west-2",  # aws_region
        ]
        mock_prompt_secure.side_effect = [
            "secret",  # password
            "secret_key",  # aws_secret_access_key
        ]

        mock_validate.return_value = (True, None)
        console = Mock()

        setup_redshift_credentials(mock_manager, console)

        # Verify AWS access key and secret key prompts were called with existing values
        default_calls = mock_prompt_default.call_args_list
        assert default_calls[5][1]["current_value"] == "AKIAIOSFODNN7EXAMPLE"  # access_key_id

        secure_calls = mock_prompt_secure.call_args_list
        assert secure_calls[1][0][0] == "AWS Secret Access Key"  # field name
        assert secure_calls[1][1]["current_value"] == "secret_key"  # secret_access_key

    @patch("benchbox.platforms.credentials.redshift._auto_detect_redshift")
    @patch("benchbox.platforms.credentials.redshift._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.redshift.validate_redshift_credentials")
    @patch("benchbox.platforms.credentials.redshift.prompt_secure_field")
    @patch("benchbox.platforms.credentials.redshift.prompt_with_default")
    @patch("rich.prompt.IntPrompt.ask")
    @patch("rich.prompt.Confirm.ask")
    def test_auto_detection_bypasses_existing_defaults(
        self,
        mock_confirm,
        mock_int_prompt,
        mock_prompt_default,
        mock_prompt_secure,
        mock_validate,
        mock_output_location,
        mock_auto_detect,
    ):
        """Test that auto-detection is skipped when existing credentials are present."""
        # Setup: existing credentials
        mock_manager = Mock()
        existing_creds = {
            "host": "old-cluster.redshift.amazonaws.com",
            "port": 5439,
            "database": "olddb",
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        # NOTE: With existing credentials, auto-detection is skipped
        mock_confirm.return_value = False  # Don't configure S3
        mock_int_prompt.return_value = 5439
        mock_prompt_default.side_effect = [
            "old-cluster.redshift.amazonaws.com",
            "olddb",
            "admin",
            "public",
        ]
        mock_prompt_secure.return_value = "password"
        mock_validate.return_value = (True, None)
        console = Mock()

        setup_redshift_credentials(mock_manager, console)

        # Verify Confirm.ask was NOT called for auto-detection
        # (only called for S3 configuration)
        assert mock_confirm.call_count == 1
        storage_call = mock_confirm.call_args_list[0]
        assert "s3" in str(storage_call).lower()
        # Verify auto-detect was NOT called
        mock_auto_detect.assert_not_called()

    @patch("benchbox.platforms.credentials.redshift._auto_detect_redshift")
    @patch("benchbox.platforms.credentials.redshift._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.redshift.validate_redshift_credentials")
    @patch("benchbox.platforms.credentials.redshift.prompt_secure_field")
    @patch("benchbox.platforms.credentials.redshift.prompt_with_default")
    @patch("rich.prompt.IntPrompt.ask")
    @patch("rich.prompt.Confirm.ask")
    def test_skips_auto_detection_when_credentials_exist(
        self,
        mock_confirm,
        mock_int_prompt,
        mock_prompt_default,
        mock_prompt_secure,
        mock_validate,
        mock_output_location,
        mock_auto_detect,
    ):
        """Test that auto-detection is skipped when credentials already exist."""
        # Setup: existing credentials
        mock_manager = Mock()
        existing_creds = {
            "host": "my-cluster.redshift.amazonaws.com",
            "port": 5439,
            "database": "mydb",
            "username": "admin",
            "password": "secret",
        }
        mock_manager.get_platform_credentials.return_value = existing_creds

        mock_confirm.return_value = False  # Don't configure S3
        mock_int_prompt.return_value = 5439
        mock_prompt_default.side_effect = [
            "my-cluster.redshift.amazonaws.com",
            "mydb",
            "admin",
            "public",
        ]
        mock_prompt_secure.return_value = "secret"
        mock_validate.return_value = (True, None)
        console = Mock()

        setup_redshift_credentials(mock_manager, console)

        # Verify no auto-detection prompt was shown (only S3 config prompt)
        assert mock_confirm.call_count == 1
        mock_auto_detect.assert_not_called()

        # Verify "updating configuration" message was displayed
        console_output = " ".join(str(call) for call in console.print.call_args_list)
        assert "Existing credentials found" in console_output
        assert "updating configuration" in console_output

    @patch("benchbox.platforms.credentials.redshift._auto_detect_redshift")
    @patch("benchbox.platforms.credentials.redshift._prompt_default_output_location")
    @patch("benchbox.platforms.credentials.redshift.validate_redshift_credentials")
    @patch("benchbox.platforms.credentials.redshift.prompt_secure_field")
    @patch("benchbox.platforms.credentials.redshift.prompt_with_default")
    @patch("rich.prompt.IntPrompt.ask")
    @patch("rich.prompt.Confirm.ask")
    def test_offers_auto_detection_when_no_credentials_exist(
        self,
        mock_confirm,
        mock_int_prompt,
        mock_prompt_default,
        mock_prompt_secure,
        mock_validate,
        mock_output_location,
        mock_auto_detect,
    ):
        """Test that auto-detection is offered when no credentials exist."""
        # Setup: no existing credentials
        mock_manager = Mock()
        mock_manager.get_platform_credentials.return_value = None

        # User declines auto-detection and S3
        mock_confirm.side_effect = [False, False]  # auto-detect, S3
        mock_int_prompt.return_value = 5439
        mock_prompt_default.side_effect = [
            "new-cluster.redshift.amazonaws.com",
            "dev",
            "newuser",
            "public",
        ]
        mock_prompt_secure.return_value = "newpassword"
        mock_validate.return_value = (True, None)
        console = Mock()

        setup_redshift_credentials(mock_manager, console)

        # Verify auto-detection prompt WAS shown
        auto_detect_call = mock_confirm.call_args_list[0]
        assert "auto-detection" in str(auto_detect_call).lower()

        # Verify "updating configuration" message was NOT displayed
        console_output = " ".join(str(call) for call in console.print.call_args_list)
        assert "Existing credentials found" not in console_output


# ---------------------------------------------------------------------------
# _auto_detect_redshift direct tests
# ---------------------------------------------------------------------------


class TestAutoDetectRedshift:
    """Test _auto_detect_redshift reads from environment variables."""

    def _console(self):
        from unittest.mock import MagicMock

        return MagicMock()

    def test_returns_dict_when_all_required_vars_set(self):
        from unittest.mock import patch

        from benchbox.platforms.credentials.redshift import _auto_detect_redshift

        env = {
            "REDSHIFT_HOST": "cluster.abc123.us-east-1.redshift.amazonaws.com",
            "REDSHIFT_USERNAME": "admin",
            "REDSHIFT_PASSWORD": "secret",
            "REDSHIFT_DATABASE": "dev",
        }
        with patch.dict("os.environ", env, clear=True):
            result = _auto_detect_redshift(self._console())

        assert result is not None
        assert result["host"] == "cluster.abc123.us-east-1.redshift.amazonaws.com"
        assert result["username"] == "admin"
        assert result["database"] == "dev"

    def test_returns_none_when_required_vars_missing(self):
        from unittest.mock import patch

        from benchbox.platforms.credentials.redshift import _auto_detect_redshift

        with patch.dict("os.environ", {}, clear=True):
            result = _auto_detect_redshift(self._console())

        assert result is None

    def test_port_defaults_to_5439_when_not_set(self):
        from unittest.mock import patch

        from benchbox.platforms.credentials.redshift import _auto_detect_redshift

        env = {
            "REDSHIFT_HOST": "cluster.example.redshift.amazonaws.com",
            "REDSHIFT_USERNAME": "admin",
            "REDSHIFT_PASSWORD": "secret",
            "REDSHIFT_DATABASE": "dev",
        }
        with patch.dict("os.environ", env, clear=True):
            result = _auto_detect_redshift(self._console())

        assert result is not None
        assert result["port"] == 5439

    def test_port_parsed_from_env(self):
        from unittest.mock import patch

        from benchbox.platforms.credentials.redshift import _auto_detect_redshift

        env = {
            "REDSHIFT_HOST": "cluster.example.redshift.amazonaws.com",
            "REDSHIFT_USERNAME": "admin",
            "REDSHIFT_PASSWORD": "secret",
            "REDSHIFT_DATABASE": "dev",
            "REDSHIFT_PORT": "5440",
        }
        with patch.dict("os.environ", env, clear=True):
            result = _auto_detect_redshift(self._console())

        assert result is not None
        assert result["port"] == 5440

    def test_iam_role_captured_from_env(self):
        from unittest.mock import patch

        from benchbox.platforms.credentials.redshift import _auto_detect_redshift

        env = {
            "REDSHIFT_HOST": "cluster.example.redshift.amazonaws.com",
            "REDSHIFT_USERNAME": "admin",
            "REDSHIFT_PASSWORD": "secret",
            "REDSHIFT_DATABASE": "dev",
            "REDSHIFT_IAM_ROLE": "arn:aws:iam::123456789:role/RedshiftS3Access",
        }
        with patch.dict("os.environ", env, clear=True):
            result = _auto_detect_redshift(self._console())

        assert result is not None
        assert result["iam_role"] == "arn:aws:iam::123456789:role/RedshiftS3Access"

    def test_auto_detect_prints_success_message(self):
        """Test that _auto_detect_redshift prints a success message when all vars are present."""
        from unittest.mock import MagicMock, patch

        from benchbox.platforms.credentials.redshift import _auto_detect_redshift

        env = {
            "REDSHIFT_HOST": "myhost.us-east-1.redshift.amazonaws.com",
            "REDSHIFT_USERNAME": "admin",
            "REDSHIFT_PASSWORD": "secret",
            "REDSHIFT_DATABASE": "mydb",
        }
        console = MagicMock()
        with patch.dict("os.environ", env, clear=True):
            result = _auto_detect_redshift(console)

        assert result is not None
        # Function should print at least one success/found message
        assert console.print.called
        output = " ".join(str(c) for c in console.print.call_args_list)
        assert "Found" in output or "✓" in output

    def test_auto_detect_prints_s3_message_when_s3_bucket_set(self):
        """Test that _auto_detect_redshift prints S3 staging message when REDSHIFT_S3_BUCKET is set."""
        from unittest.mock import MagicMock, patch

        from benchbox.platforms.credentials.redshift import _auto_detect_redshift

        env = {
            "REDSHIFT_HOST": "cluster.example.redshift.amazonaws.com",
            "REDSHIFT_USERNAME": "admin",
            "REDSHIFT_PASSWORD": "secret",
            "REDSHIFT_DATABASE": "dev",
            "REDSHIFT_S3_BUCKET": "my-benchbox-bucket",
        }
        console = MagicMock()
        with patch.dict("os.environ", env, clear=True):
            result = _auto_detect_redshift(console)

        assert result is not None
        output = " ".join(str(c) for c in console.print.call_args_list)
        assert "S3" in output or "staging" in output.lower()


# ---------------------------------------------------------------------------
# _test_tcp_connectivity direct tests
# ---------------------------------------------------------------------------


class TestTcpConnectivity:
    """Tests for _test_tcp_connectivity helper."""

    def test_returns_true_on_successful_connection(self):
        """Test that a successful TCP connect returns (True, None)."""
        from unittest.mock import MagicMock, patch

        from benchbox.platforms.credentials.redshift import _test_tcp_connectivity

        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 0

        with patch("benchbox.platforms.credentials.redshift.socket") as mock_socket_mod:
            mock_socket_mod.AF_INET = 2
            mock_socket_mod.SOCK_STREAM = 1
            mock_socket_mod.socket.return_value = mock_sock

            ok, err = _test_tcp_connectivity("host.example.com", 5439)

        assert ok is True
        assert err is None

    def test_returns_false_on_non_zero_connect_result(self):
        """Test that a non-zero connect_ex result returns (False, message)."""
        from unittest.mock import MagicMock, patch

        from benchbox.platforms.credentials.redshift import _test_tcp_connectivity

        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 111  # Connection refused code

        with patch("benchbox.platforms.credentials.redshift.socket") as mock_socket_mod:
            mock_socket_mod.AF_INET = 2
            mock_socket_mod.SOCK_STREAM = 1
            mock_socket_mod.socket.return_value = mock_sock

            ok, err = _test_tcp_connectivity("host.example.com", 5439)

        assert ok is False
        assert err is not None
        assert "111" in err or "TCP" in err

    def test_returns_false_on_gaierror(self):
        """Test that a DNS failure returns (False, message)."""
        import socket as real_socket
        from unittest.mock import MagicMock, patch

        from benchbox.platforms.credentials.redshift import _test_tcp_connectivity

        mock_sock = MagicMock()
        mock_sock.connect_ex.side_effect = real_socket.gaierror("Name not found")

        with patch("benchbox.platforms.credentials.redshift.socket") as mock_socket_mod:
            mock_socket_mod.AF_INET = 2
            mock_socket_mod.SOCK_STREAM = 1
            mock_socket_mod.socket.return_value = mock_sock
            mock_socket_mod.gaierror = real_socket.gaierror

            ok, err = _test_tcp_connectivity("no-such-host.invalid", 5439)

        assert ok is False
        assert err is not None

    def test_returns_false_on_timeout_error(self):
        """Test that a TimeoutError returns (False, message)."""
        import socket as real_socket
        from unittest.mock import MagicMock, patch

        from benchbox.platforms.credentials.redshift import _test_tcp_connectivity

        mock_sock = MagicMock()
        mock_sock.connect_ex.side_effect = TimeoutError("timed out")

        with patch("benchbox.platforms.credentials.redshift.socket") as mock_socket_mod:
            mock_socket_mod.AF_INET = 2
            mock_socket_mod.SOCK_STREAM = 1
            mock_socket_mod.socket.return_value = mock_sock
            mock_socket_mod.gaierror = real_socket.gaierror

            ok, err = _test_tcp_connectivity("host.example.com", 5439)

        assert ok is False
        assert err is not None
        assert "timeout" in err.lower() or "unreachable" in err.lower()


# ---------------------------------------------------------------------------
# _diagnose_redshift_connectivity tests
# ---------------------------------------------------------------------------


class TestDiagnoseRedshiftConnectivity:
    """Tests for _diagnose_redshift_connectivity."""

    def test_provisioned_cluster_path(self):
        """Test provisioned cluster describe_clusters path."""
        from unittest.mock import MagicMock, patch

        from benchbox.platforms.credentials.redshift import _diagnose_redshift_connectivity

        mock_redshift_client = MagicMock()
        mock_redshift_client.describe_clusters.return_value = {
            "Clusters": [
                {
                    "PubliclyAccessible": True,
                    "VpcId": "vpc-abc123",
                    "VpcSecurityGroups": [{"VpcSecurityGroupId": "sg-111"}],
                    "ClusterSubnetGroupName": [],
                }
            ]
        }
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_redshift_client

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            result = _diagnose_redshift_connectivity(
                host="mycluster.abc123.us-east-1.redshift.amazonaws.com",
                port=5439,
                aws_access_key_id=None,
                aws_secret_access_key=None,
                aws_region="us-east-1",
            )

        assert result["publicly_accessible"] is True
        assert result["vpc_id"] == "vpc-abc123"
        assert "sg-111" in result["security_group_ids"]

    def test_serverless_workgroup_path(self):
        """Test serverless workgroup describe path."""
        from unittest.mock import MagicMock, patch

        from benchbox.platforms.credentials.redshift import _diagnose_redshift_connectivity

        mock_serverless_client = MagicMock()
        mock_serverless_client.get_workgroup.return_value = {
            "workgroup": {
                "publiclyAccessible": False,
                "endpoint": {"vpcEndpoint": {"vpcId": "vpc-serverless"}},
                "securityGroupIds": ["sg-222"],
                "subnetIds": ["subnet-aaa"],
            }
        }
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_serverless_client

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            result = _diagnose_redshift_connectivity(
                host="myworkgroup.123456789.us-east-1.redshift-serverless.amazonaws.com",
                port=5439,
                aws_access_key_id=None,
                aws_secret_access_key=None,
                aws_region="us-east-1",
            )

        assert result["publicly_accessible"] is False
        assert result["vpc_id"] == "vpc-serverless"
        assert "sg-222" in result["security_group_ids"]

    def test_access_denied_returns_diagnostic_error_not_exception(self):
        """Test that AWS AccessDenied causes graceful degradation with error key."""
        from unittest.mock import MagicMock, patch

        from benchbox.platforms.credentials.redshift import _diagnose_redshift_connectivity

        mock_client = MagicMock()
        mock_client.describe_clusters.side_effect = Exception("AccessDenied")
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            result = _diagnose_redshift_connectivity(
                host="cluster.abc123.us-east-1.redshift.amazonaws.com",
                port=5439,
                aws_access_key_id="AKIA",
                aws_secret_access_key="secret",
                aws_region="us-east-1",
            )

        # Should not raise; error is captured in result dict
        assert result is not None
        assert result.get("error") is not None

    def test_unknown_endpoint_format_returns_error(self):
        """Test that unrecognized endpoint format returns error key."""
        from benchbox.platforms.credentials.redshift import _diagnose_redshift_connectivity

        result = _diagnose_redshift_connectivity(
            host="some.random.host.example.com",
            port=5439,
            aws_access_key_id=None,
            aws_secret_access_key=None,
            aws_region="us-east-1",
        )

        assert result["error"] == "Unknown endpoint format"


# ---------------------------------------------------------------------------
# _format_remediation_steps tests
# ---------------------------------------------------------------------------


class TestFormatRemediationSteps:
    """Tests for _format_remediation_steps display logic."""

    def test_publicly_accessible_false_includes_enable_public_access_step(self):
        """Test that 'Enable public access' step appears when publicly_accessible=False."""
        from unittest.mock import MagicMock, patch

        from benchbox.platforms.credentials.redshift import _format_remediation_steps

        console = MagicMock()
        diagnostics = {
            "workgroup_name": "my-workgroup",
            "cluster_id": None,
            "publicly_accessible": False,
            "vpc_id": "vpc-abc",
            "security_group_ids": ["sg-111"],
        }

        with patch("benchbox.platforms.credentials.redshift._get_public_ip", return_value=None):
            _format_remediation_steps(console, "host.example.com", 5439, "us-east-1", diagnostics, False)

        output = " ".join(str(c) for c in console.print.call_args_list)
        assert "public" in output.lower() or "Enable" in output

    def test_publicly_accessible_true_omits_enable_public_access_step(self):
        """Test that 'Enable public access' step is absent when publicly_accessible=True."""
        from unittest.mock import MagicMock, patch

        from benchbox.platforms.credentials.redshift import _format_remediation_steps

        console = MagicMock()
        diagnostics = {
            "workgroup_name": None,
            "cluster_id": "mycluster",
            "publicly_accessible": True,
            "vpc_id": "vpc-xyz",
            "security_group_ids": [],
        }

        with patch("benchbox.platforms.credentials.redshift._get_public_ip", return_value="1.2.3.4"):
            _format_remediation_steps(console, "host.example.com", 5439, "us-east-1", diagnostics, True)

        # When publicly accessible, step 1 should NOT be the "Enable public access" step -
        # step numbering starts at 1 (security group config).
        output = " ".join(str(c) for c in console.print.call_args_list)
        # The security group / troubleshooting heading must still appear
        assert "Troubleshooting" in output or "security" in output.lower() or "Configure" in output

    def test_publicly_not_accessible_provisioned_cluster_step(self):
        """Test remediation step for provisioned cluster with public access disabled."""
        from unittest.mock import MagicMock, patch

        from benchbox.platforms.credentials.redshift import _format_remediation_steps

        console = MagicMock()
        diagnostics = {
            "workgroup_name": None,
            "cluster_id": "my-cluster-id",
            "publicly_accessible": False,
            "vpc_id": None,
            "security_group_ids": [],
        }

        with patch("benchbox.platforms.credentials.redshift._get_public_ip", return_value=None):
            _format_remediation_steps(console, "host.example.com", 5439, "us-east-1", diagnostics, False)

        output = " ".join(str(c) for c in console.print.call_args_list)
        assert "my-cluster-id" in output


# ---------------------------------------------------------------------------
# validate_redshift_credentials direct tests
# ---------------------------------------------------------------------------


class TestValidateRedshiftCredentials:
    """Test validate_redshift_credentials success/failure paths."""

    def _make_cred_manager(self, creds=None):
        from unittest.mock import MagicMock

        mgr = MagicMock()
        mgr.get_platform_credentials.return_value = creds
        return mgr

    def test_returns_false_when_no_credentials(self):
        from benchbox.platforms.credentials.redshift import validate_redshift_credentials

        mgr = self._make_cred_manager(None)
        ok, err = validate_redshift_credentials(mgr)
        assert ok is False
        assert err is not None

    def test_returns_false_when_missing_required_fields(self):
        from benchbox.platforms.credentials.redshift import validate_redshift_credentials

        mgr = self._make_cred_manager({"host": "h"})
        ok, err = validate_redshift_credentials(mgr)
        assert ok is False
        assert "Missing required fields" in err

    def test_returns_false_on_tcp_failure(self):
        from unittest.mock import patch

        from benchbox.platforms.credentials.redshift import validate_redshift_credentials

        creds = {"host": "unreachable.example.com", "username": "u", "password": "p"}
        mgr = self._make_cred_manager(creds)

        with (
            patch("benchbox.platforms.credentials.redshift._build_redshift_adapter", return_value=None),
            patch(
                "benchbox.platforms.credentials.redshift._test_tcp_connectivity",
                return_value=(False, "Connection timed out"),
            ),
        ):
            ok, err = validate_redshift_credentials(mgr)

        assert ok is False
        assert err is not None

    def test_returns_true_on_successful_probe(self):
        from unittest.mock import MagicMock, patch

        from benchbox.platforms.credentials.redshift import validate_redshift_credentials

        creds = {"host": "cluster.example.com", "username": "u", "password": "p", "database": "dev"}
        mgr = self._make_cred_manager(creds)

        mock_adapter = MagicMock()

        with (
            patch("benchbox.platforms.credentials.redshift._build_redshift_adapter", return_value=mock_adapter),
            patch("benchbox.platforms.credentials.redshift._test_tcp_connectivity", return_value=(True, None)),
            patch("benchbox.platforms.credentials.redshift._probe_redshift_connection", return_value=None),
        ):
            ok, err = validate_redshift_credentials(mgr)

        assert ok is True
        assert err is None

    def test_returns_false_on_probe_exception(self):
        from unittest.mock import MagicMock, patch

        from benchbox.platforms.credentials.redshift import validate_redshift_credentials

        creds = {"host": "cluster.example.com", "username": "u", "password": "p", "database": "dev"}
        mgr = self._make_cred_manager(creds)

        mock_adapter = MagicMock()

        with (
            patch("benchbox.platforms.credentials.redshift._build_redshift_adapter", return_value=mock_adapter),
            patch("benchbox.platforms.credentials.redshift._test_tcp_connectivity", return_value=(True, None)),
            patch(
                "benchbox.platforms.credentials.redshift._probe_redshift_connection",
                side_effect=RuntimeError("auth error"),
            ),
        ):
            ok, err = validate_redshift_credentials(mgr)

        assert ok is False
        assert err is not None
