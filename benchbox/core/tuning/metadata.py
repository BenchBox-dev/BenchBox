"""Tuning metadata management system for BenchBox.

This module provides database metadata table management for tracking and validating
tuning configurations across benchmark executions. It ensures database compatibility
when reusing databases with different tuning configurations.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from .interface import BenchmarkTunings, TableTuning, TuningColumn, TuningType, UnifiedTuningConfiguration

logger = logging.getLogger(__name__)

# The subset of TuningType values that _rebuild_tunings_from_records knows how
# to place into a TableTuning (column-based, per-table tunings). Any other
# tuning_type value found in the metadata table -- including the sentinel
# section-hash / schema-version marker rows written under
# TuningMetadataManager._SECTION_MARKER_TABLE -- is not column data and must
# be skipped rather than fed into the table-keyed reconstruction.
_COLUMN_TUNING_TYPE_VALUES = frozenset(
    {
        TuningType.PARTITIONING.value,
        TuningType.CLUSTERING.value,
        TuningType.DISTRIBUTION.value,
        TuningType.SORTING.value,
    }
)


@dataclass
class TuningMetadata:
    """Represents a single tuning metadata record."""

    table_name: str
    tuning_type: str
    column_name: str
    column_order: int
    configuration_hash: str
    created_at: datetime
    platform: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "table_name": self.table_name,
            "tuning_type": self.tuning_type,
            "column_name": self.column_name,
            "column_order": self.column_order,
            "configuration_hash": self.configuration_hash,
            "created_at": self.created_at.isoformat(),
            "platform": self.platform,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TuningMetadata":
        """Create from dictionary representation."""
        created_at = data["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        return cls(
            table_name=data["table_name"],
            tuning_type=data["tuning_type"],
            column_name=data["column_name"],
            column_order=data["column_order"],
            configuration_hash=data["configuration_hash"],
            created_at=created_at,
            platform=data["platform"],
        )


@dataclass
class MetadataValidationResult:
    """Result of tuning metadata validation.

    `drifted_sections` names the coarse-grained config sections (see
    `TuningMetadataManager._CONSTRAINTS_SECTION` /
    `_PLATFORM_OPTIMIZATIONS_SECTION`) whose persisted canonical hash no
    longer matches the expected `UnifiedTuningConfiguration`. It is additive
    and safe to ignore for callers that only care about `is_valid`/`errors`;
    it exists so a richer drift-reporting consumer (e.g. the applied-ledger
    drift_check companion) can tell *which* section drifted without
    re-parsing `errors` strings.
    """

    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_tables: set[str] = field(default_factory=set)
    extra_tables: set[str] = field(default_factory=set)
    configuration_mismatches: dict[str, str] = field(default_factory=dict)
    drifted_sections: set[str] = field(default_factory=set)

    def add_error(self, message: str) -> None:
        """Add an error and mark validation as failed."""
        self.errors.append(message)
        self.is_valid = False

    def add_warning(self, message: str) -> None:
        """Add a warning."""
        self.warnings.append(message)

    def has_issues(self) -> bool:
        """Check if there are any errors or warnings."""
        return len(self.errors) > 0 or len(self.warnings) > 0

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the ``.applied.json`` companion ``drift_check`` section.

        Deterministic (sets rendered as sorted lists) so two identical drift
        outcomes serialize byte-identically. Empty collections are omitted so a
        clean reuse renders a minimal ``{"is_valid": true}``.
        """
        payload: dict[str, Any] = {"is_valid": self.is_valid}
        if self.errors:
            payload["errors"] = list(self.errors)
        if self.warnings:
            payload["warnings"] = list(self.warnings)
        if self.missing_tables:
            payload["missing_tables"] = sorted(self.missing_tables)
        if self.extra_tables:
            payload["extra_tables"] = sorted(self.extra_tables)
        if self.configuration_mismatches:
            payload["configuration_mismatches"] = dict(sorted(self.configuration_mismatches.items()))
        if self.drifted_sections:
            payload["drifted_sections"] = sorted(self.drifted_sections)
        return payload


class TuningMetadataManager:
    """Manages tuning metadata operations for database validation.

    Widened persistence (unique/check constraints + platform optimizations):
    `UnifiedTuningConfiguration.unique_constraints`, `.check_constraints`, and
    `.platform_optimizations` are whole-config toggles/settings, not per-table
    per-column data like partitioning/clustering/distribution/sorting. Rather
    than change the `benchbox_tuning_metadata` table's DDL (which would need a
    migration for every platform adapter), each of those two sections is
    persisted as a canonical SHA-256 hash in a sentinel data *row* that reuses
    the existing (table_name, tuning_type, column_name, column_order,
    configuration_hash, created_at, platform) schema -- see
    `_SECTION_MARKER_TABLE` / `_build_section_marker_records`. This keeps the
    schema itself unchanged (additive at the data level only), so tables
    written by older BenchBox versions -- which simply lack these sentinel
    rows -- still load without error; `_load_section_markers` returning empty
    is treated as "no drift data available" (a warning), never an error.
    """

    # Sentinel `table_name` used for section-hash / schema-version marker
    # rows. Not a real benchmark table -- `_rebuild_tunings_from_records`
    # filters it out so it never leaks into a loaded `BenchmarkTunings`.
    _SECTION_MARKER_TABLE = "__benchbox_tuning_sections__"

    # Sentinel `tuning_type` values for marker rows (never a `TuningType`
    # enum value, so they can't collide with real column-tuning rows).
    _TUNING_TYPE_SCHEMA_VERSION = "schema_version"
    _TUNING_TYPE_CONSTRAINTS_HASH = "constraints_hash"
    _TUNING_TYPE_PLATFORM_OPT_HASH = "platform_optimizations_hash"
    _TUNING_TYPE_TABLE_ATTRIBUTES_HASH = "table_attributes_hash"

    # Bumped whenever the *shape* of what gets hashed into the section-marker
    # rows changes (e.g. a new field folded into the constraints payload).
    # The reader branches on this value so legacy rows are never compared
    # against a hash shape they did not persist.
    _METADATA_SCHEMA_VERSION = 3

    # `MetadataValidationResult.drifted_sections` values.
    _CONSTRAINTS_SECTION = "constraints"
    _PLATFORM_OPTIMIZATIONS_SECTION = "platform_optimizations"
    _TABLE_ATTRIBUTES_SECTION = "table_attributes"

    def __init__(
        self,
        platform_adapter,
        database_name: Optional[str] = None,
        connection_config: Optional[dict[str, Any]] = None,
    ):
        """Initialize the metadata manager.

        Args:
            platform_adapter: Database platform adapter instance
            database_name: Optional database name for isolation
            connection_config: Exact connection settings used by validation
        """
        self.platform_adapter = platform_adapter
        self.database_name = database_name
        self.connection_config = dict(connection_config or {})
        self.logger = logging.getLogger(f"{self.__class__.__name__}")
        self._metadata_table_name = "benchbox_tuning_metadata"
        self._table_exists = None  # Cache for table existence check
        self.last_load_error: str | None = None
        self.marker_save_failed = False

    def _connection_kwargs(self) -> dict[str, Any]:
        """Use the validated database name instead of silently falling back to another database."""
        config = dict(self.platform_adapter.platform_config)
        config.update(self.connection_config)
        if self.database_name is not None:
            config["database"] = self.database_name
        return config

    def _platform_key(self) -> str:
        """Return the canonical platform type key for lookups and persistence.

        Prefers the adapter's `canonical_platform_type` (the machine-readable
        CLI/config type key, e.g. 'clickhouse-local'); falls back to a
        normalized `platform_name` for lightweight adapters/stubs that do not
        expose the property. The display name (`platform_name`) must never be
        stored or used for dialect dispatch -- multi-word display strings like
        'ClickHouse Local' do not match any canonical key.
        """
        canonical = getattr(self.platform_adapter, "canonical_platform_type", None)
        if canonical:
            return str(canonical).strip().lower()
        return str(self.platform_adapter.platform_name).strip().lower().replace(" ", "-")

    @staticmethod
    def _hash_section(payload: dict[str, Any]) -> str:
        """Canonical SHA-256 hash of a config section's dict representation.

        Uses the same sort_keys + compact-separator recipe as
        `BenchmarkTunings.get_configuration_hash` so equal configurations
        always hash identically regardless of dict insertion order.
        """
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @staticmethod
    def _constraints_payload(unified_config: UnifiedTuningConfiguration, *, legacy: bool = False) -> dict[str, Any]:
        payload = {
            "unique_constraints": unified_config.unique_constraints.to_dict(),
            "check_constraints": unified_config.check_constraints.to_dict(),
        }
        if not legacy:
            payload = {
                "primary_keys": unified_config.primary_keys.to_dict(),
                "foreign_keys": unified_config.foreign_keys.to_dict(),
                **payload,
            }
        return payload

    @staticmethod
    def _table_attributes_payload(unified_config: UnifiedTuningConfiguration) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for table_name, table_tuning in sorted(unified_config.table_tunings.items()):
            sections: dict[str, Any] = {}
            for tuning_type in TuningType:
                columns = table_tuning.get_columns_by_type(tuning_type)
                if columns:
                    sections[tuning_type.value] = [column.to_dict() for column in columns]
            payload[table_name] = sections
        return payload

    def _build_section_marker_records(
        self, unified_config: UnifiedTuningConfiguration, platform: str, created_at: datetime
    ) -> list["TuningMetadata"]:
        """Build the sentinel rows that carry the constraints/platform-optimizations
        section hashes plus a schema-version marker, using the existing
        TuningMetadata row shape (see `_SECTION_MARKER_TABLE`).
        """
        constraints_payload = self._constraints_payload(unified_config)
        platform_optimizations_payload = unified_config.platform_optimizations.to_dict()
        table_attributes_payload = self._table_attributes_payload(unified_config)

        return [
            TuningMetadata(
                table_name=self._SECTION_MARKER_TABLE,
                tuning_type=self._TUNING_TYPE_SCHEMA_VERSION,
                column_name="schema_version",
                column_order=self._METADATA_SCHEMA_VERSION,
                configuration_hash=str(self._METADATA_SCHEMA_VERSION),
                created_at=created_at,
                platform=platform,
            ),
            TuningMetadata(
                table_name=self._SECTION_MARKER_TABLE,
                tuning_type=self._TUNING_TYPE_CONSTRAINTS_HASH,
                column_name="constraints_hash",
                column_order=0,
                configuration_hash=self._hash_section(constraints_payload),
                created_at=created_at,
                platform=platform,
            ),
            TuningMetadata(
                table_name=self._SECTION_MARKER_TABLE,
                tuning_type=self._TUNING_TYPE_PLATFORM_OPT_HASH,
                column_name="platform_optimizations_hash",
                column_order=0,
                configuration_hash=self._hash_section(platform_optimizations_payload),
                created_at=created_at,
                platform=platform,
            ),
            TuningMetadata(
                table_name=self._SECTION_MARKER_TABLE,
                tuning_type=self._TUNING_TYPE_TABLE_ATTRIBUTES_HASH,
                column_name="table_attributes_hash",
                column_order=0,
                configuration_hash=self._hash_section(table_attributes_payload),
                created_at=created_at,
                platform=platform,
            ),
        ]

    def _save_section_markers(self, unified_config: UnifiedTuningConfiguration) -> bool:
        """Persist the constraints/platform-optimizations section-hash markers.

        Best-effort: any failure is logged and swallowed. This is
        supplementary drift-detection data written *after* `save_tunings`
        has already committed the column-based table tunings, so a failure
        here must never be surfaced as an overall save failure (see
        `save_unified_tunings` and the must_preserve "save failure remains
        non-fatal" requirement).
        """
        try:
            if not self.create_metadata_table():
                self.marker_save_failed = True
                return False

            platform = self._platform_key()
            records = self._build_section_marker_records(unified_config, platform, datetime.now())
            self._batch_insert_records(records)
            self.marker_save_failed = False
            return True
        except Exception as e:
            self.marker_save_failed = True
            self.logger.warning(f"Failed to save tuning section markers (non-fatal): {e}")
            return False

    def _load_section_markers(self) -> dict[str, str]:
        """Load section-hash / schema-version marker rows, keyed by tuning_type.

        Returns an empty dict both when the metadata table doesn't exist and
        when it exists but predates this widening (no sentinel rows were
        ever written) -- callers must treat "no markers" as "no drift data
        available", not as an error.
        """
        if not self._table_exists_check():
            return {}

        query_sql = f"""
        SELECT tuning_type, configuration_hash
        FROM {self._metadata_table_name}
        WHERE table_name = '{self._SECTION_MARKER_TABLE}'
        """
        temp_conn = self.platform_adapter.create_connection(**self._connection_kwargs())
        try:
            rows = self._fetch_all(temp_conn, query_sql)
        finally:
            self.platform_adapter.close_connection(temp_conn)

        return dict(rows)

    def _compare_section_hashes(
        self, unified_config: UnifiedTuningConfiguration, result: MetadataValidationResult
    ) -> None:
        """Compare persisted constraints/platform-optimizations section hashes.

        Widens drift detection beyond column-based table tunings: unique/check
        constraints and platform optimizations (z-ordering, liquid clustering,
        bloom filters, auto-optimize/compact, materialized views, ...) are
        whole-config sections with no per-table representation, so they are
        compared here by canonical hash rather than by `_compare_table_tunings`.
        """
        existing_markers = self._load_section_markers()
        if not existing_markers:
            result.add_warning(
                "No section-hash metadata found in database (written by an older BenchBox "
                "version, or no tunings have been saved yet); unique/check constraint and "
                "platform-optimization drift cannot be detected for this database."
            )
            return

        try:
            schema_version = int(existing_markers.get(self._TUNING_TYPE_SCHEMA_VERSION, "1"))
        except (TypeError, ValueError):
            result.add_error("Unreadable tuning metadata schema version; database reuse is unsafe")
            return
        if schema_version > self._METADATA_SCHEMA_VERSION:
            result.add_error(
                f"Unsupported tuning metadata schema version {schema_version}; "
                f"this BenchBox supports up to {self._METADATA_SCHEMA_VERSION}"
            )
            return

        constraints_payload = self._constraints_payload(unified_config, legacy=schema_version < 3)
        if schema_version < 3:
            result.add_warning(
                "Legacy tuning metadata schema does not record primary/foreign-key or column-attribute drift"
            )
        expected_constraints_hash = self._hash_section(constraints_payload)
        expected_platform_opt_hash = self._hash_section(unified_config.platform_optimizations.to_dict())

        existing_constraints_hash = existing_markers.get(self._TUNING_TYPE_CONSTRAINTS_HASH)
        existing_platform_opt_hash = existing_markers.get(self._TUNING_TYPE_PLATFORM_OPT_HASH)
        existing_table_attributes_hash = existing_markers.get(self._TUNING_TYPE_TABLE_ATTRIBUTES_HASH)

        if schema_version >= 3:
            required_markers = {
                self._TUNING_TYPE_CONSTRAINTS_HASH,
                self._TUNING_TYPE_PLATFORM_OPT_HASH,
                self._TUNING_TYPE_TABLE_ATTRIBUTES_HASH,
            }
            missing_markers = sorted(required_markers - existing_markers.keys())
            if missing_markers:
                result.add_error(
                    "Incomplete tuning metadata section markers; database reuse is unsafe "
                    f"(missing: {', '.join(missing_markers)})"
                )
                return

        if existing_constraints_hash is not None and existing_constraints_hash != expected_constraints_hash:
            result.drifted_sections.add(self._CONSTRAINTS_SECTION)
            result.add_error(
                "Primary/foreign/unique/check constraint configuration drift detected: persisted database metadata "
                "does not match the expected configuration (constraint enablement changed since the database was tuned)."
            )

        if existing_platform_opt_hash is not None and existing_platform_opt_hash != expected_platform_opt_hash:
            result.drifted_sections.add(self._PLATFORM_OPTIMIZATIONS_SECTION)
            result.add_error(
                "Platform-optimization configuration drift detected: persisted database metadata "
                "does not match the expected configuration (e.g. z-ordering, liquid clustering, "
                "bloom filters, auto-optimize/compact, or materialized views changed since the "
                "database was tuned)."
            )

        if schema_version >= 3:
            table_attributes_payload = self._table_attributes_payload(unified_config)
            if existing_table_attributes_hash != self._hash_section(table_attributes_payload):
                result.drifted_sections.add(self._TABLE_ATTRIBUTES_SECTION)
                result.configuration_mismatches[self._TABLE_ATTRIBUTES_SECTION] = (
                    "Persisted column attributes do not match expected sort order, null placement, compression, or type"
                )
                result.add_error("Table tuning column attributes drifted from persisted database metadata")

    def create_metadata_table(self) -> bool:
        """Create the tunings metadata table if it doesn't exist.

        Returns:
            True if table was created or already exists, False on error
        """
        if self._table_exists:
            return True

        try:
            # Platform-specific table creation SQL
            create_sql = self._get_create_table_sql()

            self.logger.info(f"Creating tuning metadata table: {self._metadata_table_name}")

            # Create temporary connection for schema operations
            temp_conn = self.platform_adapter.create_connection(**self._connection_kwargs())
            try:
                self._execute_sql(temp_conn, create_sql)

                # Create index for performance
                index_sql = self._get_create_index_sql()
                if index_sql:
                    self._execute_sql(temp_conn, index_sql)
            finally:
                self.platform_adapter.close_connection(temp_conn)

            self._table_exists = True
            return True

        except Exception as e:
            self.logger.error(f"Failed to create metadata table: {e}")
            return False

    def _get_create_table_sql(self) -> str:
        """Get platform-specific CREATE TABLE SQL."""
        platform = self._platform_key()

        # Base table definition
        base_sql = f"""
        CREATE TABLE IF NOT EXISTS {self._metadata_table_name} (
            table_name VARCHAR(255) NOT NULL,
            tuning_type VARCHAR(50) NOT NULL,
            column_name VARCHAR(255) NOT NULL,
            column_order INTEGER NOT NULL,
            configuration_hash VARCHAR(64) NOT NULL,
            created_at TIMESTAMP NOT NULL,
            platform VARCHAR(50) NOT NULL
        )"""

        # Platform-specific modifications
        if platform == "bigquery":
            # BigQuery doesn't support IF NOT EXISTS, but we'll handle that in the adapter
            return base_sql.replace("CREATE TABLE IF NOT EXISTS", "CREATE TABLE")
        elif platform == "snowflake":
            # Snowflake uses TIMESTAMP_NTZ for deterministic timestamps
            return base_sql.replace("TIMESTAMP", "TIMESTAMP_NTZ")
        elif platform == "redshift":
            # Redshift prefers explicit column encoding
            return base_sql + " ENCODE AUTO"
        elif platform in {"clickhouse", "clickhouse-local", "clickhouse-server"}:
            # ClickHouse uses specific engine and ordering. base_sql always ends
            # with the CREATE TABLE's closing ")", so appending here is enough -
            # str.replace(")", ...) would also rewrite every VARCHAR(N) column
            # width's closing paren, corrupting the column definitions.
            return base_sql + " ENGINE = MergeTree() ORDER BY (table_name, tuning_type)"
        else:
            # Default for DuckDB, Databricks, etc.
            return base_sql

    def _get_create_index_sql(self) -> Optional[str]:
        """Get platform-specific index creation SQL."""
        platform = self._platform_key()

        if platform in {"clickhouse", "clickhouse-local", "clickhouse-server"}:
            # ClickHouse uses ORDER BY in table definition, no separate index needed
            return None
        elif platform == "bigquery":
            # BigQuery doesn't support explicit indexes
            return None
        else:
            # Create index for faster lookups
            return f"""
            CREATE INDEX IF NOT EXISTS idx_{self._metadata_table_name}_lookup
            ON {self._metadata_table_name} (table_name, configuration_hash)
            """

    def save_tunings(self, benchmark_tunings: BenchmarkTunings) -> bool:
        """Save tuning configuration to metadata table.

        Args:
            benchmark_tunings: The tuning configuration to save

        Returns:
            True if saved successfully, False otherwise
        """
        try:
            if not self.create_metadata_table():
                return False

            # Clear existing metadata for this configuration
            self.clear_tunings(benchmark_tunings.benchmark_name)

            # Generate configuration hash
            config_hash = benchmark_tunings.get_configuration_hash()
            # Persist the canonical platform type key, not the display name
            platform = self._platform_key()
            current_time = datetime.now()

            # Prepare records to insert
            records = []
            for table_name in benchmark_tunings.get_table_names():
                table_tuning = benchmark_tunings.get_table_tuning(table_name)
                if not table_tuning:
                    continue

                # Create records for each tuning type and column
                for tuning_type in TuningType:
                    columns = table_tuning.get_columns_by_type(tuning_type)
                    if not columns:
                        continue

                    for column in columns:
                        records.append(
                            TuningMetadata(
                                table_name=table_name,
                                tuning_type=tuning_type.value,
                                column_name=column.name,
                                column_order=column.order,
                                configuration_hash=config_hash,
                                created_at=current_time,
                                platform=platform,
                            )
                        )

            # Insert records in batch
            if records:
                self._batch_insert_records(records)
                self.logger.info(f"Saved {len(records)} tuning metadata records")

            return True

        except Exception as e:
            self.logger.error(f"Failed to save tunings: {e}")
            return False

    def _as_benchmark_tunings(
        self, unified_config: UnifiedTuningConfiguration, benchmark_name: str = "unified"
    ) -> BenchmarkTunings:
        """Convert unified tuning config to benchmark tuning representation."""
        return BenchmarkTunings(
            benchmark_name=benchmark_name,
            enable_primary_keys=unified_config.primary_keys.enabled,
            enable_foreign_keys=unified_config.foreign_keys.enabled,
            table_tunings=unified_config.table_tunings.copy(),
        )

    def _as_unified_tunings(self, benchmark_tunings: BenchmarkTunings) -> UnifiedTuningConfiguration:
        """Convert benchmark tuning representation to unified tuning config."""
        unified = UnifiedTuningConfiguration()
        unified.primary_keys.enabled = benchmark_tunings.enable_primary_keys
        unified.foreign_keys.enabled = benchmark_tunings.enable_foreign_keys
        unified.table_tunings.update(benchmark_tunings.table_tunings)
        return unified

    def save_unified_tunings(self, unified_config: UnifiedTuningConfiguration) -> bool:
        """Save a UnifiedTuningConfiguration to the metadata table.

        Persists the column-based table tunings via `save_tunings`, then
        best-effort persists the constraints/platform-optimizations section
        hashes used by `validate_unified_tunings` to widen drift detection.
        A section-marker save failure is logged and swallowed -- it must
        never turn an otherwise-successful save into a failure (metadata
        persistence is diagnostic, not required for the run to proceed).
        """
        try:
            if not isinstance(unified_config, UnifiedTuningConfiguration):
                raise TypeError("Expected UnifiedTuningConfiguration")
            saved = self.save_tunings(self._as_benchmark_tunings(unified_config))
            if saved:
                self._save_section_markers(unified_config)
            return saved
        except Exception as e:
            self.logger.error(f"Failed to save unified tunings: {e}")
            return False

    def load_unified_tunings(self) -> Optional[UnifiedTuningConfiguration]:
        """Load tuning metadata and return as UnifiedTuningConfiguration."""
        try:
            benchmark_tunings = self.load_tunings()
            # `is None` (not a truthiness check) -- see validate_tunings above:
            # a saved config whose only persisted rows are the section-hash
            # markers loads back as a real, non-None BenchmarkTunings with an
            # empty table_tunings dict, which is falsy via __len__. Treating
            # that as "nothing to load" silently drops section-only configs
            # (platform optimizations/constraints, no column tunings) from
            # every caller of this method, e.g. _validate_database_tunings'
            # "DB has tuning metadata but none expected" warning.
            if benchmark_tunings is None:
                return None
            return self._as_unified_tunings(benchmark_tunings)
        except Exception as e:
            self.logger.error(f"Failed to load unified tunings: {e}")
            return None

    def validate_unified_tunings(self, unified_config: UnifiedTuningConfiguration) -> MetadataValidationResult:
        """Validate database metadata against a UnifiedTuningConfiguration.

        Widened comparison: in addition to the existing table-tunings check
        (`validate_tunings`), this compares the persisted constraints and
        platform-optimizations section hashes against `unified_config`, so
        drift in unique/check constraints or platform optimizations
        (z-ordering, liquid clustering, bloom filters, auto-optimize/compact,
        materialized views, ...) on a reused database is no longer invisible.
        Drifted sections are recorded by name in
        `MetadataValidationResult.drifted_sections`.
        """
        try:
            if not isinstance(unified_config, UnifiedTuningConfiguration):
                raise TypeError("Expected UnifiedTuningConfiguration")
            result = self.validate_tunings(self._as_benchmark_tunings(unified_config))
            # Only attempt the section-hash comparison when the metadata
            # table actually exists -- otherwise validate_tunings has
            # already reported "No tuning metadata found in database" and a
            # second "no section-hash metadata" warning would be noise.
            if self._table_exists_check():
                self._compare_section_hashes(unified_config, result)
            return result
        except Exception as e:
            result = MetadataValidationResult(is_valid=False)
            result.add_error(f"Validation failed with error: {e}")
            return result

    def _batch_insert_records(self, records: list[TuningMetadata]) -> None:
        """Insert metadata records in batch."""
        if not records:
            return

        # Build INSERT statement
        insert_sql = f"""
        INSERT INTO {self._metadata_table_name}
        (table_name, tuning_type, column_name, column_order,
         configuration_hash, created_at, platform)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """

        # Prepare parameter lists
        param_lists = []
        for record in records:
            param_lists.append(
                [
                    record.table_name,
                    record.tuning_type,
                    record.column_name,
                    record.column_order,
                    record.configuration_hash,
                    record.created_at,
                    record.platform,
                ]
            )

        # Execute batch insert - handle platforms that don't support batch operations
        temp_conn = self.platform_adapter.create_connection(**self._connection_kwargs())
        try:
            cursor = temp_conn.cursor()
            for params in param_lists:
                cursor.execute(insert_sql, params)
            temp_conn.commit()
        finally:
            self.platform_adapter.close_connection(temp_conn)

    def load_tunings(self, benchmark_name: Optional[str] = None) -> Optional[BenchmarkTunings]:
        """Load tuning configuration from metadata table.

        Args:
            benchmark_name: Optional benchmark name filter

        Returns:
            BenchmarkTunings object if found, None otherwise
        """
        try:
            self.last_load_error = None
            if not self._table_exists_check():
                return None

            # Query metadata records
            query_sql = f"""
            SELECT table_name, tuning_type, column_name, column_order,
                   configuration_hash, created_at, platform
            FROM {self._metadata_table_name}
            ORDER BY table_name, tuning_type, column_order
            """

            temp_conn = self.platform_adapter.create_connection(**self._connection_kwargs())
            try:
                results = self._fetch_all(temp_conn, query_sql)
            finally:
                self.platform_adapter.close_connection(temp_conn)
            if not results:
                return None

            # Group records by table and rebuild tuning configuration
            return self._rebuild_tunings_from_records(results, benchmark_name or "loaded")

        except Exception as e:
            self.last_load_error = str(e)
            self.logger.error(f"Failed to load tunings: {e}")
            return None

    def _table_exists_check(self) -> bool:
        """Check if metadata table exists."""
        if self._table_exists is not None:
            return self._table_exists

        try:
            # Try to query the table
            query_sql = f"SELECT COUNT(*) FROM {self._metadata_table_name} LIMIT 1"
            temp_conn = self.platform_adapter.create_connection(**self._connection_kwargs())
            try:
                self._fetch_one(temp_conn, query_sql)
                self._table_exists = True
                return True
            finally:
                self.platform_adapter.close_connection(temp_conn)
        except Exception as exc:
            self.last_load_error = str(exc)
            self._table_exists = False
            return False

    def _rebuild_tunings_from_records(self, records: list[tuple], benchmark_name: str) -> BenchmarkTunings:
        """Rebuild BenchmarkTunings object from metadata records."""
        benchmark_tunings = BenchmarkTunings(benchmark_name=benchmark_name)

        # Group records by table
        tables = {}
        for record in records:
            (
                table_name,
                tuning_type,
                column_name,
                column_order,
                config_hash,
                created_at,
                platform,
            ) = record

            # Skip section-hash / schema-version marker rows (see
            # _SECTION_MARKER_TABLE): they are not column-tuning data and
            # their tuning_type values are not TuningType columns, so
            # including them here would KeyError below.
            if table_name == self._SECTION_MARKER_TABLE:
                continue
            if tuning_type not in _COLUMN_TUNING_TYPE_VALUES:
                continue

            if table_name not in tables:
                tables[table_name] = {
                    TuningType.PARTITIONING.value: [],
                    TuningType.CLUSTERING.value: [],
                    TuningType.DISTRIBUTION.value: [],
                    TuningType.SORTING.value: [],
                }

            # Include column in appropriate tuning type
            tables[table_name][tuning_type].append(
                TuningColumn(
                    name=column_name,
                    type="UNKNOWN",  # Type not stored in metadata
                    order=column_order,
                )
            )

        # Create TableTuning objects
        for table_name, tuning_columns in tables.items():
            table_tuning = TableTuning(
                table_name=table_name,
                partitioning=tuning_columns[TuningType.PARTITIONING.value] or None,
                clustering=tuning_columns[TuningType.CLUSTERING.value] or None,
                distribution=tuning_columns[TuningType.DISTRIBUTION.value] or None,
                sorting=tuning_columns[TuningType.SORTING.value] or None,
            )

            # Only add if it has actual tuning configurations
            if table_tuning.has_any_tuning():
                benchmark_tunings.add_table_tuning(table_tuning)

        return benchmark_tunings

    def validate_tunings(self, expected_tunings: BenchmarkTunings) -> MetadataValidationResult:
        """Validate that database tunings match expected configuration.

        Args:
            expected_tunings: The expected tuning configuration

        Returns:
            MetadataValidationResult with detailed comparison results
        """
        result = MetadataValidationResult()

        try:
            # Load existing tunings from database
            existing_tunings = self.load_tunings(expected_tunings.benchmark_name)

            # `is None` (not a truthiness check): load_tunings returns None
            # only when the metadata table is missing or truly empty. A
            # config whose only persisted rows are the section-hash markers
            # (see _SECTION_MARKER_TABLE) -- i.e. a saved config with
            # platform optimizations/constraint toggles but zero
            # column-based table tunings -- loads back as a real, non-None
            # BenchmarkTunings with an empty table_tunings dict, which is
            # falsy via __len__. Treating that as "not found" was a false
            # hard error for exactly the whole-config-sections-only scenario
            # this widening exists to validate; it must instead fall through
            # to comparison (which correctly reports "no drift") and let
            # validate_unified_tunings' _compare_section_hashes do its job.
            if existing_tunings is None:
                if self.last_load_error:
                    result.add_error(f"Failed to load tuning metadata: {self.last_load_error}")
                else:
                    result.add_error("No tuning metadata found in database")
                return result

            # Compare configurations
            self._compare_tuning_configurations(expected_tunings, existing_tunings, result)

            if result.is_valid:
                self.logger.info("Tuning configuration validation passed")
            else:
                self.logger.warning(f"Tuning validation failed with {len(result.errors)} errors")

            return result

        except Exception as e:
            result.add_error(f"Validation failed with error: {e}")
            return result

    def _compare_tuning_configurations(
        self,
        expected: BenchmarkTunings,
        existing: BenchmarkTunings,
        result: MetadataValidationResult,
    ) -> None:
        """Compare expected vs existing tuning configurations."""
        # Check configuration hashes first (quick comparison)
        expected_hash = expected.get_configuration_hash()
        existing_hash = existing.get_configuration_hash()

        if expected_hash == existing_hash:
            # Configurations are identical
            return

        # Detailed comparison if hashes don't match
        expected_tables = set(expected.get_table_names())
        existing_tables = set(existing.get_table_names())

        # Find missing and extra tables
        result.missing_tables = expected_tables - existing_tables
        result.extra_tables = existing_tables - expected_tables

        for table_name in result.missing_tables:
            result.add_error(f"Expected tuning for table '{table_name}' not found in database")

        for table_name in result.extra_tables:
            result.add_error(f"Unexpected tuning found for table '{table_name}' in database")

        # Compare common tables
        common_tables = expected_tables & existing_tables
        for table_name in common_tables:
            self._compare_table_tunings(
                expected.get_table_tuning(table_name),
                existing.get_table_tuning(table_name),
                result,
            )

    def _compare_table_tunings(
        self,
        expected: Optional[TableTuning],
        existing: Optional[TableTuning],
        result: MetadataValidationResult,
    ) -> None:
        """Compare tuning configurations for a specific table."""
        if not expected or not existing:
            return

        table_name = expected.table_name

        # Compare each tuning type
        for tuning_type in TuningType:
            expected_columns = expected.get_columns_by_type(tuning_type)
            existing_columns = existing.get_columns_by_type(tuning_type)

            # Convert to comparable format (sorted by order)
            expected_spec = sorted([(col.name, col.order) for col in expected_columns])
            existing_spec = sorted([(col.name, col.order) for col in existing_columns])

            if expected_spec != existing_spec:
                result.configuration_mismatches[f"{table_name}.{tuning_type.value}"] = (
                    f"Expected: {expected_spec}, Found: {existing_spec}"
                )
                result.add_error(
                    f"Table '{table_name}' {tuning_type.value} tuning mismatch: "
                    f"expected {expected_spec}, found {existing_spec}"
                )

    def clear_tunings(self, benchmark_name: Optional[str] = None) -> bool:
        """Clear tuning metadata from the database.

        Args:
            benchmark_name: Optional benchmark name filter (unused in current implementation)

        Returns:
            True if cleared successfully, False otherwise
        """
        try:
            if not self._table_exists_check():
                return True  # Nothing to clear

            # Delete all records (could be filtered by benchmark_name if we stored it)
            delete_sql = f"DELETE FROM {self._metadata_table_name}"
            temp_conn = self.platform_adapter.create_connection(**self._connection_kwargs())
            try:
                self._execute_sql(temp_conn, delete_sql)
            finally:
                self.platform_adapter.close_connection(temp_conn)

            self.logger.info("Cleared tuning metadata")
            return True

        except Exception as e:
            self.logger.error(f"Failed to clear tunings: {e}")
            return False

    def get_metadata_summary(self) -> dict[str, Any]:
        """Get summary of stored tuning metadata.

        Returns:
            Dictionary with metadata statistics
        """
        try:
            if not self._table_exists_check():
                return {"table_exists": False}

            # Query summary statistics. Section-hash / schema-version marker
            # rows (table_name == _SECTION_MARKER_TABLE) are excluded so they
            # don't inflate unique_tables/unique_tuning_types with sentinel
            # bookkeeping data that isn't a real benchmark table.
            summary_sql = f"""
            SELECT
                COUNT(*) as total_records,
                COUNT(DISTINCT table_name) as unique_tables,
                COUNT(DISTINCT tuning_type) as unique_tuning_types,
                COUNT(DISTINCT platform) as unique_platforms,
                MIN(created_at) as oldest_record,
                MAX(created_at) as newest_record
            FROM {self._metadata_table_name}
            WHERE table_name != '{self._SECTION_MARKER_TABLE}'
            """

            temp_conn = self.platform_adapter.create_connection(**self._connection_kwargs())
            try:
                result = self._fetch_one(temp_conn, summary_sql)
            finally:
                self.platform_adapter.close_connection(temp_conn)
            if result:
                return {
                    "table_exists": True,
                    "total_records": result[0],
                    "unique_tables": result[1],
                    "unique_tuning_types": result[2],
                    "unique_platforms": result[3],
                    "oldest_record": result[4],
                    "newest_record": result[5],
                }

            return {"table_exists": True, "no_data": True}

        except Exception as e:
            return {"table_exists": False, "error": str(e)}

    def _execute_sql(self, connection, sql: str, params: Optional[list] = None) -> Any:
        """Execute SQL statement through platform adapter.

        Args:
            connection: Database connection
            sql: SQL statement to execute
            params: Optional query parameters

        Returns:
            Query result if applicable
        """
        # Use platform adapter's query execution method
        if hasattr(self.platform_adapter, "execute_query"):
            result = self.platform_adapter.execute_query(connection, sql, "metadata")
            return result.get("result")
        else:
            # Fall back to direct connection execution
            cursor = connection.cursor()
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)

            try:
                return cursor.fetchall()
            except Exception:
                return None

    def _fetch_all(self, connection, sql: str) -> list[tuple]:
        """Fetch all results from a SELECT query.

        Args:
            connection: Database connection
            sql: SELECT SQL statement

        Returns:
            List of result tuples
        """
        cursor = connection.cursor()
        cursor.execute(sql)
        return cursor.fetchall()

    def _fetch_one(self, connection, sql: str) -> Optional[tuple]:
        """Fetch one result from a SELECT query.

        Args:
            connection: Database connection
            sql: SELECT SQL statement

        Returns:
            Single result tuple or None
        """
        cursor = connection.cursor()
        cursor.execute(sql)
        return cursor.fetchone()
