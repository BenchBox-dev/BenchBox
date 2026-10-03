# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

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


def _default_store_path() -> Path:
    return Path.home() / ".benchbox" / "published.json"


@dataclass
class PublicationRecord:
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

    dataset_version: str | None = None
    """Logical dataset version from the benchmark data manifest, when present."""

    manifest_hash: str | None = None
    """Logical manifest hash from the benchmark data manifest, when present."""

    data_archive_hash: str | None = None
    """Aggregate data archive hash from the benchmark data manifest, when present."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PublicationRecord:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class PublicationStore:
    store_path: Path = field(default_factory=_default_store_path)

    def __post_init__(self) -> None:
        self.store_path = Path(self.store_path)

    def add(
        self,
        source_path: str | Path,
        destination: str,
        reference: str,
        label: str = "maintainer-run",
        benchmark: str = "",
        platform: str = "",
        scale_factor: float = 1.0,
        dataset_version: str | None = None,
        manifest_hash: str | None = None,
        data_archive_hash: str | None = None,
    ) -> PublicationRecord:
        records = self._load()

        source_str = str(Path(source_path).resolve())
        existing = self._find_by_source_and_dest(records, source_str, destination)

        if existing is not None:
            existing.reference = reference
            existing.label = label
            existing.published_at = _now_iso()
            existing.benchmark = benchmark or existing.benchmark
            existing.platform = platform or existing.platform
            existing.scale_factor = scale_factor or existing.scale_factor
            existing.dataset_version = dataset_version if dataset_version is not None else existing.dataset_version
            existing.manifest_hash = manifest_hash if manifest_hash is not None else existing.manifest_hash
            existing.data_archive_hash = (
                data_archive_hash if data_archive_hash is not None else existing.data_archive_hash
            )
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
            dataset_version=dataset_version,
            manifest_hash=manifest_hash,
            data_archive_hash=data_archive_hash,
        )
        records.append(record)
        self._save(records)
        return record

    def list_all(self) -> list[PublicationRecord]:
        records = self._load()
        return sorted(records, key=lambda r: r.published_at, reverse=True)

    def get(self, pub_id: str) -> PublicationRecord | None:
        for record in self._load():
            if record.pub_id == pub_id:
                return record
        return None

    def remove(self, pub_id: str) -> bool:
        records = self._load()
        before = len(records)
        records = [r for r in records if r.pub_id != pub_id]
        if len(records) == before:
            return False
        self._save(records)
        return True

    def _load(self) -> list[PublicationRecord]:
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
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps([r.to_dict() for r in records], indent=2, ensure_ascii=False)
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
    combined = f"{source_path}:{_now_iso()}"
    return hashlib.sha256(combined.encode()).hexdigest()[:12]


def build_reference(destination: str, bundle_filename: str) -> str:
    from benchbox.utils.cloud_storage import is_cloud_path

    if is_cloud_path(destination):
        base = destination.rstrip("/")
        return f"{base}/{bundle_filename}"

    abs_path = Path(destination).resolve() / bundle_filename
    return abs_path.as_uri()
