"""Data models for manifest v1 and v2."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FileEntry:
    """Single file entry (v1 format).

    Represents a basic file in the original manifest format with minimal metadata.
    """

    path: str
    size_bytes: int
    row_count: int


@dataclass
class ConvertedFileEntry:
    """File entry with conversion metadata (v2).

    Extends basic file metadata with information about format conversions,
    including source format, conversion timestamp, and options used.
    """

    path: str
    size_bytes: int
    row_count: int
    converted_from: str | None = None
    converted_at: str | None = None
    compression: str | None = None
    row_groups: int | None = None
    is_directory: bool = False
    conversion_options: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TableFormats:
    """v2: Multiple formats for a single table.

    Groups all available formats for a table (e.g., tbl, parquet, delta, iceberg).
    Each format contains a list of files that comprise that table in that format.
    """

    formats: dict[str, list[ConvertedFileEntry]]


@dataclass
class ManifestV1:
    """Original manifest format.

    Legacy format that tracks a single format per table, typically TBL files.
    Preserved for backward compatibility with existing benchmarks.
    """

    benchmark: str
    scale_factor: float
    tables: dict[str, list[FileEntry]]
    compression: dict[str, Any] | None = None
    parallel: int | None = None
    created_at: str | None = None
    generator_version: str | None = None


# PlanMetadata.normalization_scheme values. "literal" is the default,
# literal-sensitive plan_fingerprint; "normalized" marks fingerprints recorded
# via QueryPlanDAG.normalized_fingerprint (opt-in, seed-independent). Comparing
# fingerprints recorded under different schemes is meaningless - see
# update_plan_versions/merge_plan_metadata, which refuse to do so.
PLAN_FINGERPRINT_SCHEME_LITERAL = "literal"
PLAN_FINGERPRINT_SCHEME_NORMALIZED = "normalized"


@dataclass
class PlanMetadata:
    """Query plan fingerprint and version tracking.

    Tracks plan fingerprints and versions for each query executed during
    a benchmark run. Used for cross-run comparison and regression detection.
    """

    plan_fingerprints: dict[str, str] = field(default_factory=dict)  # query_id → SHA256 fingerprint
    plan_versions: dict[str, int] = field(default_factory=dict)  # query_id → version number
    plan_capture_timestamp: dict[str, str] = field(default_factory=dict)  # query_id → ISO timestamp
    platform: str | None = None
    platform_version: str | None = None
    # Which fingerprint scheme plan_fingerprints was recorded under - "literal"
    # (default) or "normalized". update_plan_versions/merge_plan_metadata compare
    # this before diffing fingerprints across two PlanMetadata instances.
    normalization_scheme: str = PLAN_FINGERPRINT_SCHEME_LITERAL

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        result: dict[str, Any] = {}
        if self.plan_fingerprints:
            result["plan_fingerprints"] = self.plan_fingerprints
        if self.plan_versions:
            result["plan_versions"] = self.plan_versions
        if self.plan_capture_timestamp:
            result["plan_capture_timestamp"] = self.plan_capture_timestamp
        if self.platform:
            result["platform"] = self.platform
        if self.platform_version:
            result["platform_version"] = self.platform_version
        if self.normalization_scheme != PLAN_FINGERPRINT_SCHEME_LITERAL:
            result["normalization_scheme"] = self.normalization_scheme
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanMetadata:
        """Create PlanMetadata from dictionary."""
        return cls(
            plan_fingerprints=data.get("plan_fingerprints", {}),
            plan_versions=data.get("plan_versions", {}),
            plan_capture_timestamp=data.get("plan_capture_timestamp", {}),
            platform=data.get("platform"),
            platform_version=data.get("platform_version"),
            normalization_scheme=data.get("normalization_scheme", PLAN_FINGERPRINT_SCHEME_LITERAL),
        )


@dataclass
class ManifestV2:
    """Enhanced manifest with multi-format support.

    Tracks multiple formats per table, enabling format conversion workflows
    and automatic format selection by platform adapters.

    Format preference defines the order in which formats should be tried
    when loading data (e.g., ["parquet", "delta", "tbl"]).
    """

    version: int = 2
    benchmark: str | None = None
    scale_factor: float | None = None
    tables: dict[str, TableFormats] = field(default_factory=dict)
    format_preference: list[str] = field(default_factory=list)
    compression: dict[str, Any] | None = None
    parallel: int | None = None
    created_at: str | None = None
    generator_version: str | None = None
    plan_metadata: PlanMetadata | None = None
