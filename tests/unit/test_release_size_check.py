"""Tests for release size safety checks (check_release_size, ReleaseSizeViolation).

Verifies individual file size limits, total size limits, forbidden pattern detection,
allowed data path exemptions, and edge cases. All tests use tmp_path for filesystem
operations -- no real release directories needed.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path

import pytest

from benchbox.release.workflow import (
    ALLOWED_DATA_PATHS,
    DEFAULT_MAX_FILE_SIZE_MB,
    DEFAULT_MAX_TOTAL_SIZE_MB,
    FORBIDDEN_PATTERNS,
    ReleaseSizeViolation,
    check_release_size,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# =============================================================================
# ReleaseSizeViolation Tests
# =============================================================================
class TestReleaseSizeViolation:
    """Test ReleaseSizeViolation class."""

    def test_str_format_includes_path_size_reason(self):
        """__str__ includes path, size_mb, and reason."""
        v = ReleaseSizeViolation(Path("big.dat"), 10 * 1024 * 1024, "too big")
        s = str(v)
        assert "big.dat" in s
        assert "10.00" in s
        assert "too big" in s

    def test_size_mb_calculation(self):
        """size_mb correctly converts bytes to megabytes."""
        v = ReleaseSizeViolation(Path("f"), 5 * 1024 * 1024, "reason")
        assert v.size_mb == pytest.approx(5.0)

    def test_constructor_stores_fields(self):
        """Constructor stores path, size_bytes, and reason correctly."""
        p = Path("some/file.txt")
        v = ReleaseSizeViolation(p, 12345, "my reason")
        assert v.path == p
        assert v.size_bytes == 12345
        assert v.reason == "my reason"


# =============================================================================
# check_release_size Tests
# =============================================================================
class TestCheckReleaseSize:
    """Test check_release_size() function."""

    def test_clean_release_passes(self, tmp_path: Path):
        """Clean release directory with small files passes."""
        (tmp_path / "README.md").write_text("# Hello")
        (tmp_path / "setup.py").write_text("setup()")

        passed, violations, total_size_mb = check_release_size(tmp_path)

        assert passed is True
        assert violations == []
        assert total_size_mb > 0

    def test_oversized_individual_file_detected(self, tmp_path: Path):
        """Files exceeding max_file_size_mb are detected."""
        big_file = tmp_path / "big.bin"
        big_file.write_bytes(b"\x00" * (11 * 1024 * 1024))  # 11 MB

        passed, violations, _ = check_release_size(tmp_path)

        assert passed is False
        assert any("exceeds" in v.reason for v in violations)

    def test_exact_at_limit_passes(self, tmp_path: Path):
        """File exactly at the size limit passes."""
        limit_mb = 1.0
        exact = tmp_path / "exact.bin"
        exact.write_bytes(b"\x00" * int(limit_mb * 1024 * 1024))

        passed, violations, _ = check_release_size(tmp_path, max_file_size_mb=limit_mb)

        assert passed is True
        assert violations == []

    def test_one_byte_over_limit_fails(self, tmp_path: Path):
        """File one byte over the limit is flagged."""
        limit_mb = 1.0
        over = tmp_path / "over.bin"
        over.write_bytes(b"\x00" * (int(limit_mb * 1024 * 1024) + 1))

        passed, violations, _ = check_release_size(tmp_path, max_file_size_mb=limit_mb)

        assert passed is False
        assert len(violations) >= 1

    def test_total_size_violation_detected(self, tmp_path: Path):
        """Total size exceeding max_total_size_mb is detected."""
        # Create several small files that together exceed total limit
        for i in range(3):
            (tmp_path / f"file{i}.bin").write_bytes(b"\x00" * (1024 * 1024))  # 1 MB each

        passed, violations, total_mb = check_release_size(tmp_path, max_total_size_mb=2.0, max_file_size_mb=10.0)

        assert passed is False
        assert any("total size" in v.reason for v in violations)

    @pytest.mark.parametrize(
        "pattern",
        [
            "data.dat",
            "data.tbl",
            "data.csv",
            "data.parquet",
            "data.db",
            "data.duckdb",
        ],
    )
    def test_forbidden_pattern_detected(self, tmp_path: Path, pattern: str):
        """Each forbidden pattern is detected."""
        (tmp_path / pattern).write_bytes(b"\x00" * 100)

        passed, violations, _ = check_release_size(tmp_path)

        assert passed is False
        assert any("forbidden pattern" in v.reason for v in violations)

    def test_allowed_data_path_exemption(self, tmp_path: Path):
        """Files under ALLOWED_DATA_PATHS are not flagged for forbidden patterns."""
        allowed_path = tmp_path / ALLOWED_DATA_PATHS[0]
        allowed_path.mkdir(parents=True, exist_ok=True)
        (allowed_path / "sample.csv").write_bytes(b"col1,col2\n1,2\n")

        passed, violations, _ = check_release_size(tmp_path)

        assert passed is True
        assert violations == []

    def test_custom_max_file_size_mb(self, tmp_path: Path):
        """Custom max_file_size_mb parameter is honored."""
        (tmp_path / "small.bin").write_bytes(b"\x00" * (2 * 1024 * 1024))  # 2 MB

        # Default limit (10MB) - should pass
        passed1, _, _ = check_release_size(tmp_path)
        assert passed1 is True

        # Custom limit (1MB) - should fail
        passed2, violations, _ = check_release_size(tmp_path, max_file_size_mb=1.0)
        assert passed2 is False
        assert len(violations) >= 1

    def test_custom_max_total_size_mb(self, tmp_path: Path):
        """Custom max_total_size_mb parameter is honored."""
        (tmp_path / "file.bin").write_bytes(b"\x00" * (2 * 1024 * 1024))  # 2 MB

        passed, violations, _ = check_release_size(tmp_path, max_total_size_mb=1.0)

        assert passed is False
        assert any("total size" in v.reason for v in violations)

    def test_git_directory_excluded(self, tmp_path: Path):
        """Files in .git/ directory are excluded from size calculations."""
        git_dir = tmp_path / ".git" / "objects"
        git_dir.mkdir(parents=True)
        (git_dir / "huge_pack.bin").write_bytes(b"\x00" * (20 * 1024 * 1024))

        passed, violations, total_mb = check_release_size(tmp_path)

        assert passed is True
        assert total_mb < 1.0  # .git contents not counted

    def test_empty_release_directory_passes(self, tmp_path: Path):
        """Empty release directory passes all checks."""
        passed, violations, total_mb = check_release_size(tmp_path)

        assert passed is True
        assert violations == []
        assert total_mb == 0.0

    def test_nested_forbidden_files_detected(self, tmp_path: Path):
        """Forbidden files in nested directories are detected."""
        deep = tmp_path / "deep" / "path"
        deep.mkdir(parents=True)
        (deep / "data.dat").write_bytes(b"\x00" * 100)

        passed, violations, _ = check_release_size(tmp_path)

        assert passed is False
        assert any("forbidden pattern" in v.reason for v in violations)

    def test_multiple_violations_returned(self, tmp_path: Path):
        """Multiple violations are returned in a single check."""
        (tmp_path / "bad1.dat").write_bytes(b"\x00" * 100)
        (tmp_path / "bad2.tbl").write_bytes(b"\x00" * 100)
        (tmp_path / "bad3.csv").write_bytes(b"\x00" * 100)

        passed, violations, _ = check_release_size(tmp_path)

        assert passed is False
        assert len(violations) >= 3

    def test_check_forbidden_patterns_false_disables(self, tmp_path: Path):
        """check_forbidden_patterns=False disables pattern checks."""
        (tmp_path / "data.dat").write_bytes(b"\x00" * 100)

        passed, violations, _ = check_release_size(tmp_path, check_forbidden_patterns=False)

        assert passed is True
        assert violations == []

    def test_total_violation_inserted_at_index_zero(self, tmp_path: Path):
        """Total size violation is inserted at index 0 of violations list."""
        # Create a forbidden file AND exceed total size
        (tmp_path / "data.dat").write_bytes(b"\x00" * (2 * 1024 * 1024))

        passed, violations, _ = check_release_size(tmp_path, max_total_size_mb=1.0, max_file_size_mb=100.0)

        assert passed is False
        assert len(violations) >= 2  # forbidden + total
        assert "total size" in violations[0].reason

    def test_returns_three_tuple(self, tmp_path: Path):
        """check_release_size returns a 3-tuple of (bool, list, float)."""
        result = check_release_size(tmp_path)

        assert isinstance(result, tuple)
        assert len(result) == 3
        passed, violations, total_mb = result
        assert isinstance(passed, bool)
        assert isinstance(violations, list)
        assert isinstance(total_mb, float)

    def test_constants_have_expected_values(self):
        """Verify constants have expected default values."""
        assert DEFAULT_MAX_FILE_SIZE_MB == 10
        assert DEFAULT_MAX_TOTAL_SIZE_MB == 100
        assert "*.dat" in FORBIDDEN_PATTERNS
        assert "*.tbl" in FORBIDDEN_PATTERNS
        assert "*.csv" in FORBIDDEN_PATTERNS
        assert "*.parquet" in FORBIDDEN_PATTERNS
        assert "*.db" in FORBIDDEN_PATTERNS
        assert "*.duckdb" in FORBIDDEN_PATTERNS
        assert "benchbox/data/coffeeshop" in ALLOWED_DATA_PATHS
