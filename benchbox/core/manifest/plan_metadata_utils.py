from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from benchbox.core.manifest.models import (
    PLAN_FINGERPRINT_SCHEME_LITERAL,
    PLAN_FINGERPRINT_SCHEME_NORMALIZED,
    PlanMetadata,
)
from benchbox.core.results.loader import iter_query_results


class PlanFingerprintSchemeMismatchError(ValueError):
    pass


def create_plan_metadata_from_results(
    results: Any,
    platform: str | None = None,
    platform_version: str | None = None,
    normalize_literals: bool = False,
) -> PlanMetadata:
    metadata = PlanMetadata(
        platform=platform or getattr(results, "platform", None),
        platform_version=platform_version or getattr(results, "platform_version", None),
        normalization_scheme=PLAN_FINGERPRINT_SCHEME_NORMALIZED
        if normalize_literals
        else PLAN_FINGERPRINT_SCHEME_LITERAL,
    )

    timestamp = datetime.now(timezone.utc).isoformat()

    attr = "normalized_fingerprint" if normalize_literals else "plan_fingerprint"
    for execution in iter_query_results(results):
        plan = execution.get("query_plan")
        fingerprint = getattr(plan, attr, None) if plan is not None else None
        if fingerprint:
            query_id = execution.get("query_id")
            if query_id not in metadata.plan_fingerprints:
                metadata.plan_fingerprints[query_id] = fingerprint
                metadata.plan_capture_timestamp[query_id] = timestamp
                metadata.plan_versions[query_id] = 1
                metadata.plan_fingerprint_versions[query_id] = getattr(plan, "fingerprint_version", 1)

    return metadata


def _require_matching_scheme(a: PlanMetadata, b: PlanMetadata, *, operation: str) -> None:
    if not a.plan_fingerprints or not b.plan_fingerprints:
        return
    if a.normalization_scheme != b.normalization_scheme:
        raise PlanFingerprintSchemeMismatchError(
            f"Cannot {operation} PlanMetadata recorded under different normalization "
            f"schemes ({a.normalization_scheme!r} vs {b.normalization_scheme!r}). "
            "Fingerprints from a literal-sensitive run and a literal-normalized run "
            "are not comparable - re-record both under the same normalize_literals "
            "setting."
        )


def update_plan_versions(
    prev_metadata: PlanMetadata | None,
    current_metadata: PlanMetadata,
) -> None:
    if not prev_metadata:
        for query_id in current_metadata.plan_fingerprints:
            current_metadata.plan_versions[query_id] = 1
        return

    _require_matching_scheme(prev_metadata, current_metadata, operation="diff")

    for query_id, current_fp in current_metadata.plan_fingerprints.items():
        if query_id not in prev_metadata.plan_fingerprints:
            current_metadata.plan_versions[query_id] = 1
            continue

        prev_fp = prev_metadata.plan_fingerprints[query_id]
        prev_version = prev_metadata.plan_versions.get(query_id, 1)
        prev_fp_version = prev_metadata.plan_fingerprint_versions.get(query_id, 1)
        current_fp_version = current_metadata.plan_fingerprint_versions.get(query_id, 1)

        if prev_fp_version != current_fp_version or prev_fp == current_fp:
            current_metadata.plan_versions[query_id] = prev_version
        else:
            current_metadata.plan_versions[query_id] = prev_version + 1


def validate_plan_metadata(metadata: PlanMetadata) -> list[str]:
    errors = []

    sha256_pattern = re.compile(r"^[a-f0-9]{64}$")
    for query_id, fp in metadata.plan_fingerprints.items():
        if not sha256_pattern.match(fp):
            errors.append(f"Invalid fingerprint for {query_id}: {fp[:20]}...")

    for query_id, version in metadata.plan_versions.items():
        if version < 1:
            errors.append(f"Invalid version for {query_id}: {version}")

    fp_keys = set(metadata.plan_fingerprints.keys())
    version_keys = set(metadata.plan_versions.keys())
    if fp_keys != version_keys:
        missing_versions = fp_keys - version_keys
        missing_fingerprints = version_keys - fp_keys
        if missing_versions:
            errors.append(f"Missing versions for queries: {sorted(missing_versions)}")
        if missing_fingerprints:
            errors.append(f"Missing fingerprints for queries: {sorted(missing_fingerprints)}")

    return errors


def merge_plan_metadata(
    base: PlanMetadata,
    overlay: PlanMetadata,
) -> PlanMetadata:
    _require_matching_scheme(base, overlay, operation="merge")

    merged = PlanMetadata(
        plan_fingerprints={**base.plan_fingerprints, **overlay.plan_fingerprints},
        plan_versions={**base.plan_versions, **overlay.plan_versions},
        plan_capture_timestamp={**base.plan_capture_timestamp, **overlay.plan_capture_timestamp},
        platform=overlay.platform or base.platform,
        platform_version=overlay.platform_version or base.platform_version,
        normalization_scheme=overlay.normalization_scheme if overlay.plan_fingerprints else base.normalization_scheme,
        plan_fingerprint_versions={**base.plan_fingerprint_versions, **overlay.plan_fingerprint_versions},
    )
    return merged
