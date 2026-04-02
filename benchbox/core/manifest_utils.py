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
        manifest.add_entry(table, path, row_count=row_count)

    manifest.write()
