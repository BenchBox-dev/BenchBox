"""Unit tests for the DuckLake platform adapter.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.core.config_inheritance import resolve_dialect_for_query_translation
from benchbox.core.platform_registry import PlatformRegistry
from benchbox.platforms.ducklake import (
    DuckLakeAdapter,
    _duckdb_version_supports_ducklake,
    _parse_duckdb_major_minor,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestDuckLakeVersionGuard:
    """Test the DuckDB >= 1.3 runtime version parser/guard used by DuckLake."""

    @pytest.mark.parametrize(
        "version,expected",
        [
            ("1.3.2", (1, 3)),
            ("1.4.0", (1, 4)),
            ("1.2.0", (1, 2)),
            ("v1.3.2", (1, 3)),
            ("1.3", (1, 3)),
            ("1.4.0-dev123", (1, 4)),
        ],
    )
    def test_parse_major_minor(self, version, expected):
        assert _parse_duckdb_major_minor(version) == expected

    @pytest.mark.parametrize("bad_version", [None, "", "not-a-version", "v"])
    def test_parse_major_minor_rejects_unparseable(self, bad_version):
        assert _parse_duckdb_major_minor(bad_version) is None

    @pytest.mark.parametrize(
        "version,supported",
        [
            ("1.2.0", False),
            ("1.2.9", False),
            ("1.3.0", True),
            ("1.3.2", True),
            ("1.4.0", True),
            ("v1.3.2", True),
            ("0.10.0", False),
            (None, False),
            ("garbage", False),
        ],
    )
    def test_meets_minimum_version(self, version, supported):
        assert _duckdb_version_supports_ducklake(version) is supported


class TestDuckLakeFromConfig:
    """Test DuckLakeAdapter.from_config() path resolution."""

    def test_resolves_default_paths_under_benchmark_runs(self, tmp_path):
        config = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "output_dir": str(tmp_path),
        }
        adapter = DuckLakeAdapter.from_config(config)

        assert adapter.metadata_path.suffix == ".ducklake"
        assert str(adapter.metadata_path).startswith(str(tmp_path))
        assert adapter.data_path.name != ""
        # Data path is a sibling "ducklake_data" dir alongside the metadata db.
        assert "ducklake_data" in adapter.data_path.parts
        # from_config resolves paths only; directory creation is lazy (deferred
        # to create_connection), so nothing is written to disk here.
        assert not adapter.metadata_path.parent.exists()
        assert not adapter.data_path.exists()

    def test_honors_explicit_argparse_style_keys(self, tmp_path):
        metadata_path = tmp_path / "custom" / "catalog.ducklake"
        data_path = tmp_path / "custom" / "data"
        config = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "ducklake_metadata_path": str(metadata_path),
            "ducklake_data_path": str(data_path),
        }
        adapter = DuckLakeAdapter.from_config(config)

        assert adapter.metadata_path == metadata_path
        assert adapter.data_path == data_path

    def test_honors_explicit_normalized_keys(self, tmp_path):
        metadata_path = tmp_path / "normalized" / "catalog.ducklake"
        data_path = tmp_path / "normalized" / "data"
        config = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "metadata_path": str(metadata_path),
            "data_path": str(data_path),
        }
        adapter = DuckLakeAdapter.from_config(config)

        assert adapter.metadata_path == metadata_path
        assert adapter.data_path == data_path

    def test_argparse_style_key_takes_precedence_over_normalized(self, tmp_path):
        preferred = tmp_path / "preferred.ducklake"
        ignored = tmp_path / "ignored.ducklake"
        config = {
            "benchmark": "tpch",
            "scale_factor": 0.01,
            "ducklake_metadata_path": str(preferred),
            "metadata_path": str(ignored),
            "ducklake_data_path": str(tmp_path / "data"),
        }
        adapter = DuckLakeAdapter.from_config(config)

        assert adapter.metadata_path == preferred


class TestDuckLakeAdapterBasics:
    """Test basic adapter properties and construction."""

    def test_platform_name(self, tmp_path):
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path=str(tmp_path / "data"),
        )
        assert adapter.platform_name == "DuckLake"

    def test_target_dialect_is_duckdb(self, tmp_path):
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path=str(tmp_path / "data"),
        )
        assert adapter.get_target_dialect() == "duckdb"
        assert resolve_dialect_for_query_translation("ducklake") == "duckdb"

    def test_init_does_not_create_directories(self, tmp_path):
        # Directory creation is lazy (deferred to create_connection): merely
        # constructing an adapter must not touch the filesystem.
        metadata_path = tmp_path / "nested" / "catalog.ducklake"
        data_path = tmp_path / "nested" / "data"
        adapter = DuckLakeAdapter(metadata_path=str(metadata_path), data_path=str(data_path))

        assert adapter.metadata_path == metadata_path
        assert adapter.data_path == data_path
        # No eager mkdir: neither the parent nor the data dir should exist yet.
        assert not metadata_path.parent.exists()
        assert not data_path.exists()

    def test_constructs_with_fallback_paths_without_touching_disk(self, tmp_path, monkeypatch):
        # Direct construction without metadata_path/data_path should not raise
        # and must not write real dirs. Redirect the fallback root into tmp_path
        # and assert nothing is created on disk by construction alone.
        import benchbox.utils.path_utils as path_utils

        monkeypatch.setattr(
            path_utils,
            "get_benchmark_runs_databases_path",
            lambda *args, **kwargs: tmp_path / "fallback",
        )

        adapter = DuckLakeAdapter()
        assert adapter.metadata_path.suffix == ".ducklake"
        assert str(adapter.metadata_path).startswith(str(tmp_path))
        # Lazy: construction created nothing on disk.
        assert not (tmp_path / "fallback").exists()

    def test_create_connection_rejects_old_duckdb_version(self, tmp_path, monkeypatch):
        # No live INSTALL/ATTACH: the guard is patched to reject before any
        # network call, so this stays in the hermetic fast lane.
        metadata_path = tmp_path / "catalog.ducklake"
        data_path = tmp_path / "data"
        adapter = DuckLakeAdapter(metadata_path=str(metadata_path), data_path=str(data_path))

        # DuckDBAdapter.create_connection() re-detects the live version from
        # the real connection (SELECT version()) and overwrites
        # driver_version_actual, so pre-seeding that attribute wouldn't stick.
        # Patch the version-support predicate itself to exercise the
        # create_connection wiring (guard runs, raises before INSTALL/ATTACH)
        # without needing to actually downgrade the installed duckdb package.
        import benchbox.platforms.ducklake as ducklake_module

        monkeypatch.setattr(ducklake_module, "_duckdb_version_supports_ducklake", lambda version: False)

        with pytest.raises(RuntimeError, match=r"DuckDB >= 1\.3"):
            adapter.create_connection()


class TestDuckLakeRegistration:
    """Test DuckLake platform is properly registered."""

    def test_platform_registered_in_registry(self):
        caps = PlatformRegistry.get_platform_capabilities("ducklake")
        assert caps is not None
        assert caps.supports_sql is True
        assert caps.supports_dataframe is False

    def test_inherits_from_duckdb(self):
        caps = PlatformRegistry.get_platform_capabilities("ducklake")
        assert caps.inherits_from == "duckdb"
        assert caps.platform_family == "duckdb"

    def test_platform_appears_in_available_platforms(self):
        available = PlatformRegistry.get_available_platforms()
        assert "ducklake" in available

    def test_support_status_is_experimental(self):
        assert PlatformRegistry.get_platform_support_status("ducklake") == "experimental"

    def test_adapter_class_resolves(self):
        adapter_class = PlatformRegistry.get_adapter_class("ducklake")
        assert adapter_class is DuckLakeAdapter

    def test_appears_in_list_available_platforms(self):
        from benchbox.platforms import list_available_platforms

        platforms = list_available_platforms()
        assert "ducklake" in platforms
        assert platforms["ducklake"] is True

    def test_lazy_export_resolves_adapter(self):
        import benchbox.platforms as platforms_module

        assert platforms_module.DuckLakeAdapter is DuckLakeAdapter
