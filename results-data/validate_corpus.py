#!/usr/bin/env python3

from __future__ import annotations

import collections
import datetime as _dt
import json
import pathlib
import re
import sys
from typing import NamedTuple

COMPANION_SUFFIXES = (".manifest.json", ".plans.json", ".tuning.json", ".applied.json", ".override.json")
LEGACY_MANIFEST_NAME = "submission-manifest.json"

MINIMUM_PLATFORMS_PER_COHORT = 3
UTC = _dt.timezone.utc
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
TIMESTAMP_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})?$")

CohortKey = tuple[str, str]


class CorpusReadError(Exception):
    pass


class RecencyStats(NamedTuple):
    oldest: _dt.date
    newest: _dt.date
    oldest_age_days: int
    newest_age_days: int
    bundle_count: int


def discover_bundles(bundles_dir: pathlib.Path) -> list[pathlib.Path]:
    return sorted(
        path
        for path in bundles_dir.rglob("*.json")
        if path.name != LEGACY_MANIFEST_NAME and not path.name.endswith(COMPANION_SUFFIXES)
    )


def _load_bundle(bundle: pathlib.Path) -> dict:
    try:
        with open(bundle, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        raise CorpusReadError(f"ERROR reading {bundle}: {exc}") from exc


def _cohort_key(payload: dict) -> CohortKey:
    try:
        benchmark_id = payload["benchmark"]["id"]
        scale_factor = str(payload["benchmark"].get("scale_factor", ""))
    except Exception as exc:
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
    except Exception as exc:
        raise CorpusReadError(f"ERROR reading platform identity from {bundle}: {exc}") from exc
    identity = str(platform)
    if version and str(version) != "unknown":
        identity = f"{identity} v{str(version)[:120]}"
    return identity


def parse_run_date(payload: dict, *, bundle: pathlib.Path | None = None) -> _dt.date:
    label = f" in {bundle}" if bundle is not None else ""
    try:
        timestamp = payload["run"]["timestamp"]
    except Exception as exc:
        raise CorpusReadError(f"ERROR missing run.timestamp{label}: {exc}") from exc
    if not isinstance(timestamp, str):
        raise CorpusReadError(f"ERROR unparseable run.timestamp{label}: {timestamp!r}")

    if DATE_RE.fullmatch(timestamp):
        try:
            return _dt.date.fromisoformat(timestamp)
        except ValueError as exc:
            raise CorpusReadError(f"ERROR unparseable run.timestamp{label}: {timestamp!r}") from exc

    if not TIMESTAMP_RE.fullmatch(timestamp):
        raise CorpusReadError(f"ERROR unparseable run.timestamp{label}: {timestamp!r}")
    try:
        parsed = _dt.datetime.fromisoformat(f"{timestamp[:-1]}+00:00" if timestamp.endswith("Z") else timestamp)
    except ValueError as exc:
        raise CorpusReadError(f"ERROR unparseable run.timestamp{label}: {timestamp!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).date()


def utc_today() -> _dt.date:
    return _dt.datetime.now(UTC).date()


def age_days(run_date: _dt.date, *, as_of: _dt.date | None = None) -> int:
    as_of = as_of or utc_today()
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
    as_of = as_of or utc_today()
    by_cohort: collections.defaultdict[CohortKey, list[_dt.date]] = collections.defaultdict(list)
    all_dates: list[_dt.date] = []
    warnings: list[str] = []
    for bundle in bundles:
        payload = _load_bundle(bundle)
        try:
            run_date = parse_run_date(payload, bundle=bundle)
        except CorpusReadError as exc:
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
    lines = [
        "Recency (from run.timestamp; informational only — age does not fail "
        "the depth gate and does not affect ranking eligibility):",
        f"  as_of={as_of.isoformat()}",
    ]
    if overall is None:
        lines.append("  Overall: no parseable run timestamps")
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
    return {key: platforms for key, platforms in cohorts.items() if len(platforms) < MINIMUM_PLATFORMS_PER_COHORT}


def main(bundles_dir: pathlib.Path | None = None, *, as_of: _dt.date | None = None) -> int:
    bundles_dir = bundles_dir or pathlib.Path(__file__).parent / "bundles"
    as_of = as_of or utc_today()
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

    try:
        overall, per_cohort, recency_warnings = cohort_recency(bundles, as_of=as_of)
    except CorpusReadError as exc:
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
