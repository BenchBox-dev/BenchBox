"""Tests for path utilities.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from benchbox.utils.path_utils import (
    ensure_directory,
    find_work_tree_root,
    get_benchmark_runs_databases_path,
    get_benchmark_runs_dataframe_path,
    get_benchmark_runs_datagen_path,
    get_default_data_directory,
    get_results_path,
    resolve_benchmark_runs_dir,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestGetDefaultDataDirectory:
    """Test get_default_data_directory function."""

    @patch.dict(os.environ, {"BENCHBOX_DATA_DIR": "/custom/data/path"})
    def test_get_default_data_directory_from_env(self):
        """Test getting default data directory from environment variable."""
        result = get_default_data_directory()

        assert result == Path("/custom/data/path")
        assert isinstance(result, Path)

    @patch.dict(os.environ, {}, clear=True)
    @patch("benchbox.utils.path_utils.Path.cwd")
    def test_get_default_data_directory_fallback(self, mock_cwd):
        """Test getting default data directory fallback to current directory."""
        mock_cwd.return_value = Path("/current/working/dir")

        result = get_default_data_directory()

        assert result == Path("/current/working/dir/data")
        mock_cwd.assert_called_once()

    @patch.dict(os.environ, {"BENCHBOX_DATA_DIR": ""})
    @patch("benchbox.utils.path_utils.Path.cwd")
    def test_get_default_data_directory_empty_env(self, mock_cwd):
        """Test that empty environment variable falls back to current directory."""
        mock_cwd.return_value = Path("/fallback/path")

        result = get_default_data_directory()

        assert result == Path("/fallback/path/data")
        mock_cwd.assert_called_once()

    def test_get_default_data_directory_returns_path_object(self, tmp_path):
        """Test that function always returns Path object."""
        test_path = str(tmp_path / "env_path")
        with patch.dict(os.environ, {"BENCHBOX_DATA_DIR": test_path}):
            result = get_default_data_directory()

            assert isinstance(result, Path)
            assert result == Path(test_path)


class TestGetResultsPath:
    """Test get_results_path function."""

    def test_get_results_path_default_base_dir(self):
        """Test getting results path with default base directory."""
        with patch("benchbox.utils.path_utils.get_default_data_directory") as mock_default:
            mock_default.return_value = Path("/default/data")

            result = get_results_path("tpch", "20250115_123045")

            assert result == Path("/default/data/results/tpch_20250115_123045")
            mock_default.assert_called_once()

    def test_get_results_path_custom_base_dir_string(self):
        """Test getting results path with custom base directory as string."""
        result = get_results_path("tpcds", "20250115_143000", "/custom/results/base")

        assert result == Path("/custom/results/base/results/tpcds_20250115_143000")

    def test_get_results_path_custom_base_dir_path(self):
        """Test getting results path with custom base directory as Path."""
        base_path = Path("/custom/path/object")
        result = get_results_path("ssb", "20250115_160000", base_path)

        assert result == Path("/custom/path/object/results/ssb_20250115_160000")

    def test_get_results_path_various_benchmarks(self):
        """Test results paths for various benchmark names."""
        base_dir = "/test/results"
        timestamp = "20250115_120000"

        # Test different benchmark names
        tpch_path = get_results_path("tpch", timestamp, base_dir)
        tpcds_path = get_results_path("tpcds", timestamp, base_dir)
        ssb_path = get_results_path("ssb", timestamp, base_dir)

        assert tpch_path == Path("/test/results/results/tpch_20250115_120000")
        assert tpcds_path == Path("/test/results/results/tpcds_20250115_120000")
        assert ssb_path == Path("/test/results/results/ssb_20250115_120000")

    def test_get_results_path_various_timestamps(self):
        """Test results paths for various timestamp formats."""
        base_dir = "/test/timestamps"
        benchmark = "tpch"

        # Test different timestamp formats
        iso_path = get_results_path(benchmark, "2025-01-15T12:30:45", base_dir)
        compact_path = get_results_path(benchmark, "20250115_123045", base_dir)
        custom_path = get_results_path(benchmark, "run_001", base_dir)

        assert iso_path == Path("/test/timestamps/results/tpch_2025-01-15T12:30:45")
        assert compact_path == Path("/test/timestamps/results/tpch_20250115_123045")
        assert custom_path == Path("/test/timestamps/results/tpch_run_001")

    def test_get_results_path_returns_path_object(self):
        """Test that function always returns Path object."""
        result = get_results_path("test", "timestamp", "/base")

        assert isinstance(result, Path)

    def test_get_results_path_special_characters(self):
        """Test results path with special characters in benchmark and timestamp."""
        base_dir = "/test/special"

        # Test with special characters
        special_benchmark = get_results_path("test-benchmark_v2", "2025-01-15_run-001", base_dir)

        assert special_benchmark == Path("/test/special/results/test-benchmark_v2_2025-01-15_run-001")


class TestEnsureDirectory:
    """Test ensure_directory function."""

    def test_ensure_directory_string_path(self, tmp_path):
        """Test ensuring directory with string path."""
        test_dir = tmp_path / "test_string_dir"
        test_dir_str = str(test_dir)

        result = ensure_directory(test_dir_str)

        assert result == Path(test_dir_str)
        assert test_dir.exists()
        assert test_dir.is_dir()

    def test_ensure_directory_path_object(self, tmp_path):
        """Test ensuring directory with Path object."""
        test_dir = tmp_path / "test_path_dir"

        result = ensure_directory(test_dir)

        assert result == test_dir
        assert test_dir.exists()
        assert test_dir.is_dir()

    def test_ensure_directory_nested_path(self, tmp_path):
        """Test ensuring nested directory structure."""
        nested_dir = tmp_path / "level1" / "level2" / "level3"

        result = ensure_directory(nested_dir)

        assert result == nested_dir
        assert nested_dir.exists()
        assert nested_dir.is_dir()
        # Verify all parent directories were created
        assert (tmp_path / "level1").exists()
        assert (tmp_path / "level1" / "level2").exists()

    def test_ensure_directory_already_exists(self, tmp_path):
        """Test ensuring directory that already exists."""
        existing_dir = tmp_path / "existing"
        existing_dir.mkdir()

        result = ensure_directory(existing_dir)

        assert result == existing_dir
        assert existing_dir.exists()
        assert existing_dir.is_dir()

    def test_ensure_directory_parents_true(self, tmp_path):
        """Test that parents=True is used (creates parent directories)."""
        deep_dir = tmp_path / "a" / "b" / "c" / "d" / "e"

        result = ensure_directory(deep_dir)

        assert result == deep_dir
        assert deep_dir.exists()
        # Verify all intermediate directories exist
        current = tmp_path
        for part in ["a", "b", "c", "d", "e"]:
            current = current / part
            assert current.exists()
            assert current.is_dir()

    def test_ensure_directory_exist_ok_true(self, tmp_path):
        """Test that exist_ok=True is used (no error if directory exists)."""
        existing_dir = tmp_path / "existing"
        existing_dir.mkdir()

        # Should not raise an exception
        result = ensure_directory(existing_dir)

        assert result == existing_dir
        assert existing_dir.exists()

    def test_ensure_directory_returns_path_object(self, tmp_path):
        """Test that function always returns Path object."""
        test_dir = tmp_path / "test_return_type"

        # Test with string input
        result_from_string = ensure_directory(str(test_dir))
        assert isinstance(result_from_string, Path)

        # Test with Path input
        test_dir2 = tmp_path / "test_return_type2"
        result_from_path = ensure_directory(test_dir2)
        assert isinstance(result_from_path, Path)

    def test_ensure_directory_absolute_path(self, tmp_path):
        """Test ensuring directory with absolute path."""
        abs_dir = tmp_path / "absolute_test"

        result = ensure_directory(abs_dir)

        assert result.is_absolute()
        assert result == abs_dir
        assert abs_dir.exists()

    def test_ensure_directory_relative_path(self):
        """Test ensuring directory with relative path."""
        with patch("pathlib.Path.mkdir") as mock_mkdir:
            relative_dir = Path("relative/test/dir")

            result = ensure_directory(relative_dir)

            assert result == relative_dir
            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

    def test_ensure_directory_permission_error(self):
        """Test handling permission errors when creating directory."""
        with patch("pathlib.Path.mkdir") as mock_mkdir:
            mock_mkdir.side_effect = PermissionError("Permission denied")

            with pytest.raises(PermissionError, match="Permission denied"):
                ensure_directory("/restricted/path")

    def test_ensure_directory_file_exists_error(self, tmp_path):
        """Test error when path exists as file, not directory."""
        # Create a file at the target path
        file_path = tmp_path / "file_not_dir"
        file_path.write_text("content")

        # Trying to create directory with same name should fail
        with pytest.raises(FileExistsError):
            ensure_directory(file_path)


class TestPathUtilsIntegration:
    """Test integration scenarios combining multiple path utilities."""

    def test_datagen_and_results_paths_independence(self, tmp_path):
        """Test that datagen and results paths are independent."""
        base_dir = tmp_path / "test_integration"
        base_dir.mkdir()
        benchmark = "tpch"
        scale_factor = 1.0
        timestamp = "20250115_120000"

        datagen_path = get_benchmark_runs_datagen_path(benchmark, scale_factor, base_dir)
        results_path = get_results_path(benchmark, timestamp, base_dir)

        # Paths should be different
        assert datagen_path != results_path

        # But both under same base directory
        assert datagen_path.is_relative_to(base_dir)
        assert results_path.is_relative_to(base_dir)

        # Verify expected structures (use Path for cross-platform comparison)
        assert datagen_path == base_dir / "tpch_sf1"
        assert results_path == base_dir / "results" / "tpch_20250115_120000"

    def test_full_workflow_path_creation(self, tmp_path):
        """Test complete workflow of creating datagen and results directories."""
        base_dir = tmp_path / "workflow_test"
        benchmark = "tpcds"
        scale_factor = 0.1
        timestamp = "20250115_140000"

        # Get paths
        datagen_path = get_benchmark_runs_datagen_path(benchmark, scale_factor, base_dir)
        results_path = get_results_path(benchmark, timestamp, base_dir)

        # Ensure directories exist
        datagen_dir = ensure_directory(datagen_path)
        results_dir = ensure_directory(results_path)

        # Verify everything was created correctly
        assert datagen_dir.exists() and datagen_dir.is_dir()
        assert results_dir.exists() and results_dir.is_dir()

        # Verify path structure
        assert datagen_dir == base_dir / "tpcds_sf01"
        assert results_dir == base_dir / "results" / "tpcds_20250115_140000"

        # Verify base directory was created
        assert base_dir.exists()

    def test_environment_variable_integration(self, tmp_path):
        """Test integration with environment variable configuration."""
        custom_data_dir = tmp_path / "env_test_data"

        with patch.dict(os.environ, {"BENCHBOX_DATA_DIR": str(custom_data_dir)}):
            # Get default directory (should use env var)
            default_dir = get_default_data_directory()
            assert default_dir == custom_data_dir

            # get_results_path consumes BENCHBOX_DATA_DIR via get_default_data_directory.
            # (BENCHBOX_OUTPUT_DIR is the runs-root override; covered separately below.)
            results_path = get_results_path("ssb", "20250115_150000")  # No base_dir specified

            # Verify results path uses environment variable
            assert str(results_path).startswith(str(custom_data_dir))

            # Create directory
            ensure_directory(results_path)

            # Verify creation
            assert results_path.exists()

    def test_mixed_path_types_handling(self, tmp_path):
        """Test handling of mixed string and Path objects."""
        base_dir_str = str(tmp_path / "mixed_test")
        base_dir_path = Path(tmp_path / "mixed_test2")

        # Test with string base directory
        path1 = get_benchmark_runs_datagen_path("test1", 1.0, base_dir_str)
        ensure_directory(path1)

        # Test with Path base directory
        path2 = get_results_path("test2", "timestamp", base_dir_path)
        ensure_directory(path2)

        # Both should work and return Path objects
        assert isinstance(path1, Path)
        assert isinstance(path2, Path)
        assert path1.exists()
        assert path2.exists()


class TestGetBenchmarkRunsDatabasesPath:
    """Test get_benchmark_runs_databases_path function."""

    def test_default_databases_path(self):
        """Default path should use benchmark_runs/databases under cwd."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("benchbox.utils.path_utils.Path.cwd", return_value=Path("/repo")),
        ):
            result = get_benchmark_runs_databases_path("tpch", 1.0)
        assert result == Path("/repo/benchmark_runs/databases/tpch_sf1")

    def test_custom_base_dir(self):
        """Custom base dir should be used directly."""
        result = get_benchmark_runs_databases_path("tpcds", 0.01, "/tmp/base")
        assert result == Path("/tmp/base/tpcds_sf001")


class TestBenchboxOutputDirRedirection:
    """BENCHBOX_OUTPUT_DIR redirects datagen, databases, and dataframe-cache roots."""

    def test_datagen_path_honors_output_dir(self, tmp_path):
        custom_root = tmp_path / "runs"
        with patch.dict(os.environ, {"BENCHBOX_OUTPUT_DIR": str(custom_root)}):
            result = get_benchmark_runs_datagen_path("tpch", 1.0)
        assert result == custom_root / "datagen" / "tpch_sf1"

    def test_databases_path_honors_output_dir(self, tmp_path):
        custom_root = tmp_path / "runs"
        with patch.dict(os.environ, {"BENCHBOX_OUTPUT_DIR": str(custom_root)}):
            result = get_benchmark_runs_databases_path("tpcds", 0.01)
        assert result == custom_root / "databases" / "tpcds_sf001"

    def test_dataframe_path_honors_output_dir(self, tmp_path):
        custom_root = tmp_path / "runs"
        with patch.dict(os.environ, {"BENCHBOX_OUTPUT_DIR": str(custom_root)}):
            result = get_benchmark_runs_dataframe_path()
        assert result == custom_root / "datagen"

    def test_explicit_base_dir_overrides_env(self, tmp_path):
        """An explicit base_dir takes precedence over BENCHBOX_OUTPUT_DIR."""
        env_root = tmp_path / "from_env"
        explicit = tmp_path / "from_arg"
        with patch.dict(os.environ, {"BENCHBOX_OUTPUT_DIR": str(env_root)}):
            result = get_benchmark_runs_databases_path("tpch", 1.0, explicit)
        assert result == explicit / "tpch_sf1"

    def test_resolve_benchmark_runs_dir_expands_user(self, tmp_path, monkeypatch):
        """``~`` in the env var is expanded so callers get an absolute path."""
        # Path.expanduser() consults HOME on POSIX and USERPROFILE on Windows
        # (ntpath.expanduser ignores HOME); set both so the test is portable.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", "~/runs")
        assert resolve_benchmark_runs_dir() == tmp_path / "runs"

    def test_resolve_benchmark_runs_dir_falls_back_to_cwd(self):
        """Outside a Git work tree, the cwd-anchored default is unchanged.

        ``/repo`` has no ``.git`` entry in any parent, so this exercises the
        installed-package path where there is no work tree to anchor to.
        """
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("benchbox.utils.path_utils.Path.cwd", return_value=Path("/repo")),
        ):
            assert resolve_benchmark_runs_dir() == Path("/repo/benchmark_runs")

    def test_empty_env_var_falls_back_to_cwd(self):
        """An empty BENCHBOX_OUTPUT_DIR value should not override the default."""
        with (
            patch.dict(os.environ, {"BENCHBOX_OUTPUT_DIR": ""}),
            patch("benchbox.utils.path_utils.Path.cwd", return_value=Path("/repo")),
        ):
            assert resolve_benchmark_runs_dir() == Path("/repo/benchmark_runs")


class TestWorkTreeAnchoredDefault:
    """The default benchmark_runs root is a sibling of the enclosing work tree.

    A cwd-anchored default put multi-gigabyte datagen artifacts *inside* the
    checkout and gave every pool worktree its own copy. Anchoring to the work
    tree's parent yields one shared ``../benchmark_runs`` for the clone and
    every linked worktree.
    """

    def _make_work_tree(self, root: Path, *, linked: bool) -> Path:
        """Create a fake work tree whose .git is a file (linked) or directory."""
        root.mkdir(parents=True, exist_ok=True)
        marker = root / ".git"
        if linked:
            # A linked worktree's .git is a *file* pointing at the real gitdir.
            marker.write_text("gitdir: /elsewhere/.git/worktrees/wt\n")
        else:
            marker.mkdir()
        return root

    @pytest.mark.parametrize("linked", [False, True], ids=["clone", "linked_worktree"])
    def test_find_work_tree_root_accepts_both_git_marker_forms(self, tmp_path, linked):
        """.git is a directory in a clone and a file in a linked worktree."""
        work_tree = self._make_work_tree(tmp_path / "checkout", linked=linked)
        nested = work_tree / "benchbox" / "utils"
        nested.mkdir(parents=True)

        assert find_work_tree_root(work_tree) == work_tree
        assert find_work_tree_root(nested) == work_tree

    def test_find_work_tree_root_returns_none_outside_a_work_tree(self, tmp_path):
        """No .git in any parent means no work tree."""
        plain = tmp_path / "not_a_repo" / "deep"
        plain.mkdir(parents=True)
        assert find_work_tree_root(plain) is None

    @pytest.mark.parametrize("linked", [False, True], ids=["clone", "linked_worktree"])
    def test_default_root_is_the_work_tree_sibling(self, tmp_path, monkeypatch, linked):
        """The resolved default is <work_tree>.parent/'benchmark_runs'."""
        work_tree = self._make_work_tree(tmp_path / "checkout", linked=linked)
        monkeypatch.delenv("BENCHBOX_OUTPUT_DIR", raising=False)
        monkeypatch.chdir(work_tree)

        assert resolve_benchmark_runs_dir() == tmp_path / "benchmark_runs"

    def test_default_root_is_never_inside_the_work_tree(self, tmp_path, monkeypatch):
        """The regression this item exists to prevent: no in-repo artifacts."""
        work_tree = self._make_work_tree(tmp_path / "checkout", linked=False)
        monkeypatch.delenv("BENCHBOX_OUTPUT_DIR", raising=False)
        monkeypatch.chdir(work_tree)

        resolved = resolve_benchmark_runs_dir()

        assert resolved != work_tree
        assert work_tree not in resolved.parents

    def test_default_root_is_cwd_independent_within_a_work_tree(self, tmp_path, monkeypatch):
        """Running from a nested subdirectory resolves to the same root."""
        work_tree = self._make_work_tree(tmp_path / "checkout", linked=False)
        nested = work_tree / "tests" / "unit"
        nested.mkdir(parents=True)
        monkeypatch.delenv("BENCHBOX_OUTPUT_DIR", raising=False)

        monkeypatch.chdir(work_tree)
        from_root = resolve_benchmark_runs_dir()
        monkeypatch.chdir(nested)
        from_nested = resolve_benchmark_runs_dir()

        assert from_root == from_nested == tmp_path / "benchmark_runs"

    def test_sibling_worktrees_share_one_root(self, tmp_path, monkeypatch):
        """A clone and its pool worktrees resolve to the SAME shared root."""
        clone = self._make_work_tree(tmp_path / "BenchBox", linked=False)
        pool = self._make_work_tree(tmp_path / "BenchBox.pool-01", linked=True)
        monkeypatch.delenv("BENCHBOX_OUTPUT_DIR", raising=False)

        monkeypatch.chdir(clone)
        from_clone = resolve_benchmark_runs_dir()
        monkeypatch.chdir(pool)
        from_pool = resolve_benchmark_runs_dir()

        assert from_clone == from_pool == tmp_path / "benchmark_runs"

    def test_directory_name_is_still_benchmark_runs(self, tmp_path, monkeypatch):
        """The name is unchanged, so the existing corpus keeps working."""
        work_tree = self._make_work_tree(tmp_path / "checkout", linked=False)
        monkeypatch.delenv("BENCHBOX_OUTPUT_DIR", raising=False)
        monkeypatch.chdir(work_tree)

        assert resolve_benchmark_runs_dir().name == "benchmark_runs"

    def test_env_var_still_wins_inside_a_work_tree(self, tmp_path, monkeypatch):
        """BENCHBOX_OUTPUT_DIR keeps absolute precedence over the new default."""
        work_tree = self._make_work_tree(tmp_path / "checkout", linked=False)
        override = tmp_path / "explicit_root"
        monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", str(override))
        monkeypatch.chdir(work_tree)

        assert resolve_benchmark_runs_dir() == override

    def test_relative_env_var_still_wins_inside_a_work_tree(self, tmp_path, monkeypatch):
        """A relative BENCHBOX_OUTPUT_DIR is still accepted verbatim."""
        work_tree = self._make_work_tree(tmp_path / "checkout", linked=False)
        monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", "local_runs")
        monkeypatch.chdir(work_tree)

        assert resolve_benchmark_runs_dir() == Path("local_runs")

    def test_explicit_benchmark_runs_env_is_not_inferred_as_absent(self, tmp_path, monkeypatch):
        """An explicit value equal to the old default remains a caller override."""
        work_tree = self._make_work_tree(tmp_path / "checkout", linked=False)
        monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", "benchmark_runs")
        monkeypatch.chdir(work_tree)

        assert resolve_benchmark_runs_dir() == Path("benchmark_runs")

    def test_env_var_tilde_still_expands_inside_a_work_tree(self, tmp_path, monkeypatch):
        """``~`` expansion is unaffected by the work-tree anchor."""
        work_tree = self._make_work_tree(tmp_path / "checkout", linked=False)
        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", "~/runs")
        monkeypatch.chdir(work_tree)

        assert resolve_benchmark_runs_dir() == home / "runs"

    def test_derived_subdirs_follow_the_resolved_root(self, tmp_path, monkeypatch):
        """datagen/databases helpers hang off the new root, not off cwd."""
        work_tree = self._make_work_tree(tmp_path / "checkout", linked=False)
        monkeypatch.delenv("BENCHBOX_OUTPUT_DIR", raising=False)
        monkeypatch.chdir(work_tree)

        expected_root = tmp_path / "benchmark_runs"
        assert get_benchmark_runs_datagen_path("tpch", 0.01) == expected_root / "datagen" / "tpch_sf001"
        assert get_benchmark_runs_databases_path("tpch", 0.01) == expected_root / "databases" / "tpch_sf001"
