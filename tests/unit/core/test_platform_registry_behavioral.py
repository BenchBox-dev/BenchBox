"""Behavioral tests for PlatformRegistry: registration, lookup, filtering, capabilities.

Targets uncovered paths in core/platform_registry.py to push line coverage
from ~70% toward 85%.  Tests exercise real registry methods (no mocking of
the registry itself) and assert on concrete values.
"""

import pytest

from benchbox.core.platform_registry import (
    DeploymentCapability,
    PlatformCapability,
    PlatformRegistry,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


# ---------------------------------------------------------------------------
# Alias resolution
# ---------------------------------------------------------------------------


class TestAliasResolution:
    def test_resolve_sqlite3_alias(self):
        assert PlatformRegistry.resolve_platform_name("sqlite3") == "sqlite"

    def test_resolve_azure_synapse_alias(self):
        assert PlatformRegistry.resolve_platform_name("azure_synapse") == "synapse"

    def test_resolve_fabric_dw_alias(self):
        assert PlatformRegistry.resolve_platform_name("fabric-dw") == "fabric_dw"

    def test_resolve_canonical_name_unchanged(self):
        assert PlatformRegistry.resolve_platform_name("duckdb") == "duckdb"

    def test_resolve_is_case_insensitive(self):
        assert PlatformRegistry.resolve_platform_name("DuckDB") == "duckdb"
        assert PlatformRegistry.resolve_platform_name("SQLITE3") == "sqlite"

    def test_resolve_unknown_name_returns_lowered(self):
        assert PlatformRegistry.resolve_platform_name("NoSuchPlatform") == "nosuchplatform"

    def test_get_all_aliases_returns_copy(self):
        aliases = PlatformRegistry.get_all_aliases()
        assert isinstance(aliases, dict)
        assert "sqlite3" in aliases
        # Mutating the returned dict should not affect the registry
        aliases["bogus_alias"] = "bogus"
        assert "bogus_alias" not in PlatformRegistry.get_all_aliases()


# ---------------------------------------------------------------------------
# Adapter registration & lookup
# ---------------------------------------------------------------------------


class TestAdapterRegistration:
    def setup_method(self):
        PlatformRegistry.clear_cache()

    def test_get_available_platforms_includes_duckdb(self):
        available = PlatformRegistry.get_available_platforms()
        assert "duckdb" in available

    def test_get_adapter_class_for_duckdb(self):
        from benchbox.platforms.duckdb import DuckDBAdapter

        cls = PlatformRegistry.get_adapter_class("duckdb")
        assert cls is DuckDBAdapter

    def test_get_adapter_class_resolves_alias(self):
        """sqlite3 alias should resolve to the sqlite adapter class."""
        cls = PlatformRegistry.get_adapter_class("sqlite3")
        assert cls.__name__.lower().startswith("sqlite")

    def test_get_adapter_class_unknown_raises(self):
        with pytest.raises(ValueError, match="not registered"):
            PlatformRegistry.get_adapter_class("nosuchplatform_xyz")

    def test_register_adapter_clears_availability_cache(self):
        """Registering a new adapter should invalidate the availability cache."""
        # Prime the cache
        PlatformRegistry.get_platform_availability()
        assert PlatformRegistry._availability_cache is not None

        # Register a dummy adapter (use an existing one to avoid import issues)
        from benchbox.platforms.duckdb import DuckDBAdapter

        PlatformRegistry.register_adapter("duckdb", DuckDBAdapter)
        assert PlatformRegistry._availability_cache is None


# ---------------------------------------------------------------------------
# Availability detection
# ---------------------------------------------------------------------------


class TestPlatformAvailability:
    def setup_method(self):
        PlatformRegistry.clear_cache()

    def test_duckdb_is_available(self):
        assert PlatformRegistry.is_platform_available("duckdb") is True

    def test_unknown_platform_is_not_available(self):
        assert PlatformRegistry.is_platform_available("nosuchplatform_xyz") is False

    def test_availability_cache_is_populated_after_first_call(self):
        PlatformRegistry.get_platform_availability()
        assert PlatformRegistry._availability_cache is not None

    def test_availability_returns_copy(self):
        avail1 = PlatformRegistry.get_platform_availability()
        avail2 = PlatformRegistry.get_platform_availability()
        assert avail1 == avail2
        assert avail1 is not avail2


# ---------------------------------------------------------------------------
# Platform info
# ---------------------------------------------------------------------------


class TestPlatformInfo:
    def test_get_platform_info_duckdb(self):
        info = PlatformRegistry.get_platform_info("duckdb")
        assert info is not None
        assert info.name == "duckdb"
        assert info.display_name == "DuckDB"
        assert info.category == "analytical"
        assert info.available is True
        assert "duckdb" in [lib.name for lib in info.libraries]

    def test_get_platform_info_unknown_returns_none(self):
        info = PlatformRegistry.get_platform_info("nosuchplatform_xyz")
        assert info is None

    def test_get_platform_info_resolves_alias(self):
        info = PlatformRegistry.get_platform_info("sqlite3")
        assert info is not None
        assert info.name == "sqlite"

    def test_driver_package_from_metadata(self):
        info = PlatformRegistry.get_platform_info("duckdb")
        assert info.driver_package == "duckdb"

    def test_get_platform_requirements_returns_string(self):
        reqs = PlatformRegistry.get_platform_requirements("duckdb")
        assert isinstance(reqs, str)
        assert "duckdb" in reqs.lower()

    def test_get_platform_requirements_unknown_returns_fallback(self):
        reqs = PlatformRegistry.get_platform_requirements("nosuchplatform_xyz")
        assert isinstance(reqs, str)


# ---------------------------------------------------------------------------
# Filtering by category and adoption
# ---------------------------------------------------------------------------


class TestPlatformFiltering:
    def test_get_platforms_by_category_analytical(self):
        analytical = PlatformRegistry.get_platforms_by_category("analytical")
        assert "duckdb" in analytical

    def test_get_platforms_by_category_embedded(self):
        embedded = PlatformRegistry.get_platforms_by_category("embedded")
        assert "sqlite" in embedded

    def test_get_platforms_by_category_nonexistent_returns_empty(self):
        result = PlatformRegistry.get_platforms_by_category("does_not_exist")
        assert result == []

    def test_get_platforms_by_adoption_mainstream(self):
        mainstream = PlatformRegistry.get_platforms_by_adoption("mainstream")
        assert "duckdb" in mainstream

    def test_get_platforms_by_adoption_niche_includes_sqlite(self):
        niche = PlatformRegistry.get_platforms_by_adoption("niche")
        assert "sqlite" in niche

    def test_get_platforms_by_adoption_nonexistent_returns_empty(self):
        result = PlatformRegistry.get_platforms_by_adoption("ultra_rare")
        assert result == []


# ---------------------------------------------------------------------------
# Capabilities & modes
# ---------------------------------------------------------------------------


class TestPlatformCapabilities:
    def test_get_platform_capabilities_duckdb(self):
        caps = PlatformRegistry.get_platform_capabilities("duckdb")
        assert isinstance(caps, PlatformCapability)
        assert caps.supports_sql is True
        assert caps.supports_dataframe is False
        assert caps.default_mode == "sql"

    def test_get_platform_capabilities_unknown_returns_none(self):
        caps = PlatformRegistry.get_platform_capabilities("nosuchplatform_xyz")
        assert caps is None

    def test_supports_mode_sql(self):
        assert PlatformRegistry.supports_mode("duckdb", "sql") is True

    def test_supports_mode_dataframe_false_for_duckdb(self):
        assert PlatformRegistry.supports_mode("duckdb", "dataframe") is False

    def test_supports_mode_unknown_platform_returns_false(self):
        assert PlatformRegistry.supports_mode("nosuchplatform_xyz", "sql") is False

    def test_supports_mode_unknown_mode_returns_false(self):
        assert PlatformRegistry.supports_mode("duckdb", "graphql") is False

    def test_get_default_mode_duckdb(self):
        assert PlatformRegistry.get_default_mode("duckdb") == "sql"

    def test_get_default_mode_unknown_returns_sql(self):
        assert PlatformRegistry.get_default_mode("nosuchplatform_xyz") == "sql"

    def test_get_dual_mode_platforms(self):
        dual = PlatformRegistry.get_dual_mode_platforms()
        assert isinstance(dual, list)
        # datafusion supports both SQL and DataFrame
        assert "datafusion" in dual


# ---------------------------------------------------------------------------
# Deployment capabilities
# ---------------------------------------------------------------------------


class TestDeploymentCapabilities:
    def test_duckdb_has_local_deployment(self):
        caps = PlatformRegistry.get_platform_capabilities("duckdb")
        assert "local" in caps.deployment_modes
        local_dep = caps.deployment_modes["local"]
        assert isinstance(local_dep, DeploymentCapability)
        assert local_dep.mode == "local"
        assert local_dep.requires_credentials is False
        assert local_dep.default_for_platform is True

    def test_motherduck_has_managed_deployment(self):
        caps = PlatformRegistry.get_platform_capabilities("motherduck")
        assert caps is not None
        assert "managed" in caps.deployment_modes
        managed = caps.deployment_modes["managed"]
        assert managed.mode == "managed"
        assert managed.requires_credentials is True
        assert managed.requires_network is True

    def test_get_deployment_capability_specific_mode(self):
        dep = PlatformRegistry.get_deployment_capability("duckdb", "local")
        assert dep is not None
        assert dep.mode == "local"

    def test_get_deployment_capability_nonexistent_mode_returns_none(self):
        dep = PlatformRegistry.get_deployment_capability("duckdb", "cloud")
        assert dep is None

    def test_get_deployment_capability_unknown_platform_returns_none(self):
        dep = PlatformRegistry.get_deployment_capability("nosuchplatform_xyz", "local")
        assert dep is None

    def test_get_default_deployment_duckdb(self):
        assert PlatformRegistry.get_default_deployment("duckdb") == "local"

    def test_get_default_deployment_motherduck(self):
        assert PlatformRegistry.get_default_deployment("motherduck") == "managed"

    def test_get_default_deployment_unknown_returns_none(self):
        assert PlatformRegistry.get_default_deployment("nosuchplatform_xyz") is None

    def test_get_available_deployment_modes_duckdb(self):
        modes = PlatformRegistry.get_available_deployment_modes("duckdb")
        assert "local" in modes

    def test_get_available_deployment_modes_clickhouse(self):
        modes = PlatformRegistry.get_available_deployment_modes("clickhouse")
        assert "local" in modes
        assert "server" in modes

    def test_get_available_deployment_modes_unknown_returns_empty(self):
        modes = PlatformRegistry.get_available_deployment_modes("nosuchplatform_xyz")
        assert modes == []

    def test_supports_deployment_mode_true(self):
        assert PlatformRegistry.supports_deployment_mode("duckdb", "local") is True

    def test_supports_deployment_mode_false(self):
        assert PlatformRegistry.supports_deployment_mode("duckdb", "managed") is False

    def test_supports_deployment_mode_unknown_platform_defaults_local(self):
        # Platforms with no deployment modes defined only support "local"
        assert PlatformRegistry.supports_deployment_mode("sqlite", "local") is True

    def test_requires_cloud_storage_for_deployment_motherduck(self):
        # MotherDuck managed deployment does not require cloud storage
        assert PlatformRegistry.requires_cloud_storage_for_deployment("motherduck") is False

    def test_requires_cloud_storage_for_deployment_unknown(self):
        assert PlatformRegistry.requires_cloud_storage_for_deployment("nosuchplatform_xyz") is False


# ---------------------------------------------------------------------------
# Platform family & inheritance
# ---------------------------------------------------------------------------


class TestPlatformFamilyAndInheritance:
    def test_get_platform_family_duckdb(self):
        assert PlatformRegistry.get_platform_family("duckdb") == "duckdb"

    def test_get_platform_family_motherduck(self):
        assert PlatformRegistry.get_platform_family("motherduck") == "duckdb"

    def test_get_platform_family_unknown_returns_none(self):
        assert PlatformRegistry.get_platform_family("nosuchplatform_xyz") is None

    def test_get_inherited_platform_motherduck(self):
        assert PlatformRegistry.get_inherited_platform("motherduck") == "duckdb"

    def test_get_inherited_platform_duckdb_returns_none(self):
        """DuckDB is a root platform, it does not inherit from anything."""
        assert PlatformRegistry.get_inherited_platform("duckdb") is None

    def test_get_inherited_platform_unknown_returns_none(self):
        assert PlatformRegistry.get_inherited_platform("nosuchplatform_xyz") is None


# ---------------------------------------------------------------------------
# Platform conflicts
# ---------------------------------------------------------------------------


class TestPlatformConflicts:
    def test_pg_duckdb_conflicts_with_pg_mooncake(self):
        conflicts = PlatformRegistry.get_platform_conflicts("pg-duckdb")
        assert "pg-mooncake" in conflicts

    def test_pg_mooncake_conflicts_with_pg_duckdb(self):
        conflicts = PlatformRegistry.get_platform_conflicts("pg-mooncake")
        assert "pg-duckdb" in conflicts

    def test_duckdb_has_no_conflicts(self):
        conflicts = PlatformRegistry.get_platform_conflicts("duckdb")
        assert conflicts == []

    def test_unknown_platform_has_no_conflicts(self):
        conflicts = PlatformRegistry.get_platform_conflicts("nosuchplatform_xyz")
        assert conflicts == []


# ---------------------------------------------------------------------------
# _extract_requirement_package (static helper)
# ---------------------------------------------------------------------------


class TestExtractRequirementPackage:
    def test_simple_package(self):
        assert PlatformRegistry._extract_requirement_package("duckdb") == "duckdb"

    def test_with_version_specifier(self):
        assert PlatformRegistry._extract_requirement_package("duckdb>=0.8.0") == "duckdb"

    def test_with_tilde_specifier(self):
        assert PlatformRegistry._extract_requirement_package("polars~=0.20.0") == "polars"

    def test_with_not_equal_specifier(self):
        assert PlatformRegistry._extract_requirement_package("pandas!=2.1.0") == "pandas"

    def test_builtin_description_format(self):
        result = PlatformRegistry._extract_requirement_package("sqlite3 (built-in)")
        assert result == "sqlite3"

    def test_empty_string_returns_none(self):
        assert PlatformRegistry._extract_requirement_package("") is None

    def test_none_input(self):
        # Not a documented scenario but exercises the guard clause
        assert PlatformRegistry._extract_requirement_package(None) is None

    def test_whitespace_only_returns_none(self):
        assert PlatformRegistry._extract_requirement_package("   ") is None
