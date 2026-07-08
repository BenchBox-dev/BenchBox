"""Utilities for plan metadata management."""

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
    """Raised when comparing/merging PlanMetadata recorded under different
    normalization_scheme values (literal-sensitive vs literal-normalized).

    A fingerprint recorded under one scheme is not comparable to one recorded
    under the other - they hash different input (raw vs literal-masked plan
    text) for the same logical plan, so a naive diff reports every query as
    "changed" (update_plan_versions) or silently keeps whichever side happened
    to write last (merge_plan_metadata), neither of which is a real signal.
    """


def create_plan_metadata_from_results(
    results: Any,  # BenchmarkResults
    platform: str | None = None,
    platform_version: str | None = None,
    normalize_literals: bool = False,
) -> PlanMetadata:
    """
    Create plan metadata from benchmark results.

    Extracts plan fingerprints from query executions and creates timestamps.

    Args:
        results: BenchmarkResults instance with query plans
        platform: Platform name (defaults to results.platform)
        platform_version: Platform version (defaults to results.platform_version)
        normalize_literals: When True, record each query's literal-normalized
            fingerprint (``QueryPlanDAG.normalized_fingerprint``) instead of the
            default literal-sensitive ``plan_fingerprint``. Use this when comparing
            runs that may use different benchmark seeds: structurally identical plans
            then share a fingerprint even when their filter literals differ. Default
            False preserves the existing literal-sensitive behaviour. The returned
            metadata's ``normalization_scheme`` records which mode was used, so
            ``update_plan_versions``/``merge_plan_metadata`` can refuse to compare
            metadata recorded under different modes.

    Returns:
        PlanMetadata with fingerprints and timestamps
    """
    metadata = PlanMetadata(
        platform=platform or getattr(results, "platform", None),
        platform_version=platform_version or getattr(results, "platform_version", None),
        normalization_scheme=PLAN_FINGERPRINT_SCHEME_NORMALIZED
        if normalize_literals
        else PLAN_FINGERPRINT_SCHEME_LITERAL,
    )

    timestamp = datetime.now(timezone.utc).isoformat()

    # Extract fingerprints from all phase results. When normalize_literals is set we
    # read the literal-normalized fingerprint and never fall back to the
    # literal-sensitive one — silently mixing the two would defeat the seed-stable
    # comparison this option exists for (a plan lacking the normalized property is
    # skipped rather than recorded under the wrong scheme).
    attr = "normalized_fingerprint" if normalize_literals else "plan_fingerprint"
    for execution in iter_query_results(results):
        plan = execution.get("query_plan")
        fingerprint = getattr(plan, attr, None) if plan is not None else None
        if fingerprint:
            query_id = execution.get("query_id")
            if query_id not in metadata.plan_fingerprints:
                metadata.plan_fingerprints[query_id] = fingerprint
                metadata.plan_capture_timestamp[query_id] = timestamp
                metadata.plan_versions[query_id] = 1  # Default to version 1
                metadata.plan_fingerprint_versions[query_id] = getattr(plan, "fingerprint_version", 1)

    return metadata


def _require_matching_scheme(a: PlanMetadata, b: PlanMetadata, *, operation: str) -> None:
    """Raise if ``a`` and ``b`` were recorded under different fingerprint schemes.

    Skipped when either side has no recorded fingerprints yet (a fresh/empty
    accumulator's default scheme shouldn't block combining it with real data).
    """
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
    """
    Update plan versions based on fingerprint changes.

    Increments version number when fingerprint changes from previous run.

    Args:
        prev_metadata: Previous run's plan metadata (None for first run)
        current_metadata: Current run's plan metadata to update

    Raises:
        PlanFingerprintSchemeMismatchError: if ``prev_metadata`` and
            ``current_metadata`` were recorded under different
            ``normalization_scheme`` values (both non-empty) - their
            fingerprints are not comparable, so diffing them would report every
            query as "changed" regardless of whether the plan actually did.
    """
    if not prev_metadata:
        # First run: all versions = 1
        for query_id in current_metadata.plan_fingerprints:
            current_metadata.plan_versions[query_id] = 1
        return

    _require_matching_scheme(prev_metadata, current_metadata, operation="diff")

    for query_id, current_fp in current_metadata.plan_fingerprints.items():
        prev_fp = prev_metadata.plan_fingerprints.get(query_id)
        prev_version = prev_metadata.plan_versions.get(query_id, 0)
        # Legacy metadata predating plan_fingerprint_versions defaults to 1
        # (LEGACY_FINGERPRINT_VERSION), matching QueryPlanDAG.from_dict's own
        # legacy-bundle default.
        prev_fp_version = prev_metadata.plan_fingerprint_versions.get(query_id, 1)
        current_fp_version = current_metadata.plan_fingerprint_versions.get(query_id, 1)

        if prev_fp_version != current_fp_version:
            # Not comparable across fingerprint encoding versions (qpc-03
            # anti-pattern): a v1->v2 encoding bump makes every fingerprint
            # string change even for an unchanged plan. Without the full plan
            # tree here (only the fingerprint string is persisted), we cannot
            # verify equality, so preserve the previous version rather than
            # recording a spurious "changed" event.
            current_metadata.plan_versions[query_id] = prev_version
        elif prev_fp == current_fp:
            # Unchanged
            current_metadata.plan_versions[query_id] = prev_version
        else:
            # Changed - increment version
            current_metadata.plan_versions[query_id] = prev_version + 1


def validate_plan_metadata(metadata: PlanMetadata) -> list[str]:
    """
    Validate plan metadata completeness and correctness.

    Args:
        metadata: PlanMetadata instance to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    # Check fingerprints are valid SHA256
    sha256_pattern = re.compile(r"^[a-f0-9]{64}$")
    for query_id, fp in metadata.plan_fingerprints.items():
        if not sha256_pattern.match(fp):
            errors.append(f"Invalid fingerprint for {query_id}: {fp[:20]}...")

    # Check versions are positive
    for query_id, version in metadata.plan_versions.items():
        if version < 1:
            errors.append(f"Invalid version for {query_id}: {version}")

    # Check fingerprints and versions are aligned
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
    """
    Merge two plan metadata objects.

    Overlay values take precedence over base values for same query IDs.

    Args:
        base: Base plan metadata
        overlay: Overlay plan metadata (takes precedence)

    Returns:
        New PlanMetadata with merged values

    Raises:
        PlanFingerprintSchemeMismatchError: if ``base`` and ``overlay`` were
            recorded under different ``normalization_scheme`` values (both
            non-empty) - merging would silently mix the two schemes under
            whichever ``normalization_scheme`` value happens to win below.
    """
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
