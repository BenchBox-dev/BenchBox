"""Data Vault cross-surface gate builder (staged)."""

from __future__ import annotations

import logging
from pathlib import Path

from benchbox.core.equivalence.builders.base import CrossSurfaceData, _load_duckdb_cell

logger = logging.getLogger(__name__)


def build_datavault_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate Data Vault data, load it into in-memory DuckDB, and wire both surfaces.

    Regeneration is forced on every build: probes must never pass on a stale
    manifest from a previous run. The datagen manifest written by this exact
    generation is logged, so every gate run records which probe manifest its
    cell came from.
    """
    from benchbox.core.datavault.benchmark import DataVaultBenchmark
    from benchbox.core.datavault.dataframe_queries import DATAVAULT_DATAFRAME_QUERIES
    from benchbox.core.datavault.schema import LOADING_ORDER
    from benchbox.utils.datagen_manifest import MANIFEST_FILENAME, load_manifest, summarise_manifest

    output_dir = Path(output_dir)
    benchmark = DataVaultBenchmark(scale_factor=scale_factor, output_dir=output_dir, force_regenerate=True)
    benchmark.generate_data()

    manifest_path = output_dir / MANIFEST_FILENAME
    manifest = load_manifest(manifest_path)
    table_count, file_count = summarise_manifest(manifest)
    logger.info(
        "Data Vault gate probe manifest: %s (benchmark=%s scale_factor=%s tables=%d files=%d)",
        manifest_path,
        manifest.get("benchmark"),
        manifest.get("scale_factor"),
        table_count,
        file_count,
    )

    connection = _load_duckdb_cell(benchmark, output_dir, list(LOADING_ORDER), label="Data Vault")
    queries = DATAVAULT_DATAFRAME_QUERIES
    return CrossSurfaceData(
        connection=connection,
        query_ids=queries.get_query_ids(),
        reference_sql=lambda query_id: benchmark.get_query(int(str(query_id).lstrip("Q"))),
        dataframe_query=lambda query_id: queries.get_or_raise(str(query_id)),
        benchmark=benchmark,
        data_dir=output_dir,
    )
