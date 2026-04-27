"""File management helpers for TPC-DS data generation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from benchbox.utils.file_format import COMPRESSION_EXTENSIONS, detect_compression, strip_compression_suffix
from benchbox.utils.printing import emit
from benchbox.utils.scale_factor import format_scale_factor
from benchbox.utils.stale_artifact_pruning import TableArtifactPattern, prune_stale_table_artifacts


class FileArtifactMixin:
    """Mixin handling filesystem and manifest responsibilities."""

    def _prune_stale_table_artifacts(self, target_dir: Path) -> list[Path]:
        """Remove stale per-table artifacts before regeneration.

        Keeps cleanup table-aware to avoid broad recursive deletions while
        preventing coexistence of raw/sharded/compressed variants from older runs.

        Args:
            target_dir: Directory containing generated table artifacts.

        Returns:
            List of deleted file paths.
        """

        return prune_stale_table_artifacts(
            target_dir=target_dir,
            table_names=self._known_table_names(),
            pattern=TableArtifactPattern(
                single_suffix=".dat",
                raw_shard_glob_template="{table}_*.dat",
                compressed_shard_glob_template="{table}_*.dat{ext}",
                shard_regex_template=r"^{table}_\d+_\d+\.dat(?:\.[a-z0-9]+)?$",
            ),
            compression_extensions=COMPRESSION_EXTENSIONS,
            use_compression=self.should_use_compression(),
            expect_sharded=int(getattr(self, "parallel", 1) or 1) > 1,
        )

    def _copy_distribution_files(self, output_dir: Path) -> None:
        """Copy required distribution files to output directory.

        Args:
            output_dir: Output directory for data generation
        """
        dsdgen_dir = Path(self.dsdgen_exe).parent
        dist_files = ["tpcds.dst", "tpcds.idx"]
        for dist_file in dist_files:
            dest_path = output_dir / dist_file

            # Check primary location (dsdgen_dir)
            dist_src = dsdgen_dir / dist_file
            if dist_src.exists() and dist_src != dest_path:
                import shutil

                shutil.copy2(dist_src, dest_path)

            # Also check if file exists in tools_dir (source version)
            dist_src_alt = self.tools_dir / dist_file
            if not dest_path.exists() and dist_src_alt.exists() and dist_src_alt != dest_path:
                import shutil

                shutil.copy2(dist_src_alt, dest_path)

    def _get_generated_dat_files(self) -> list[Path]:
        """Get list of generated .dat files in output directory.

        Returns:
            List of paths to generated .dat files
        """
        return list(self.output_dir.glob("*.dat"))

    def _gather_existing_table_files(
        self,
        target_dir: Path,
        use_compression: bool | None = None,
    ) -> dict[str, list[Path]]:
        """Map known tables to existing data files under the target directory.

        Returns all chunk files per table to support multi-chunk loading.

        Returns:
            Dictionary mapping table names to lists of file paths (one or more per table)
        """

        use_compression = self.should_use_compression() if use_compression is None else use_compression
        table_paths: dict[str, list[Path]] = {}
        for table_name in self._known_table_names():
            single_file = self._find_existing_single_table_file(target_dir, table_name, use_compression)
            if single_file is not None:
                table_paths[table_name] = [single_file]
                continue

            parallel_files = self._find_existing_parallel_table_files(target_dir, table_name, use_compression)
            if parallel_files:
                table_paths[table_name] = parallel_files

        return table_paths

    def _find_existing_single_table_file(
        self,
        target_dir: Path,
        table_name: str,
        use_compression: bool,
    ) -> Path | None:
        """Return the existing single-file artifact for a table, if present."""
        filename = self.get_compressed_filename(f"{table_name}.dat") if use_compression else f"{table_name}.dat"
        candidate = target_dir / filename
        if candidate.exists() and self._is_valid_data_file(candidate):
            return candidate
        return None

    def _find_existing_parallel_table_files(
        self,
        target_dir: Path,
        table_name: str,
        use_compression: bool,
    ) -> list[Path]:
        """Return sorted valid shard files for an existing table."""
        extension = self.get_compressor().get_file_extension() if use_compression else ""
        pattern = f"{table_name}_*.dat{extension}"
        valid_parallel_files = [
            path for path in target_dir.glob(pattern) if self._is_parallel_table_file(path, table_name, use_compression)
        ]
        return sorted(valid_parallel_files)

    def _is_parallel_table_file(self, file_path: Path, table_name: str, use_compression: bool) -> bool:
        """Check whether a file path matches the expected shard naming convention."""
        name_core = strip_compression_suffix(file_path).name if use_compression else file_path.name
        stem = Path(name_core).stem
        if not stem.startswith(f"{table_name}_"):
            return False
        suffix = stem[len(f"{table_name}_") :]
        parts = suffix.split("_")
        return len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit() and self._is_valid_data_file(file_path)

    def _is_valid_data_file(self, file_path: Path) -> bool:
        """Check if a file contains valid data (not empty or just compressed headers).

        Args:
            file_path: Path to the file to check

        Returns:
            True if file appears to contain actual data, False otherwise
        """
        if not file_path.exists():
            return False

        file_size = file_path.stat().st_size

        # For compressed files, minimum valid size should be significantly larger than just compressed headers
        compression = detect_compression(file_path)
        if compression == "zstd":
            # Empty zstd files are exactly 9 bytes; consider any value >9 as non-empty
            return file_size > 9
        elif compression == "gzip":
            # Empty gzip files are around ~20 bytes; accept >20 as non-empty
            return file_size > 20
        elif compression is not None:
            # For other compression types, use a reasonable minimum
            return file_size > 20
        else:
            # For uncompressed files, any non-empty file is valid
            return file_size > 0

    def _validate_file_format_consistency(self, target_dir: Path) -> None:
        """Validate that file formats are consistent with compression settings.

        When compression is enabled, ensure no .dat files exist (only compressed files).
        When compression is disabled, ensure no compressed files exist (only .dat files).

        Args:
            target_dir: Directory containing the generated files

        Raises:
            RuntimeError: If file format inconsistencies are detected
        """
        if self.should_use_compression():
            # When compression is enabled, no .dat files should exist
            dat_files = list(target_dir.glob("*.dat"))
            if dat_files:
                violation_files = [str(f.name) for f in dat_files]
                raise RuntimeError(
                    f"File format consistency violation: Found {len(violation_files)} raw .dat files when "
                    f"compression is enabled. Streaming compression should create only compressed files. "
                    f"Violating files: {', '.join(violation_files[:5])}"
                    f"{'...' if len(violation_files) > 5 else ''}"
                )

            # Also check for empty compressed files (which should not exist)
            extension = self.get_compressor().get_file_extension()
            compressed_files = list(target_dir.glob(f"*.dat{extension}"))
            empty_compressed = [f for f in compressed_files if not self._is_valid_data_file(f)]
            if empty_compressed:
                violation_files = [str(f.name) for f in empty_compressed]
                raise RuntimeError(
                    f"File format consistency violation: Found {len(violation_files)} empty compressed files "
                    f"(should not be created when no data exists). Empty files: {', '.join(violation_files[:5])}"
                    f"{'...' if len(violation_files) > 5 else ''}"
                )

        if self.verbose:
            # Report validation success
            if self.should_use_compression():
                extension = self.get_compressor().get_file_extension()
                compressed_files = list(target_dir.glob(f"*.dat{extension}"))
                valid_compressed = [f for f in compressed_files if self._is_valid_data_file(f)]
                emit(f"✓ File format validation passed: {len(valid_compressed)} compressed files, 0 raw .dat files")
            else:
                dat_files = list(target_dir.glob("*.dat"))
                valid_dat = [f for f in dat_files if self._is_valid_data_file(f)]
                emit(f"✓ File format validation passed: {len(valid_dat)} .dat files, 0 compressed files")

    def _write_manifest(self, output_dir: Path, table_paths: dict[str, list[Path]]) -> None:
        """Write a manifest describing generated files with sizes and row counts.

        Args:
            output_dir: Directory where manifest will be written
            table_paths: Dictionary mapping table names to lists of file paths
        """
        from datetime import datetime, timezone

        # compliance_class is set on the generator by validate_tpcds_scale()
        compliance_class = getattr(self, "compliance_class", None)
        compliance_str = (
            compliance_class.value
            if hasattr(compliance_class, "value")
            else str(compliance_class)
            if compliance_class
            else "unknown"
        )

        manifest = {
            "benchmark": "tpcds",
            "scale_factor": self.scale_factor,
            "compliance_class": compliance_str,
            "compression": {
                "enabled": self.should_use_compression(),
                "type": (
                    None
                    if not self.should_use_compression() or getattr(self, "compression_type", "none") == "none"
                    else getattr(self, "compression_type", None)
                ),
                "level": (None if not self.should_use_compression() else getattr(self, "compression_level", None)),
            },
            "parallel": self.parallel,
            "created_at": datetime.now(timezone.utc).isoformat() + "Z",
            "generator_version": "v1",
            "validation_metadata": {
                "benchmark_type": "tpcds",
                "expected_table_count": 25,
                "critical_tables": [
                    "call_center",
                    "catalog_page",
                    "catalog_returns",
                    "catalog_sales",
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
                    "store_returns",
                    "store_sales",
                    "time_dim",
                    "warehouse",
                    "web_page",
                    "web_returns",
                    "web_sales",
                    "web_site",
                    "dbgen_version",
                ],
                "dimension_tables": [
                    "call_center",
                    "catalog_page",
                    "customer",
                    "customer_address",
                    "customer_demographics",
                    "date_dim",
                    "household_demographics",
                    "income_band",
                    "item",
                    "promotion",
                    "reason",
                    "ship_mode",
                    "store",
                    "time_dim",
                    "warehouse",
                    "web_page",
                    "web_site",
                ],
                "fact_tables": [
                    "catalog_returns",
                    "catalog_sales",
                    "inventory",
                    "store_returns",
                    "store_sales",
                    "web_returns",
                    "web_sales",
                ],
                "validation_thresholds": {
                    "min_file_size_bytes": 10,
                    "min_row_count": 1,
                    "critical_table_coverage": 1.0,
                },
            },
            "tables": {},
        }
        # Collect ALL chunk files for each table
        for table, file_paths in table_paths.items():
            # Use collected manifest entries if available (from streaming generation)
            entries = self._manifest_entries.get(table)
            if entries:
                for e in entries:
                    manifest["tables"].setdefault(table, []).append(e)
                continue

            # Fallback: Use all files from table_paths (already collected by _gather_existing_table_files)
            # Count rows for each file to enable accurate validation
            for file_path in file_paths:
                size = file_path.stat().st_size if file_path.exists() else 0
                # Count rows in the file (handles both compressed and uncompressed)
                row_count = 0
                try:
                    # Handle compressed files using centralized detection
                    compression = detect_compression(file_path)
                    if compression == "gzip":
                        import gzip

                        with gzip.open(file_path, "rb") as f:
                            row_count = sum(1 for _ in f)
                    elif compression == "zstd":
                        import zstandard as zstd

                        with zstd.open(file_path, "rb") as f:
                            row_count = sum(1 for _ in f)
                    elif compression == "bzip2":
                        import bz2

                        with bz2.open(file_path, "rb") as f:
                            row_count = sum(1 for _ in f)
                    elif compression == "xz":
                        import lzma

                        with lzma.open(file_path, "rb") as f:
                            row_count = sum(1 for _ in f)
                    else:
                        # Uncompressed file
                        with open(file_path, "rb") as f:
                            row_count = sum(1 for _ in f)
                except Exception:
                    # If row counting fails, fall back to 0
                    row_count = 0

                manifest["tables"].setdefault(table, []).append(
                    {
                        "path": file_path.name,
                        "size_bytes": size,
                        "row_count": row_count,
                    }
                )

        out = output_dir / "_datagen_manifest.json"

        with open(out, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    def _get_sample_data_dir(self) -> Path | None:
        """Return bundled sample data path for the requested scale when available."""

        if self.scale_factor >= 1 or not self.should_use_compression():
            return None

        sf_label = format_scale_factor(self.scale_factor)
        candidate = self._package_root / "examples" / "data" / f"tpcds_{sf_label}"
        return candidate if candidate.exists() else None

    def _copy_sample_dataset(self, sample_dir: Path, target_dir: Path) -> None:
        """Copy bundled sample dataset into the target directory."""

        # Clear existing files to avoid mixing with the sample dataset
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

        self._manifest_entries.clear()


__all__ = ["FileArtifactMixin"]
