"""Apache Iceberg local table-layout helpers for BenchBox.

Centralizes the "is this directory an Iceberg table, and which metadata file
is current" predicate so adapters and validation code share one definition
instead of re-implementing the metadata-directory check per module.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union


def is_iceberg_directory(path: Union[str, Path]) -> bool:
    """Return whether a local path is an Iceberg table directory."""
    path = Path(path)
    metadata = path / "metadata"
    if not path.is_dir() or not metadata.is_dir():
        return False
    return (metadata / "version-hint.text").exists() or bool(list(metadata.glob("*.metadata.json")))


def resolve_iceberg_metadata_file(path: Union[str, Path]) -> Path | None:
    """Return the current Iceberg metadata file for a table directory, if any.

    Prefers the newest ``metadata/*.metadata.json`` by file name. Iceberg
    writers use zero-padded sequence prefixes (``00000-<uuid>.metadata.json``),
    so lexicographic order matches snapshot order. Returns None when the path
    is not an Iceberg table directory.
    """
    path = Path(path)
    if not is_iceberg_directory(path):
        return None
    candidates = sorted((path / "metadata").glob("*.metadata.json"), key=lambda p: p.name)
    if not candidates:
        return None
    return candidates[-1]
