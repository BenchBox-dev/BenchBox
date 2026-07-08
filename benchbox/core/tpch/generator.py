"""TPC-H data generator module.

Provides functionality to generate TPC-H benchmark data using the official TPC-H dbgen tool.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-H specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import platform
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NoReturn

import yaml

from benchbox.utils.cloud_storage import CloudStorageGeneratorMixin, create_path_handler
from benchbox.utils.compression_mixin import CompressionMixin
from benchbox.utils.data_validation import BenchmarkDataValidator
from benchbox.utils.datagen_manifest import DataGenerationManifest, resolve_compression_metadata
from benchbox.utils.file_format import COMPRESSION_EXTENSIONS
from benchbox.utils.scale_factor import format_scale_factor
from benchbox.utils.stale_artifact_pruning import TableArtifactPattern, prune_stale_table_artifacts
from benchbox.utils.tpc_compilation import CompilationStatus, ensure_tpc_binaries
from benchbox.utils.verbosity import VerbosityMixin, compute_verbosity


def _load_generator_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("generator_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_GENERATOR_SPECS = _load_generator_specs()
_TPCH_TABLE_CODES = dict(_GENERATOR_SPECS["table_codes"])
_TPCH_BASE_ROW_COUNTS = dict(_GENERATOR_SPECS["base_row_counts"])

# Chunk size for the streaming trailing-delimiter rewrite (bytes).
_NORMALIZE_CHUNK_SIZE = 1 << 20


def _has_trailing_delimiter(path: Path) -> bool:
    """Probe the last bytes of ``path`` for a classic dbgen trailing delimiter.

    dbgen row framing is decided at compile time (EOL_HANDLING), so every row
    in a file shares the same framing; inspecting the file tail is sufficient
    to classify the whole file.
    """
    size = path.stat().st_size
    if size == 0:
        return False
    with path.open("rb") as handle:
        handle.seek(max(0, size - 2))
        tail = handle.read()
    return tail.endswith((b"|\n", b"|"))


def normalize_tbl_trailing_delimiters(path: Path) -> bool:
    """Strip exactly one trailing ``|`` before each newline, rewriting in place.

    Classic dbgen file mode (binaries without the BenchBox stdout-streaming
    patch, e.g. the bundled Linux dbgen) terminates every row with a field
    delimiter (``...|BUILDING|comment.|``), while the patched ``-z`` streaming
    mode does not. Normalizing file-mode output keeps generated data identical
    across platforms.

    Only the delimiter immediately before the line terminator is removed;
    interior empty fields are preserved. In ``.tbl`` format a trailing empty
    field is a delimiter artifact, not a NULL (see
    :func:`benchbox.utils.file_format.get_data_extension`).

    The rewrite streams fixed-size chunks through a temporary file, so large
    scale-factor outputs are never loaded into memory. Files that are already
    clean are detected with an O(1) tail probe and left untouched, which also
    makes the operation idempotent.

    Args:
        path: Uncompressed ``.tbl`` (or ``.tbl.N`` chunk) file to normalize.

    Returns:
        True if the file was rewritten, False if it was already clean.
    """
    if not _has_trailing_delimiter(path):
        return False

    tmp_path = path.with_name(path.name + ".normalize.tmp")
    try:
        with path.open("rb") as src, tmp_path.open("wb") as dst:
            carry = b""
            while True:
                chunk = src.read(_NORMALIZE_CHUNK_SIZE)
                if not chunk:
                    break
                data = carry + chunk
                # Hold back a chunk-final "|": it may be followed by "\n" in
                # the next chunk and must be stripped together with it.
                if data.endswith(b"|"):
                    carry = b"|"
                    data = data[:-1]
                else:
                    carry = b""
                # "\n" only occurs at row boundaries, so "|\n" is always the
                # trailing delimiter; str.replace removes exactly one "|" per
                # newline and never touches interior empty fields.
                dst.write(data.replace(b"|\n", b"\n"))
            # A held-back "|" at EOF means the final row is unterminated but
            # still carries the trailing delimiter; drop it.
        with contextlib.suppress(OSError):
            shutil.copystat(path, tmp_path)
        os.replace(tmp_path, path)
    finally:
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
    return True


class TPCHDataGenerator(CompressionMixin, CloudStorageGeneratorMixin, VerbosityMixin):
    """TPC-H data generator.

    Generates TPC-H benchmark data using the official TPC-H dbgen tool.
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: str | Path | None = None,
        verbose: int | bool = 0,
        quiet: bool = False,
        parallel: int = 1,
        force_regenerate: bool = False,
        **kwargs,
    ) -> None:
        """Initialize TPC-H data generator.

        Args:
            scale_factor: Scale factor (1.0 = ~1GB)
            output_dir: Directory to output generated data
            verbose: Whether to print verbose output during generation
            parallel: Number of parallel processes for data generation
            force_regenerate: Force data regeneration even if valid data exists
            **kwargs: Additional arguments including compression options
        """
        # Extract data organization config before passing kwargs to super
        self._data_organization_config = kwargs.pop("data_organization", None)
        if self._data_organization_config is None:
            raw_config = os.getenv("BENCHBOX_DATA_ORGANIZATION_CONFIG_JSON")
            if raw_config:
                try:
                    from benchbox.core.data_organization.config import DataOrganizationConfig

                    self._data_organization_config = DataOrganizationConfig.from_dict(json.loads(raw_config))
                except Exception as exc:
                    logging.getLogger("benchbox.core.tpch.generator").warning(
                        "Ignoring invalid BENCHBOX_DATA_ORGANIZATION_CONFIG_JSON: %s", exc
                    )

        # Initialize compression mixin
        super().__init__(**kwargs)

        self.scale_factor = scale_factor
        self.output_dir = create_path_handler(output_dir) if output_dir else Path.cwd() / "tpch_data"

        verbosity_settings = compute_verbosity(verbose, quiet)
        self.apply_verbosity(verbosity_settings)
        self.logger = logging.getLogger("benchbox.core.tpch.generator")

        self.parallel = parallel
        self.force_regenerate = force_regenerate

        # Initialize data validator with actual scale factor
        # TPC-H dbgen supports fractional scale factors for development
        self.validator = BenchmarkDataValidator("tpch", scale_factor)

        # Path to dbgen source - resolve from multiple candidate locations
        self._package_root = self._package_root_dir()
        resolved_path = self.resolve_dbgen_path()

        # Always record a concrete path for downstream helpers even when
        # bundled sources are absent so precompiled binaries can be used
        self.dbgen_path = resolved_path or (self._package_root / "_sources/tpc-h/dbgen")
        self.dbgen_available = resolved_path is not None
        self._dbgen_error: Exception | None = None

        # Validate parameters
        self._validate_parameters()

        # Defer dbgen initialization until needed (lazy loading)
        # When sources are absent, defer raising until generation is requested
        self._dbgen_exe = None

    @property
    def dbgen_exe(self) -> Path:
        """Get the dbgen executable, building it if necessary."""
        if self._dbgen_exe is None:
            try:
                self._dbgen_exe = self._find_or_build_dbgen()
                self.dbgen_available = self._dbgen_exe.exists()
                # Update dbgen_path to the directory containing the executable
                # This ensures dists.dss can be found when using precompiled binaries
                if self.dbgen_available:
                    self.dbgen_path = self._dbgen_exe.parent
            except (FileNotFoundError, RuntimeError, PermissionError) as exc:
                self.dbgen_available = False
                self._dbgen_error = exc
                self._raise_missing_dbgen()  # NoReturn - always raises
        assert self._dbgen_exe is not None  # Guaranteed by logic above
        return self._dbgen_exe

    def _validate_parameters(self) -> None:
        """Validate input parameters."""
        if self.scale_factor <= 0:
            raise ValueError(f"Scale factor must be positive, got {self.scale_factor}")

        # TPC-H dbgen supports fractional scale factors down to 0.01 for development/testing
        # Only enforce minimum scale factor for production usage (scale_factor >= 1.0)
        if self.scale_factor < 0.01:
            raise ValueError(
                f"Scale factor {self.scale_factor} is too small. "
                "TPC-H supports fractional scale factors down to 0.01 for development."
            )

        if self.scale_factor > 100000:
            raise ValueError(f"Scale factor {self.scale_factor} is too large (max 100000)")

        if self.parallel < 1:
            raise ValueError(f"Parallel processes must be >= 1, got {self.parallel}")

        if self.parallel > 64:
            raise ValueError(f"Too many parallel processes {self.parallel} (max 64)")

    @classmethod
    def _package_root_dir(cls) -> Path:
        """Return the project root directory (not package root).

        This is used to locate resources like sample data in examples/data/
        at the project root level.
        """
        return Path(__file__).parent.parent.parent.parent

    @classmethod
    def _candidate_dbgen_paths(cls) -> Iterator[Path]:
        """Yield candidate paths where dbgen sources might be located."""
        package_root = cls._package_root_dir()

        # Primary location: _sources in package root
        yield package_root / "_sources/tpc-h/dbgen"

        # Fallback: relative to current file
        yield Path(__file__).parent.parent / "_sources/tpc-h/dbgen"

        # Fallback: installed package location
        try:
            import benchbox

            if benchbox.__file__ is not None:
                module_path = Path(benchbox.__file__).parent
                yield module_path / "_sources/tpc-h/dbgen"
        except ImportError:
            return

    @classmethod
    def resolve_dbgen_path(cls) -> Path | None:
        """Resolve the dbgen source directory from candidate locations.

        Returns:
            Path to dbgen tools directory if found, None otherwise.
        """
        for candidate in cls._candidate_dbgen_paths():
            if candidate.exists():
                return candidate
        return None

    def has_dbgen_sources(self) -> bool:
        """Check if dbgen sources are available.

        Returns:
            True if dbgen sources are available, False otherwise.
        """
        return self.dbgen_available

    def _raise_missing_dbgen(self) -> NoReturn:
        """Raise an error when dbgen is not available for data generation."""
        import benchbox

        pkg_dir = Path(benchbox.__file__).parent
        binaries_path = pkg_dir / "_binaries/tpc-h"

        message = (
            "TPC-H dbgen tool not found. Pre-compiled binaries should be at "
            f"{binaries_path}/<platform>/ but were not found. "
            "This may indicate a corrupted or incomplete installation. "
            "Try reinstalling: pip install --force-reinstall benchbox"
        )
        if self._dbgen_error:
            message += f"\n\nDetails: {self._dbgen_error}"
        raise RuntimeError(message)

    def _find_or_build_dbgen(self) -> Path:
        """Find existing dbgen executable or build it if needed.

        Returns:
            Path to the dbgen executable
        """
        # Use auto-compilation utility
        results = ensure_tpc_binaries(["dbgen"], auto_compile=True)
        dbgen_result = results.get("dbgen")

        if (
            dbgen_result
            and dbgen_result.status
            in [
                CompilationStatus.SUCCESS,
                CompilationStatus.NOT_NEEDED,
                CompilationStatus.PRECOMPILED,
            ]
            and dbgen_result.binary_path
            and dbgen_result.binary_path.exists()
        ):
            self.log_verbose(f"Using dbgen binary: {dbgen_result.binary_path}")
            self.logger.info(f"Using dbgen binary: {dbgen_result.binary_path}")
            return dbgen_result.binary_path

        # Fallback to traditional build logic for backward compatibility
        system = platform.system().lower()
        dbgen_exe = self.dbgen_path / "dbgen.exe" if system == "windows" else self.dbgen_path / "dbgen"

        self.logger.debug(f"dbgen_exe path: {dbgen_exe}")
        if dbgen_exe.exists():
            self.log_verbose(f"Using existing dbgen executable: {dbgen_exe}")
            # Validate the executable is actually executable (X_OK is a no-op on Windows)
            if os.name != "nt" and not os.access(dbgen_exe, os.X_OK):
                raise PermissionError(f"dbgen executable at {dbgen_exe} is not executable")
            return dbgen_exe

        # If auto-compilation failed, provide detailed error
        error_msg = f"dbgen binary required but not found at {dbgen_exe}."
        if dbgen_result and dbgen_result.error_message:
            error_msg += f" Auto-compilation failed: {dbgen_result.error_message}"
        error_msg += " TPC-H requires the compiled dbgen tool to function."

        raise RuntimeError(error_msg)

    def _check_stdout_support(self) -> bool:
        """Check if dbgen supports the -z stdout flag.

        The -z flag enables streaming output to stdout instead of files,
        which allows direct piping to compression utilities.

        Returns:
            True if -z flag is supported, False otherwise.
        """
        if not hasattr(self, "_stdout_support_cached"):
            try:
                result = subprocess.run(
                    [str(self.dbgen_exe), "-h"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                # Check if -z appears in help output
                self._stdout_support_cached = "-z" in result.stderr or "-z" in result.stdout
            except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
                self._stdout_support_cached = False

        return self._stdout_support_cached

    def _generate_table_streaming(self, table_name: str, output_path: Path, work_dir: Path) -> Path:
        """Generate a single table using streaming stdout mode.

        Pipes dbgen -z output directly to compression, avoiding intermediate files.

        Args:
            table_name: Name of the table to generate
            output_path: Path for the output file (with compression extension)
            work_dir: Working directory with dists.dss

        Returns:
            Path to the generated (compressed) file
        """
        table_code = _TPCH_TABLE_CODES.get(table_name.lower())
        if not table_code:
            raise ValueError(f"Unknown TPC-H table: {table_name}")

        # Build dbgen command with -z for stdout output
        cmd = [
            str(self.dbgen_exe),
            "-z",  # Output to stdout
            "-q",  # Quiet mode (suppress progress to stderr)
            "-f",  # Force (overwrite if needed)
            "-s",
            str(self.scale_factor),
            "-T",
            table_code,  # Generate single table
        ]

        # Set up environment
        env = os.environ.copy()
        env["DSS_PATH"] = str(work_dir)
        env["DSS_CONFIG"] = str(work_dir)

        # Get compressor for streaming write
        compressor = self.get_compressor()

        try:
            # Start dbgen process with stdout pipe
            with subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=work_dir,
                env=env,
            ) as proc:
                if proc.stdout is None:
                    raise RuntimeError(f"Failed to capture stdout for {table_name}")

                # Stream directly to compressed file
                with compressor.open_for_write(output_path, "wb") as f:
                    # Read in chunks and write to compressed file
                    chunk_size = 64 * 1024  # 64KB chunks
                    while True:
                        chunk = proc.stdout.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)

                # Wait for process to complete and check return code
                proc.wait()
                if proc.returncode != 0:
                    stderr = proc.stderr.read().decode(errors="ignore") if proc.stderr else ""
                    raise RuntimeError(f"dbgen failed for table {table_name}: {stderr}")

            return output_path

        except OSError as e:
            # Clean up partial file on error
            if output_path.exists():
                with contextlib.suppress(OSError):
                    output_path.unlink()
            raise RuntimeError(f"Streaming generation failed for {table_name}: {e}") from e

    def _run_streaming_dbgen(self, work_dir: Path) -> dict[str, Path | list[Path]]:
        """Run dbgen with streaming output for all tables.

        Uses the -z flag to stream each table's output directly to compression,
        avoiding intermediate uncompressed files on disk.

        Args:
            work_dir: Working directory for data generation

        Returns:
            Dictionary mapping table names to compressed file paths
        """
        import concurrent.futures

        work_dir_path = Path(work_dir)
        work_dir_path.mkdir(parents=True, exist_ok=True)

        # Copy required files to work directory
        dists_file = self.dbgen_path / "dists.dss"
        if dists_file.exists():
            shutil.copy2(dists_file, work_dir_path / "dists.dss")

        # All TPC-H tables to generate
        tables = list(_TPCH_TABLE_CODES.keys())

        # Get compression extension
        ext = self.get_compressor().get_file_extension()

        # Generate all tables (can parallelize since -z generates one table at a time)
        results: dict[str, Path | list[Path]] = {}

        def generate_table(table_name: str) -> tuple[str, Path]:
            base_filename = f"{table_name}.tbl"
            output_path = work_dir_path / f"{base_filename}{ext}"
            result_path = self._generate_table_streaming(table_name, output_path, work_dir_path)
            return table_name, result_path

        if self.parallel > 1:
            # Generate tables in parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(self.parallel, len(tables))) as executor:
                futures = {executor.submit(generate_table, table): table for table in tables}

                for future in concurrent.futures.as_completed(futures):
                    table_name, file_path = future.result()
                    results[table_name] = file_path
                    self.log_verbose(f"Generated {table_name} via streaming: {file_path.name}")
        else:
            # Generate tables sequentially
            for table in tables:
                table_name, file_path = generate_table(table)
                results[table_name] = file_path
                self.log_verbose(f"Generated {table_name} via streaming: {file_path.name}")

        return results

    def _compile_dbgen(self, work_dir: Path) -> Path:
        """Compile the TPC-H dbgen tool.

        Args:
            work_dir: Working directory for compilation

        Returns:
            Path to the compiled dbgen executable
        """
        # Copy dbgen source to a temporary directory for building
        dbgen_build_dir = work_dir / "dbgen"
        shutil.copytree(self.dbgen_path, dbgen_build_dir)

        # Determine platform-specific settings
        system = platform.system().lower()
        if system == "linux":
            machine_flag = "LINUX"
        elif system == "darwin":
            machine_flag = "MACOS"
        elif system == "windows":
            machine_flag = "WIN32"
        else:
            # Default to Linux for unknown platforms
            machine_flag = "LINUX"

        # Run make to build dbgen
        try:
            cmd = [
                "make",
                "-f",
                "makefile.suite",
                "DATABASE=SQLSERVER",
                f"MACHINE={machine_flag}",
            ]
            subprocess.run(
                cmd,
                cwd=dbgen_build_dir,
                check=True,
                stdout=subprocess.PIPE if not self.verbose else None,
                stderr=subprocess.PIPE if not self.verbose else None,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to compile dbgen: {e}") from e

        # Check for the executable
        dbgen_exe = dbgen_build_dir / "dbgen.exe" if system == "windows" else dbgen_build_dir / "dbgen"

        if not dbgen_exe.exists():
            raise FileNotFoundError(f"dbgen executable not found at {dbgen_exe}")

        return dbgen_exe

    def _run_dbgen(self, dbgen_exe: Path, work_dir: Path) -> None:
        """Run the dbgen executable to generate data.

        Args:
            dbgen_exe: Path to the dbgen executable
            work_dir: Working directory for data generation
        """
        work_dir_path = Path(work_dir)
        work_dir_path.mkdir(parents=True, exist_ok=True)
        resolved_work_dir = work_dir_path.resolve()

        # Create output directory if it doesn't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Run dbgen to generate TPC-H data
        cmd = [
            str(dbgen_exe),
            "-vf",  # verbose, force overwrites
            "-s",
            str(self.scale_factor),  # scale factor
        ]

        try:
            subprocess.run(
                cmd,
                cwd=resolved_work_dir,
                check=True,
                stdout=subprocess.DEVNULL,  # Always suppress spinner output to prevent log bloat
                stderr=subprocess.PIPE,  # Capture errors for debugging
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to generate TPC-H data: {e}") from e

    def _move_data_files(self, work_dir: Path) -> dict[str, Path]:
        """Move generated data files to the output directory.

        Args:
            work_dir: Working directory where data was generated

        Returns:
            Dictionary mapping table names to paths of generated data files
        """
        # Map of TPC-H table names to their generated file names
        table_files = {
            "customer": "customer.tbl",
            "lineitem": "lineitem.tbl",
            "nation": "nation.tbl",
            "orders": "orders.tbl",
            "part": "part.tbl",
            "partsupp": "partsupp.tbl",
            "region": "region.tbl",
            "supplier": "supplier.tbl",
        }

        output_paths = {}

        # Debug: List all files in work_dir
        if self.very_verbose:
            contents = ", ".join(sorted(p.name for p in work_dir.glob("*")))
            self.logger.debug(f"Work directory contents before move: {contents}")

        for table, filename in table_files.items():
            source_path = work_dir / filename
            target_path = self.output_dir / filename

            # First try the working directory
            if source_path.exists():
                # Copy the file to the output directory
                shutil.copy2(source_path, target_path)
                output_paths[table] = target_path
                self.log_verbose(f"Copied {filename} from work_dir to {target_path}")
            else:
                # If not found in work_dir, check the dbgen source directory
                # This happens because dbgen sometimes generates files in its own directory
                source_path_alt = self.dbgen_path / filename
                if source_path_alt.exists():
                    # Copy the file to the output directory
                    shutil.copy2(source_path_alt, target_path)
                    output_paths[table] = target_path
                    self.log_verbose(f"Copied {filename} from dbgen_path to {target_path}")
                    # Clean up the file from the source directory to avoid confusion
                    try:
                        source_path_alt.unlink()
                    except (OSError, PermissionError):
                        self.log_very_verbose(f"Could not clean up {source_path_alt}")
                else:
                    # Log warnings for missing files regardless of verbose setting
                    self.logger.warning(
                        "Generated file %s not found at %s or %s",
                        filename,
                        source_path,
                        source_path_alt,
                    )

        return output_paths

    def _run_dbgen_native(self, work_dir: Path) -> dict[str, Path | list[Path]] | None:
        """Run the native dbgen executable to generate data.

        Args:
            work_dir: Working directory for data generation

        Returns:
            Dictionary mapping table names to file paths if streaming mode was used,
            None if traditional file-based generation was used.
        """
        work_dir_path = Path(work_dir)
        work_dir_path.mkdir(parents=True, exist_ok=True)
        resolved_work_dir = work_dir_path.resolve()

        # Create output directory if it doesn't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Check if we can use streaming mode (compression enabled + -z flag supported)
        # Streaming mode avoids intermediate files by piping dbgen output to compression
        use_streaming = (
            self.should_use_compression()
            and self.parallel == 1  # Streaming works per-table, not with -C chunks
            and self._check_stdout_support()
        )

        if use_streaming:
            self.log_verbose("Using streaming data generation with -z flag")
            return self._run_streaming_dbgen(work_dir_path)

        # Fall back to traditional file-based generation
        if self.should_use_compression() and not self._check_stdout_support():
            self.logger.warning("dbgen binary does not support -z flag; falling back to file-then-compress mode")

        # Proactively remove any existing TPC-H .tbl outputs to avoid permission/overwrite issues
        try:
            patterns = [
                "customer.tbl*",
                "lineitem.tbl*",
                "nation.tbl*",
                "orders.tbl*",
                "part.tbl*",
                "partsupp.tbl*",
                "region.tbl*",
                "supplier.tbl*",
                "delete.*",
                "*.u*",
            ]
            for pat in patterns:
                for f in work_dir_path.glob(pat):
                    try:
                        if f.is_file():
                            f.unlink()
                    except Exception:
                        # Ignore failures; dbgen -f will attempt to overwrite
                        pass
        except Exception:
            # Non-fatal: cleanup is best-effort
            pass

        # Copy required files to work directory so dbgen can always resolve them
        dists_file = self.dbgen_path / "dists.dss"
        if dists_file.exists():
            # Best-effort; if copy fails, we will still pass -b with original path
            with contextlib.suppress(OSError, shutil.Error):
                shutil.copy2(dists_file, work_dir_path / "dists.dss")

        if self.parallel > 1:
            # Generate data in parallel chunks
            self._run_parallel_dbgen(work_dir_path)
        else:
            # Single-threaded generation
            # Prefer using local dists.dss in work dir, else rely on DSS_CONFIG to dbgen source
            dists_in_workdir = work_dir_path / "dists.dss"
            dss_config_dir = str((work_dir_path if dists_in_workdir.exists() else dists_file.parent).resolve())

            cmd = [
                str(self.dbgen_exe),
                "-vf",  # verbose, force overwrites
                "-s",
                str(self.scale_factor),  # scale factor
            ]

            try:
                env = os.environ.copy()
                # Ensure dbgen finds distributions and writes into the work directory
                env["DSS_PATH"] = str(resolved_work_dir)
                # Some dbgen builds expect DSS_CONFIG to be a directory containing dists.dss
                env["DSS_CONFIG"] = dss_config_dir
                subprocess.run(
                    cmd,
                    cwd=resolved_work_dir,
                    check=True,
                    env=env,
                    stdout=subprocess.DEVNULL,  # Always suppress spinner output to prevent log bloat
                    stderr=subprocess.PIPE,  # Capture errors for debugging
                )

                # Ensure files are fully written to disk (sync may not be available on all systems)
                with contextlib.suppress(FileNotFoundError, subprocess.SubprocessError):
                    subprocess.run(["sync"], check=False, capture_output=True)

                import time

                time.sleep(0.2)  # Small delay to ensure files are written

                # Debug: Check what files were created after dbgen completes
                if self.very_verbose:
                    created = ", ".join(sorted(p.name for p in work_dir_path.glob("*")))
                    self.logger.debug(f"Files after dbgen: {created}")

            except subprocess.CalledProcessError as e:
                stderr = (
                    e.stderr.decode(errors="ignore") if isinstance(e.stderr, (bytes, bytearray)) else (e.stderr or "")
                )
                stdout = (
                    e.stdout.decode(errors="ignore") if isinstance(e.stdout, (bytes, bytearray)) else (e.stdout or "")
                )
                error_msg = f"Failed to generate TPC-H data with exit code {e.returncode}: {stderr.strip()}"
                if stdout:
                    error_msg += f"\nOutput: {stdout.strip()}"
                raise RuntimeError(error_msg) from e

        # File-based generation was used
        return None

    def _run_parallel_dbgen(self, work_dir: Path) -> None:
        """Run dbgen in parallel to generate data faster.

        Args:
            work_dir: Working directory for data generation
        """
        import concurrent.futures

        work_dir_path = Path(work_dir)
        work_dir_path.mkdir(parents=True, exist_ok=True)
        resolved_work_dir = work_dir_path.resolve()

        # Copy required files to work directory
        dists_file = self.dbgen_path / "dists.dss"
        if dists_file.exists():
            shutil.copy2(dists_file, work_dir_path / "dists.dss")

        def generate_chunk(chunk_id: int) -> None:
            """Generate a specific chunk of data."""
            # Prefer using local dists.dss in work dir, else rely on DSS_CONFIG to dbgen source
            dists_in_workdir = work_dir_path / "dists.dss"
            dss_config_dir = str((work_dir_path if dists_in_workdir.exists() else dists_file.parent).resolve())

            cmd = [
                str(self.dbgen_exe),
                "-vf",  # verbose, force overwrites
                "-s",
                str(self.scale_factor),  # scale factor
                "-S",
                str(chunk_id),  # chunk number (1-based)
                "-C",
                str(self.parallel),  # total number of chunks
            ]

            try:
                env = os.environ.copy()
                # Provide absolute paths so dbgen never writes to unintended directories
                env["DSS_PATH"] = str(resolved_work_dir)
                env["DSS_CONFIG"] = dss_config_dir
                subprocess.run(
                    cmd,
                    cwd=resolved_work_dir,
                    check=True,
                    env=env,
                    stdout=subprocess.DEVNULL,  # Always suppress spinner output to prevent log bloat
                    stderr=subprocess.PIPE,  # Capture errors for debugging
                )
            except subprocess.CalledProcessError as e:
                error_msg = f"Failed to generate TPC-H data chunk {chunk_id} with exit code {e.returncode}"
                if e.stderr:
                    error_msg += f": {e.stderr}"
                if e.stdout:
                    error_msg += f"\nOutput: {e.stdout}"
                raise RuntimeError(error_msg) from e

        # Generate chunks in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.parallel) as executor:
            futures = []
            for chunk_id in range(1, self.parallel + 1):
                future = executor.submit(generate_chunk, chunk_id)
                futures.append(future)

            # Wait for all chunks to complete
            for future in concurrent.futures.as_completed(futures):
                future.result()  # This will raise any exceptions that occurred

    def generate(self) -> dict[str, Path | list[Path]]:
        """Generate TPC-H benchmark data using native C executable.

        Returns:
            Dictionary mapping table names to file path(s). For single files,
            returns a Path. For sharded files (parallel generation), returns a
            list of Paths.

        Raises:
            RuntimeError: If data generation fails
            PermissionError: If output directory cannot be created or written to
            FileNotFoundError: If dbgen executable is not found
        """
        # Use centralized cloud/local generation handler
        return self._handle_cloud_or_local_generation(self.output_dir, self._generate_local, self.verbose)

    def _generate_local(self, output_dir: Path | None = None) -> dict[str, Path | list[Path]]:
        """Generate data locally (original implementation)."""
        # Trigger lazy loading of dbgen_exe, which will find precompiled binaries
        # if sources are not available. This raises _raise_missing_dbgen() if neither
        # sources nor precompiled binaries are found.
        _ = self.dbgen_exe

        # Use provided output directory or fall back to instance output_dir
        target_dir = output_dir if output_dir is not None else self.output_dir

        # Create output directory
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise PermissionError(f"Cannot create output directory {target_dir}: {e}") from e

        # Validate output directory is writable
        if not os.access(target_dir, os.W_OK):
            raise PermissionError(f"Output directory {target_dir} is not writable")

        # Smart data generation: check if valid data already exists
        # CloudStagingPath/DatabricksPath expose local cache paths for validation
        should_regenerate, validation_result = self.validator.should_regenerate_data(target_dir, self.force_regenerate)

        if not should_regenerate:
            if self.verbose_enabled:
                self.logger.info("✅ Valid TPC-H data found for scale factor %s", self.scale_factor)
                self.validator.print_validation_report(validation_result, verbose=False)
                self.logger.info("Skipping data generation (existing data is valid)")

            return self._collect_existing_table_files(target_dir)

        removed_stale = self._prune_stale_table_artifacts(target_dir)
        if removed_stale and self.verbose_enabled:
            self.logger.info("Removed %d stale TPC-H table artifacts before regeneration", len(removed_stale))

        sample_dir = self._get_sample_data_dir()
        if sample_dir is not None:
            self.log_verbose(f"⚡ Using bundled TPC-H sample dataset for scale factor {self.scale_factor}")
            self._copy_sample_dataset(sample_dir, target_dir)
            return self._finalize_generation(target_dir)

        # Data generation needed
        if output_dir is None:
            if validation_result and validation_result.issues:
                self.logger.warning("⚠️️  Data validation failed for scale factor %s", self.scale_factor)
                if self.verbose_enabled:
                    self.validator.print_validation_report(validation_result, verbose=True)
            elif self.force_regenerate and self.verbose_enabled:
                self.logger.info("⚠️️ Force regeneration requested")

        self.log_operation_start(
            "TPC-H data generation",
            details=f"scale_factor={self.scale_factor}, parallel={self.parallel}",
        )

        # Run native dbgen to generate data directly in the target directory
        # Returns dict if streaming was used, None for file-based generation
        streaming_result = self._run_dbgen_native(target_dir)

        if streaming_result is not None:
            # Streaming mode was used - files are already compressed
            self._write_manifest(target_dir, streaming_result)
            self.log_operation_complete("TPC-H data generation (streaming)")
            return streaming_result

        result = self._finalize_generation(target_dir)
        self.log_operation_complete("TPC-H data generation")
        return result

    def _collect_existing_table_files(self, target_dir: Path) -> dict[str, Path | list[Path]]:
        """Collect existing table files from target directory.

        Returns:
            Dictionary mapping table names to file path(s). For single files,
            returns a Path. For sharded files, returns a list of Paths.
        """
        table_files = {
            "customer": "customer.tbl",
            "lineitem": "lineitem.tbl",
            "nation": "nation.tbl",
            "orders": "orders.tbl",
            "part": "part.tbl",
            "partsupp": "partsupp.tbl",
            "region": "region.tbl",
            "supplier": "supplier.tbl",
        }

        existing: dict[str, Path | list[Path]] = {}
        for table, filename in table_files.items():
            # Check for compressed files first (regardless of current compression setting)
            # Data may have been generated with compression even if not requested now
            # Use centralized compression extensions for comprehensive coverage
            for ext in COMPRESSION_EXTENSIONS:
                compressed_file = target_dir / f"{filename}{ext}"
                if compressed_file.exists():
                    existing[table] = compressed_file
                    break

                # Check for sharded compressed files (e.g., customer.tbl.1.zst)
                compressed_chunks = [
                    cf
                    for cf in target_dir.glob(f"{filename}.*{ext}")
                    if cf.name.replace(ext, "").split(".")[-1].isdigit()
                ]
                if compressed_chunks:
                    # Return ALL shards sorted by name, not just the first one
                    existing[table] = sorted(compressed_chunks, key=lambda f: f.name)
                    break
            else:
                # No compressed files found, check for uncompressed
                tbl_file = target_dir / filename
                if tbl_file.exists():
                    existing[table] = tbl_file
                    continue

                # Check for sharded uncompressed files (e.g., customer.tbl.1)
                chunk_files = [cf for cf in target_dir.glob(f"{filename}.*") if cf.name.split(".")[-1].isdigit()]
                if chunk_files:
                    # Return ALL shards sorted by name, not just the first one
                    existing[table] = sorted(chunk_files, key=lambda f: f.name)

        return existing

    def _prune_stale_table_artifacts(self, target_dir: Path) -> list[Path]:
        """Remove stale per-table artifacts before regeneration.

        This prevents coexistence of raw, sharded, and compressed variants
        from previous generation modes.

        Args:
            target_dir: Directory containing generated TPCH artifacts.

        Returns:
            List of deleted file paths.
        """
        table_files = (
            "customer",
            "lineitem",
            "nation",
            "orders",
            "part",
            "partsupp",
            "region",
            "supplier",
        )
        return prune_stale_table_artifacts(
            target_dir=target_dir,
            table_names=table_files,
            pattern=TableArtifactPattern(
                single_suffix=".tbl",
                raw_shard_glob_template="{table}.tbl.*",
                compressed_shard_glob_template="{table}.tbl.*{ext}",
                shard_regex_template=r"^{table}\.tbl\.\d+(?:\.[a-z0-9]+)?$",
            ),
            compression_extensions=COMPRESSION_EXTENSIONS,
            use_compression=self.should_use_compression(),
            expect_sharded=int(getattr(self, "parallel", 1) or 1) > 1,
        )

    def _get_sample_data_dir(self) -> Path | None:
        if self.scale_factor >= 1:
            return None
        if not self.should_use_compression():
            return None
        sf_label = format_scale_factor(self.scale_factor)
        candidate = self._package_root / "examples" / "data" / f"tpch_{sf_label}"
        return candidate if candidate.exists() else None

    def _copy_sample_dataset(self, sample_dir: Path, target_dir: Path) -> None:
        # Clear existing contents
        for child in target_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

        for item in sample_dir.iterdir():
            destination = target_dir / item.name
            if item.is_dir():
                shutil.copytree(item, destination)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, destination)

    def _finalize_generation(self, target_dir: Path) -> dict[str, Path | list[Path]]:
        """Finalize data generation and return table paths.

        Returns:
            Dictionary mapping table names to file path(s). For single files,
            returns a Path. For sharded files, returns a list of Paths.
        """
        table_paths, precompressed_tables = self._gather_generated_table_paths(target_dir)

        # Classic (non -z) dbgen writes a trailing field delimiter on every
        # row. Normalize file-mode output before any compression or data
        # organization so results match the streaming path byte-for-byte
        # (release PR #1043 canary: the bundled Linux dbgen lacks the stdout
        # patch, falls back to file mode, and emitted trailing pipes).
        self._normalize_table_delimiters(table_paths, precompressed_tables)

        # Data organization is a post-generation output mode. When configured,
        # prefer organized outputs over raw compression artifacts.
        if self._data_organization_config is not None:
            table_paths = self._apply_data_organization(target_dir, table_paths)
            self._write_manifest(target_dir, table_paths)
            return table_paths

        if self.should_use_compression():
            compressed_paths = self._compress_table_paths(target_dir, table_paths, precompressed_tables)

            if self.verbose_enabled and compressed_paths:
                flat_paths = {k: (v[0] if isinstance(v, list) else v) for k, v in compressed_paths.items()}
                self.print_compression_report(flat_paths)

            self._validate_file_format_consistency(target_dir)
            self._write_manifest(target_dir, compressed_paths)
            return compressed_paths

        self._write_manifest(target_dir, table_paths)
        return table_paths

    def _normalize_table_delimiters(
        self,
        table_paths: dict[str, Path | list[Path]],
        precompressed_tables: set[str],
    ) -> None:
        """Strip classic dbgen trailing row delimiters from uncompressed outputs.

        Covers both single-file mode (``customer.tbl``) and parallel chunked
        mode (``customer.tbl.1`` ... ``customer.tbl.N``). Pre-compressed
        tables are skipped: they come from the streaming (-z) path or a
        previous run and are already normalized.
        """
        for table_name, paths in table_paths.items():
            if table_name in precompressed_tables:
                continue
            for file_path in paths if isinstance(paths, list) else [paths]:
                if normalize_tbl_trailing_delimiters(file_path):
                    self.log_verbose(f"Stripped trailing row delimiters from {file_path.name}")

    def _apply_data_organization(
        self,
        target_dir: Path,
        table_paths: dict[str, Path | list[Path]],
    ) -> dict[str, Path | list[Path]]:
        """Post-process generated TBL files into sorted Parquet.

        Reads the TBL source files and writes sorted Parquet files alongside them.
        Returns updated table_paths with Parquet paths replacing TBL paths for
        tables that have sort columns configured.

        Args:
            target_dir: Directory containing generated TBL files.
            table_paths: Current table name → path mapping (TBL files).

        Returns:
            Updated table_paths with Parquet paths for sorted tables.
        """
        from benchbox.core.data_organization.sorting import SortedParquetWriter

        config = self._data_organization_config
        writer = SortedParquetWriter(config, schema_registry=self._build_schema_registry())
        result = dict(table_paths)

        for table_name, paths in table_paths.items():
            sort_columns = config.get_sort_columns_for_table(table_name)
            partition_columns = config.get_partition_columns_for_table(table_name)
            cluster_columns = config.get_cluster_columns_for_table(table_name)
            if not sort_columns and not partition_columns and not cluster_columns:
                continue

            # Normalize to list of source files
            source_files = paths if isinstance(paths, list) else [paths]

            parquet_path = writer.write_sorted_parquet(
                table_name=table_name,
                source_files=source_files,
                output_dir=target_dir,
            )
            result[table_name] = parquet_path

        return result

    def _build_schema_registry(self) -> dict[str, dict[str, Any]]:
        """Build table schema mapping for sorted writer column resolution."""
        from benchbox.core.tpch.schema import TABLES

        schema_registry: dict[str, dict[str, Any]] = {}
        for table in TABLES:
            schema_registry[table.name.lower()] = {
                "name": table.name.lower(),
                "columns": [
                    {
                        "name": col.name,
                        "type": col.get_sql_type(),
                    }
                    for col in table.columns
                ],
            }
        return schema_registry

    def _gather_generated_table_paths(self, target_dir: Path) -> tuple[dict[str, Path | list[Path]], set[str]]:
        """Locate generated table files from various possible locations.

        Returns:
            Tuple of (table_paths dict, set of already-compressed table names).
        """
        table_files = {
            "customer": "customer.tbl",
            "lineitem": "lineitem.tbl",
            "nation": "nation.tbl",
            "orders": "orders.tbl",
            "part": "part.tbl",
            "partsupp": "partsupp.tbl",
            "region": "region.tbl",
            "supplier": "supplier.tbl",
        }

        table_paths: dict[str, Path | list[Path]] = {}
        precompressed_tables: set[str] = set()
        for table_name, filename in table_files.items():
            if self.should_use_compression():
                compressed_filename = self.get_compressed_filename(filename)
                compressed_path = target_dir / compressed_filename
                if compressed_path.exists():
                    table_paths[table_name] = compressed_path
                    precompressed_tables.add(table_name)
                    self.log_verbose(f"Found pre-compressed file {compressed_filename} for {table_name}")
                    continue

            tbl_file = target_dir / filename
            if tbl_file.exists():
                table_paths[table_name] = tbl_file
                self.log_verbose(f"Generated {filename} at {tbl_file}")
                continue

            chunk_files = [
                target_dir / f"{filename}.{chunk_id}"
                for chunk_id in range(1, self.parallel + 1)
                if (target_dir / f"{filename}.{chunk_id}").exists()
            ]
            if chunk_files:
                sorted_chunks = sorted(chunk_files, key=lambda f: f.name)
                table_paths[table_name] = sorted_chunks
                self.log_verbose(f"Generated {len(chunk_files)} chunk files for {table_name}")
                continue

            # Try recovering files from dbgen source or binary directories
            source_file = self.dbgen_path / filename
            binary_dir = self.dbgen_exe.parent
            binary_source_file = binary_dir / filename
            if source_file.exists():
                shutil.move(str(source_file), str(tbl_file))
                table_paths[table_name] = tbl_file
                self.log_verbose(f"Moved {filename} from dbgen source path to {tbl_file}")
                continue
            if binary_source_file.exists():
                shutil.move(str(binary_source_file), str(tbl_file))
                table_paths[table_name] = tbl_file
                self.log_verbose(f"Moved {filename} from dbgen binary path to {tbl_file}")
                continue

            self.logger.warning(
                "Generated file %s not found in %s, %s, or %s",
                filename,
                target_dir,
                source_file,
                binary_source_file,
            )

        return table_paths, precompressed_tables

    def _compress_table_paths(
        self,
        target_dir: Path,
        table_paths: dict[str, Path | list[Path]],
        precompressed_tables: set[str],
    ) -> dict[str, Path | list[Path]]:
        """Compress all uncompressed table files and return updated paths."""
        compressed_paths: dict[str, Path | list[Path]] = {}
        for table_name, file_path_or_paths in table_paths.items():
            if table_name in precompressed_tables:
                compressed_paths[table_name] = file_path_or_paths
                continue

            if isinstance(file_path_or_paths, list):
                compressed_chunks = self._compress_file_list(file_path_or_paths)
                if compressed_chunks:
                    compressed_paths[table_name] = sorted(compressed_chunks, key=lambda f: f.name)
            else:
                compressed_paths[table_name] = self._compress_single_or_legacy_shards(target_dir, file_path_or_paths)

        return compressed_paths

    def _compress_file_list(self, file_paths: list[Path]) -> list[Path]:
        """Compress a list of shard files, returning compressed paths."""
        compressed_chunk_files = []
        for chunk_file in file_paths:
            compressed_chunk = self.compress_existing_file(chunk_file, remove_original=True)
            compressed_chunk_files.append(compressed_chunk)
            self.log_verbose(f"Compressed {chunk_file.name} to {compressed_chunk.name}")
        return compressed_chunk_files

    def _compress_single_or_legacy_shards(self, target_dir: Path, file_path: Path) -> Path | list[Path]:
        """Compress a single file or discover and compress legacy shards."""
        filename = file_path.name
        if "." in filename and filename.split(".")[-1].isdigit():
            # Legacy path for single shard reference
            base_filename = ".".join(filename.split(".")[:-1])
            chunk_files = [cf for cf in target_dir.glob(f"{base_filename}.*") if cf.name.split(".")[-1].isdigit()]
            compressed_chunks = self._compress_file_list(chunk_files)
            if compressed_chunks:
                return sorted(compressed_chunks, key=lambda f: f.name)
            return file_path  # fallback: return original if nothing compressed

        compressed_file = self.compress_existing_file(file_path, remove_original=True)
        self.log_verbose(f"Compressed {file_path.name} to {compressed_file.name}")
        return compressed_file

    def _validate_file_format_consistency(self, target_dir: Path) -> None:
        """Ensure format invariants under compression for TPCH outputs."""
        if not self.should_use_compression():
            return
        # No raw .tbl files should remain
        raw_tbl = list(target_dir.glob("*.tbl"))
        if raw_tbl:
            names = ", ".join(f.name for f in raw_tbl[:5])
            more = "..." if len(raw_tbl) > 5 else ""
            raise RuntimeError(
                f"File format consistency violation: Found raw .tbl files with compression enabled: {names}{more}"
            )
        # No empty compressed files
        ext = self.get_compressor().get_file_extension()
        compressed = list(target_dir.glob(f"*.tbl{ext}"))
        empties = [f for f in compressed if f.stat().st_size <= (9 if ext == ".zst" else 20)]
        if empties:
            names = ", ".join(f.name for f in empties[:5])
            more = "..." if len(empties) > 5 else ""
            raise RuntimeError(f"File format consistency violation: Found empty compressed files: {names}{more}")

    def _write_manifest(self, output_dir: Path, table_paths: dict[str, Path | list[Path]]) -> None:
        if not table_paths:
            return

        manifest = DataGenerationManifest(
            output_dir=output_dir,
            benchmark="tpch",
            scale_factor=self.scale_factor,
            compression=resolve_compression_metadata(self),
            parallel=self.parallel,
            seed=getattr(self, "seed", None),
        )

        # Collect ALL chunk files for each table
        for table, file_path_or_paths in table_paths.items():
            expected_rows_total = self._expected_row_count(table)

            # Handle list of paths directly (new code path)
            if isinstance(file_path_or_paths, list):
                chunk_files = file_path_or_paths
                if chunk_files:
                    rows_per_chunk = expected_rows_total // len(chunk_files)
                    for chunk_file in chunk_files:
                        manifest.add_entry(table, chunk_file, row_count=rows_per_chunk)
                    self.log_very_verbose(f"Added {len(chunk_files)} chunk files for {table} to manifest")
                continue

            # Single Path - check if it represents a sharded file (legacy path)
            first_file_path = file_path_or_paths
            filename = first_file_path.name
            is_sharded = False
            pattern = ""

            # Detect sharding pattern: filename.ext.N or filename.ext.N.compression
            parts = filename.split(".")
            if len(parts) >= 3 and parts[-2].isdigit():
                # Pattern: customer.tbl.1.zst (has compression)
                is_sharded = True
                base_parts = parts[:-2]  # ['customer', 'tbl']
                compression_ext = parts[-1]  # 'zst'
                pattern = f"{'.'.join(base_parts)}.*{compression_ext}"
            elif len(parts) >= 2 and parts[-1].isdigit():
                # Pattern: customer.tbl.1 (no compression)
                is_sharded = True
                base_parts = parts[:-1]  # ['customer', 'tbl']
                pattern = f"{'.'.join(base_parts)}.*"

            if is_sharded and pattern:
                # Find all chunk files matching the pattern
                chunk_files = sorted(
                    [
                        f
                        for f in output_dir.glob(pattern)
                        if f.name.split(".")[-2 if self.should_use_compression() else -1].isdigit()
                    ]
                )

                if chunk_files:
                    # Distribute row count across chunks (approximately equal)
                    rows_per_chunk = expected_rows_total // len(chunk_files) if chunk_files else expected_rows_total

                    for chunk_file in chunk_files:
                        manifest.add_entry(table, chunk_file, row_count=rows_per_chunk)

                    self.log_very_verbose(f"Added {len(chunk_files)} chunk files for {table} to manifest")
                    continue

            # Single file (not sharded)
            manifest.add_entry(table, first_file_path, row_count=expected_rows_total)

        manifest.write()

    def _expected_row_count(self, table: str) -> int:
        base = _TPCH_BASE_ROW_COUNTS.get(table.lower())
        if base is None:
            return 0
        if table.lower() in {"nation", "region"}:
            return base
        return max(0, int(round(base * float(self.scale_factor))))

    # No post-generation compressed-file counting; counts captured during compression or plain-text counting for uncompressed
