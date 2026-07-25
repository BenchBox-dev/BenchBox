"""Tests for DataFrame/SQL storage location parity.

Asserts that DataFrame and SQL default data directories share the same
``benchmark_runs/`` root, eliminating the historical asymmetry where SQL data
lived project-locally but DataFrame cache lived under ``~/.benchbox/``.

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from benchbox.core.dataframe.data_loader import DEFAULT_CACHE_DIR, DataCache
from benchbox.utils.path_utils import (
    get_benchmark_runs_dataframe_path,
    get_benchmark_runs_datagen_path,
    resolve_benchmark_runs_dir,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestStorageLocationParity:
    """Verify DataFrame and SQL defaults share benchmark_runs/ root."""

    def test_default_cache_dir_suffix_is_benchmark_runs_dataframe_data(self):
        """DEFAULT_CACHE_DIR should represent the benchmark_runs/datagen suffix."""
        assert Path("benchmark_runs") / "datagen" == DEFAULT_CACHE_DIR

    def test_dataframe_and_sql_share_benchmark_runs_root(self):
        """DataFrame and SQL datagen paths share the same benchmark_runs/ parent."""
        df_path = get_benchmark_runs_dataframe_path()
        sql_path = get_benchmark_runs_datagen_path("tpch", 1.0)

        # Both should be under benchmark_runs/
        assert df_path.parent.name == "benchmark_runs"
        assert sql_path.parent.parent.name == "benchmark_runs"

        # Both should share the same benchmark_runs/ root
        df_root = df_path.parent
        sql_root = sql_path.parent.parent
        assert df_root == sql_root

    def test_datacache_default_resolves_to_benchmark_runs(self):
        """DataCache with no arguments should use benchmark_runs/datagen/."""
        with patch.dict("os.environ", {}, clear=True):
            # Remove BENCHBOX_CACHE_DIR if set
            import os

            env = os.environ.copy()
            env.pop("BENCHBOX_CACHE_DIR", None)
            with patch.dict("os.environ", env, clear=True):
                cache = DataCache()
                assert cache.cache_dir == resolve_benchmark_runs_dir() / "datagen"

    def test_benchbox_cache_dir_env_overrides_default(self):
        """BENCHBOX_CACHE_DIR environment variable should override the default."""
        with patch.dict("os.environ", {"BENCHBOX_CACHE_DIR": "/custom/cache"}):
            cache = DataCache()
            assert cache.cache_dir == Path("/custom/cache")

    def test_explicit_cache_dir_takes_precedence(self):
        """Explicit cache_dir parameter should take precedence over everything."""
        explicit = Path("/explicit/path")
        with patch.dict("os.environ", {"BENCHBOX_CACHE_DIR": "/env/path"}):
            cache = DataCache(cache_dir=explicit)
            assert cache.cache_dir == explicit

    def test_default_not_in_home_directory(self):
        """Default DataFrame cache should NOT be under home directory."""
        cache = DataCache()
        assert not str(cache.cache_dir).startswith(str(Path.home() / ".benchbox"))

    def test_path_helper_default(self):
        """get_benchmark_runs_dataframe_path() returns benchmark_runs/datagen/."""
        path = get_benchmark_runs_dataframe_path()
        assert path == resolve_benchmark_runs_dir() / "datagen"

    def test_path_helper_override(self):
        """get_benchmark_runs_dataframe_path() respects base_dir override."""
        path = get_benchmark_runs_dataframe_path("/custom/dir")
        assert path == Path("/custom/dir")

    def test_datacache_get_cache_path_is_child_of_datagen_path(self):
        """DataCache.get_cache_path() should return a path nested inside get_benchmark_runs_datagen_path()."""
        from benchbox.core.dataframe.capabilities import DataFormat

        cache = DataCache()
        for benchmark, sf in [("tpch", 0.01), ("tpch", 1.0), ("tpcds", 10.0)]:
            cache_path = cache.get_cache_path(benchmark, sf, DataFormat.PARQUET)
            datagen_path = get_benchmark_runs_datagen_path(benchmark, sf)
            # cache_path must be strictly inside datagen_path
            assert cache_path.is_relative_to(datagen_path), f"Expected {cache_path} to be under {datagen_path}"


class TestGlobalCacheOption:
    """Verify --global-cache routes DataFrame cache to ~/.benchbox/datagen/."""

    def test_global_cache_path_is_under_home(self):
        """~/.benchbox/datagen/ is under the user home directory."""
        expected = Path.home() / ".benchbox" / "datagen"
        assert str(expected).startswith(str(Path.home()))

    def test_global_cache_path_uses_datagen_subdir(self):
        """Global cache uses the unified datagen/ subdirectory name."""
        expected = Path.home() / ".benchbox" / "datagen"
        assert expected.name == "datagen"

    def test_datacache_with_global_dir_resolves_correctly(self):
        """DataCache constructed with ~/.benchbox/datagen/ uses that path."""
        global_dir = Path.home() / ".benchbox" / "datagen"
        cache = DataCache(cache_dir=global_dir)
        assert cache.cache_dir == global_dir

    def test_global_cache_differs_from_project_local(self):
        """Global cache path must differ from the default project-local path."""
        global_dir = Path.home() / ".benchbox" / "datagen"
        project_local = get_benchmark_runs_dataframe_path()
        assert global_dir != project_local
