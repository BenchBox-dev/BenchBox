"""Manifest management for multi-format benchmark data tracking.

This module provides support for both v1 (legacy) and v2 (multi-format) manifests.
"""

from benchbox.core.manifest.io import (
    detect_version,
    load_manifest,
    upgrade_v1_to_v2,
    write_manifest,
)
from benchbox.core.manifest.models import (
    PLAN_FINGERPRINT_SCHEME_LITERAL,
    PLAN_FINGERPRINT_SCHEME_NORMALIZED,
    ConvertedFileEntry,
    FileEntry,
    ManifestV1,
    ManifestV2,
    PlanMetadata,
    TableFormats,
)
from benchbox.core.manifest.plan_metadata_utils import (
    PlanFingerprintSchemeMismatchError,
    create_plan_metadata_from_results,
    merge_plan_metadata,
    update_plan_versions,
    validate_plan_metadata,
)
from benchbox.core.manifest.preferences import (
    get_files_for_format,
    get_preferred_format,
)

__all__ = [
    # Models
    "PLAN_FINGERPRINT_SCHEME_LITERAL",
    "PLAN_FINGERPRINT_SCHEME_NORMALIZED",
    "ConvertedFileEntry",
    "FileEntry",
    "ManifestV1",
    "ManifestV2",
    "PlanMetadata",
    "TableFormats",
    # I/O
    "detect_version",
    "load_manifest",
    "upgrade_v1_to_v2",
    "write_manifest",
    # Preferences
    "get_files_for_format",
    "get_preferred_format",
    # Plan Metadata Utils
    "PlanFingerprintSchemeMismatchError",
    "create_plan_metadata_from_results",
    "merge_plan_metadata",
    "update_plan_versions",
    "validate_plan_metadata",
]
