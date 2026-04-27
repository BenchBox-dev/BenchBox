"""TPC binary auto-compilation utilities.

This module provides centralized functionality to automatically use pre-compiled TPC-H and
TPC-DS binary tools when available, or compile them from source when needed.

Supports:
- TPC-H: dbgen (data generator), qgen (query generator)
- TPC-DS: dsdgen (data generator), dsqgen (query generator)

Features:
- Pre-compiled binary detection and usage (priority #1)
- Platform-aware compilation fallback (macOS, Linux, Windows)
- Binary verification with checksums
- Dependency detection and error reporting
- Configuration option to disable auto-compilation
- Comprehensive logging and status reporting

Copyright 2026 Joe Harris / BenchBox Project

TPC-H and TPC-DS auto-compilation utilities for dbgen, qgen, dsdgen, and dsqgen tools.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import hashlib
import logging
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from benchbox.utils.clock import elapsed_seconds, mono_time

# Configure logging for this module
logger = logging.getLogger(__name__)

# Cached discovery results (shared across all TPCCompiler instances)
_discovered_paths: dict[str, Optional[Path]] = {}

# Cached checksum verification results (shared across all TPCCompiler instances)
_checksum_cache: dict[Path, bool] = {}


def _discover_tpc_paths() -> dict[str, Optional[Path]]:
    """Discover TPC source and binary paths once, cache the results."""
    global _discovered_paths

    if _discovered_paths:
        return _discovered_paths

    # Find TPC-H source
    tpc_h_source = None
    for path in [
        Path(__file__).parent.parent.parent / "_sources/tpc-h/dbgen",
        Path.cwd() / "_sources/tpc-h/dbgen",
        Path.home() / "tpc-h/dbgen",
    ]:
        if path.exists() and (path / "build.c").exists():
            logger.debug(f"Found TPC-H source at: {path}")
            tpc_h_source = path
            break
    if tpc_h_source is None:
        logger.debug("TPC-H source directory not found")

    # Find TPC-DS source
    tpc_ds_source = None
    for path in [
        Path(__file__).parent.parent.parent / "_sources/tpc-ds/tools",
        Path.cwd() / "_sources/tpc-ds/tools",
        Path.home() / "tpc-ds/tools",
    ]:
        if path.exists() and (path / "driver.c").exists():
            logger.debug(f"Found TPC-DS source at: {path}")
            tpc_ds_source = path
            break
    if tpc_ds_source is None:
        logger.debug("TPC-DS source directory not found")

    # Find pre-compiled binaries
    # Priority: 1) Inside the benchbox package (for installed packages)
    #           2) Adjacent to benchbox package (for development)
    #           3) Current working directory (fallback)
    precompiled_base = None
    for path in [
        Path(__file__).parent.parent / "_binaries",  # Inside benchbox package
        Path(__file__).parent.parent.parent / "_binaries",  # Adjacent to benchbox (dev)
        Path.cwd() / "_binaries",  # Current working directory
    ]:
        if path.exists() and path.is_dir():
            logger.debug(f"Found pre-compiled binaries at: {path}")
            precompiled_base = path
            break
    if precompiled_base is None:
        logger.debug("Pre-compiled binaries directory not found")

    _discovered_paths = {
        "tpc_h_source": tpc_h_source,
        "tpc_ds_source": tpc_ds_source,
        "precompiled_base": precompiled_base,
    }
    return _discovered_paths


def get_tpc_templates_dir(benchmark: str) -> Path:
    """Locate TPC template directory: bundled package first, _sources/ fallback.

    Resolution priority:
        1. Inside package: benchbox/_binaries/{benchmark}/templates/
           (works for wheel installs and editable installs)
        2. _sources/ at repo root: _sources/{benchmark-path}/
           (development without editable install)

    Args:
        benchmark: "tpc-h" or "tpc-ds"

    Returns:
        Path to the templates directory

    Raises:
        ValueError: If benchmark name is not recognized
        RuntimeError: If templates directory not found at any location
    """
    import benchbox

    package_dir = Path(benchbox.__file__).parent

    # Priority 1: Inside package (_binaries/{benchmark}/templates/)
    bundled = package_dir / "_binaries" / benchmark / "templates"
    if bundled.exists():
        return bundled

    # Priority 2: _sources/ at repo root (development/editable installs)
    repo_root = package_dir.parent
    if benchmark == "tpc-h":
        dev_path = repo_root / "_sources" / "tpc-h" / "dbgen"
    elif benchmark == "tpc-ds":
        dev_path = repo_root / "_sources" / "tpc-ds"
    else:
        raise ValueError(f"Unknown benchmark: {benchmark}")

    if dev_path.exists():
        return dev_path

    raise RuntimeError(f"TPC template directory not found for {benchmark}. Checked: {bundled}, {dev_path}")


class CompilationStatus(Enum):
    """Status of binary compilation."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    DISABLED = "disabled"
    NOT_NEEDED = "not_needed"
    PRECOMPILED = "precompiled"


@dataclass
class BinaryInfo:
    """Information about a TPC binary."""

    name: str
    source_dir: Path
    binary_path: Path
    precompiled_path: Optional[Path] = None
    makefile_path: Optional[Path] = None
    dependencies: list[str] = None

    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []


@dataclass
class CompilationResult:
    """Result of binary compilation attempt."""

    binary_name: str
    status: CompilationStatus
    binary_path: Optional[Path] = None
    error_message: Optional[str] = None
    compilation_time: Optional[float] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None


class TPCCompiler:
    """Auto-compiler for TPC-H and TPC-DS binary tools."""

    def __init__(self, auto_compile: bool = True, verbose: bool = False):
        """Initialize TPC compiler.

        Args:
            auto_compile: Whether to enable auto-compilation
            verbose: Whether to enable verbose logging
        """
        self.auto_compile = auto_compile
        self.verbose = verbose

        # Use cached path discovery (only runs once globally)
        paths = _discover_tpc_paths()
        self.tpc_h_source = paths["tpc_h_source"]
        self.tpc_ds_source = paths["tpc_ds_source"]
        self.precompiled_base = paths["precompiled_base"]

        # Define binary configurations
        self._setup_binary_configs()

        if verbose:
            logger.setLevel(logging.DEBUG)

    def _get_platform_string(self) -> str:
        """Get platform string for pre-compiled binary lookup."""
        system = platform.system().lower()
        machine = platform.machine().lower()

        # Normalize machine architecture
        if machine in ["x86_64", "amd64"]:
            arch = "x86_64"
        elif machine in ["arm64", "aarch64"]:
            arch = "arm64"
        else:
            arch = machine

        # Normalize system name
        if system == "darwin":
            system = "darwin"
        elif system == "linux":
            system = "linux"
        elif system == "windows":
            system = "windows"
        else:
            system = system

        return f"{system}-{arch}"

    def _setup_binary_configs(self):
        """Set up binary configuration information."""
        self.binaries: dict[str, BinaryInfo] = {}
        platform_str = self._get_platform_string()
        is_windows = platform.system() == "Windows"
        exe_suffix = ".exe" if is_windows else ""

        # Helper to get precompiled path
        def get_precompiled_path(benchmark: str, binary_name: str) -> Optional[Path]:
            if self.precompiled_base:
                return self.precompiled_base / benchmark / platform_str / f"{binary_name}{exe_suffix}"
            return None

        # TPC-H binaries
        if self.tpc_h_source or self.precompiled_base:
            self.binaries["dbgen"] = BinaryInfo(
                name="dbgen",
                source_dir=self.tpc_h_source or Path(),
                binary_path=(self.tpc_h_source / f"dbgen{exe_suffix}") if self.tpc_h_source else Path(),
                precompiled_path=get_precompiled_path("tpc-h", "dbgen"),
                makefile_path=(self.tpc_h_source / "makefile.suite") if self.tpc_h_source else None,
                dependencies=["gcc", "make"],
            )

            self.binaries["qgen"] = BinaryInfo(
                name="qgen",
                source_dir=self.tpc_h_source or Path(),
                binary_path=(self.tpc_h_source / f"qgen{exe_suffix}") if self.tpc_h_source else Path(),
                precompiled_path=get_precompiled_path("tpc-h", "qgen"),
                makefile_path=(self.tpc_h_source / "makefile.suite") if self.tpc_h_source else None,
                dependencies=["gcc", "make"],
            )

        # TPC-DS binaries
        if self.tpc_ds_source or self.precompiled_base:
            self.binaries["dsdgen"] = BinaryInfo(
                name="dsdgen",
                source_dir=self.tpc_ds_source or Path(),
                binary_path=(self.tpc_ds_source / f"dsdgen{exe_suffix}") if self.tpc_ds_source else Path(),
                precompiled_path=get_precompiled_path("tpc-ds", "dsdgen"),
                makefile_path=(self.tpc_ds_source / "makefile") if self.tpc_ds_source else None,
                dependencies=["gcc", "make", "yacc"],
            )

            self.binaries["dsqgen"] = BinaryInfo(
                name="dsqgen",
                source_dir=self.tpc_ds_source or Path(),
                binary_path=(self.tpc_ds_source / f"dsqgen{exe_suffix}") if self.tpc_ds_source else Path(),
                precompiled_path=get_precompiled_path("tpc-ds", "dsqgen"),
                makefile_path=(self.tpc_ds_source / "makefile") if self.tpc_ds_source else None,
                dependencies=["gcc", "make", "yacc"],
            )

    def check_dependencies(self, binary_name: str) -> tuple[bool, list[str]]:
        """Check if compilation dependencies are available.

        Args:
            binary_name: Name of binary to check dependencies for

        Returns:
            Tuple of (all_available, missing_dependencies)
        """
        if binary_name not in self.binaries:
            return False, [f"Unknown binary: {binary_name}"]

        binary_info = self.binaries[binary_name]
        missing = []

        for dep in binary_info.dependencies:
            if not shutil.which(dep):
                missing.append(dep)

        return len(missing) == 0, missing

    def _verify_checksum(self, binary_path: Path) -> bool:
        """Verify binary checksum against checksums.md5 file (cached globally)."""
        if not binary_path.exists():
            return False

        # Check global cache first
        if binary_path in _checksum_cache:
            return _checksum_cache[binary_path]

        checksum_file = binary_path.parent / "checksums.md5"
        if not checksum_file.exists():
            logger.debug(f"No checksum file found for {binary_path}")
            _checksum_cache[binary_path] = True
            return True  # Assume valid if no checksum file

        try:
            # Calculate MD5 hash of the binary
            with open(binary_path, "rb") as f:
                binary_hash = hashlib.md5(f.read()).hexdigest()

            # Read and parse checksums.md5 file
            with open(checksum_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    # Handle both formats: "hash filename" and "hash  filename"
                    parts = line.split()
                    if len(parts) >= 2:
                        expected_hash = parts[0]
                        filename = parts[-1]  # Take last part as filename

                        # Normalize filenames - remove ./ prefix if present
                        normalized_filename = filename.lstrip("./")
                        if normalized_filename == binary_path.name:
                            if binary_hash == expected_hash:
                                logger.debug(f"Checksum verified for {binary_path.name}")
                                _checksum_cache[binary_path] = True
                                return True
                            else:
                                logger.warning(
                                    f"Checksum mismatch for {binary_path.name}: expected {expected_hash}, got {binary_hash}"
                                )
                                _checksum_cache[binary_path] = False
                                return False

            logger.warning(f"No checksum entry found for {binary_path.name}")
            _checksum_cache[binary_path] = True
            return True  # Assume valid if not in checksum file

        except Exception as e:
            logger.warning(f"Failed to verify checksum for {binary_path}: {e}")
            _checksum_cache[binary_path] = True
            return True  # Assume valid on verification error

    def is_precompiled_available(self, binary_name: str) -> bool:
        """Check if pre-compiled binary is available and valid."""
        if binary_name not in self.binaries:
            return False

        binary_info = self.binaries[binary_name]
        if not binary_info.precompiled_path:
            return False

        precompiled_path = binary_info.precompiled_path

        # Check if binary exists and is executable (X_OK is a no-op on Windows)
        if not (precompiled_path.exists() and (os.name == "nt" or os.access(precompiled_path, os.X_OK))):
            return False

        # Verify checksum if available
        return self._verify_checksum(precompiled_path)

    def is_binary_available(self, binary_name: str) -> bool:
        """Check if binary is already compiled and available.

        Checks in order:
        1. Pre-compiled binaries (priority)
        2. Source-compiled binaries

        Args:
            binary_name: Name of binary to check

        Returns:
            True if binary exists and is executable
        """
        if binary_name not in self.binaries:
            return False

        # First check for pre-compiled binary
        if self.is_precompiled_available(binary_name):
            return True

        # Fall back to source-compiled binary
        binary_info = self.binaries[binary_name]
        binary_path = binary_info.binary_path

        # os.X_OK is a no-op on Windows (always True); existence check is sufficient there
        return binary_path and binary_path.exists() and (os.name == "nt" or os.access(binary_path, os.X_OK))

    def needs_compilation(self, binary_name: str) -> bool:
        """Check if binary needs compilation.

        Args:
            binary_name: Name of binary to check

        Returns:
            True if source exists but binary is missing or not executable
        """
        if binary_name not in self.binaries:
            return False

        binary_info = self.binaries[binary_name]

        # Check if source directory exists
        if not binary_info.source_dir.exists():
            return False

        # Check if binary is already available
        return not self.is_binary_available(binary_name)

    def get_binary_path(self, binary_name: str) -> Optional[Path]:
        """Get the actual path to the binary (precompiled or source-compiled).

        Args:
            binary_name: Name of binary to locate

        Returns:
            Path to the binary if available, None otherwise
        """
        if binary_name not in self.binaries:
            return None

        binary_info = self.binaries[binary_name]

        # First check for pre-compiled binary
        if self.is_precompiled_available(binary_name):
            return binary_info.precompiled_path

        # Fall back to source-compiled binary
        # os.X_OK is a no-op on Windows (always True); existence check is sufficient there
        if (
            binary_info.binary_path
            and binary_info.binary_path.exists()
            and (os.name == "nt" or os.access(binary_info.binary_path, os.X_OK))
        ):
            return binary_info.binary_path

        return None

    def compile_binary(self, binary_name: str) -> CompilationResult:
        """Compile a TPC binary.

        Args:
            binary_name: Name of binary to compile ("dbgen", "qgen", "dsdgen", "dsqgen")

        Returns:
            CompilationResult with status and details
        """

        start_time = mono_time()

        # Check if compilation is disabled
        if not self.auto_compile:
            return CompilationResult(
                binary_name=binary_name,
                status=CompilationStatus.DISABLED,
                error_message="Auto-compilation is disabled",
            )

        # Check if binary is known
        if binary_name not in self.binaries:
            return CompilationResult(
                binary_name=binary_name,
                status=CompilationStatus.FAILED,
                error_message=f"Unknown binary: {binary_name}",
            )

        binary_info = self.binaries[binary_name]

        # Check if pre-compiled binary is available (highest priority)
        if self.is_precompiled_available(binary_name):
            logger.info(f"Using pre-compiled binary for {binary_name}")
            return CompilationResult(
                binary_name=binary_name,
                status=CompilationStatus.PRECOMPILED,
                binary_path=binary_info.precompiled_path,
            )

        # Check if compilation is needed
        if not self.needs_compilation(binary_name):
            if self.is_binary_available(binary_name):
                return CompilationResult(
                    binary_name=binary_name,
                    status=CompilationStatus.NOT_NEEDED,
                    binary_path=self.get_binary_path(binary_name),
                )
            else:
                return CompilationResult(
                    binary_name=binary_name,
                    status=CompilationStatus.FAILED,
                    error_message=f"Source directory not found: {binary_info.source_dir}",
                )

        # Check dependencies
        deps_available, missing_deps = self.check_dependencies(binary_name)
        if not deps_available:
            return CompilationResult(
                binary_name=binary_name,
                status=CompilationStatus.FAILED,
                error_message=f"Missing dependencies: {', '.join(missing_deps)}",
            )

        logger.info(f"Compiling {binary_name}...")

        try:
            # Perform compilation based on binary type
            if binary_name in ["dbgen", "qgen"]:
                result = self._compile_tpc_h_binary(binary_name, binary_info)
            else:  # dsdgen, dsqgen
                result = self._compile_tpc_ds_binary(binary_name, binary_info)

            # Add timing information
            result.compilation_time = elapsed_seconds(start_time)

            if result.status == CompilationStatus.SUCCESS:
                logger.info(f"Successfully compiled {binary_name} in {result.compilation_time:.2f}s")
            else:
                logger.error(f"Failed to compile {binary_name}: {result.error_message}")

            return result

        except Exception as e:
            return CompilationResult(
                binary_name=binary_name,
                status=CompilationStatus.FAILED,
                error_message=f"Compilation failed with exception: {str(e)}",
                compilation_time=elapsed_seconds(start_time),
            )

    def _compile_tpc_h_binary(self, binary_name: str, binary_info: BinaryInfo) -> CompilationResult:
        """Compile TPC-H binary (dbgen or qgen)."""

        # Apply platform-specific source patches if needed
        if platform.system().lower() == "darwin":
            self._apply_macos_patches(binary_info.source_dir)

        # Create platform-aware Makefile
        makefile_path = binary_info.source_dir / "Makefile.auto"
        self._create_tpc_h_makefile(makefile_path)

        try:
            # Run make command
            cmd = ["make", "-f", "Makefile.auto", binary_name]

            result = subprocess.run(
                cmd,
                cwd=binary_info.source_dir,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode == 0 and binary_info.binary_path.exists():
                return CompilationResult(
                    binary_name=binary_name,
                    status=CompilationStatus.SUCCESS,
                    binary_path=binary_info.binary_path,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            else:
                return CompilationResult(
                    binary_name=binary_name,
                    status=CompilationStatus.FAILED,
                    error_message=f"Make failed with exit code {result.returncode}",
                    stdout=result.stdout,
                    stderr=result.stderr,
                )

        except subprocess.TimeoutExpired:
            return CompilationResult(
                binary_name=binary_name,
                status=CompilationStatus.FAILED,
                error_message="Compilation timed out after 5 minutes",
            )
        except Exception as e:
            return CompilationResult(
                binary_name=binary_name,
                status=CompilationStatus.FAILED,
                error_message=f"Compilation error: {str(e)}",
            )

    def _compile_tpc_ds_binary(self, binary_name: str, binary_info: BinaryInfo) -> CompilationResult:
        """Compile TPC-DS binary (dsdgen or dsqgen)."""

        try:
            # Use existing Makefile if available, otherwise create simple one
            makefile_name = "makefile" if (binary_info.source_dir / "makefile").exists() else "Makefile"

            # Run make command
            cmd = ["make", "-f", makefile_name, binary_name]

            result = subprocess.run(
                cmd,
                cwd=binary_info.source_dir,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout for TPC-DS (needs yacc processing)
            )

            if result.returncode == 0 and binary_info.binary_path.exists():
                return CompilationResult(
                    binary_name=binary_name,
                    status=CompilationStatus.SUCCESS,
                    binary_path=binary_info.binary_path,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            else:
                return CompilationResult(
                    binary_name=binary_name,
                    status=CompilationStatus.FAILED,
                    error_message=f"Make failed with exit code {result.returncode}",
                    stdout=result.stdout,
                    stderr=result.stderr,
                )

        except subprocess.TimeoutExpired:
            return CompilationResult(
                binary_name=binary_name,
                status=CompilationStatus.FAILED,
                error_message="Compilation timed out after 10 minutes",
            )
        except Exception as e:
            return CompilationResult(
                binary_name=binary_name,
                status=CompilationStatus.FAILED,
                error_message=f"Compilation error: {str(e)}",
            )

    def _create_tpc_h_makefile(self, makefile_path: Path):
        """Create a platform-aware Makefile for TPC-H compilation."""
        # Determine platform-specific settings
        platform_name = platform.system().lower()

        if platform_name == "linux":
            machine_flag = "LINUX"
            extra_defines = "-DORACLE"  # Use ORACLE DB defines (simplest)
        elif platform_name == "darwin":
            # Use LINUX compatibility mode for macOS with additional macOS-specific fixes
            machine_flag = "LINUX"
            # Add macOS-specific workarounds
            extra_defines = "-DORACLE -DMACOS_COMPAT"  # Use ORACLE DB defines
        elif platform_name == "windows":
            machine_flag = "WIN32"
            extra_defines = "-DSQLSERVER"  # Use SQLSERVER DB defines for Windows
        else:
            machine_flag = "LINUX"  # Default to Linux
            extra_defines = "-DORACLE"  # Use ORACLE DB defines

        makefile_content = f"""# Auto-generated Makefile for TPC-H compilation
# Platform: {platform_name}
CC = gcc
# Let config.h handle most definitions to avoid redefinition warnings
# Enable EOL_HANDLING to prevent trailing column separators
CFLAGS = -O2 -DDBNAME=\\"dss\\" -D{machine_flag} -DTPCH -DRNG_TEST -D_FILE_OFFSET_BITS=64 \\
         -DEOL_HANDLING {extra_defines} -I.

# macOS-specific compiler adjustments
ifeq ($(shell uname),Darwin)
    CFLAGS += -Dmalloc=malloc -D_DARWIN_C_SOURCE
    # Suppress getopt warnings on macOS by using system getopt
    CFLAGS += -DUSE_SYSTEM_GETOPT
endif

# Object files for dbgen
DBGEN_OBJECTS = build.o driver.o bm_utils.o rnd.o print.o load_stub.o bcd2.o speed_seed.o text.o permute.o rng64.o

# Object files for qgen
QGEN_OBJECTS = build.o bm_utils.o qgen.o rnd.o varsub.o text.o bcd2.o permute.o rng64.o speed_seed.o

all: dbgen qgen

dbgen: $(DBGEN_OBJECTS)
	$(CC) $(CFLAGS) -o dbgen $(DBGEN_OBJECTS) -lm

qgen: $(QGEN_OBJECTS)
	$(CC) $(CFLAGS) -o qgen $(QGEN_OBJECTS) -lm

# Special compilation rules for macOS compatibility
%.o: %.c
	@if [ "$$(uname)" = "Darwin" ]; then \\
		$(CC) $(CFLAGS) -c $< -o $@ 2>/dev/null || \\
		$(CC) $(CFLAGS) -include stdlib.h -Dmalloc_h_included=1 -c $< -o $@; \\
	else \\
		$(CC) $(CFLAGS) -c $< -o $@; \\
	fi

clean:
	rm -f *.o dbgen qgen

.PHONY: all clean dbgen qgen

# Debug target to show configuration
debug:
	@echo "Platform: {platform_name}"
	@echo "Machine flag: {machine_flag}"
	@echo "CFLAGS: $(CFLAGS)"
"""
        with open(makefile_path, "w", encoding="utf-8") as f:
            f.write(makefile_content)

    def _apply_macos_patches(self, source_dir: Path):
        """Apply minimal patches for macOS compatibility."""

        # Files that need malloc.h -> stdlib.h replacement
        files_to_patch = ["bm_utils.c", "varsub.c"]

        for filename in files_to_patch:
            file_path = source_dir / filename
            if file_path.exists():
                try:
                    # Read the file
                    with open(file_path, encoding="utf-8") as f:
                        content = f.read()

                    # Check if already patched
                    if "#include <malloc.h>" in content:
                        logger.debug(f"Patching {filename} for macOS compatibility")

                        # Replace malloc.h with stdlib.h
                        content = content.replace("#include <malloc.h>", "#include <stdlib.h>")

                        # Write back
                        with open(file_path, "w", encoding="utf-8") as f:
                            f.write(content)

                except Exception as e:
                    logger.warning(f"Failed to patch {filename}: {e}")

        # Create a compatibility header for getopt conflicts
        compat_header = source_dir / "macos_compat.h"
        if not compat_header.exists():
            compat_content = """/* macOS compatibility header - auto-generated */
#ifndef MACOS_COMPAT_H
#define MACOS_COMPAT_H

#ifdef MACOS_COMPAT
/* Use system getopt on macOS to avoid conflicts */
#include <unistd.h>
#ifdef getopt
#undef getopt
#endif
#endif

#endif /* MACOS_COMPAT_H */
"""
            try:
                with open(compat_header, "w", encoding="utf-8") as f:
                    f.write(compat_content)
            except Exception as e:
                logger.warning(f"Failed to create compatibility header: {e}")

    def compile_all_needed(self) -> dict[str, CompilationResult]:
        """Compile all TPC binaries that need compilation.

        Returns:
            Dictionary mapping binary names to CompilationResults
        """
        results = {}

        for binary_name in self.binaries:
            if self.needs_compilation(binary_name):
                results[binary_name] = self.compile_binary(binary_name)
            else:
                results[binary_name] = CompilationResult(
                    binary_name=binary_name,
                    status=CompilationStatus.NOT_NEEDED,
                    binary_path=self.binaries[binary_name].binary_path
                    if self.is_binary_available(binary_name)
                    else None,
                )

        return results

    def get_status_report(self) -> dict[str, Any]:
        """Get comprehensive status report of all TPC binaries.

        Returns:
            Dictionary with status information
        """
        report = {
            "auto_compile_enabled": self.auto_compile,
            "tpc_h_source": str(self.tpc_h_source) if self.tpc_h_source else None,
            "tpc_ds_source": str(self.tpc_ds_source) if self.tpc_ds_source else None,
            "precompiled_base": str(self.precompiled_base) if self.precompiled_base else None,
            "platform": self._get_platform_string(),
            "binaries": {},
        }

        for binary_name, binary_info in self.binaries.items():
            deps_available, missing_deps = self.check_dependencies(binary_name)

            report["binaries"][binary_name] = {
                "source_dir": str(binary_info.source_dir) if binary_info.source_dir else None,
                "binary_path": str(binary_info.binary_path) if binary_info.binary_path else None,
                "precompiled_path": str(binary_info.precompiled_path) if binary_info.precompiled_path else None,
                "precompiled_available": self.is_precompiled_available(binary_name),
                "exists": self.is_binary_available(binary_name),
                "actual_path": str(self.get_binary_path(binary_name)) if self.get_binary_path(binary_name) else None,
                "needs_compilation": self.needs_compilation(binary_name),
                "dependencies_available": deps_available,
                "missing_dependencies": missing_deps,
            }

        return report


# Cached compiler instances by (auto_compile, verbose) settings
_compiler_cache: dict[tuple[bool, bool], TPCCompiler] = {}


def get_tpc_compiler(auto_compile: bool = True, verbose: bool = False) -> TPCCompiler:
    """Get TPC compiler instance (cached to avoid repeated initialization).

    Args:
        auto_compile: Whether to enable auto-compilation
        verbose: Whether to enable verbose logging

    Returns:
        TPCCompiler instance
    """
    cache_key = (auto_compile, verbose)
    if cache_key not in _compiler_cache:
        _compiler_cache[cache_key] = TPCCompiler(auto_compile=auto_compile, verbose=verbose)
    return _compiler_cache[cache_key]


def get_precompiled_bundle_root(binary_name: str) -> Optional[Path]:
    """Locate the platform-specific directory for precompiled TPC bundles."""

    compiler = get_tpc_compiler(auto_compile=False)
    if compiler.precompiled_base is None:
        return None

    platform_str = compiler._get_platform_string()
    if binary_name in {"dsqgen", "dsdgen"}:
        candidate = compiler.precompiled_base / "tpc-ds" / platform_str
    elif binary_name in {"dbgen", "qgen"}:
        candidate = compiler.precompiled_base / "tpc-h" / platform_str
    else:
        return None

    return candidate if candidate.exists() else None


def ensure_tpc_binaries(binaries: list[str], auto_compile: bool = True) -> dict[str, CompilationResult]:
    """Ensure specified TPC binaries are available, compiling if needed.

    Args:
        binaries: List of binary names to ensure ("dbgen", "qgen", "dsdgen", "dsqgen")
        auto_compile: Whether to enable auto-compilation

    Returns:
        Dictionary mapping binary names to CompilationResults
    """
    compiler = get_tpc_compiler(auto_compile=auto_compile)
    results = {}

    for binary_name in binaries:
        if binary_name in compiler.binaries:
            if compiler.needs_compilation(binary_name):
                results[binary_name] = compiler.compile_binary(binary_name)
            else:
                # Check if using precompiled binary
                if compiler.is_precompiled_available(binary_name):
                    results[binary_name] = CompilationResult(
                        binary_name=binary_name,
                        status=CompilationStatus.PRECOMPILED,
                        binary_path=compiler.get_binary_path(binary_name),
                    )
                else:
                    results[binary_name] = CompilationResult(
                        binary_name=binary_name,
                        status=CompilationStatus.NOT_NEEDED,
                        binary_path=compiler.get_binary_path(binary_name),
                    )
        else:
            results[binary_name] = CompilationResult(
                binary_name=binary_name,
                status=CompilationStatus.FAILED,
                error_message=f"Unknown binary: {binary_name}",
            )

    return results
