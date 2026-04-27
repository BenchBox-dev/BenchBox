"""Tests for source fingerprinting (compute_source_fingerprint).

Verifies determinism, content sensitivity, file filtering, path normalization,
and edge cases for the fingerprint function that prevents source/artifact divergence.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import os
import re
from pathlib import Path

import pytest

from benchbox.release.workflow import compute_source_fingerprint

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestComputeSourceFingerprint:
    """Test compute_source_fingerprint() function."""

    def test_deterministic_same_content(self, tmp_path: Path):
        """Fingerprint is deterministic for identical content."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("# init")
        (pkg / "core.py").write_text("def main(): pass")

        fp1 = compute_source_fingerprint(pkg)
        fp2 = compute_source_fingerprint(pkg)

        assert fp1 == fp2

    def test_content_sensitivity(self, tmp_path: Path):
        """Changing file content changes the fingerprint."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("# version 1")

        fp1 = compute_source_fingerprint(pkg)

        (pkg / "__init__.py").write_text("# version 2")
        fp2 = compute_source_fingerprint(pkg)

        assert fp1 != fp2

    def test_adding_file_changes_fingerprint(self, tmp_path: Path):
        """Adding a new .py file changes the fingerprint."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("# init")

        fp1 = compute_source_fingerprint(pkg)

        (pkg / "new_module.py").write_text("# new")
        fp2 = compute_source_fingerprint(pkg)

        assert fp1 != fp2

    def test_ignores_non_py_files(self, tmp_path: Path):
        """Non-.py files do not affect the fingerprint."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("# init")

        fp1 = compute_source_fingerprint(pkg)

        (pkg / "README.md").write_text("readme")
        (pkg / "data.json").write_text("{}")
        (pkg / "config.yaml").write_text("key: value")
        fp2 = compute_source_fingerprint(pkg)

        assert fp1 == fp2

    def test_empty_directory(self, tmp_path: Path):
        """Empty directory produces a valid fingerprint (hash of empty input)."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()

        fp = compute_source_fingerprint(pkg)

        assert isinstance(fp, str)
        assert len(fp) == 64

    def test_nested_packages(self, tmp_path: Path):
        """Fingerprint includes files from nested subdirectories."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("# top")
        sub = pkg / "sub"
        sub.mkdir()
        (sub / "__init__.py").write_text("# sub")
        (sub / "module.py").write_text("def foo(): pass")

        fp1 = compute_source_fingerprint(pkg)

        # Modify a nested file
        (sub / "module.py").write_text("def foo(): return 42")
        fp2 = compute_source_fingerprint(pkg)

        assert fp1 != fp2

    def test_uses_posix_paths(self, tmp_path: Path):
        """Fingerprint is deterministic regardless of OS path separator."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()
        (sub / "module.py").write_text("# module")

        # The function uses .as_posix() internally, so the fingerprint
        # is consistent cross-platform. Verify determinism as a proxy.
        fp1 = compute_source_fingerprint(pkg)
        fp2 = compute_source_fingerprint(pkg)
        assert fp1 == fp2

    def test_ignores_timestamps(self, tmp_path: Path):
        """File timestamps do not affect the fingerprint."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        py_file = pkg / "__init__.py"
        py_file.write_text("# init")

        fp1 = compute_source_fingerprint(pkg)

        os.utime(py_file, (1000000, 1000000))
        fp2 = compute_source_fingerprint(pkg)

        assert fp1 == fp2

    def test_symlinks_followed(self, tmp_path: Path):
        """Symlinked .py files are included via rglob."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("# init")

        external = tmp_path / "external.py"
        external.write_text("# external module")

        try:
            (pkg / "linked.py").symlink_to(external)
        except OSError:
            pytest.skip("Symlinks not supported on this system")

        fp_with_link = compute_source_fingerprint(pkg)

        (pkg / "linked.py").unlink()
        fp_without_link = compute_source_fingerprint(pkg)

        assert fp_with_link != fp_without_link

    def test_file_ordering_deterministic(self, tmp_path: Path):
        """Fingerprint is consistent regardless of file creation order."""
        pkg1 = tmp_path / "pkg1"
        pkg1.mkdir()
        (pkg1 / "a.py").write_text("# a")
        (pkg1 / "b.py").write_text("# b")
        (pkg1 / "c.py").write_text("# c")

        pkg2 = tmp_path / "pkg2"
        pkg2.mkdir()
        (pkg2 / "c.py").write_text("# c")
        (pkg2 / "a.py").write_text("# a")
        (pkg2 / "b.py").write_text("# b")

        fp1 = compute_source_fingerprint(pkg1)
        fp2 = compute_source_fingerprint(pkg2)

        assert fp1 == fp2

    def test_different_content_different_fingerprint(self, tmp_path: Path):
        """Two packages with different content produce different fingerprints."""
        pkg1 = tmp_path / "pkg1"
        pkg1.mkdir()
        (pkg1 / "__init__.py").write_text("version = '1.0'")

        pkg2 = tmp_path / "pkg2"
        pkg2.mkdir()
        (pkg2 / "__init__.py").write_text("version = '2.0'")

        fp1 = compute_source_fingerprint(pkg1)
        fp2 = compute_source_fingerprint(pkg2)

        assert fp1 != fp2

    def test_path_sensitivity(self, tmp_path: Path):
        """Files at different relative paths produce different fingerprints even with same content."""
        pkg1 = tmp_path / "pkg1"
        pkg1.mkdir()
        (pkg1 / "module_a.py").write_text("# same content")

        pkg2 = tmp_path / "pkg2"
        pkg2.mkdir()
        (pkg2 / "module_b.py").write_text("# same content")

        fp1 = compute_source_fingerprint(pkg1)
        fp2 = compute_source_fingerprint(pkg2)

        assert fp1 != fp2

    def test_sha256_hex_format(self, tmp_path: Path):
        """Result is always a 64-char lowercase hex string."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("# test")

        fp = compute_source_fingerprint(pkg)

        assert len(fp) == 64
        assert re.match(r"^[0-9a-f]{64}$", fp)
