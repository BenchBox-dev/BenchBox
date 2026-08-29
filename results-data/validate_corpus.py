#!/usr/bin/env python3
"""Validate the seed corpus meets depth and schema requirements.

`SEED_CORPUS_SPEC.md` states the hard requirement this enforces: every
committed cohort must have at least 3 distinct comparison identities. A
one-identity cohort is not a comparison, so publishing it would put a row on
the public leaderboard that nothing can be read against.

Structured into functions so `tests/unit/scripts/test_corpus_cohort_depth.py`
can import and assert the same rule instead of restating it. Before that, the
script ran in no CI lane at all -- every workflow reference to it is a path
list for mirroring -- so a corpus PR could violate the requirement, pass
pr-preflight green, and merge. That is exactly what PR #1854 did.

Kept deliberately stdlib-only and free of `benchbox` imports: this file is
vendored onto the slim `published-results` branch, where the package is not
installed.
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys

#: Companion suffixes that are not primary result bundles.
COMPANION_SUFFIXES = (".manifest.json", ".plans.json", ".tuning.json", ".applied.json")
LEGACY_MANIFEST_NAME = "submission-manifest.json"

#: A cohort below this many distinct comparison identities is not a comparison.
MINIMUM_PLATFORMS_PER_COHORT = 3

CohortKey = tuple[str, str]


class CorpusReadError(Exception):
    """A bundle could not be read or lacks the fields a cohort key needs."""


def discover_bundles(bundles_dir: pathlib.Path) -> list[pathlib.Path]:
    """Primary result bundles under *bundles_dir*, companions excluded."""
    return sorted(
        path
        for path in bundles_dir.rglob("*.json")
        if path.name != LEGACY_MANIFEST_NAME and not path.name.endswith(COMPANION_SUFFIXES)
    )


def cohort_platforms(bundles: list[pathlib.Path]) -> dict[CohortKey, set[str]]:
    """Map a cohort to distinct platform/version comparison identities.

    A version-over-version cohort legitimately repeats one platform name. A
    reported version therefore participates in the identity when available;
    duplicate runs of the same platform at the same version still count once.
    Bundles without version metadata retain the historical platform-only
    identity.

    Raises:
        CorpusReadError: if any bundle is unreadable or missing a key field.
            Fail closed -- an unparseable bundle is exactly the state a
            truncated or unreviewed one would be in, and skipping it would let
            the corpus regress while this gate stayed green.
    """
    cohorts: collections.defaultdict[CohortKey, set[str]] = collections.defaultdict(set)
    for bundle in bundles:
        try:
            with open(bundle, encoding="utf-8") as handle:
                payload = json.load(handle)
            benchmark_id = payload["benchmark"]["id"]
            scale_factor = str(payload["benchmark"].get("scale_factor", ""))
            platform_section = payload["platform"]
            platform = platform_section["name"]
            version = platform_section.get("version") or platform_section.get("client_version")
            if str(platform).lower() == "duckdb":
                execution = payload.get("execution", {})
                if isinstance(execution, dict):
                    for key in (
                        "driver_version_resolved",
                        "driver_version_requested",
                        "driver_resolved_version",
                        "driver_requested_version",
                    ):
                        candidate = execution.get(key)
                        if candidate and str(candidate) != "unknown":
                            version = candidate
                            break
        except Exception as exc:  # noqa: BLE001 - any read failure is fatal here
            raise CorpusReadError(f"ERROR reading {bundle}: {exc}") from exc
        identity = str(platform)
        if version and str(version) != "unknown":
            identity = f"{identity} v{str(version)[:120]}"
        cohorts[(benchmark_id, scale_factor)].add(identity)
    return dict(cohorts)


def shallow_cohorts(cohorts: dict[CohortKey, set[str]]) -> dict[CohortKey, set[str]]:
    """Cohorts with fewer than the required number of platforms."""
    return {key: platforms for key, platforms in cohorts.items() if len(platforms) < MINIMUM_PLATFORMS_PER_COHORT}


def main(bundles_dir: pathlib.Path | None = None) -> int:
    """Print the cohort report and return the process exit code."""
    bundles_dir = bundles_dir or pathlib.Path(__file__).parent / "bundles"
    bundles = discover_bundles(bundles_dir)
    print(f"Found {len(bundles)} bundles")

    try:
        cohorts = cohort_platforms(bundles)
    except CorpusReadError as exc:
        print(exc)
        return 1

    print("\nCohorts:")
    for key, platforms in sorted(cohorts.items()):
        status = "OK" if len(platforms) >= MINIMUM_PLATFORMS_PER_COHORT else "WARN (<3 identities)"
        print(f"  {key[0]} SF={key[1]}: {len(platforms)} identities ({sorted(platforms)}) [{status}]")

    low = shallow_cohorts(cohorts)
    if low:
        print(f"\nWARN: {len(low)} cohort(s) have <3 comparison identities: { {k: len(v) for k, v in low.items()} }")
        return 1

    print(f"\nAll {len(cohorts)} cohort(s) meet the >={MINIMUM_PLATFORMS_PER_COHORT}-identity depth criterion.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
