"""Tests for benchbox.release.sync module."""

import argparse
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from benchbox.release.sync import (
    git_add_files,
    git_commit,
    git_fetch,
    is_git_repo,
    is_repo_clean,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestIsGitRepo:
    def test_is_git_repo_true(self, tmp_path):
        (tmp_path / ".git").mkdir()
        assert is_git_repo(tmp_path) is True

    def test_is_git_repo_false(self, tmp_path):
        assert is_git_repo(tmp_path) is False


class TestIsRepoClean:
    def test_clean_repo(self, tmp_path):
        with patch("benchbox.release.sync.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            assert is_repo_clean(tmp_path) is True
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert call_args[0][0] == ["git", "status", "--porcelain"]
            assert call_args[1]["cwd"] == tmp_path

    def test_dirty_repo(self, tmp_path):
        with patch("benchbox.release.sync.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="M some_file.py\n", stderr=""
            )
            assert is_repo_clean(tmp_path) is False


class TestGitFetch:
    def test_fetch_success(self, tmp_path):
        with patch("benchbox.release.sync.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            assert git_fetch(tmp_path) is True

    def test_fetch_failure(self, tmp_path):
        with patch("benchbox.release.sync.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="error")
            assert git_fetch(tmp_path) is False


class TestGitAddFiles:
    def test_add_empty_set(self, tmp_path):
        assert git_add_files(tmp_path, set()) is True

    def test_add_files_success(self, tmp_path):
        with patch("benchbox.release.sync.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            files = {Path("file1.py"), Path("file2.py")}
            assert git_add_files(tmp_path, files) is True
            assert mock_run.call_count == 2

    def test_add_files_failure(self, tmp_path):
        with patch("benchbox.release.sync.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="error")
            files = {Path("file1.py")}
            assert git_add_files(tmp_path, files) is False


class TestGitCommit:
    def test_commit_nothing_to_commit(self, tmp_path):
        with patch("benchbox.release.sync.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            assert git_commit(tmp_path, "test message") is True

    def test_commit_success(self, tmp_path):
        with patch("benchbox.release.sync.subprocess.run") as mock_run:
            # First call (status) returns changes, second call (commit) succeeds
            mock_run.side_effect = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout="M file.py\n", stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            ]
            assert git_commit(tmp_path, "test commit") is True
            assert mock_run.call_count == 2

    def test_commit_failure(self, tmp_path):
        with patch("benchbox.release.sync.subprocess.run") as mock_run:
            mock_run.side_effect = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout="M file.py\n", stderr=""),
                subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="commit error"),
            ]
            assert git_commit(tmp_path, "test commit") is False


class TestCmdStatus:
    def test_source_not_found(self, tmp_path):
        from benchbox.release.sync import cmd_status

        args = argparse.Namespace(source=tmp_path / "nonexistent", target=tmp_path / "target")
        assert cmd_status(args) == 1

    def test_target_not_found_returns_zero(self, tmp_path):
        from benchbox.release.sync import cmd_status

        source = tmp_path / "source"
        source.mkdir()
        args = argparse.Namespace(source=source, target=tmp_path / "nonexistent")
        assert cmd_status(args) == 0

    @patch("benchbox.release.sync.compare_repos")
    def test_status_in_sync(self, mock_compare, tmp_path):
        from benchbox.release.sync import cmd_status

        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"
        target.mkdir()

        mock_comparison = MagicMock()
        mock_comparison.has_changes = False
        mock_comparison.has_conflicts = False
        mock_comparison.added = set()
        mock_comparison.modified = set()
        mock_comparison.deleted = set()
        mock_comparison.conflicts = set()
        mock_comparison.summary.return_value = "No changes"
        mock_compare.return_value = mock_comparison

        args = argparse.Namespace(source=source, target=target)
        assert cmd_status(args) == 0

    @patch("benchbox.release.sync.compare_repos")
    def test_status_with_changes(self, mock_compare, tmp_path):
        from benchbox.release.sync import cmd_status

        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"
        target.mkdir()

        mock_comparison = MagicMock()
        mock_comparison.has_changes = True
        mock_comparison.has_conflicts = False
        mock_comparison.added = {Path("new.py")}
        mock_comparison.modified = {Path("changed.py")}
        mock_comparison.deleted = set()
        mock_comparison.conflicts = set()
        mock_comparison.summary.return_value = "1 added, 1 modified"
        mock_compare.return_value = mock_comparison

        args = argparse.Namespace(source=source, target=target)
        assert cmd_status(args) == 0


class TestCmdPush:
    def test_push_source_not_found(self, tmp_path):
        from benchbox.release.sync import cmd_push

        args = argparse.Namespace(
            source=tmp_path / "nonexistent",
            target=tmp_path / "target",
            force=False,
            dry_run=False,
            message=None,
        )
        assert cmd_push(args) == 1

    @patch("benchbox.release.sync.compare_repos")
    def test_push_no_changes(self, mock_compare, tmp_path):
        from benchbox.release.sync import cmd_push

        source = tmp_path / "source"
        source.mkdir()

        mock_comparison = MagicMock()
        mock_comparison.has_changes = False
        mock_comparison.has_conflicts = False
        mock_comparison.summary.return_value = "No changes"
        mock_compare.return_value = mock_comparison

        args = argparse.Namespace(
            source=source,
            target=tmp_path / "nonexistent",
            force=False,
            dry_run=False,
            message=None,
        )
        assert cmd_push(args) == 0

    @patch("benchbox.release.sync.compare_repos")
    def test_push_conflicts_without_force(self, mock_compare, tmp_path):
        from benchbox.release.sync import cmd_push

        source = tmp_path / "source"
        source.mkdir()

        mock_comparison = MagicMock()
        mock_comparison.has_changes = True
        mock_comparison.has_conflicts = True
        mock_comparison.conflicts = {Path("conflict.py")}
        mock_comparison.summary.return_value = "1 conflict"
        mock_compare.return_value = mock_comparison

        args = argparse.Namespace(
            source=source,
            target=tmp_path / "nonexistent",
            force=False,
            dry_run=False,
            message=None,
        )
        assert cmd_push(args) == 1

    @patch("benchbox.release.sync.compare_repos")
    def test_push_dry_run(self, mock_compare, tmp_path):
        from benchbox.release.sync import cmd_push

        source = tmp_path / "source"
        source.mkdir()

        mock_comparison = MagicMock()
        mock_comparison.has_changes = True
        mock_comparison.has_conflicts = False
        mock_comparison.added = {Path("new.py")}
        mock_comparison.modified = set()
        mock_comparison.deleted = set()
        mock_comparison.conflicts = set()
        mock_comparison.summary.return_value = "1 added"
        mock_compare.return_value = mock_comparison

        args = argparse.Namespace(
            source=source,
            target=tmp_path / "nonexistent",
            force=False,
            dry_run=True,
            message=None,
        )
        assert cmd_push(args) == 0

    def test_push_target_dirty(self, tmp_path):
        from benchbox.release.sync import cmd_push

        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"
        target.mkdir()
        (target / ".git").mkdir()

        with patch("benchbox.release.sync.is_repo_clean", return_value=False):
            args = argparse.Namespace(
                source=source,
                target=target,
                force=False,
                dry_run=False,
                message=None,
            )
            assert cmd_push(args) == 1


class TestCmdPull:
    def test_pull_target_not_found(self, tmp_path):
        from benchbox.release.sync import cmd_pull

        source = tmp_path / "source"
        source.mkdir()
        args = argparse.Namespace(
            source=source,
            target=tmp_path / "nonexistent",
            force=False,
            dry_run=False,
            delete=False,
            revspec=None,
            max_files=100,
        )
        assert cmd_pull(args) == 1

    def test_pull_source_not_found(self, tmp_path):
        from benchbox.release.sync import cmd_pull

        target = tmp_path / "target"
        target.mkdir()
        args = argparse.Namespace(
            source=tmp_path / "nonexistent",
            target=target,
            force=False,
            dry_run=False,
            delete=False,
            revspec=None,
            max_files=100,
        )
        assert cmd_pull(args) == 1

    @patch("benchbox.release.sync.compare_repos")
    def test_pull_no_changes(self, mock_compare, tmp_path):
        from benchbox.release.sync import cmd_pull

        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"
        target.mkdir()

        mock_comparison = MagicMock()
        mock_comparison.has_changes = False
        mock_comparison.has_conflicts = False
        mock_comparison.summary.return_value = "No changes"
        mock_compare.return_value = mock_comparison

        args = argparse.Namespace(
            source=source,
            target=target,
            force=False,
            dry_run=False,
            delete=False,
            revspec=None,
            max_files=100,
        )
        assert cmd_pull(args) == 0

    @patch("benchbox.release.sync.compare_repos")
    def test_pull_dry_run(self, mock_compare, tmp_path):
        from benchbox.release.sync import cmd_pull

        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"
        target.mkdir()

        mock_comparison = MagicMock()
        mock_comparison.has_changes = True
        mock_comparison.has_conflicts = False
        mock_comparison.added = {Path("new.py")}
        mock_comparison.modified = set()
        mock_comparison.deleted = set()
        mock_comparison.conflicts = set()
        mock_comparison.summary.return_value = "1 added"
        mock_compare.return_value = mock_comparison

        args = argparse.Namespace(
            source=source,
            target=target,
            force=False,
            dry_run=True,
            delete=False,
            revspec=None,
            max_files=100,
        )
        assert cmd_pull(args) == 0

    @patch("benchbox.release.sync.compare_repos")
    def test_pull_conflicts_without_force(self, mock_compare, tmp_path):
        from benchbox.release.sync import cmd_pull

        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"
        target.mkdir()

        mock_comparison = MagicMock()
        mock_comparison.has_changes = True
        mock_comparison.has_conflicts = True
        mock_comparison.conflicts = {Path("conflict.py")}
        mock_comparison.summary.return_value = "1 conflict"
        mock_compare.return_value = mock_comparison

        args = argparse.Namespace(
            source=source,
            target=target,
            force=False,
            dry_run=False,
            delete=False,
            revspec=None,
            max_files=100,
        )
        assert cmd_pull(args) == 1

    @patch("benchbox.release.sync.compare_repos")
    def test_pull_preserves_private_gitignore(self, mock_compare, tmp_path):
        from benchbox.release.sync import cmd_pull

        source = tmp_path / "private"
        source.mkdir()
        target = tmp_path / "public"
        target.mkdir()

        (source / ".gitignore").write_text("private-only-pattern\n", encoding="utf-8")
        (target / ".gitignore").write_text("public-pattern\n", encoding="utf-8")
        (target / "new.py").write_text("print('synced')\n", encoding="utf-8")

        mock_comparison = MagicMock()
        mock_comparison.has_changes = True
        mock_comparison.has_conflicts = False
        mock_comparison.added = {Path("new.py")}
        mock_comparison.modified = {Path(".gitignore")}
        mock_comparison.deleted = set()
        mock_comparison.conflicts = set()
        mock_comparison.summary.return_value = "1 added, 1 modified"
        mock_compare.return_value = mock_comparison

        args = argparse.Namespace(
            source=source,
            target=target,
            force=False,
            dry_run=False,
            delete=False,
            revspec=None,
            max_files=100,
        )
        assert cmd_pull(args) == 0
        assert (source / "new.py").read_text(encoding="utf-8") == "print('synced')\n"
        assert (source / ".gitignore").read_text(encoding="utf-8") == "private-only-pattern\n"

    @patch("benchbox.release.sync.compare_repos")
    def test_pull_aborts_on_large_change_set_without_force(self, mock_compare, tmp_path):
        from benchbox.release.sync import cmd_pull

        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"
        target.mkdir()

        mock_comparison = MagicMock()
        mock_comparison.has_changes = True
        mock_comparison.has_conflicts = False
        mock_comparison.added = {Path(f"f{i}.py") for i in range(80)}
        mock_comparison.modified = {Path(f"m{i}.py") for i in range(80)}
        mock_comparison.deleted = set()
        mock_comparison.conflicts = set()
        mock_comparison.summary.return_value = "160 changed"
        mock_compare.return_value = mock_comparison

        args = argparse.Namespace(
            source=source,
            target=target,
            force=False,
            dry_run=False,
            delete=False,
            revspec=None,
            max_files=100,
        )
        assert cmd_pull(args) == 1

    @patch("benchbox.release.sync.git_changed_files")
    @patch("benchbox.release.sync.compare_repos")
    def test_pull_revspec_filters_files(self, mock_compare, mock_changed_files, tmp_path):
        from benchbox.release.sync import cmd_pull

        source = tmp_path / "private"
        source.mkdir()
        target = tmp_path / "public"
        target.mkdir()

        (target / "keep.py").write_text("print('keep')\n", encoding="utf-8")
        (target / "drop.py").write_text("print('drop')\n", encoding="utf-8")

        mock_comparison = MagicMock()
        mock_comparison.has_changes = True
        mock_comparison.has_conflicts = False
        mock_comparison.added = {Path("keep.py"), Path("drop.py")}
        mock_comparison.modified = set()
        mock_comparison.deleted = set()
        mock_comparison.conflicts = set()
        mock_comparison.summary.return_value = "2 added"
        mock_compare.return_value = mock_comparison
        mock_changed_files.return_value = {Path("keep.py")}

        args = argparse.Namespace(
            source=source,
            target=target,
            force=False,
            dry_run=False,
            delete=False,
            revspec="HEAD~1..HEAD",
            max_files=100,
        )
        assert cmd_pull(args) == 0
        assert (source / "keep.py").exists()
        assert not (source / "drop.py").exists()


class TestMainArgparser:
    def test_main_no_args_exits(self):
        from benchbox.release.sync import main

        with patch("sys.argv", ["benchbox-sync"]):
            with pytest.raises(SystemExit):
                main()
