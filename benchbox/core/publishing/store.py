"""Persistent publication metadata store for BenchBox.

Replaces the in-memory ArtifactManager with a durable JSON-backed store
located at ~/.benchbox/published.json. State survives process restart.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from benchbox.utils.clock import utc_now

logger = logging.getLogger(__name__)


# Default store location: user-level, shared across projects.
# Computed lazily so that tests can override HOME before instantiation.
def _default_store_path() -> Path:
    return Path.home() / ".benchbox" / "published.json"


@dataclass
class PublicationRecord:
    """A single publication entry in the persistent store.

    Each record tracks one publish operation: what was published, where it
    went, and a truthful reference for the backend (file URI or cloud URI).
    """

    pub_id: str
    """Unique publication ID (12-char hex derived from source path + timestamp)."""

    source_path: str
    """Absolute path to the original schema-v2 result bundle (.json file)."""

    destination: str
    """Storage destination: a directory path or cloud URI prefix (s3://, gs://, etc)."""

    reference: str
    """Truthful, durable reference to the published artifact.

    - Local filesystem: file:///abs/path/to/bundle.json
    - Cloud storage: full cloud URI (e.g., s3://bucket/prefix/bundle.json)
    """

    label: str
    """Trust / provenance label (e.g., 'maintainer-run', 'community-submission')."""

    published_at: str
    """ISO-8601 timestamp of the publication."""

    benchmark: str = ""
    """Benchmark name extracted from the result bundle."""

    platform: str = ""
    """Platform name extracted from the result bundle."""

    scale_factor: float = 1.0
    """Scale factor extracted from the result bundle."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PublicationRecord:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class PublicationStore:
    """Durable JSON-backed store for publication metadata.

    Reads and writes ``~/.benchbox/published.json`` atomically. All mutating
    methods flush the file to disk before returning, so state is not lost on
    process exit.

    Usage::

        store = PublicationStore()
        rec = store.add(source_path, destination, reference, label, benchmark, platform, scale_factor)
        store.list_all()       # list[PublicationRecord]
        store.remove(pub_id)   # remove record only (does not delete files)
    """

    store_path: Path = field(default_factory=_default_store_path)

    def __post_init__(self) -> None:
        self.store_path = Path(self.store_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(
        self,
        source_path: str | Path,
        destination: str,
        reference: str,
        label: str = "maintainer-run",
        benchmark: str = "",
        platform: str = "",
        scale_factor: float = 1.0,
    ) -> PublicationRecord:
        """Add or update a publication record.

        If the same ``source_path`` has already been published to the same
        ``destination``, the existing record is updated in place (idempotent).
        Otherwise a new record is created.

        Args:
            source_path: Absolute path to the schema-v2 result bundle.
            destination: Target directory or cloud URI prefix.
            reference: Durable reference URI for the published artifact.
            label: Trust/provenance label.
            benchmark: Benchmark name (informational).
            platform: Platform name (informational).
            scale_factor: Scale factor (informational).

        Returns:
            The created or updated PublicationRecord.
        """
        records = self._load()

        source_str = str(Path(source_path).resolve())
        existing = self._find_by_source_and_dest(records, source_str, destination)

        if existing is not None:
            # Update in place - idempotent republish
            existing.reference = reference
            existing.label = label
            existing.published_at = _now_iso()
            existing.benchmark = benchmark or existing.benchmark
            existing.platform = platform or existing.platform
            existing.scale_factor = scale_factor or existing.scale_factor
            self._save(records)
            return existing

        pub_id = _generate_pub_id(source_str)
        record = PublicationRecord(
            pub_id=pub_id,
            source_path=source_str,
            destination=destination,
            reference=reference,
            label=label,
            published_at=_now_iso(),
            benchmark=benchmark,
            platform=platform,
            scale_factor=scale_factor,
        )
        records.append(record)
        self._save(records)
        return record

    def list_all(self) -> list[PublicationRecord]:
        """Return all publication records, newest first."""
        records = self._load()
        return sorted(records, key=lambda r: r.published_at, reverse=True)

    def get(self, pub_id: str) -> PublicationRecord | None:
        """Return a single record by pub_id, or None if not found."""
        for record in self._load():
            if record.pub_id == pub_id:
                return record
        return None

    def remove(self, pub_id: str) -> bool:
        """Remove a publication record.

        Does NOT delete the underlying artifact files - only removes the
        metadata entry from the store.

        Args:
            pub_id: ID of the record to remove.

        Returns:
            True if the record was found and removed, False otherwise.
        """
        records = self._load()
        before = len(records)
        records = [r for r in records if r.pub_id != pub_id]
        if len(records) == before:
            return False
        self._save(records)
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> list[PublicationRecord]:
        """Load records from disk. Returns empty list if file doesn't exist."""
        if not self.store_path.exists():
            return []
        try:
            text = self.store_path.read_text(encoding="utf-8")
            raw: list[dict[str, Any]] = json.loads(text)
            return [PublicationRecord.from_dict(entry) for entry in raw]
        except Exception as exc:
            logger.warning("Could not load publication store %s: %s", self.store_path, exc)
            return []

    def _save(self, records: list[PublicationRecord]) -> None:
        """Atomically save records to disk."""
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps([r.to_dict() for r in records], indent=2, ensure_ascii=False)
        # Write to a temp file then rename for atomicity
        tmp_path = self.store_path.with_suffix(".json.tmp")
        try:
            tmp_path.write_text(payload, encoding="utf-8")
            shutil.move(tmp_path, self.store_path)
        except Exception as exc:
            logger.error("Failed to save publication store: %s", exc)
            tmp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _find_by_source_and_dest(
        records: list[PublicationRecord], source_path: str, destination: str
    ) -> PublicationRecord | None:
        for record in records:
            if record.source_path == source_path and record.destination == destination:
                return record
        return None


def _now_iso() -> str:
    return utc_now().isoformat()


def _generate_pub_id(source_path: str) -> str:
    """Generate a 12-char hex publication ID from source path + current time."""
    combined = f"{source_path}:{_now_iso()}"
    return hashlib.sha256(combined.encode()).hexdigest()[:12]


def build_reference(destination: str, bundle_filename: str) -> str:
    """Build a truthful, durable reference for the published artifact.

    Args:
        destination: The storage destination (local path or cloud URI).
        bundle_filename: The filename of the published bundle.

    Returns:
        - Local path: ``file:///abs/path/to/bundle.json``
        - Cloud URI (s3://, gs://, abfss://, dbfs://): full cloud URI
    """
    from benchbox.utils.cloud_storage import is_cloud_path

    if is_cloud_path(destination):
        # Cloud URI: strip trailing slash and append filename
        base = destination.rstrip("/")
        return f"{base}/{bundle_filename}"

    # Local filesystem: produce a file:// URI
    abs_path = Path(destination).resolve() / bundle_filename
    return abs_path.as_uri()
