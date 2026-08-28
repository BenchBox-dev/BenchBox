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
from urllib.parse import urlparse

import yaml

from benchbox.core.results import platform_options as _platform_options

is_secret_option_key = _platform_options.is_secret_option_key
# Compatibility export for callers/tests that compare the shared classifier's
# source list; behavior goes through ``is_secret_option_key`` below.
_SECRET_KEY_PARTS = _platform_options._SECRET_KEY_PARTS

logger = logging.getLogger(__name__)

PUBLIC_REDACTED_VALUE = "<redacted>"


def _load_anonymization_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("anonymization_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_ANONYMIZATION_SPECS = _load_anonymization_specs()

# Secret-key matching is shared with the internal capture path through
# ``is_secret_option_key`` so the lists cannot diverge again. The spec file
# deliberately no longer carries its own copy - the two hand-synced lists
# drifted within a month of #1346 (``keyid`` was added to platform_options
# only), which left ``*_key_id`` values unredacted on this public path.
_IDENTIFIER_KEYS = dict(_ANONYMIZATION_SPECS["identifier_keys"])
_ENDPOINT_KEYS = set(_ANONYMIZATION_SPECS["endpoint_keys"])
_PATH_KEYS = set(_ANONYMIZATION_SPECS["path_keys"])
_MOUNT_COLLECTION_KEYS = set(_ANONYMIZATION_SPECS["mount_collection_keys"])
_MOUNT_PATH_KEYS = set(_ANONYMIZATION_SPECS["mount_path_keys"])
_LOCAL_ENDPOINT_VALUES = set(_ANONYMIZATION_SPECS["local_endpoint_values"])
_MESSAGE_KEYS = set(_ANONYMIZATION_SPECS["message_keys"])
# Unread identifier fields: omit at the public boundary rather than publish a
# confirmable pseudonym. Compact forms; see anonymization_specs.yaml.
_PUBLIC_DROP_KEYS = frozenset(_ANONYMIZATION_SPECS["public_drop_keys"])
# Optional nested maps that collapse to `{}` after drop keys are removed.
# Omit the empty block rather than publishing a hollow object (e.g. client_host
# that only held machine_id). Compact forms match ``_compact_key``.
_PUBLIC_EMPTY_OPTIONAL_MAP_KEYS = frozenset({"clienthost"})

_MESSAGE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_])("
    r"(?:~|/Users|/home|/root|/private/var|/var/folders|/var/run|/Volumes)/[^\s'\",;)]*"
    r"|[A-Za-z]:\\Users\\[^\s'\",;)]*"
    r")"
)
_TUNING_SOURCE_REFERENCE_RE = re.compile(
    r"[a-z0-9_.-]+(?:/[a-z0-9_.-]+)*(?::[0-9a-f]{16,64})?",
    re.IGNORECASE,
)
_MESSAGE_URL_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s'\",;)]*", flags=re.IGNORECASE)
_MESSAGE_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b([a-z0-9][a-z0-9_.-]*)=[^&\s,;)]*",
    flags=re.IGNORECASE,
)
# Public bundles may contain path-like values below generic metadata keys
# (for example ``working_dir`` or a nested ``raw_config`` entry).  Keep this
# detector deliberately narrower than a generic slash matcher: URL paths,
# SQL literals, and repository-relative tuning references must remain intact.
_PRIVATE_LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    r"(?:~|/Users|/home|/root|/private/var|/var/folders|/var/run|/Volumes)/[^\s'\",;)]*"
    r"|[A-Za-z]:\\Users\\[^\s'\",;)]*"
    r")",
    flags=re.IGNORECASE,
)


def _compact_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", key.lower())


# Width of the digest carried by a public pseudonym. Shared by the emitter and
# the recognizer below so the two cannot drift into a non-idempotent pair.
_PUBLIC_HASH_WIDTH = 12
_PUBLIC_HASH_DIGITS = frozenset("0123456789abcdef")


def _is_public_pseudonym(value: str, prefix: str) -> bool:
    """Return whether *value* is already the pseudonym ``prefix`` would emit.

    Deliberately scoped to one prefix and to the exact emitted digest width
    rather than matching any pseudonym-shaped token: see
    ``AnonymizationManager._hash_public_identifier``.
    """
    marker = f"{prefix}_"
    if not value.startswith(marker):
        return False
    digest = value[len(marker) :]
    return len(digest) == _PUBLIC_HASH_WIDTH and all(char in _PUBLIC_HASH_DIGITS for char in digest)


# Community-facing publish paths (``benchbox submit``) require a non-empty salt
# from this env var. The value must not be baked into the repository.
PUBLIC_PSEUDONYM_SALT_ENV = "BENCHBOX_MACHINE_ID_SALT"


class MissingPublicPseudonymSaltError(ValueError):
    """Raised when a community-facing path is used without a deployment salt."""


def resolve_public_pseudonym_salt(
    *,
    explicit: Optional[str] = None,
    environ: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """Return a non-empty public pseudonym salt, or ``None`` if unset.

    Precedence: *explicit* argument, then :data:`PUBLIC_PSEUDONYM_SALT_ENV`.
    Empty strings are treated as unset. The OSS default remains empty so a
    repository-baked constant cannot pretend to be a secret.
    """
    if explicit is not None:
        stripped = str(explicit).strip()
        return stripped or None
    env = environ if environ is not None else os.environ
    raw = env.get(PUBLIC_PSEUDONYM_SALT_ENV)
    if raw is None:
        return None
    stripped = str(raw).strip()
    return stripped or None


def require_public_pseudonym_salt(
    *,
    explicit: Optional[str] = None,
    environ: Optional[dict[str, str]] = None,
) -> str:
    """Return a non-empty salt or raise :class:`MissingPublicPseudonymSaltError`.

    Use on community-facing publish paths only. Private/local export may still
    use an empty default salt.
    """
    salt = resolve_public_pseudonym_salt(explicit=explicit, environ=environ)
    if salt is None:
        raise MissingPublicPseudonymSaltError(
            "Community publish requires a non-empty public pseudonym salt. "
            f"Set the {PUBLIC_PSEUDONYM_SALT_ENV} environment variable to a "
            "deployment-private value before the first public export/submit. "
            "See docs/development/adr/adr-published-identifier-field-set.md "
            "(retained-field salt decision)."
        )
    return salt


@dataclass
class AnonymizationConfig:
    """Configuration for result anonymization.

    ``machine_id_salt`` defaults to empty. Under that default, public
    identifier pseudonyms are a confirmation oracle for anyone who knows the
    documented hash (see ``adr-published-identifier-field-set`` retained-field
    salt decision). Open-source BenchBox keeps the empty default so a
    repository-baked salt cannot pretend to be a secret. Operators who publish
    community-facing results must set a non-empty salt known only to the
    deployment before the first public export (via ``machine_id_salt`` or
    :data:`PUBLIC_PSEUDONYM_SALT_ENV`). Already-public-shaped tokens still pass
    through unchanged (publication fixed point).
    """

    # Machine identification. The salt feeds both get_anonymous_machine_id and
    # the public pseudonym hash, so it is the one knob that changes published
    # identity for *raw* values. Empty default = residual confirmation oracle.
    machine_id_salt: Optional[str] = None

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

    @classmethod
    def from_public_environ(
        cls,
        *,
        environ: Optional[dict[str, str]] = None,
        require_salt: bool = False,
    ) -> "AnonymizationConfig":
        """Build config from the public-salt environment variable.

        When *require_salt* is true, raises :class:`MissingPublicPseudonymSaltError`
        if the salt is unset (community publish). When false, empty salt is allowed
        for private/local use.
        """
        if require_salt:
            salt: Optional[str] = require_public_pseudonym_salt(environ=environ)
        else:
            salt = resolve_public_pseudonym_salt(environ=environ)
        return cls(machine_id_salt=salt)


class AnonymizationManager:
    """Manages anonymization of benchmark results and metadata."""

    def __init__(self, config: Optional[AnonymizationConfig] = None):
        """Initialize the anonymization manager.

        Args:
            config: Anonymization configuration (uses defaults if None)
        """
        self.config = config or AnonymizationConfig()
        self._machine_id_cache: Optional[str] = None

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

    def anonymize_result_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Anonymize public result payload metadata beyond the client host block.

        This is intentionally key-aware: secret-like keys are redacted, while
        stable infrastructure identifiers are hashed so public artifacts can
        still be grouped without exposing account, endpoint, storage, or
        container identities.
        """
        return self._anonymize_public_value(payload, ())

    def anonymize_tuning_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Anonymize a tuning companion while preserving normalized provenance.

        Tuning payloads use table names as mapping keys and column names under
        a generic ``name`` key, so the generic payload walker cannot identify
        those identifiers. Current capture emits ``source_file`` as a normalized
        repository-relative reference, optionally suffixed by a content digest.
        Legacy or user-authored companions are untrusted, so any other value is
        path-hashed before a bundle is re-exported.
        """
        source_file = payload.get("source_file")
        working = dict(payload)
        working.pop("source_file", None)

        requested = working.get("requested")
        constraints = None
        table_tunings = None
        if isinstance(requested, dict):
            requested = dict(requested)
            constraints = requested.get("constraints")
            table_tunings = requested.pop("table_tunings", None)
            working["requested"] = requested

        anonymized = self.anonymize_result_payload(working)
        if source_file is not None:
            anonymized["source_file"] = (
                source_file
                if self._is_normalized_tuning_source_reference(source_file)
                else self._hash_public_identifier(str(source_file), "path")
            )
        if constraints is not None or table_tunings is not None:
            anonymized_requested = anonymized.setdefault("requested", {})
            if isinstance(anonymized_requested, dict):
                # Non-dict companions (list-of-constraint-dicts) are untrusted
                # shapes too; route every non-None value through the recursive
                # constraint walker rather than only dict payloads.
                if constraints is not None:
                    anonymized_requested["constraints"] = self._anonymize_tuning_constraints(constraints)
                if table_tunings is not None:
                    anonymized_requested["table_tunings"] = self._anonymize_tuning_table_tunings(table_tunings)
        return anonymized

    @staticmethod
    def _is_normalized_tuning_source_reference(value: Any) -> bool:
        """Return whether *value* is a safe repo-relative/template reference."""
        if not isinstance(value, str) or not _TUNING_SOURCE_REFERENCE_RE.fullmatch(value):
            return False
        reference = value.rpartition(":")[0] if ":" in value else value
        return bool(reference) and all(part not in {"", ".", ".."} for part in reference.split("/"))

    # Identifier-bearing companion keys. Scalar keys hash the value (including
    # slash-delimited compounds such as ``orders/o_orderkey`` as one token so
    # neither segment survives). Collection keys hash list/dict containers while
    # recursing into nested dict entries so list-of-dicts FK shapes do not leak.
    _CONSTRAINT_TABLE_SCALAR_KEYS = frozenset(
        {
            "table",
            "table_name",
            "referenced_table",
            "referenced_table_name",
            "local_table",
            "references_table",
        }
    )
    _CONSTRAINT_COLUMN_SCALAR_KEYS = frozenset(
        {
            "column",
            "column_name",
            "name",
            "referenced_column",
            "referenced_column_name",
            "references_column",
            "local_column",
        }
    )
    _CONSTRAINT_TABLE_COLLECTION_KEYS = frozenset({"tables", "table_names", "referenced_tables"})
    _CONSTRAINT_COLUMN_COLLECTION_KEYS = frozenset(
        {"columns", "column_names", "referenced_columns", "referenced_column_names"}
    )

    def _anonymize_tuning_constraints(self, value: Any) -> Any:
        """Anonymize table/column identifiers nested in constraint settings.

        Walks dict/list/tuple companions recursively. Only identifier-bearing
        keys (table/column scalars and collections, including TPC-DI-style
        ``local_table`` / ``references_table``) are pseudonymized; enabled
        flags, actions, and unrelated tuning values pass through.
        """
        if isinstance(value, dict):
            anonymized: dict[str, Any] = {}
            for key, child in value.items():
                # Same drop set as the public walker: omit unread identifiers
                # rather than KeyErroring when the scalar walk drops the key.
                if _compact_key(str(key)) in _PUBLIC_DROP_KEYS:
                    continue
                if key in self._CONSTRAINT_TABLE_SCALAR_KEYS:
                    anonymized[key] = self._anonymize_constraint_identifier_value(child, "table")
                elif key in self._CONSTRAINT_COLUMN_SCALAR_KEYS:
                    anonymized[key] = self._anonymize_constraint_identifier_value(child, "column")
                elif key in self._CONSTRAINT_TABLE_COLLECTION_KEYS:
                    anonymized[key] = self._anonymize_constraint_identifier_collection(child, "table")
                elif key in self._CONSTRAINT_COLUMN_COLLECTION_KEYS:
                    anonymized[key] = self._anonymize_constraint_identifier_collection(child, "column")
                else:
                    if isinstance(child, (dict, list, tuple)):
                        anonymized[key] = self._anonymize_tuning_constraints(child)
                    else:
                        walked = self._anonymize_public_value({str(key): child}, ())
                        if str(key) in walked:
                            anonymized[key] = walked[str(key)]
            return anonymized
        if isinstance(value, list):
            return [self._anonymize_tuning_constraints(item) for item in value]
        if isinstance(value, tuple):
            return [self._anonymize_tuning_constraints(item) for item in value]
        return value

    def _anonymize_constraint_identifier_value(self, value: Any, prefix: str) -> Any:
        """Hash one identifier scalar, or walk a nested collection under a scalar key."""
        if isinstance(value, (dict, list, tuple)):
            return self._anonymize_constraint_identifier_collection(value, prefix)
        if value in (None, ""):
            return value
        return self._hash_public_identifier(str(value), prefix)

    def _anonymize_constraint_identifier_collection(self, value: Any, prefix: str) -> Any:
        """Hash identifier collections while preserving their container shape.

        Dict keys are table/column identifiers. List/tuple string items are
        hashed; nested dicts/lists recurse so list-of-dicts FK companions
        (``tables: [{table, columns, referenced_table}, ...]``) do not pass
        through unhashed.
        """
        if isinstance(value, dict):
            return {
                self._hash_public_identifier(str(key), prefix): self._anonymize_constraint_columns(child)
                for key, child in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self._anonymize_constraint_identifier_item(item, prefix) for item in value]
        if isinstance(value, str):
            return self._hash_public_identifier(value, prefix)
        return value

    def _anonymize_constraint_identifier_item(self, item: Any, prefix: str) -> Any:
        """Hash one collection member, or recurse into nested companion structure."""
        if isinstance(item, str):
            return self._hash_public_identifier(item, prefix)
        if isinstance(item, dict):
            return self._anonymize_tuning_constraints(item)
        if isinstance(item, (list, tuple)):
            return [self._anonymize_constraint_identifier_item(child, prefix) for child in item]
        return item

    def _anonymize_constraint_columns(self, value: Any) -> Any:
        """Hash column lists stored as values under a table identifier."""
        if isinstance(value, (list, tuple)):
            return [self._anonymize_constraint_identifier_item(item, "column") for item in value]
        if isinstance(value, dict):
            return self._anonymize_tuning_constraints(value)
        if isinstance(value, str):
            return self._hash_public_identifier(value, "column")
        return value

    def _anonymize_tuning_table_tunings(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                self._hash_public_identifier(str(key), "table"): self._anonymize_tuning_value(child)
                for key, child in value.items()
            }
        return self._anonymize_tuning_value(value)

    def _anonymize_tuning_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            anonymized: dict[str, Any] = {}
            for key, child in value.items():
                if _compact_key(str(key)) in _PUBLIC_DROP_KEYS:
                    continue
                if key in {"table", "table_name"}:
                    anonymized[key] = self._hash_public_identifier(str(child), "table")
                elif key in {"column", "column_name", "name"}:
                    anonymized[key] = self._hash_public_identifier(str(child), "column")
                else:
                    anonymized[key] = self._anonymize_tuning_value(child)
            return anonymized
        if isinstance(value, list):
            return [self._anonymize_tuning_value(item) for item in value]
        if isinstance(value, tuple):
            return [self._anonymize_tuning_value(item) for item in value]
        return value

    def _anonymize_public_value(self, value: Any, key_path: tuple[str, ...]) -> Any:
        if isinstance(value, dict):
            anonymized: dict[str, Any] = {}
            for key, child in value.items():
                # Drop unread identifier fields at every nesting depth so they
                # never appear as pseudonyms in public bundles (ADR published
                # identifier field set).
                if _compact_key(str(key)) in _PUBLIC_DROP_KEYS:
                    continue
                child_path = (*key_path, str(key))
                if self._is_secret_metadata_key(child_path):
                    child_value = PUBLIC_REDACTED_VALUE if child not in (None, "") else child
                else:
                    child_value = self._anonymize_public_value(child, child_path)
                # After dropping identifier-only content (e.g. client_host with
                # only machine_id), omit empty optional blocks rather than
                # publishing a hollow object. Non-empty profiles keep.
                # One-time corpus re-derive (rederive-prune-empty-client-host)
                # also strips already-empty `{}` residuals so stored bytes match
                # the fresh public shape.
                if (
                    isinstance(child_value, dict)
                    and not child_value
                    and _compact_key(str(key)) in _PUBLIC_EMPTY_OPTIONAL_MAP_KEYS
                ):
                    continue
                anonymized[key] = child_value
            return anonymized

        if isinstance(value, (set, frozenset)):
            # Set iteration depends on PYTHONHASHSEED. Sort by the stable
            # scalar representation before recursing so canonical JSON is
            # reproducible across processes.
            value = sorted(value, key=repr)

        if isinstance(value, (list, tuple, set, frozenset)):
            # Tuples/sets serialize as JSON arrays; recursing as a list keeps
            # their contents inside the anonymization boundary instead of
            # falling through to the scalar branch untouched.
            return [self._anonymize_public_value(item, key_path) for item in value]

        return self._anonymize_public_scalar(value, key_path)

    def _anonymize_public_scalar(self, value: Any, key_path: tuple[str, ...]) -> Any:
        if value in (None, ""):
            return value

        if isinstance(value, str) and self._looks_like_connection_string(value):
            return PUBLIC_REDACTED_VALUE

        if isinstance(value, str) and self._is_message_metadata_key(key_path):
            return self._sanitize_public_message(value)

        if isinstance(value, str):
            # Key-aware path handling covers the normal schema fields, while
            # this recursive value check protects generic/nested metadata that
            # a producer can add without first adding a field-name allowlist.
            # Replace only the private path token so surrounding diagnostic
            # text remains useful and URLs/SQL are not blanket-redacted.
            value = _PRIVATE_LOCAL_PATH_RE.sub(
                lambda match: self._hash_public_identifier(match.group(0), "path"),
                value,
            )

        prefix = self._identifier_prefix_for_key_path(key_path)
        if prefix is not None:
            if prefix == "host" and isinstance(value, str) and self._is_local_endpoint_value(value):
                return value
            return self._hash_public_identifier(str(value), prefix)

        if isinstance(value, str):
            return self.remove_pii(value)

        return value

    def _is_secret_metadata_key(self, key_path: tuple[str, ...]) -> bool:
        return bool(key_path) and is_secret_option_key(key_path[-1])

    def _is_message_metadata_key(self, key_path: tuple[str, ...]) -> bool:
        key = _compact_key(key_path[-1]) if key_path else ""
        return key in _MESSAGE_KEYS or key.endswith("message") or key.endswith("error") or key.endswith("errors")

    def _identifier_prefix_for_key_path(self, key_path: tuple[str, ...]) -> str | None:
        if not key_path:
            return None

        key = _compact_key(key_path[-1])
        parent = _compact_key(key_path[-2]) if len(key_path) >= 2 else ""

        if parent in _MOUNT_COLLECTION_KEYS and key in _MOUNT_PATH_KEYS:
            return "path"
        if key in _IDENTIFIER_KEYS:
            return _IDENTIFIER_KEYS[key]
        if key.endswith("bucket"):
            return "bucket"
        if key.endswith("prefix"):
            return "prefix"
        if key.endswith("arn"):
            return "arn"
        if key.endswith("host") or key.endswith("hostname") or key in _ENDPOINT_KEYS:
            return "host" if key in {"host", "hostname", "server", "enginehost"} else "endpoint"
        if key.endswith("url") or key.endswith("endpoint"):
            return "endpoint"
        if (
            key.endswith("path")
            or key.endswith("directory")
            or key.endswith("dir")
            or key.endswith("folder")
            or key.endswith("root")
            or key.endswith("file")
            or key.endswith("executable")
            or key in _PATH_KEYS
        ):
            return "path"
        return None

    def _hash_public_identifier(self, value: str, prefix: str) -> str:
        """Hash one identifier into a stable public pseudonym.

        Anonymization has to reach a fixed point. Curated bundles are stored
        already-anonymized, so the Explorer publication boundary re-anonymizes
        values this method produced; hashing them a second time would mint a
        different pseudonym for the same machine than a freshly submitted run
        gets, and pseudonym stability is what lets the Explorer group results
        by machine at all. A value already carrying *this* prefix's pseudonym
        shape therefore passes through untouched.

        The pass-through is scoped to ``prefix`` and to the exact emitted
        digest width, not to pseudonym shape in general. That keeps a
        capture-side ``machine_<16 hex>`` hashed, so internal and public
        identities stay decoupled, and stops a ``host_`` token from surviving
        verbatim inside a ``path_`` field. A submitter can still hand-craft a
        value of this shape to pick their own pseudonym, so a pseudonym is a
        grouping key only - never a provenance or trust signal. Provenance is
        carried by trust labels.
        """
        if _is_public_pseudonym(value, prefix):
            return value
        salt = self.config.machine_id_salt or ""
        digest = hashlib.sha256(f"{salt}|{prefix}|{value}".encode()).hexdigest()[:_PUBLIC_HASH_WIDTH]
        return f"{prefix}_{digest}"

    @staticmethod
    def _is_local_endpoint_value(value: str) -> bool:
        value = value.strip()
        parsed = urlparse(value if "://" in value else f"//{value}")
        host = (parsed.hostname or value.split("/", 1)[0].split(":", 1)[0]).lower()
        return host in _LOCAL_ENDPOINT_VALUES

    @staticmethod
    def _looks_like_connection_string(value: str) -> bool:
        if re.search(r"://[^/@\s:]+:[^/@\s]+@", value):
            return True
        return any(is_secret_option_key(match.group(1)) for match in _MESSAGE_SECRET_ASSIGNMENT_RE.finditer(value))

    def _sanitize_public_message(self, value: str) -> str:
        cleaned = self.remove_pii(value)
        cleaned = _MESSAGE_SECRET_ASSIGNMENT_RE.sub(
            lambda match: (
                f"{match.group(1)}={PUBLIC_REDACTED_VALUE}" if is_secret_option_key(match.group(1)) else match.group(0)
            ),
            cleaned,
        )
        cleaned = _MESSAGE_URL_RE.sub(lambda match: self._hash_public_identifier(match.group(0), "endpoint"), cleaned)
        cleaned = _MESSAGE_PATH_RE.sub(lambda match: self._hash_public_identifier(match.group(0), "path"), cleaned)
        return cleaned

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


def find_public_path_leaks(value: Any, key_path: tuple[str, ...] = ()) -> list[str]:
    """Return dotted paths containing private absolute paths in public JSON.

    The detector is intentionally value-redacting: callers can report the
    offending field path without echoing a user's home directory or other
    machine-local material.  It is shared by submission validation and the
    Explorer publication boundary so both surfaces enforce the same contract.

    Object *keys* are checked as well as values.  A payload can encode a path
    as a mapping key -- ``{"per_path_timings": {"/Users/alice/db": 1.2}}`` is
    the shape that occurs in practice -- and scanning values alone would call
    that clean.  Such a key is reported at ``<parent>.<key>`` with the key
    itself elided, because the offending string *is* the private path and
    naming it would break the redaction contract above.
    """

    leaks: list[str] = []

    if isinstance(value, dict):
        for key, child in value.items():
            # A leaking key is elided in its own report *and* in the path of
            # everything beneath it: recursing with the raw key would put the
            # private path back into a descendant's diagnostic, which is the
            # one place these strings are surfaced (PR comments, exceptions).
            label = str(key)
            if isinstance(key, str) and _PRIVATE_LOCAL_PATH_RE.search(key):
                label = "<key>"
                leaks.append(".".join((*key_path, label)))
            leaks.extend(find_public_path_leaks(child, (*key_path, label)))
        return leaks

    if isinstance(value, (list, tuple, set, frozenset)):
        for index, child in enumerate(value):
            leaks.extend(find_public_path_leaks(child, (*key_path, str(index))))
        return leaks

    if isinstance(value, str) and _PRIVATE_LOCAL_PATH_RE.search(value):
        leaks.append(".".join(key_path) or "<root>")
    return leaks


__all__ = [
    "PUBLIC_PSEUDONYM_SALT_ENV",
    "PUBLIC_REDACTED_VALUE",
    "AnonymizationConfig",
    "AnonymizationManager",
    "MissingPublicPseudonymSaltError",
    "find_public_path_leaks",
    "require_public_pseudonym_salt",
    "resolve_public_pseudonym_salt",
]
