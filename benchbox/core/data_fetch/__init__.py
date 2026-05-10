"""Reusable data-fetch infrastructure for real-data benchmarks.

Foundation w2 ships the skeleton; cutover TODO instantiates it for
joinorder via `benchbox/core/joinorder/data_manifest.toml`. Future
benchmarks (ClickBench, Wikipedia pageviews, GitHub Archive, etc.)
reuse the same machinery.

Public API:

    fetch_data(benchmark_id, manifest_path, output_dir) -> Path

        Resolve the per-benchmark manifest, ensure the archive is
        present + sha256-verified at output_dir, and return the
        verified directory.

Exceptions (also re-exported from the top-level errors module):
    DataFetchError, ManifestValidationError, ChecksumMismatchError,
    DownloadError.

This module is benchmark-agnostic by contract. joinorder-specific
configuration lives in benchbox/core/joinorder/data_manifest.toml.
"""

from __future__ import annotations

from .errors import (
    ChecksumMismatchError,
    DataFetchError,
    DownloadError,
    ManifestValidationError,
)
from .manager import fetch_data
from .manifest import DataManifest, TableEntry, load_manifest

__all__ = [
    "fetch_data",
    "DataManifest",
    "TableEntry",
    "load_manifest",
    "DataFetchError",
    "ManifestValidationError",
    "ChecksumMismatchError",
    "DownloadError",
]
