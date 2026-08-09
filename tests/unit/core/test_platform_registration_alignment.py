"""Tests for manifest-derived platform registration and capability alignment.

Static platform sets are projections of the typed manifest. Subsystem-specific
maps are tested as semantic consumers, never restated here as another registry.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.platform_manifest import PLATFORM_MANIFEST, get_platform_aliases
from benchbox.core.platform_registry import PlatformRegistry

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


CANONICAL_SQL_PLATFORMS = {entry.key for entry in PLATFORM_MANIFEST if entry.capabilities["supports_sql"]}
PLATFORM_ALIASES = get_platform_aliases("cli")
DATAFRAME_ONLY_PLATFORMS = {
    entry.key
    for entry in PLATFORM_MANIFEST
    if entry.capabilities["supports_dataframe"] and not entry.capabilities["supports_sql"] and entry.adapter is None
}
HYBRID_DATAFRAME_PLATFORMS = {
    entry.key
    for entry in PLATFORM_MANIFEST
    if entry.capabilities["supports_dataframe"] and not entry.capabilities["supports_sql"] and entry.adapter is not None
}


class TestPlatformRegistrationAlignment:
    """Tests ensuring platform registration systems stay synchronized."""

    def setup_method(self):
        """Clear registry cache before each test."""
        PlatformRegistry.clear_cache()

    def test_all_canonical_platforms_in_registry_metadata(self):
        """All canonical SQL platforms must have metadata in PlatformRegistry."""
        metadata = PlatformRegistry.get_all_platform_metadata()

        missing = CANONICAL_SQL_PLATFORMS - set(metadata.keys())
        assert not missing, f"Platforms missing from PlatformRegistry metadata: {missing}"

    def test_all_canonical_platforms_registered_in_registry(self):
        """All canonical SQL platforms must be registered in PlatformRegistry._adapters."""
        registered = set(PlatformRegistry.get_available_platforms())

        missing = CANONICAL_SQL_PLATFORMS - registered
        assert not missing, (
            f"Platforms missing from PlatformRegistry._adapters: {missing}. "
            "Add registration in auto_register_platforms()."
        )


class TestPlatformRequirementsAlignment:
    """Tests ensuring platform requirements are consistent between systems."""

    def setup_method(self):
        """Clear registry cache before each test."""
        PlatformRegistry.clear_cache()

    def test_all_platforms_have_metadata_requirements(self):
        """All canonical platforms must have installation requirements in metadata."""
        metadata = PlatformRegistry.get_all_platform_metadata()

        for platform in CANONICAL_SQL_PLATFORMS:
            if platform in metadata:
                spec = metadata[platform]
                assert "installation_command" in spec, f"Platform '{platform}' missing installation_command in metadata"
                assert spec["installation_command"], f"Platform '{platform}' has empty installation_command"

    def test_all_platforms_have_driver_package(self):
        """All canonical platforms should have driver_package defined or be built-in."""
        metadata = PlatformRegistry.get_all_platform_metadata()

        for platform in CANONICAL_SQL_PLATFORMS:
            if platform in metadata:
                spec = metadata[platform]
                # driver_package can be None for built-in (sqlite) or platforms without drivers (polars)
                assert "driver_package" in spec, f"Platform '{platform}' missing driver_package key in metadata"


class TestPlatformCapabilitiesAlignment:
    """Tests ensuring platform capabilities are correctly defined."""

    def setup_method(self):
        """Clear registry cache before each test."""
        PlatformRegistry.clear_cache()

    def test_all_sql_platforms_support_sql_mode(self):
        """All canonical SQL platforms must have supports_sql=True."""
        for platform in CANONICAL_SQL_PLATFORMS:
            caps = PlatformRegistry.get_platform_capabilities(platform)
            assert caps is not None, f"Platform '{platform}' has no capabilities defined"
            assert caps.supports_sql, f"Platform '{platform}' is a SQL platform but supports_sql=False"

    def test_dataframe_only_platforms_dont_support_sql(self):
        """DataFrame-only platforms should have supports_sql=False."""
        for platform in DATAFRAME_ONLY_PLATFORMS:
            caps = PlatformRegistry.get_platform_capabilities(platform)
            if caps is not None:  # May not be registered if deps not installed
                assert not caps.supports_sql, f"DataFrame-only platform '{platform}' should have supports_sql=False"
                assert caps.supports_dataframe, (
                    f"DataFrame-only platform '{platform}' should have supports_dataframe=True"
                )

    def test_hybrid_dataframe_platforms_dont_support_sql(self):
        """Hybrid platforms (have adapters but no SQL) should have supports_sql=False."""
        for platform in HYBRID_DATAFRAME_PLATFORMS:
            caps = PlatformRegistry.get_platform_capabilities(platform)
            if caps is not None:
                assert not caps.supports_sql, (
                    f"Hybrid platform '{platform}' should have supports_sql=False "
                    "(adapter exists for data loading only)"
                )
                assert caps.supports_dataframe, f"Hybrid platform '{platform}' should have supports_dataframe=True"

    def test_dual_mode_platforms_support_both(self):
        """Platforms that support both modes must have both flags True."""
        dual_mode = PlatformRegistry.get_dual_mode_platforms()

        for platform in dual_mode:
            caps = PlatformRegistry.get_platform_capabilities(platform)
            assert caps.supports_sql, f"Dual-mode platform '{platform}' missing supports_sql"
            assert caps.supports_dataframe, f"Dual-mode platform '{platform}' missing supports_dataframe"

    def test_dataframe_adapter_mapping_matches_registry_capabilities(self):
        """The local DataFrame factory's semantic keys must be DataFrame-capable."""
        from benchbox.platforms import _DATAFRAME_PLATFORM_INFO

        for spelling in _DATAFRAME_PLATFORM_INFO:
            canonical = PLATFORM_ALIASES.get(spelling, spelling)
            caps = PlatformRegistry.get_platform_capabilities(canonical)
            assert caps is not None, (
                f"DataFrame factory spelling '{spelling}' resolves to missing platform '{canonical}'"
            )
            assert caps.supports_dataframe, (
                f"DataFrame factory spelling '{spelling}' resolves to platform '{canonical}' without supports_dataframe"
            )


class TestPlatformRegistryAliasResolution:
    """Tests for PlatformRegistry alias resolution."""

    def setup_method(self):
        """Clear registry cache before each test."""
        PlatformRegistry.clear_cache()

    def test_resolve_platform_name_canonical(self):
        """Canonical names should resolve to themselves."""
        assert PlatformRegistry.resolve_platform_name("duckdb") == "duckdb"
        assert PlatformRegistry.resolve_platform_name("sqlite") == "sqlite"
        assert PlatformRegistry.resolve_platform_name("synapse") == "synapse"

    def test_resolve_platform_name_aliases(self):
        """Aliases should resolve to canonical names."""
        assert PlatformRegistry.resolve_platform_name("sqlite3") == "sqlite"
        assert PlatformRegistry.resolve_platform_name("azure_synapse") == "synapse"

    def test_resolve_platform_name_case_insensitive(self):
        """Alias resolution should be case-insensitive."""
        assert PlatformRegistry.resolve_platform_name("SQLITE3") == "sqlite"
        assert PlatformRegistry.resolve_platform_name("SQLite3") == "sqlite"
        assert PlatformRegistry.resolve_platform_name("Azure_Synapse") == "synapse"
        assert PlatformRegistry.resolve_platform_name("AZURE_SYNAPSE") == "synapse"

    def test_resolve_platform_name_unknown(self):
        """Unknown names should return the normalized input."""
        assert PlatformRegistry.resolve_platform_name("unknown") == "unknown"
        assert PlatformRegistry.resolve_platform_name("UNKNOWN") == "unknown"

    def test_get_all_aliases(self):
        """get_all_aliases should return a copy of all aliases."""
        aliases = PlatformRegistry.get_all_aliases()
        assert isinstance(aliases, dict)
        assert "sqlite3" in aliases
        assert aliases["sqlite3"] == "sqlite"
        assert "azure_synapse" in aliases
        assert aliases["azure_synapse"] == "synapse"

    def test_get_all_aliases_returns_copy(self):
        """get_all_aliases should return a copy, not the original."""
        aliases1 = PlatformRegistry.get_all_aliases()
        aliases2 = PlatformRegistry.get_all_aliases()
        assert aliases1 == aliases2
        assert aliases1 is not aliases2
        # Modifying one shouldn't affect the other
        aliases1["test"] = "value"
        assert "test" not in aliases2

    def test_get_platform_info_with_alias(self):
        """get_platform_info should work with aliases."""
        info = PlatformRegistry.get_platform_info("sqlite3")
        assert info is not None
        assert info.name == "sqlite"  # Returns canonical name
        assert info.display_name == "SQLite"

        info = PlatformRegistry.get_platform_info("azure_synapse")
        assert info is not None
        assert info.name == "synapse"  # Returns canonical name

    def test_get_platform_capabilities_with_alias(self):
        """get_platform_capabilities should work with aliases."""
        caps = PlatformRegistry.get_platform_capabilities("sqlite3")
        assert caps is not None
        assert caps.supports_sql is True

        caps = PlatformRegistry.get_platform_capabilities("azure_synapse")
        assert caps is not None
        assert caps.supports_sql is True

    def test_get_adapter_class_with_alias(self):
        """get_adapter_class should work with aliases."""
        # This will work if sqlite adapter is registered
        try:
            adapter_class = PlatformRegistry.get_adapter_class("sqlite3")
            assert adapter_class is not None
            # Verify it's the same as getting by canonical name
            canonical_class = PlatformRegistry.get_adapter_class("sqlite")
            assert adapter_class is canonical_class
        except ValueError:
            # If adapter not registered, that's expected in some test environments
            pass


class TestMetadataConsistency:
    """Tests for metadata consistency across systems."""

    def setup_method(self):
        """Clear registry cache before each test."""
        PlatformRegistry.clear_cache()

    def test_registered_platforms_have_metadata(self):
        """All registered platforms must have corresponding metadata."""
        registered = PlatformRegistry.get_available_platforms()
        metadata = PlatformRegistry.get_all_platform_metadata()

        for platform in registered:
            assert platform in metadata, (
                f"Registered platform '{platform}' has no metadata. Add entry in _build_platform_metadata()."
            )

    def test_metadata_platforms_can_get_info(self):
        """get_platform_info() must work for all platforms with metadata."""
        metadata = PlatformRegistry.get_all_platform_metadata()

        for platform in metadata:
            info = PlatformRegistry.get_platform_info(platform)
            # May be None if not registered, but should not raise
            if info is not None:
                assert info.name == platform
                assert info.display_name == metadata[platform]["display_name"]

    def test_no_orphaned_registrations(self):
        """No platform should be registered without metadata."""
        registered = set(PlatformRegistry.get_available_platforms())
        metadata_platforms = set(PlatformRegistry.get_all_platform_metadata().keys())

        orphaned = registered - metadata_platforms
        assert not orphaned, (
            f"Platforms registered but missing metadata: {orphaned}. Add metadata in _build_platform_metadata()."
        )
