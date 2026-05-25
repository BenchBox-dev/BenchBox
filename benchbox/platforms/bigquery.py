"""BigQuery platform adapter with native BigQuery SQL and Cloud Storage integration.

Provides BigQuery-specific optimizations for large-scale analytics,
including efficient data loading via Cloud Storage and native BigQuery features.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.platforms.base.config_utils import make_registered_platform_config_builder
from benchbox.platforms.base.tuning import make_informational_constraint_applier
from benchbox.utils.clock import elapsed_seconds, mono_time

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        PlatformOptimizationConfiguration,
        TuningColumn,
        UnifiedTuningConfiguration,
    )

from benchbox.utils.cloud_storage import get_cloud_path_info, is_cloud_path
from benchbox.utils.file_format import detect_compression, detect_data_format
from benchbox.utils.printing import emit

from ..utils.dependencies import check_platform_dependencies, get_dependency_error_message
from .base import DriverIsolationCapability, PlatformAdapter
from .base.data_loading import NO_BENCHMARK, DataSource, resolve_adapter_data_source, resolve_csv_dialect
from .base.runtime_metadata import build_default_normalized_result_metadata

try:
    import google.auth

    google_auth = google.auth  # Store reference for _load_credentials
    from google.cloud import bigquery, storage
    from google.cloud.exceptions import NotFound
    from google.oauth2 import service_account
except ImportError:
    google_auth = None
    bigquery = None
    storage = None
    service_account = None


def _compact_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in payload.items() if value not in (None, "", {}, [], ())}


class BigQueryAdapter(PlatformAdapter):
    """BigQuery platform adapter with Cloud Storage integration."""

    driver_isolation_capability = DriverIsolationCapability.FEASIBLE_CLIENT_ONLY
    supports_external_tables = True
    _DELIMITED_FORMATS = frozenset({"tbl", "csv"})

    def __init__(self, **config):
        super().__init__(**config)

        # Check dependencies with improved error message
        available, missing = check_platform_dependencies("bigquery")
        if not available:
            error_msg = get_dependency_error_message("bigquery", missing)
            raise ImportError(error_msg)

        self._dialect = "bigquery"

        # BigQuery configuration
        self.project_id = config.get("project_id")
        self.dataset_id = config.get("dataset_id") or "benchbox"
        self.location = config.get("location") or "US"
        self.credentials_path = config.get("credentials_path")

        # Cloud Storage settings for data loading
        # Check for staging_root first (set by orchestrator for CloudStagingPath)
        staging_root = config.get("staging_root")
        self.staging_root = staging_root
        if staging_root:
            # Parse gs://bucket/path format to extract bucket and prefix
            from benchbox.utils.cloud_storage import get_cloud_path_info

            path_info = get_cloud_path_info(staging_root)
            if path_info["provider"] in ("gs", "gcs"):
                self.storage_bucket = path_info["bucket"]
                # Use the path component if provided, otherwise use default
                self.storage_prefix = path_info["path"].strip("/") if path_info["path"] else "benchbox-data"
                self.logger.info(
                    f"Using staging location from config: gs://{self.storage_bucket}/{self.storage_prefix}"
                )
            else:
                raise ValueError(f"BigQuery requires GCS (gs://) staging location, got: {path_info['provider']}://")
        else:
            # Fall back to explicit storage_bucket configuration
            self.storage_bucket = config.get("storage_bucket")
            self.storage_prefix = config.get("storage_prefix") or "benchbox-data"

        # Query settings
        self.job_priority = config.get("job_priority") or "INTERACTIVE"  # INTERACTIVE or BATCH
        self.biglake_connection = config.get("biglake_connection")
        # Disable result cache by default for accurate benchmarking
        # Can be overridden with query_cache=true or disable_result_cache=false
        if config.get("query_cache") is not None:
            self.query_cache = config.get("query_cache")
        elif config.get("disable_result_cache") is not None:
            self.query_cache = not config.get("disable_result_cache")
        else:
            # Default: disable cache for accurate benchmark results
            self.query_cache = False
        self.dry_run = config.get("dry_run") if config.get("dry_run") is not None else False
        self.maximum_bytes_billed = config.get("maximum_bytes_billed")

        # Table settings
        self.clustering_fields = config.get("clustering_fields") or []
        self.partitioning_field = config.get("partitioning_field")

        if not self.project_id:
            from ..core.exceptions import ConfigurationError

            raise ConfigurationError(
                "BigQuery configuration requires project_id.\n"
                "Configure with one of:\n"
                "  1. CLI: benchbox platforms setup --platform bigquery\n"
                "  2. Environment variable: BIGQUERY_PROJECT\n"
                "  3. CLI option: --platform-option project_id=<your-project>\n"
                "Also ensure Google Cloud credentials are configured:\n"
                "  - Set GOOGLE_APPLICATION_CREDENTIALS to service account JSON path\n"
                "  - Or run 'gcloud auth application-default login'"
            )

    def _build_ctas_sort_sql(self, table_name: str, sort_columns: list[TuningColumn]) -> str | None:
        """Build opt-in sorted-ingestion SQL for BigQuery."""
        mode, method = self.resolve_sorted_ingestion_strategy()
        if mode == "off":
            return None

        raise ValueError(
            "BigQuery sorted ingestion is not yet executable through this CTAS hook because "
            "the BigQuery client path does not expose execute()/cursor(). Use CLUSTER BY today "
            "or implement BigQuery query-job execution for method "
            f"'{method}'."
        )

    @staticmethod
    def add_cli_arguments(parser: argparse.ArgumentParser) -> None:
        """Add BigQuery-specific CLI arguments."""
        bq_group = parser.add_argument_group("BigQuery Arguments")
        bq_group.add_argument("--project-id", type=str, help="BigQuery project ID")
        bq_group.add_argument("--dataset-id", type=str, help="BigQuery dataset ID")
        bq_group.add_argument("--location", type=str, default="US", help="BigQuery dataset location")
        bq_group.add_argument("--credentials-path", type=str, help="Path to Google Cloud credentials file")
        bq_group.add_argument("--storage-bucket", type=str, help="GCS bucket for data loading")

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        """Create BigQuery adapter from unified configuration."""
        from benchbox.utils.database_naming import generate_database_name

        adapter_config = {}
        very_verbose = config.get("very_verbose", False)

        # Auto-detect project ID if not provided
        if not config.get("project_id"):
            try:
                _, project_id = google.auth.default()
                if project_id:
                    adapter_config["project_id"] = project_id
                    if very_verbose:
                        logging.info(f"Auto-detected BigQuery project ID: {project_id}")
            except google.auth.exceptions.DefaultCredentialsError:
                if very_verbose:
                    logging.warning("Could not auto-detect BigQuery project ID. Please provide --project-id.")

        # Override with explicit config values
        if config.get("project_id"):
            adapter_config["project_id"] = config["project_id"]

        # Generate dataset name
        dataset_name = generate_database_name(
            benchmark_name=config["benchmark"],
            scale_factor=config["scale_factor"],
            platform="bigquery",
            tuning_config=config.get("tuning_config"),
        )
        adapter_config["dataset_id"] = dataset_name

        # Pass through other relevant config
        for key in [
            "location",
            "credentials_path",
            "storage_bucket",
            "storage_prefix",
            "staging_root",
            "job_priority",
            "biglake_connection",
            "query_cache",
            "disable_result_cache",
            "maximum_bytes_billed",
            "tuning_config",
            "verbose_enabled",
            "very_verbose",
        ]:
            if key in config:
                adapter_config[key] = config[key]

        return cls(**adapter_config)

    @property
    def platform_name(self) -> str:
        return "BigQuery"

    def _detect_bigquery_client_version(self) -> str | None:
        """Return the google-cloud-bigquery client version, or None if unavailable."""
        try:
            import google.cloud.bigquery

            return getattr(google.cloud.bigquery, "__version__", None)
        except (ImportError, AttributeError):
            return None

    def _collect_bigquery_dataset_metadata(self, connection: Any) -> dict[str, Any]:
        """Fetch dataset metadata from the BigQuery client with explicit unavailable status on failure."""
        try:
            dataset_ref = f"{self.project_id}.{self.dataset_id}"
            dataset = connection.get_dataset(dataset_ref)
            self.logger.debug(f"Successfully captured BigQuery dataset metadata for {dataset_ref}")
            return {
                "dataset_metadata_collection_status": "available",
                "dataset_location": dataset.location,
                "dataset_default_table_expiration_ms": dataset.default_table_expiration_ms,
                "dataset_default_partition_expiration_ms": dataset.default_partition_expiration_ms,
                "dataset_created": dataset.created.isoformat() if dataset.created else None,
                "dataset_modified": dataset.modified.isoformat() if dataset.modified else None,
            }
        except Exception as e:
            self.logger.debug(f"Could not fetch BigQuery dataset metadata: {e}")
            return {
                "dataset_metadata_collection_status": "unavailable",
                "dataset_metadata_error_class": type(e).__name__,
                "dataset_metadata_error_message": str(e),
            }

    @staticmethod
    def _determine_bigquery_pricing(
        reservation_info: dict[str, Any] | None,
        commitment_info: dict[str, Any] | None,
    ) -> tuple[str, str]:
        """Derive (pricing_model, edition) from reservation + commitment info."""
        if not reservation_info:
            return "on-demand", "ON_DEMAND"

        edition = reservation_info.get("edition") or "STANDARD"
        if not commitment_info:
            return "flat-rate", edition

        commitment_plan_map = {
            "FLEX": "flex-slots",
            "MONTHLY": "monthly-commitment",
            "ANNUAL": "annual-commitment",
            "THREE_YEAR": "three-year-commitment",
        }
        pricing_model = commitment_plan_map.get(commitment_info.get("commitment_plan", ""), "flat-rate")
        return pricing_model, edition

    def _apply_bigquery_compute_configuration(
        self,
        platform_info: dict[str, Any],
        dataset_metadata: dict[str, Any] | None,
        reservation_info: dict[str, Any] | None,
        commitment_info: dict[str, Any] | None,
        assignment_info: dict[str, Any] | None,
    ) -> None:
        """Merge compute_configuration block onto platform_info in place."""
        compute: dict[str, Any] = dict(dataset_metadata) if dataset_metadata else {}
        pricing_model, edition = self._determine_bigquery_pricing(reservation_info, commitment_info)
        self.logger.debug(f"Detected BigQuery pricing model: {pricing_model}, edition: {edition}")

        compute["pricing_model"] = pricing_model
        compute["edition"] = edition
        compute["slot_capacity"] = reservation_info.get("slot_capacity") if reservation_info else None
        compute["autoscale_max_slots"] = reservation_info.get("autoscale_max_slots") if reservation_info else None

        if reservation_info:
            compute["reservation_details"] = {
                "name": reservation_info.get("reservation_name"),
                "slot_capacity": reservation_info.get("slot_capacity"),
                "ignore_idle_slots": reservation_info.get("ignore_idle_slots"),
                "autoscale_max_slots": reservation_info.get("autoscale_max_slots"),
                "creation_time": reservation_info.get("creation_time"),
                "update_time": reservation_info.get("update_time"),
            }
        if commitment_info:
            compute["capacity_commitment"] = commitment_info
        if assignment_info:
            compute["assignment"] = assignment_info

        platform_info["compute_configuration"] = compute

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get BigQuery platform information.

        Captures comprehensive BigQuery configuration including:
        - Dataset location and region
        - Slot reservation information (best effort)
        - Project and billing configuration
        - Dataset metadata

        BigQuery doesn't expose a version number as it's a fully managed service.
        Gracefully degrades if permissions are insufficient for metadata queries.
        """
        platform_info: dict[str, Any] = {
            "platform_type": "bigquery",
            "platform_name": "BigQuery",
            "connection_mode": "remote",
            "cloud_provider": "GCP",
            "configuration": {
                "project_id": self.project_id,
                "dataset_id": self.dataset_id,
                "location": self.location,
                "storage_bucket": self.storage_bucket,
                "storage_prefix": self.storage_prefix,
                "staging_root": self.staging_root,
                "biglake_connection": self.biglake_connection,
                "job_timeout": getattr(self, "job_timeout", None),
                "job_priority": self.job_priority,
                "query_cache_enabled": self.query_cache,
                "maximum_bytes_billed": self.maximum_bytes_billed,
            },
            "client_library_version": self._detect_bigquery_client_version(),
            "platform_version": None,
        }

        if connection:
            try:
                dataset_metadata = self._collect_bigquery_dataset_metadata(connection)

                reservation_info = None
                try:
                    # Query INFORMATION_SCHEMA for reservation info if available
                    query = f"""
                        SELECT
                            reservation_name,
                            slot_capacity,
                            ignore_idle_slots,
                            edition,
                            autoscale_max_slots,
                            creation_time,
                            update_time
                        FROM `region-{self.location}`.INFORMATION_SCHEMA.RESERVATIONS
                        WHERE project_id = @project_id
                        LIMIT 1
                    """

                    from google.cloud.bigquery import ScalarQueryParameter

                    job_config = bigquery.QueryJobConfig(
                        query_parameters=[ScalarQueryParameter("project_id", "STRING", self.project_id)]
                    )

                    query_job = connection.query(query, job_config=job_config)
                    results = list(query_job.result())

                    if results:
                        row = results[0]
                        reservation_info = {
                            "reservation_name": row.reservation_name if hasattr(row, "reservation_name") else None,
                            "slot_capacity": int(row.slot_capacity)
                            if hasattr(row, "slot_capacity") and row.slot_capacity
                            else None,
                            "ignore_idle_slots": row.ignore_idle_slots if hasattr(row, "ignore_idle_slots") else None,
                            "edition": row.edition if hasattr(row, "edition") else None,
                            "autoscale_max_slots": int(row.autoscale_max_slots)
                            if hasattr(row, "autoscale_max_slots") and row.autoscale_max_slots
                            else None,
                            "creation_time": row.creation_time.isoformat()
                            if hasattr(row, "creation_time") and row.creation_time
                            else None,
                            "update_time": row.update_time.isoformat()
                            if hasattr(row, "update_time") and row.update_time
                            else None,
                        }
                        self.logger.debug(
                            f"Successfully captured BigQuery reservation info: {reservation_info['reservation_name']}"
                        )

                except Exception as e:
                    self.logger.debug(
                        f"Could not fetch BigQuery reservation info (insufficient permissions or not configured): {e}"
                    )

                # Try to get capacity commitment information
                commitment_info = None
                try:
                    commitment_query = f"""
                        SELECT
                            commitment_id,
                            slot_count,
                            commitment_plan,
                            state,
                            renewal_plan,
                            commitment_start_time,
                            commitment_end_time
                        FROM `region-{self.location}`.INFORMATION_SCHEMA.CAPACITY_COMMITMENTS
                        WHERE project_id = @project_id
                            AND state = 'ACTIVE'
                        ORDER BY commitment_start_time DESC
                        LIMIT 1
                    """

                    job_config = bigquery.QueryJobConfig(
                        query_parameters=[ScalarQueryParameter("project_id", "STRING", self.project_id)]
                    )

                    commitment_job = connection.query(commitment_query, job_config=job_config)
                    commitment_results = list(commitment_job.result())

                    if commitment_results:
                        row = commitment_results[0]
                        commitment_info = {
                            "commitment_id": row.commitment_id if hasattr(row, "commitment_id") else None,
                            "slot_count": int(row.slot_count)
                            if hasattr(row, "slot_count") and row.slot_count
                            else None,
                            "commitment_plan": row.commitment_plan if hasattr(row, "commitment_plan") else None,
                            "state": row.state if hasattr(row, "state") else None,
                            "renewal_plan": row.renewal_plan if hasattr(row, "renewal_plan") else None,
                            "commitment_start_time": row.commitment_start_time.isoformat()
                            if hasattr(row, "commitment_start_time") and row.commitment_start_time
                            else None,
                            "commitment_end_time": row.commitment_end_time.isoformat()
                            if hasattr(row, "commitment_end_time") and row.commitment_end_time
                            else None,
                        }
                        self.logger.debug(
                            f"Successfully captured capacity commitment: {commitment_info['commitment_plan']}"
                        )

                except Exception as e:
                    error_msg = str(e).lower()
                    if "permission" in error_msg or "access denied" in error_msg:
                        self.logger.warning(
                            f"Unable to query capacity commitments (insufficient permissions): {e}. "
                            "Grant bigquery.capacityCommitments.list permission for complete platform metadata."
                        )
                    else:
                        self.logger.debug(f"Could not fetch capacity commitment info: {e}")

                # Try to get reservation assignment information
                assignment_info = None
                try:
                    assignment_query = f"""
                        SELECT
                            assignment_id,
                            assignee_id,
                            assignee_type,
                            job_type,
                            reservation_name
                        FROM `region-{self.location}`.INFORMATION_SCHEMA.ASSIGNMENTS_BY_PROJECT
                        WHERE assignee_id = @project_id
                        LIMIT 1
                    """

                    job_config = bigquery.QueryJobConfig(
                        query_parameters=[ScalarQueryParameter("project_id", "STRING", self.project_id)]
                    )

                    assignment_job = connection.query(assignment_query, job_config=job_config)
                    assignment_results = list(assignment_job.result())

                    if assignment_results:
                        row = assignment_results[0]
                        assignment_info = {
                            "assignment_id": row.assignment_id if hasattr(row, "assignment_id") else None,
                            "assignee_type": row.assignee_type if hasattr(row, "assignee_type") else None,
                            "job_type": row.job_type if hasattr(row, "job_type") else None,
                            "reservation_name": row.reservation_name if hasattr(row, "reservation_name") else None,
                        }
                        self.logger.debug(
                            f"Successfully captured reservation assignment: {assignment_info['assignment_id']}"
                        )

                except Exception as e:
                    error_msg = str(e).lower()
                    if "permission" in error_msg or "access denied" in error_msg:
                        self.logger.warning(
                            f"Unable to query reservation assignments (insufficient permissions): {e}. "
                            "Grant bigquery.reservationAssignments.list permission for complete platform metadata."
                        )
                    else:
                        self.logger.debug(f"Could not fetch reservation assignment info: {e}")

                self._apply_bigquery_compute_configuration(
                    platform_info,
                    dataset_metadata,
                    reservation_info,
                    commitment_info,
                    assignment_info,
                )

            except Exception as e:
                self.logger.debug(f"Error collecting BigQuery platform info: {e}")

        return platform_info

    def get_normalized_result_metadata(
        self,
        *,
        connection: Any | None = None,
        platform_info: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return BigQuery-specific normalized cloud/runtime metadata."""
        info = dict(platform_info) if isinstance(platform_info, Mapping) else self.get_platform_info(connection)
        metadata = build_default_normalized_result_metadata(self, connection=connection, platform_info=info)
        config = info.get("configuration") if isinstance(info.get("configuration"), Mapping) else {}
        compute = info.get("compute_configuration") if isinstance(info.get("compute_configuration"), Mapping) else {}

        metadata["platform_deployment"] = self._bigquery_deployment_metadata(config)
        metadata["platform_cloud"] = self._bigquery_cloud_metadata(config, compute)
        metadata["platform_compute"] = self._bigquery_compute_metadata(config, compute)
        metadata["platform_storage"] = self._bigquery_storage_metadata(config)
        return metadata

    @staticmethod
    def _bigquery_deployment_metadata(config: Mapping[str, Any]) -> dict[str, Any]:
        return _compact_metadata(
            {
                "deployment_type": "serverless",
                "connection_mode": "remote",
                "endpoint_class": "cloud_endpoint",
                "metadata_source": "requested",
                "collection_status": "partial",
                "dataset": config.get("dataset_id"),
            }
        )

    @staticmethod
    def _bigquery_cloud_metadata(config: Mapping[str, Any], compute: Mapping[str, Any]) -> dict[str, Any]:
        location = compute.get("dataset_location") or config.get("location")
        return _compact_metadata(
            {
                "provider": "gcp",
                "location": location,
                "project": config.get("project_id"),
                "source": "observed" if compute.get("dataset_location") else "requested",
                "collection_status": "partial" if config.get("project_id") or location else "unavailable",
            }
        )

    @staticmethod
    def _bigquery_compute_metadata(config: Mapping[str, Any], compute: Mapping[str, Any]) -> dict[str, Any]:
        reservation = (
            compute.get("reservation_details") if isinstance(compute.get("reservation_details"), Mapping) else {}
        )
        commitment = (
            compute.get("capacity_commitment") if isinstance(compute.get("capacity_commitment"), Mapping) else {}
        )
        assignment = compute.get("assignment") if isinstance(compute.get("assignment"), Mapping) else {}
        observed = bool(
            compute.get("dataset_location")
            or reservation
            or commitment
            or assignment
            or compute.get("dataset_metadata_collection_status") == "available"
        )
        dataset_metadata_unavailable = compute.get("dataset_metadata_collection_status") == "unavailable"
        collection_status = "available" if observed else "partial"
        if dataset_metadata_unavailable:
            collection_status = "partial"
        payload = {
            "serverless_slots": compute.get("slot_capacity"),
            "pricing_model": compute.get("pricing_model"),
            "edition": compute.get("edition"),
            "reservation": reservation.get("name"),
            "reservation_slot_capacity": reservation.get("slot_capacity"),
            "reservation_ignore_idle_slots": reservation.get("ignore_idle_slots"),
            "autoscale_max_slots": compute.get("autoscale_max_slots"),
            "capacity_commitment_id": commitment.get("commitment_id"),
            "capacity_commitment_plan": commitment.get("commitment_plan"),
            "capacity_commitment_slots": commitment.get("slot_count"),
            "reservation_assignment_id": assignment.get("assignment_id"),
            "reservation_assignment": assignment.get("reservation_name"),
            "reservation_assignment_job_type": assignment.get("job_type"),
            "job_priority": config.get("job_priority"),
            "cache_enabled": config.get("query_cache_enabled"),
            "maximum_bytes_billed": config.get("maximum_bytes_billed"),
            "dataset_metadata_collection_status": compute.get("dataset_metadata_collection_status"),
            "dataset_metadata_error_class": compute.get("dataset_metadata_error_class"),
            "dataset_metadata_error_message": compute.get("dataset_metadata_error_message"),
            "source": "observed" if observed else "requested",
            "collection_status": collection_status,
        }
        return _compact_metadata(payload)

    @staticmethod
    def _bigquery_storage_metadata(config: Mapping[str, Any]) -> dict[str, Any]:
        bucket = config.get("storage_bucket")
        staging_location = config.get("staging_root")
        biglake_connection = config.get("biglake_connection")
        has_storage_target = bool(bucket or staging_location or biglake_connection)
        prefix = config.get("storage_prefix") if bucket or staging_location else None
        if not staging_location and bucket:
            staging_location = f"gs://{bucket}/{prefix or ''}".rstrip("/")
        return _compact_metadata(
            {
                "staging_location": staging_location,
                "bucket": bucket,
                "prefix": prefix,
                "biglake_connection": biglake_connection,
                "source": "requested",
                "collection_status": "partial" if has_storage_target else "unavailable",
            }
        )

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for BigQuery."""
        return "bigquery"

    def _get_connection_params(self, **connection_config) -> dict[str, Any]:
        """Get standardized connection parameters."""
        return {
            "project_id": connection_config.get("project_id", self.project_id),
            "location": connection_config.get("location", self.location),
            "credentials_path": connection_config.get("credentials_path", self.credentials_path),
        }

    def _load_credentials(self, credentials_path: str | None) -> Any:
        """Load Google Cloud credentials from service account file.

        This method loads credentials directly from the file without setting
        environment variables, which is more secure as it avoids credential
        exposure via environment inspection.

        Args:
            credentials_path: Path to service account JSON file, or None for default

        Returns:
            Credentials object suitable for BigQuery/Storage clients
        """
        if credentials_path:
            return service_account.Credentials.from_service_account_file(credentials_path)
        # Fall back to default credentials (ADC)
        credentials, _ = google_auth.default()
        return credentials

    def _create_admin_client(self, **connection_config) -> Any:
        """Create BigQuery client for admin operations."""
        params = self._get_connection_params(**connection_config)
        credentials = self._load_credentials(params["credentials_path"])
        return bigquery.Client(
            project=params["project_id"],
            location=params["location"],
            credentials=credentials,
        )

    def check_server_database_exists(self, **connection_config) -> bool:
        """Check if dataset exists in BigQuery project."""
        try:
            client = self._create_admin_client(**connection_config)
            dataset_id = connection_config.get("dataset", self.dataset_id)

            # Check if dataset exists
            datasets = list(client.list_datasets())
            dataset_names = [d.dataset_id for d in datasets]

            return dataset_id in dataset_names

        except Exception:
            # If we can't connect or check, assume dataset doesn't exist
            return False

    def drop_database(self, **connection_config) -> None:
        """Drop dataset in BigQuery project."""
        try:
            client = self._create_admin_client(**connection_config)
            dataset_id = connection_config.get("dataset", self.dataset_id)

            # Create dataset reference
            dataset_ref = client.dataset(dataset_id)

            # Drop dataset and all its tables
            client.delete_dataset(dataset_ref, delete_contents=True, not_found_ok=True)

        except Exception as e:
            raise RuntimeError(f"Failed to drop BigQuery dataset {dataset_id}: {e}") from e

    def _validate_database_compatibility(self, **connection_config):
        """Validate database compatibility with BigQuery-specific empty table detection.

        Extends base validation to add fast empty table detection using BigQuery's
        table.num_rows metadata property. This catches cases where tables exist but
        have no data (usually from failed previous loads).

        Args:
            **connection_config: Connection configuration

        Returns:
            DatabaseValidationResult with compatibility information
        """
        # First run the standard validation
        from benchbox.platforms.base.validation import DatabaseValidator

        validator = DatabaseValidator(adapter=self, connection_config=connection_config)
        result = validator.validate()

        # If validation already failed, no need for additional checks
        if not result.is_valid:
            return result

        # BigQuery-specific check: detect empty tables using fast num_rows API
        # This is more comprehensive than the standard row count validation which
        # only samples 2 tables for performance. BigQuery's num_rows is metadata
        # and doesn't require running queries, so we can check all tables quickly.
        try:
            client = self._create_admin_client(**connection_config)
            dataset_ref = client.dataset(self.dataset_id, project=self.project_id)

            try:
                tables = list(client.list_tables(dataset_ref))
            except Exception as e:
                # If we can't list tables, validation already failed in base validator
                self.log_very_verbose(f"Could not list tables for empty table check: {e}")
                return result

            if not tables:
                # No tables means database is empty - base validator should have caught this
                return result

            # Count empty tables using fast metadata API
            empty_count = 0
            empty_tables = []

            for table_info in tables:
                try:
                    table = client.get_table(table_info.reference)
                    if table.num_rows == 0:
                        empty_count += 1
                        empty_tables.append(table.table_id)
                except Exception as e:
                    self.log_very_verbose(f"Failed to check table {table_info.table_id}: {e}")

            # If more than half the tables are empty, mark database as invalid
            # This indicates a failed previous load where schema was created but data loading failed
            if empty_count > len(tables) / 2:
                self.log_verbose(
                    f"Found {empty_count}/{len(tables)} empty tables - database appears to have failed data load"
                )
                result.issues.append(
                    f"Empty tables detected: {empty_count}/{len(tables)} tables have no rows "
                    f"(indicates failed previous load)"
                )
                result.is_valid = False
                result.can_reuse = False

        except Exception as e:
            # Don't fail validation if empty table check fails - just log it
            self.log_very_verbose(f"Empty table check failed: {e}")

        return result

    def _cleanup_empty_tables_if_needed(self, client) -> None:
        """Fallback cleanup for empty tables (defense-in-depth).

        This is a fallback mechanism that runs after connection is created.
        The primary empty table detection now happens during _validate_database_compatibility(),
        which prevents the database from being marked as reusable in the first place.

        This method is kept as defense-in-depth in case validation is bypassed or
        tables become empty between validation and connection.

        If more than half the tables are empty, it drops all empty tables and forces
        schema/data recreation by setting database_was_reused = False.

        Args:
            client: BigQuery client connection
        """
        try:
            self.logger.debug(f"Starting empty table cleanup check for dataset {self.dataset_id}")
            dataset_ref = client.dataset(self.dataset_id, project=self.project_id)
            self.logger.debug(f"Listing tables in dataset {self.dataset_id}")
            tables = list(client.list_tables(dataset_ref))
            self.logger.debug(f"Found {len(tables)} tables in dataset")

            if not tables:
                # No tables exist - nothing to clean up
                self.logger.debug("No tables found - nothing to clean up")
                return

            empty_count = 0
            empty_tables = []

            # Check each table for emptiness
            self.logger.debug(f"Checking {len(tables)} tables for empty rows")
            for table_info in tables:
                try:
                    table = client.get_table(table_info.reference)
                    if table.num_rows == 0:
                        empty_count += 1
                        empty_tables.append(table.table_id)
                        self.logger.debug(f"Table {table.table_id} is empty (0 rows)")
                except Exception as e:
                    self.logger.warning(f"Failed to check table {table_info.table_id}: {e}")

            self.logger.debug(f"Empty table count: {empty_count}/{len(tables)}")

            # If more than half the tables are empty, likely a failed load - drop them all
            if empty_count > len(tables) / 2:
                self.logger.warning(
                    f"Found {empty_count}/{len(tables)} empty tables - cleaning up failed previous load"
                )

                # Drop all empty tables
                for table_id in empty_tables:
                    try:
                        table_ref = dataset_ref.table(table_id)
                        client.delete_table(table_ref, not_found_ok=True)
                        self.logger.info(f"Dropped empty table: {table_id}")
                    except Exception as e:
                        self.logger.warning(f"Failed to drop empty table {table_id}: {e}")

                # Mark database as NOT reused so schema and data will be loaded
                self.database_was_reused = False
                self.logger.info(f"Dropped {len(empty_tables)} empty tables - forcing schema and data recreation")
            elif empty_count > 0:
                # Some tables are empty but not majority - just log it
                self.logger.info(
                    f"Found {empty_count} empty tables (out of {len(tables)} total) - not enough to trigger cleanup"
                )
            else:
                self.logger.debug("No empty tables found")

        except Exception as e:
            # Don't fail if cleanup check fails - just log and continue
            import traceback

            self.logger.error(f"Empty table cleanup check failed: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")

    def create_connection(self, **connection_config) -> Any:
        """Create optimized BigQuery client connection."""
        self.log_operation_start("BigQuery connection")

        # Handle existing database using base class method
        self.handle_existing_database(**connection_config)

        # Get connection parameters
        params = self._get_connection_params(**connection_config)
        self.log_very_verbose(
            f"BigQuery connection params: project={params.get('project_id')}, location={params.get('location')}"
        )

        try:
            # Load credentials securely (without environment variable exposure)
            credentials = self._load_credentials(params["credentials_path"])

            # Create BigQuery client
            client = bigquery.Client(
                project=params["project_id"],
                location=params["location"],
                credentials=credentials,
            )

            # Test connection
            query = "SELECT 1 as test"
            query_job = client.query(query)
            list(query_job.result())

            self.logger.info(f"Connected to BigQuery project: {params['project_id']}")

            # If database was reused, check for and clean up empty tables from failed previous loads
            self.logger.debug(
                f"Checking if cleanup needed: database_was_reused={getattr(self, 'database_was_reused', False)}"
            )
            if getattr(self, "database_was_reused", False):
                self.logger.info("Database was reused - checking for empty tables from failed previous loads")
                self._cleanup_empty_tables_if_needed(client)

            # Storage client will be created lazily when needed (see load_data)

            self.log_operation_complete("BigQuery connection", details=f"Connected to project {params['project_id']}")

            return client

        except Exception as e:
            self.logger.error(f"Failed to connect to BigQuery: {e}")
            raise

    def _get_existing_tables(self, connection: Any) -> list[str]:
        """Get list of existing tables in BigQuery dataset.

        Returns table names in lowercase for case-insensitive comparison.
        BigQuery stores table names in the case they were created (usually uppercase
        for TPC benchmarks), but we normalize to lowercase for validation.
        """
        try:
            dataset_ref = connection.dataset(self.dataset_id, project=self.project_id)
            tables = list(connection.list_tables(dataset_ref))
            # Normalize to lowercase since BigQuery is case-insensitive
            return [table.table_id.lower() for table in tables]
        except Exception as e:
            self.log_very_verbose(f"Failed to list tables: {e}")
            return []

    def _validate_data_integrity(
        self, benchmark, connection: Any, table_stats: dict[str, int]
    ) -> tuple[str, dict[str, Any]]:
        """Validate data integrity using BigQuery Client API.

        BigQuery Client doesn't support cursor pattern (connection.cursor()) like
        traditional databases. Instead, it uses connection.query() for SQL execution.

        This override prevents "'Client' object has no attribute 'cursor'" errors
        during database compatibility validation.

        Args:
            benchmark: Benchmark instance
            connection: BigQuery Client
            table_stats: Dictionary of table names to row counts

        Returns:
            Tuple of (status, validation_details)
        """
        validation_details = {}

        try:
            accessible_tables = []
            inaccessible_tables = []

            for table_name in table_stats:
                try:
                    # BigQuery stores tables in uppercase for TPC benchmarks
                    table_upper = table_name.upper()

                    # Use BigQuery's query API instead of cursor pattern
                    query = f"SELECT 1 FROM `{self.project_id}.{self.dataset_id}.{table_upper}` LIMIT 1"
                    query_job = connection.query(query)
                    list(query_job.result())  # Execute query to verify table is accessible

                    accessible_tables.append(table_name)
                except Exception as e:
                    self.log_very_verbose(f"Table {table_name} inaccessible: {e}")
                    inaccessible_tables.append(table_name)

            if inaccessible_tables:
                validation_details["inaccessible_tables"] = inaccessible_tables
                validation_details["constraints_enabled"] = False
                return "FAILED", validation_details
            else:
                validation_details["accessible_tables"] = accessible_tables
                validation_details["constraints_enabled"] = True
                return "PASSED", validation_details

        except Exception as e:
            validation_details["constraints_enabled"] = False
            validation_details["integrity_error"] = str(e)
            return "FAILED", validation_details

    def get_table_row_count(self, connection: Any, table: str) -> int:
        """Get row count using BigQuery Client API.

        Overrides base implementation that uses cursor pattern.
        BigQuery Client doesn't have .cursor() method, so we use .query() instead.

        Args:
            connection: BigQuery Client
            table: Table name

        Returns:
            Row count as integer, or 0 if unable to determine
        """
        try:
            # BigQuery stores tables in uppercase for TPC benchmarks
            table_upper = table.upper()

            # Use BigQuery's query API instead of cursor pattern
            query = f"SELECT COUNT(*) FROM `{self.project_id}.{self.dataset_id}.{table_upper}`"
            query_job = connection.query(query)
            result = list(query_job.result())
            return result[0][0] if result else 0
        except Exception as e:
            self.log_very_verbose(f"Could not get row count for {table}: {e}")
            return 0

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema using BigQuery dataset and tables."""
        start_time = mono_time()

        try:
            # Create dataset if it doesn't exist
            dataset_ref = connection.dataset(self.dataset_id)

            try:
                connection.get_dataset(dataset_ref)
                self.logger.info(f"Dataset {self.dataset_id} already exists")
            except NotFound:
                dataset = bigquery.Dataset(dataset_ref)
                dataset.location = self.location
                dataset.description = (
                    f"BenchBox benchmark data for {benchmark._name if hasattr(benchmark, '_name') else 'benchmark'}"
                )

                dataset = connection.create_dataset(dataset)
                self.logger.info(f"Created dataset {self.dataset_id}")

            # Use common schema creation helper
            schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")

            # Split schema into individual statements and execute
            statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]

            for statement in statements:
                # Convert to BigQuery table definition
                bq_statement = self._convert_to_bigquery_table(statement)

                # Execute via query job
                query_job = connection.query(bq_statement)
                query_job.result()  # Wait for completion

                self.logger.debug(f"Executed schema statement: {bq_statement[:100]}...")

            self.logger.info("Schema created")

        except Exception as e:
            self.logger.error(f"Schema creation failed: {e}")
            raise

        return elapsed_seconds(start_time)

    def load_data(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load data using BigQuery efficient loading via Cloud Storage."""
        logger = logging.getLogger(__name__)
        logger.debug(f"Starting data loading for benchmark: {benchmark.__class__.__name__}")
        logger.debug(f"Data directory: {data_dir}")

        # Check if using cloud storage
        if is_cloud_path(str(data_dir)):
            path_info = get_cloud_path_info(str(data_dir))
            logger.info(f"Loading data from cloud storage: {path_info['provider']} bucket '{path_info['bucket']}'")
            emit(f"  Loading data from {path_info['provider']} cloud storage")

        start_time = mono_time()
        table_stats = {}
        total_time = 0.0

        try:
            data_source = self._resolve_data_files(benchmark, data_dir)
            if not isinstance(data_source, DataSource):
                data_source = DataSource(source_type="legacy_test_mapping", tables=data_source)
            self._validate_compression_support(data_source.tables, benchmark)

            if self.storage_bucket:
                bucket = self._create_storage_bucket()
                table_stats = self._load_tables_via_cloud_storage(connection, data_source, bucket, benchmark)
            else:
                self.logger.warning("No Cloud Storage bucket configured, using direct loading")
                table_stats = self._load_tables_direct(connection, data_source, benchmark)

            total_time = elapsed_seconds(start_time)
            total_rows = sum(table_stats.values())
            self.logger.info(f"✅ Loaded {total_rows:,} total rows in {total_time:.2f}s")

        except Exception as e:
            self.logger.error(f"Data loading failed: {e}")
            raise

        # BigQuery doesn't provide detailed per-table timings yet
        return table_stats, total_time, None

    def validate_external_table_requirements(self) -> None:
        """Validate required GCS configuration for external table mode."""
        if not self.storage_bucket:
            raise ValueError(
                "BigQuery external mode requires a GCS bucket (set --platform-option storage_bucket=<bucket> "
                "or provide --platform-option staging_root=gs://bucket/path)."
            )

    def create_external_tables(
        self, benchmark: Any, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Upload external-table sources to GCS and register BigQuery external tables."""
        self.validate_external_table_requirements()

        start_time = mono_time()
        table_stats: dict[str, int] = {}
        data_source = self._resolve_data_files(benchmark, data_dir)
        if not isinstance(data_source, DataSource):
            data_source = DataSource(source_type="legacy_test_mapping", tables=data_source)
        bucket = self._create_storage_bucket()

        for table_name, file_paths in data_source.tables.items():
            table_name_upper = table_name.upper()
            source_format, uris = self._prepare_external_table_uris(bucket, table_name, file_paths)
            if not uris:
                raise ValueError(
                    f"BigQuery external mode requires Parquet files or Delta directories for table "
                    f"'{table_name_upper}'. No supported sources were found."
                )

            uris_sql = ", ".join(f"'{uri}'" for uri in uris)
            connection_clause = (
                f"\n                WITH CONNECTION `{self.biglake_connection}`"
                if source_format == "DELTA_LAKE"
                else ""
            )
            ddl = f"""
                CREATE OR REPLACE EXTERNAL TABLE `{self.project_id}.{self.dataset_id}.{table_name_upper}`{connection_clause}
                OPTIONS (
                  format = '{source_format}',
                  uris = [{uris_sql}]
                )
            """
            query_job = connection.query(ddl)
            query_job.result()

            table_stats[table_name_upper] = self._get_table_row_count(connection, table_name_upper)

        total_time = elapsed_seconds(start_time)
        return table_stats, total_time, None

    def _resolve_data_files(self, benchmark: Any, data_dir: Path) -> Any:
        """Resolve benchmark data files from benchmark tables or manifest."""
        return resolve_adapter_data_source(self, benchmark, data_dir)

    @staticmethod
    def _ensure_file_list(file_paths: Any) -> list[Any]:
        """Normalize table file paths to a list."""
        return file_paths if isinstance(file_paths, list) else [file_paths]

    def _filter_valid_files(self, file_paths: Any, *, allow_cloud: bool) -> list[Any]:
        """Filter valid file inputs for load operations."""
        valid_files: list[Any] = []
        for file_path in self._ensure_file_list(file_paths):
            if allow_cloud and is_cloud_path(str(file_path)):
                valid_files.append(file_path)
                continue
            path = Path(file_path)
            if path.exists() and (path.is_dir() or path.stat().st_size > 0):
                valid_files.append(path)
        return valid_files

    def _validate_compression_support(self, data_files: dict[str, Any], benchmark: Any) -> None:
        """Reject unsupported compressed files for BigQuery CSV loads."""
        for file_paths in data_files.values():
            for file_path in self._ensure_file_list(file_paths):
                if detect_compression(file_path) != "zstd":
                    continue

                benchmark_name = getattr(benchmark, "name", "unknown")
                scale_factor = getattr(benchmark, "scale_factor", "unknown")
                raise ValueError(
                    f"\n❌ Incompatible data compression detected\n\n"
                    f"BigQuery does not support Zstd (.zst) compression for CSV file loading.\n"
                    f"Found Zstd file: {Path(file_path).name}\n\n"
                    f"To fix this, regenerate the data with gzip compression:\n\n"
                    f"  # Remove existing incompatible data\n"
                    f"  rm -rf {benchmark.data_dir}\n\n"
                    f"  # Regenerate with gzip compression\n"
                    f"  benchbox run --platform bigquery --benchmark {benchmark_name} "
                    f"--scale {scale_factor} --compression-type gzip\n\n"
                    f"Or use uncompressed data (larger files, slower uploads):\n\n"
                    f"  benchbox run --platform bigquery --benchmark {benchmark_name} "
                    f"--scale {scale_factor} --no-compression\n"
                )

    def _create_storage_bucket(self) -> Any:
        """Create a Google Cloud Storage bucket client."""
        params = self._get_connection_params()
        credentials = self._load_credentials(params["credentials_path"])
        storage_client = storage.Client(project=self.project_id, credentials=credentials)
        return storage_client.bucket(self.storage_bucket)

    def _get_table_row_count(self, connection: Any, table_name_upper: str) -> int:
        """Return current row count for a BigQuery table."""
        query = f"SELECT COUNT(*) FROM `{self.project_id}.{self.dataset_id}.{table_name_upper}`"
        query_job = connection.query(query)
        result = list(query_job.result())
        return result[0][0] if result else 0

    def _load_table_via_cloud_storage(
        self,
        connection: Any,
        bucket: Any,
        table_name: str,
        valid_files: list[Any],
        data_source: Any | None = None,
        benchmark: Any | None = None,
    ) -> int:
        """Load one table through GCS staging."""
        table_name_upper = table_name.upper()
        table_ref = connection.dataset(self.dataset_id).table(table_name_upper)

        for file_idx, file_path in enumerate(valid_files):
            chunk_info = f" (chunk {file_idx + 1}/{len(valid_files)})" if len(valid_files) > 1 else ""

            blob_name = f"{self.storage_prefix}/{table_name}_{file_idx}{''.join(file_path.suffixes)}"
            self.log_very_verbose(f"Uploading to Cloud Storage{chunk_info}: {blob_name}")
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(str(file_path))

            write_disposition = (
                bigquery.WriteDisposition.WRITE_TRUNCATE if file_idx == 0 else bigquery.WriteDisposition.WRITE_APPEND
            )
            job_config = self._build_load_job_config(
                file_path,
                write_disposition=write_disposition,
                allow_quoted_newlines=True,
                table_name=table_name,
                data_source=data_source,
                benchmark=benchmark,
            )
            uri = f"gs://{self.storage_bucket}/{blob_name}"
            load_job = connection.load_table_from_uri(uri, table_ref, job_config=job_config)
            load_job.result()

        return self._get_table_row_count(connection, table_name_upper)

    def _load_table_direct(
        self,
        connection: Any,
        table_name: str,
        valid_files: list[Path],
        data_source: Any | None = None,
        benchmark: Any | None = None,
    ) -> int:
        """Load one table directly from local files."""
        table_name_upper = table_name.upper()
        table_ref = connection.dataset(self.dataset_id).table(table_name_upper)

        for file_idx, file_path in enumerate(valid_files):
            chunk_info = f" (chunk {file_idx + 1}/{len(valid_files)})" if len(valid_files) > 1 else ""
            self.log_very_verbose(f"Loading {table_name}{chunk_info} from {file_path.name}")
            write_disposition = (
                bigquery.WriteDisposition.WRITE_TRUNCATE if file_idx == 0 else bigquery.WriteDisposition.WRITE_APPEND
            )
            job_config = self._build_load_job_config(
                file_path,
                write_disposition=write_disposition,
                table_name=table_name,
                data_source=data_source,
                benchmark=benchmark,
            )
            with open(file_path, "rb") as source_file:
                load_job = connection.load_table_from_file(source_file, table_ref, job_config=job_config)
            load_job.result()

        return self._get_table_row_count(connection, table_name_upper)

    def _build_load_job_config(
        self,
        file_path: Path | str,
        *,
        write_disposition: bigquery.WriteDisposition,
        allow_quoted_newlines: bool = False,
        table_name: str | None = None,
        data_source: Any | None = None,
        benchmark: Any | None = None,
    ) -> bigquery.LoadJobConfig:
        """Build a native BigQuery load job config for parquet or delimited text.

        ``allow_quoted_newlines`` applies only to CSV configs; it is ignored for parquet.
        """
        data_format = detect_data_format(file_path)
        if data_format == "parquet":
            return bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.PARQUET,
                autodetect=False,
                write_disposition=write_disposition,
            )

        if data_format not in self._DELIMITED_FORMATS:
            self.logger.warning(
                "Unrecognized data format %r for %s - falling back to CSV load job config",
                data_format,
                Path(file_path).name,
            )

        dialect_source = data_source or DataSource(source_type="bigquery_load_job", tables={})
        dialect = resolve_csv_dialect(
            dialect_source,
            table_name or Path(file_path).stem,
            Path(file_path),
            benchmark if benchmark is not None else NO_BENCHMARK,
        )
        config_kwargs: dict[str, Any] = {
            "source_format": bigquery.SourceFormat.CSV,
            "field_delimiter": dialect.delimiter,
            "skip_leading_rows": 1 if dialect.has_header else 0,
            "autodetect": False,
            "write_disposition": write_disposition,
        }
        if dialect.null_marker is not None:
            config_kwargs["null_marker"] = dialect.null_marker
        if allow_quoted_newlines:
            config_kwargs["allow_quoted_newlines"] = True
        return bigquery.LoadJobConfig(**config_kwargs)

    def _load_tables_via_cloud_storage(
        self,
        connection: Any,
        data_source: Any,
        bucket: Any,
        benchmark: Any | None = None,
    ) -> dict[str, int]:
        """Load all tables using GCS staging."""
        logger = logging.getLogger(__name__)
        table_stats: dict[str, int] = {}

        if not isinstance(data_source, DataSource):
            data_source = DataSource(source_type="legacy_test_mapping", tables=data_source)

        for table_name, file_paths in data_source.tables.items():
            valid_files = self._filter_valid_files(file_paths, allow_cloud=True)
            if not valid_files:
                self.logger.warning(f"Skipping {table_name} - no valid data files")
                table_stats[table_name] = 0
                continue

            logger.debug(f"Loading {table_name} from {len(valid_files)} file(s)")
            try:
                self.log_verbose(f"Loading data for table: {table_name}")
                load_start = mono_time()
                row_count = self._load_table_via_cloud_storage(
                    connection, bucket, table_name, valid_files, data_source, benchmark
                )
                table_name_upper = table_name.upper()
                table_stats[table_name_upper] = row_count
                chunk_info = f" from {len(valid_files)} file(s)" if len(valid_files) > 1 else ""
                self.logger.info(
                    f"✅ Loaded {row_count:,} rows into {table_name_upper}{chunk_info} in "
                    f"{elapsed_seconds(load_start):.2f}s"
                )
            except Exception as e:
                self.logger.error(f"Failed to load {table_name}: {str(e)[:100]}...")
                table_stats[table_name.upper()] = 0

        return table_stats

    def _load_tables_direct(self, connection: Any, data_source: Any, benchmark: Any | None = None) -> dict[str, int]:
        """Load all tables directly from local files."""
        table_stats: dict[str, int] = {}

        if not isinstance(data_source, DataSource):
            data_source = DataSource(source_type="legacy_test_mapping", tables=data_source)

        for table_name, file_paths in data_source.tables.items():
            valid_files_any = self._filter_valid_files(file_paths, allow_cloud=False)
            valid_files = [file_path for file_path in valid_files_any if isinstance(file_path, Path)]
            if not valid_files:
                self.logger.warning(f"Skipping {table_name} - no valid data files")
                table_stats[table_name.upper()] = 0
                continue

            try:
                self.log_verbose(f"Direct loading data for table: {table_name}")
                load_start = mono_time()
                row_count = self._load_table_direct(connection, table_name, valid_files, data_source, benchmark)
                table_name_upper = table_name.upper()
                table_stats[table_name_upper] = row_count
                chunk_info = f" from {len(valid_files)} file(s)" if len(valid_files) > 1 else ""
                self.logger.info(
                    f"✅ Loaded {row_count:,} rows into {table_name_upper}{chunk_info} in "
                    f"{elapsed_seconds(load_start):.2f}s"
                )
            except Exception as e:
                self.logger.error(f"Failed to load {table_name}: {str(e)[:100]}...")
                table_stats[table_name.upper()] = 0

        return table_stats

    def _prepare_external_table_uris(self, bucket: Any, table_name: str, file_paths: Any) -> tuple[str, list[str]]:
        """Prepare BigQuery external-table sources for parquet files or delta directories."""
        valid_files = self._filter_valid_files(file_paths, allow_cloud=True)
        delta_uris = self._prepare_external_delta_uris(bucket, table_name, valid_files)
        if delta_uris:
            if not self.biglake_connection:
                raise ValueError(
                    "BigQuery Delta external mode requires --platform-option biglake_connection=<project.region.name>."
                )
            return "DELTA_LAKE", delta_uris
        return "PARQUET", self._prepare_external_parquet_uris(bucket, table_name, valid_files)

    def _prepare_external_parquet_uris(self, bucket: Any, table_name: str, file_paths: Any) -> list[str]:
        """Prepare external-table GCS URIs from local or already-cloud Parquet file paths."""
        uris: list[str] = []
        valid_files = self._filter_valid_files(file_paths, allow_cloud=True)

        for file_path in valid_files:
            file_path_str = str(file_path)
            if is_cloud_path(file_path_str):
                if file_path_str.lower().endswith(".parquet"):
                    uris.append(file_path_str)
                continue

            path = Path(file_path)
            if path.suffix.lower() != ".parquet":
                continue

            blob_name = f"{self.storage_prefix}/{table_name.lower()}/{path.name}"
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(str(path))
            uris.append(f"gs://{self.storage_bucket}/{blob_name}")

        return uris

    def _prepare_external_delta_uris(self, bucket: Any, table_name: str, file_paths: list[Path]) -> list[str]:
        """Prepare BigQuery Delta table root URIs from local or cloud directory inputs."""
        uris: list[str] = []

        for file_path in file_paths:
            file_path_str = str(file_path)
            if is_cloud_path(file_path_str):
                if "/_delta_log" in file_path_str:
                    uris.append(file_path_str.split("/_delta_log", 1)[0] + "/")
                continue

            path = Path(file_path)
            if not path.is_dir() or not (path / "_delta_log").is_dir():
                continue

            table_prefix = f"{self.storage_prefix}/{table_name.lower()}/"
            for source_file in path.rglob("*"):
                if not source_file.is_file():
                    continue
                relative = source_file.relative_to(path)
                blob = bucket.blob(f"{table_prefix}{relative.as_posix()}")
                blob.upload_from_filename(str(source_file))
            uris.append(f"gs://{self.storage_bucket}/{table_prefix}")

        return uris

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply BigQuery-specific optimizations based on benchmark type."""

        # Set default query job configuration
        job_config = bigquery.QueryJobConfig(
            priority=getattr(
                bigquery.QueryPriority,
                self.job_priority,
                bigquery.QueryPriority.INTERACTIVE,
            ),
            use_query_cache=self.query_cache,
            dry_run=self.dry_run,
        )

        if self.maximum_bytes_billed:
            job_config.maximum_bytes_billed = self.maximum_bytes_billed

        # Set default dataset to avoid requiring fully-qualified table names
        if self.project_id and self.dataset_id:
            job_config.default_dataset = f"{self.project_id}.{self.dataset_id}"

        if benchmark_type.lower() in ["olap", "analytics", "tpch", "tpcds"]:
            # OLAP optimizations
            job_config.use_legacy_sql = False  # Use Standard SQL
            job_config.flatten_results = False  # Keep nested/repeated fields

        # Store job config for use in execute_query
        connection._default_job_config = job_config

    def execute_query(
        self,
        connection: Any,
        query: str,
        query_id: str,
        benchmark_type: str | None = None,
        scale_factor: float | None = None,
        validate_row_count: bool = True,
        stream_id: int | None = None,
    ) -> dict[str, Any]:
        """Execute query with detailed timing and cost tracking."""
        start_time = mono_time()

        try:
            # Replace table references with fully qualified names
            # Note: Query dialect translation is now handled automatically by the base adapter
            # Skip qualification if query has backtick-quoted identifiers (from sqlglot)
            # because default_dataset handles unqualified names and regex breaks backticks
            if "`" in query:
                # Query processed by sqlglot with identify=True
                # Normalize lowercase table names to UPPERCASE to match TPC-DS schema
                # (BigQuery backtick-quoted identifiers are case-sensitive)
                translated_query = self._normalize_table_names_case(query)
            else:
                # Non-translated queries (e.g., raw TPC-H) need explicit qualification
                translated_query = self._qualify_table_names(query)

            # Use default job config if available
            job_config = getattr(connection, "_default_job_config", bigquery.QueryJobConfig())

            # Execute the query
            query_job = connection.query(translated_query, job_config=job_config)
            result = list(query_job.result())

            execution_time = elapsed_seconds(start_time)
            actual_row_count = len(result) if result else 0

            # Get job statistics
            job_stats = {
                "bytes_processed": query_job.total_bytes_processed,
                "bytes_billed": query_job.total_bytes_billed,
                "slot_ms": query_job.slot_millis,
                "creation_time": query_job.created.isoformat() if query_job.created else None,
                "start_time": query_job.started.isoformat() if query_job.started else None,
                "end_time": query_job.ended.isoformat() if query_job.ended else None,
            }

            # Validate row count if enabled and benchmark type is provided
            validation_result = None
            if validate_row_count and benchmark_type:
                from benchbox.core.validation.query_validation import QueryValidator

                validator = QueryValidator()
                validation_result = validator.validate_query_result(
                    benchmark_type=benchmark_type,
                    query_id=query_id,
                    actual_row_count=actual_row_count,
                    scale_factor=scale_factor,
                    stream_id=stream_id,
                )

                # Log validation result
                if validation_result.warning_message:
                    self.log_verbose(f"Row count validation: {validation_result.warning_message}")
                elif not validation_result.is_valid:
                    self.log_verbose(f"Row count validation FAILED: {validation_result.error_message}")
                else:
                    self.log_very_verbose(
                        f"Row count validation PASSED: {actual_row_count} rows "
                        f"(expected: {validation_result.expected_row_count})"
                    )

            # Use base helper to build result with consistent validation field mapping
            result_dict = self._build_query_result_with_validation(
                query_id=query_id,
                execution_time=execution_time,
                actual_row_count=actual_row_count,
                first_row=result[0] if result else None,
                validation_result=validation_result,
            )

            # Include BigQuery-specific fields
            result_dict["translated_query"] = translated_query if translated_query != query else None
            result_dict["job_statistics"] = job_stats
            result_dict["job_id"] = query_job.job_id
            # Map job_statistics to resource_usage for cost calculation
            result_dict["resource_usage"] = job_stats

            return result_dict

        except Exception as e:
            execution_time = elapsed_seconds(start_time)

            return {
                "query_id": query_id,
                "status": "FAILED",
                "execution_time_seconds": execution_time,
                "rows_returned": 0,
                "error": str(e),
                "error_type": type(e).__name__,
            }

    def _convert_to_bigquery_table(self, statement: str) -> str:
        """Convert CREATE TABLE statement to BigQuery format.

        Makes tables idempotent by using CREATE OR REPLACE TABLE.
        """
        if not statement.upper().startswith("CREATE TABLE"):
            return statement

        # Ensure idempotency with OR REPLACE (defense-in-depth)
        if "CREATE TABLE" in statement and "OR REPLACE" not in statement.upper():
            statement = statement.replace("CREATE TABLE", "CREATE OR REPLACE TABLE", 1)

        # Include dataset qualification
        if f"{self.dataset_id}." not in statement:
            statement = statement.replace(
                "CREATE OR REPLACE TABLE ", f"CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset_id}."
            )
            statement = statement.replace(" (", "` (")

        # Include partitioning and clustering if configured
        if "PARTITION BY" not in statement.upper() and self.partitioning_field:
            statement += f" PARTITION BY DATE({self.partitioning_field})"

        if "CLUSTER BY" not in statement.upper() and self.clustering_fields:
            clustering = ", ".join(self.clustering_fields)
            statement += f" CLUSTER BY {clustering}"

        return statement

    def _qualify_table_names(self, query: str) -> str:
        """Add full qualification to table names in query.

        Note: Only used for non-translated queries (e.g., raw TPC-H queries without sqlglot).
        Queries processed by sqlglot with identify=True should skip this method to avoid
        conflicts with backtick-quoted identifiers. When default_dataset is configured,
        BigQuery automatically resolves unqualified table names.
        """
        # Simple table name qualification - could be with proper SQL parsing
        table_names = [
            "REGION",
            "NATION",
            "CUSTOMER",
            "SUPPLIER",
            "PART",
            "PARTSUPP",
            "ORDERS",
            "LINEITEM",
        ]

        for table_name in table_names:
            # Replace unqualified table names
            qualified_name = f"`{self.project_id}.{self.dataset_id}.{table_name}`"

            # Simple replacement - in production would use proper SQL parser
            import re

            pattern = rf"\b{table_name}\b"
            query = re.sub(pattern, qualified_name, query, flags=re.IGNORECASE)

        return query

    def _normalize_table_names_case(self, query: str) -> str:
        """Normalize backtick-quoted table names to UPPERCASE for case-sensitive matching.

        BigQuery stores TPC-DS tables in UPPERCASE (per schema), but sqlglot generates
        lowercase table names with backticks. Since backtick-quoted identifiers are
        case-sensitive in BigQuery, we need to normalize to UPPERCASE to match the schema.

        Only processes backtick-quoted identifiers to avoid affecting string literals.

        Args:
            query: SQL query with backtick-quoted identifiers

        Returns:
            Query with lowercase table names normalized to UPPERCASE
        """
        import re

        # Pattern: backtick, lowercase word characters (table names), backtick
        # This safely matches table identifiers without affecting string literals
        pattern = r"`([a-z_][a-z0-9_]*)`"

        def uppercase_table(match: re.Match[str]) -> str:
            return f"`{match.group(1).upper()}`"

        return re.sub(pattern, uppercase_table, query)

    def _get_platform_metadata(self, connection: Any) -> dict[str, Any]:
        """Get BigQuery-specific metadata and system information."""
        metadata = {
            "platform": self.platform_name,
            "project_id": self.project_id,
            "dataset_id": self.dataset_id,
            "location": self.location,
            "result_cache_enabled": self.query_cache,
        }

        try:
            # Get dataset information
            dataset_ref = connection.dataset(self.dataset_id)
            dataset = connection.get_dataset(dataset_ref)

            metadata["dataset_info"] = {
                "created": dataset.created.isoformat() if dataset.created else None,
                "modified": dataset.modified.isoformat() if dataset.modified else None,
                "location": dataset.location,
                "description": dataset.description,
            }

            # Get table list and sizes
            tables = list(connection.list_tables(dataset))
            table_info = []

            for table in tables:
                table_ref = dataset.table(table.table_id)
                table_obj = connection.get_table(table_ref)

                table_info.append(
                    {
                        "table_id": table.table_id,
                        "num_rows": table_obj.num_rows,
                        "num_bytes": table_obj.num_bytes,
                        "created": table_obj.created.isoformat() if table_obj.created else None,
                        "modified": table_obj.modified.isoformat() if table_obj.modified else None,
                    }
                )

            metadata["tables"] = table_info

            # Get project information
            try:
                # This requires additional permissions
                project = connection.get_project(self.project_id)
                metadata["project_info"] = {
                    "display_name": project.display_name,
                    "project_number": project.project_number,
                }
            except Exception:
                pass  # Skip if no permissions

        except Exception as e:
            metadata["metadata_error"] = str(e)

        return metadata

    def get_query_plan(self, connection: Any, query: str) -> dict[str, Any]:
        """Get query execution plan for analysis."""
        try:
            # Use dry run to get query plan without execution
            job_config = bigquery.QueryJobConfig(dry_run=True)
            # Note: Query dialect translation is now handled automatically by the base adapter
            qualified_query = self._qualify_table_names(query)

            query_job = connection.query(qualified_query, job_config=job_config)

            return {
                "bytes_processed": query_job.total_bytes_processed,
                "estimated_cost": query_job.total_bytes_processed / (1024**4) * 5,  # Rough cost estimate
                "query_plan": "Dry run completed",
                "job_id": query_job.job_id,
            }

        except Exception as e:
            return {"error": str(e)}

    def close_connection(self, connection: Any) -> None:
        """Close BigQuery connection.

        Handles credential refresh errors gracefully during connection cleanup.
        Suppresses all credential-related errors as they are non-fatal during cleanup.
        """
        if not connection:
            return

        try:
            if hasattr(connection, "close"):
                connection.close()
        except Exception as e:
            # Suppress credential refresh errors during cleanup (anonymous credentials, expired tokens, etc.)
            # These are non-fatal - the connection is being closed anyway
            error_msg = str(e).lower()
            if any(keyword in error_msg for keyword in ["credential", "refresh", "anonymous", "auth", "token"]):
                # Silently suppress credential/auth errors during cleanup
                self.log_very_verbose(f"Credential cleanup warning (non-fatal, suppressed): {e}")
            else:
                self.logger.warning(f"Error closing connection: {e}")

        # Also try to clean up any transport/channel resources that might have credential issues
        try:
            if hasattr(connection, "_transport"):
                transport = connection._transport
                if hasattr(transport, "close"):
                    transport.close()
        except Exception:
            # Silently ignore transport cleanup errors
            pass

    _supported_tuning_type_names = ("PARTITIONING", "CLUSTERING")

    def generate_tuning_clause(self, table_tuning) -> str:
        """Generate BigQuery-specific tuning clauses for CREATE TABLE statements.

        BigQuery supports:
        - PARTITION BY DATE(column), DATETIME_TRUNC(column, DAY), column (for date/integer)
        - CLUSTER BY column1, column2, ... (up to 4 columns)

        Args:
            table_tuning: The tuning configuration for the table

        Returns:
            SQL clause string to be appended to CREATE TABLE statement
        """
        if not table_tuning or not table_tuning.has_any_tuning():
            return ""

        clauses = []

        try:
            # Import here to avoid circular imports
            from benchbox.core.tuning.interface import TuningType

            # Handle partitioning
            partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
            if partition_columns:
                # Sort by order and use first column for partitioning
                sorted_cols = sorted(partition_columns, key=lambda col: col.order)
                partition_col = sorted_cols[0]  # BigQuery typically uses single column partitioning

                # Determine partition strategy based on column type
                col_type = partition_col.type.upper()
                if any(date_type in col_type for date_type in ["DATE", "TIMESTAMP", "DATETIME"]):
                    if "DATE" in col_type:
                        partition_clause = f"PARTITION BY {partition_col.name}"
                    else:
                        partition_clause = f"PARTITION BY DATE({partition_col.name})"
                elif "INT" in col_type:
                    # Integer partitioning with range
                    partition_clause = (
                        f"PARTITION BY RANGE_BUCKET({partition_col.name}, GENERATE_ARRAY(0, 1000000, 10000))"
                    )
                else:
                    # Default date-based partitioning
                    partition_clause = f"PARTITION BY DATE({partition_col.name})"

                clauses.append(partition_clause)

            # Handle clustering (up to 4 columns)
            cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
            if cluster_columns:
                # Sort by order and take up to 4 columns
                sorted_cols = sorted(cluster_columns, key=lambda col: col.order)
                cluster_cols = sorted_cols[:4]  # BigQuery limit of 4 clustering columns
                column_names = [col.name for col in cluster_cols]

                cluster_clause = f"CLUSTER BY {', '.join(column_names)}"
                clauses.append(cluster_clause)

            # Distribution and sorting not directly supported in BigQuery CREATE TABLE
            # but handled through partitioning and clustering

        except ImportError:
            # If tuning interface not available, return empty string
            pass

        return " ".join(clauses)

    def apply_table_tunings(self, table_tuning, connection: Any) -> None:
        """Apply tuning configurations to a BigQuery table.

        BigQuery tuning approach:
        - PARTITIONING: Handled in CREATE TABLE via PARTITION BY
        - CLUSTERING: Handled in CREATE TABLE via CLUSTER BY
        - Additional optimization via table options

        Args:
            table_tuning: The tuning configuration to apply
            connection: BigQuery client connection

        Raises:
            ValueError: If the tuning configuration is invalid for BigQuery
        """
        if not table_tuning or not table_tuning.has_any_tuning():
            return

        table_name = table_tuning.table_name
        self.logger.info(f"Applying BigQuery tunings for table: {table_name}")

        try:
            # Import here to avoid circular imports
            from benchbox.core.tuning.interface import TuningType

            # BigQuery tuning is primarily handled at table creation time
            # Post-creation optimizations are limited

            # Get table reference
            dataset_ref = connection.dataset(self.dataset_id)
            table_ref = dataset_ref.table(table_name)

            try:
                table_obj = connection.get_table(table_ref)

                # Log current table configuration
                if table_obj.time_partitioning:
                    self.logger.info(f"Table {table_name} has partitioning: {table_obj.time_partitioning.type_}")

                if table_obj.clustering_fields:
                    self.logger.info(f"Table {table_name} has clustering: {table_obj.clustering_fields}")

                # Check if table needs to be recreated with new tuning
                partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
                cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)

                needs_recreation = False

                # Check if partitioning configuration changed
                if partition_columns and not table_obj.time_partitioning:
                    needs_recreation = True
                    self.logger.info(f"Table {table_name} needs recreation for partitioning")

                # Check if clustering configuration changed
                if cluster_columns:
                    sorted_cols = sorted(cluster_columns, key=lambda col: col.order)
                    desired_clustering = [col.name for col in sorted_cols[:4]]
                    current_clustering = table_obj.clustering_fields or []

                    if desired_clustering != current_clustering:
                        needs_recreation = True
                        self.logger.info(f"Table {table_name} needs recreation for clustering")

                if needs_recreation:
                    self.logger.warning(
                        f"Table {table_name} configuration differs from desired tuning. "
                        "Consider recreating the table with proper tuning configuration."
                    )

            except Exception as e:
                self.logger.warning(f"Could not verify table configuration for {table_name}: {e}")

            # Handle unsupported tuning types
            distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
            if distribution_columns:
                self.logger.warning(f"Distribution tuning not directly supported in BigQuery for table: {table_name}")

            sorting_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
            if sorting_columns:
                # In BigQuery, sorting is achieved through clustering
                sorted_cols = sorted(sorting_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]
                self.logger.info(
                    f"Sorting in BigQuery achieved via clustering for table {table_name}: {', '.join(column_names)}"
                )

        except ImportError:
            self.logger.warning("Tuning interface not available - skipping tuning application")
        except Exception as e:
            raise ValueError(f"Failed to apply tunings to BigQuery table {table_name}: {e}") from e

    def apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None:
        """Apply unified tuning configuration to BigQuery."""
        from benchbox.platforms.base.tuning_config import apply_standard_unified_tuning

        apply_standard_unified_tuning(self, unified_config, connection)

    def apply_platform_optimizations(self, platform_config: PlatformOptimizationConfiguration, connection: Any) -> None:
        """Apply BigQuery-specific platform optimizations.

        Args:
            platform_config: Platform optimization configuration
            connection: BigQuery connection
        """
        if not platform_config:
            return

        # BigQuery optimizations are mostly applied at query/job level
        # Store optimizations for use during query execution
        self.logger.info("BigQuery platform optimizations stored for query execution")

    apply_constraint_configuration = make_informational_constraint_applier(
        "Primary key constraints enabled for BigQuery (applied during table creation)",
        "Foreign key constraints enabled for BigQuery (applied during table creation)",
    )


def _apply_bigquery_config_fields(config: Any) -> None:
    staging_root = config.options.get("staging_root")
    if not staging_root:
        default_output = config.options.get("default_output_location")
        if isinstance(default_output, str) and default_output.startswith("gs://"):
            staging_root = default_output

    storage_bucket = config.options.get("storage_bucket")
    storage_prefix = config.options.get("storage_prefix")
    if staging_root:
        try:
            path_info = get_cloud_path_info(staging_root)
            if path_info and path_info.get("bucket"):
                storage_bucket = path_info["bucket"]
                storage_prefix = path_info.get("path", "")
        except (ValueError, TypeError):
            pass

    config.staging_root = staging_root
    config.storage_bucket = storage_bucket
    config.storage_prefix = storage_prefix


_build_bigquery_config = make_registered_platform_config_builder(
    "bigquery",
    __name__,
    "Google BigQuery",
    "google-cloud-bigquery",
    [
        "project_id",
        "dataset_id",
        "location",
        "credentials_path",
    ],
    postprocess=_apply_bigquery_config_fields,
)
