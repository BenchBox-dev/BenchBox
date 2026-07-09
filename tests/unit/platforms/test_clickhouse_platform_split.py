"""Tests for first-class clickhouse-local, clickhouse-server platform split.

Covers:
- Migration contract constants in deployment_mode module
- ClickHouseLocalAdapter and ClickHouseServerAdapter thin wrappers
- Adapter factory legacy selector routing with deprecation warnings
- Platform registry metadata for new platforms
- is_clickhouse_platform() helper

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import warnings
from unittest.mock import patch

import pytest

from benchbox.platforms.clickhouse.deployment_mode import (
    CLICKHOUSE_CANONICAL_PLATFORM_NAMES,
    CLICKHOUSE_DEFAULT_CANONICAL_PLATFORM,
    CLICKHOUSE_LEGACY_SELECTOR_MAP,
    clickhouse_legacy_selector_warning,
    is_clickhouse_platform,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# ---------------------------------------------------------------------------
# Migration contract constants
# ---------------------------------------------------------------------------


class TestMigrationContract:
    def test_canonical_platform_names_are_complete(self) -> None:
        assert "clickhouse-local" in CLICKHOUSE_CANONICAL_PLATFORM_NAMES
        assert "clickhouse-server" in CLICKHOUSE_CANONICAL_PLATFORM_NAMES
        assert "clickhouse-cloud" in CLICKHOUSE_CANONICAL_PLATFORM_NAMES

    def test_bare_clickhouse_is_not_canonical(self) -> None:
        assert "clickhouse" not in CLICKHOUSE_CANONICAL_PLATFORM_NAMES

    def test_legacy_selector_map_covers_colon_syntax(self) -> None:
        assert CLICKHOUSE_LEGACY_SELECTOR_MAP["clickhouse:local"] == "clickhouse-local"
        assert CLICKHOUSE_LEGACY_SELECTOR_MAP["clickhouse:server"] == "clickhouse-server"
        assert CLICKHOUSE_LEGACY_SELECTOR_MAP["clickhouse:cloud"] == "clickhouse-cloud"

    def test_default_canonical_platform_is_local(self) -> None:
        assert CLICKHOUSE_DEFAULT_CANONICAL_PLATFORM == "clickhouse-local"

    def test_legacy_warning_message_mentions_target(self) -> None:
        msg = clickhouse_legacy_selector_warning("clickhouse", "clickhouse-local")
        assert "clickhouse-local" in msg
        assert "clickhouse" in msg
        assert "deprecated" in msg.lower()


# ---------------------------------------------------------------------------
# is_clickhouse_platform helper
# ---------------------------------------------------------------------------


class TestIsClickhousePlatform:
    @pytest.mark.parametrize(
        "platform",
        [
            "clickhouse",
            "clickhouse-local",
            "clickhouse-server",
            "clickhouse-cloud",
            "chdb",
            "CLICKHOUSE",
            "Clickhouse-Local",
        ],
    )
    def test_returns_true_for_all_clickhouse_family_names(self, platform: str) -> None:
        assert is_clickhouse_platform(platform) is True

    @pytest.mark.parametrize(
        "platform",
        ["duckdb", "postgresql", "snowflake", "databricks", "polars"],
    )
    def test_returns_false_for_non_clickhouse_platforms(self, platform: str) -> None:
        assert is_clickhouse_platform(platform) is False


# ---------------------------------------------------------------------------
# ClickHouseLocalAdapter thin wrapper
# ---------------------------------------------------------------------------


class TestClickHouseLocalAdapter:
    def test_import_succeeds(self) -> None:
        from benchbox.platforms.clickhouse_local import ClickHouseLocalAdapter

        assert ClickHouseLocalAdapter is not None

    def test_forces_local_deployment_mode(self) -> None:
        from benchbox.platforms.clickhouse_local import ClickHouseLocalAdapter

        with (
            patch("benchbox.platforms.clickhouse.adapter.check_platform_dependencies", return_value=(True, [])),
            patch("benchbox.platforms.clickhouse.setup.ClickHouseLocalClient"),
            patch("importlib.util.find_spec", return_value=object()),
        ):
            adapter = ClickHouseLocalAdapter()
            assert adapter.deployment_mode == "local"

    def test_platform_name_is_clickhouse_local(self) -> None:
        from benchbox.platforms.clickhouse_local import ClickHouseLocalAdapter

        with (
            patch("benchbox.platforms.clickhouse.adapter.check_platform_dependencies", return_value=(True, [])),
            patch("benchbox.platforms.clickhouse.setup.ClickHouseLocalClient"),
            patch("importlib.util.find_spec", return_value=object()),
        ):
            adapter = ClickHouseLocalAdapter()
            assert adapter.platform_name == "ClickHouse Local"

    def test_from_config_forces_local_mode(self) -> None:
        from benchbox.platforms.clickhouse_local import ClickHouseLocalAdapter

        with (
            patch("benchbox.platforms.clickhouse.adapter.check_platform_dependencies", return_value=(True, [])),
            patch("benchbox.platforms.clickhouse.setup.ClickHouseLocalClient"),
            patch("importlib.util.find_spec", return_value=object()),
        ):
            # Even if config says server, local adapter forces local
            adapter = ClickHouseLocalAdapter.from_config({"deployment_mode": "server"})
            assert adapter.deployment_mode == "local"


# ---------------------------------------------------------------------------
# ClickHouseServerAdapter thin wrapper
# ---------------------------------------------------------------------------


class TestClickHouseServerAdapter:
    def test_import_succeeds(self) -> None:
        from benchbox.platforms.clickhouse_server import ClickHouseServerAdapter

        assert ClickHouseServerAdapter is not None

    def test_forces_server_deployment_mode(self) -> None:
        from benchbox.platforms.clickhouse_server import ClickHouseServerAdapter

        with (
            patch("benchbox.platforms.clickhouse.adapter.check_platform_dependencies", return_value=(True, [])),
            patch("benchbox.platforms.clickhouse.setup.ClickHouseClient"),
        ):
            adapter = ClickHouseServerAdapter()
            assert adapter.deployment_mode == "server"

    def test_platform_name_is_clickhouse_server(self) -> None:
        from benchbox.platforms.clickhouse_server import ClickHouseServerAdapter

        with (
            patch("benchbox.platforms.clickhouse.adapter.check_platform_dependencies", return_value=(True, [])),
            patch("benchbox.platforms.clickhouse.setup.ClickHouseClient"),
        ):
            adapter = ClickHouseServerAdapter()
            assert adapter.platform_name == "ClickHouse Server"

    def test_from_config_forces_server_mode(self) -> None:
        from benchbox.platforms.clickhouse_server import ClickHouseServerAdapter

        with (
            patch("benchbox.platforms.clickhouse.adapter.check_platform_dependencies", return_value=(True, [])),
            patch("benchbox.platforms.clickhouse.setup.ClickHouseClient"),
        ):
            # Even if config says local, server adapter forces server
            adapter = ClickHouseServerAdapter.from_config({"deployment_mode": "local"})
            assert adapter.deployment_mode == "server"

    def test_from_config_preserves_database_config_options(self) -> None:
        from benchbox.platforms.clickhouse_server import ClickHouseServerAdapter

        with (
            patch("benchbox.platforms.clickhouse.adapter.check_platform_dependencies", return_value=(True, [])),
            patch("benchbox.platforms.clickhouse.setup.ClickHouseClient"),
        ):
            adapter = ClickHouseServerAdapter.from_config(
                {
                    "options": {
                        "host": "localhost",
                        "port": 19000,
                        "username": "default",
                        "password": "benchbox",
                    }
                }
            )

        assert adapter.host == "localhost"
        assert adapter.port == 19000
        assert adapter.username == "default"
        assert adapter.password == "benchbox"


# ---------------------------------------------------------------------------
# Adapter factory: legacy selector routing and deprecation warnings
# ---------------------------------------------------------------------------


class TestAdapterFactoryMigration:
    def test_clickhouse_local_resolves_without_warning(self) -> None:
        from benchbox.platforms.adapter_factory import _resolve_clickhouse_legacy

        platform, warning = _resolve_clickhouse_legacy("clickhouse-local")
        assert platform == "clickhouse-local"
        assert warning is None

    def test_clickhouse_server_resolves_without_warning(self) -> None:
        from benchbox.platforms.adapter_factory import _resolve_clickhouse_legacy

        platform, warning = _resolve_clickhouse_legacy("clickhouse-server")
        assert platform == "clickhouse-server"
        assert warning is None

    def test_clickhouse_cloud_resolves_without_warning(self) -> None:
        from benchbox.platforms.adapter_factory import _resolve_clickhouse_legacy

        platform, warning = _resolve_clickhouse_legacy("clickhouse-cloud")
        assert platform == "clickhouse-cloud"
        assert warning is None

    def test_bare_clickhouse_emits_deprecation_and_maps_to_local(self) -> None:
        from benchbox.platforms.adapter_factory import _resolve_clickhouse_legacy

        platform, warning = _resolve_clickhouse_legacy("clickhouse")
        assert platform == "clickhouse-local"
        assert warning is not None
        assert "deprecated" in warning.lower()

    def test_bare_clickhouse_with_server_mode_maps_to_server(self) -> None:
        from benchbox.platforms.adapter_factory import _resolve_clickhouse_legacy

        platform, warning = _resolve_clickhouse_legacy("clickhouse", config={"deployment_mode": "server"})
        assert platform == "clickhouse-server"
        assert warning is not None

    def test_bare_clickhouse_with_explicit_deployment_server_maps_to_server(self) -> None:
        from benchbox.platforms.adapter_factory import _resolve_clickhouse_legacy

        platform, warning = _resolve_clickhouse_legacy("clickhouse", deployment="server")
        assert platform == "clickhouse-server"

    def test_clickhouse_colon_local_maps_to_clickhouse_local(self) -> None:
        from benchbox.platforms.adapter_factory import _resolve_clickhouse_legacy

        platform, warning = _resolve_clickhouse_legacy("clickhouse:local")
        assert platform == "clickhouse-local"
        assert warning is not None
        assert "clickhouse:local" in warning

    def test_clickhouse_colon_server_maps_to_clickhouse_server(self) -> None:
        from benchbox.platforms.adapter_factory import _resolve_clickhouse_legacy

        platform, warning = _resolve_clickhouse_legacy("clickhouse:server")
        assert platform == "clickhouse-server"
        assert warning is not None
        assert "clickhouse:server" in warning

    def test_clickhouse_colon_cloud_maps_to_clickhouse_cloud(self) -> None:
        from benchbox.platforms.adapter_factory import _resolve_clickhouse_legacy

        platform, warning = _resolve_clickhouse_legacy("clickhouse:cloud")
        assert platform == "clickhouse-cloud"
        assert warning is not None

    def test_non_clickhouse_platforms_pass_through_unchanged(self) -> None:
        from benchbox.platforms.adapter_factory import _resolve_clickhouse_legacy

        for name in ("duckdb", "snowflake", "polars-df", "databricks:serverless"):
            platform, warning = _resolve_clickhouse_legacy(name)
            assert platform == name
            assert warning is None

    def test_get_adapter_emits_deprecation_for_bare_clickhouse(self) -> None:
        """Integration: get_adapter("clickhouse") emits DeprecationWarning."""
        from benchbox.platforms.adapter_factory import get_adapter

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                get_adapter("clickhouse")
            except Exception:
                pass  # May fail if chDB not installed; we only care about the warning
        deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert any("clickhouse" in str(w.message).lower() for w in deprecation_warnings), (
            f"Expected a DeprecationWarning about 'clickhouse' but got: {[str(w.message) for w in deprecation_warnings]}"
        )


# ---------------------------------------------------------------------------
# Platform registry: new platforms are registered
# ---------------------------------------------------------------------------


class TestPlatformRegistryNewPlatforms:
    def setup_method(self) -> None:
        from benchbox.core.platform_registry import PlatformRegistry

        PlatformRegistry.clear_cache()

    def test_clickhouse_local_has_metadata(self) -> None:
        from benchbox.core.platform_registry import PlatformRegistry

        metadata = PlatformRegistry.get_all_platform_metadata()
        assert "clickhouse-local" in metadata, "clickhouse-local must be in platform metadata"
        spec = metadata["clickhouse-local"]
        assert "chdb" in spec["installation_command"] or "clickhouse-local" in spec["installation_command"]

    def test_clickhouse_server_has_metadata(self) -> None:
        from benchbox.core.platform_registry import PlatformRegistry

        metadata = PlatformRegistry.get_all_platform_metadata()
        assert "clickhouse-server" in metadata, "clickhouse-server must be in platform metadata"
        spec = metadata["clickhouse-server"]
        assert "clickhouse-driver" in str(spec["requirements"])

    def test_clickhouse_local_capabilities_have_sql_support(self) -> None:
        from benchbox.core.platform_registry import PlatformRegistry

        caps = PlatformRegistry.get_platform_capabilities("clickhouse-local")
        assert caps is not None
        assert caps.supports_sql is True
        assert caps.platform_family == "clickhouse"

    def test_clickhouse_server_capabilities_have_sql_support(self) -> None:
        from benchbox.core.platform_registry import PlatformRegistry

        caps = PlatformRegistry.get_platform_capabilities("clickhouse-server")
        assert caps is not None
        assert caps.supports_sql is True
        assert caps.platform_family == "clickhouse"

    def test_clickhouse_local_adapter_registered(self) -> None:
        from benchbox.core.platform_registry import PlatformRegistry

        PlatformRegistry._ensure_registered()
        available = PlatformRegistry.get_available_platforms()
        assert "clickhouse-local" in available, "clickhouse-local must be in available platforms"

    def test_clickhouse_server_adapter_registered(self) -> None:
        from benchbox.core.platform_registry import PlatformRegistry

        PlatformRegistry._ensure_registered()
        available = PlatformRegistry.get_available_platforms()
        assert "clickhouse-server" in available, "clickhouse-server must be in available platforms"
