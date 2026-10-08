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
    quote: str | None = None,
) -> None:
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
            "csv_quote": quote,
        },
    )
