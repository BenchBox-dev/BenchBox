"""I/O operations for manifest v1 and v2."""

import json
from pathlib import Path
from typing import Any

from benchbox.core.manifest.models import (
    ConvertedFileEntry,
    FileEntry,
    ManifestV1,
    ManifestV2,
    PlanMetadata,
    TableFormats,
)
from benchbox.utils.file_format import is_csv_format, is_parquet_format, is_tpc_format


def detect_version(manifest_dict: dict[str, Any]) -> int:
    """Detect manifest version (1 or 2).

    Args:
        manifest_dict: Parsed JSON manifest data

    Returns:
        1 for v1 format, 2 for v2 format
    """
    if "version" in manifest_dict:
        return manifest_dict["version"]

    # v1: tables -> {table_name: [files]}
    # v2: tables -> {table_name: {formats: {format: [files]}}}
    tables = manifest_dict.get("tables", {})
    if not tables:
        return 1

    first_table_value = next(iter(tables.values()))
    if isinstance(first_table_value, dict) and "formats" in first_table_value:
        return 2

    return 1


def load_manifest(manifest_path: Path) -> ManifestV1 | ManifestV2:
    """Load manifest, auto-detecting version.

    Args:
        manifest_path: Path to JSON manifest file

    Returns:
        ManifestV1 or ManifestV2 instance based on detected version
    """
    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)

    version = detect_version(data)

    if version == 1:
        return _parse_v1(data)
    else:
        return _parse_v2(data)


def _parse_v1(data: dict) -> ManifestV1:
    """Parse v1 manifest.

    Args:
        data: Raw JSON data

    Returns:
        ManifestV1 instance
    """
    tables = {}
    for table_name, files in data.get("tables", {}).items():
        tables[table_name] = [
            FileEntry(path=f["path"], size_bytes=f["size_bytes"], row_count=f["row_count"]) for f in files
        ]

    return ManifestV1(
        benchmark=data["benchmark"],
        scale_factor=data["scale_factor"],
        tables=tables,
        compression=data.get("compression"),
        parallel=data.get("parallel"),
        created_at=data.get("created_at"),
        generator_version=data.get("generator_version"),
    )


def _parse_v2(data: dict) -> ManifestV2:
    """Parse v2 manifest.

    Args:
        data: Raw JSON data

    Returns:
        ManifestV2 instance
    """
    tables = {}
    for table_name, table_data in data.get("tables", {}).items():
        formats_dict = {}
        for format_name, files in table_data.get("formats", {}).items():
            formats_dict[format_name] = [
                ConvertedFileEntry(
                    path=f["path"],
                    size_bytes=f["size_bytes"],
                    row_count=f["row_count"],
                    converted_from=f.get("converted_from"),
                    converted_at=f.get("converted_at"),
                    compression=f.get("compression"),
                    row_groups=f.get("row_groups"),
                    is_directory=bool(f.get("is_directory", False)),
                    conversion_options=f.get("conversion_options", {}),
                    metadata=f.get("metadata", {}),
                )
                for f in files
            ]
        tables[table_name] = TableFormats(formats=formats_dict)

    # Parse plan metadata if present
    plan_metadata = None
    if "plan_metadata" in data:
        plan_metadata = PlanMetadata.from_dict(data["plan_metadata"])

    return ManifestV2(
        version=data.get("version", 2),
        benchmark=data.get("benchmark"),
        scale_factor=data.get("scale_factor"),
        tables=tables,
        format_preference=data.get("format_preference", []),
        compression=data.get("compression"),
        parallel=data.get("parallel"),
        created_at=data.get("created_at"),
        generator_version=data.get("generator_version"),
        plan_metadata=plan_metadata,
    )


def upgrade_v1_to_v2(v1: ManifestV1) -> ManifestV2:
    """Migrate v1 manifest to v2 structure.

    Args:
        v1: ManifestV1 instance to upgrade

    Returns:
        ManifestV2 instance with tables nested under formats
    """
    tables = {}
    format_name = "tbl"  # Default format if no tables present
    for table_name, files in v1.tables.items():
        # Detect format from file extension
        format_name = _detect_format_from_files(files)

        converted_files = [
            ConvertedFileEntry(
                path=f.path,
                size_bytes=f.size_bytes,
                row_count=f.row_count,
            )
            for f in files
        ]

        tables[table_name] = TableFormats(formats={format_name: converted_files})

    return ManifestV2(
        version=2,
        benchmark=v1.benchmark,
        scale_factor=v1.scale_factor,
        tables=tables,
        format_preference=[format_name, "tbl", "csv"],  # Prefer detected format
        compression=v1.compression,
        parallel=v1.parallel,
        created_at=v1.created_at,
        generator_version=v1.generator_version,
    )


def _detect_format_from_files(files: list[FileEntry]) -> str:
    """Detect format from file extensions.

    Args:
        files: List of file entries

    Returns:
        Format name (tbl, parquet, csv, etc.)
    """
    if not files:
        return "tbl"

    path = files[0].path
    if is_parquet_format(path):
        return "parquet"
    elif is_tpc_format(path):
        return "tbl"
    elif is_csv_format(path):
        return "csv"
    else:
        return "tbl"


def write_manifest(manifest: ManifestV1 | ManifestV2, path: Path) -> None:
    """Write manifest to JSON file.

    Args:
        manifest: Manifest instance to write
        path: Output path for JSON file
    """
    if isinstance(manifest, ManifestV1):
        # Convert v1 to dict
        data = _manifest_v1_to_dict(manifest)
    else:
        # Convert v2 to dict
        data = _manifest_v2_to_dict(manifest)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _manifest_v1_to_dict(manifest: ManifestV1) -> dict:
    """Convert ManifestV1 to dict.

    Args:
        manifest: ManifestV1 instance

    Returns:
        Dictionary suitable for JSON serialization
    """
    tables = {}
    for table_name, files in manifest.tables.items():
        tables[table_name] = [{"path": f.path, "size_bytes": f.size_bytes, "row_count": f.row_count} for f in files]

    result = {
        "benchmark": manifest.benchmark,
        "scale_factor": manifest.scale_factor,
        "tables": tables,
    }

    # Add optional fields only if they have values
    if manifest.compression is not None:
        result["compression"] = manifest.compression
    if manifest.parallel is not None:
        result["parallel"] = manifest.parallel
    if manifest.created_at is not None:
        result["created_at"] = manifest.created_at
    if manifest.generator_version is not None:
        result["generator_version"] = manifest.generator_version

    return result


_FILE_OPTIONAL_FIELDS = ["converted_from", "converted_at", "compression", "row_groups", "conversion_options"]
_MANIFEST_OPTIONAL_FIELDS = [
    "benchmark",
    "scale_factor",
    "format_preference",
    "compression",
    "parallel",
    "created_at",
    "generator_version",
]


def _manifest_v2_to_dict(manifest: ManifestV2) -> dict:
    """Convert ManifestV2 to dict.

    Args:
        manifest: ManifestV2 instance

    Returns:
        Dictionary suitable for JSON serialization
    """
    tables = {}
    for table_name, table_formats in manifest.tables.items():
        formats_dict = {}
        for format_name, files in table_formats.formats.items():
            file_dicts = []
            for f in files:
                file_dict = {
                    "path": f.path,
                    "size_bytes": f.size_bytes,
                    "row_count": f.row_count,
                }
                for attr in _FILE_OPTIONAL_FIELDS:
                    value = getattr(f, attr, None)
                    if value is not None and value:
                        file_dict[attr] = value
                if f.is_directory:
                    file_dict["is_directory"] = True
                file_dicts.append(file_dict)

            formats_dict[format_name] = file_dicts
        tables[table_name] = {"formats": formats_dict}

    result: dict = {
        "version": 2,
        "tables": tables,
    }

    for attr in _MANIFEST_OPTIONAL_FIELDS:
        value = getattr(manifest, attr, None)
        if value is not None and value:
            result[attr] = value

    if manifest.plan_metadata is not None:
        metadata_dict = manifest.plan_metadata.to_dict()
        if metadata_dict:
            result["plan_metadata"] = metadata_dict

    return result
