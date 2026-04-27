"""Tests for TPC binary auto-compilation utilities.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import hashlib
import os
import platform
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from benchbox.utils.tpc_compilation import (
    BinaryInfo,
    CompilationResult,
    CompilationStatus,
    TPCCompiler,
    _discover_tpc_paths,
    ensure_tpc_binaries,
    get_precompiled_bundle_root,
    get_tpc_compiler,
    get_tpc_templates_dir,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# ---------------------------------------------------------------------------
# Dataclass and Enum tests
# ---------------------------------------------------------------------------
class TestCompilationStatus:
    """Tests for CompilationStatus enum."""

    def test_all_statuses_exist(self):
        assert CompilationStatus.SUCCESS.value == "success"
        assert CompilationStatus.FAILED.value == "failed"
        assert CompilationStatus.SKIPPED.value == "skipped"
        assert CompilationStatus.DISABLED.value == "disabled"
        assert CompilationStatus.NOT_NEEDED.value == "not_needed"
        assert CompilationStatus.PRECOMPILED.value == "precompiled"


class TestBinaryInfo:
    """Tests for BinaryInfo dataclass."""

    def test_defaults(self):
        info = BinaryInfo(name="dbgen", source_dir=Path("/src"), binary_path=Path("/bin/dbgen"))
        assert info.name == "dbgen"
        assert info.precompiled_path is None
        assert info.makefile_path is None
        assert info.dependencies == []

    def test_post_init_none_dependencies(self):
        info = BinaryInfo(name="qgen", source_dir=Path("/src"), binary_path=Path("/bin/qgen"), dependencies=None)
        assert info.dependencies == []

    def test_explicit_dependencies(self):
        info = BinaryInfo(
            name="dsdgen",
            source_dir=Path("/src"),
            binary_path=Path("/bin/dsdgen"),
            dependencies=["gcc", "make"],
        )
        assert info.dependencies == ["gcc", "make"]


class TestCompilationResult:
    """Tests for CompilationResult dataclass."""

    def test_result_fields(self):
        result = CompilationResult(
            binary_name="dbgen",
            status=CompilationStatus.SUCCESS,
            binary_path=Path("/bin/dbgen"),
            compilation_time=1.5,
            stdout="ok",
            stderr="",
        )
        assert result.binary_name == "dbgen"
        assert result.status == CompilationStatus.SUCCESS
        assert result.binary_path == Path("/bin/dbgen")
        assert result.compilation_time == 1.5
        assert result.stdout == "ok"
        assert result.stderr == ""
        assert result.error_message is None


# ---------------------------------------------------------------------------
# Platform string detection
# ---------------------------------------------------------------------------
class TestPlatformString:
    """Tests for TPCCompiler._get_platform_string."""

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("platform.system", return_value="Darwin")
    @patch("platform.machine", return_value="arm64")
    def test_darwin_arm64(self, _mock_machine, _mock_system):
        compiler = TPCCompiler(auto_compile=False)
        assert compiler._get_platform_string() == "darwin-arm64"

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("platform.system", return_value="Linux")
    @patch("platform.machine", return_value="x86_64")
    def test_linux_x86_64(self, _mock_machine, _mock_system):
        compiler = TPCCompiler(auto_compile=False)
        assert compiler._get_platform_string() == "linux-x86_64"

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("platform.system", return_value="Linux")
    @patch("platform.machine", return_value="amd64")
    def test_amd64_normalized_to_x86_64(self, _mock_machine, _mock_system):
        compiler = TPCCompiler(auto_compile=False)
        assert compiler._get_platform_string() == "linux-x86_64"

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("platform.system", return_value="Linux")
    @patch("platform.machine", return_value="aarch64")
    def test_aarch64_normalized_to_arm64(self, _mock_machine, _mock_system):
        compiler = TPCCompiler(auto_compile=False)
        assert compiler._get_platform_string() == "linux-arm64"

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("platform.system", return_value="Windows")
    @patch("platform.machine", return_value="x86_64")
    def test_windows_platform(self, _mock_machine, _mock_system):
        compiler = TPCCompiler(auto_compile=False)
        assert compiler._get_platform_string() == "windows-x86_64"

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("platform.system", return_value="FreeBSD")
    @patch("platform.machine", return_value="riscv64")
    def test_unknown_platform_and_arch(self, _mock_machine, _mock_system):
        compiler = TPCCompiler(auto_compile=False)
        assert compiler._get_platform_string() == "freebsd-riscv64"


# ---------------------------------------------------------------------------
# Binary configs setup
# ---------------------------------------------------------------------------
class TestBinaryConfigSetup:
    """Tests for _setup_binary_configs."""

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_binaries_with_precompiled_base(self, tmp_path):
        """When precompiled_base exists, all 4 binaries should be registered."""
        # Create fake directory structure
        precompiled_base = tmp_path / "_binaries"
        precompiled_base.mkdir()

        with patch.object(TPCCompiler, "__init__", lambda self, **kw: None):
            compiler = TPCCompiler.__new__(TPCCompiler)
            compiler.auto_compile = False
            compiler.verbose = False
            compiler.tpc_h_source = None
            compiler.tpc_ds_source = None
            compiler.precompiled_base = precompiled_base
            compiler._setup_binary_configs()

        assert "dbgen" in compiler.binaries
        assert "qgen" in compiler.binaries
        assert "dsdgen" in compiler.binaries
        assert "dsqgen" in compiler.binaries

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_binaries_without_sources_or_precompiled(self):
        """When nothing exists, binaries dict should be empty."""
        with patch.object(TPCCompiler, "__init__", lambda self, **kw: None):
            compiler = TPCCompiler.__new__(TPCCompiler)
            compiler.auto_compile = False
            compiler.verbose = False
            compiler.tpc_h_source = None
            compiler.tpc_ds_source = None
            compiler.precompiled_base = None
            compiler._setup_binary_configs()

        assert len(compiler.binaries) == 0


# ---------------------------------------------------------------------------
# Checksum verification
# ---------------------------------------------------------------------------
class TestChecksumVerification:
    """Tests for _verify_checksum."""

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("benchbox.utils.tpc_compilation._checksum_cache", {})
    def test_valid_checksum(self, tmp_path):
        """Test checksum verification with matching hash."""
        binary = tmp_path / "dbgen"
        binary.write_bytes(b"hello world")
        expected_md5 = hashlib.md5(b"hello world").hexdigest()

        checksum_file = tmp_path / "checksums.md5"
        checksum_file.write_text(f"{expected_md5}  dbgen\n")

        compiler = TPCCompiler(auto_compile=False)
        assert compiler._verify_checksum(binary) is True

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("benchbox.utils.tpc_compilation._checksum_cache", {})
    def test_invalid_checksum(self, tmp_path):
        """Test checksum verification with mismatched hash."""
        binary = tmp_path / "dbgen"
        binary.write_bytes(b"hello world")

        checksum_file = tmp_path / "checksums.md5"
        checksum_file.write_text("deadbeef12345678deadbeef12345678  dbgen\n")

        compiler = TPCCompiler(auto_compile=False)
        assert compiler._verify_checksum(binary) is False

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("benchbox.utils.tpc_compilation._checksum_cache", {})
    def test_no_checksum_file(self, tmp_path):
        """No checksum file means assume valid."""
        binary = tmp_path / "dbgen"
        binary.write_bytes(b"content")

        compiler = TPCCompiler(auto_compile=False)
        assert compiler._verify_checksum(binary) is True

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("benchbox.utils.tpc_compilation._checksum_cache", {})
    def test_binary_not_in_checksum_file(self, tmp_path):
        """Binary not listed in checksum file means assume valid."""
        binary = tmp_path / "qgen"
        binary.write_bytes(b"content")

        checksum_file = tmp_path / "checksums.md5"
        checksum_file.write_text("abc123  other_binary\n")

        compiler = TPCCompiler(auto_compile=False)
        assert compiler._verify_checksum(binary) is True

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("benchbox.utils.tpc_compilation._checksum_cache", {})
    def test_nonexistent_binary(self, tmp_path):
        """Non-existent binary returns False."""
        binary = tmp_path / "nonexistent"

        compiler = TPCCompiler(auto_compile=False)
        assert compiler._verify_checksum(binary) is False

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("benchbox.utils.tpc_compilation._checksum_cache", {})
    def test_checksum_with_dotslash_prefix(self, tmp_path):
        """Handle checksums.md5 with ./ prefix on filenames."""
        binary = tmp_path / "dbgen"
        binary.write_bytes(b"data")
        expected_md5 = hashlib.md5(b"data").hexdigest()

        checksum_file = tmp_path / "checksums.md5"
        checksum_file.write_text(f"{expected_md5}  ./dbgen\n")

        compiler = TPCCompiler(auto_compile=False)
        assert compiler._verify_checksum(binary) is True

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("benchbox.utils.tpc_compilation._checksum_cache", {})
    def test_checksum_caching(self, tmp_path):
        """Results are cached so second call doesn't re-read."""
        binary = tmp_path / "dbgen"
        binary.write_bytes(b"data")

        compiler = TPCCompiler(auto_compile=False)
        # First call - no checksum file, returns True
        result1 = compiler._verify_checksum(binary)
        assert result1 is True

        # Second call - should use cache
        result2 = compiler._verify_checksum(binary)
        assert result2 is True


# ---------------------------------------------------------------------------
# Dependency checking
# ---------------------------------------------------------------------------
class TestCheckDependencies:
    """Tests for check_dependencies."""

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_unknown_binary(self):
        compiler = TPCCompiler(auto_compile=False)
        available, missing = compiler.check_dependencies("unknown_binary")
        assert available is False
        assert "Unknown binary: unknown_binary" in missing

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("shutil.which")
    def test_all_dependencies_present(self, mock_which, tmp_path):
        """When all deps are present, returns (True, [])."""
        mock_which.return_value = "/usr/bin/gcc"

        precompiled_base = tmp_path / "_binaries"
        precompiled_base.mkdir()

        with patch.object(TPCCompiler, "__init__", lambda self, **kw: None):
            compiler = TPCCompiler.__new__(TPCCompiler)
            compiler.auto_compile = False
            compiler.verbose = False
            compiler.tpc_h_source = tmp_path
            compiler.tpc_ds_source = None
            compiler.precompiled_base = precompiled_base
            compiler._setup_binary_configs()

        available, missing = compiler.check_dependencies("dbgen")
        assert available is True
        assert missing == []

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("shutil.which", return_value=None)
    def test_missing_dependencies(self, mock_which, tmp_path):
        """When deps are missing, returns (False, [...])."""
        precompiled_base = tmp_path / "_binaries"
        precompiled_base.mkdir()

        with patch.object(TPCCompiler, "__init__", lambda self, **kw: None):
            compiler = TPCCompiler.__new__(TPCCompiler)
            compiler.auto_compile = False
            compiler.verbose = False
            compiler.tpc_h_source = tmp_path
            compiler.tpc_ds_source = None
            compiler.precompiled_base = precompiled_base
            compiler._setup_binary_configs()

        available, missing = compiler.check_dependencies("dbgen")
        assert available is False
        assert "gcc" in missing
        assert "make" in missing


# ---------------------------------------------------------------------------
# Binary availability checks
# ---------------------------------------------------------------------------
class TestBinaryAvailability:
    """Tests for is_binary_available and related methods."""

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_is_binary_available_unknown(self):
        compiler = TPCCompiler(auto_compile=False)
        assert compiler.is_binary_available("unknown") is False

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_is_precompiled_available_unknown(self):
        compiler = TPCCompiler(auto_compile=False)
        assert compiler.is_precompiled_available("unknown") is False

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_get_binary_path_unknown(self):
        compiler = TPCCompiler(auto_compile=False)
        assert compiler.get_binary_path("unknown") is None

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_needs_compilation_unknown(self):
        compiler = TPCCompiler(auto_compile=False)
        assert compiler.needs_compilation("unknown") is False

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("benchbox.utils.tpc_compilation._checksum_cache", {})
    def test_precompiled_available_with_executable(self, tmp_path):
        """Precompiled binary that exists and is executable returns True."""
        precompiled_base = tmp_path / "_binaries"
        platform_dir = precompiled_base / "tpc-h" / "darwin-arm64"
        platform_dir.mkdir(parents=True)
        dbgen = platform_dir / "dbgen"
        dbgen.write_bytes(b"fake binary")
        dbgen.chmod(0o755)

        with patch.object(TPCCompiler, "__init__", lambda self, **kw: None):
            compiler = TPCCompiler.__new__(TPCCompiler)
            compiler.auto_compile = False
            compiler.verbose = False
            compiler.tpc_h_source = None
            compiler.tpc_ds_source = None
            compiler.precompiled_base = precompiled_base
            compiler._setup_binary_configs()

        # Manually set the precompiled_path to our test binary
        compiler.binaries["dbgen"].precompiled_path = dbgen

        assert compiler.is_precompiled_available("dbgen") is True
        assert compiler.is_binary_available("dbgen") is True
        assert compiler.get_binary_path("dbgen") == dbgen


# ---------------------------------------------------------------------------
# Compilation disabled / unknown
# ---------------------------------------------------------------------------
class TestCompileBinary:
    """Tests for compile_binary."""

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_compile_disabled(self):
        compiler = TPCCompiler(auto_compile=False)
        result = compiler.compile_binary("dbgen")
        assert result.status == CompilationStatus.DISABLED
        assert "disabled" in result.error_message.lower()

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_compile_unknown_binary(self):
        compiler = TPCCompiler(auto_compile=True)
        result = compiler.compile_binary("unknown_binary")
        assert result.status == CompilationStatus.FAILED
        assert "Unknown binary" in result.error_message

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("benchbox.utils.tpc_compilation._checksum_cache", {})
    def test_compile_returns_precompiled_when_available(self, tmp_path):
        """When precompiled exists, compile_binary returns PRECOMPILED status."""
        precompiled_base = tmp_path / "_binaries"
        platform_dir = precompiled_base / "tpc-h" / "test-arch"
        platform_dir.mkdir(parents=True)
        dbgen = platform_dir / "dbgen"
        dbgen.write_bytes(b"fake binary")
        dbgen.chmod(0o755)

        with patch.object(TPCCompiler, "__init__", lambda self, **kw: None):
            compiler = TPCCompiler.__new__(TPCCompiler)
            compiler.auto_compile = True
            compiler.verbose = False
            compiler.tpc_h_source = None
            compiler.tpc_ds_source = None
            compiler.precompiled_base = precompiled_base
            compiler._setup_binary_configs()
            compiler.binaries["dbgen"].precompiled_path = dbgen

        result = compiler.compile_binary("dbgen")
        assert result.status == CompilationStatus.PRECOMPILED
        assert result.binary_path == dbgen


# ---------------------------------------------------------------------------
# Makefile generation
# ---------------------------------------------------------------------------
class TestMakefileGeneration:
    """Tests for _create_tpc_h_makefile."""

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("platform.system", return_value="Linux")
    def test_linux_makefile(self, _mock_sys, tmp_path):
        compiler = TPCCompiler(auto_compile=False)
        makefile_path = tmp_path / "Makefile.auto"
        compiler._create_tpc_h_makefile(makefile_path)

        content = makefile_path.read_text()
        assert "LINUX" in content
        assert "ORACLE" in content
        assert "Platform: linux" in content

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("platform.system", return_value="Darwin")
    def test_darwin_makefile(self, _mock_sys, tmp_path):
        compiler = TPCCompiler(auto_compile=False)
        makefile_path = tmp_path / "Makefile.auto"
        compiler._create_tpc_h_makefile(makefile_path)

        content = makefile_path.read_text()
        assert "MACOS_COMPAT" in content
        assert "Platform: darwin" in content

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("platform.system", return_value="Windows")
    def test_windows_makefile(self, _mock_sys, tmp_path):
        compiler = TPCCompiler(auto_compile=False)
        makefile_path = tmp_path / "Makefile.auto"
        compiler._create_tpc_h_makefile(makefile_path)

        content = makefile_path.read_text()
        assert "WIN32" in content
        assert "SQLSERVER" in content
        assert "Platform: windows" in content

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("platform.system", return_value="SomeOS")
    def test_unknown_platform_makefile(self, _mock_sys, tmp_path):
        compiler = TPCCompiler(auto_compile=False)
        makefile_path = tmp_path / "Makefile.auto"
        compiler._create_tpc_h_makefile(makefile_path)

        content = makefile_path.read_text()
        # Default to LINUX
        assert "LINUX" in content


# ---------------------------------------------------------------------------
# macOS patches
# ---------------------------------------------------------------------------
class TestMacOSPatches:
    """Tests for _apply_macos_patches."""

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_patches_malloc_h(self, tmp_path):
        """malloc.h include is replaced with stdlib.h."""
        source_dir = tmp_path / "dbgen"
        source_dir.mkdir()
        bm_utils = source_dir / "bm_utils.c"
        bm_utils.write_text("#include <malloc.h>\nint main() { return 0; }\n")

        compiler = TPCCompiler(auto_compile=False)
        compiler._apply_macos_patches(source_dir)

        patched = bm_utils.read_text()
        assert "#include <stdlib.h>" in patched
        assert "#include <malloc.h>" not in patched

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_already_patched_file(self, tmp_path):
        """Already-patched files are not modified."""
        source_dir = tmp_path / "dbgen"
        source_dir.mkdir()
        bm_utils = source_dir / "bm_utils.c"
        bm_utils.write_text("#include <stdlib.h>\nint main() { return 0; }\n")

        compiler = TPCCompiler(auto_compile=False)
        compiler._apply_macos_patches(source_dir)

        patched = bm_utils.read_text()
        assert "#include <stdlib.h>" in patched
        # No malloc.h was present, so nothing should change
        assert patched.count("#include <stdlib.h>") == 1

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_compat_header_created(self, tmp_path):
        """Compatibility header is created when missing."""
        source_dir = tmp_path / "dbgen"
        source_dir.mkdir()

        compiler = TPCCompiler(auto_compile=False)
        compiler._apply_macos_patches(source_dir)

        compat_header = source_dir / "macos_compat.h"
        assert compat_header.exists()
        content = compat_header.read_text()
        assert "MACOS_COMPAT_H" in content
        assert "#include <unistd.h>" in content

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_compat_header_not_overwritten(self, tmp_path):
        """Existing compatibility header is not overwritten."""
        source_dir = tmp_path / "dbgen"
        source_dir.mkdir()
        compat_header = source_dir / "macos_compat.h"
        compat_header.write_text("/* existing */")

        compiler = TPCCompiler(auto_compile=False)
        compiler._apply_macos_patches(source_dir)

        assert compat_header.read_text() == "/* existing */"


# ---------------------------------------------------------------------------
# Status report
# ---------------------------------------------------------------------------
class TestStatusReport:
    """Tests for get_status_report."""

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_report_structure(self):
        compiler = TPCCompiler(auto_compile=False)
        report = compiler.get_status_report()

        assert "auto_compile_enabled" in report
        assert report["auto_compile_enabled"] is False
        assert "platform" in report
        assert "binaries" in report
        assert isinstance(report["binaries"], dict)


# ---------------------------------------------------------------------------
# compile_all_needed
# ---------------------------------------------------------------------------
class TestCompileAllNeeded:
    """Tests for compile_all_needed."""

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_compile_all_when_none_needed(self):
        """When no binaries need compilation, all get NOT_NEEDED."""
        compiler = TPCCompiler(auto_compile=True)
        results = compiler.compile_all_needed()
        for name, result in results.items():
            assert result.status == CompilationStatus.NOT_NEEDED


# ---------------------------------------------------------------------------
# get_tpc_compiler caching
# ---------------------------------------------------------------------------
class TestGetTPCCompiler:
    """Tests for the cached compiler factory."""

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_returns_tpc_compiler(self):
        compiler = get_tpc_compiler(auto_compile=False)
        assert isinstance(compiler, TPCCompiler)
        assert compiler.auto_compile is False

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_caches_same_params(self):
        c1 = get_tpc_compiler(auto_compile=False, verbose=False)
        c2 = get_tpc_compiler(auto_compile=False, verbose=False)
        assert c1 is c2

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_different_params_different_instances(self):
        c1 = get_tpc_compiler(auto_compile=False, verbose=False)
        c2 = get_tpc_compiler(auto_compile=True, verbose=False)
        assert c1 is not c2


# ---------------------------------------------------------------------------
# get_precompiled_bundle_root
# ---------------------------------------------------------------------------
class TestGetPrecompiledBundleRoot:
    """Tests for get_precompiled_bundle_root."""

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_unknown_binary_name(self):
        result = get_precompiled_bundle_root("nonexistent")
        # May return None since precompiled_base may not exist or binary is unknown
        assert result is None

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    @patch("benchbox.utils.tpc_compilation._checksum_cache", {})
    def test_returns_path_for_known_binary(self, tmp_path):
        """When precompiled dir exists, returns the path."""
        precompiled_base = tmp_path / "_binaries"
        # Get actual platform string
        compiler = TPCCompiler(auto_compile=False)
        platform_str = compiler._get_platform_string()

        tpch_dir = precompiled_base / "tpc-h" / platform_str
        tpch_dir.mkdir(parents=True)

        with (
            patch(
                "benchbox.utils.tpc_compilation._discovered_paths",
                {
                    "tpc_h_source": None,
                    "tpc_ds_source": None,
                    "precompiled_base": precompiled_base,
                },
            ),
            patch("benchbox.utils.tpc_compilation._compiler_cache", {}),
        ):
            result = get_precompiled_bundle_root("dbgen")
            assert result == tpch_dir

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_returns_none_without_precompiled_base(self):
        with (
            patch(
                "benchbox.utils.tpc_compilation._discovered_paths",
                {
                    "tpc_h_source": None,
                    "tpc_ds_source": None,
                    "precompiled_base": None,
                },
            ),
            patch("benchbox.utils.tpc_compilation._compiler_cache", {}),
        ):
            result = get_precompiled_bundle_root("dbgen")
            assert result is None


# ---------------------------------------------------------------------------
# ensure_tpc_binaries
# ---------------------------------------------------------------------------
class TestEnsureTPCBinaries:
    """Tests for ensure_tpc_binaries."""

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_unknown_binary(self):
        results = ensure_tpc_binaries(["unknown_binary"], auto_compile=False)
        assert results["unknown_binary"].status == CompilationStatus.FAILED
        assert "Unknown binary" in results["unknown_binary"].error_message


# ---------------------------------------------------------------------------
# get_tpc_templates_dir
# ---------------------------------------------------------------------------
class TestGetTPCTemplatesDir:
    """Tests for get_tpc_templates_dir."""

    def test_unknown_benchmark_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown benchmark"):
            get_tpc_templates_dir("unknown-benchmark")

    def test_tpch_returns_path(self):
        """TPC-H templates should be found in dev or package layout."""
        try:
            path = get_tpc_templates_dir("tpc-h")
            assert path.exists()
        except RuntimeError:
            pytest.skip("TPC-H templates not available in this environment")

    def test_tpcds_returns_path_or_raises(self):
        """TPC-DS templates should be found or raise RuntimeError."""
        try:
            path = get_tpc_templates_dir("tpc-ds")
            assert path.exists()
        except RuntimeError:
            # Expected if sources not available
            pass


# ---------------------------------------------------------------------------
# Path discovery
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Windows-specific: executable detection with os.name guard
# ---------------------------------------------------------------------------
class TestExecutableDetectionWindows:
    """Verify is_binary_available / is_precompiled_available honour the
    os.name != 'nt' guard added for Windows.

    On Windows os.access(path, os.X_OK) is always True, so the code now
    skips that check when os.name == 'nt'.  These tests mock os.name to
    confirm both the Unix path (checking X_OK) and the Windows path (skipping
    it) behave correctly.
    """

    def _make_compiler_with_binary(self, tmp_path, *, use_precompiled: bool):
        """Helper: build a minimal TPCCompiler wired to a real file on disk."""
        binary = tmp_path / "dbgen"
        binary.write_bytes(b"fake binary")
        # Do NOT chmod +x - tests that mock os.name == 'nt' should still pass.

        with (
            patch("benchbox.utils.tpc_compilation._discovered_paths", {}),
            patch("benchbox.utils.tpc_compilation._compiler_cache", {}),
            patch.object(TPCCompiler, "__init__", lambda self, **kw: None),
        ):
            compiler = TPCCompiler.__new__(TPCCompiler)
            compiler.auto_compile = False
            compiler.verbose = False
            compiler.tpc_h_source = None
            compiler.tpc_ds_source = None
            compiler.precompiled_base = tmp_path
            compiler._setup_binary_configs()

        if use_precompiled:
            compiler.binaries["dbgen"].precompiled_path = binary
        else:
            compiler.binaries["dbgen"].binary_path = binary

        return compiler, binary

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._checksum_cache", {})
    def test_precompiled_unix_requires_executable_bit(self, tmp_path):
        """On Unix, a file without +x is rejected by is_precompiled_available."""
        compiler, binary = self._make_compiler_with_binary(tmp_path, use_precompiled=True)
        # os.access(path, X_OK) always returns True on Windows regardless of file
        # permissions, so mock it to False to simulate a non-executable Unix file.
        with patch("benchbox.utils.tpc_compilation.os.name", "posix"):
            with patch("benchbox.utils.tpc_compilation.os.access", return_value=False):
                # File exists but is NOT executable → should return False
                assert compiler.is_precompiled_available("dbgen") is False

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._checksum_cache", {})
    def test_precompiled_windows_skips_executable_bit(self, tmp_path):
        """On Windows (os.name == 'nt'), existence is sufficient."""
        compiler, binary = self._make_compiler_with_binary(tmp_path, use_precompiled=True)
        with patch("benchbox.utils.tpc_compilation.os.name", "nt"):
            # File exists; X_OK check is skipped → should return True
            assert compiler.is_precompiled_available("dbgen") is True

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_source_binary_unix_requires_executable_bit(self, tmp_path):
        """On Unix, a non-executable source binary is rejected."""
        compiler, binary = self._make_compiler_with_binary(tmp_path, use_precompiled=False)
        with patch("benchbox.utils.tpc_compilation.os.name", "posix"):
            with patch("benchbox.utils.tpc_compilation.os.access", return_value=False):
                assert compiler.is_binary_available("dbgen") is False

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_source_binary_windows_skips_executable_bit(self, tmp_path):
        """On Windows, a source binary is accepted if it exists."""
        compiler, binary = self._make_compiler_with_binary(tmp_path, use_precompiled=False)
        with patch("benchbox.utils.tpc_compilation.os.name", "nt"):
            assert compiler.is_binary_available("dbgen") is True

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    @patch("benchbox.utils.tpc_compilation._compiler_cache", {})
    def test_get_binary_path_windows(self, tmp_path):
        """get_binary_path returns the path on Windows without X_OK check."""
        compiler, binary = self._make_compiler_with_binary(tmp_path, use_precompiled=False)
        with patch("benchbox.utils.tpc_compilation.os.name", "nt"):
            assert compiler.get_binary_path("dbgen") == binary


class TestDiscoverTPCPaths:
    """Tests for _discover_tpc_paths."""

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    def test_discover_returns_dict_with_expected_keys(self):
        paths = _discover_tpc_paths()
        assert "tpc_h_source" in paths
        assert "tpc_ds_source" in paths
        assert "precompiled_base" in paths

    @patch("benchbox.utils.tpc_compilation._discovered_paths", {})
    def test_discover_caching(self):
        """Second call returns cached dict."""
        paths1 = _discover_tpc_paths()
        paths2 = _discover_tpc_paths()
        assert paths1 is paths2
