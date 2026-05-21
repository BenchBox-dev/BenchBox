"""Bundle-based publisher for schema-v2 result artifacts.

Publishes already-exported schema-v2 result bundles (produced by
``benchbox.core.results.exporter``) to a destination, and records
durable publication metadata in the persistent store.

This is the real publishing workflow - it does NOT re-serialize results.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from benchbox.core.results.loader import load_result_file
from benchbox.core.results.status import result_non_clean_reason
from benchbox.validation.bundle import COMPANION_SUFFIXES

from .store import PublicationRecord, PublicationStore, build_reference

logger = logging.getLogger(__name__)

VALID_LABELS = ("maintainer-run", "community-submission", "ci", "local", "unofficial-research")


@dataclass
class BundlePublishResult:
    """Result of publishing a schema-v2 result bundle."""

    success: bool
    record: PublicationRecord | None = None
    reference: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "pub_id": self.record.pub_id if self.record else None,
            "reference": self.reference,
            "errors": self.errors,
        }


class BundlePublisher:
    """Publish schema-v2 result bundles and track publication metadata.

    Operates on existing exported bundle files (`.json`, with optional
    `.plans.json`` and ``.tuning.json`` companions). Does not re-serialize
    results - delegates all format conversion to ``benchbox.core.results.exporter``.

    The destination can be:
    - A local directory path (e.g., ``/home/user/published/``)
    - A cloud URI prefix (e.g., ``s3://my-bucket/benchbox/``)

    The emitted reference is always truthful:
    - Local: ``file:///abs/path/to/bundle.json``
    - Cloud: the full cloud URI (e.g., ``s3://bucket/prefix/bundle.json``)

    Example::

        publisher = BundlePublisher(destination="/tmp/published", store=PublicationStore())
        result = publisher.publish(Path("benchmark_runs/results/tpch_sf1_duckdb.json"))
        print(result.reference)   # file:///tmp/published/tpch_sf1_duckdb.json
    """

    def __init__(
        self,
        destination: str | Path,
        store: PublicationStore | None = None,
        label: str = "maintainer-run",
    ) -> None:
        """Initialize the bundle publisher.

        Args:
            destination: Target directory path or cloud URI prefix.
            store: Persistent publication store. Uses default path if not provided.
            label: Trust label for publications.
        """
        self.destination = str(destination)
        self.store = store or PublicationStore()
        self.label = label if label in VALID_LABELS else "maintainer-run"

    def publish(self, source_bundle: str | Path) -> BundlePublishResult:
        """Publish a schema-v2 result bundle to the configured destination.

        Copies the primary bundle file and any companion files (.plans.json,
        .tuning.json) to the destination, then records a publication entry
        in the persistent store.

        If the same bundle has already been published to this destination,
        the metadata record is updated rather than creating a duplicate.

        Args:
            source_bundle: Path to the primary result .json file.

        Returns:
            BundlePublishResult with success status, pub_id, and reference.
        """
        bundle_path = Path(source_bundle)

        if not bundle_path.exists():
            return BundlePublishResult(
                success=False,
                errors=[f"Source bundle not found: {source_bundle}"],
            )

        if bundle_path.suffix != ".json" or bundle_path.name.endswith((".plans.json", ".tuning.json")):
            return BundlePublishResult(
                success=False,
                errors=[
                    f"Expected a primary .json result bundle, got: {bundle_path.name}. "
                    "Companion files (.plans.json, .tuning.json) are published automatically."
                ],
            )

        validation_errors = _validate_source_bundle_for_publication(bundle_path)
        if validation_errors:
            return BundlePublishResult(success=False, errors=validation_errors)

        # Extract informational metadata from the bundle header
        metadata = _read_bundle_metadata(bundle_path)

        try:
            dest_filename = _copy_bundle(bundle_path, self.destination)
        except Exception as exc:
            return BundlePublishResult(
                success=False,
                errors=[f"Failed to copy bundle to destination: {exc}"],
            )

        reference = build_reference(self.destination, dest_filename)

        try:
            record = self.store.add(
                source_path=bundle_path,
                destination=self.destination,
                reference=reference,
                label=self.label,
                benchmark=metadata.benchmark,
                platform=metadata.platform,
                scale_factor=metadata.scale_factor,
                dataset_version=metadata.dataset_version,
                manifest_hash=metadata.manifest_hash,
                data_archive_hash=metadata.data_archive_hash,
            )
        except Exception as exc:
            return BundlePublishResult(
                success=True,
                reference=reference,
                errors=[f"Bundle published but metadata store update failed: {exc}"],
            )

        return BundlePublishResult(
            success=True,
            record=record,
            reference=reference,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _BundleMetadata:
    benchmark: str
    platform: str
    scale_factor: float
    dataset_version: str | None = None
    manifest_hash: str | None = None
    data_archive_hash: str | None = None


def _validate_source_bundle_for_publication(bundle_path: Path) -> list[str]:
    """Return publication-blocking errors for source bundles that are not clean passes."""
    try:
        result, _data = load_result_file(bundle_path)
    except Exception as exc:
        return [f"Source bundle is not a loadable schema-v2 result bundle: {exc}"]

    reason = result_non_clean_reason(result)
    if reason:
        return [f"Source bundle is not a clean pass: {reason}"]
    return []


def _read_bundle_metadata(bundle_path: Path) -> _BundleMetadata:
    """Read benchmark/platform/scale_factor from a schema-v2 result bundle.

    Returns empty strings / 1.0 on any failure - metadata is informational only.
    """
    try:
        text = bundle_path.read_text(encoding="utf-8")
        data: dict = json.loads(text)
        benchmark_block = data.get("benchmark", {})
        benchmark = benchmark_block.get("id", "") or data.get("benchmark_id", "") or benchmark_block.get("name", "")
        platform = data.get("platform", {}).get("name", "") or data.get("platform", "")
        if isinstance(platform, dict):
            platform = platform.get("name", "")
        raw_sf = data.get("benchmark", {}).get("scale_factor") or data.get("scale_factor") or 1.0
        scale_factor = float(raw_sf) if raw_sf else 1.0
        identity = _read_dataset_identity(str(benchmark))
        return _BundleMetadata(
            benchmark=str(benchmark),
            platform=str(platform),
            scale_factor=scale_factor,
            dataset_version=identity.dataset_version,
            manifest_hash=identity.manifest_hash,
            data_archive_hash=identity.data_archive_hash,
        )
    except Exception:
        return _BundleMetadata("", "", 1.0)


@dataclass(frozen=True)
class _DatasetIdentity:
    dataset_version: str | None
    manifest_hash: str | None
    data_archive_hash: str | None


def _read_dataset_identity(benchmark_id: str) -> _DatasetIdentity:
    """Read benchmark data identity from registry-declared data_manifest."""
    try:
        from benchbox.core.benchmark_registry import get_benchmark_metadata
        from benchbox.core.data_fetch import load_manifest

        meta = get_benchmark_metadata(benchmark_id) or {}
        manifest_rel = meta.get("data_manifest")
        if not manifest_rel:
            return _DatasetIdentity(None, None, None)
        repo_root = Path(__file__).resolve().parents[3]
        manifest = load_manifest(repo_root / str(manifest_rel))
        return _DatasetIdentity(
            dataset_version=manifest.dataset_version,
            manifest_hash=manifest.manifest_hash,
            data_archive_hash=manifest.data_archive_hash,
        )
    except Exception:
        return _DatasetIdentity(None, None, None)


def _copy_bundle(source: Path, destination: str) -> str:
    """Copy bundle and companion files to destination.

    Returns the filename of the primary bundle as copied.
    """
    from benchbox.utils.cloud_storage import is_cloud_path

    filename = source.name
    stem = source.stem  # e.g., "tpch_sf1_duckdb_20260101_120000"
    files_to_copy = [source]
    for suffix in COMPANION_SUFFIXES:
        companion = source.parent / (stem + suffix)
        if companion.exists():
            files_to_copy.append(companion)

    if is_cloud_path(destination):
        _copy_to_cloud(files_to_copy, destination)
    else:
        _copy_to_local(files_to_copy, destination)

    return filename


def _copy_to_local(files: list[Path], destination: str) -> None:
    """Copy files to a local directory."""
    dest_dir = Path(destination)
    dest_dir.mkdir(parents=True, exist_ok=True)
    for file in files:
        shutil.copy2(file, dest_dir / file.name)


def _copy_to_cloud(files: list[Path], destination: str) -> None:
    """Copy files to a cloud storage path using benchbox.utils.cloud_storage."""
    try:
        from benchbox.utils.cloud_storage import create_path_handler
    except ImportError as exc:
        raise RuntimeError("Cloud storage is not available. Install cloudpathlib for cloud support.") from exc

    base = destination.rstrip("/")
    for file in files:
        cloud_path = create_path_handler(f"{base}/{file.name}")
        cloud_path.write_bytes(file.read_bytes())  # type: ignore[attr-defined]
