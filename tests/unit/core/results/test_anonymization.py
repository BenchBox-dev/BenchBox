"""Tests for benchbox.core.results.anonymization module.

Tests the anonymization system with focus on stable machine ID generation
across different operating systems and configurations.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import dataclasses
import inspect
import json
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, mock_open, patch

import pytest

from benchbox.core.results.anonymization import (
    _IDENTIFIER_KEYS,
    PUBLIC_REDACTED_VALUE,
    AnonymizationConfig,
    AnonymizationManager,
    _is_public_pseudonym,
    find_public_path_leaks,
)

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

        assert config.machine_id_salt is None
        assert config.pii_patterns
        assert config.custom_sanitizers == {}

    def test_custom_config(self):
        """Test custom configuration values."""
        config = AnonymizationConfig(machine_id_salt="custom_salt")

        assert config.machine_id_salt == "custom_salt"

    def test_no_flag_promises_privacy_it_does_not_deliver(self):
        """Every remaining field must actually reach published output.

        The retired flags (include_machine_id, anonymize_paths,
        allowed_path_prefixes, include_system_profile, anonymize_hostnames,
        anonymize_usernames) fed only the deleted legacy API. They read as
        privacy controls but gated nothing on the publication path, which is
        the worst kind of config: a caller could set anonymize_paths=False
        and see no change, or leave it True and assume paths were protected
        by it. Keep the surface honest.
        """
        retired = {
            "include_machine_id",
            "anonymize_paths",
            "allowed_path_prefixes",
            "include_system_profile",
            "anonymize_hostnames",
            "anonymize_usernames",
        }
        present = {f.name for f in dataclasses.fields(AnonymizationConfig)}
        assert not (present & retired), f"dead privacy flags are back: {sorted(present & retired)}"


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


class TestPublicPayloadSecretKeys:
    """The public export path must honor every secret part the internal
    capture path honors — both consumers read one shared list, so a key that
    is redacted at capture time can never be published by re-export either."""

    @staticmethod
    def _payload(config):
        return {"platform_metadata": {"platform_raw_config": config}}

    def test_key_id_values_are_redacted(self):
        manager = AnonymizationManager()
        out = manager.anonymize_result_payload(
            self._payload({"s3_key_id": "AKIA-SENTINEL", "kms_key_id": "KMS-SENTINEL"})
        )
        raw = json.dumps(out, default=str)
        assert "AKIA-SENTINEL" not in raw
        assert "KMS-SENTINEL" not in raw

    def test_already_covered_keys_keep_behavior(self):
        manager = AnonymizationManager()
        out = manager.anonymize_result_payload(
            self._payload({"pg_password": "PW-SENTINEL", "username": "alice-sentinel"})
        )["platform_metadata"]["platform_raw_config"]
        assert out["pg_password"] == PUBLIC_REDACTED_VALUE
        assert out["username"] != "alice-sentinel"
        assert out["username"].startswith("user_")

    def test_secret_parts_shared_with_platform_options(self):
        from benchbox.core.results.anonymization import _SECRET_KEY_PARTS as anon_parts
        from benchbox.core.results.platform_options import _SECRET_KEY_PARTS as capture_parts

        assert set(capture_parts) <= set(anon_parts)

    def test_data_modelling_keys_are_not_over_redacted(self):
        manager = AnonymizationManager()
        out = manager.anonymize_result_payload(
            self._payload({"sort_key": "l_shipdate", "partition_key": "l_orderkey"})
        )["platform_metadata"]["platform_raw_config"]
        assert out["sort_key"] == "l_shipdate"
        assert out["partition_key"] == "l_orderkey"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestPublicPayloadApiKeyAndAccountKey:
    """The shared secret list must cover api_key/*_account_key on the public
    path too — these leaked through anonymize_result_payload verbatim."""

    def test_api_key_and_storage_account_key_are_redacted(self):
        manager = AnonymizationManager()
        out = json.dumps(
            manager.anonymize_result_payload(
                {
                    "platform_metadata": {
                        "platform_raw_config": {
                            "api_key": "APIKEY-SENTINEL",
                            "onehouse_api_key": "OH-SENTINEL",
                            "storage_account_key": "AZKEY-SENTINEL",
                        }
                    }
                }
            ),
            default=str,
        )
        assert "APIKEY-SENTINEL" not in out
        assert "OH-SENTINEL" not in out
        assert "AZKEY-SENTINEL" not in out


class TestPublicPayloadCredentialAliases:
    """The public anonymizer must share exact alias handling with capture."""

    def test_aliases_are_redacted_while_preserving_tuning_keys_and_path_contract(self):
        out = AnonymizationManager().anonymize_result_payload(
            {
                "platform_metadata": {
                    "platform_raw_config": {
                        "passwd": "PASSWD_SECRET",
                        "pwd": "PWD_SECRET",
                        "pat": "PAT_SECRET",
                        "path": "/tmp/data",
                        "sort_key": "o_orderkey",
                    }
                }
            }
        )["platform_metadata"]["platform_raw_config"]

        assert out["passwd"] == PUBLIC_REDACTED_VALUE
        assert out["pwd"] == PUBLIC_REDACTED_VALUE
        assert out["pat"] == PUBLIC_REDACTED_VALUE
        assert out["path"].startswith("path_")
        assert out["sort_key"] == "o_orderkey"


class TestPublicPayloadSslRootCert:
    """The libpq sslrootcert spelling ends in neither path nor file, so the
    raw local path (leaking the home-dir username) passed through."""

    def test_sslrootcert_path_is_hashed(self):
        out = json.dumps(
            AnonymizationManager().anonymize_result_payload(
                {"platform_metadata": {"platform_raw_config": {"sslrootcert": "/Users/joe/certs/root.pem"}}}
            ),
            default=str,
        )
        assert "/Users/joe" not in out

    def test_underscore_cert_paths_still_hashed(self):
        out = json.dumps(
            AnonymizationManager().anonymize_result_payload(
                {"platform_metadata": {"platform_raw_config": {"ca_cert_path": "/Users/joe/certs/ca.pem"}}}
            ),
            default=str,
        )
        assert "/Users/joe" not in out


class TestPublicPayloadTupleRecursion:
    """A tuple fell through to the scalar branch untouched, so any payload
    branch not pre-flattened by internal capture leaked tuple contents."""

    def test_tuple_nested_identifier_is_anonymized(self):
        out = json.dumps(
            AnonymizationManager().anonymize_result_payload(
                {"platform_metadata": {"nested": ({"userid": "TUP-SENTINEL"},)}}
            ),
            default=str,
        )
        assert "TUP-SENTINEL" not in out

    def test_tuple_secret_key_is_redacted(self):
        out = json.dumps(
            AnonymizationManager().anonymize_result_payload(
                {"platform_metadata": {"configs": ({"password": "TUPPW-SENTINEL"},)}}
            ),
            default=str,
        )
        assert "TUPPW-SENTINEL" not in out

    def test_list_and_dict_recursion_unchanged(self):
        out = AnonymizationManager().anonymize_result_payload(
            {"platform_metadata": {"platform_raw_config": [{"username": "alice-sentinel"}]}}
        )["platform_metadata"]["platform_raw_config"]
        assert out[0]["username"].startswith("user_")

    def test_unordered_collections_are_sorted_before_export(self):
        out = AnonymizationManager().anonymize_result_payload(
            {"platform_metadata": {"values": frozenset({"zeta", "alpha"})}}
        )

        assert out["platform_metadata"]["values"] == ["alpha", "zeta"]


class TestTuningPayloadAnonymization:
    def test_unknown_constraint_fields_use_generic_public_sanitization(self):
        out = AnonymizationManager().anonymize_tuning_payload(
            {
                "requested": {
                    "constraints": {
                        "foreign_keys": {
                            "password": "CONSTRAINT-PASSWORD",
                            "owner_email": "owner@example.com",
                            "endpoint": "https://warehouse.example.com",
                            "path": "/Users/alice/private-run",
                        }
                    }
                }
            }
        )

        serialized = json.dumps(out)
        assert "CONSTRAINT-PASSWORD" not in serialized
        assert "owner@example.com" not in serialized
        assert "warehouse.example.com" not in serialized
        assert "/Users/alice" not in serialized

    def test_constraint_table_and_column_identifiers_are_pseudonymized(self):
        out = AnonymizationManager().anonymize_tuning_payload(
            {
                "requested": {
                    "constraints": {
                        "primary_keys": {
                            "enabled": True,
                            "tables": {"orders": ["o_orderkey"]},
                        },
                        "foreign_keys": {
                            "enabled": True,
                            "tables": {
                                "lineitem": {
                                    "columns": ["l_orderkey"],
                                    "referenced_table": "orders",
                                    "referenced_columns": ["o_orderkey"],
                                }
                            },
                        },
                    }
                }
            }
        )

        serialized = json.dumps(out)
        assert all(identifier not in serialized for identifier in ("orders", "lineitem", "o_orderkey", "l_orderkey"))
        constraints = out["requested"]["constraints"]
        assert next(iter(constraints["primary_keys"]["tables"])).startswith("table_")
        assert constraints["primary_keys"]["tables"][next(iter(constraints["primary_keys"]["tables"]))][0].startswith(
            "column_"
        )

    def test_table_and_column_identifiers_are_pseudonymized_but_source_is_preserved(self):
        manager = AnonymizationManager()
        out = manager.anonymize_tuning_payload(
            {
                "source_file": "examples/tunings/custom.yaml:0123456789abcdef",
                "requested": {
                    "table_tunings": {
                        "lineitem": {
                            "table_name": "lineitem",
                            "sorting": [{"name": "l_orderkey", "order": 1}],
                        }
                    }
                },
            }
        )

        tuning = out["requested"]["table_tunings"]
        table_key = next(iter(tuning))
        assert table_key.startswith("table_")
        assert tuning[table_key]["table_name"].startswith("table_")
        assert tuning[table_key]["sorting"][0]["name"].startswith("column_")
        assert out["source_file"] == "examples/tunings/custom.yaml:0123456789abcdef"

    @pytest.mark.parametrize(
        "source_file",
        [
            "/Users/alice/private/custom.yaml",
            r"C:\Users\alice\private\custom.yaml",
            "../private/custom.yaml",
            "source=/Users/alice/private/custom.yaml",
            "template.yaml\n/Users/alice/private/custom.yaml",
        ],
    )
    def test_untrusted_tuning_source_path_is_hashed(self, source_file):
        out = AnonymizationManager().anonymize_tuning_payload({"source_file": source_file})

        assert out["source_file"].startswith("path_")
        assert "alice" not in out["source_file"]


class TestPublicPayloadWorkspaceRoleAndApplicationIds:
    """Near-miss variants of covered identifier keys are the recurring leak
    pattern: workspace_name, job_role and application_id all exported
    verbatim while workspace/workspaceid and role/iamrole were covered."""

    @staticmethod
    def _payload(config):
        return {"platform_metadata": {"platform_raw_config": config}}

    def test_workspace_name_pseudonymizes_like_workspace(self):
        out = AnonymizationManager().anonymize_result_payload(self._payload({"workspace_name": "WSN-SENTINEL"}))[
            "platform_metadata"
        ]["platform_raw_config"]
        assert out["workspace_name"] != "WSN-SENTINEL"
        assert out["workspace_name"].startswith("workspace_")

    def test_job_role_pseudonymizes_like_role(self):
        out = AnonymizationManager().anonymize_result_payload(self._payload({"job_role": "JR-SENTINEL"}))[
            "platform_metadata"
        ]["platform_raw_config"]
        assert out["job_role"] != "JR-SENTINEL"
        assert out["job_role"].startswith("role_")

    def test_application_id_is_hashed(self):
        out = AnonymizationManager().anonymize_result_payload(self._payload({"application_id": "APP-SENTINEL"}))[
            "platform_metadata"
        ]["platform_raw_config"]
        assert out["application_id"] != "APP-SENTINEL"
        assert out["application_id"].startswith("application_")


class TestPublicPayloadPgUserAndTenantId:
    """pg_user must pseudonymize like every other username spelling, and a
    tenant id (an org-identifying GUID) must hash — both escaped the public
    identifier map because their compact keys matched nothing."""

    @staticmethod
    def _payload(config):
        return {"platform_metadata": {"platform_raw_config": config}}

    def test_pg_user_pseudonymizes_like_username(self):
        manager = AnonymizationManager()
        out = manager.anonymize_result_payload(self._payload({"pg_user": "PGUSER-SENTINEL"}))["platform_metadata"][
            "platform_raw_config"
        ]
        assert out["pg_user"] != "PGUSER-SENTINEL"
        assert out["pg_user"].startswith("user_")

    def test_tenant_id_is_hashed(self):
        manager = AnonymizationManager()
        out = manager.anonymize_result_payload(self._payload({"tenant_id": "TENANT-SENTINEL"}))["platform_metadata"][
            "platform_raw_config"
        ]
        assert out["tenant_id"] != "TENANT-SENTINEL"
        assert out["tenant_id"].startswith("tenant_")

    def test_existing_identifier_behavior_unchanged(self):
        manager = AnonymizationManager()
        out = manager.anonymize_result_payload(
            self._payload({"username": "alice-sentinel", "account": "acct-sentinel"})
        )["platform_metadata"]["platform_raw_config"]
        assert out["username"].startswith("user_")
        assert out["account"].startswith("account_")


class TestPublicPayloadSecretMessages:
    def test_message_values_use_the_shared_secret_key_classifier(self):
        manager = AnonymizationManager()
        out = manager.anonymize_result_payload(
            {
                "platform_metadata": {
                    "error_message": "api_key=API-SENTINEL storage_account_key=AZ-SENTINEL",
                    "stderr": "AccountKey=AZ-CONNECTION-SENTINEL",
                }
            }
        )
        serialized = json.dumps(out, default=str)
        assert "API-SENTINEL" not in serialized
        assert "AZ-SENTINEL" not in serialized
        assert "AZ-CONNECTION-SENTINEL" not in serialized


class TestPublicPayloadPathPrivacy:
    def test_generic_working_directory_is_hashed(self):
        out = AnonymizationManager().anonymize_result_payload(
            {"platform_metadata": {"working_dir": "/Users/alice/benchbox/run"}}
        )
        serialized = json.dumps(out, default=str)
        assert "/Users/alice" not in serialized
        assert out["platform_metadata"]["working_dir"].startswith("path_")

    def test_nested_generic_metadata_paths_are_hashed_without_field_allowlist(self):
        out = AnonymizationManager().anonymize_result_payload(
            {"platform_metadata": {"raw_config": {"runtime": {"path_value": "/home/alice/cache"}}}}
        )
        assert "/home/alice" not in json.dumps(out, default=str)
        assert out["platform_metadata"]["raw_config"]["runtime"]["path_value"].startswith("path_")

    def test_relative_references_and_urls_are_not_false_positives(self):
        payload = {
            "source_ref": "examples/tunings/custom.yaml:0123456789abcdef",
            "url": "https://example.com/home/alice/reference",
        }
        assert find_public_path_leaks(payload) == []
        out = AnonymizationManager().anonymize_result_payload(payload)
        assert out["source_ref"] == payload["source_ref"]
        assert out["url"].startswith("endpoint_")

    def test_detector_reports_field_paths_without_echoing_values(self):
        leaks = find_public_path_leaks({"nested": [{"working_dir": "/Users/alice/private"}]})
        assert leaks == ["nested.0.working_dir"]

    def test_detector_flags_private_paths_encoded_as_object_keys(self):
        """Scanning values alone called this payload clean."""
        leaks = find_public_path_leaks({"per_path_timings": {"/Users/alice/db": 1.2}})
        assert leaks == ["per_path_timings.<key>"]

    def test_key_leak_report_does_not_echo_the_key(self):
        """The offending key *is* the private path, so it must stay redacted."""
        leaks = find_public_path_leaks({"metadata": {"/Users/alice/secret-project": True}})
        assert leaks and "alice" not in " ".join(leaks)
        assert "secret-project" not in " ".join(leaks)

    def test_detector_flags_a_leaking_key_at_the_root(self):
        leaks = find_public_path_leaks({"/Users/alice/db": 1})
        assert leaks == ["<key>"]

    def test_leaking_key_is_elided_from_descendant_field_paths(self):
        """Reporting a nested leak must not splice the parent key back in.

        These diagnostics are surfaced in submission PR comments and Explorer
        exceptions, so a raw key in a child's path discloses the private path
        precisely when the detector is doing its job.
        """
        leaks = find_public_path_leaks({"/Users/alice/secret": {"working_dir": "/home/bob/private"}})
        joined = " ".join(leaks)
        assert "<key>.working_dir" in leaks
        assert "alice" not in joined
        assert "secret" not in joined
        assert "bob" not in joined

    def test_ordinary_keys_are_not_flagged(self):
        """Relative and non-path keys stay clean - no blanket key rejection."""
        payload = {"queries": {"q1": 1.0, "tpch/q2": 2.0}, "platform": {"name": "DuckDB"}}
        assert find_public_path_leaks(payload) == []

    def test_root_owned_home_paths_are_private_even_under_generic_keys(self):
        payload = {"raw_config": {"location": "/root/private-run"}}

        assert find_public_path_leaks(payload)
        out = AnonymizationManager().anonymize_result_payload(payload)
        assert "/root/private-run" not in json.dumps(out, default=str)


class TestPublicPseudonymFixedPoint:
    """Anonymization must reach a fixed point.

    Curated bundles are stored already-anonymized, so the Explorer publication
    boundary anonymizes values this module produced. Hashing a pseudonym again
    mints a second token for the same machine, so the corpus and a freshly
    submitted run from that machine would group apart. Nothing fails when this
    breaks - the grouping is just silently wrong - so it is pinned here.
    """

    PAYLOAD = {
        "environment": {"machine_id": "machine_0123456789ab", "platform_runtime": {"engine_host": "db.internal"}},
        "platform": {
            "config": {
                "working_dir": "/Users/alice/benchbox",
                "database": "analytics",
                "endpoint": "https://example.invalid/warehouse",
                "s3_bucket": "alice-results",
                "role_arn": "arn:aws:iam::1234:role/bench",
            }
        },
        "config": {"platform_options": {"account_id": "acct-1", "cluster_id": "c-1", "schema_name": "public"}},
    }

    def test_result_payload_anonymization_is_idempotent(self):
        manager = AnonymizationManager()
        once = manager.anonymize_result_payload(self.PAYLOAD)
        assert manager.anonymize_result_payload(once) == once

    def test_tuning_payload_anonymization_is_idempotent(self):
        """Tuning hashes table/column names into mapping *keys*, so re-walking
        an already-anonymized companion re-hashes the keys as well as values.
        """
        manager = AnonymizationManager()
        payload = {
            "source_file": "examples/tunings/custom.yaml",
            "requested": {
                "table_tunings": {"lineitem": {"columns": [{"name": "l_orderkey"}]}},
                "constraints": {"primary_key": {"table": "orders", "columns": ["o_orderkey"]}},
            },
        }
        once = manager.anonymize_tuning_payload(payload)
        assert manager.anonymize_tuning_payload(once) == once

    def test_pseudonym_survives_a_second_pass_unchanged(self):
        manager = AnonymizationManager()
        once = manager.anonymize_result_payload(self.PAYLOAD)
        twice = manager.anonymize_result_payload(once)
        assert twice["environment"]["machine_id"] == once["environment"]["machine_id"]
        assert twice["platform"]["config"]["working_dir"] == once["platform"]["config"]["working_dir"]

    def test_every_emitted_pseudonym_is_recognized_as_one(self):
        """Pin the emitter against the recognizer.

        These are two halves of one contract - the ``[:12]`` slice and the
        width the pass-through accepts. Widening one alone silently restores
        the double-hash bug, and no payload-level test would notice.
        """
        manager = AnonymizationManager()
        for prefix in sorted(set(_IDENTIFIER_KEYS.values()) | {"path", "host", "endpoint", "table", "column"}):
            emitted = manager._hash_public_identifier("some-private-value", prefix)
            assert _is_public_pseudonym(emitted, prefix), f"{prefix}: emitted {emitted!r} is not recognized"
            assert manager._hash_public_identifier(emitted, prefix) == emitted

    def test_capture_side_machine_id_is_still_hashed(self):
        """The pass-through must not decouple-proof internal identity.

        ``get_anonymous_machine_id`` emits a 16-hex token; the public boundary
        re-hashes it to a 12-hex one so the internal id is never published. A
        width-agnostic pass-through would publish the internal id verbatim.
        """
        manager = AnonymizationManager()
        internal = manager.get_anonymous_machine_id()
        published = manager.anonymize_result_payload({"machine_id": internal})["machine_id"]
        assert published != internal
        assert _is_public_pseudonym(published, "machine")

    def test_pass_through_does_not_cross_prefixes(self):
        """A token only survives in the field family that would mint it.

        Without prefix scoping, a ``host_``-shaped value would survive verbatim
        inside a path field, letting a submitted payload carry a chosen token
        into a namespace the anonymizer never assigned it to.
        """
        manager = AnonymizationManager()
        out = manager.anonymize_result_payload({"working_dir": "host_0123456789ab"})
        assert out["working_dir"] != "host_0123456789ab"
        assert _is_public_pseudonym(out["working_dir"], "path")

    @pytest.mark.parametrize(
        "value",
        [
            "path_0123456789",  # too short
            "path_0123456789abc",  # too long
            "path_0123456789zz",  # not hex
            "path_",  # no digest
            "pathx_0123456789ab",  # prefix is not an exact match
        ],
    )
    def test_only_the_exact_pseudonym_shape_passes_through(self, value):
        assert not _is_public_pseudonym(value, "path")
        assert AnonymizationManager().anonymize_result_payload({"working_dir": value})["working_dir"] != value


class TestLegacyAnonymizationSchemeIsGone:
    """One salted scheme, no second weaker one.

    The module used to carry a parallel legacy API - sanitize_path,
    anonymize_query_metadata, anonymize_execution_metadata,
    anonymize_system_profile, validate_anonymization - that hashed with
    UNSALTED md5 truncated to 8 hex and, in sanitize_path's case, returned
    private paths completely unchanged. It had no production caller, so it
    leaked nothing in practice, but it sat in the same module as the real
    boundary where a future caller could reasonably have trusted it.
    """

    LEGACY_METHODS = (
        "sanitize_path",
        "anonymize_query_metadata",
        "anonymize_execution_metadata",
        "anonymize_system_profile",
        "validate_anonymization",
    )

    @pytest.mark.parametrize("name", LEGACY_METHODS)
    def test_legacy_method_is_gone(self, name):
        assert not hasattr(AnonymizationManager, name), f"{name} is back on the public surface"

    def test_no_unsalted_md5_pseudonym_scheme_remains(self):
        """md5 is unsalted and 8 hex here - trivially reversible for a
        username or hostname. The public boundary uses salted sha256.
        """
        source = inspect.getsource(sys.modules[AnonymizationManager.__module__])
        assert "md5" not in source, "an md5 pseudonym scheme is back in the anonymizer"

    def test_every_pseudonym_emitter_uses_the_shared_salted_helper(self):
        """Catch a second emitter even if it reaches for sha256.

        The bug was two schemes, not md5 specifically. Any new
        f"prefix_{...hexdigest()[:n]}" that bypasses _hash_public_identifier
        would reintroduce it, so pin that the module truncates a digest in
        exactly the two places that are supposed to.
        """
        source = inspect.getsource(sys.modules[AnonymizationManager.__module__])
        truncations = re.findall(r"hexdigest\(\)\[:[^\]]+\]", source)
        assert len(truncations) == 2, f"unexpected digest truncations: {truncations}"

    def test_no_sibling_module_mints_a_pseudonym_behind_the_boundary(self):
        """Widen the check past this one module.

        The rung above reads only ``anonymization.py``, so a second emitter
        added in a sibling under ``benchbox/core/results/`` would satisfy it
        while reintroducing exactly the split this class exists to prevent.
        Scan the package and require that anything minting a ``<prefix>_<hex>``
        token does it through the shared salted helper.
        """
        package = Path(inspect.getfile(sys.modules[AnonymizationManager.__module__])).parent
        emitter = re.compile(r"f\"[a-z_]+_\{[^}]*hexdigest\(\)")
        offenders = []
        for path in sorted(package.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            if path.name == "anonymization.py":
                continue
            if emitter.search(text):
                offenders.append(path.name)
        assert not offenders, f"pseudonym emitters outside the shared helper: {offenders}"

    def test_public_surface_is_only_the_salted_boundary(self):
        public = {
            name for name, _ in inspect.getmembers(AnonymizationManager, inspect.isfunction) if not name.startswith("_")
        }
        assert public == {
            "get_anonymous_machine_id",
            "anonymize_result_payload",
            "anonymize_tuning_payload",
            "remove_pii",
        }, public

    def test_salt_does_not_reach_an_already_anonymized_value(self):
        """Pin the salt/pass-through interaction, including its downside.

        The pass-through is checked BEFORE the salt is applied, so a value that
        is already a pseudonym survives verbatim no matter whose salt is in
        play. That is required for idempotence, but it means changing the salt
        does not re-pseudonymize a stored corpus: new captures adopt the new
        salt while stored bundles keep the old pseudonyms, splitting one
        machine across two identities. Rotating the salt requires re-deriving
        the corpus from pre-anonymization originals. Documented under
        "Salt rotation" in docs/reference/result-formats.md.
        """
        a = AnonymizationManager(AnonymizationConfig(machine_id_salt="org-A"))
        b = AnonymizationManager(AnonymizationConfig(machine_id_salt="org-B"))
        raw = {"machine_id": "machine_0123456789abcdef"}

        published_by_a = a.anonymize_result_payload(raw)["machine_id"]
        published_by_b = b.anonymize_result_payload(raw)["machine_id"]
        assert published_by_a != published_by_b, "salt must scope pseudonyms derived from raw values"

        reanonymized = b.anonymize_result_payload({"machine_id": published_by_a})["machine_id"]
        assert reanonymized == published_by_a, "already-anonymized values are salt-independent by design"

    def test_no_public_method_returns_a_private_path_verbatim(self):
        """The concrete defect: sanitize_path('/Users/alice/bench') used to
        return that string unchanged, and find_public_path_leaks flagged its
        own module's output as a leak.
        """
        manager = AnonymizationManager()
        private = "/Users/alice/bench"
        for payload in ({"working_dir": private}, {"database_path": private}, {"note": private}):
            out = manager.anonymize_result_payload(payload)
            assert find_public_path_leaks(out) == [], f"{payload} leaked: {out}"
            assert "alice" not in json.dumps(out)
