"""Shared GCS staging-path helper for GCP adapters.

Both Dataproc and Dataproc Serverless adapters accept a
``gcs_staging_dir`` string that must start with ``gs://`` and parse into
(bucket, prefix). The previous implementations were identical line for
line in each adapter's ``__init__`` - this module is the single owner.

Kept narrow: one function, no imports beyond stdlib, so it's cheap to
load at adapter construction time and easy to test in isolation.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root.
"""

from __future__ import annotations

from dataclasses import dataclass

from benchbox.core.exceptions import ConfigurationError


@dataclass(frozen=True)
class GcsStagingPath:
    """Parsed GCS staging path: bucket, prefix, and normalized URI."""

    bucket: str
    prefix: str
    uri: str


def parse_gcs_staging_dir(gcs_staging_dir: str | None) -> GcsStagingPath:
    """Validate and parse a ``gs://bucket[/prefix]`` staging path.

    Raises ConfigurationError with a message shared across GCP adapters;
    both Dataproc flavors used the same wording before this helper
    consolidated them, so the error surface is preserved.

    The returned ``uri`` has any trailing slash trimmed - matching what
    the adapters used to assign to ``self.gcs_staging_dir``.
    """
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
