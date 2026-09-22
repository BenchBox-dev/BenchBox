"""Apache Iceberg local table-layout helpers for BenchBox.

Centralizes the "is this directory an Iceberg table, and which metadata file
is current" predicate so adapters and validation code share one definition
instead of re-implementing the metadata-directory check per module. Also
hosts the metadata-graph relocator used when a locally built table is
staged to cloud storage: copying the tree is not enough because metadata,
manifest lists, and manifests embed the original ``file://`` URIs.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
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


_METADATA_VERSION_RE = re.compile(r"(\d+)-.*\.metadata\.json")


@dataclass
class RelocatedIcebergGraph:
    """An Iceberg metadata graph rewritten for a new table location.

    Data files are byte-identical and are NOT staged here — upload them
    unchanged. Only the graph files (metadata JSON, manifest list,
    manifests) are rewritten into ``staging_dir``.
    """

    metadata_location: str
    """Destination URI of the rewritten current metadata file."""
    graph_files: dict[str, Path] = field(default_factory=dict)
    """Destination-relative path -> local staged file, for every rewritten graph file."""
    data_files: list[str] = field(default_factory=list)
    """Table-relative paths of data files to upload unchanged."""


def relocate_iceberg_table(
    table_dir: Union[str, Path],
    dest_uri: str,
    staging_dir: Union[str, Path],
) -> RelocatedIcebergGraph:
    """Rewrite a local Iceberg table's metadata graph for a new location URI.

    A plain file copy leaves ``file://`` data and manifest references inside
    the metadata JSON, manifest lists, and manifests, so cloud engines cannot
    read the staged table. This rebuilds the graph with PyIceberg's own
    manifest writers: manifest entries are re-emitted with destination data
    URIs (sizes and statistics preserved — the data files themselves are
    untouched), followed by a new manifest list and a new current metadata
    file. Only the current snapshot is relocated; the staged copy is a new
    single-snapshot table, so snapshot and metadata logs are reset.

    Args:
        table_dir: Local Iceberg table directory to relocate.
        dest_uri: Destination table URI prefix (e.g. ``s3://bucket/prefix``).
            Data files are expected at the same relative paths beneath it.
        staging_dir: Local directory receiving the rewritten graph files
            under ``metadata/``.

    Returns:
        RelocatedIcebergGraph with the destination metadata URI, staged
        graph files, and the table-relative data files to upload unchanged.

    Raises:
        ValueError: If ``table_dir`` is not an Iceberg table directory.
    """
    from pyiceberg.io.pyarrow import PyArrowFileIO
    from pyiceberg.manifest import read_manifest_list, write_manifest, write_manifest_list
    from pyiceberg.serializers import ToOutputFile
    from pyiceberg.table.metadata import TableMetadataUtil

    table_path = Path(table_dir)
    metadata_file = resolve_iceberg_metadata_file(table_path)
    if metadata_file is None:
        raise ValueError(f"Not an Iceberg table directory: {table_path}")

    dest_prefix = dest_uri.rstrip("/")
    metadata = TableMetadataUtil.parse_obj(json.loads(metadata_file.read_text(encoding="utf-8")))
    src_prefix = metadata.location.rstrip("/")
    staging = Path(staging_dir)
    (staging / "metadata").mkdir(parents=True, exist_ok=True)
    io = PyArrowFileIO()
    graph_files: dict[str, Path] = {}

    current = next((s for s in metadata.snapshots if s.snapshot_id == metadata.current_snapshot_id), None)
    if current is not None:
        specs = {spec.spec_id: spec for spec in metadata.partition_specs}
        relocated_manifests = []
        for manifest in read_manifest_list(io.new_input(current.manifest_list)):
            entries = manifest.fetch_manifest_entry(io, discard_deleted=False)
            for entry in entries:
                old_path = entry.data_file.file_path
                if old_path.startswith(src_prefix):
                    entry.data_file[1] = dest_prefix + old_path[len(src_prefix) :]
            manifest_rel = f"metadata/reloc-{uuid.uuid4().hex[:8]}.manifest.avro"
            with write_manifest(
                metadata.format_version,
                specs[manifest.partition_spec_id],
                metadata.schema(),
                io.new_output(str(staging / manifest_rel)),
                current.snapshot_id,
                "null",
            ) as writer:
                for entry in entries:
                    status = entry.status.name
                    if status == "DELETED":
                        writer.delete(entry)
                    elif status == "EXISTING":
                        writer.existing(entry)
                    else:
                        writer.add(entry)
                new_manifest = writer.to_manifest_file()
            new_manifest[0] = f"{dest_prefix}/{manifest_rel}"
            relocated_manifests.append(new_manifest)
            graph_files[manifest_rel] = staging / manifest_rel

        list_rel = f"metadata/reloc-{uuid.uuid4().hex[:8]}.avro"
        with write_manifest_list(
            metadata.format_version,
            io.new_output(str(staging / list_rel)),
            current.snapshot_id,
            current.parent_snapshot_id,
            current.sequence_number,
            "null",
        ) as list_writer:
            list_writer.add_manifests(relocated_manifests)
        graph_files[list_rel] = staging / list_rel
        new_manifest_list = f"{dest_prefix}/{list_rel}"
    else:
        new_manifest_list = None

    existing_versions = [
        int(match.group(1))
        for candidate in (table_path / "metadata").glob("*.metadata.json")
        if (match := _METADATA_VERSION_RE.fullmatch(candidate.name)) is not None
    ]
    next_version = (max(existing_versions) + 1) if existing_versions else 0
    meta_rel = f"metadata/{next_version:05d}-{uuid.uuid4().hex}.metadata.json"
    if current is not None:
        new_snapshot = current.model_copy(update={"manifest_list": new_manifest_list})
        metadata = metadata.model_copy(
            update={
                "location": dest_prefix,
                "snapshots": [new_snapshot],
                "snapshot_log": [entry for entry in metadata.snapshot_log if entry.snapshot_id == current.snapshot_id],
                "metadata_log": [],
            }
        )
    else:
        metadata = metadata.model_copy(update={"location": dest_prefix, "metadata_log": []})
    ToOutputFile.table_metadata(metadata, io.new_output(str(staging / meta_rel)))
    graph_files[meta_rel] = staging / meta_rel

    data_files = sorted(
        path.relative_to(table_path).as_posix()
        for path in table_path.rglob("*")
        if path.is_file() and path.relative_to(table_path).parts[0] != "metadata"
    )
    return RelocatedIcebergGraph(
        metadata_location=f"{dest_prefix}/{meta_rel}",
        graph_files=graph_files,
        data_files=data_files,
    )
