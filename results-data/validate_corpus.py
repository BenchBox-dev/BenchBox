#!/usr/bin/env python3
"""Validate the seed corpus meets depth and schema requirements.

`SEED_CORPUS_SPEC.md` states the hard requirement this enforces: every
committed cohort must have at least 3 distinct comparison identities. A
one-identity cohort is not a comparison, so publishing it would put a row on
the public leaderboard that nothing can be read against.

This script also prints a recency/staleness report derived from each bundle's
``run.timestamp``. Age is informational only: it never fails the depth gate and
never implies ranking exclusion or automatic withdrawal.

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
import datetime as _dt
import json
import pathlib
import sys
from typing import NamedTuple

#: Companion suffixes that are not primary result bundles.
COMPANION_SUFFIXES = (".manifest.json", ".plans.json", ".tuning.json", ".applied.json")
LEGACY_MANIFEST_NAME = "submission-manifest.json"

#: A cohort below this many distinct comparison identities is not a comparison.
MINIMUM_PLATFORMS_PER_COHORT = 3

CohortKey = tuple[str, str]


class CorpusReadError(Exception):
    """A bundle could not be read or lacks the fields a cohort key needs."""


class RecencyStats(NamedTuple):
    """Oldest/newest run dates and ages for one cohort or the whole corpus."""

    oldest: _dt.date
    newest: _dt.date
    oldest_age_days: int
    newest_age_days: int
    bundle_count: int


def discover_bundles(bundles_dir: pathlib.Path) -> list[pathlib.Path]:
    """Primary result bundles under *bundles_dir*, companions excluded."""
    return sorted(
        path
        for path in bundles_dir.rglob("*.json")
        if path.name != LEGACY_MANIFEST_NAME and not path.name.endswith(COMPANION_SUFFIXES)
    )


def _load_bundle(bundle: pathlib.Path) -> dict:
    """Read one primary bundle; any failure is fatal for corpus gates."""
    try:
        with open(bundle, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:  # noqa: BLE001 - any read failure is fatal here
        raise CorpusReadError(f"ERROR reading {bundle}: {exc}") from exc


def _cohort_key(payload: dict) -> CohortKey:
    try:
        benchmark_id = payload["benchmark"]["id"]
        scale_factor = str(payload["benchmark"].get("scale_factor", ""))
    except Exception as exc:  # noqa: BLE001
        raise CorpusReadError(f"ERROR missing cohort fields: {exc}") from exc
    return (benchmark_id, scale_factor)


def _comparison_identity(bundle: pathlib.Path, payload: dict) -> str:
    try:
        platform_section = payload["platform"]
        platform = platform_section["name"]
        version = None
        if bundle.parent.name == "duckdb-version-matrix":
            version = platform_section.get("version") or platform_section.get("client_version")
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
    except Exception as exc:  # noqa: BLE001
        raise CorpusReadError(f"ERROR reading platform identity from {bundle}: {exc}") from exc
    identity = str(platform)
    if version and str(version) != "unknown":
        identity = f"{identity} v{str(version)[:120]}"
    return identity


def parse_run_date(payload: dict, *, bundle: pathlib.Path | None = None) -> _dt.date:
    """Extract the calendar run date from ``run.timestamp``.

    Accepts ISO-8601 prefixes (``YYYY-MM-DD``) as written by BenchBox exporters.
    Missing or unparseable timestamps raise ``CorpusReadError``; callers that
    treat age as informational (``cohort_recency``) must catch and omit rather
    than fail the depth gate.
    """
    label = f" in {bundle}" if bundle is not None else ""
    try:
        timestamp = payload["run"]["timestamp"]
    except Exception as exc:  # noqa: BLE001
        raise CorpusReadError(f"ERROR missing run.timestamp{label}: {exc}") from exc
    if not isinstance(timestamp, str) or len(timestamp) < 10:
        raise CorpusReadError(f"ERROR unparseable run.timestamp{label}: {timestamp!r}")
    try:
        return _dt.date.fromisoformat(timestamp[:10])
    except ValueError as exc:
        raise CorpusReadError(f"ERROR unparseable run.timestamp{label}: {timestamp!r}") from exc


def age_days(run_date: _dt.date, *, as_of: _dt.date | None = None) -> int:
    """Whole days between *run_date* and *as_of* (default: today, local).

    Informational only. Age does not fail the depth gate and does not affect
    ranking eligibility (see ``ranking_exclusion_reason`` in explorer_pipeline).
    """
    as_of = as_of or _dt.date.today()
    return (as_of - run_date).days


def _stats_from_dates(dates: list[_dt.date], *, as_of: _dt.date) -> RecencyStats:
    oldest = min(dates)
    newest = max(dates)
    return RecencyStats(
        oldest=oldest,
        newest=newest,
        oldest_age_days=age_days(oldest, as_of=as_of),
        newest_age_days=age_days(newest, as_of=as_of),
        bundle_count=len(dates),
    )


def cohort_platforms(bundles: list[pathlib.Path]) -> dict[CohortKey, set[str]]:
    """Map a cohort to distinct platform/version comparison identities.

    An explicitly segregated version-over-version corpus legitimately repeats
    one platform name. Only bundles under ``duckdb-version-matrix/`` therefore
    include a reported version in their identity. Ordinary cohorts retain the
    historical platform-only identity so three versions of one engine cannot
    weaken the cross-platform admission floor.

    Raises:
        CorpusReadError: if any bundle is unreadable or missing a key field.
            Fail closed -- an unparseable bundle is exactly the state a
            truncated or unreviewed one would be in, and skipping it would let
            the corpus regress while this gate stayed green.
    """
    cohorts: collections.defaultdict[CohortKey, set[str]] = collections.defaultdict(set)
    for bundle in bundles:
        payload = _load_bundle(bundle)
        cohorts[_cohort_key(payload)].add(_comparison_identity(bundle, payload))
    return dict(cohorts)


def cohort_recency(
    bundles: list[pathlib.Path],
    *,
    as_of: _dt.date | None = None,
) -> tuple[RecencyStats | None, dict[CohortKey, RecencyStats], list[str]]:
    """Per-cohort and overall oldest/newest run ages from bundle timestamps.

    Returns ``(overall, per_cohort, warnings)``. *overall* is ``None`` when no
    parseable timestamps remain. Bundles with a missing or unparseable
    ``run.timestamp`` are omitted from the report and listed in *warnings*.
    Age never participates in the depth-gate exit code.
    """
    as_of = as_of or _dt.date.today()
    by_cohort: collections.defaultdict[CohortKey, list[_dt.date]] = collections.defaultdict(list)
    all_dates: list[_dt.date] = []
    warnings: list[str] = []
    for bundle in bundles:
        payload = _load_bundle(bundle)
        try:
            run_date = parse_run_date(payload, bundle=bundle)
        except CorpusReadError as exc:
            # Age is informational: omit, warn, and leave the depth exit alone.
            warnings.append(str(exc).replace("ERROR", "WARN", 1))
            continue
        key = _cohort_key(payload)
        by_cohort[key].append(run_date)
        all_dates.append(run_date)
    per_cohort = {key: _stats_from_dates(dates, as_of=as_of) for key, dates in by_cohort.items()}
    overall = _stats_from_dates(all_dates, as_of=as_of) if all_dates else None
    return overall, per_cohort, warnings


def format_recency_report(
    overall: RecencyStats | None,
    per_cohort: dict[CohortKey, RecencyStats],
    *,
    as_of: _dt.date,
) -> str:
    """Human-readable recency report; does not encode a pass/fail decision."""
    lines = [
        "Recency (from run.timestamp; informational only — age does not fail "
        "the depth gate and does not affect ranking eligibility):",
        f"  as_of={as_of.isoformat()}",
    ]
    if overall is None:
        lines.append("  Overall: no bundles")
        return "\n".join(lines)
    lines.append(
        "  Overall: "
        f"oldest={overall.oldest.isoformat()} ({overall.oldest_age_days} days), "
        f"newest={overall.newest.isoformat()} ({overall.newest_age_days} days), "
        f"{overall.bundle_count} bundles"
    )
    lines.append("  Cohorts:")
    for key, stats in sorted(per_cohort.items()):
        lines.append(
            f"    {key[0]} SF={key[1]}: "
            f"oldest={stats.oldest.isoformat()} ({stats.oldest_age_days} days), "
            f"newest={stats.newest.isoformat()} ({stats.newest_age_days} days), "
            f"{stats.bundle_count} bundles"
        )
    return "\n".join(lines)


def shallow_cohorts(cohorts: dict[CohortKey, set[str]]) -> dict[CohortKey, set[str]]:
    """Cohorts with fewer than the required number of platforms."""
    return {key: platforms for key, platforms in cohorts.items() if len(platforms) < MINIMUM_PLATFORMS_PER_COHORT}


def main(bundles_dir: pathlib.Path | None = None, *, as_of: _dt.date | None = None) -> int:
    """Print the cohort and recency reports; exit code reflects depth only."""
    bundles_dir = bundles_dir or pathlib.Path(__file__).parent / "bundles"
    as_of = as_of or _dt.date.today()
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

    # Recency is informational: timestamp parse failures warn and omit, and
    # never override the depth exit code computed below.
    try:
        overall, per_cohort, recency_warnings = cohort_recency(bundles, as_of=as_of)
    except CorpusReadError as exc:
        # Unreadable payload after a successful depth pass is unexpected; warn
        # and continue with an empty recency report rather than flipping depth.
        print(f"WARN recency skipped: {exc}")
        overall, per_cohort, recency_warnings = None, {}, []
    for warning in recency_warnings:
        print(warning)

    print()
    print(format_recency_report(overall, per_cohort, as_of=as_of))

    low = shallow_cohorts(cohorts)
    if low:
        print(f"\nWARN: {len(low)} cohort(s) have <3 comparison identities: { {k: len(v) for k, v in low.items()} }")
        return 1

    print(f"\nAll {len(cohorts)} cohort(s) meet the >={MINIMUM_PLATFORMS_PER_COHORT}-identity depth criterion.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
