"""Static build pipeline for the BenchBox results explorer.

Transforms schema-v2 benchmark result bundles into the read model consumed
by the results-explorer frontend.
"""

from __future__ import annotations

from benchbox.core.explorer_pipeline.duckdb_builder import DuckDBSnapshotBuilder
from benchbox.core.explorer_pipeline.models import (
    DetailResult,
    ManifestEntry,
    QueryTiming,
)
from benchbox.core.explorer_pipeline.pipeline import BuildStats, ExplorerPipeline
from benchbox.core.explorer_pipeline.transformer import BundleTransformer

__all__ = [
    "BuildStats",
    "BundleTransformer",
    "DetailResult",
    "DuckDBSnapshotBuilder",
    "ExplorerPipeline",
    "ManifestEntry",
    "QueryTiming",
]
