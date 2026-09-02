#!/usr/bin/env python3
"""Compare-And-Swap (CAS) controller logic and manifest promotion lifecycle (A3 w3).

Implements atomic promotion validation against publication head, stale-PR
detection, value-only vs control-plane change classification, and
descendant-aware corpus coalescing.
"""

from __future__ import annotations

from dataclasses import replace

from scripts.publication.manifest import (
    PublicationManifest,
    validate_manifest_dict,
)

# Files outside of publication manifest that constitute control-plane changes
CONTROL_PLANE_PREFIXES = (
    ".github/",
    "publication/control/",
    "scripts/publication/",
    "tests/unit/scripts/publication/",
)


class CASTransitionError(Exception):
    """Raised when a proposed manifest fails CAS atomic promotion checks."""


class CASController:
    """Controller enforcing CAS invariants on publication manifest transitions."""

    @staticmethod
    def validate_transition(
        current_manifest: PublicationManifest | None,
        proposed_manifest: PublicationManifest,
        expected_parent_sha: str | None = None,
    ) -> list[str]:
        """Validate whether proposed_manifest can be atomically applied on current_manifest.

        Returns a list of violation error strings (empty list means valid).
        """
        errors: list[str] = []

        # Validate internal manifest consistency first
        internal_errors = validate_manifest_dict(proposed_manifest.to_dict())
        if internal_errors:
            errors.extend(internal_errors)
            return errors

        # Genesis promotion (no current manifest exists)
        if current_manifest is None:
            if proposed_manifest.generation != 1:
                errors.append(f"Genesis manifest must have generation=1, got {proposed_manifest.generation}")
            if proposed_manifest.parent_sha is not None:
                errors.append(f"Genesis manifest must have parent_sha=None, got {proposed_manifest.parent_sha}")
            if proposed_manifest.parent_generation is not None:
                errors.append(
                    f"Genesis manifest must have parent_generation=None, got {proposed_manifest.parent_generation}"
                )
            return errors

        # Non-genesis transition checks
        expected_gen = current_manifest.generation + 1
        if proposed_manifest.generation != expected_gen:
            errors.append(
                f"CAS generation violation: proposed generation is {proposed_manifest.generation}, "
                f"expected monotonic successor {expected_gen} (current generation: {current_manifest.generation})"
            )

        if proposed_manifest.parent_generation != current_manifest.generation:
            errors.append(
                f"CAS parent_generation violation: proposed parent_generation is {proposed_manifest.parent_generation}, "
                f"expected {current_manifest.generation}"
            )

        if expected_parent_sha is not None and proposed_manifest.parent_sha != expected_parent_sha:
            errors.append(
                f"CAS parent_sha violation: proposed parent_sha '{proposed_manifest.parent_sha}' "
                f"does not match publication HEAD SHA '{expected_parent_sha}' (stale promotion / concurrent update race)"
            )

        return errors

    @staticmethod
    def is_value_only_diff(
        old_manifest: PublicationManifest,
        new_manifest: PublicationManifest,
        changed_paths: list[str],
    ) -> bool:
        """Determine if a proposed promotion is a safe, value-only manifest change.

        A change is value-only if and only if:
        1. Only `publication/manifest.json` (or similar manifest path) is modified in changed_paths.
        2. No workflow, script, CODEOWNERS, or control files are touched.
        3. The manifest schema version remains unchanged.
        """
        for p in changed_paths:
            normalized = p.replace("\\", "/")
            if any(normalized.startswith(prefix) for prefix in CONTROL_PLANE_PREFIXES):
                return False
            if normalized not in ("publication/manifest.json", "publication/desired_state.json"):
                return False

        # Schema version must match exactly
        if old_manifest.schema_version != new_manifest.schema_version:
            return False

        return True

    @staticmethod
    def regenerate_stale_manifest(
        stale_manifest: PublicationManifest,
        current_head_manifest: PublicationManifest,
        current_head_sha: str,
    ) -> PublicationManifest:
        """Rebind a stale proposed manifest onto the new current publication state.

        Updates parent_sha, parent_generation, and advances generation monotonically.
        """
        return replace(
            stale_manifest,
            generation=current_head_manifest.generation + 1,
            parent_sha=current_head_sha,
            parent_generation=current_head_manifest.generation,
        )

    @staticmethod
    def coalesce_corpus_promotions(
        base_manifest: PublicationManifest,
        base_sha: str,
        promotions: list[PublicationManifest],
    ) -> PublicationManifest:
        """Coalesce multiple sequential corpus updates into a single atomic promotion.

        Combines the newest artifact digests and bundle counts while binding to base_manifest.
        """
        if not promotions:
            return base_manifest

        latest = promotions[-1]
        return replace(
            latest,
            generation=base_manifest.generation + 1,
            parent_sha=base_sha,
            parent_generation=base_manifest.generation,
        )
