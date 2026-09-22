"""Delta Lake to Parquet export for snapshot and fallback ingestion paths.

ClickHouse can read Delta Lake tables natively via the ``DeltaLake`` table
engine and the ``deltaLake`` table-function family (see
:mod:`benchbox.platforms.clickhouse.delta_lake`); native reads are deployment
dependent and unavailable in some embedded builds. This module provides the
Parquet conversion layer for the remaining cases: it reads a Delta table
directory (optionally at a pinned version, giving time travel for free) and
writes plain Parquet files that ClickHouse can ingest via its
``s3(..., 'Parquet')`` table function or local ``.parquet`` files.

The export uses the ``deltalake`` package only -- no JVM or Spark session is
required, so it runs in the default unit-test lane.

Example:
    from benchbox.utils.delta_export import export_delta_to_parquet

    result = export_delta_to_parquet("s3-staging/orders", "parquet-out/orders")
    assert (result.row_count, result.parquet_files)  # exported rows and files

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


class DeltaExportError(RuntimeError):
    """Raised when a Delta table cannot be exported to Parquet."""


@dataclass(frozen=True)
class DeltaExportResult:
    """Outcome of a Delta to Parquet export."""

    table_path: str
    output_dir: Path
    version: int
    row_count: int
    column_names: list[str]
    parquet_files: list[Path] = field(default_factory=list)


def _load_delta_table(table_path: Path, version: int | None):
    """Open a Delta table, raising DeltaExportError on failure."""
    try:
        from deltalake import DeltaTable
    except ImportError as exc:
        raise DeltaExportError(
            "Delta Lake support requires the 'deltalake' package. "
            "Install it with: uv add deltalake --optional table-formats"
        ) from exc

    try:
        if version is None:
            return DeltaTable(str(table_path))
        return DeltaTable(str(table_path), version=version)
    except Exception as exc:
        raise DeltaExportError(f"Cannot open Delta table at '{table_path}': {exc}") from exc


def _validate_export_paths(table_dir: Path, out_dir: Path, file_name: str) -> None:
    """Reject file names and output dirs that could escape the export layout."""
    if not file_name or file_name != Path(file_name).name or file_name.startswith("."):
        raise DeltaExportError(
            f"Invalid file_name {file_name!r}: must be a plain file name inside the output directory."
        )
    if not file_name.endswith(".parquet"):
        raise DeltaExportError(f"Invalid file_name {file_name!r}: expected a '.parquet' file.")
    table_resolved = table_dir.resolve()
    out_resolved = out_dir.resolve() if out_dir.exists() else (out_dir.parent.resolve() / out_dir.name)
    if (
        out_resolved == table_resolved
        or table_resolved in out_resolved.parents
        or out_resolved in table_resolved.parents
    ):
        raise DeltaExportError(
            f"Refusing to export into '{out_dir}': output must not overlap the Delta table directory."
        )


def export_delta_to_parquet(
    table_path: Path | str,
    output_dir: Path | str,
    *,
    version: int | None = None,
    file_name: str = "data.parquet",
    max_rows_per_file: int = 1_000_000,
) -> DeltaExportResult:
    """Export a Delta table directory to plain Parquet files.

    The table is read as a lazy Arrow dataset and streamed to Parquet, so
    exports stay bounded in memory regardless of table size. Partitioned
    tables keep their Hive-style layout (one file group per partition);
    unpartitioned tables that fit in one chunk land in ``file_name``.
    The new tree is staged in a sibling temp directory and published with
    an atomic directory swap, so ``output_dir`` is either the complete new
    export or the previous one — never partial, and reusing the directory
    with a different file name or layout cannot leave stale snapshots
    behind (safe to retry or to glob from ClickHouse). Consumers of
    partitioned outputs must glob ``**/*.parquet`` (or iterate
    ``result.parquet_files``): a flat ``*.parquet`` glob misses the Hive
    subdirectories by design.

    Args:
        table_path: Local path to the Delta table directory (must contain
            a ``_delta_log`` subdirectory).
        output_dir: Directory receiving the exported ``.parquet`` file(s).
        version: Delta version to export; ``None`` exports the latest version.
        file_name: Name of the single Parquet file written into ``output_dir``
            for unpartitioned single-chunk tables.
        max_rows_per_file: Row cap per emitted Parquet file.

    Returns:
        DeltaExportResult with the exported version, row count, columns,
        and written files.

    Raises:
        DeltaExportError: If the table cannot be opened or the export fails.
    """
    table_dir = Path(table_path)
    if not (table_dir / "_delta_log").is_dir():
        raise DeltaExportError(
            f"No Delta table at '{table_dir}': missing '_delta_log' directory. "
            "ClickHouse Delta ingestion requires a Delta Lake source."
        )

    out_dir = Path(output_dir)
    _validate_export_paths(table_dir, out_dir, file_name)

    dt = _load_delta_table(table_dir, version)
    try:
        dataset = dt.to_pyarrow_dataset()
        resolved_version = dt.version()
        metadata = dt.metadata()
        partition_columns = list(getattr(metadata, "partition_columns", None) or [])
    except Exception as exc:
        raise DeltaExportError(f"Failed to read Delta table at '{table_dir}': {exc}") from exc

    run_id = uuid.uuid4().hex[:12]
    staging_dir = out_dir.parent / f".{out_dir.name}.export-tmp-{run_id}"
    backup_dir = out_dir.parent / f".{out_dir.name}.export-backup-{run_id}"
    try:
        out_dir.parent.mkdir(parents=True, exist_ok=True)
        import pyarrow as pa
        import pyarrow.dataset as ds

        partitioning = None
        if partition_columns:
            partitioning = ds.partitioning(
                pa.schema(
                    [dataset.schema.field(name) for name in partition_columns],
                    metadata=dataset.schema.metadata,
                ),
                flavor="hive",
            )
        ds.write_dataset(
            dataset,
            str(staging_dir),
            format="parquet",
            partitioning=partitioning,
            basename_template="part-{i}.parquet",
            max_rows_per_file=max_rows_per_file,
            max_rows_per_group=max_rows_per_file,
        )
        # An empty table writes no files (and possibly no directory); the
        # swap below still publishes an empty output tree.
        staging_dir.mkdir(parents=True, exist_ok=True)
        staged = sorted(p for p in staging_dir.rglob("*") if p.is_file())
        row_count = dataset.count_rows()
        column_names = dataset.schema.names

        if len(staged) == 1 and not partition_columns:
            os.replace(staged[0], staging_dir / file_name)

        # Atomic publish: the previous tree (if any) moves aside, the new
        # tree swaps in, then the backup is dropped. Readers see either the
        # complete old export or the complete new one.
        if out_dir.exists() or out_dir.is_symlink():
            os.replace(out_dir, backup_dir)
        os.replace(staging_dir, out_dir)
        if backup_dir.is_symlink() or backup_dir.is_file():
            backup_dir.unlink(missing_ok=True)
        elif backup_dir.is_dir():
            shutil.rmtree(backup_dir, ignore_errors=True)
        moved = sorted(p for p in out_dir.rglob("*") if p.is_file())
    except Exception as exc:
        if backup_dir.exists() and not out_dir.exists():
            try:
                os.replace(backup_dir, out_dir)
            except OSError:
                logger.warning(f"Could not restore previous export at '{out_dir}' after failed publish")
        raise DeltaExportError(f"Failed to export Delta table at '{table_dir}': {exc}") from exc
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    logger.info(
        f"Exported Delta table '{table_dir}' version {resolved_version} "
        f"({row_count:,} rows) to {len(moved)} Parquet file(s) in {out_dir}"
    )
    return DeltaExportResult(
        table_path=str(table_dir),
        output_dir=out_dir,
        version=resolved_version,
        row_count=row_count,
        column_names=column_names,
        parquet_files=moved,
    )
