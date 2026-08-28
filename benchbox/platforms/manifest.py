"""Compatibility facade for the core-owned platform manifest.

The import-safe authority lives below the platform layer so core registry code
does not depend upward on ``benchbox.platforms``. New internal consumers should
import ``benchbox.core.platform_manifest`` directly.
"""

from benchbox.core.platform_manifest import (
    PLATFORM_MANIFEST,
    PLATFORM_MANIFEST_BY_KEY,
    SUPPORT_STATUS_VALUES,
    AdapterImportSpec,
    AliasScope,
    DefaultMode,
    PlatformAliasSpec,
    PlatformManifestEntry,
    SupportStatus,
    get_adapter_imports,
    get_all_platform_aliases,
    get_platform_alias_modes,
    get_platform_aliases,
    get_platform_manifest_entry,
    get_platform_metadata,
    is_valid_platform_key,
)

__all__ = [
    "AdapterImportSpec",
    "AliasScope",
    "DefaultMode",
    "PLATFORM_MANIFEST",
    "PLATFORM_MANIFEST_BY_KEY",
    "PlatformAliasSpec",
    "PlatformManifestEntry",
    "SUPPORT_STATUS_VALUES",
    "SupportStatus",
    "get_adapter_imports",
    "get_all_platform_aliases",
    "get_platform_alias_modes",
    "get_platform_aliases",
    "get_platform_manifest_entry",
    "get_platform_metadata",
    "is_valid_platform_key",
]
