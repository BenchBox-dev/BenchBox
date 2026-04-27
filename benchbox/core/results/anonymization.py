"""Anonymization system for benchmark results.

Provides secure anonymization of sensitive data in benchmark results including
machine identification, file paths, and other potentially identifying information.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import hashlib
import logging
import os
import platform
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class AnonymizationConfig:
    """Configuration for result anonymization."""

    # Machine identification
    include_machine_id: bool = True
    machine_id_salt: Optional[str] = None

    # Path sanitization
    anonymize_paths: bool = True
    allowed_path_prefixes: list[str] = field(default_factory=lambda: ["/tmp", "/var/tmp"])

    # System info
    include_system_profile: bool = True
    anonymize_hostnames: bool = True
    anonymize_usernames: bool = True

    # Data anonymization
    pii_patterns: list[str] = field(
        default_factory=lambda: [
            r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",  # IP addresses
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # Email addresses
            r"\b\d{3}-\d{2}-\d{4}\b",  # SSN-like patterns
        ]
    )

    # Custom sanitizers
    custom_sanitizers: dict[str, str] = field(default_factory=dict)


class AnonymizationManager:
    """Manages anonymization of benchmark results and metadata."""

    def __init__(self, config: Optional[AnonymizationConfig] = None):
        """Initialize the anonymization manager.

        Args:
            config: Anonymization configuration (uses defaults if None)
        """
        self.config = config or AnonymizationConfig()
        self._machine_id_cache: Optional[str] = None
        self._path_mapping: dict[str, str] = {}
        self._hostname_mapping: dict[str, str] = {}

    def _get_macos_platform_uuid(self) -> Optional[str]:
        """Get macOS IOPlatformUUID - a stable hardware-based identifier.

        Returns:
            IOPlatformUUID string or None if unavailable
        """
        try:
            result = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                # Parse IOPlatformUUID from output
                for line in result.stdout.split("\n"):
                    if "IOPlatformUUID" in line:
                        # Extract UUID from line like: "IOPlatformUUID" = "F79092CB-..."
                        parts = line.split("=")
                        if len(parts) >= 2:
                            uuid = parts[1].strip().strip('"')
                            logger.debug(f"Found macOS IOPlatformUUID: {uuid[:8]}...")
                            return uuid
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            logger.debug(f"Failed to get macOS platform UUID: {e}")
        return None

    def _get_linux_machine_id(self) -> Optional[str]:
        """Get Linux machine-id - a stable system-level identifier.

        Returns:
            machine-id string or None if unavailable
        """
        # Try systemd machine-id first (most common)
        for machine_id_path in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
            try:
                if os.path.exists(machine_id_path):
                    with open(machine_id_path, encoding="utf-8") as f:
                        machine_id = f.read().strip()
                        if machine_id:
                            logger.debug(f"Found Linux machine-id from {machine_id_path}")
                            return machine_id
            except (OSError, PermissionError) as e:
                logger.debug(f"Failed to read {machine_id_path}: {e}")
                continue
        return None

    def _get_windows_machine_guid(self) -> Optional[str]:
        """Get Windows MachineGuid - a stable system-level identifier.

        Returns:
            MachineGuid string or None if unavailable
        """
        try:
            import winreg

            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\Microsoft\\Cryptography", 0, winreg.KEY_READ)
            machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            winreg.CloseKey(key)
            logger.debug(f"Found Windows MachineGuid: {machine_guid[:8]}...")
            return machine_guid
        except (ImportError, OSError, Exception) as e:
            logger.debug(f"Failed to get Windows MachineGuid: {e}")
        return None

    def _get_os_machine_id(self) -> Optional[str]:
        """Get OS-provided stable machine identifier.

        Returns:
            OS-level machine ID or None if unavailable
        """
        system = platform.system()

        if system == "Darwin":
            return self._get_macos_platform_uuid()
        elif system == "Linux":
            return self._get_linux_machine_id()
        elif system == "Windows":
            return self._get_windows_machine_guid()
        else:
            logger.debug(f"Unknown OS: {system}, no OS-level machine ID available")
            return None

    def _get_stable_mac_address(self) -> str:
        """Get a stable MAC address from physical network interfaces.

        Attempts to filter out virtual interfaces and select the most stable
        physical network adapter.

        Returns:
            MAC address string or 'unknown_mac' if unavailable
        """
        try:
            import uuid

            # Try to get a more stable MAC by using uuid.getnode()
            # This typically returns the MAC of a physical interface
            mac = uuid.getnode()

            # Check if it's a valid MAC (not the random fallback)
            # uuid.getnode() returns a 48-bit integer, convert to hex
            mac_hex = f"{mac:012x}".upper()

            # If the second least significant bit of the first octet is 1,
            # it might be a randomly generated MAC (IEEE standard)
            first_octet = int(mac_hex[:2], 16)
            if first_octet & 0x02:  # Check if locally administered bit is set
                logger.debug("MAC address appears to be locally administered/random")

            return mac_hex
        except Exception as e:
            logger.debug(f"Failed to get MAC address: {e}")
            return "unknown_mac"

    def _get_hardware_fingerprint(self) -> str:
        """Generate hardware fingerprint from stable system characteristics.

        This is used as a fallback when OS-level machine ID is unavailable.
        Uses only the most stable hardware/system characteristics.

        Returns:
            Pipe-separated string of stable hardware characteristics
        """
        fingerprint_data = []

        try:
            # CPU architecture (very stable - only changes with hardware replacement)
            fingerprint_data.append(platform.machine())

            # OS type (stable unless dual-boot or OS migration)
            fingerprint_data.append(platform.system())

            # CPU count (stable - only changes with hardware upgrade)
            fingerprint_data.append(str(os.cpu_count() or 0))

            # MAC address (reasonably stable, filtered for physical interfaces)
            fingerprint_data.append(self._get_stable_mac_address())

            # Note: We explicitly EXCLUDE:
            # - platform.processor() - too unreliable, often empty or varies
            # - platform.release() - changes with OS updates
            # - uuid.getnode() directly - replaced with _get_stable_mac_address()

        except Exception as e:
            logger.warning(f"Failed to collect hardware fingerprint: {e}")
            fingerprint_data = ["fallback_fingerprint"]

        return "|".join(fingerprint_data)

    def get_anonymous_machine_id(self) -> str:
        """Generate a stable, anonymous machine identifier.

        Uses a three-tier approach for maximum stability:
        1. OS-provided machine IDs (macOS IOPlatformUUID, Linux machine-id, Windows MachineGuid)
        2. Hardware fingerprint from stable characteristics (fallback)
        3. Warning and random ID (extreme fallback)

        The OS-level ID is hashed for anonymization while maintaining stability
        across runs on the same physical hardware.

        Returns:
            Anonymous machine identifier string (format: "machine_<16-char-hex>")
        """
        if self._machine_id_cache:
            return self._machine_id_cache

        machine_string = None

        # Tier 1: Try OS-provided stable machine ID (preferred method)
        os_machine_id = self._get_os_machine_id()
        if os_machine_id:
            machine_string = f"os_id|{os_machine_id}"
            logger.debug("Using OS-level machine identifier")
        else:
            # Tier 2: Fallback to hardware fingerprint
            logger.debug("OS machine ID unavailable, using hardware fingerprint")
            hardware_fingerprint = self._get_hardware_fingerprint()
            machine_string = f"hw_fingerprint|{hardware_fingerprint}"

        # Tier 3: Extreme fallback (should rarely happen)
        if not machine_string or machine_string == "hw_fingerprint|fallback_fingerprint":
            logger.warning(
                "Unable to generate stable machine ID from system. "
                "Machine ID may not be consistent across runs. "
                "This can happen on systems with restricted permissions or unusual configurations."
            )
            # Use a very basic fallback - at least try to be somewhat stable
            import uuid

            fallback_data = f"{platform.system()}|{platform.machine()}|{uuid.getnode()}"
            machine_string = f"fallback|{fallback_data}"

        # Apply optional salt
        if self.config.machine_id_salt:
            machine_string += f"|{self.config.machine_id_salt}"

        # Hash for anonymization (prevents exposing actual UUIDs/hardware info)
        hasher = hashlib.sha256(machine_string.encode("utf-8"))
        anonymous_id = f"machine_{hasher.hexdigest()[:16]}"

        self._machine_id_cache = anonymous_id
        logger.debug(f"Generated anonymous machine ID: {anonymous_id}")
        return anonymous_id

    def anonymize_system_profile(self) -> dict[str, Any]:
        """Generate anonymized system profile information.

        Returns:
            Dictionary with anonymized system information
        """
        if not self.config.include_system_profile:
            return {}

        profile = {}

        try:
            # Operating system (safe to include)
            profile["os_type"] = platform.system()
            profile["os_release"] = platform.release()
            profile["architecture"] = platform.machine()

            # Hardware information (generally safe)
            profile["cpu_count"] = os.cpu_count()
            profile["python_version"] = platform.python_version()

            # Memory information (if available, in general terms)
            try:
                import psutil

                memory = psutil.virtual_memory()
                # Round to nearest GB for privacy
                profile["memory_gb"] = round(memory.total / (1024**3))
            except ImportError:
                profile["memory_gb"] = None

            # Hostname (anonymized if requested)
            if self.config.anonymize_hostnames:
                hostname = platform.node()
                if hostname not in self._hostname_mapping:
                    hash_obj = hashlib.md5(hostname.encode())
                    self._hostname_mapping[hostname] = f"host_{hash_obj.hexdigest()[:8]}"
                profile["hostname"] = self._hostname_mapping[hostname]
            else:
                profile["hostname"] = platform.node()

            # Username (anonymized if requested)
            if self.config.anonymize_usernames:
                try:
                    username = os.getlogin()
                    hash_obj = hashlib.md5(username.encode())
                    profile["username"] = f"user_{hash_obj.hexdigest()[:8]}"
                except Exception:
                    profile["username"] = "anonymous"
            else:
                profile["username"] = os.getlogin() if hasattr(os, "getlogin") else "unknown"

        except Exception as e:
            logger.warning(f"Failed to collect system profile: {e}")
            profile["collection_error"] = str(e)

        return profile

    def sanitize_path(self, path: str) -> str:
        """Sanitize file paths by removing or anonymizing sensitive components.

        Args:
            path: File path to sanitize

        Returns:
            Sanitized path string
        """
        if not self.config.anonymize_paths:
            return path

        original_path = str(path)

        # Check if path is in allowed prefixes (keep as-is)
        for prefix in self.config.allowed_path_prefixes:
            if original_path.startswith(prefix):
                return original_path

        # Use cached mapping if available
        if original_path in self._path_mapping:
            return self._path_mapping[original_path]

        # Parse path components
        path_obj = Path(original_path)
        sanitized_parts = []

        # Handle different path components
        for i, part in enumerate(path_obj.parts):
            if i == 0:
                # Root or drive - keep structure but anonymize
                if part.startswith("/"):
                    sanitized_parts.append("/")
                elif ":" in part:  # Windows drive
                    sanitized_parts.append("C:")
                else:
                    sanitized_parts.append(part)
            elif part in ["tmp", "temp", "var", "usr", "opt", "home", "Users"]:
                # Common system directories - keep
                sanitized_parts.append(part)
            elif len(part) > 20 or any(char.isdigit() for char in part):
                # Long names or names with numbers - likely UUIDs or sensitive
                hash_obj = hashlib.md5(part.encode())
                sanitized_parts.append(f"dir_{hash_obj.hexdigest()[:8]}")
            else:
                # Regular directory names - keep
                sanitized_parts.append(part)

        sanitized_path = str(Path(*sanitized_parts))

        # Cache the mapping
        self._path_mapping[original_path] = sanitized_path

        return sanitized_path

    def remove_pii(self, text: str) -> str:
        """Remove personally identifiable information from text.

        Args:
            text: Text to clean

        Returns:
            Text with PII removed or anonymized
        """
        if not text:
            return text

        cleaned_text = text

        # Apply built-in PII patterns
        for pattern in self.config.pii_patterns:
            cleaned_text = re.sub(pattern, "[REDACTED]", cleaned_text, flags=re.IGNORECASE)

        # Apply custom sanitizers
        for pattern, replacement in self.config.custom_sanitizers.items():
            cleaned_text = re.sub(pattern, replacement, cleaned_text, flags=re.IGNORECASE)

        return cleaned_text

    def anonymize_query_metadata(self, query_metadata: dict[str, Any]) -> dict[str, Any]:
        """Anonymize query execution metadata.

        Args:
            query_metadata: Original query metadata

        Returns:
            Anonymized metadata dictionary
        """
        if not query_metadata:
            return {}

        anonymized = {}

        for key, value in query_metadata.items():
            if key in ["query_id", "execution_time", "rows_returned", "status"]:
                # Safe metadata - keep as-is
                anonymized[key] = value
            elif key == "sql_text":
                # Clean SQL text of PII
                anonymized[key] = self.remove_pii(str(value))
            elif key in ["file_path", "data_path", "output_path"]:
                # Paths - sanitize
                anonymized[key] = self.sanitize_path(str(value))
            elif isinstance(value, str):
                # String values - clean of PII
                anonymized[key] = self.remove_pii(value)
            elif isinstance(value, dict):
                # Nested dictionaries - recurse
                anonymized[key] = self.anonymize_query_metadata(value)
            elif isinstance(value, list):
                # Lists - process each item
                anonymized[key] = [
                    self.anonymize_query_metadata(item)
                    if isinstance(item, dict)
                    else self.remove_pii(str(item))
                    if isinstance(item, str)
                    else item
                    for item in value
                ]
            else:
                # Other types - keep as-is
                anonymized[key] = value

        return anonymized

    def anonymize_execution_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Anonymize complete execution metadata.

        Args:
            metadata: Original execution metadata

        Returns:
            Fully anonymized metadata dictionary
        """
        if not metadata:
            return {}

        anonymized = {
            "anonymization_version": "1.0",
            "anonymized_at": metadata.get("timestamp", "unknown"),
        }

        # Process each metadata field
        for key, value in metadata.items():
            if key in [
                "benchmark_name",
                "platform",
                "scale_factor",
                "execution_id",
                "timestamp",
                "duration_seconds",
                "total_queries",
                "successful_queries",
            ]:
                # Safe benchmark metadata
                anonymized[key] = value
            elif key == "machine_id":
                # Replace with anonymous ID
                anonymized["anonymous_machine_id"] = self.get_anonymous_machine_id()
            elif key == "system_profile":
                # Anonymize system information
                anonymized["system_profile"] = self.anonymize_system_profile()
            elif key in ["database_path", "data_directory", "output_directory"]:
                # Paths - sanitize
                anonymized[key] = self.sanitize_path(str(value))
            elif key == "query_results" and isinstance(value, list):
                # Query results - anonymize each
                anonymized[key] = [self.anonymize_query_metadata(query) for query in value]
            elif isinstance(value, dict):
                # Nested dictionaries
                anonymized[key] = self.anonymize_execution_metadata(value)
            elif isinstance(value, str):
                # String values
                anonymized[key] = self.remove_pii(value)
            else:
                # Other values - keep as-is
                anonymized[key] = value

        return anonymized

    def validate_anonymization(self, original_data: dict[str, Any], anonymized_data: dict[str, Any]) -> dict[str, Any]:
        """Validate that anonymization was successful.

        Args:
            original_data: Original data before anonymization
            anonymized_data: Data after anonymization

        Returns:
            Validation results dictionary
        """
        validation = {
            "is_valid": True,
            "warnings": [],
            "errors": [],
            "checks_performed": [],
        }

        # Check for potential PII leaks
        str(original_data).lower()
        anonymized_str = str(anonymized_data).lower()

        # Check for common PII patterns in anonymized data
        pii_checks = [
            (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "IP addresses"),
            (r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", "email addresses"),
            (r"/home/[^/]+", "home directory paths"),
            (r"/users/[^/]+", "user directory paths"),
            (r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", "UUIDs"),
        ]

        for pattern, description in pii_checks:
            if re.search(pattern, anonymized_str, re.IGNORECASE):
                validation["warnings"].append(f"Potential {description} found in anonymized data")
            validation["checks_performed"].append(f"Checked for {description}")

        # Verify anonymous machine ID is present
        if self.config.include_machine_id:
            if "anonymous_machine_id" not in anonymized_str:
                validation["errors"].append("Anonymous machine ID not found in anonymized data")
            validation["checks_performed"].append("Anonymous machine ID presence")

        # Check that system profile is anonymized
        if self.config.include_system_profile:
            if "system_profile" in anonymized_data:
                profile = anonymized_data["system_profile"]
                if self.config.anonymize_hostnames and "hostname" in profile:
                    if not profile["hostname"].startswith("host_"):
                        validation["warnings"].append("Hostname may not be properly anonymized")
                if self.config.anonymize_usernames and "username" in profile:
                    if not profile["username"].startswith("user_"):
                        validation["warnings"].append("Username may not be properly anonymized")
            validation["checks_performed"].append("System profile anonymization")

        validation["is_valid"] = len(validation["errors"]) == 0

        return validation
