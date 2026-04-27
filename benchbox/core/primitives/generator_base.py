"""Base data generator for primitives benchmarks.

Shared infrastructure for write_primitives and transaction_primitives generators.
Both benchmarks reuse TPC-H base data and generate identical staging tables,
bulk load files, and special test files. This base class contains all shared logic;
subclasses only provide benchmark-specific naming via class attributes.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import bz2
import csv
import gzip
import io
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Union

from benchbox.utils.clock import elapsed_seconds, mono_time

if TYPE_CHECKING:
    import pyarrow as pa
    from cloudpathlib import CloudPath

# Type alias for paths that could be local or cloud
PathLike = Union[Path, "CloudPath"]

from benchbox.core.tpch.generator import TPCHDataGenerator
from benchbox.utils.cloud_storage import CloudStorageGeneratorMixin, create_path_handler
from benchbox.utils.compression_mixin import CompressionMixin
from benchbox.utils.datagen_manifest import DataGenerationManifest, resolve_compression_metadata
from benchbox.utils.file_format import detect_compression
from benchbox.utils.path_utils import get_benchmark_runs_datagen_path
from benchbox.utils.verbosity import VerbosityMixin, compute_verbosity


class PrimitivesDataGeneratorBase(CompressionMixin, CloudStorageGeneratorMixin, VerbosityMixin):
    """Base data generator for primitives benchmarks.

    Reuses TPC-H data for base tables and generates staging tables
    and bulk load files for write operations testing.

    Subclasses must set:
        _benchmark_name: str  (e.g., "write_primitives", "transaction_primitives")
        _display_name: str    (e.g., "Write Primitives", "Transaction Primitives")
        _auxiliary_dir: str   (e.g., "write_primitives_auxiliary")
        _logger_name: str     (e.g., "benchbox.core.write_primitives.generator")
    """

    _benchmark_name: str
    _display_name: str
    _auxiliary_dir: str
    _logger_name: str

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Union[str, Path] | None = None,
        verbose: int | bool = 0,
        quiet: bool = False,
        parallel: int = 1,
        force_regenerate: bool = False,
        compress_data: bool = False,
        compression_type: str | None = None,
        compression_level: int | None = None,
        **kwargs,
    ) -> None:
        """Initialize primitives data generator.

        Args:
            scale_factor: Scale factor (1.0 = ~1GB)
            output_dir: Directory to output generated data
            verbose: Whether to print verbose output during generation
            quiet: Suppress all output
            parallel: Number of parallel processes for data generation
            force_regenerate: Force data regeneration even if valid data exists
            compress_data: Whether to compress generated data files
            compression_type: Type of compression ('gzip', 'zstd', 'bzip2', or 'none')
            compression_level: Compression level (algorithm-specific)
            **kwargs: Additional arguments
        """
        # Initialize compression mixin (handles compression kwargs)
        # Only pass compression parameters if they are explicitly set
        compression_kwargs = {}
        if compress_data:
            compression_kwargs["compress_data"] = compress_data
        if compression_type is not None:
            compression_kwargs["compression_type"] = compression_type
        if compression_level is not None:
            compression_kwargs["compression_level"] = compression_level

        super().__init__(**compression_kwargs, **kwargs)

        self.scale_factor = scale_factor

        # Set up output directory - reuse TPC-H data directory
        if output_dir is None:
            output_dir = get_benchmark_runs_datagen_path("tpch", scale_factor)

        self.output_dir = create_path_handler(output_dir)

        # Set up verbosity
        verbosity_settings = compute_verbosity(verbose, quiet)
        self.apply_verbosity(verbosity_settings)
        self.logger = logging.getLogger(self._logger_name)

        self.parallel = parallel
        self.force_regenerate = force_regenerate

        # Initialize TPC-H generator for base data
        # Pass compression parameters only if explicitly set
        tpch_kwargs = {
            "scale_factor": scale_factor,
            "output_dir": self.output_dir,
            "verbose": verbose,
            "quiet": quiet,
            "parallel": parallel,
            "force_regenerate": force_regenerate,
        }
        if compress_data:
            tpch_kwargs["compress_data"] = compress_data
        if compression_type is not None:
            tpch_kwargs["compression_type"] = compression_type
        if compression_level is not None:
            tpch_kwargs["compression_level"] = compression_level

        self.tpch_generator = TPCHDataGenerator(**tpch_kwargs, **kwargs)

        # Paths for generated files
        # Store bulk load files in subdirectory to isolate from TPC-H data
        # This prevents contamination and makes cleanup easier
        self.files_dir = self.output_dir / self._auxiliary_dir
        self.staging_data: dict[str, Path] = {}

    def generate(self) -> dict[str, Path]:
        """Generate all data for primitives benchmark.

        Returns:
            Dictionary mapping table names to data file paths
        """
        self.log_verbose(f"Generating {self._display_name} data at scale factor {self.scale_factor}...")

        # 1. Generate base TPC-H data (or reuse existing)
        tpch_tables = self.tpch_generator.generate()
        self.log_verbose(f"TPC-H base data available: {len(tpch_tables)} tables")

        # 2. Generate staging table data files
        staging_tables = self._generate_staging_table_files()
        self.log_verbose(f"Generated {len(staging_tables)} staging table files")

        # 3. Generate bulk load files for BULK_LOAD operations
        # Use double-check locking pattern for efficiency:
        # 1. Check if files exist (fast, no lock needed)
        # 2. If missing, acquire lock and check again (prevents redundant generation)
        # This pattern is safe and avoids unnecessary lock contention
        bulk_files_exist = self.check_bulk_load_files_exist()
        if not bulk_files_exist or self.force_regenerate:
            if not bulk_files_exist:
                self.log_verbose("Bulk load files missing - will generate after acquiring lock")
            elif self.force_regenerate:
                self.log_verbose("Force regenerate enabled - will regenerate bulk load files")

            # Acquire lock to prevent concurrent generation (uses file-based locking)
            if self._acquire_bulk_load_lock(timeout=300):
                try:
                    # Double-check after acquiring lock (another process may have generated files)
                    # This prevents redundant work if multiple processes detected missing files
                    if not self.check_bulk_load_files_exist() or self.force_regenerate:
                        self.log_verbose("Lock acquired - starting bulk load file generation...")
                        bulk_files = self.generate_bulk_load_files()
                        self.log_verbose(f"✅ Generated {len(bulk_files)} bulk load files")
                    else:
                        self.log_verbose("✅ Files generated by another process while waiting for lock - skipping")
                finally:
                    self._release_bulk_load_lock()
            else:
                # Lock timeout - another process may be generating or lock is stale
                # Log warning but continue (benchmark can proceed without bulk load files)
                self.log_verbose(
                    "⚠️ Warning: Could not acquire lock for bulk load generation after 5 minutes. "
                    "Another process may be generating files, or a stale lock exists. "
                    "Some BULK_LOAD operations may fail if files are missing."
                )
        else:
            self.log_verbose("✅ Bulk load files already exist - skipping generation")

        # 4. Write manifest file (includes both base and staging tables)
        all_tables = {**tpch_tables, **staging_tables}
        self._write_manifest(all_tables)

        # Return combined base and staging tables
        return all_tables

    def _generate_staging_table_files(self) -> dict[str, Path]:
        """Generate staging table data files.

        Creates .tbl files for primitives staging tables:
        - orders_stage.tbl: Copy of orders data
        - lineitem_stage.tbl: Copy of lineitem data
        - orders_new.tbl: Empty (populated during operations)
        - orders_summary.tbl, lineitem_enriched.tbl, bulk_load_target.tbl: Empty

        Returns:
            Dictionary mapping staging table names to file paths
        """
        staging_files: dict[str, Path] = {}

        # Generate orders_stage.tbl (copy of orders data)
        orders_files = sorted(self.output_dir.glob("orders.tbl*"))
        if orders_files:
            self.log_verbose("Generating orders_stage.tbl from orders data...")
            orders_rows = self._read_tbl_files("orders.tbl*")
            orders_stage_path = self._write_tbl_file("orders_stage.tbl", orders_rows)
            staging_files["orders_stage"] = orders_stage_path
        else:
            self.log_verbose("No orders data found, skipping orders_stage.tbl generation")

        # Generate lineitem_stage.tbl (copy of lineitem data)
        lineitem_files = sorted(self.output_dir.glob("lineitem.tbl*"))
        if lineitem_files:
            self.log_verbose("Generating lineitem_stage.tbl from lineitem data...")
            lineitem_rows = self._read_tbl_files("lineitem.tbl*")
            lineitem_stage_path = self._write_tbl_file("lineitem_stage.tbl", lineitem_rows)
            staging_files["lineitem_stage"] = lineitem_stage_path
        else:
            self.log_verbose("No lineitem data found, skipping lineitem_stage.tbl generation")

        # Empty staging tables (orders_new, orders_summary, etc.) are NOT generated as files
        # They will be created as empty tables during schema creation
        # No .tbl files needed since they have no initial data

        return staging_files

    def _write_tbl_file(self, filename: str, rows: list[tuple]) -> PathLike:
        """Write rows to TPC-H pipe-delimited .tbl file with optional compression.

        TPC-H .tbl files use pipe delimiter (no trailing pipe).
        Empty files should be truly empty (no content).

        If compression is enabled via the TPC-H generator, the file will be compressed
        after writing and the uncompressed file will be removed to maintain format consistency.

        Args:
            filename: Output filename (e.g., "orders_stage.tbl")
            rows: List of tuples containing row data

        Returns:
            Path to generated .tbl file (compressed if compression enabled)
        """
        output_path = self.output_dir / filename

        # Write uncompressed file first
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            for row in rows:
                # TPC-H format: field1|field2|...|fieldn (no trailing pipe)
                line = "|".join(str(field) for field in row) + "\n"
                f.write(line)

        self.log_verbose(f"Generated {output_path} ({len(rows)} rows)")

        # Compress if enabled (maintains format consistency with base TPC-H tables)
        if self.tpch_generator.should_use_compression():
            compressor = self.tpch_generator.get_compressor()
            compressed_path = compressor.compress_file(output_path)
            output_path.unlink()  # Remove uncompressed file to avoid format mixing
            self.log_verbose(f"Compressed {filename} to {compressed_path.name}")
            return compressed_path

        return output_path

    def _write_manifest(self, table_paths: dict[str, Path]) -> None:
        """Write data generation manifest for primitives benchmark.

        Args:
            table_paths: Dictionary mapping table names to file paths
        """
        if not table_paths:
            return

        manifest = DataGenerationManifest(
            output_dir=self.output_dir,
            benchmark=self._benchmark_name,
            scale_factor=self.scale_factor,
            compression=resolve_compression_metadata(self.tpch_generator),
            parallel=self.parallel,
            seed=getattr(self.tpch_generator, "seed", None),
        )

        # Include each table in manifest with row count
        # Skip empty staging tables - they will be created during schema creation but not loaded
        for table_name, file_path in table_paths.items():
            # Get row count from file or use expected value
            if table_name in ["orders_stage", "orders"]:
                expected_rows = self._get_tpch_row_count("orders")
            elif table_name in ["lineitem_stage", "lineitem"]:
                expected_rows = self._get_tpch_row_count("lineitem")
            elif table_name in [
                "orders_new",
                "orders_summary",
                "lineitem_enriched",
                "bulk_load_target",
                "write_ops_log",
                "batch_metadata",
            ]:
                # Empty staging tables - skip adding to manifest since they have no data to load
                # Tables will be created during schema creation
                continue
            else:
                # Other TPC-H base tables
                expected_rows = self._get_tpch_row_count(table_name)

            # TPC-H base tables may be multi-chunk (list[Path] for parallel generation).
            # add_entry accepts a single PathLike, so iterate chunks individually.
            if isinstance(file_path, list):
                chunk_count = len(file_path)
                rows_per_chunk = expected_rows // chunk_count if chunk_count else expected_rows
                remainder = expected_rows - rows_per_chunk * chunk_count
                for i, chunk_file in enumerate(file_path):
                    rc = rows_per_chunk + (remainder if i == chunk_count - 1 else 0)
                    manifest.add_entry(table_name, chunk_file, row_count=rc)
            else:
                manifest.add_entry(table_name, file_path, row_count=expected_rows)

        manifest.write()
        self.log_verbose(f"Wrote manifest with {len(table_paths)} tables")

    def _get_tpch_row_count(self, table_name: str) -> int:
        """Get expected row count for TPC-H table at current scale factor.

        Args:
            table_name: Name of TPC-H table

        Returns:
            Expected row count
        """
        # TPC-H base row counts (at SF=1)
        base_row_counts = {
            "region": 5,
            "nation": 25,
            "supplier": 10_000,
            "customer": 150_000,
            "part": 200_000,
            "partsupp": 800_000,
            "orders": 1_500_000,
            "lineitem": 6_001_215,
        }

        base = base_row_counts.get(table_name.lower(), 0)
        if table_name.lower() in {"nation", "region"}:
            return base
        return max(0, int(round(base * float(self.scale_factor))))

    def _acquire_bulk_load_lock(self, timeout: int = 300) -> bool:
        """Acquire a lock for bulk load file generation.

        Uses a lock file to prevent concurrent generation of bulk load files.
        This prevents file corruption when multiple processes try to generate
        the same files simultaneously.

        Args:
            timeout: Maximum seconds to wait for lock acquisition

        Returns:
            True if lock was acquired, False if timeout

        Note:
            Caller must call _release_bulk_load_lock() when done.
        """
        # Ensure files directory exists before creating lock file
        self.files_dir.mkdir(parents=True, exist_ok=True)

        lock_file = self.files_dir / ".bulk_load_generation.lock"
        start_time = mono_time()

        while elapsed_seconds(start_time) < timeout:
            try:
                # Try to create lock file exclusively (fails if exists)
                fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"pid:{os.getpid()}\n".encode())
                os.close(fd)
                self._lock_file = lock_file
                return True
            except FileExistsError:
                # Lock held by another process - wait and retry
                time.sleep(0.5)

        # Timeout - check if lock is stale (process died or lock abandoned)
        if lock_file.exists():
            try:
                # Read lock file to get PID
                with open(lock_file, encoding="utf-8") as f:
                    lock_content = f.read().strip()

                # Extract PID from lock file (format: "pid:12345")
                lock_pid = None
                if lock_content.startswith("pid:"):
                    try:
                        lock_pid = int(lock_content.split(":")[1])
                    except (IndexError, ValueError):
                        pass

                # Check if process is still running
                is_stale = False
                if lock_pid is not None and not self._is_process_running(lock_pid):
                    # Process died - lock is definitely stale
                    self.log_verbose(f"Lock held by dead process (PID {lock_pid}) - removing")
                    is_stale = True
                else:
                    # Process still running or PID unknown - check age
                    age = time.time() - lock_file.stat().st_mtime
                    if age > 300:
                        # Lock older than 5 minutes - likely stale
                        self.log_verbose(f"Removing stale lock file (age: {age:.0f}s, PID: {lock_pid})")
                        is_stale = True

                if is_stale:
                    lock_file.unlink()
                    # Retry with shorter timeout (lock should be available now)
                    return self._acquire_bulk_load_lock(timeout=30)

            except Exception as e:
                self.log_verbose(f"Error checking stale lock: {e}")

        return False

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process with given PID is currently running.

        Args:
            pid: Process ID to check

        Returns:
            True if process is running, False otherwise

        Note:
            Uses platform-specific checks. On Unix, sends signal 0 (doesn't actually
            signal the process, just checks if it exists). On Windows, this may not
            work correctly and will return True to be safe.
        """
        import sys

        try:
            if sys.platform == "win32":
                # Windows: Try to open process handle
                import ctypes

                PROCESS_QUERY_INFORMATION = 0x0400
                handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                    return True
                return False
            else:
                # Unix: Send signal 0 (doesn't actually signal, just checks existence)
                os.kill(pid, 0)
                return True
        except (OSError, AttributeError):
            # Process doesn't exist or we don't have permission to check
            return False

    def _release_bulk_load_lock(self) -> None:
        """Release the bulk load generation lock."""
        if hasattr(self, "_lock_file") and self._lock_file.exists():
            try:
                self._lock_file.unlink()
            except Exception as e:
                self.log_verbose(f"Warning: Failed to release lock: {e}")

    def check_bulk_load_files_exist(self) -> bool:
        """Check if bulk load files already exist and match current scale factor.

        Verifies presence of representative bulk load test files including
        CSV/Parquet files with various compressions and special test files.
        Also validates that files were generated for the current scale factor.

        Returns:
            True if all expected bulk load files exist and match scale factor, False otherwise

        Note:
            This is a public API method that can be safely called by benchmarks
            to verify auxiliary file availability.
        """
        # Check for key bulk load files
        # We check a representative sample rather than all files for efficiency
        expected_files = [
            "csv_small_1k.csv",
            "csv_medium_100k.csv",
            "csv_large_1m.csv",
            "parquet_small_1k.parquet",
            "parquet_medium_100k.parquet",
            "parquet_large_1m.parquet",
            "csv_with_errors.csv",
            "csv_with_nulls.csv",
            "csv_parallel_part1.csv",
            "csv_parallel_part2.csv",
            "csv_parallel_part3.csv",
            "csv_parallel_part4.csv",
        ]

        for filename in expected_files:
            file_path = self.files_dir / filename
            if not file_path.exists():
                self.log_verbose(f"Missing bulk load file: {filename}")
                return False

        # Check if scale factor matches (validates files aren't stale)
        metadata_file = self.files_dir / ".bulk_load_metadata.json"
        if metadata_file.exists():
            try:
                import json

                with open(metadata_file, encoding="utf-8") as f:
                    metadata = json.load(f)
                stored_sf = metadata.get("scale_factor")
                if stored_sf != self.scale_factor:
                    self.log_verbose(
                        f"Bulk load files scale factor mismatch: stored={stored_sf}, current={self.scale_factor}"
                    )
                    return False
            except Exception as e:
                self.log_verbose(f"Warning: Could not read metadata file: {e}")
                # Continue without scale factor check if metadata unreadable

        return True

    def generate_bulk_load_files(self) -> dict[str, Path]:
        """Generate bulk load files in various formats and compressions.

        Creates CSV and Parquet files with different compression settings
        for bulk load testing. This includes:
        - CSV files (small/medium/large) with gzip/zstd/bzip2 compression
        - Parquet files (small/medium/large) with various compression codecs
        - Special test files (errors, nulls, parallel parts, etc.)

        Returns:
            Dictionary mapping file identifiers to file paths

        Note:
            This is a public API method that can be safely called by benchmarks
            to generate auxiliary test files.
        """
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.log_verbose(f"Bulk load files directory: {self.files_dir}")

        generated_files: dict[str, Path] = {}

        # Find orders data files (handles both uncompressed and compressed/sharded formats)
        orders_files = sorted(self.output_dir.glob("orders.tbl*"))
        if not orders_files:
            self.log_verbose("No TPC-H orders data files found, skipping bulk load file generation")
            return generated_files

        # Read source data from all shards
        self.log_verbose(f"Reading source data from {len(orders_files)} file(s)")
        rows = self._read_tbl_files("orders.tbl*", limit=1_000_000)

        # Define size variants
        size_configs = [
            ("small", 1_000),
            ("medium", 100_000),
            ("large", 1_000_000),
        ]

        # Generate CSV files with various compressions
        for size_name, row_count in size_configs:
            subset = rows[:row_count]

            # Uncompressed CSV (use "1m" for 1,000,000 rows, otherwise use "Nk" format)
            size_suffix = "1m" if row_count >= 1_000_000 else f"{row_count // 1000}k"
            csv_file = self._write_csv(f"csv_{size_name}_{size_suffix}.csv", subset)
            generated_files[f"csv_{size_name}_uncompressed"] = csv_file

            # GZIP compressed
            gz_file = self._compress_file(csv_file, "gzip")
            generated_files[f"csv_{size_name}_gzip"] = gz_file

            # ZSTD compressed
            zst_file = self._compress_file(csv_file, "zstd")
            generated_files[f"csv_{size_name}_zstd"] = zst_file

            # BZIP2 compressed
            bz2_file = self._compress_file(csv_file, "bzip2")
            generated_files[f"csv_{size_name}_bzip2"] = bz2_file

        # Generate Parquet files with various compressions
        try:
            import pyarrow.parquet as pq

            for size_name, row_count in size_configs:
                subset = rows[:row_count]

                # Convert to PyArrow table
                pa_table = self._rows_to_pyarrow_table(subset)

                # Uncompressed Parquet (use "1m" for 1,000,000 rows, otherwise use "Nk" format)
                size_suffix = "1m" if row_count >= 1_000_000 else f"{row_count // 1000}k"
                parquet_file = self.files_dir / f"parquet_{size_name}_{size_suffix}.parquet"
                pq.write_table(pa_table, parquet_file, compression="none")
                generated_files[f"parquet_{size_name}_uncompressed"] = parquet_file
                self.log_verbose(f"Generated {parquet_file}")

                # Snappy compressed
                parquet_snappy = self.files_dir / f"parquet_{size_name}_{size_suffix}_snappy.parquet"
                pq.write_table(pa_table, parquet_snappy, compression="snappy")
                generated_files[f"parquet_{size_name}_snappy"] = parquet_snappy
                self.log_verbose(f"Generated {parquet_snappy}")

                # GZIP compressed
                parquet_gzip = self.files_dir / f"parquet_{size_name}_{size_suffix}_gzip.parquet"
                pq.write_table(pa_table, parquet_gzip, compression="gzip")
                generated_files[f"parquet_{size_name}_gzip"] = parquet_gzip
                self.log_verbose(f"Generated {parquet_gzip}")

                # ZSTD compressed
                parquet_zstd = self.files_dir / f"parquet_{size_name}_{size_suffix}_zstd.parquet"
                pq.write_table(pa_table, parquet_zstd, compression="zstd")
                generated_files[f"parquet_{size_name}_zstd"] = parquet_zstd
                self.log_verbose(f"Generated {parquet_zstd}")

        except ImportError:
            self.log_verbose("PyArrow not available, skipping Parquet file generation")

        # Generate special test files for edge case testing
        special = self._generate_special_test_files(rows)
        generated_files.update(special)
        self.log_verbose(f"Generated {len(special)} special test files")

        # Write metadata file with scale factor for validation
        self._write_bulk_load_metadata()

        self.log_verbose(f"Generated {len(generated_files)} total bulk load files")
        return generated_files

    def _write_bulk_load_metadata(self) -> None:
        """Write metadata file for bulk load files.

        Stores scale factor and generation timestamp to detect stale files.
        """
        import json
        from datetime import datetime, timezone

        metadata = {
            "scale_factor": self.scale_factor,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "file_count": len(list(self.files_dir.glob("*"))),
        }

        metadata_file = self.files_dir / ".bulk_load_metadata.json"
        try:
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)
            self.log_verbose(f"Wrote bulk load metadata: {metadata_file}")
        except Exception as e:
            self.log_verbose(f"Warning: Could not write metadata file: {e}")

    def _read_tbl_file(self, path: Path, limit: int = 1_000_000) -> list[tuple]:
        """Read rows from TPC-H .tbl file.

        Args:
            path: Path to .tbl file
            limit: Maximum number of rows to read

        Returns:
            List of tuples containing row data
        """
        rows = []
        with open(path, encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="|")
            for i, row in enumerate(reader):
                if i >= limit:
                    break
                # TPC-H .tbl files have trailing delimiter, remove last empty field
                if row and row[-1] == "":
                    row = row[:-1]
                rows.append(tuple(row))
        return rows

    def _read_tbl_files(self, file_pattern: str, limit: int = 1_000_000) -> list[tuple]:
        """Read rows from TPC-H .tbl files (handles compression and sharding).

        Args:
            file_pattern: Glob pattern for files (e.g., "orders.tbl*")
            limit: Maximum total rows to read across all files

        Returns:
            List of tuples containing row data
        """
        files = sorted(self.output_dir.glob(file_pattern))
        rows = []

        for file_path in files:
            if len(rows) >= limit:
                break

            # Decompress if needed based on file extension
            compression = detect_compression(file_path)
            if compression == "zstd":
                try:
                    import zstandard as zstd

                    with open(file_path, "rb") as f_in:
                        dctx = zstd.ZstdDecompressor()
                        with dctx.stream_reader(f_in) as reader:
                            text_stream = io.TextIOWrapper(reader, encoding="utf-8")
                            rows.extend(self._parse_tbl_stream(text_stream, limit - len(rows)))
                except ImportError:
                    self.log_verbose(f"zstandard not available, skipping {file_path}")
                    continue
            elif compression == "gzip":
                with gzip.open(file_path, "rt", encoding="utf-8") as f:
                    rows.extend(self._parse_tbl_stream(f, limit - len(rows)))
            elif compression == "bzip2":
                with bz2.open(file_path, "rt", encoding="utf-8") as f:
                    rows.extend(self._parse_tbl_stream(f, limit - len(rows)))
            elif compression == "xz":
                import lzma

                with lzma.open(file_path, "rt", encoding="utf-8") as f:
                    rows.extend(self._parse_tbl_stream(f, limit - len(rows)))
            else:
                # Uncompressed .tbl file or numbered shard, or unsupported compression
                with open(file_path, encoding="utf-8") as f:
                    rows.extend(self._parse_tbl_stream(f, limit - len(rows)))

        return rows

    def _parse_tbl_stream(self, stream, limit: int) -> list[tuple]:
        """Parse TPC-H pipe-delimited data from a text stream.

        Args:
            stream: Text stream to read from
            limit: Maximum number of rows to parse

        Returns:
            List of tuples containing row data
        """
        rows = []
        reader = csv.reader(stream, delimiter="|")
        for i, row in enumerate(reader):
            if i >= limit:
                break
            # TPC-H .tbl files have trailing delimiter, remove last empty field
            if row and row[-1] == "":
                row = row[:-1]
            rows.append(tuple(row))
        return rows

    def _validate_filename(self, filename: str) -> str:
        """Validate and sanitize filename to prevent directory traversal attacks.

        Args:
            filename: Proposed filename

        Returns:
            Sanitized filename (just the basename, no path components)

        Raises:
            ValueError: If filename contains suspicious patterns

        Security:
            - Strips any directory components (prevents ../../../etc/passwd)
            - Rejects filenames with null bytes (prevents null byte injection)
            - Rejects empty or whitespace-only filenames
            - Only allows alphanumeric, dots, dashes, underscores
        """
        if not filename or not filename.strip():
            raise ValueError("Filename cannot be empty")

        # Check for null bytes (null byte injection attack)
        if "\x00" in filename:
            raise ValueError(f"Filename contains null byte: {filename!r}")

        # Get basename only (strips any directory components like ../)
        # This is the primary defense against directory traversal
        basename = os.path.basename(filename)

        if not basename or basename in (".", ".."):
            raise ValueError(f"Invalid filename: {filename}")

        # Additional validation: only allow safe characters
        # Allow: alphanumeric, dot, dash, underscore, and common file extensions
        import re

        if not re.match(r"^[a-zA-Z0-9._-]+$", basename):
            raise ValueError(
                f"Filename contains invalid characters: {basename}. "
                "Only alphanumeric, dots, dashes, and underscores allowed."
            )

        # Prevent hidden files (. prefix) except for extensions
        if basename.startswith(".") and basename.count(".") == 1:
            raise ValueError(f"Hidden files not allowed: {basename}")

        return basename

    def _write_csv(self, filename: str, rows: list[tuple]) -> PathLike:
        """Write rows to CSV file.

        Args:
            filename: Output filename (will be validated for security)
            rows: List of tuples containing row data

        Returns:
            Path to generated CSV file

        Raises:
            ValueError: If filename is invalid or contains directory traversal attempts
        """
        # Validate filename to prevent directory traversal attacks
        safe_filename = self._validate_filename(filename)
        output_path = self.files_dir / safe_filename

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            # Write header
            writer.writerow(
                [
                    "o_orderkey",
                    "o_custkey",
                    "o_orderstatus",
                    "o_totalprice",
                    "o_orderdate",
                    "o_orderpriority",
                    "o_clerk",
                    "o_shippriority",
                    "o_comment",
                ]
            )
            # Write data
            writer.writerows(rows)

        self.log_verbose(f"Generated {output_path} ({len(rows)} rows)")
        return output_path

    def _compress_file(self, source_path: Path, compression: str) -> Path:
        """Compress a file using specified compression.

        Args:
            source_path: Path to source file
            compression: Compression type (gzip, zstd, bzip2)

        Returns:
            Path to compressed file
        """
        if compression == "gzip":
            output_path = source_path.with_suffix(source_path.suffix + ".gz")
            with open(source_path, "rb") as f_in, gzip.open(output_path, "wb") as f_out:
                f_out.writelines(f_in)
        elif compression == "zstd":
            try:
                import zstandard as zstd

                output_path = source_path.with_suffix(source_path.suffix + ".zst")
                with open(source_path, "rb") as f_in, open(output_path, "wb") as f_out:
                    compressor = zstd.ZstdCompressor()
                    compressor.copy_stream(f_in, f_out)
            except ImportError:
                self.log_verbose("zstandard not available, skipping zstd compression")
                return source_path
        elif compression == "bzip2":
            output_path = source_path.with_suffix(source_path.suffix + ".bz2")
            with open(source_path, "rb") as f_in, bz2.open(output_path, "wb") as f_out:
                f_out.writelines(f_in)
        else:
            raise ValueError(f"Unsupported compression: {compression}")

        self.log_verbose(f"Compressed {source_path} to {output_path}")
        return output_path

    def _rows_to_pyarrow_table(self, rows: list[tuple]) -> pa.Table:
        """Convert rows to PyArrow table.

        Args:
            rows: List of tuples containing row data

        Returns:
            PyArrow Table
        """
        import pyarrow as pa

        # Define schema for ORDERS table
        schema = pa.schema(
            [
                ("o_orderkey", pa.int64()),
                ("o_custkey", pa.int64()),
                ("o_orderstatus", pa.string()),
                ("o_totalprice", pa.float64()),
                ("o_orderdate", pa.string()),
                ("o_orderpriority", pa.string()),
                ("o_clerk", pa.string()),
                ("o_shippriority", pa.int64()),
                ("o_comment", pa.string()),
            ]
        )

        # Convert rows to columnar format
        columns = list(zip(*rows))
        arrays = [
            pa.array([int(v) for v in columns[0]]),  # o_orderkey
            pa.array([int(v) for v in columns[1]]),  # o_custkey
            pa.array(columns[2]),  # o_orderstatus
            pa.array([float(v) for v in columns[3]]),  # o_totalprice
            pa.array(columns[4]),  # o_orderdate
            pa.array(columns[5]),  # o_orderpriority
            pa.array(columns[6]),  # o_clerk
            pa.array([int(v) for v in columns[7]]),  # o_shippriority
            pa.array(columns[8]),  # o_comment
        ]

        return pa.Table.from_arrays(arrays, schema=schema)

    # Column names shared across special test file generators
    _ORDERS_HEADER = [
        "o_orderkey",
        "o_custkey",
        "o_orderstatus",
        "o_totalprice",
        "o_orderdate",
        "o_orderpriority",
        "o_clerk",
        "o_shippriority",
        "o_comment",
    ]

    def _generate_special_test_files(self, rows: list[tuple]) -> dict[str, Path]:
        """Generate special test files for edge case testing.

        Args:
            rows: Source data rows

        Returns:
            Dictionary mapping file identifiers to paths
        """
        special_files: dict[str, Path] = {}

        special_files.update(self._generate_error_and_null_files(rows))
        special_files.update(self._generate_format_variant_files(rows))
        special_files.update(self._generate_parallel_load_files(rows))

        return special_files

    def _generate_error_and_null_files(self, rows: list[tuple]) -> dict[str, Path]:
        """Generate CSV files with intentional errors, nulls, and upsert data."""
        header = self._ORDERS_HEADER
        result: dict[str, Path] = {}

        # 1. CSV with intentional errors (some rows malformed)
        error_file = self.files_dir / "csv_with_errors.csv"
        with open(error_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            good_rows_count = min(100, len(rows))
            for row in rows[:good_rows_count]:
                writer.writerow(row)
            if len(rows) > 100:
                writer.writerow([rows[100][0], rows[100][1]])
            if len(rows) > 101:
                writer.writerow([rows[101][0], "INVALID_NUMBER", rows[101][2]])
            if len(rows) > 102:
                for row in rows[102 : min(200, len(rows))]:
                    writer.writerow(row)
        result["csv_with_errors"] = error_file
        self.log_verbose(f"Generated {error_file}")

        # 2. CSV with NULL values
        null_file = self.files_dir / "csv_with_nulls.csv"
        with open(null_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            for i, row in enumerate(rows[:1000]):
                row_list = list(row)
                if i % 10 == 0:
                    row_list[8] = ""
                if i % 20 == 0:
                    row_list[6] = ""
                writer.writerow(row_list)
        result["csv_with_nulls"] = null_file
        self.log_verbose(f"Generated {null_file}")

        # 3. Upsert data (overlapping with existing data)
        upsert_file = self.files_dir / "csv_upsert_data.csv"
        with open(upsert_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            for row in rows[:50]:
                row_list = list(row)
                try:
                    row_list[3] = str(float(row_list[3]) * 1.5)
                except (ValueError, IndexError):
                    pass
                writer.writerow(row_list)
        result["csv_upsert_data"] = upsert_file
        self.log_verbose(f"Generated {upsert_file}")

        return result

    def _generate_format_variant_files(self, rows: list[tuple]) -> dict[str, Path]:
        """Generate CSV files with quoted fields, custom delimiters, dates, and UTF-8."""
        header = self._ORDERS_HEADER
        result: dict[str, Path] = {}

        # Quoted fields
        quoted_file = self.files_dir / "csv_quoted_fields.csv"
        with open(quoted_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_ALL)
            writer.writerow(header)
            for row in rows[:1000]:
                row_list = list(row)
                row_list[8] = 'Comment with "quotes" and, commas'
                writer.writerow(row_list)
        result["csv_quoted_fields"] = quoted_file
        self.log_verbose(f"Generated {quoted_file}")

        # Pipe-separated values (custom delimiter)
        psv_file = self.files_dir / "csv_custom_delim.psv"
        with open(psv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter="|")
            writer.writerow(header)
            for row in rows[:1000]:
                writer.writerow(row)
        result["csv_custom_delim"] = psv_file
        self.log_verbose(f"Generated {psv_file}")

        # Custom date format
        custom_dates_file = self.files_dir / "csv_custom_dates.csv"
        with open(custom_dates_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            for row in rows[:1000]:
                row_list = list(row)
                if row_list[4]:
                    row_list[4] = row_list[4].replace("-", "/")
                writer.writerow(row_list)
        result["csv_custom_dates"] = custom_dates_file
        self.log_verbose(f"Generated {custom_dates_file}")

        # UTF-8 encoded with special characters
        utf8_file = self.files_dir / "csv_utf8_encoded.csv"
        with open(utf8_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            for row in rows[:1000]:
                row_list = list(row)
                row_list[8] = "Comment with UTF-8: café, naïve, 日本語"
                writer.writerow(row_list)
        result["csv_utf8_encoded"] = utf8_file
        self.log_verbose(f"Generated {utf8_file}")

        return result

    def _generate_parallel_load_files(self, rows: list[tuple]) -> dict[str, Path]:
        """Generate parallel load part files for multi-file load testing."""
        header = self._ORDERS_HEADER
        result: dict[str, Path] = {}

        min_rows_needed = 2000
        if len(rows) < min_rows_needed:
            self.log_verbose(
                f"Warning: Only {len(rows)} rows available for parallel parts "
                f"(minimum {min_rows_needed} recommended). Using available data."
            )

        num_parts = 4
        rows_per_part = max(len(rows) // num_parts, 1)

        for part_num in range(1, num_parts + 1):
            start_idx = (part_num - 1) * rows_per_part
            end_idx = len(rows) if part_num == num_parts else start_idx + rows_per_part

            parallel_file = self.files_dir / f"csv_parallel_part{part_num}.csv"
            with open(parallel_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(header)
                rows_written = 0
                for row in rows[start_idx:end_idx]:
                    writer.writerow(row)
                    rows_written += 1
            result[f"csv_parallel_part{part_num}"] = parallel_file
            self.log_verbose(f"Generated {parallel_file} ({rows_written} rows)")

        return result

    def get_data_source_benchmark(self) -> str:
        """Return the source benchmark for data sharing.

        Returns:
            "tpch" to indicate this benchmark shares TPC-H data
        """
        return "tpch"
