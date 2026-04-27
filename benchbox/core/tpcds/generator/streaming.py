"""Streaming generation helpers for TPC-DS tables."""

from __future__ import annotations

import contextlib
import os
import subprocess
from pathlib import Path

from benchbox.utils.printing import emit


class StreamingGenerationMixin:
    """Mixin encapsulating streaming-oriented generation utilities."""

    def _generate_table_with_streaming(self, output_dir: Path, table_name: str) -> None:
        """Generate a single table with streaming compression.

        For parent tables that generate child tables (e.g., catalog_sales generates catalog_returns),
        we need to handle the combined output stream.

        Args:
            output_dir: Output directory for data generation
            table_name: Name of the table to generate
        """
        # Check if this is a parent table that generates child tables
        child_tables = {
            "catalog_sales": ["catalog_returns"],
            "store_sales": ["store_returns"],
            "web_sales": ["web_returns"],
        }

        if table_name in child_tables:
            # For parent tables, we need to use traditional file-based generation then compress
            # because dsdgen outputs multiple tables to stdout in a format that's hard to separate
            self._generate_parent_table_with_children(output_dir, table_name, child_tables[table_name])
        else:
            # For single tables, generate file then compress (more robust across dsdgen builds)
            self._generate_single_table_streaming(output_dir, table_name)

    def _generate_single_table_streaming(self, output_dir: Path, table_name: str) -> None:
        """Generate a single table to .dat then compress (robust path)."""
        cmd = [
            str(self.dsdgen_exe),
            "-verbose" if self.verbose else "-quiet",
            "-force",
            "-terminate",
            "n",
            "-scale",
            str(self.scale_factor),
            "-table",
            table_name,
        ]
        expected_filename = f"{table_name}.dat"
        dat_file = output_dir / expected_filename
        compressed_filename = self.get_compressed_filename(expected_filename)
        compressed_path = output_dir / compressed_filename
        try:
            env = os.environ.copy()
            self._copy_distribution_files(output_dir)
            subprocess.run(
                cmd,
                cwd=output_dir,
                check=True,
                env=env,
                stdout=subprocess.DEVNULL,  # Always suppress spinner output to prevent log bloat
                stderr=None if self.verbose else subprocess.PIPE,  # Show errors in verbose mode for debugging
            )
            if dat_file.exists() and self._is_valid_data_file(dat_file):
                row_count = 0

                # Check if compression is actually needed (avoid copying file to itself)
                if dat_file.resolve() == compressed_path.resolve():
                    # No compression needed - just count rows and update manifest
                    with open(dat_file, encoding="utf-8") as src:
                        for line in src:
                            row_count += 1
                else:
                    # Compression needed - copy and compress
                    with (
                        open(dat_file, encoding="utf-8") as src,
                        self.open_output_file(compressed_path, mode="wt") as dst,
                    ):
                        for line in src:
                            dst.write(line)
                            row_count += 1
                # Only delete the .dat file if we compressed it to a different file
                if dat_file.resolve() != compressed_path.resolve():
                    with contextlib.suppress(OSError):
                        dat_file.unlink()
                if self.verbose:
                    emit(f"✓ Generated and compressed {table_name} -> {compressed_path.name}")
                # Thread-safe manifest update
                with self._manifest_lock:
                    self._manifest_entries.setdefault(table_name, []).append(
                        {
                            "path": compressed_path.name,
                            "size_bytes": compressed_path.stat().st_size if compressed_path.exists() else 0,
                            "row_count": row_count,
                        }
                    )
            else:
                if dat_file.exists():
                    with contextlib.suppress(OSError):
                        dat_file.unlink()
                if self.verbose:
                    emit(f"○ Skipped {table_name} (no data at scale factor {self.scale_factor})")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to generate TPC-DS table {table_name} with exit code {e.returncode}") from e
        except Exception as e:
            raise RuntimeError(f"Failed to generate TPC-DS table {table_name}: {e}") from e

    def _generate_parent_table_with_children(
        self, output_dir: Path, parent_table: str, child_tables: list[str]
    ) -> None:
        """Generate a parent table and its child tables using streaming compression.

        Instead of generating all tables together and then compressing, we generate each
        table individually with streaming compression to maintain the requirement that
        no raw .dat files are ever written when compression is enabled.

        Args:
            output_dir: Output directory for data generation
            parent_table: Name of the parent table
            child_tables: List of child table names generated with the parent
        """
        try:
            env = os.environ.copy()

            if self.verbose:
                tables_str = f"{parent_table} + {', '.join(child_tables)}"
                emit(f"Generating {tables_str} with streaming compression...")

            # For parent tables with children, dsdgen outputs multiple tables mixed in stdout
            # We need to generate to files first, then compress them to maintain data integrity
            cmd = [
                str(self.dsdgen_exe),
                "-verbose" if self.verbose else "-quiet",
                "-force",  # force overwrites
                "-terminate",
                "n",  # disable trailing field delimiters
                "-scale",
                str(self.scale_factor),
                "-table",
                parent_table,  # generate parent table (and children automatically)
            ]

            # Run dsdgen to generate files
            subprocess.run(
                cmd,
                cwd=output_dir,
                check=True,
                env=env,
                stdout=subprocess.DEVNULL,  # Always suppress spinner output to prevent log bloat
                stderr=None if self.verbose else subprocess.PIPE,  # Show errors in verbose mode for debugging
            )

            # Now compress the generated files and remove originals while counting rows
            all_tables = [parent_table] + child_tables
            files_processed = 0

            for table_name in all_tables:
                dat_file = output_dir / f"{table_name}.dat"
                if dat_file.exists() and self._is_valid_data_file(dat_file):
                    expected_filename = f"{table_name}.dat"
                    compressed_name = self.get_compressed_filename(expected_filename)
                    compressed_path = output_dir / compressed_name
                    row_count = 0
                    try:
                        with (
                            open(dat_file, encoding="utf-8") as src,
                            self.open_output_file(compressed_path, mode="wt") as dst,
                        ):
                            for line in src:
                                dst.write(line)
                                row_count += 1
                        with contextlib.suppress(OSError):
                            dat_file.unlink()
                        files_processed += 1
                        if self.verbose:
                            emit(f"✓ Generated and compressed {table_name} -> {compressed_path.name}")
                        # Thread-safe manifest update
                        with self._manifest_lock:
                            self._manifest_entries.setdefault(table_name, []).append(
                                {
                                    "path": compressed_path.name,
                                    "size_bytes": compressed_path.stat().st_size if compressed_path.exists() else 0,
                                    "row_count": row_count,
                                }
                            )
                    except Exception as e:
                        raise RuntimeError(f"Failed to compress {dat_file.name}: {e}") from e
                elif self.verbose and dat_file.exists():
                    dat_file.unlink()
                    emit(f"○ Skipped {table_name} (no data at scale factor {self.scale_factor})")

            # If no files were processed, this is normal for small scale factors
            if files_processed == 0 and self.verbose:
                tables_str = f"{parent_table} + {', '.join(child_tables)}"
                emit(f"○ Skipped {tables_str} (no data at scale factor {self.scale_factor})")

        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to generate TPC-DS table {parent_table} with exit code {e.returncode}"
            if e.stderr:
                error_msg += f": {e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr}"
            raise RuntimeError(error_msg) from e
        except Exception as e:
            raise RuntimeError(f"Failed to generate TPC-DS table {parent_table}: {e}") from e

    def _generate_single_table_chunk_streaming(self, output_dir: Path, table_name: str, chunk_id: int) -> None:
        """Generate a single table chunk with direct streaming compression.

        Args:
            output_dir: Output directory for data generation
            table_name: Name of the table to generate
            chunk_id: Chunk ID for parallel generation
        """
        cmd = [
            str(self.dsdgen_exe),
            "-verbose" if self.verbose else "-quiet",
            "-force",
            "-terminate",
            "n",
            "-scale",
            str(self.scale_factor),
            "-table",
            table_name,
            "-child",
            str(chunk_id),
            "-parallel",
            str(self.parallel),
            "-FILTER",
            "Y",
        ]

        expected_filename = f"{table_name}_{chunk_id}_{self.parallel}.dat"
        compressed_filename = self.get_compressed_filename(expected_filename)
        output_file = output_dir / compressed_filename

        try:
            env = os.environ.copy()

            if self.verbose:
                emit(f"Generating {table_name} chunk {chunk_id}/{self.parallel} with streaming compression...")

            process = subprocess.Popen(
                cmd,
                cwd=output_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL if not self.verbose else None,
            )

            row_count, bytes_written = self._stream_process_output(process, output_file)

            process.wait()

            potential_dat_file = output_dir / expected_filename
            self._handle_chunk_result(
                process,
                cmd,
                table_name,
                chunk_id,
                compressed_filename,
                output_file,
                potential_dat_file,
                row_count,
                bytes_written,
            )

        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to generate TPC-DS table {table_name} chunk {chunk_id} with exit code {e.returncode}"
            if e.stderr:
                error_msg += f": {e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr}"
            raise RuntimeError(error_msg) from e
        except Exception as e:
            raise RuntimeError(f"Failed to generate TPC-DS table {table_name} chunk {chunk_id}: {e}") from e

    def _stream_process_output(self, process, output_file: Path) -> tuple[int, int]:
        """Stream dsdgen stdout into a compressed output file.

        Returns:
            Tuple of (row_count, bytes_written).
        """
        row_count = 0
        bytes_written = 0
        chunk_size = 65536
        last_chunk = b""

        first_chunk = process.stdout.read(chunk_size)
        if first_chunk:
            with self.open_output_file(output_file, mode="wb") as f:
                f.write(first_chunk)
                bytes_written += len(first_chunk)
                row_count += first_chunk.count(b"\n")
                last_chunk = first_chunk

                for chunk in iter(lambda: process.stdout.read(chunk_size), b""):
                    f.write(chunk)
                    bytes_written += len(chunk)
                    row_count += chunk.count(b"\n")
                    last_chunk = chunk

            if last_chunk and not last_chunk.endswith(b"\n"):
                row_count += 1

        return row_count, bytes_written

    def _handle_chunk_result(
        self,
        process,
        cmd: list[str],
        table_name: str,
        chunk_id: int,
        compressed_filename: str,
        output_file: Path,
        potential_dat_file: Path,
        row_count: int,
        bytes_written: int,
    ) -> None:
        """Process the outcome of a streaming chunk generation."""
        if bytes_written > 0:
            if potential_dat_file.exists():
                potential_dat_file.unlink()

            if process.returncode != 0:
                with contextlib.suppress(OSError):
                    output_file.unlink()
                stderr_output = ""
                if process.stderr:
                    stderr_output = process.stderr.read().decode("utf-8", errors="replace")
                raise subprocess.CalledProcessError(process.returncode, cmd, stderr=stderr_output)

            if self.verbose:
                emit(f"✓ Generated {table_name} chunk {chunk_id}/{self.parallel} -> {compressed_filename}")

            size_bytes = output_file.stat().st_size if output_file.exists() else 0
            with self._manifest_lock:
                self._manifest_entries.setdefault(table_name, []).append(
                    {"path": output_file.name, "size_bytes": size_bytes, "row_count": row_count}
                )
        else:
            if potential_dat_file.exists():
                potential_dat_file.unlink()

            if process.returncode != 0:
                stderr_output = ""
                if process.stderr:
                    stderr_output = process.stderr.read().decode("utf-8", errors="replace")
                raise subprocess.CalledProcessError(process.returncode, cmd, stderr=stderr_output)

            if self.verbose:
                emit(f"○ Skipped {table_name} chunk {chunk_id}/{self.parallel} (no data in this chunk)")

    def _generate_parent_table_chunk_with_children(
        self,
        output_dir: Path,
        parent_table: str,
        chunk_id: int,
        child_tables: list[str],
    ) -> None:
        """Generate a parent table chunk that also generates child table chunks.

        For parent tables, TPC-DS dsdgen automatically generates child tables when generating
        the parent table chunk. We use file-based generation then compress the results because
        child tables cannot be generated individually.

        Args:
            output_dir: Output directory for data generation
            parent_table: Name of the parent table
            chunk_id: Chunk ID for parallel generation
            child_tables: List of child table names generated with the parent
        """
        try:
            env = os.environ.copy()

            if self.verbose:
                tables_str = f"{parent_table} + {', '.join(child_tables)}"
                emit(f"Generating {tables_str} chunk {chunk_id}/{self.parallel} with file-then-compress...")

            # Generate parent table chunk (which automatically creates child tables)
            cmd = [
                str(self.dsdgen_exe),
                "-verbose" if self.verbose else "-quiet",
                "-force",  # force overwrites
                "-terminate",
                "n",  # disable trailing field delimiters
                "-scale",
                str(self.scale_factor),
                "-table",
                parent_table,  # generate parent table (creates children automatically)
                "-child",
                str(chunk_id),  # chunk number (1-based)
                "-parallel",
                str(self.parallel),
            ]

            # Run dsdgen to generate files
            subprocess.run(
                cmd,
                cwd=output_dir,
                check=True,
                env=env,
                stdout=subprocess.DEVNULL,  # Always suppress spinner output to prevent log bloat
                stderr=None if self.verbose else subprocess.PIPE,  # Show errors in verbose mode for debugging
            )

            # Now compress the generated files and remove originals
            all_tables = [parent_table] + child_tables
            files_processed = 0

            for table_name in all_tables:
                expected_filename = f"{table_name}_{chunk_id}_{self.parallel}.dat"
                dat_file = output_dir / expected_filename

                if dat_file.exists() and self._is_valid_data_file(dat_file):
                    if self.should_use_compression():
                        # Count rows before compression
                        row_count = 0
                        with open(dat_file, "rb") as f:
                            row_count = sum(1 for _ in f)

                        # Compress the file and remove original
                        compressed_file = self.compress_existing_file(dat_file, remove_original=True)
                        files_processed += 1

                        # Track in manifest (thread-safe)
                        with self._manifest_lock:
                            self._manifest_entries.setdefault(table_name, []).append(
                                {
                                    "path": compressed_file.name,
                                    "size_bytes": compressed_file.stat().st_size if compressed_file.exists() else 0,
                                    "row_count": row_count,
                                }
                            )

                        if self.verbose:
                            emit(
                                f"✓ Generated and compressed {table_name} chunk {chunk_id}/{self.parallel} -> {compressed_file.name}"
                            )
                    else:
                        # Keep original file when compression is disabled
                        # Count rows for manifest tracking
                        row_count = 0
                        with open(dat_file, "rb") as f:
                            row_count = sum(1 for _ in f)

                        files_processed += 1

                        # Track in manifest (thread-safe)
                        with self._manifest_lock:
                            self._manifest_entries.setdefault(table_name, []).append(
                                {
                                    "path": dat_file.name,
                                    "size_bytes": dat_file.stat().st_size if dat_file.exists() else 0,
                                    "row_count": row_count,
                                }
                            )

                        if self.verbose:
                            emit(f"✓ Generated {table_name} chunk {chunk_id}/{self.parallel} -> {expected_filename}")
                elif dat_file.exists():
                    # Remove empty file if it exists
                    dat_file.unlink()
                    if self.verbose:
                        emit(f"○ Skipped {table_name} chunk {chunk_id}/{self.parallel} (no data in this chunk)")

            # If no files were processed, this chunk had no data (normal for parallel generation)
            if files_processed == 0 and self.verbose:
                tables_str = f"{parent_table} + {', '.join(child_tables)}"
                emit(f"○ Skipped {tables_str} chunk {chunk_id}/{self.parallel} (no data in this chunk)")

        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to generate TPC-DS table {parent_table} chunk {chunk_id} with exit code {e.returncode}"
            if e.stderr:
                error_msg += f": {e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr}"
            raise RuntimeError(error_msg) from e
        except Exception as e:
            raise RuntimeError(f"Failed to generate TPC-DS table {parent_table} chunk {chunk_id}: {e}") from e


__all__ = ["StreamingGenerationMixin"]
