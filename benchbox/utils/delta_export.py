"""Delta Lake to Parquet export for engines without native Delta support.

ClickHouse cannot read Delta Lake tables directly. This module provides the
Parquet conversion layer: it reads a Delta table directory (optionally at a
pinned version, giving time travel for free) and writes plain Parquet files
that ClickHouse can ingest via its ``s3(..., 'Parquet')`` table function or
local ``.parquet`` files.

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


def export_delta_to_parquet(
    table_path: Path | str,
    output_dir: Path | str,
    *,
    version: int | None = None,
    file_name: str = "data.parquet",
) -> DeltaExportResult:
    """Export a Delta table directory to plain Parquet files.

    Args:
        table_path: Local path to the Delta table directory (must contain
            a ``_delta_log`` subdirectory).
        output_dir: Directory receiving the exported ``.parquet`` file(s).
        version: Delta version to export; ``None`` exports the latest version.
        file_name: Name of the single Parquet file written into ``output_dir``.

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

    dt = _load_delta_table(table_dir, version)
    try:
        arrow_table = dt.to_pyarrow_table()
        resolved_version = dt.version()
    except Exception as exc:
        raise DeltaExportError(f"Failed to read Delta table at '{table_dir}': {exc}") from exc

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = out_dir / file_name
    try:
        import pyarrow.parquet as pq

        pq.write_table(arrow_table, parquet_path)
    except Exception as exc:
        raise DeltaExportError(f"Failed to write Parquet to '{parquet_path}': {exc}") from exc

    logger.info(
        f"Exported Delta table '{table_dir}' version {resolved_version} "
        f"({arrow_table.num_rows:,} rows) to {parquet_path}"
    )
    return DeltaExportResult(
        table_path=str(table_dir),
        output_dir=out_dir,
        version=resolved_version,
        row_count=arrow_table.num_rows,
        column_names=arrow_table.schema.names,
        parquet_files=[parquet_path],
    )
