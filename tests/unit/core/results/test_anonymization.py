"""Tests for benchbox.core.results.anonymization module.

Tests the anonymization system with focus on stable machine ID generation
across different operating systems and configurations.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import subprocess
import sys
from unittest.mock import MagicMock, Mock, mock_open, patch

import pytest

from benchbox.core.results.anonymization import AnonymizationConfig, AnonymizationManager

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestAnonymizationMachineID:
    """Test suite for machine ID generation and stability."""

    def test_machine_id_is_string(self):
        """Test that machine ID is returned as a string."""
        manager = AnonymizationManager()
        machine_id = manager.get_anonymous_machine_id()

        assert isinstance(machine_id, str)
        assert machine_id.startswith("machine_")
        assert len(machine_id) == 24  # "machine_" + 16 hex chars

    def test_machine_id_stability_within_instance(self):
        """Test that machine ID is stable across multiple calls on same instance."""
        manager = AnonymizationManager()

        id1 = manager.get_anonymous_machine_id()
        id2 = manager.get_anonymous_machine_id()
        id3 = manager.get_anonymous_machine_id()

        assert id1 == id2 == id3

    def test_machine_id_stability_across_instances(self):
        """Test that machine ID is stable across different AnonymizationManager instances.

        This is the key test that was failing before the OS-level ID implementation.
        """
        manager1 = AnonymizationManager()
        manager2 = AnonymizationManager()
        manager3 = AnonymizationManager()

        id1 = manager1.get_anonymous_machine_id()
        id2 = manager2.get_anonymous_machine_id()
        id3 = manager3.get_anonymous_machine_id()

        assert id1 == id2 == id3, "Machine IDs should be identical across instances"

    def test_machine_id_uses_cache(self):
        """Test that machine ID is properly cached after first generation."""
        manager = AnonymizationManager()

        # First call should generate and cache
        assert manager._machine_id_cache is None
        id1 = manager.get_anonymous_machine_id()
        assert manager._machine_id_cache == id1

        # Subsequent calls should use cache
        id2 = manager.get_anonymous_machine_id()
        assert id2 == id1

    def test_machine_id_with_salt(self):
        """Test that machine ID changes with different salt values."""
        config1 = AnonymizationConfig(machine_id_salt="salt1")
        config2 = AnonymizationConfig(machine_id_salt="salt2")
        config3 = AnonymizationConfig(machine_id_salt=None)

        manager1 = AnonymizationManager(config1)
        manager2 = AnonymizationManager(config2)
        manager3 = AnonymizationManager(config3)

        id1 = manager1.get_anonymous_machine_id()
        id2 = manager2.get_anonymous_machine_id()
        id3 = manager3.get_anonymous_machine_id()

        # Different salts should produce different IDs
        assert id1 != id2
        assert id1 != id3
        assert id2 != id3

    def test_machine_id_deterministic_with_same_salt(self):
        """Test that same salt produces same ID across instances."""
        config1 = AnonymizationConfig(machine_id_salt="test_salt")
        config2 = AnonymizationConfig(machine_id_salt="test_salt")

        manager1 = AnonymizationManager(config1)
        manager2 = AnonymizationManager(config2)

        assert manager1.get_anonymous_machine_id() == manager2.get_anonymous_machine_id()


class TestMacOSPlatformUUID:
    """Test macOS IOPlatformUUID extraction."""

    @patch("platform.system")
    @patch("subprocess.run")
    def test_macos_platform_uuid_success(self, mock_run, mock_system):
        """Test successful extraction of macOS IOPlatformUUID."""
        mock_system.return_value = "Darwin"
        mock_run.return_value = Mock(
            returncode=0,
            stdout="""
            {
              "IOPlatformUUID" = "F79092CB-6DA1-5604-BBD1-78EF17E58BEF"
              "IOPlatformSerialNumber" = "J6WP2C57KT"
            }
            """,
        )

        manager = AnonymizationManager()
        uuid = manager._get_macos_platform_uuid()

        assert uuid == "F79092CB-6DA1-5604-BBD1-78EF17E58BEF"
        mock_run.assert_called_once_with(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    @patch("platform.system")
    @patch("subprocess.run")
    def test_macos_platform_uuid_command_failure(self, mock_run, mock_system):
        """Test handling of ioreg command failure."""
        mock_system.return_value = "Darwin"
        mock_run.return_value = Mock(returncode=1, stdout="")

        manager = AnonymizationManager()
        uuid = manager._get_macos_platform_uuid()

        assert uuid is None

    @patch("platform.system")
    @patch("subprocess.run")
    def test_macos_platform_uuid_timeout(self, mock_run, mock_system):
        """Test handling of ioreg command timeout."""
        mock_system.return_value = "Darwin"
        mock_run.side_effect = subprocess.TimeoutExpired("ioreg", 5)

        manager = AnonymizationManager()
        uuid = manager._get_macos_platform_uuid()

        assert uuid is None

    @patch("platform.system")
    @patch("subprocess.run")
    def test_macos_platform_uuid_missing_from_output(self, mock_run, mock_system):
        """Test handling when IOPlatformUUID is not in output."""
        mock_system.return_value = "Darwin"
        mock_run.return_value = Mock(returncode=0, stdout="Some other output without UUID")

        manager = AnonymizationManager()
        uuid = manager._get_macos_platform_uuid()

        assert uuid is None


class TestLinuxMachineID:
    """Test Linux machine-id extraction."""

    @patch("platform.system")
    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open, read_data="abc123def456ghi789\n")
    def test_linux_machine_id_from_etc(self, mock_file, mock_exists, mock_system):
        """Test successful extraction of Linux machine-id from /etc/machine-id."""
        mock_system.return_value = "Linux"
        mock_exists.side_effect = lambda path: path == "/etc/machine-id"

        manager = AnonymizationManager()
        machine_id = manager._get_linux_machine_id()

        assert machine_id == "abc123def456ghi789"
        mock_file.assert_called_with("/etc/machine-id", encoding="utf-8")

    @patch("platform.system")
    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open, read_data="xyz789abc123def456\n")
    def test_linux_machine_id_from_dbus(self, mock_file, mock_exists, mock_system):
        """Test fallback to /var/lib/dbus/machine-id."""
        mock_system.return_value = "Linux"
        mock_exists.side_effect = lambda path: path == "/var/lib/dbus/machine-id"

        manager = AnonymizationManager()
        machine_id = manager._get_linux_machine_id()

        assert machine_id == "xyz789abc123def456"
        mock_file.assert_called_with("/var/lib/dbus/machine-id", encoding="utf-8")

    @patch("platform.system")
    @patch("os.path.exists")
    def test_linux_machine_id_not_found(self, mock_exists, mock_system):
        """Test handling when no machine-id file exists."""
        mock_system.return_value = "Linux"
        mock_exists.return_value = False

        manager = AnonymizationManager()
        machine_id = manager._get_linux_machine_id()

        assert machine_id is None

    @patch("platform.system")
    @patch("os.path.exists")
    @patch("builtins.open")
    def test_linux_machine_id_permission_error(self, mock_file, mock_exists, mock_system):
        """Test handling of permission errors when reading machine-id."""
        mock_system.return_value = "Linux"
        mock_exists.return_value = True
        mock_file.side_effect = PermissionError("Access denied")

        manager = AnonymizationManager()
        machine_id = manager._get_linux_machine_id()

        assert machine_id is None


class TestWindowsMachineGUID:
    """Test Windows MachineGuid extraction."""

    @patch("platform.system")
    def test_windows_machine_guid_success(self, mock_system):
        """Test successful extraction of Windows MachineGuid."""
        mock_system.return_value = "Windows"

        # Mock the winreg module
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value = mock_key
        mock_winreg.QueryValueEx.return_value = ("12345678-90AB-CDEF-1234-567890ABCDEF", 1)
        mock_winreg.HKEY_LOCAL_MACHINE = "HKLM"
        mock_winreg.KEY_READ = 0x20019

        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            manager = AnonymizationManager()
            guid = manager._get_windows_machine_guid()

        assert guid == "12345678-90AB-CDEF-1234-567890ABCDEF"

    @pytest.mark.skipif(sys.platform == "win32", reason="winreg always available on Windows")
    @patch("platform.system")
    def test_windows_machine_guid_not_on_windows(self, mock_system):
        """Test that Windows MachineGuid returns None on non-Windows systems."""
        mock_system.return_value = "Darwin"

        manager = AnonymizationManager()
        guid = manager._get_windows_machine_guid()

        # Should return None because winreg module won't be available
        assert guid is None


class TestOSMachineID:
    """Test OS-level machine ID detection across platforms."""

    @patch("platform.system")
    def test_os_machine_id_delegates_to_macos(self, mock_system):
        """Test that Darwin delegates to macOS UUID method."""
        mock_system.return_value = "Darwin"

        manager = AnonymizationManager()
        with patch.object(manager, "_get_macos_platform_uuid", return_value="test-uuid") as mock_method:
            result = manager._get_os_machine_id()

        mock_method.assert_called_once()
        assert result == "test-uuid"

    @patch("platform.system")
    def test_os_machine_id_delegates_to_linux(self, mock_system):
        """Test that Linux delegates to Linux machine-id method."""
        mock_system.return_value = "Linux"

        manager = AnonymizationManager()
        with patch.object(manager, "_get_linux_machine_id", return_value="test-machine-id") as mock_method:
            result = manager._get_os_machine_id()

        mock_method.assert_called_once()
        assert result == "test-machine-id"

    @patch("platform.system")
    def test_os_machine_id_delegates_to_windows(self, mock_system):
        """Test that Windows delegates to Windows MachineGuid method."""
        mock_system.return_value = "Windows"

        manager = AnonymizationManager()
        with patch.object(manager, "_get_windows_machine_guid", return_value="test-guid") as mock_method:
            result = manager._get_os_machine_id()

        mock_method.assert_called_once()
        assert result == "test-guid"

    @patch("platform.system")
    def test_os_machine_id_unknown_os(self, mock_system):
        """Test handling of unknown operating system."""
        mock_system.return_value = "FreeBSD"

        manager = AnonymizationManager()
        result = manager._get_os_machine_id()

        assert result is None


class TestHardwareFingerprint:
    """Test hardware fingerprint generation (fallback method)."""

    def test_hardware_fingerprint_format(self):
        """Test that hardware fingerprint returns pipe-separated string."""
        manager = AnonymizationManager()
        fingerprint = manager._get_hardware_fingerprint()

        assert isinstance(fingerprint, str)
        assert "|" in fingerprint

        # Should have 4 components: machine|system|cpu_count|mac
        parts = fingerprint.split("|")
        assert len(parts) == 4

    def test_hardware_fingerprint_stability(self):
        """Test that hardware fingerprint is stable across calls."""
        manager = AnonymizationManager()

        fp1 = manager._get_hardware_fingerprint()
        fp2 = manager._get_hardware_fingerprint()

        assert fp1 == fp2

    @patch("platform.machine")
    @patch("platform.system")
    @patch("os.cpu_count")
    def test_hardware_fingerprint_components(self, mock_cpu_count, mock_system, mock_machine):
        """Test that hardware fingerprint contains expected components."""
        mock_machine.return_value = "arm64"
        mock_system.return_value = "Darwin"
        mock_cpu_count.return_value = 10

        manager = AnonymizationManager()
        fingerprint = manager._get_hardware_fingerprint()

        assert "arm64" in fingerprint
        assert "Darwin" in fingerprint
        assert "10" in fingerprint

    @patch("platform.machine")
    def test_hardware_fingerprint_exception_handling(self, mock_machine):
        """Test that hardware fingerprint handles exceptions gracefully."""
        mock_machine.side_effect = Exception("Test error")

        manager = AnonymizationManager()
        fingerprint = manager._get_hardware_fingerprint()

        assert fingerprint == "fallback_fingerprint"


class TestStableMACAddress:
    """Test stable MAC address extraction."""

    @patch("uuid.getnode")
    def test_stable_mac_address_format(self, mock_getnode):
        """Test MAC address formatting."""
        mock_getnode.return_value = 0x2211EB301A8A

        manager = AnonymizationManager()
        mac = manager._get_stable_mac_address()

        assert isinstance(mac, str)
        assert mac == "2211EB301A8A"

    @patch("uuid.getnode")
    def test_stable_mac_address_exception(self, mock_getnode):
        """Test MAC address exception handling."""
        mock_getnode.side_effect = Exception("Test error")

        manager = AnonymizationManager()
        mac = manager._get_stable_mac_address()

        assert mac == "unknown_mac"


class TestMachineIDIntegration:
    """Integration tests for complete machine ID generation flow."""

    @patch("platform.system")
    @patch("subprocess.run")
    def test_macos_uses_os_level_id(self, mock_run, mock_system):
        """Test that macOS uses IOPlatformUUID when available."""
        mock_system.return_value = "Darwin"
        mock_run.return_value = Mock(returncode=0, stdout='"IOPlatformUUID" = "F79092CB-6DA1-5604-BBD1-78EF17E58BEF"')

        manager = AnonymizationManager()
        machine_id = manager.get_anonymous_machine_id()

        # Should get a consistent ID based on the UUID
        assert machine_id.startswith("machine_")
        assert len(machine_id) == 24

        # Calling again should give same ID
        assert machine_id == manager.get_anonymous_machine_id()

    @patch("platform.system")
    @patch("subprocess.run")
    def test_macos_falls_back_to_fingerprint(self, mock_run, mock_system):
        """Test that macOS falls back to hardware fingerprint if ioreg fails."""
        mock_system.return_value = "Darwin"
        mock_run.side_effect = FileNotFoundError("ioreg not found")

        manager = AnonymizationManager()
        machine_id = manager.get_anonymous_machine_id()

        # Should still get a valid ID from fallback
        assert machine_id.startswith("machine_")
        assert len(machine_id) == 24

    @patch("platform.system")
    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open, read_data="stable-machine-id-value\n")
    def test_linux_uses_os_level_id(self, mock_file, mock_exists, mock_system):
        """Test that Linux uses machine-id when available."""
        mock_system.return_value = "Linux"
        mock_exists.side_effect = lambda path: path == "/etc/machine-id"

        manager1 = AnonymizationManager()
        manager2 = AnonymizationManager()

        id1 = manager1.get_anonymous_machine_id()
        id2 = manager2.get_anonymous_machine_id()

        # IDs should be identical across instances
        assert id1 == id2
        assert id1.startswith("machine_")

    def test_fallback_chain_completeness(self):
        """Test that system always produces a machine ID, even in worst case."""
        # Don't mock anything - let it use real system
        manager = AnonymizationManager()
        machine_id = manager.get_anonymous_machine_id()

        # Should always get a valid ID
        assert machine_id is not None
        assert isinstance(machine_id, str)
        assert machine_id.startswith("machine_")
        assert len(machine_id) == 24


class TestAnonymizationConfig:
    """Test anonymization configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = AnonymizationConfig()

        assert config.include_machine_id is True
        assert config.machine_id_salt is None
        assert config.anonymize_paths is True
        assert config.include_system_profile is True
        assert config.anonymize_hostnames is True
        assert config.anonymize_usernames is True

    def test_custom_config(self):
        """Test custom configuration values."""
        config = AnonymizationConfig(
            include_machine_id=False,
            machine_id_salt="custom_salt",
            anonymize_paths=False,
        )

        assert config.include_machine_id is False
        assert config.machine_id_salt == "custom_salt"
        assert config.anonymize_paths is False


class TestAnonymizeSystemProfile:
    """Test anonymize_system_profile method."""

    def test_returns_dict_with_expected_keys(self):
        manager = AnonymizationManager()
        profile = manager.anonymize_system_profile()
        assert isinstance(profile, dict)
        assert "os_type" in profile
        assert "cpu_count" in profile
        assert "python_version" in profile

    def test_hostname_is_anonymized(self):
        config = AnonymizationConfig(anonymize_hostnames=True)
        manager = AnonymizationManager(config)
        profile = manager.anonymize_system_profile()
        assert profile["hostname"].startswith("host_")

    def test_hostname_not_anonymized_when_disabled(self):
        config = AnonymizationConfig(anonymize_hostnames=False)
        manager = AnonymizationManager(config)
        profile = manager.anonymize_system_profile()
        assert not profile["hostname"].startswith("host_")

    def test_username_anonymized_when_enabled(self):
        config = AnonymizationConfig(anonymize_usernames=True)
        manager = AnonymizationManager(config)
        profile = manager.anonymize_system_profile()
        username = profile.get("username", "")
        assert username.startswith("user_") or username == "anonymous"

    def test_include_system_profile_false_returns_empty(self):
        config = AnonymizationConfig(include_system_profile=False)
        manager = AnonymizationManager(config)
        profile = manager.anonymize_system_profile()
        assert profile == {}

    def test_hostname_is_cached_consistently(self):
        manager = AnonymizationManager()
        p1 = manager.anonymize_system_profile()
        p2 = manager.anonymize_system_profile()
        assert p1["hostname"] == p2["hostname"]


class TestSanitizePath:
    """Test path sanitization."""

    def test_allowed_prefix_path_unchanged(self):
        manager = AnonymizationManager()
        result = manager.sanitize_path("/tmp/benchmark/results.json")
        assert result == "/tmp/benchmark/results.json"

    def test_path_anonymization_disabled(self):
        config = AnonymizationConfig(anonymize_paths=False)
        manager = AnonymizationManager(config)
        result = manager.sanitize_path("/home/user/secret/data.parquet")
        assert result == "/home/user/secret/data.parquet"

    def test_long_path_component_hashed(self):
        manager = AnonymizationManager()
        # A path component with more than 20 chars should be hashed
        result = manager.sanitize_path("/some/averylongdirectorynamewithmanychars/file.parquet")
        assert "averylongdirectorynamewithmanychars" not in result
        assert "dir_" in result

    def test_path_cache_returns_same_result(self):
        manager = AnonymizationManager()
        p = "/home/alice/project/data.csv"
        r1 = manager.sanitize_path(p)
        r2 = manager.sanitize_path(p)
        assert r1 == r2

    def test_common_system_dirs_kept(self):
        manager = AnonymizationManager()
        result = manager.sanitize_path("/home/foo")
        assert "home" in result

    def test_numeric_component_hashed(self):
        manager = AnonymizationManager()
        result = manager.sanitize_path("/data/user123/file.parquet")
        # "user123" has a digit so should be hashed
        assert "user123" not in result


class TestRemovePII:
    """Test PII removal from text."""

    def test_removes_ip_address(self):
        manager = AnonymizationManager()
        result = manager.remove_pii("Server at 192.168.1.100 failed")
        assert "192.168.1.100" not in result
        assert "[REDACTED]" in result

    def test_removes_email(self):
        manager = AnonymizationManager()
        result = manager.remove_pii("Contact user@example.com for help")
        assert "user@example.com" not in result
        assert "[REDACTED]" in result

    def test_removes_ssn_like_pattern(self):
        manager = AnonymizationManager()
        result = manager.remove_pii("SSN: 123-45-6789")
        assert "123-45-6789" not in result

    def test_empty_string_returns_empty(self):
        manager = AnonymizationManager()
        assert manager.remove_pii("") == ""

    def test_custom_sanitizer_applied(self):
        config = AnonymizationConfig(custom_sanitizers={r"SECRET-\d+": "[TOKEN]"})
        manager = AnonymizationManager(config)
        result = manager.remove_pii("Using key SECRET-9876")
        assert "SECRET-9876" not in result
        assert "[TOKEN]" in result

    def test_clean_text_unchanged(self):
        manager = AnonymizationManager()
        clean = "Benchmark finished in 3.5 seconds"
        assert manager.remove_pii(clean) == clean


class TestAnonymizeQueryMetadata:
    """Test query metadata anonymization."""

    def test_safe_fields_preserved(self):
        manager = AnonymizationManager()
        meta = {"query_id": "Q1", "execution_time": 1.5, "rows_returned": 100, "status": "ok"}
        result = manager.anonymize_query_metadata(meta)
        assert result["query_id"] == "Q1"
        assert result["execution_time"] == 1.5
        assert result["rows_returned"] == 100

    def test_sql_text_pii_removed(self):
        manager = AnonymizationManager()
        meta = {"sql_text": "SELECT * FROM t WHERE email = 'user@example.com'"}
        result = manager.anonymize_query_metadata(meta)
        assert "user@example.com" not in result["sql_text"]

    def test_file_path_sanitized(self):
        manager = AnonymizationManager()
        meta = {"file_path": "/tmp/data.parquet"}
        result = manager.anonymize_query_metadata(meta)
        assert result["file_path"] == "/tmp/data.parquet"

    def test_nested_dict_recursed(self):
        manager = AnonymizationManager()
        meta = {"nested": {"sql_text": "SELECT 1"}}
        result = manager.anonymize_query_metadata(meta)
        assert "nested" in result

    def test_list_values_processed(self):
        manager = AnonymizationManager()
        meta = {"tags": ["fast", "192.168.1.1"]}
        result = manager.anonymize_query_metadata(meta)
        assert isinstance(result["tags"], list)
        joined = " ".join(result["tags"])
        assert "192.168.1.1" not in joined

    def test_empty_dict_returns_empty(self):
        manager = AnonymizationManager()
        assert manager.anonymize_query_metadata({}) == {}


class TestAnonymizeExecutionMetadata:
    """Test execution metadata anonymization."""

    def test_safe_benchmark_fields_preserved(self):
        manager = AnonymizationManager()
        meta = {
            "benchmark_name": "tpch",
            "platform": "duckdb",
            "scale_factor": 1.0,
            "execution_id": "run-001",
        }
        result = manager.anonymize_execution_metadata(meta)
        assert result["benchmark_name"] == "tpch"
        assert result["platform"] == "duckdb"

    def test_machine_id_replaced_with_anonymous(self):
        manager = AnonymizationManager()
        meta = {"machine_id": "real-machine-id-12345"}
        result = manager.anonymize_execution_metadata(meta)
        assert "anonymous_machine_id" in result
        assert result["anonymous_machine_id"].startswith("machine_")

    def test_system_profile_included(self):
        manager = AnonymizationManager()
        meta = {"system_profile": {"hostname": "myhost", "os_type": "Linux"}}
        result = manager.anonymize_execution_metadata(meta)
        assert "system_profile" in result

    def test_data_path_sanitized(self):
        manager = AnonymizationManager()
        meta = {"data_directory": "/tmp/bench_data"}
        result = manager.anonymize_execution_metadata(meta)
        assert result["data_directory"] == "/tmp/bench_data"

    def test_query_results_list_anonymized(self):
        manager = AnonymizationManager()
        meta = {
            "query_results": [
                {"query_id": "Q1", "execution_time": 1.0},
                {"query_id": "Q2", "execution_time": 2.0},
            ]
        }
        result = manager.anonymize_execution_metadata(meta)
        assert isinstance(result["query_results"], list)
        assert len(result["query_results"]) == 2

    def test_empty_metadata_returns_empty(self):
        manager = AnonymizationManager()
        assert manager.anonymize_execution_metadata({}) == {}


class TestValidateAnonymization:
    """Test anonymization validation."""

    def test_valid_anonymized_data_passes(self):
        manager = AnonymizationManager()
        meta = {"benchmark_name": "tpch", "machine_id": "x"}
        anonymized = manager.anonymize_execution_metadata(meta)
        validation = manager.validate_anonymization(meta, anonymized)
        assert validation["is_valid"] is True
        assert isinstance(validation["checks_performed"], list)

    def test_pii_in_anonymized_data_generates_warning(self):
        manager = AnonymizationManager()
        original = {}
        # Manually inject IP into otherwise clean data
        anonymized = {"result": "connected to 10.0.0.1"}
        validation = manager.validate_anonymization(original, anonymized)
        warnings = " ".join(validation["warnings"])
        assert "IP" in warnings or "ip" in warnings.lower()

    def test_missing_machine_id_generates_error(self):
        config = AnonymizationConfig(include_machine_id=True)
        manager = AnonymizationManager(config)
        validation = manager.validate_anonymization({}, {"result": "ok"})
        assert any("machine" in e.lower() for e in validation["errors"])
        assert validation["is_valid"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
