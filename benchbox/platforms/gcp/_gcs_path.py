# Copyright 2026 Joe Harris / BenchBox Project
# Licensed under the MIT License. See LICENSE file in the project root.

from __future__ import annotations

from dataclasses import dataclass

from benchbox.core.exceptions import ConfigurationError


@dataclass(frozen=True)
class GcsStagingPath:
    bucket: str
    prefix: str
    uri: str


def parse_gcs_staging_dir(gcs_staging_dir: str | None) -> GcsStagingPath:
    if not gcs_staging_dir:
        raise ConfigurationError("gcs_staging_dir is required (e.g., gs://bucket/path)")
    if not gcs_staging_dir.startswith("gs://"):
        raise ConfigurationError(f"Invalid GCS path: {gcs_staging_dir}. Must start with gs://")
    parts = gcs_staging_dir[len("gs://") :].split("/", 1)
    bucket = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""
    return GcsStagingPath(
        bucket=bucket,
        prefix=prefix,
        uri=gcs_staging_dir.rstrip("/"),
    )
