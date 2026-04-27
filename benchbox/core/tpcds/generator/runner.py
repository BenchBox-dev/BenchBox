"""Execution helpers for invoking the TPC-DS dsdgen binaries."""

from __future__ import annotations

import concurrent.futures
import os
import platform
import shutil
import subprocess
from pathlib import Path

from benchbox.utils.printing import emit
from benchbox.utils.tpc_compilation import CompilationStatus, ensure_tpc_binaries


class DsdgenRunnerMixin:
    """Mixin providing native and parallel dsdgen execution helpers."""

    def _find_or_build_dsdgen(self) -> Path:
        """Find existing dsdgen executable or build it if needed.

        Returns:
            Path to the dsdgen executable
        """
        import logging

        logger = logging.getLogger(__name__)

        # Use auto-compilation utility
        results = ensure_tpc_binaries(["dsdgen"], auto_compile=True)
        dsdgen_result = results.get("dsdgen")

        if (
            dsdgen_result
            and dsdgen_result.status
            in [
                CompilationStatus.SUCCESS,
                CompilationStatus.NOT_NEEDED,
                CompilationStatus.PRECOMPILED,
            ]
            and dsdgen_result.binary_path
            and dsdgen_result.binary_path.exists()
        ):
            if self.verbose:
                emit(f"Using dsdgen binary: {dsdgen_result.binary_path}")
            logger.info(f"Using dsdgen binary: {dsdgen_result.binary_path}")
            return dsdgen_result.binary_path

        # Fallback to traditional build logic for backward compatibility
        system = platform.system().lower()
        dsdgen_exe = self.dsdgen_path / "dsdgen.exe" if system == "windows" else self.dsdgen_path / "dsdgen"

        if dsdgen_exe.exists():
            if self.verbose:
                emit(f"Using existing dsdgen executable: {dsdgen_exe}")
            # Validate the executable is actually executable (X_OK is a no-op on Windows)
            if os.name != "nt" and not os.access(dsdgen_exe, os.X_OK):
                raise PermissionError(f"dsdgen executable at {dsdgen_exe} is not executable")
            return dsdgen_exe

        # If auto-compilation failed, provide detailed error
        error_msg = f"dsdgen binary required but not found at {dsdgen_exe}."
        if dsdgen_result and dsdgen_result.error_message:
            error_msg += f" Auto-compilation failed: {dsdgen_result.error_message}"
        error_msg += " TPC-DS requires the compiled dsdgen tool to function."

        raise RuntimeError(error_msg)

    def _run_dsdgen_native(self, output_dir: Path) -> None:
        """Run the native dsdgen executable to generate data.

        Args:
            output_dir: Output directory for data generation
        """
        # Copy required files to output directory
        tpcds_idx = self.dsdgen_path / "tpcds.idx"
        if tpcds_idx.exists():
            shutil.copy2(tpcds_idx, output_dir / "tpcds.idx")

        # Copy other required data files
        for data_file in [
            "tpcds.dst",
            "english.dst",
            "names.dst",
            "streets.dst",
            "cities.dst",
            "fips.dst",
            "items.dst",
            "scaling.dst",
        ]:
            src_file = self.dsdgen_path / data_file
            if src_file.exists():
                shutil.copy2(src_file, output_dir / data_file)

        if self.parallel > 1:
            # Try parallel generation first, fallback to single-threaded if it fails
            try:
                self._run_parallel_dsdgen(output_dir)
            except RuntimeError as e:
                # Don't mask the real problem with fallback - parallel generation should work
                raise RuntimeError(f"Parallel TPC-DS generation failed: {e}") from e
        else:
            # Single-threaded generation
            self._run_single_threaded_dsdgen(output_dir)

    def _run_single_threaded_dsdgen(self, output_dir: Path) -> None:
        """Run single-threaded dsdgen generation.

        Args:
            output_dir: Output directory for data generation
        """
        # Use streaming compression if enabled, otherwise fall back to file-based generation
        if self.should_use_compression():
            self._run_streaming_dsdgen(output_dir)
        else:
            self._run_file_based_dsdgen(output_dir)

    def _run_streaming_dsdgen(self, output_dir: Path) -> None:
        """Run dsdgen with streaming compression table-by-table.

        Args:
            output_dir: Output directory for data generation
        """
        # Copy required distribution files to output directory
        self._copy_distribution_files(output_dir)

        # Get list of TPC-DS parent tables (child tables are generated with their parents)
        # catalog_returns is generated with catalog_sales
        # store_returns is generated with store_sales
        # web_returns is generated with web_sales
        parent_table_names = [
            "call_center",
            "catalog_page",
            "catalog_sales",  # catalog_sales generates catalog_returns too
            "customer",
            "customer_address",
            "customer_demographics",
            "date_dim",
            "household_demographics",
            "income_band",
            "inventory",
            "item",
            "promotion",
            "reason",
            "ship_mode",
            "store",
            "store_sales",  # store_sales generates store_returns too
            "time_dim",
            "warehouse",
            "web_page",
            "web_sales",  # web_sales generates web_returns too
            "web_site",
        ]

        # Generate each parent table with streaming compression
        # Child tables (catalog_returns, store_returns, web_returns) will be generated automatically
        for table_name in parent_table_names:
            self._generate_table_with_streaming(output_dir, table_name)

        # Generate dbgen_version table (required by TPC-DS specification)
        # This table is not parallelized and generates as a single file
        self._generate_single_table_streaming(output_dir, "dbgen_version")

    def _run_file_based_dsdgen(self, output_dir: Path) -> None:
        """Run traditional file-based dsdgen generation (no compression).

        Args:
            output_dir: Output directory for data generation
        """
        cmd = [
            str(self.dsdgen_exe),
            "-verbose",  # verbose output
            "-force",  # force overwrites
            "-terminate",
            "n",  # disable trailing field delimiters
            "-scale",
            str(self.scale_factor),  # scale factor
        ]

        try:
            # Copy required distribution files to output directory
            self._copy_distribution_files(output_dir)

            env = os.environ.copy()
            subprocess.run(
                cmd,
                cwd=output_dir,
                check=True,
                env=env,
                stdout=subprocess.DEVNULL,  # Always suppress spinner output to prevent log bloat
                stderr=None if self.verbose else subprocess.PIPE,  # Show errors in verbose mode for debugging
            )

            # Ensure files are fully written to disk
            try:
                subprocess.run(["sync"], check=False, capture_output=True)  # Unix sync command
            except (FileNotFoundError, subprocess.SubprocessError):
                pass  # sync command may not be available on all systems

            import time

            time.sleep(0.2)  # Small delay to ensure files are written

            # Debug: Check what files were created after dsdgen completes
            if self.verbose:
                emit(f"Files after dsdgen: {list(output_dir.glob('*.dat'))}")

        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to generate TPC-DS data with exit code {e.returncode}"
            if e.stderr:
                error_msg += f": {e.stderr}"
            if e.stdout and self.verbose:
                error_msg += f"\nOutput: {e.stdout}"
            raise RuntimeError(error_msg) from e

    def _run_parallel_dsdgen(self, output_dir: Path) -> None:
        """Run dsdgen in parallel to generate data faster.

        Args:
            output_dir: Output directory for data generation
        """
        # Use streaming compression if enabled, otherwise fall back to file-based generation
        if self.should_use_compression():
            self._run_parallel_streaming_dsdgen(output_dir)
        else:
            self._run_parallel_file_based_dsdgen(output_dir)

    def _run_parallel_streaming_dsdgen(self, output_dir: Path) -> None:
        """Run parallel dsdgen with streaming compression.

        Args:
            output_dir: Output directory for data generation
        """
        # Copy required distribution files to output directory
        self._copy_distribution_files(output_dir)

        # Get list of TPC-DS parent tables (child tables are generated with their parents)
        parent_table_names = [
            "call_center",
            "catalog_page",
            "catalog_sales",  # catalog_sales generates catalog_returns too
            "customer",
            "customer_address",
            "customer_demographics",
            "date_dim",
            "household_demographics",
            "income_band",
            "inventory",
            "item",
            "promotion",
            "reason",
            "ship_mode",
            "store",
            "store_sales",  # store_sales generates store_returns too
            "time_dim",
            "warehouse",
            "web_page",
            "web_sales",  # web_sales generates web_returns too
            "web_site",
        ]

        def generate_table_chunk(args):
            """Generate a specific table chunk with streaming compression."""
            table_name, chunk_id = args

            # Check if this is a parent table that generates child tables
            child_tables = {
                "catalog_sales": ["catalog_returns"],
                "store_sales": ["store_returns"],
                "web_sales": ["web_returns"],
            }

            if table_name in child_tables:
                # For parent tables, use file-based generation then compress
                self._generate_parent_table_chunk_with_children(
                    output_dir, table_name, chunk_id, child_tables[table_name]
                )
            else:
                # For single tables, use direct streaming compression
                self._generate_single_table_chunk_streaming(output_dir, table_name, chunk_id)

        # Generate table chunks in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.parallel) as executor:
            futures = []
            # Create tasks for each table and chunk combination
            for table_name in parent_table_names:
                for chunk_id in range(1, self.parallel + 1):
                    future = executor.submit(generate_table_chunk, (table_name, chunk_id))
                    futures.append(future)

            # Wait for all chunks to complete and collect errors
            errors = []
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    errors.append(str(e))

            # Raise comprehensive error if any tasks failed
            if errors:
                error_summary = f"TPC-DS parallel generation failed with {len(errors)} errors:\n"
                error_summary += "\n".join(f"  - {err}" for err in errors[:5])
                if len(errors) > 5:
                    error_summary += f"\n  ... and {len(errors) - 5} more errors"
                raise RuntimeError(error_summary)

        # Generate dbgen_version table after parallel generation completes
        # This table is not parallelized and generates as a single file
        self._generate_single_table_streaming(output_dir, "dbgen_version")

    def _run_parallel_file_based_dsdgen(self, output_dir: Path) -> None:
        """Run traditional parallel file-based dsdgen generation (no compression).

        Args:
            output_dir: Output directory for data generation
        """

        def generate_chunk(chunk_id: int) -> None:
            """Generate a specific chunk of data."""
            cmd = [
                str(self.dsdgen_exe),
                "-verbose",  # verbose output
                "-force",  # force overwrites
                "-terminate",
                "n",  # disable trailing field delimiters
                "-scale",
                str(self.scale_factor),  # scale factor
                "-child",
                str(chunk_id),  # chunk number (1-based)
                "-parallel",
                str(self.parallel),  # total number of chunks
            ]

            try:
                env = os.environ.copy()
                subprocess.run(
                    cmd,
                    cwd=output_dir,
                    check=True,
                    env=env,
                    stdout=subprocess.DEVNULL,  # Always suppress spinner output to prevent log bloat
                    stderr=None if self.verbose else subprocess.PIPE,  # Show errors in verbose mode for debugging
                )
            except subprocess.CalledProcessError as e:
                error_msg = f"Failed to generate TPC-DS data chunk {chunk_id} with exit code {e.returncode}"
                if e.stderr:
                    error_msg += f": {e.stderr}"
                raise RuntimeError(error_msg) from e

        # Copy required distribution files to output directory
        self._copy_distribution_files(output_dir)

        # Generate chunks in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.parallel) as executor:
            futures = []
            for chunk_id in range(1, self.parallel + 1):
                future = executor.submit(generate_chunk, chunk_id)
                futures.append(future)

            # Wait for all chunks to complete and collect errors
            errors = []
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    errors.append(str(e))

            # Raise comprehensive error if any tasks failed
            if errors:
                error_summary = f"TPC-DS parallel file-based generation failed with {len(errors)} errors:\n"
                error_summary += "\n".join(f"  - {err}" for err in errors[:5])
                if len(errors) > 5:
                    error_summary += f"\n  ... and {len(errors) - 5} more errors"
                raise RuntimeError(error_summary)


__all__ = ["DsdgenRunnerMixin"]
