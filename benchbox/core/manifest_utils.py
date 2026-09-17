"""Shared utilities for benchmark data-generation manifests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from benchbox.utils.datagen_manifest import DataGenerationManifest, resolve_compression_metadata


def write_generator_manifest(
    generator: Any,
    benchmark_name: str,
    table_paths: dict[str, Path],
    row_counts: dict[str, int],
    metadata: dict[str, Any] | None = None,
) -> None:
    """Write a :class:`DataGenerationManifest` for a generator run.

    This centralises the manifest-writing boilerplate shared across benchmark
    generators (AMPLab, ClickBench, H2O.db, Join-Order).

    Args:
        generator: The generator instance (used to resolve ``output_dir``,
            ``scale_factor``, and compression metadata).
        benchmark_name: Short benchmark identifier (e.g. ``"amplab"``).
        table_paths: Mapping of table name → file path produced by the generator.
        row_counts: Mapping of table name → row count produced by the generator.
        metadata: Optional CSV dialect metadata applied to every table entry.
            Keys follow the DataGenerationManifest.add_entry() metadata contract
            (csv_delimiter, csv_has_header, csv_null_marker, csv_normalize_booleans,
            csv_quote). When None, no metadata is recorded.
    """
    if not table_paths:
        return

    manifest = DataGenerationManifest(
        output_dir=generator.output_dir,
        benchmark=benchmark_name,
        scale_factor=generator.scale_factor,
        compression=resolve_compression_metadata(generator),
        parallel=1,
        seed=None,
    )

    for table, path in table_paths.items():
        row_count = row_counts.get(table, 0)
        manifest.add_entry(table, path, row_count=row_count, metadata=metadata)

    manifest.write()


def write_delimited_manifest(
    generator: Any,
    benchmark_name: str,
    table_paths: dict[str, Path],
    row_counts: dict[str, int],
    *,
    delimiter: str = "|",
    has_header: bool = False,
    null_marker: str | None = None,
    normalize_booleans: bool = False,
) -> None:
    """Write a generator manifest with CSV-dialect metadata for delimited files.

    Shorthand for :func:`write_generator_manifest` covering the common
    pipe/comma-delimited case (AMPLab, ClickBench, vector_search): every table
    entry records the same delimiter, header, null-marker, and boolean
    contract. ``null_marker=""`` means empty fields load as NULL;
    ``None`` preserves empty strings.
    """
    write_generator_manifest(
        generator,
        benchmark_name,
        table_paths,
        row_counts,
        metadata={
            "csv_delimiter": delimiter,
            "csv_has_header": has_header,
            "csv_null_marker": null_marker,
            "csv_normalize_booleans": normalize_booleans,
        },
    )
