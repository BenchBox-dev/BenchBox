"""Tests for release script functions.

Tests functions from scripts/automate_release.py, scripts/build_release.py,
scripts/verify_release.py, and scripts/finalize_release.py. All subprocess
calls are mocked -- no real git, uv, or builds.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import hashlib
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]


# Add scripts/ to sys.path so we can import release script functions directly
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from automate_release import (
    _find_squash_anchor,
    _incremental_release_commit_message,
    _initial_release_commit_message,
    parse_timestamp,
    run_ci_checks,
    run_pre_flight_checks,
    squash_commits,
)
from build_release import calculate_sha256, verify_wheel_timestamps
from finalize_release import (
    archive_release_artifacts,
    git_commit_with_timestamp,
    git_tag_with_timestamp,
    verify_git_status,
    verify_source_fingerprint,
)
from update_version import update_version_in_init, update_version_in_pyproject
from verify_release import verify_wheel_fingerprint


# =============================================================================
# automate_release.py Tests
# =============================================================================
class TestParseTimestamp:
    """Test parse_timestamp() from automate_release.py."""

    def test_git_format_with_timezone(self):
        """Git format with timezone parses correctly."""
        unix_ts, iso_fmt, git_fmt = parse_timestamp("2026-01-16 13:00:00 -0500")

        assert isinstance(unix_ts, int)
        assert isinstance(iso_fmt, str)
        assert isinstance(git_fmt, str)
        # Verify the parsed timestamp represents the correct moment
        dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
        assert dt.hour == 18  # 13:00 EST = 18:00 UTC

    def test_without_timezone_assumes_utc(self):
        """Timestamp without timezone is treated as UTC."""
        unix_ts, iso_fmt, git_fmt = parse_timestamp("2026-01-16 13:00:00")

        dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
        assert dt.hour == 13  # No conversion, stays at 13:00 UTC

    def test_invalid_format_raises_valueerror(self):
        """Invalid format raises ValueError with descriptive message."""
        with pytest.raises(ValueError, match="Cannot parse timestamp"):
            parse_timestamp("not-a-date")

    def test_format_consistency(self):
        """All three return values represent the same moment in time."""
        unix_ts, iso_fmt, git_fmt = parse_timestamp("2026-01-16 13:00:00 +0000")

        dt_from_iso = datetime.fromisoformat(iso_fmt)
        dt_from_git = datetime.strptime(git_fmt, "%Y-%m-%d %H:%M:%S %z")

        assert int(dt_from_iso.timestamp()) == unix_ts
        assert int(dt_from_git.timestamp()) == unix_ts


class TestRunPreFlightChecks:
    """Test run_pre_flight_checks() from automate_release.py."""

    @staticmethod
    def _write_version(tmp_path: Path, version: str = "0.1.0") -> None:
        """Create benchbox/__init__.py with __version__ in tmp_path."""
        pkg = tmp_path / "benchbox"
        pkg.mkdir(exist_ok=True)
        (pkg / "__init__.py").write_text(f'__version__ = "{version}"\n')

    def test_missing_changelog_returns_false(self, tmp_path: Path):
        """Missing CHANGELOG.md returns False after version checks pass."""
        self._write_version(tmp_path)
        result = run_pre_flight_checks(tmp_path, "0.1.0", "2026-02-08", auto_continue=True)
        assert result is False

    def test_changelog_without_version_auto_generates(self, tmp_path: Path):
        """CHANGELOG without version entry triggers auto-generation."""
        self._write_version(tmp_path)
        (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\nNo versions yet.\n")

        def mock_run_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if cmd[0] == "git" and cmd[1] == "describe":
                return MagicMock(returncode=1, stdout="", stderr="no tag")
            if cmd[0] == "git" and cmd[1] == "log":
                return MagicMock(returncode=0, stdout="feat: add new feature\nfix: fix a bug\n")
            # git status
            return MagicMock(returncode=0, stdout="M CHANGELOG.md\n")

        with patch("automate_release.subprocess.run", side_effect=mock_run_side_effect):
            result = run_pre_flight_checks(tmp_path, "0.1.0", "2026-02-08", auto_continue=True)

        assert result is True
        changelog_text = (tmp_path / "CHANGELOG.md").read_text()
        assert "## [0.1.0] - 2026-02-08" in changelog_text

    def test_valid_changelog_passes(self, tmp_path: Path):
        """CHANGELOG with version entry passes."""
        self._write_version(tmp_path)
        (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## [0.1.0]\n\n- Initial release\n")

        with patch("automate_release.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            result = run_pre_flight_checks(tmp_path, "0.1.0", "2026-02-08", auto_continue=True)

        assert result is True

    def test_invalid_version_format_returns_false(self, tmp_path: Path):
        """Invalid version format returns False."""
        (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## [!@#$]\n")

        result = run_pre_flight_checks(tmp_path, "!@#$", "2026-02-08", auto_continue=True)

        assert result is False

    def test_clean_git_status_passes(self, tmp_path: Path):
        """Clean git status passes check."""
        self._write_version(tmp_path)
        (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## [0.1.0]\n")

        with patch("automate_release.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            result = run_pre_flight_checks(tmp_path, "0.1.0", "2026-02-08", auto_continue=True)

        assert result is True

    def test_dirty_git_status_continues_with_auto(self, tmp_path: Path):
        """Dirty git status continues when auto_continue=True."""
        self._write_version(tmp_path)
        (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## [0.1.0]\n")

        with patch("automate_release.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="M file.py\n")
            result = run_pre_flight_checks(tmp_path, "0.1.0", "2026-02-08", auto_continue=True)

        assert result is True


class TestRunCiChecks:
    """Test run_ci_checks() from automate_release.py."""

    def test_all_checks_pass(self, tmp_path: Path):
        """All 4 CI checks passing returns True."""
        with patch("automate_release.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = run_ci_checks(tmp_path)

        assert result is True
        assert mock_run.call_count == 4

    def test_lint_failure(self, tmp_path: Path):
        """First check (ruff check) failing returns False."""
        with patch("automate_release.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="lint error", stderr="")
            result = run_ci_checks(tmp_path)

        assert result is False

    def test_format_failure(self, tmp_path: Path):
        """Second check (ruff format --check) failing returns False."""
        with patch("automate_release.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),  # lint passes
                MagicMock(returncode=1, stdout="format error", stderr=""),  # format fails
            ]
            result = run_ci_checks(tmp_path)

        assert result is False

    def test_typecheck_failure(self, tmp_path: Path):
        """Third check (ty check) failing returns False."""
        with patch("automate_release.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),  # lint
                MagicMock(returncode=0, stdout="", stderr=""),  # format
                MagicMock(returncode=1, stdout="type error", stderr=""),  # typecheck fails
            ]
            result = run_ci_checks(tmp_path)

        assert result is False

    def test_test_failure(self, tmp_path: Path):
        """Fourth check (pytest) failing returns False."""
        with patch("automate_release.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),  # lint
                MagicMock(returncode=0, stdout="", stderr=""),  # format
                MagicMock(returncode=0, stdout="", stderr=""),  # typecheck
                MagicMock(returncode=1, stdout="test failure", stderr=""),  # test fails
            ]
            result = run_ci_checks(tmp_path)

        assert result is False


class TestUpdateVersionScript:
    """Regression coverage for scripts/update_version.py helpers."""

    def test_update_version_in_init_noop_returns_true(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Already-matching __version__ should be treated as a successful no-op."""
        pkg_dir = tmp_path / "benchbox"
        pkg_dir.mkdir()
        init_file = pkg_dir / "__init__.py"
        init_file.write_text('__version__ = "0.1.3"\n')

        monkeypatch.setattr("update_version.get_project_root", lambda: tmp_path)

        assert update_version_in_init("0.1.3") is True
        assert init_file.read_text() == '__version__ = "0.1.3"\n'

    def test_update_version_in_init_missing_pattern_returns_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Missing __version__ marker should fail clearly."""
        pkg_dir = tmp_path / "benchbox"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("name = 'benchbox'\n")

        monkeypatch.setattr("update_version.get_project_root", lambda: tmp_path)

        assert update_version_in_init("0.1.3") is False

    def test_update_version_in_pyproject_noop_returns_true(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Already-matching pyproject version should be treated as a successful no-op."""
        pyproject_file = tmp_path / "pyproject.toml"
        pyproject_file.write_text('[project]\nname = "benchbox"\nversion = "0.1.3"\n')

        monkeypatch.setattr("update_version.get_project_root", lambda: tmp_path)

        assert update_version_in_pyproject("0.1.3") is True
        assert pyproject_file.read_text() == '[project]\nname = "benchbox"\nversion = "0.1.3"\n'

    def test_update_version_in_pyproject_updates_value(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Version field should update when target differs."""
        pyproject_file = tmp_path / "pyproject.toml"
        pyproject_file.write_text('[project]\nname = "benchbox"\nversion = "0.1.2"\n')

        monkeypatch.setattr("update_version.get_project_root", lambda: tmp_path)

        assert update_version_in_pyproject("0.1.3") is True
        assert 'version = "0.1.3"' in pyproject_file.read_text()


# =============================================================================
# build_release.py Tests
# =============================================================================
class TestCalculateSha256:
    """Test calculate_sha256() from build_release.py."""

    def test_known_hash(self, tmp_path: Path):
        """File with known content produces expected SHA256 hex digest."""
        f = tmp_path / "test.txt"
        content = b"hello world\n"
        f.write_bytes(content)

        result = calculate_sha256(f)
        expected = hashlib.sha256(content).hexdigest()

        assert result == expected

    def test_empty_file(self, tmp_path: Path):
        """Empty file produces SHA256 of empty bytes."""
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")

        result = calculate_sha256(f)
        expected = hashlib.sha256(b"").hexdigest()

        assert result == expected
        assert result.startswith("e3b0c44298fc1c149")

    def test_large_file_chunking(self, tmp_path: Path):
        """File larger than 8192 bytes hashes correctly (verifies chunked reading)."""
        f = tmp_path / "large.bin"
        content = b"x" * 20000  # Larger than 8192 chunk size
        f.write_bytes(content)

        result = calculate_sha256(f)
        expected = hashlib.sha256(content).hexdigest()

        assert result == expected


class TestVerifyWheelTimestamps:
    """Test verify_wheel_timestamps() from build_release.py."""

    def _create_wheel_zip(self, path: Path, timestamp: int, filenames: list[str] | None = None):
        """Helper: create a fake wheel zip with files at given timestamp."""
        if filenames is None:
            filenames = ["benchbox/__init__.py", "benchbox/core.py"]
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        date_time = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)

        with zipfile.ZipFile(path, "w") as zf:
            for fname in filenames:
                info = zipfile.ZipInfo(fname, date_time=date_time)
                zf.writestr(info, f"# {fname}")

    def test_matching_timestamps_pass(self, tmp_path: Path):
        """Wheel with matching timestamps passes."""
        wheel = tmp_path / "benchbox-0.1.0.whl"
        ts = 1700000000
        self._create_wheel_zip(wheel, ts)

        result = verify_wheel_timestamps(wheel, ts)

        assert result is True

    def test_mismatched_timestamps_fail(self, tmp_path: Path):
        """Wheel with wrong timestamp fails."""
        wheel = tmp_path / "benchbox-0.1.0.whl"
        self._create_wheel_zip(wheel, 1700000000)

        result = verify_wheel_timestamps(wheel, 1800000000)

        assert result is False

    def test_one_second_tolerance(self, tmp_path: Path):
        """Entry timestamp off by exactly 1 second passes (within tolerance)."""
        wheel = tmp_path / "benchbox-0.1.0.whl"
        ts = 1700000000
        self._create_wheel_zip(wheel, ts)

        # Off by 1 second should still pass
        result = verify_wheel_timestamps(wheel, ts + 1)

        assert result is True

    def test_beyond_tolerance_fails(self, tmp_path: Path):
        """Entry timestamp off by 2 seconds fails."""
        wheel = tmp_path / "benchbox-0.1.0.whl"
        ts = 1700000000
        self._create_wheel_zip(wheel, ts)

        result = verify_wheel_timestamps(wheel, ts + 2)

        assert result is False


# =============================================================================
# verify_release.py Tests
# =============================================================================
class TestVerifyWheelFingerprint:
    """Test verify_wheel_fingerprint() from verify_release.py."""

    def test_matching_fingerprint(self, tmp_path: Path):
        """Wheel with matching benchbox/ .py files verifies correctly."""
        wheel = tmp_path / "benchbox-0.1.0.whl"
        with zipfile.ZipFile(wheel, "w") as zf:
            zf.writestr("benchbox/__init__.py", "version = '0.1.0'")
            zf.writestr("benchbox/core.py", "def main(): pass")

        # Compute expected fingerprint by extracting and fingerprinting
        from benchbox.release.workflow import compute_source_fingerprint

        extract_dir = tmp_path / "extract"
        with zipfile.ZipFile(wheel, "r") as zf:
            zf.extractall(extract_dir)
        expected = compute_source_fingerprint(extract_dir / "benchbox")

        result = verify_wheel_fingerprint(wheel, expected)

        assert result is True

    def test_mismatched_fingerprint(self, tmp_path: Path):
        """Wrong expected fingerprint returns False."""
        wheel = tmp_path / "benchbox-0.1.0.whl"
        with zipfile.ZipFile(wheel, "w") as zf:
            zf.writestr("benchbox/__init__.py", "version = '0.1.0'")

        result = verify_wheel_fingerprint(wheel, "a" * 64)

        assert result is False

    def test_missing_benchbox_dir(self, tmp_path: Path):
        """Wheel without benchbox/ directory returns False."""
        wheel = tmp_path / "benchbox-0.1.0.whl"
        with zipfile.ZipFile(wheel, "w") as zf:
            zf.writestr("other_package/__init__.py", "# not benchbox")

        result = verify_wheel_fingerprint(wheel, "a" * 64)

        assert result is False


# =============================================================================
# finalize_release.py Tests
# =============================================================================
class TestGitCommitWithTimestamp:
    """Test git_commit_with_timestamp() from finalize_release.py."""

    def test_success_sets_env_vars(self, tmp_path: Path):
        """Successful commit sets GIT_AUTHOR_DATE and GIT_COMMITTER_DATE."""
        git_ts = "2026-01-04 00:00:00 +0000"

        with patch("finalize_release.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="[main abc1234] msg")
            result = git_commit_with_timestamp(tmp_path, "test commit", git_ts)

        assert result is True
        env_arg = mock_run.call_args.kwargs.get("env") or mock_run.call_args[1].get("env")
        assert env_arg["GIT_AUTHOR_DATE"] == git_ts
        assert env_arg["GIT_COMMITTER_DATE"] == git_ts

    def test_failure_returns_false(self, tmp_path: Path):
        """Failed git commit returns False."""
        with patch("finalize_release.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            result = git_commit_with_timestamp(tmp_path, "msg", "2026-01-04 00:00:00 +0000")

        assert result is False

    def test_commit_message_passed(self, tmp_path: Path):
        """Commit message is passed to git commit -m."""
        msg = "chore(release): prepare v0.1.0"

        with patch("finalize_release.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok")
            git_commit_with_timestamp(tmp_path, msg, "2026-01-04 00:00:00 +0000")

        cmd = mock_run.call_args[0][0]
        assert cmd == ["git", "commit", "-m", msg]


class TestGitTagWithTimestamp:
    """Test git_tag_with_timestamp() from finalize_release.py."""

    def test_success_creates_tag(self, tmp_path: Path):
        """Successfully creates tag when no existing tag."""
        with patch("finalize_release.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=""),  # git tag -l (no existing)
                MagicMock(returncode=0, stdout=""),  # git tag -a
            ]
            result = git_tag_with_timestamp(tmp_path, "v0.1.0", "2026-01-04 00:00:00 +0000")

        assert result is True

    def test_existing_tag_without_force_returns_false(self, tmp_path: Path):
        """Existing tag without force=True returns False."""
        with patch("finalize_release.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="v0.1.0\n")
            result = git_tag_with_timestamp(tmp_path, "v0.1.0", "2026-01-04 00:00:00 +0000")

        assert result is False

    def test_existing_tag_with_force_deletes_and_recreates(self, tmp_path: Path):
        """Existing tag with force=True deletes and recreates."""
        with patch("finalize_release.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="v0.1.0\n"),  # tag exists
                MagicMock(returncode=0, stdout=""),  # git tag -d
                MagicMock(returncode=0, stdout=""),  # git tag -a
            ]
            result = git_tag_with_timestamp(tmp_path, "v0.1.0", "2026-01-04 00:00:00 +0000", force=True)

        assert result is True
        # Verify delete was called
        delete_call = mock_run.call_args_list[1]
        assert delete_call[0][0] == ["git", "tag", "-d", "v0.1.0"]

    def test_tag_failure_returns_false(self, tmp_path: Path):
        """git tag -a returning rc=1 returns False."""
        with patch("finalize_release.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=""),  # no existing tag
                MagicMock(returncode=1, stderr="error"),  # tag -a fails
            ]
            result = git_tag_with_timestamp(tmp_path, "v0.1.0", "2026-01-04 00:00:00 +0000")

        assert result is False

    def test_env_var_propagation(self, tmp_path: Path):
        """GIT_COMMITTER_DATE is set in subprocess env for tag creation."""
        git_ts = "2026-01-04 00:00:00 +0000"

        with patch("finalize_release.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=""),  # no existing
                MagicMock(returncode=0, stdout=""),  # tag -a
            ]
            git_tag_with_timestamp(tmp_path, "v0.1.0", git_ts)

        # The tag creation call is the second one
        tag_call = mock_run.call_args_list[1]
        env_arg = tag_call.kwargs.get("env") or tag_call[1].get("env")
        assert env_arg["GIT_COMMITTER_DATE"] == git_ts


class TestVerifyGitStatus:
    """Test verify_git_status() from finalize_release.py."""

    def test_no_git_dir_returns_false(self, tmp_path: Path):
        """tmp_path without .git directory returns False."""
        result = verify_git_status(tmp_path)

        assert result is False

    def test_staged_changes_detected(self, tmp_path: Path):
        """Staged changes (git diff --cached --quiet rc=1) returns True."""
        (tmp_path / ".git").mkdir()

        with patch("finalize_release.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0),  # git add -A
                MagicMock(returncode=1),  # git diff --cached --quiet (has changes)
            ]
            result = verify_git_status(tmp_path)

        assert result is True

    def test_clean_repo_returns_false(self, tmp_path: Path):
        """Clean repo (git diff --cached --quiet rc=0) returns False."""
        (tmp_path / ".git").mkdir()

        with patch("finalize_release.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0),  # git add -A
                MagicMock(returncode=0),  # git diff --cached --quiet (clean)
            ]
            result = verify_git_status(tmp_path)

        assert result is False

    def test_stages_before_diff(self, tmp_path: Path):
        """git add -A is called before git diff --cached --quiet."""
        (tmp_path / ".git").mkdir()

        with patch("finalize_release.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0),  # git add -A
                MagicMock(returncode=0),  # git diff --cached --quiet
            ]
            verify_git_status(tmp_path)

        calls = mock_run.call_args_list
        assert calls[0][0][0] == ["git", "add", "-A"]
        assert calls[1][0][0] == ["git", "diff", "--cached", "--quiet"]


class TestArchiveReleaseArtifacts:
    """Test archive_release_artifacts() from finalize_release.py."""

    def _setup_artifacts(self, tmp_path: Path) -> tuple[Path, Path]:
        """Helper: create fake wheel and sdist files."""
        wheel = tmp_path / "benchbox-0.1.0-py3-none-any.whl"
        sdist = tmp_path / "benchbox-0.1.0.tar.gz"
        wheel.write_bytes(b"fake wheel content")
        sdist.write_bytes(b"fake sdist content")
        return wheel, sdist

    def test_creates_archive_directory(self, tmp_path: Path):
        """archive_dir = archive_base/v{version} is created."""
        wheel, sdist = self._setup_artifacts(tmp_path)
        archive_base = tmp_path / "archives"

        archive_release_artifacts("0.1.0", wheel, sdist, archive_base)

        assert (archive_base / "v0.1.0").is_dir()

    def test_copies_wheel_and_sdist(self, tmp_path: Path):
        """Both files are present in archive directory after call."""
        wheel, sdist = self._setup_artifacts(tmp_path)
        archive_base = tmp_path / "archives"

        archive_release_artifacts("0.1.0", wheel, sdist, archive_base)

        archive_dir = archive_base / "v0.1.0"
        assert (archive_dir / wheel.name).exists()
        assert (archive_dir / sdist.name).exists()

    def test_manifest_content(self, tmp_path: Path):
        """MANIFEST.txt contains version, wheel name, sdist name, and shasum."""
        wheel, sdist = self._setup_artifacts(tmp_path)
        archive_base = tmp_path / "archives"

        archive_release_artifacts("0.1.0", wheel, sdist, archive_base)

        manifest = (archive_base / "v0.1.0" / "MANIFEST.txt").read_text()
        assert "0.1.0" in manifest
        assert wheel.name in manifest
        assert sdist.name in manifest
        assert "shasum" in manifest

    def test_returns_archive_path(self, tmp_path: Path):
        """Returned Path matches archive_base/v{version}."""
        wheel, sdist = self._setup_artifacts(tmp_path)
        archive_base = tmp_path / "archives"

        result = archive_release_artifacts("0.1.0", wheel, sdist, archive_base)

        assert result == archive_base / "v0.1.0"


class TestVerifySourceFingerprint:
    """Test verify_source_fingerprint() from finalize_release.py."""

    def test_matching_fingerprint_passes(self, tmp_path: Path):
        """Matching fingerprint in dist/.source_fingerprint passes."""
        from benchbox.release.workflow import compute_source_fingerprint

        # Create benchbox/ source tree
        pkg = tmp_path / "benchbox"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("version = '0.1.0'")

        # Compute and write fingerprint
        fp = compute_source_fingerprint(pkg)
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / ".source_fingerprint").write_text(fp + "\n")

        result = verify_source_fingerprint(tmp_path)

        assert result is True

    def test_mismatched_fingerprint_fails(self, tmp_path: Path):
        """Wrong fingerprint in dist/.source_fingerprint fails."""
        pkg = tmp_path / "benchbox"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("version = '0.1.0'")

        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / ".source_fingerprint").write_text("wrong" * 13 + "\n")

        result = verify_source_fingerprint(tmp_path)

        assert result is False

    def test_missing_fingerprint_file_fails(self, tmp_path: Path):
        """No dist/.source_fingerprint file returns False."""
        pkg = tmp_path / "benchbox"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("version = '0.1.0'")

        result = verify_source_fingerprint(tmp_path)

        assert result is False

    def test_skip_flag_returns_true(self, tmp_path: Path):
        """skip=True returns True regardless of file state."""
        result = verify_source_fingerprint(tmp_path, skip=True)

        assert result is True

    def test_reads_and_strips_fingerprint(self, tmp_path: Path):
        """Fingerprint file with trailing newline is handled correctly."""
        from benchbox.release.workflow import compute_source_fingerprint

        pkg = tmp_path / "benchbox"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("version = '0.1.0'")

        fp = compute_source_fingerprint(pkg)
        dist = tmp_path / "dist"
        dist.mkdir()
        # Write with extra whitespace/newlines
        (dist / ".source_fingerprint").write_text(f"  {fp}  \n\n")

        result = verify_source_fingerprint(tmp_path)

        assert result is True


# =============================================================================
# squash_commits and related helpers (automate_release.py)
# =============================================================================

import subprocess


def _init_git_repo(path: Path) -> None:
    """Helper: initialize a git repo with initial commit."""
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, capture_output=True, check=True)


def _git_commit(path: Path, message: str, filename: str | None = None) -> None:
    """Helper: create a file and commit it."""
    if filename:
        (path / filename).write_text(f"# {message}\n")
        subprocess.run(["git", "add", filename], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", message], cwd=path, capture_output=True, check=True)


def _get_commit_message(path: Path) -> str:
    """Helper: get HEAD commit message."""
    result = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=path, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _get_commit_count(path: Path) -> int:
    """Helper: count commits on current branch."""
    result = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], cwd=path, capture_output=True, text=True, check=True
    )
    return int(result.stdout.strip())


class TestCommitMessages:
    """Test release commit message generators."""

    def test_initial_message_contains_version(self):
        msg = _initial_release_commit_message("0.1.0")
        assert "Initial release v0.1.0" in msg

    def test_initial_message_contains_features(self):
        msg = _initial_release_commit_message("0.1.0")
        assert "TPC-H" in msg
        assert "DuckDB" in msg

    def test_initial_message_has_co_author(self):
        msg = _initial_release_commit_message("0.1.0")
        assert "Co-Authored-By:" in msg

    def test_incremental_message_contains_version(self):
        msg = _incremental_release_commit_message("0.1.2")
        assert "Incremental release v0.1.2" in msg

    def test_incremental_message_no_initial_prefix(self):
        msg = _incremental_release_commit_message("0.1.2")
        assert "Initial" not in msg

    def test_incremental_message_no_chore_prefix(self):
        msg = _incremental_release_commit_message("0.1.2")
        assert "chore" not in msg

    def test_incremental_message_has_co_author(self):
        msg = _incremental_release_commit_message("0.1.2")
        assert "Co-Authored-By:" in msg


class TestFindSquashAnchor:
    """Test _find_squash_anchor() detection logic."""

    def test_no_remote_no_tags_returns_none(self, tmp_path: Path):
        """Repo without tags or origin/main returns None (initial release)."""
        _init_git_repo(tmp_path)
        _git_commit(tmp_path, "first")

        assert _find_squash_anchor(tmp_path) is None

    def test_with_version_tag_returns_tag(self, tmp_path: Path):
        """Repo with a version tag uses the tag as anchor."""
        _init_git_repo(tmp_path)
        _git_commit(tmp_path, "initial", "file.txt")
        subprocess.run(["git", "tag", "v0.1.0"], cwd=tmp_path, capture_output=True, check=True)
        _git_commit(tmp_path, "second", "file2.txt")

        assert _find_squash_anchor(tmp_path) == "v0.1.0"

    def test_with_remote_no_tags_returns_origin(self, tmp_path: Path):
        """Repo with origin/main but no tags falls back to origin/main."""
        remote = tmp_path / "remote.git"
        remote.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=remote, capture_output=True, check=True)

        local = tmp_path / "local"
        local.mkdir()
        _init_git_repo(local)
        _git_commit(local, "initial", "file.txt")
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=local, capture_output=True, check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=local, capture_output=True, check=True)

        assert _find_squash_anchor(local) == "origin/main"

    def test_tag_preferred_over_remote(self, tmp_path: Path):
        """Version tag takes priority over origin/main."""
        remote = tmp_path / "remote.git"
        remote.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=remote, capture_output=True, check=True)

        local = tmp_path / "local"
        local.mkdir()
        _init_git_repo(local)
        _git_commit(local, "initial", "file.txt")
        subprocess.run(["git", "tag", "v0.1.0"], cwd=local, capture_output=True, check=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=local, capture_output=True, check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=local, capture_output=True, check=True)
        _git_commit(local, "second", "file2.txt")

        assert _find_squash_anchor(local) == "v0.1.0"


class TestSquashCommits:
    """Test squash_commits() with real git repos.

    Verifies both initial and incremental release squash behavior
    using temporary git repositories.
    """

    GIT_TS = "2026-01-15 00:00:00 +0000"

    def test_initial_squashes_all_into_one(self, tmp_path: Path):
        """Initial release (no remote): all commits squashed into one."""
        _init_git_repo(tmp_path)
        _git_commit(tmp_path, "first", "a.txt")
        _git_commit(tmp_path, "second", "b.txt")
        _git_commit(tmp_path, "third", "c.txt")
        assert _get_commit_count(tmp_path) == 3

        result = squash_commits(tmp_path, "0.1.0", self.GIT_TS)

        assert result is True
        assert _get_commit_count(tmp_path) == 1
        assert "Initial release v0.1.0" in _get_commit_message(tmp_path)

    def test_initial_single_commit_amends_message(self, tmp_path: Path):
        """Initial release with single commit: message is amended."""
        _init_git_repo(tmp_path)
        _git_commit(tmp_path, "prepare release", "a.txt")
        assert _get_commit_count(tmp_path) == 1

        result = squash_commits(tmp_path, "0.1.0", self.GIT_TS)

        assert result is True
        assert _get_commit_count(tmp_path) == 1
        assert "Initial release v0.1.0" in _get_commit_message(tmp_path)

    def test_incremental_amends_single_new_commit(self, tmp_path: Path):
        """Incremental release with 1 new commit: message amended, history preserved."""
        # Set up repo with remote
        remote = tmp_path / "remote.git"
        remote.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=remote, capture_output=True, check=True)

        local = tmp_path / "local"
        local.mkdir()
        _init_git_repo(local)
        _git_commit(local, "Initial Release v0.1.1", "a.txt")
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=local, capture_output=True, check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=local, capture_output=True, check=True)

        # Add one new commit (simulating finalize_release.py)
        _git_commit(local, "chore(release): prepare v0.1.2", "b.txt")
        assert _get_commit_count(local) == 2

        result = squash_commits(local, "0.1.2", self.GIT_TS)

        assert result is True
        assert _get_commit_count(local) == 2  # History preserved
        assert _get_commit_message(local) == "Incremental release v0.1.2"

    def test_incremental_squashes_multiple_new_commits(self, tmp_path: Path):
        """Incremental release with multiple new commits: squashed into one."""
        remote = tmp_path / "remote.git"
        remote.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=remote, capture_output=True, check=True)

        local = tmp_path / "local"
        local.mkdir()
        _init_git_repo(local)
        _git_commit(local, "Initial Release v0.1.0", "a.txt")
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=local, capture_output=True, check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=local, capture_output=True, check=True)

        # Add multiple new commits
        _git_commit(local, "fix: workflow", "b.txt")
        _git_commit(local, "chore(release): prepare v0.1.1", "c.txt")
        assert _get_commit_count(local) == 3

        result = squash_commits(local, "0.1.1", self.GIT_TS)

        assert result is True
        assert _get_commit_count(local) == 2  # 1 original + 1 squashed
        assert _get_commit_message(local) == "Incremental release v0.1.1"

    def test_incremental_no_new_commits_is_noop(self, tmp_path: Path):
        """Incremental release with no new commits returns True (noop)."""
        remote = tmp_path / "remote.git"
        remote.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=remote, capture_output=True, check=True)

        local = tmp_path / "local"
        local.mkdir()
        _init_git_repo(local)
        _git_commit(local, "Initial Release v0.1.0", "a.txt")
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=local, capture_output=True, check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=local, capture_output=True, check=True)

        # No new commits
        result = squash_commits(local, "0.1.1", self.GIT_TS)

        assert result is True
        assert _get_commit_count(local) == 1
        assert _get_commit_message(local) == "Initial Release v0.1.0"  # Unchanged

    def test_incremental_preserves_prior_commits(self, tmp_path: Path):
        """Incremental squash does not alter commits before origin/main."""
        remote = tmp_path / "remote.git"
        remote.mkdir()
        subprocess.run(["git", "init", "--bare"], cwd=remote, capture_output=True, check=True)

        local = tmp_path / "local"
        local.mkdir()
        _init_git_repo(local)
        _git_commit(local, "first release", "a.txt")
        _git_commit(local, "hotfix", "b.txt")
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=local, capture_output=True, check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=local, capture_output=True, check=True)

        # Get the SHA of origin/main before squash
        pre_sha = subprocess.run(
            ["git", "rev-parse", "origin/main"], cwd=local, capture_output=True, text=True, check=True
        ).stdout.strip()

        _git_commit(local, "chore(release): prepare v0.2.0", "c.txt")
        squash_commits(local, "0.2.0", self.GIT_TS)

        # Parent of HEAD should be the same as origin/main
        parent_sha = subprocess.run(
            ["git", "rev-parse", "HEAD~1"], cwd=local, capture_output=True, text=True, check=True
        ).stdout.strip()
        assert parent_sha == pre_sha

    def test_squash_normalizes_timestamps(self, tmp_path: Path):
        """Squashed commit (multi-commit case) has the normalized timestamp."""
        _init_git_repo(tmp_path)
        _git_commit(tmp_path, "first", "a.txt")
        _git_commit(tmp_path, "second", "b.txt")

        squash_commits(tmp_path, "0.1.0", self.GIT_TS)

        # Committer date is always set by the env var
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cI"], cwd=tmp_path, capture_output=True, text=True, check=True
        )
        assert "2026-01-15" in result.stdout
