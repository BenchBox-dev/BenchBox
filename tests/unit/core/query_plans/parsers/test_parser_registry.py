"""
Tests for parser registry functionality.

Tests parser registration, version-based selection, and global registry.
"""

import pytest

from benchbox.core.query_plans.parsers.base import QueryPlanParser
from benchbox.core.query_plans.parsers.registry import (
    ParserRegistry,
    get_parser_for_platform,
    get_parser_registry,
    reset_global_registry,
)
from benchbox.core.results.query_plan_models import QueryPlanDAG

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# Mock parser classes for testing
class MockParserV1(QueryPlanParser):
    """Mock parser version 1."""

    def __init__(self):
        super().__init__("mock")
        self.version = "v1"

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        raise NotImplementedError


class MockParserV2(QueryPlanParser):
    """Mock parser version 2."""

    def __init__(self):
        super().__init__("mock")
        self.version = "v2"

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        raise NotImplementedError


class MockParserV3(QueryPlanParser):
    """Mock parser version 3."""

    def __init__(self):
        super().__init__("mock")
        self.version = "v3"

    def _parse_impl(self, query_id: str, explain_output: str) -> QueryPlanDAG:
        raise NotImplementedError


class TestParserRegistry:
    """Test ParserRegistry class."""

    def test_empty_registry(self) -> None:
        """Test empty registry returns None."""
        registry = ParserRegistry()
        assert registry.get_parser("nonexistent", "1.0.0") is None

    def test_register_single_parser(self) -> None:
        """Test registering and retrieving single parser."""
        registry = ParserRegistry()
        registry.register("testdb", "1.0.0", MockParserV1)

        parser = registry.get_parser("testdb", "1.0.0")
        assert parser is not None
        assert parser.version == "v1"

    def test_register_multiple_versions(self) -> None:
        """Test registering multiple versions for same platform."""
        registry = ParserRegistry()
        registry.register("testdb", "1.0.0", MockParserV1)
        registry.register("testdb", "2.0.0", MockParserV2)
        registry.register("testdb", "3.0.0", MockParserV3)

        # Version 1.5 should use V1 parser
        parser = registry.get_parser("testdb", "1.5.0")
        assert parser is not None
        assert parser.version == "v1"

        # Version 2.5 should use V2 parser
        parser = registry.get_parser("testdb", "2.5.0")
        assert parser is not None
        assert parser.version == "v2"

        # Version 3.0+ should use V3 parser
        parser = registry.get_parser("testdb", "3.0.0")
        assert parser is not None
        assert parser.version == "v3"

        parser = registry.get_parser("testdb", "4.0.0")
        assert parser is not None
        assert parser.version == "v3"

    def test_version_too_old(self) -> None:
        """Test version older than all registered parsers."""
        registry = ParserRegistry()
        registry.register("testdb", "2.0.0", MockParserV2)

        # Version 1.0 is too old
        parser = registry.get_parser("testdb", "1.0.0")
        assert parser is None

    def test_case_insensitive_platform(self) -> None:
        """Test platform names are case insensitive."""
        registry = ParserRegistry()
        registry.register("TestDB", "1.0.0", MockParserV1)

        parser = registry.get_parser("testdb", "1.0.0")
        assert parser is not None

        parser = registry.get_parser("TESTDB", "1.0.0")
        assert parser is not None

    def test_get_parser_no_version(self) -> None:
        """Test getting parser without specifying version."""
        registry = ParserRegistry()
        registry.register("testdb", "1.0.0", MockParserV1)
        registry.register("testdb", "2.0.0", MockParserV2)

        # Should return parser with highest version requirement
        parser = registry.get_parser("testdb")
        assert parser is not None
        assert parser.version == "v2"

    def test_invalid_version_string(self) -> None:
        """Test handling of invalid version strings."""
        registry = ParserRegistry()
        registry.register("testdb", "1.0.0", MockParserV1)
        registry.register("testdb", "2.0.0", MockParserV2)

        # Invalid version should fall back to latest parser
        parser = registry.get_parser("testdb", "invalid-version")
        assert parser is not None
        assert parser.version == "v2"

    def test_get_all_platforms(self) -> None:
        """Test getting list of all platforms."""
        registry = ParserRegistry()
        registry.register("platforma", "1.0.0", MockParserV1)
        registry.register("platformb", "1.0.0", MockParserV2)

        platforms = registry.get_all_platforms()
        assert set(platforms) == {"platforma", "platformb"}

    def test_get_parser_versions(self) -> None:
        """Test getting registered versions for a platform."""
        registry = ParserRegistry()
        registry.register("testdb", "1.0.0", MockParserV1)
        registry.register("testdb", "2.0.0", MockParserV2)

        versions = registry.get_parser_versions("testdb")
        assert len(versions) == 2
        assert ("1.0.0", "MockParserV1") in versions
        assert ("2.0.0", "MockParserV2") in versions

    def test_get_parser_versions_unknown_platform(self) -> None:
        """Test getting versions for unknown platform."""
        registry = ParserRegistry()
        versions = registry.get_parser_versions("unknown")
        assert versions == []

    def test_clear_registry(self) -> None:
        """Test clearing the registry."""
        registry = ParserRegistry()
        registry.register("testdb", "1.0.0", MockParserV1)

        assert registry.get_parser("testdb", "1.0.0") is not None

        registry.clear()

        assert registry.get_parser("testdb", "1.0.0") is None
        assert registry.get_all_platforms() == []

    def test_semver_comparison(self) -> None:
        """Test proper semantic version comparison."""
        registry = ParserRegistry()
        registry.register("testdb", "0.9.0", MockParserV1)
        registry.register("testdb", "0.10.0", MockParserV2)
        registry.register("testdb", "1.0.0", MockParserV3)

        # 0.10.0 > 0.9.0 (not lexicographic comparison)
        parser = registry.get_parser("testdb", "0.9.5")
        assert parser is not None
        assert parser.version == "v1"

        parser = registry.get_parser("testdb", "0.10.0")
        assert parser is not None
        assert parser.version == "v2"

        parser = registry.get_parser("testdb", "0.11.0")
        assert parser is not None
        assert parser.version == "v2"


class TestGlobalRegistry:
    """Test global registry functionality."""

    def setup_method(self) -> None:
        """Reset global registry before each test."""
        reset_global_registry()

    def teardown_method(self) -> None:
        """Reset global registry after each test."""
        reset_global_registry()

    def test_get_parser_registry(self) -> None:
        """Test getting the global registry."""
        registry = get_parser_registry()
        assert isinstance(registry, ParserRegistry)

    def test_registry_singleton(self) -> None:
        """Test registry is singleton."""
        registry1 = get_parser_registry()
        registry2 = get_parser_registry()
        assert registry1 is registry2

    def test_default_duckdb_parser(self) -> None:
        """Test DuckDB parser is registered by default."""
        parser = get_parser_for_platform("duckdb", "1.0.0")
        assert parser is not None
        assert parser.platform_name == "duckdb"

    def test_default_postgresql_parser(self) -> None:
        """Test PostgreSQL parser is registered by default."""
        parser = get_parser_for_platform("postgresql", "14.0")
        assert parser is not None
        assert parser.platform_name == "postgresql"

    def test_default_postgres_alias(self) -> None:
        """Test 'postgres' works as alias for postgresql."""
        parser = get_parser_for_platform("postgres", "14.0")
        assert parser is not None
        assert parser.platform_name == "postgresql"

    def test_default_redshift_parser(self) -> None:
        """Test Redshift parser is registered by default."""
        parser = get_parser_for_platform("redshift", "1.0.0")
        assert parser is not None
        assert parser.platform_name == "redshift"

    def test_default_datafusion_parser(self) -> None:
        """Test DataFusion parser is registered by default."""
        parser = get_parser_for_platform("datafusion", "35.0.0")
        assert parser is not None
        assert parser.platform_name == "datafusion"

    def test_default_sqlite_parser(self) -> None:
        """Test SQLite parser is registered by default."""
        parser = get_parser_for_platform("sqlite", "3.40.0")
        assert parser is not None
        assert parser.platform_name == "sqlite"

    def test_clickhouse_deployment_mode_keys_resolve(self) -> None:
        """ClickHouse parser resolves for the concrete platform identifiers.

        The platform identifiers are clickhouse-local / clickhouse-server /
        clickhouse-cloud, not the legacy "clickhouse" key, so a direct
        get_parser_for_platform() lookup must work for every deployment mode.
        """
        for platform in (
            "clickhouse",
            "clickhouse-local",
            "clickhouse-server",
            "clickhouse-cloud",
        ):
            parser = get_parser_for_platform(platform)
            assert parser is not None, f"no parser resolved for {platform}"
            assert parser.platform_name == "clickhouse"

    def test_unknown_platform(self) -> None:
        """Test unknown platform returns None."""
        parser = get_parser_for_platform("unknowndb", "1.0.0")
        assert parser is None

    def test_reset_global_registry(self) -> None:
        """Test resetting the global registry."""
        registry1 = get_parser_registry()
        reset_global_registry()
        registry2 = get_parser_registry()
        # Should be a new instance
        assert registry1 is not registry2


class TestParserRegistryVersionSelection:
    """Test version selection edge cases."""

    def test_exact_version_match(self) -> None:
        """Test exact version match."""
        registry = ParserRegistry()
        registry.register("testdb", "1.0.0", MockParserV1)

        parser = registry.get_parser("testdb", "1.0.0")
        assert parser is not None
        assert parser.version == "v1"

    def test_version_with_prerelease(self) -> None:
        """Test handling of pre-release versions."""
        registry = ParserRegistry()
        registry.register("testdb", "1.0.0", MockParserV1)
        registry.register("testdb", "2.0.0", MockParserV2)

        # Pre-release version 2.0.0-beta should use V1 parser
        # (pre-releases are < the release version)
        parser = registry.get_parser("testdb", "2.0.0-beta")
        assert parser is not None
        # packaging considers 2.0.0-beta < 2.0.0, so V1 is selected
        assert parser.version == "v1"

    def test_version_with_build_metadata(self) -> None:
        """Test handling of version with build metadata."""
        registry = ParserRegistry()
        registry.register("testdb", "1.0.0", MockParserV1)

        # Build metadata is ignored in version comparison
        parser = registry.get_parser("testdb", "1.0.0+build123")
        assert parser is not None
        assert parser.version == "v1"

    def test_short_version_string(self) -> None:
        """Test handling of short version strings like '1' or '1.0'."""
        registry = ParserRegistry()
        registry.register("testdb", "1.0.0", MockParserV1)
        registry.register("testdb", "2.0.0", MockParserV2)

        # "1" should be interpreted as "1.0.0"
        parser = registry.get_parser("testdb", "1")
        assert parser is not None
        assert parser.version == "v1"

        # "2" should be interpreted as "2.0.0"
        parser = registry.get_parser("testdb", "2")
        assert parser is not None
        assert parser.version == "v2"
