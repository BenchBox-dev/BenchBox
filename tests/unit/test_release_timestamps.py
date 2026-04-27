"""Tests for timestamp normalization functions.

Verifies calculate_release_timestamp() and _normalize_timestamps()
for correctness, determinism, and edge cases.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from benchbox.release.workflow import (
    _normalize_timestamps,
    calculate_release_timestamp,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestCalculateReleaseTimestamp:
    """Test calculate_release_timestamp() function."""

    def test_returns_correct_tuple_structure(self):
        """Returns a 3-tuple of (int, str, str)."""
        result = calculate_release_timestamp()

        assert isinstance(result, tuple)
        assert len(result) == 3
        unix_ts, iso_fmt, git_fmt = result
        assert isinstance(unix_ts, int)
        assert isinstance(iso_fmt, str)
        assert isinstance(git_fmt, str)

    def test_always_returns_whole_hour(self):
        """Result is always truncated to the top of the hour."""
        unix_ts, _, _ = calculate_release_timestamp()
        dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
        assert dt.minute == 0
        assert dt.second == 0
        assert dt.microsecond == 0

    def test_format_consistency_iso(self):
        """ISO format string is consistent with the unix timestamp."""
        unix_ts, iso_fmt, _ = calculate_release_timestamp()
        dt_from_iso = datetime.fromisoformat(iso_fmt)
        assert int(dt_from_iso.timestamp()) == unix_ts

    def test_format_consistency_git(self):
        """Git format string is consistent with the unix timestamp."""
        unix_ts, _, git_fmt = calculate_release_timestamp()
        dt_from_git = datetime.strptime(git_fmt, "%Y-%m-%d %H:%M:%S %z")
        assert int(dt_from_git.timestamp()) == unix_ts

    def test_result_is_in_the_past_or_present(self):
        """Result timestamp is never in the future."""
        unix_ts, _, _ = calculate_release_timestamp()
        now_ts = int(datetime.now(timezone.utc).timestamp())
        assert unix_ts <= now_ts

    def test_result_is_within_one_hour(self):
        """Result is always within one hour of now."""
        unix_ts, _, _ = calculate_release_timestamp()
        now_ts = int(datetime.now(timezone.utc).timestamp())
        assert (now_ts - unix_ts) < 3600

    @pytest.mark.parametrize(
        "label,hour,minute,second",
        [
            ("start of hour", 14, 0, 0),
            ("mid hour", 14, 30, 0),
            ("just before next hour", 14, 59, 59),
            ("with seconds", 9, 12, 45),
            ("midnight sharp", 0, 0, 0),
            ("end of day", 23, 59, 59),
        ],
    )
    def test_parametrized_times(self, label, hour, minute, second):
        """Various times within an hour all truncate to the same whole hour."""
        mock_now = datetime(2025, 1, 7, hour, minute, second, tzinfo=timezone.utc)

        with patch("benchbox.release.workflow.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            unix_ts, _, _ = calculate_release_timestamp()

        result_dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
        assert result_dt.hour == hour, f"For {label}, expected hour {hour}"
        assert result_dt.minute == 0
        assert result_dt.second == 0

    def test_boundary_just_after_hour(self):
        """At 14:00:01, returns 14:00:00 (this hour)."""
        mock_now = datetime(2025, 1, 7, 14, 0, 1, tzinfo=timezone.utc)

        with patch("benchbox.release.workflow.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            unix_ts, _, _ = calculate_release_timestamp()

        result_dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
        assert result_dt.hour == 14
        assert result_dt.minute == 0
        assert result_dt.second == 0


class TestNormalizeTimestamps:
    """Test _normalize_timestamps() function."""

    def test_sets_mtime_and_atime(self, tmp_path: Path):
        """Sets both mtime and atime on files."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        target_ts = 1700000000
        _normalize_timestamps(tmp_path, target_ts)

        stat = test_file.stat()
        assert stat.st_mtime == target_ts
        assert stat.st_atime == target_ts

    def test_normalizes_root_dir(self, tmp_path: Path):
        """The root directory itself gets normalized timestamps."""
        (tmp_path / "file.txt").write_text("content")

        target_ts = 1700000000
        _normalize_timestamps(tmp_path, target_ts)

        stat = tmp_path.stat()
        assert stat.st_mtime == target_ts

    def test_normalizes_nested_files(self, tmp_path: Path):
        """Files in nested directories get normalized."""
        sub = tmp_path / "sub" / "deep"
        sub.mkdir(parents=True)
        nested_file = sub / "nested.py"
        nested_file.write_text("# nested")

        target_ts = 1700000000
        _normalize_timestamps(tmp_path, target_ts)

        assert nested_file.stat().st_mtime == target_ts
        assert sub.stat().st_mtime == target_ts

    def test_normalizes_empty_dirs(self, tmp_path: Path):
        """Empty subdirectories get normalized."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        target_ts = 1700000000
        _normalize_timestamps(tmp_path, target_ts)

        assert empty_dir.stat().st_mtime == target_ts

    def test_idempotency(self, tmp_path: Path):
        """Running normalization twice with same timestamp produces same result."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        target_ts = 1700000000
        _normalize_timestamps(tmp_path, target_ts)
        stat1_mtime = test_file.stat().st_mtime

        _normalize_timestamps(tmp_path, target_ts)
        stat2_mtime = test_file.stat().st_mtime

        assert stat1_mtime == stat2_mtime

    def test_multiple_files(self, tmp_path: Path):
        """All files in a directory tree get the same timestamp."""
        (tmp_path / "a.py").write_text("# a")
        (tmp_path / "b.py").write_text("# b")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "c.py").write_text("# c")

        target_ts = 1700000000
        _normalize_timestamps(tmp_path, target_ts)

        for f in tmp_path.rglob("*"):
            assert f.stat().st_mtime == target_ts, f"Mismatch on {f}"

    def test_different_timestamps(self, tmp_path: Path):
        """Different target timestamps produce different results."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        _normalize_timestamps(tmp_path, 1700000000)
        assert test_file.stat().st_mtime == 1700000000

        _normalize_timestamps(tmp_path, 1800000000)
        assert test_file.stat().st_mtime == 1800000000
